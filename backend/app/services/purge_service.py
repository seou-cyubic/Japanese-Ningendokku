"""검진 시각이 지난 예약의 자동 삭제.

규칙
----
    검진 시각 + 유예 시간(기본 60분) 이 지나면 예약 기록을 **삭제**한다.
    예)  8월 7일 09:00~09:30 예약  →  8월 7일 10:00 에 삭제

취소된 예약도 같은 기준으로 삭제한다. 검진일이 지나면 취소 여부와 관계없이
그 예약을 참조할 일이 없기 때문이다.

왜 「삭제」인가
--------------
plan.md BR-15 는 데이터를 영구 보존하도록 되어 있고, 자체 피드백 M-8 은
예약의 물리 삭제를 금지하고 있다. 이번 사양은 그 두 가지를 뒤집는
**명시적 지시**이므로 그대로 따르되, 다음 두 가지를 함께 둔다.

  1. 삭제 건수를 조작 로그(`audit_logs`)에 `RESERVATION_PURGE` 로 남긴다.
     레코드 자체는 사라져도 「언제 몇 건이 정리되었는가」는 추적할 수 있다.
  2. 유예 시간과 실행 주기를 설정값으로 뺐다(`.env`).
     보존이 필요해지면 주기를 0 으로 두어 자동 실행만 끌 수 있다.

`slots.reserved_count` 는 건드리지 않는다
----------------------------------------
이미 지나간 날짜의 정원을 되돌릴 이유가 없고, 되돌리면 그 날의
「몇 명이 검진을 받았는가」가 0 으로 보이게 된다.
"""

from datetime import datetime, timedelta

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.core import time_grid
from app.core.config import settings
from app.models.reservation import Reservation
from app.services import slot_grid_service as grid


def expire_cutoff(now: datetime | None = None) -> datetime:
    """이 시각 **이전**에 시작한 예약은 삭제 대상이다."""
    now = now or datetime.now()
    return now - timedelta(minutes=settings.RESERVATION_EXPIRE_GRACE_MINUTES)


def _expired_condition(cutoff: datetime):
    """`slot_date + start_time <= cutoff` 를 날짜·시각 비교로 나눈 조건.

    날짜와 시각이 별도 컬럼이므로 DATETIME 으로 합치지 않고 비교한다.
    `ix_res_schedule` 인덱스의 `slot_date` 를 그대로 탈 수 있다.
    """
    return or_(
        Reservation.slot_date < cutoff.date(),
        (Reservation.slot_date == cutoff.date())
        & (Reservation.start_time <= cutoff.time()),
    )


def count_expired(db: Session, now: datetime | None = None) -> int:
    """삭제 대상 건수를 센다. (삭제하지 않는다)"""
    cutoff = expire_cutoff(now)
    stmt = select(Reservation.id).where(_expired_condition(cutoff))
    return len(db.execute(stmt).scalars().all())


def purge_expired(db: Session, now: datetime | None = None) -> int:
    """검진 시각이 지난 예약을 삭제하고 삭제 건수를 반환한다.

    `reservation_options` · `contact_histories` 는 FK 의 ON DELETE CASCADE 로
    함께 지워진다. `mail_logs` 는 `SET NULL` 이므로 발송 이력은 남는다.
    무엇을 언제 보냈는지는 문의 대응에 필요하기 때문이다.

    **예약 수(`reservation_counts`)도 함께 내린다.** 지우기만 하면 파생
    데이터가 어긋난 채 남는다 — 아래 주석 참조.
    """
    cutoff = expire_cutoff(now)

    # 지우기 **전에** 어느 칸에서 몇 명이 빠지는지 세어 둔다.
    #
    # 예전에는 이 단계가 없어서, 지난 예약이 사라진 뒤에도 그 시간대의
    # 예약 수가 그대로 남았다. 검진이 끝난 날이라 예약에는 영향이 없지만
    # **관리 화면이 「22명 예약」이라고 계속 말했다.** 파생 데이터가 조용히
    # 어긋나는 전형적인 자리다.
    freed = db.execute(
        select(Reservation.schedule_id, Reservation.start_time, func.count())
        .where(_expired_condition(cutoff), Reservation.status != "CANCELLED")
        .group_by(Reservation.schedule_id, Reservation.start_time)
    ).all()

    # 어떤 예약이 삭제되었는지 추적하기 위해 삭제 전 목록을 확보한다.
    to_delete = db.execute(
        select(Reservation.reservation_no, Reservation.last_name, Reservation.first_name)
        .where(_expired_condition(cutoff))
    ).all()
    deleted_list = [f"{r.reservation_no} ({r.last_name} {r.first_name})" for r in to_delete]

    # ORM 캐스케이드를 타면 건마다 SELECT 가 나가므로 일괄 DELETE 를 쓴다.
    # 자식 행은 DB 의 ON DELETE 규칙이 처리한다.
    result = db.execute(
        delete(Reservation).where(_expired_condition(cutoff))
    )
    deleted = int(result.rowcount or 0)

    for schedule_id, start, count in freed:
        index = time_grid.index_of(start)
        if index is not None:
            grid.reserved_delta(db, int(schedule_id), index, -int(count))

    if deleted:
        # 레코드는 사라져도 정리가 일어난 사실은 남겨야 추적할 수 있다.
        from app.services.audit_service import write_system_log

        write_system_log(
            db,
            action="RESERVATION_PURGE",
            target_type="reservation",
            target_label=f"受診時刻経過予約 {deleted}件自動削除",
            after={
                "deleted": deleted,
                "deleted_reservations": deleted_list,
                "cutoff": cutoff.isoformat(timespec="minutes"),
                "grace_minutes": settings.RESERVATION_EXPIRE_GRACE_MINUTES,
            },
        )

    db.commit()
    return deleted
