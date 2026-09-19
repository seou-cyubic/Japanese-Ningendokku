"""관리 화면 — 회장 · 정원 · 옵션 검사 (A-20 ~ A-30).

전부 L2(업무 관리자) 이상 전용이다.
L1 스태프가 실수로 회장 정보를 지워 버리는 사고를 막기 위해,
화면을 감추는 것과 별개로 API 에서도 권한을 다시 본다 (자체 피드백 M-9).
"""

import re
import unicodedata
import csv
import io
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.admin import AdminUser
from app.models.exam_option import ExamOption
from app.models.hospital import Hospital, HospitalSchedule
from app.models.reservation import Reservation, ReservationOption
from app.schemas.admin import (
    CapacityDay,
    CapacityMonth,
    CapacitySlot,
    ExamOptionRow,
    ExamOptionSaveRequest,
    HospitalBulkFieldError,
    HospitalBulkRequest,
    HospitalBulkResult,
    HospitalBulkRow,
    HospitalBulkRowResult,
    HospitalRow,
    HospitalSaveRequest,
    ReservationImpact,
    ScheduleInput,
    ScheduleRow,
    SlotUpdateRequest,
    SlotUpdateResult,
)
from app.core import time_grid
from app.services import audit_service
from app.services import slot_grid_service as grid

WEEKDAY_JA = ["月", "火", "水", "木", "金", "土", "日"]

GENDER_LABELS = {"M": "男性のみ", "F": "女性のみ", "ALL": "全員"}


class MasterDataError(Exception):
    """마스터 데이터를 고칠 수 없는 이유."""


# ==========================================================================
# A-20 / A-21 회장
# ==========================================================================

# `region` 과 `access_info` 는 여기에 넣지 않는다. 둘 다 다른 칸에서
# 만들어지는 파생 값이라(地域+区市町村 / 交通情報+アクセス時間) 따로 쓰면
# 원본과 어긋난 값이 남는다.
#
# 개최일·마감일·개시 시각도 여기에 없다. 그것은 **회장이 아니라 회차**의
# 것이다 (`_SCHEDULE_FIELDS`). 회장에 두면 같은 장소가 여러 날 열 때
# 장소를 여러 벌 등록하는 수밖에 없어진다.
_HOSPITAL_FIELDS = [
    "code",
    "name",
    "area",
    "city",
    "postal_code",
    "address",
    "tel",
    "transit_info",
    "access_minutes",
    "has_parking",
    "latitude",
    "longitude",
    "is_visible",
    "sort_order",
]

# 감사 로그가 회차 변경을 남길 때 쓰는 칸 목록.
_SCHEDULE_FIELDS = [
    "event_date",
    "booking_close_date",
    "open_time",
    "reception_end_time",
    "is_visible",
    "note",
]


def _schedule_slot_stats(db: Session) -> dict[int, tuple[int, int, int, int]]:
    """회차별 (시간대 수, 정원 합, 예약 합, 닫힌 칸 수).

    회차 한 행이 그리드 16칸을 들고 있으므로, 회차를 한 번 읽으면 네 값이
    전부 나온다. 예전처럼 슬롯 수백 행을 `GROUP BY` 할 필요가 없다.

    닫힌 칸 수를 함께 내보내는 것은 달력이 **다른 회장**의 휴진일도
    빨갛게 그려야 하기 때문이다. 조회를 더 하지 않고 같은 값에서 꺼낸다.
    """
    return {
        schedule_id: (
            totals.slot_count, totals.capacity, totals.reserved,
            totals.closed_slots,
        )
        for schedule_id, totals in grid.totals_by_schedule(db).items()
    }


def _to_schedule_row(
    schedule: HospitalSchedule,
    stats: dict[int, tuple[int, int, int, int]],
    today: date,
) -> ScheduleRow:
    slot_count, capacity, reserved, closed_slots = stats.get(
        schedule.id, (0, 0, 0, 0)
    )
    return ScheduleRow(
        id=schedule.id,
        hospital_id=schedule.hospital_id,
        event_date=schedule.event_date,
        weekday=WEEKDAY_JA[schedule.event_date.weekday()],
        booking_close_date=schedule.booking_close_date,
        open_time=schedule.open_time,
        reception_end_time=schedule.reception_end_time,
        is_visible=schedule.is_visible,
        note=schedule.note,
        slot_count=slot_count,
        capacity=capacity,
        reserved=reserved,
        remaining=max(0, capacity - reserved),
        is_booking_open=schedule.is_open_for_booking(today),
        is_past=schedule.event_date < today,
        closed_slots=closed_slots,
        # 칸이 하나도 없는 날은 「휴진」이 아니라 「아직 시간표가 없는 날」이다.
        is_all_closed=bool(slot_count) and closed_slots >= slot_count,
    )


def _to_hospital_row(
    h: Hospital,
    *,
    schedule_stats: dict[int, tuple[int, int, int, int]],
    today: date,
    slot_days: int,
    slot_count: int,
    total_capacity: int,
    upcoming_reserved: int,
) -> HospitalRow:
    schedules = [_to_schedule_row(s, schedule_stats, today) for s in h.schedules]
    primary = h.primary_schedule

    return HospitalRow(
        id=h.id,
        code=h.code,
        name=h.name,
        name_kana=h.name_kana or "",
        area=h.area,
        city=h.city,
        region=h.region,
        postal_code=h.postal_code,
        address=h.address,
        tel=h.tel,
        contact_tel=h.contact_tel,
        transit_info=h.transit_info,
        access_minutes=h.access_minutes,
        access_info=h.access_info,
        schedules=schedules,
        schedule_count=len(schedules),
        upcoming_schedule_count=sum(1 for s in schedules if not s.is_past),
        event_date=primary.event_date if primary else None,
        booking_close_date=primary.booking_close_date if primary else None,
        open_time=primary.open_time if primary else None,
        reception_end_time=primary.reception_end_time if primary else None,
        has_parking=h.has_parking,
        latitude=h.latitude,
        longitude=h.longitude,
        is_visible=h.is_visible,
        sort_order=h.sort_order,
        slot_days=slot_days,
        slot_count=slot_count,
        total_capacity=total_capacity,
        upcoming_reserved=upcoming_reserved,
        is_booking_open=h.is_open_for_booking(today),
    )


def list_hospitals(db: Session) -> list[HospitalRow]:
    today = date.today()

    # 회장별 (시간표가 있는 날짜 수, 칸 수, 정원 합).
    hospital_totals = grid.totals_by_hospital(db)
    open_days = grid.open_days_by_hospital(db)
    slot_stats = {
        hospital_id: (
            open_days.get(hospital_id, 0),
            totals.slot_count,
            totals.capacity,
        )
        for hospital_id, totals in hospital_totals.items()
    }
    schedule_stats = _schedule_slot_stats(db)
    reserved_counts = dict(
        db.execute(
            select(Reservation.hospital_id, func.count())
            .where(
                Reservation.slot_date >= today,
                Reservation.status != "CANCELLED",
            )
            .group_by(Reservation.hospital_id)
        ).all()
    )

    hospitals = db.execute(
        select(Hospital).order_by(Hospital.sort_order, Hospital.id)
    ).scalars().all()

    rows = []
    for h in hospitals:
        days, count, capacity = slot_stats.get(h.id, (0, 0, 0))
        rows.append(
            _to_hospital_row(
                h,
                schedule_stats=schedule_stats,
                today=today,
                slot_days=days,
                slot_count=count,
                total_capacity=capacity,
                upcoming_reserved=int(reserved_counts.get(h.id, 0)),
            )
        )
    return rows


# --------------------------------------------------------------------------
# 개최 회차
# --------------------------------------------------------------------------


def schedule_reservation_count(
    db: Session, schedule_id: int, *, exclude_cancelled: bool = False
) -> int:
    """이 회차의 슬롯에 걸려 있는 예약 건수.

    기본은 **취소분도 센다** — 회차를 지우면 취소 이력까지 사라지기 때문이다.
    `exclude_cancelled` 는 「지금 이 날에 오시는 분이 몇 분인가」를 물을 때 쓴다.
    """
    stmt = (
        select(func.count(Reservation.id))
        .select_from(Reservation)
        .where(Reservation.schedule_id == schedule_id)
    )
    if exclude_cancelled:
        stmt = stmt.where(Reservation.status != "CANCELLED")
    return int(db.execute(stmt).scalar() or 0)


def close_moved_schedule(db: Session, schedule: HospitalSchedule) -> int:
    """개최일을 옮기려는 회차에 예약이 남아 있으면 그 날을 휴진으로 만든다.

    → 남아 있던 예약 건수. **0 이면 아무것도 하지 않았다** (그냥 옮기면 된다)

    왜 옮기지 않고 나누는가
    ------------------------
    `reservations.slot_date` 는 관리자 검색이 「회장 + 기간」으로 이루어지기
    때문에 회차와 **따로 저장하는** 컬럼이다 (models/reservation.py). 회차의
    날짜만 바꾸면 예약은 옛 날짜에 남아 두 값이 갈라지고, 옛 날짜가 지나면
    `purge_service` 가 그 예약들을 지운다 — 이용자는 새 날짜에 예약이 살아
    있는 줄 알고 회장에 오는데 명단이 비어 있다.

    예약도 함께 옮겨 주면 데이터는 맞는다. 그러나 그 사람들의 검진일이
    **전화 한 통 없이** 바뀌고, 「아직 연락 못 한 사람」을 찾을 목록이
    사라진다. 이 시스템은 휴진·변경을 전화로 먼저 알리고 옮기기로 되어 있다.

    그래서 담당자가 하려던 일(새 날짜를 여는 것)은 그대로 이루어 주되,
    옛 날짜는 **휴진 회차로 남긴다.** 예약이 그 날에 그대로 있으므로 예약
    검색의 「휴진일」 필터에 뜨고, 한 사람씩 옮기면 그 목록에서 사라진다.

    정원 숫자는 지우지 않는다 — 몇 자리를 열었던 날인지 남아야 한다.
    """
    held = schedule_reservation_count(db, schedule.id, exclude_cancelled=True)
    if not held:
        return 0

    for index in time_grid.indexes():
        if schedule.capacity_at(index) is not None:
            schedule.set_closed_at(index, True)
    db.flush()
    return held


def sync_schedules(
    db: Session, hospital: Hospital, items: list[ScheduleInput]
) -> list[str]:
    """회장의 개최 회차를 요청받은 목록과 똑같이 맞춘다. → 바뀐 것 설명

    **목록에 없는 회차는 지운다.** 이 목록이 그 회장 회차의 전부라는
    약속이기 때문이다. 다만 예약이 걸린 회차는 지우지 않고 거절한다 —
    지우면 그 날 예약한 사람들의 검진일이 어디서 왔는지 알 수 없게 된다.
    """
    changes: list[str] = []
    by_id = {s.id: s for s in hospital.schedules}
    by_date = {s.event_date: s for s in hospital.schedules}
    kept: set[int] = set()

    for order, item in enumerate(items, start=1):
        schedule = None
        if item.id is not None:
            schedule = by_id.get(item.id)
            if schedule is None:
                raise MasterDataError(
                    f"開催回が見つかりません (id={item.id}). "
                    "画面を更新してください。"
                )
        else:
            schedule = by_date.get(item.event_date)

        if schedule is None:
            schedule = HospitalSchedule(
                hospital_id=hospital.id, event_date=item.event_date
            )
            db.add(schedule)
            changes.append(f"+{item.event_date.isoformat()}")
        else:
            if schedule.event_date != item.event_date:
                # 예약이 걸린 회차는 옮기지 않고 **둘로 나눈다.**
                # 왜 그런지는 close_moved_schedule 에 적어 두었다.
                held = close_moved_schedule(db, schedule)
                if held:
                    stale = schedule
                    kept.add(stale.id)
                    changes.append(
                        f"{stale.event_date.isoformat()} → 休診 "
                        f"（予約 {held}件はこの日にそのまま残します）"
                    )
                    changes.append(f"+{item.event_date.isoformat()}")
                    schedule = HospitalSchedule(
                        hospital_id=hospital.id, event_date=item.event_date
                    )
                    # 같은 시간표로 다른 날을 연다. 정원을 가져오지 않으면
                    # 새 날짜에 고를 수 있는 시간이 하나도 없어, 담당자가
                    # 보기에는 날을 옮겼는데 이용자 화면에는 뜨지 않는다.
                    # 마감 표시와 예약 수는 가져오지 않는다 — 그것은
                    # 옛 날짜에 일어난 일이다.
                    for index in time_grid.indexes():
                        schedule.set_capacity_at(index, stale.capacity_at(index))
                    db.add(schedule)
                else:
                    changes.append(
                        f"{schedule.event_date.isoformat()}"
                        f"\u2192{item.event_date.isoformat()}"
                    )
            schedule.event_date = item.event_date

        if (
            item.booking_close_date is not None
            and item.booking_close_date > item.event_date
        ):
            raise MasterDataError(
                f"{item.event_date.isoformat()} — 受付締切日が開催日より後です。"
            )
        if (
            item.open_time is not None
            and item.reception_end_time is not None
            and item.reception_end_time <= item.open_time
        ):
            raise MasterDataError(
                f"{item.event_date.isoformat()} — "
                "受付終了時刻が開始時刻以前になっています。"
            )

        schedule.booking_close_date = item.booking_close_date
        schedule.open_time = item.open_time
        schedule.reception_end_time = item.reception_end_time
        schedule.is_visible = item.is_visible
        schedule.note = item.note
        schedule.sort_order = order

        db.flush()
        kept.add(schedule.id)

        # 개최일을 옮겨도 시간표는 따라올 것이 없다. 정원이 회차 행의
        # 칼럼이므로 **날짜와 시간표가 같은 행에 있기 때문**이다. 예전에는
        # 슬롯이 별도 행이라 날짜를 옮길 때마다 그 행들을 함께 옮겨야 했고,
        # 그것을 잊으면 달력에는 새 날이 뜨는데 시간표는 옛 날에 남았다.

    for schedule in list(hospital.schedules):
        if schedule.id in kept:
            continue
        count = schedule_reservation_count(db, schedule.id)
        if count:
            raise MasterDataError(
                f"{schedule.event_date.isoformat()} の開催回に予約が {count}件あり、"
                "削除できません。画面から非表示にするには「表示」をオフにしてください。"
            )
        changes.append(f"-{schedule.event_date.isoformat()}")
        db.delete(schedule)

    db.flush()
    return changes


def list_schedules(db: Session, hospital_id: int) -> list[ScheduleRow]:
    """한 회장의 개최 회차 전부. 지난 회차도 준다.

    이용자 화면과 달리 관리 화면은 **끝난 회차의 실적**도 봐야 한다.
    지난 회차를 빼면 「작년 7월에 몇 명 받았는가」에 답할 수 없다.
    """
    hospital = db.get(Hospital, hospital_id)
    if hospital is None:
        raise MasterDataError("会場が見つかりません。")

    today = date.today()
    stats = _schedule_slot_stats(db)
    return [_to_schedule_row(s, stats, today) for s in hospital.schedules]


def save_schedules(
    db: Session,
    hospital_id: int,
    items: list[ScheduleInput],
    *,
    admin: AdminUser,
    ip_address: str,
) -> list[ScheduleRow]:
    """회차 목록만 통째로 저장한다. (회장 정보는 손대지 않는다)

    회장 저장(`save_hospital`)과 나눠 둔 이유는 덮어쓰기 사고 때문이다.
    「10월 회차 하나 추가」에 회장 정보 전체를 실어 보내게 하면, 그 사이
    다른 사람이 고친 주소를 화면이 들고 있던 옛 값으로 되돌려 버린다.
    """
    hospital = db.get(Hospital, hospital_id)
    if hospital is None:
        raise MasterDataError("会場が見つかりません。")

    seen: set[date] = set()
    for item in items:
        if item.event_date in seen:
            raise MasterDataError(
                f"開催日 {item.event_date.isoformat()} が重複しています。"
            )
        seen.add(item.event_date)

    before = {
        "schedules": ", ".join(s.event_date.isoformat() for s in hospital.schedules)
    }
    changes = sync_schedules(db, hospital, items)
    db.flush()
    after = {
        "schedules": ", ".join(s.event_date.isoformat() for s in hospital.schedules)
    }

    if changes:
        audit_service.write_log(
            db,
            admin=admin,
            action="HOSPITAL_SCHEDULE_SAVE",
            target_type="hospital",
            target_id=hospital.id,
            target_label=f"{hospital.code} {hospital.name}",
            before=before,
            after={**after, "changed": ", ".join(changes)},
            ip_address=ip_address,
        )

    db.commit()
    db.refresh(hospital)

    today = date.today()
    stats = _schedule_slot_stats(db)
    return [_to_schedule_row(s, stats, today) for s in hospital.schedules]


def save_hospital(
    db: Session,
    hospital_id: int | None,
    payload: HospitalSaveRequest,
    *,
    admin: AdminUser,
    ip_address: str,
) -> HospitalRow:
    duplicate = db.execute(
        select(Hospital).where(Hospital.code == payload.code)
    ).scalar_one_or_none()

    if duplicate is not None and duplicate.id != hospital_id:
        raise MasterDataError(f"会場コード「{payload.code}」は既に使用されています。")

    if hospital_id:
        hospital = db.get(Hospital, hospital_id)
        if hospital is None:
            raise MasterDataError("会場が見つかりません。")
        before = audit_service.snapshot(hospital, _HOSPITAL_FIELDS)
        action = "HOSPITAL_UPDATE"
    else:
        hospital = Hospital()
        db.add(hospital)
        before = {}
        action = "HOSPITAL_CREATE"

    for field in _HOSPITAL_FIELDS:
        setattr(hospital, field, getattr(payload, field))

    # 표시용 지역 한 줄은 저장할 때 만들어 둔다. 읽을 때마다 잇게 하면
    # 정렬·검색 쿼리에서 쓸 수 없다.
    hospital.region = payload.region

    db.flush()
    after = audit_service.snapshot(hospital, _HOSPITAL_FIELDS)

    # `None` 은 「회차를 손대지 않음」이다. 회차 편집을 지원하지 않는 화면이
    # 회장 이름만 고쳐 저장했을 때 개최일이 전부 사라지지 않게 한다.
    schedule_changes: list[str] = []
    if payload.schedules is not None:
        schedule_changes = sync_schedules(db, hospital, payload.schedules)

    audit_after = audit_service.diff(before, after) if before else after
    if schedule_changes:
        audit_after = dict(audit_after or {})
        audit_after["schedules"] = ", ".join(schedule_changes)

    audit_service.write_log(
        db,
        admin=admin,
        action=action,
        target_type="hospital",
        target_id=hospital.id,
        target_label=f"{hospital.code} {hospital.name}",
        before=before or None,
        after=audit_after,
        ip_address=ip_address,
    )
    db.commit()

    return next(h for h in list_hospitals(db) if h.id == hospital.id)


def delete_hospital(
    db: Session,
    hospital_id: int,
    *,
    admin: AdminUser,
    ip_address: str,
) -> str:
    """회장을 삭제한다.

    앞으로의 예약이 남아 있으면 지우지 않는다. 지워 버리면 그 예약자들이
    어디로 가야 하는지 아무도 모르게 된다. 대신 「비표시」를 권한다.
    """
    hospital = db.get(Hospital, hospital_id)
    if hospital is None:
        raise MasterDataError("会場が見つかりません。")

    upcoming = db.execute(
        select(func.count())
        .select_from(Reservation)
        .where(
            Reservation.hospital_id == hospital_id,
            Reservation.slot_date >= date.today(),
            Reservation.status != "CANCELLED",
        )
    ).scalar() or 0

    if upcoming:
        raise MasterDataError(
            f"この会場に今後の予約が {upcoming}件残っているため削除できません。"
            "予約画面で非表示にするには「予約画面表示」をオフにしてください。"
        )

    audit_service.write_log(
        db,
        admin=admin,
        action="HOSPITAL_DELETE",
        target_type="hospital",
        target_id=hospital.id,
        target_label=f"{hospital.code} {hospital.name}",
        before=audit_service.snapshot(hospital, _HOSPITAL_FIELDS),
        ip_address=ip_address,
    )

    db.delete(hospital)
    db.commit()
    return f"{hospital.name} を削除しました。"


# ==========================================================================
# A-24 회장 일괄 관리 (스프레드시트)
# ==========================================================================
# 담당자가 회장 마스터를 다루는 도구는 원래 Excel 이다. 화면에서도 같은
# 모양으로 다루게 한다. 표 한 장을 통째로 받아 **전 행을 먼저 검증하고,
# 한 칸이라도 틀리면 한 건도 저장하지 않는다.** 절반만 반영된 마스터는
# 반영되지 않은 마스터보다 나쁘다 — 무엇이 들어갔는지 아무도 모른다.


class HospitalBulkValidationError(Exception):
    """일괄 입력의 모든 행을 검사한 뒤 돌려주는 셀 단위 오류."""

    def __init__(self, errors: list[HospitalBulkFieldError]) -> None:
        super().__init__("入力内容をご確認ください。")
        self.errors = errors


# 표에서 참/거짓으로 읽는 값. 원본 마스터의 ○ × 를 그대로 받는다.
_TRUE_TEXTS = frozenset(
    {"はい", "y", "yes", "true", "1", "o", "○", "◯", "有", "あり", "表示", "公開"}
)
_FALSE_TEXTS = frozenset(
    {"いいえ", "n", "no", "false", "0", "x", "×", "✕", "無", "なし", "非表示", "非公開"}
)


def _cell(value: Any) -> str:
    if value is None or value is False:
        return ""
    if value is True:
        return "はい"
    return re.sub(r"[\s ]+", " ", str(value)).strip()


def _parse_sheet_date(text: str) -> date | None:
    """표의 날짜 칸. `datetime` 으로 넘어온 Excel 셀도 여기까지 문자열이다."""
    normalized = unicodedata.normalize("NFKC", text).replace(".", "-").replace("/", "-")
    normalized = re.sub(r"\s+.*$", "", normalized)  # 「2026-07-17 00:00:00」의 뒤를 자른다
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None


def _parse_sheet_time(text: str) -> time | None:
    normalized = unicodedata.normalize("NFKC", text)
    matched = re.match(r"^(\d{1,2}):(\d{2})", normalized)
    if not matched:
        return None
    hour, minute = int(matched.group(1)), int(matched.group(2))
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def hospital_bulk_rows(db: Session) -> list[dict[str, str]]:
    """지금 등록된 회장을 표의 행으로. 화면이 열자마자 이것을 띄운다.

    **한 행이 개최 회차 하나다.** 같은 회장이 세 번 열면 세 행이 나오고,
    세 행의 장소 칸(주소·좌표·교통편)은 같은 값이다.

    회차가 하나도 없는 회장도 개최일이 빈 행으로 한 줄 나온다. 빼 버리면
    새로 등록만 해 두고 일정이 아직 안 정해진 회장을 표에서 고칠 수 없다.
    """
    hospitals = db.execute(
        select(Hospital).order_by(Hospital.sort_order, Hospital.id)
    ).scalars().all()


    rows: list[dict[str, str]] = []

    def venue_cells(h: Hospital) -> dict[str, str]:
        return {
            "id": str(h.id),
            "code": h.code,
            "name": h.name,
            "area": h.area,
            "city": h.city,
            "postal_code": h.postal_code,
            "address": h.address,
            "transit_info": h.transit_info,
            "access_minutes": h.access_minutes,
            "has_parking": "はい" if h.has_parking else "いいえ",
            # `:g` 를 쓰면 유효숫자 6자리로 잘려 35.6584491 이 35.6584 가 된다.
            # 표를 열었다 그대로 저장하는 것만으로 좌표가 200m 옮겨간다.
            # repr 은 다시 읽으면 같은 값이 되는 가장 짧은 표기를 준다.
            "latitude": "" if h.latitude is None else repr(h.latitude),
            "longitude": "" if h.longitude is None else repr(h.longitude),
            "tel": h.tel,
            "is_visible": "はい" if h.is_visible else "いいえ",
            "sort_order": str(h.sort_order),
        }

    for h in hospitals:
        if not h.schedules:
            row = venue_cells(h)
            row.update({
                "schedule_id": "",
                "event_date": "",
                "booking_close_date": "",
                "open_time": "",
                "reception_end_time": "",
                "schedule_note": "",
            })
            rows.append(row)
            continue

        for schedule in h.schedules:
            row = venue_cells(h)
            row.update({
                "schedule_id": str(schedule.id),
                "event_date": schedule.event_date.isoformat(),
                "booking_close_date": (
                    schedule.booking_close_date.isoformat()
                    if schedule.booking_close_date else ""
                ),
                "open_time": (
                    schedule.open_time.strftime("%H:%M")
                    if schedule.open_time else ""
                ),
                "reception_end_time": (
                    schedule.reception_end_time.strftime("%H:%M")
                    if schedule.reception_end_time else ""
                ),
                "schedule_note": schedule.note,
            })
            for view in grid.views_of(schedule):
                row[view.time_label] = str(view.capacity)
            rows.append(row)

    return rows


@dataclass
class _HospitalDraft:
    """검증을 통과한 한 행 = 개최 회차 하나.

    `hospital` 은 기존 회장, `schedule` 은 기존 회차다. 둘 다 `None` 이면
    새로 만든다. `values` 는 전부 DB 에 그대로 넣을 수 있는 형태다.
    """

    row_no: int
    hospital: Hospital | None
    schedule: HospitalSchedule | None
    values: dict[str, Any]

    @property
    def code_key(self) -> str:
        return str(self.values["code"]).casefold()


def _validate_bulk_row(
    row: HospitalBulkRow,
    row_no: int,
    *,
    by_id: dict[int, Hospital],
    by_code: dict[str, Hospital],
    schedules_by_id: dict[int, HospitalSchedule],
    schedules_by_key: dict[tuple[str, date], HospitalSchedule],
    seen_keys: dict[tuple[str, date | None], int],
    errors: list[HospitalBulkFieldError],
    warnings: list[HospitalBulkFieldError],
) -> _HospitalDraft | None:
    """한 행을 검사한다. 오류는 모아서 돌려주고 여기서 멈추지 않는다.

    한 칸이 틀렸다고 그 행의 나머지를 안 보면, 고쳐서 다시 올릴 때마다
    새 오류가 하나씩 나온다. 사람이 같은 왕복을 다섯 번 하게 된다.
    """
    def add(field: str, message: str) -> None:
        errors.append(
            HospitalBulkFieldError(row_no=row_no, field=field, message=message)
        )

    def warn(field: str, message: str) -> None:
        warnings.append(
            HospitalBulkFieldError(row_no=row_no, field=field, message=message)
        )

    before = len(errors)
    values: dict[str, Any] = {}

    # --- 코드 : 어느 회장인가 ---------------------------------------------
    # **코드는 이제 겹쳐도 된다.** 같은 코드가 여러 행에 나오는 것이 곧
    # 「이 회장이 여러 날 연다」는 뜻이다. 겹치면 안 되는 것은 코드가
    # 아니라 (코드 + 개최일) 쌍이다.
    code = _cell(row.code)
    if not code:
        add("code", "会場コードは必須です。")
    elif len(code) > 20:
        add("code", "会場コードは20文字以内で入力してください。")
    values["code"] = code

    name = _cell(row.name)
    if not name:
        add("name", "会場名は必須です。")
    elif len(name) > 120:
        add("name", "会場名は120文字以内で入力してください。")
    values["name"] = name

    # --- 어느 회장을 고치는가 ---------------------------------------------
    # id 가 오면 그것이 우선이다. 코드를 고치는 수정(코드 오타 정정)이
    # 코드로만 찾으면 「새 회장 등록」이 되어 버린다.
    hospital: Hospital | None = None
    raw_id = _cell(row.id)
    if raw_id:
        if not raw_id.isdigit() or int(raw_id) not in by_id:
            add("id", "この行が示す会場が見つかりません。画面を更新してください。")
        else:
            hospital = by_id[int(raw_id)]
    elif code:
        hospital = by_code.get(code.casefold())

    # 코드를 **다른** 회장이 이미 쓰고 있으면 막는다 (UNIQUE 제약을 미리 본다).
    if code:
        owner = by_code.get(code.casefold())
        if owner is not None and hospital is not None and owner.id != hospital.id:
            add("code", f"会場コード「{code}」は {owner.name} が使用しています。")

    # --- 길이만 보는 칸 ----------------------------------------------------
    for field, limit, label in (
        ("area", 40, "地域"),
        ("city", 60, "区・市町村"),
        ("postal_code", 10, "郵便番号"),
        ("address", 255, "住所"),
        ("transit_info", 200, "交通情報"),
        ("access_minutes", 40, "所要時間"),
        ("tel", 30, "電話"),
    ):
        text = _cell(getattr(row, field))
        if len(text) > limit:
            add(field, f"{label} は {limit}文字以内で入力してください。")
        values[field] = text

    # 표시용 지역 한 줄은 두 칸에서 만든다. 사람이 따로 적지 않는다.
    values["region"] = f"{values['area']}{values['city']}"

    # --- 날짜 -------------------------------------------------------------
    for field, label in (
        ("event_date", "開催日"),
        ("booking_close_date", "受付締切日"),
    ):
        text = _cell(getattr(row, field))
        if not text:
            values[field] = None
            continue
        parsed = _parse_sheet_date(text)
        if parsed is None:
            add(field, f"{label} はYYYY-MM-DD形式で入力してください。（例: 2026-07-17）")
        values[field] = parsed

    event = values.get("event_date")
    close = values.get("booking_close_date")
    if event and close and close > event:
        # 막지는 않는다. 개최일이 지나면 어차피 접수가 닫히므로(회차의
        # `is_open_for_booking`) 이 값은 효력이 없을 뿐 데이터를 망가뜨리지
        # 않는다. 무엇보다 `scripts/import_hospitals` 가 이 값을 경고만 하고
        # 저장하기 때문에, 여기서 막으면 담당자가 표를 열어 아무것도 고치지
        # 않고 저장하는 것조차 못 하게 된다.
        warn(
            "booking_close_date",
            "受付締切日が開催日より後です。開催日を過ぎると受付は締め切られるため、"
            "この値は効力がありません。",
        )
    if event is None and close is not None:
        add("event_date", "受付締切日のみ設定されており、開催日がありません。")

    # --- 시각 -------------------------------------------------------------
    for field, label in (
        ("open_time", "開始時刻"),
        ("reception_end_time", "受付終了時刻"),
    ):
        text = _cell(getattr(row, field))
        if not text:
            values[field] = None
            continue
        parsed = _parse_sheet_time(text)
        if parsed is None:
            add(field, f"{label} はHH:MM形式で入力してください。(例: 09:30)")
        values[field] = parsed

    start = values.get("open_time")
    end = values.get("reception_end_time")
    if start and end and end <= start:
        add("reception_end_time", "受付終了時刻が開始時刻以前になっています。")

    values["note"] = _cell(getattr(row, "schedule_note", ""))[:200]

    # --- 같은 회장의 같은 날이 두 번 나오면 막는다 --------------------------
    # 시트를 이어 붙이다 같은 줄을 두 번 넣는 것이 가장 흔한 실수다.
    # DB 의 UNIQUE(hospital_id, event_date) 를 여기서 미리 본다.
    if code:
        key = (code.casefold(), event)
        duplicate_at = seen_keys.get(key)
        if duplicate_at is not None:
            if event is None:
                add("event_date", f"{duplicate_at}行目と同じ会場ですが、開催日が両方とも空です。")
            else:
                add(
                    "event_date",
                    f"{duplicate_at}行目と会場・開催日が同じです。"
                    "同一会場で同日に複数回開催することはできません。",
                )
        else:
            seen_keys[key] = row_no

    # --- 어느 회차를 고치는가 ---------------------------------------------
    schedule: HospitalSchedule | None = None
    raw_schedule_id = _cell(getattr(row, "schedule_id", ""))
    if raw_schedule_id:
        if not raw_schedule_id.isdigit() or int(raw_schedule_id) not in schedules_by_id:
            add("event_date", "この行が示す開催回が見つかりません。画面を更新してください。")
        else:
            schedule = schedules_by_id[int(raw_schedule_id)]
    elif code and event is not None:
        schedule = schedules_by_key.get((code.casefold(), event))

    # --- 참/거짓 ----------------------------------------------------------
    for field, label, default in (
        ("has_parking", "駐車場", False),
        ("is_visible", "予約画面表示", True),
    ):
        text = _cell(getattr(row, field)).casefold()
        if not text:
            values[field] = default
        elif text in _TRUE_TEXTS:
            values[field] = True
        elif text in _FALSE_TEXTS:
            values[field] = False
        else:
            add(field, f"{label} は「はい」または「いいえ」で入力してください。")
            values[field] = default

    # --- 숫자 -------------------------------------------------------------
    for field, label, low, high in (
        ("latitude", "緯度", -90.0, 90.0),
        ("longitude", "経度", -180.0, 180.0),
    ):
        text = _cell(getattr(row, field))
        if not text:
            values[field] = None
            continue
        try:
            number = float(unicodedata.normalize("NFKC", text))
        except ValueError:
            add(field, f"{label} は数値で入力してください。(例: 35.6584491)")
            values[field] = None
            continue
        if not low <= number <= high:
            add(field, f"{label} は {low} ~ {high} の間である必要があります。")
        values[field] = number

    order_text = _cell(row.sort_order)
    if not order_text:
        values["sort_order"] = row_no
    elif re.fullmatch(r"-?\d+", unicodedata.normalize("NFKC", order_text)):
        values["sort_order"] = int(unicodedata.normalize("NFKC", order_text))
    else:
        add("sort_order", "並び順は整数で入力してください。")
        values["sort_order"] = row_no

    # --- 시간대별 정원 (동적 컬럼) -------------------------------------------
    from app.services.hospital_sheet_service import SLOT_HEADER
    slots: list[tuple[time, time, int, str]] = []
    extra_data = row.model_dump(exclude_unset=True)
    for key, val in extra_data.items():
        matched = SLOT_HEADER.match(key)
        if matched:
            if not matched.group(1):
                # '計' 또는 '合計' 이면 무시
                continue
            start_at = time(int(matched.group(1)), int(matched.group(2)))
            end_at = time(int(matched.group(3)), int(matched.group(4)))
            text = _cell(val)
            if not text:
                continue
            if re.fullmatch(r"-?\d+", text):
                capacity = int(text)
                if capacity > 0:
                    slots.append((start_at, end_at, capacity, key))
                else:
                    add(key, "定員は1以上の整数で入力してください。（空欄は締切（削除）を意味します。）")
            else:
                add(key, "定員は整数で入力してください。(例: 15)")

    if slots and event is None:
        add("event_date", "時間帯別定員がありますが、開催日が空欄です。")

    values["_slots"] = slots

    if len(errors) > before:
        return None
    return _HospitalDraft(
        row_no=row_no, hospital=hospital, schedule=schedule, values=values
    )


# 같은 회장의 행끼리 반드시 같아야 하는 칸. 장소는 회차마다 달라질 수 없다.
_VENUE_CELLS: tuple[tuple[str, str], ...] = (
    ("name", "会場名"),
    ("area", "地域"),
    ("city", "区・市町村"),
    ("postal_code", "郵便番号"),
    ("address", "住所"),
    ("transit_info", "交通情報"),
    ("access_minutes", "所要時間"),
    ("tel", "電話"),
    ("has_parking", "駐車場"),
    ("latitude", "緯度"),
    ("longitude", "経度"),
    ("is_visible", "予約画面表示"),
)


def _check_venue_consistency(
    drafts: list[_HospitalDraft], errors: list[HospitalBulkFieldError]
) -> None:
    """같은 회장의 행끼리 장소 칸이 어긋나면 막는다.

    조용히 한쪽을 채택하지 않는 이유는, 어느 쪽이 맞는지 표를 만든 사람만
    알기 때문이다. 마지막 행으로 덮어쓰면 **줄 순서를 바꾸는 것만으로
    주소가 바뀐다.** 어느 칸이 어느 행과 다른지 짚어 주고 사람이 고르게 한다.

    (`scripts/import_hospitals` 는 같은 상황에서 경고만 내고 첫 행을 쓴다.
    그쪽은 무인 적재라 한 칸 때문에 전부 안 들어가는 편이 더 나쁘다.)
    """
    first_of: dict[str, _HospitalDraft] = {}
    for draft in drafts:
        head = first_of.setdefault(draft.code_key, draft)
        if head is draft:
            continue
        for field, label in _VENUE_CELLS:
            if draft.values.get(field) != head.values.get(field):
                errors.append(
                    HospitalBulkFieldError(
                        row_no=draft.row_no,
                        field=field,
                        message=(
                            f"{head.row_no}行と同じ会場ですが、「{label}」が異なります。"
                            "場所情報は同じ会場のすべての行で同じである必要があります。"
                        ),
                    )
                )


def _sync_bulk_slots(
    db: Session, schedule: HospitalSchedule, wanted_slots: list
) -> bool:
    """일괄 저장에서 한 회차의 시간표를 표에 맞춘다. → 바뀌었는가

    표에 적힌 칸만 남기고 나머지는 비운다. 그리드에서 「비운다」는 정원을
    `NULL` 로 되돌리는 것이며, 그것이 「그 시간대를 열지 않음」이다.
    """
    counts = grid.counts_of(db, schedule)
    changed = False
    wanted: set[int] = set()

    for start_at, _end_at, capacity, _label in wanted_slots:
        index = time_grid.index_of(start_at)
        if index is None:
            # 격자 밖 시각. 표가 만들어 낼 수 없는 값이지만, 파일을 손으로
            # 고쳐 올리면 들어올 수 있다. 조용히 버리지 않고 넘긴다 —
            # 검증 단계에서 이미 열로 인식되지 않아 걸러졌을 값이다.
            continue
        wanted.add(index)

        # 이미 예약된 인원보다 낮게 정원을 줄이려 하면, 에러 대신 가능한
        # 최하한선(예약 수)으로 맞춘다. 단일 수정과 달리 일괄 수정에서는
        # 조용히 방어만 한다.
        new_capacity = max(capacity, counts.reserved_at(index))
        if schedule.capacity_at(index) != new_capacity:
            schedule.set_capacity_at(index, new_capacity)
            changed = True

    for index in schedule.open_indexes():
        if index in wanted:
            continue
        if counts.reserved_at(index) > 0:
            # 예약이 걸린 칸은 표에서 빠졌다는 이유로 지우지 않는다.
            # 지우면 그 예약이 몇 시였는지 화면이 답할 수 없게 된다.
            continue
        schedule.set_capacity_at(index, None)
        schedule.set_closed_at(index, False)
        changed = True

    return changed


def save_hospitals_bulk(
    db: Session,
    payload: HospitalBulkRequest,
    *,
    admin: AdminUser,
    ip_address: str,
) -> HospitalBulkResult:
    """표 한 장을 그대로 마스터에 반영한다.

    **한 행이 개최 회차 하나다.** 같은 회장 코드가 여러 행에 나오면 그
    회장이 여러 날 연다는 뜻이며, 장소 정보는 행마다 같아야 한다.

    **표에 없는 회장·회차는 지우지 않는다.** 표는 「이번에 손댄 것」이지
    「전체 목록」이 아니다. 20행을 붙여 넣었다는 이유로 나머지가 사라지면,
    거기 잡혀 있던 예약이 갈 곳을 잃는다. 지우는 것은 회장 관리 화면에서만
    할 수 있게 둔다.
    """
    hospitals = db.execute(select(Hospital)).scalars().all()
    by_id = {h.id: h for h in hospitals}
    by_code = {h.code.casefold(): h for h in hospitals}

    all_schedules = db.execute(select(HospitalSchedule)).scalars().all()
    schedules_by_id = {s.id: s for s in all_schedules}
    schedules_by_key = {
        (by_id[s.hospital_id].code.casefold(), s.event_date): s
        for s in all_schedules
        if s.hospital_id in by_id
    }

    errors: list[HospitalBulkFieldError] = []
    warnings: list[HospitalBulkFieldError] = []
    seen_keys: dict[tuple[str, date | None], int] = {}
    drafts: list[_HospitalDraft] = []

    for index, row in enumerate(payload.rows, start=1):
        row_no = int(row.row_no) if str(row.row_no or "").isdigit() else index
        draft = _validate_bulk_row(
            row,
            row_no,
            by_id=by_id,
            by_code=by_code,
            schedules_by_id=schedules_by_id,
            schedules_by_key=schedules_by_key,
            seen_keys=seen_keys,
            errors=errors,
            warnings=warnings,
        )
        if draft is not None:
            drafts.append(draft)

    _check_venue_consistency(drafts, errors)

    if errors:
        raise HospitalBulkValidationError(errors)

    results: list[HospitalBulkRowResult] = []
    created = updated = unchanged = 0

    # 회장은 코드마다 한 번만 만들고, 그 뒤 회차 행이 붙는다.
    saved_hospitals: dict[str, Hospital] = {}
    hospital_actions: dict[int, str] = {}

    for draft in drafts:
        key = draft.code_key
        hospital = saved_hospitals.get(key)

        if hospital is None:
            hospital = draft.hospital
            is_new_hospital = hospital is None
            if is_new_hospital:
                hospital = Hospital()
                db.add(hospital)
                before: dict[str, Any] = {}
            else:
                before = audit_service.snapshot(hospital, _HOSPITAL_FIELDS)

            for field in _HOSPITAL_FIELDS:
                setattr(hospital, field, draft.values[field])
            hospital.region = draft.values["region"]

            db.flush()
            after = audit_service.snapshot(hospital, _HOSPITAL_FIELDS)
            venue_changed = [
                f for f in _HOSPITAL_FIELDS if before.get(f) != after.get(f)
            ]

            if is_new_hospital:
                hospital_actions[hospital.id] = "CREATED"
            elif venue_changed:
                hospital_actions[hospital.id] = "UPDATED"
            else:
                hospital_actions[hospital.id] = "UNCHANGED"

            if is_new_hospital or venue_changed:
                audit_service.write_log(
                    db,
                    admin=admin,
                    action="HOSPITAL_CREATE" if is_new_hospital else "HOSPITAL_UPDATE",
                    target_type="hospital",
                    target_id=hospital.id,
                    target_label=f"{hospital.code} {hospital.name}",
                    before=before or None,
                    after=audit_service.diff(before, after) if before else after,
                    ip_address=ip_address,
                )

            saved_hospitals[key] = hospital
            changed = list(venue_changed)
            action = hospital_actions[hospital.id]
        else:
            # 같은 회장의 두 번째 행부터는 장소를 다시 쓰지 않는다.
            # 값이 같다는 것은 `_check_venue_consistency` 가 이미 보장했다.
            changed = []
            action = "UNCHANGED"

        event_date = draft.values.get("event_date")
        schedule: HospitalSchedule | None = None

        if event_date is not None:
            schedule = draft.schedule
            is_new_schedule = schedule is None
            if is_new_schedule:
                schedule = HospitalSchedule(
                    hospital_id=hospital.id, event_date=event_date
                )
                db.add(schedule)
                schedule_before: dict[str, Any] = {}
            else:
                schedule_before = audit_service.snapshot(schedule, _SCHEDULE_FIELDS)

            schedule.hospital_id = hospital.id
            schedule.event_date = event_date
            schedule.booking_close_date = draft.values["booking_close_date"]
            schedule.open_time = draft.values["open_time"]
            schedule.reception_end_time = draft.values["reception_end_time"]
            schedule.note = draft.values["note"]
            db.flush()

            schedule_after = audit_service.snapshot(schedule, _SCHEDULE_FIELDS)
            schedule_changed = [
                f for f in _SCHEDULE_FIELDS
                if schedule_before.get(f) != schedule_after.get(f)
            ]

            # 개최일이 옮겨져도 시간표는 같은 행에 있으므로 따라올 것이 없다.
            if _sync_bulk_slots(db, schedule, draft.values["_slots"]):
                schedule_changed.append("定員")

            if is_new_schedule:
                changed.append("schedule:new")
                action = "CREATED" if action == "CREATED" else "UPDATED"
            elif schedule_changed:
                changed.extend(f"schedule:{f}" for f in schedule_changed)
                if action == "UNCHANGED":
                    action = "UPDATED"

            if is_new_schedule or schedule_changed:
                audit_service.write_log(
                    db,
                    admin=admin,
                    action="HOSPITAL_SCHEDULE_SAVE",
                    target_type="hospital_schedule",
                    target_id=schedule.id,
                    target_label=(
                        f"{hospital.code} {hospital.name} "
                        f"{schedule.event_date.isoformat()}"
                    ),
                    before=schedule_before or None,
                    after=(
                        audit_service.diff(schedule_before, schedule_after)
                        if schedule_before else schedule_after
                    ),
                    ip_address=ip_address,
                )

        if action == "CREATED":
            created += 1
        elif action == "UPDATED":
            updated += 1
        else:
            unchanged += 1

        results.append(
            HospitalBulkRowResult(
                row_no=draft.row_no,
                id=hospital.id,
                schedule_id=schedule.id if schedule is not None else None,
                code=hospital.code,
                name=hospital.name,
                event_date=event_date,
                action=action,
                changed_fields=changed,
            )
        )

    audit_service.write_log(
        db,
        admin=admin,
        action="HOSPITAL_BULK_SAVE",
        target_type="hospital",
        target_label=(
            f"会場一括管理 {len(drafts)}行 / 会場 {len(saved_hospitals)}箇所 "
            f"(新規 {created} ・ 修正 {updated} ・ 変更なし {unchanged})"
        ),
        after={"created": created, "updated": updated, "unchanged": unchanged},
        ip_address=ip_address,
    )
    db.commit()

    return HospitalBulkResult(
        created_count=created,
        updated_count=updated,
        unchanged_count=unchanged,
        rows=results,
        warnings=warnings,
    )


# ==========================================================================
# A-22 정원 관리
# ==========================================================================


def capacity_month(
    db: Session,
    hospital_id: int,
    month: str | None,
    target_date: date | None,
) -> CapacityMonth:
    """한 달치 정원 현황 + 선택한 날짜의 시간대별 상세."""
    hospital = db.get(Hospital, hospital_id)
    if hospital is None:
        raise MasterDataError("会場が見つかりません。")

    if month:
        year, mon = (int(p) for p in month.split("-"))
    elif target_date:
        year, mon = target_date.year, target_date.month
    else:
        today = date.today()
        year, mon = today.year, today.month

    first = date(year, mon, 1)
    last = date(year, mon, monthrange(year, mon)[1])

    month_schedules = db.execute(
        select(HospitalSchedule)
        .where(
            HospitalSchedule.hospital_id == hospital_id,
            HospitalSchedule.event_date >= first,
            HospitalSchedule.event_date <= last,
        )
        .order_by(HospitalSchedule.event_date)
    ).scalars().all()

    days = []
    for schedule in month_schedules:
        totals = grid.totals_of(schedule)
        if not totals.slot_count:
            continue
        days.append(
            CapacityDay(
                date=schedule.event_date,
                weekday=WEEKDAY_JA[schedule.event_date.weekday()],
                schedule_id=schedule.id,
                capacity=totals.capacity,
                reserved=totals.reserved,
                remaining=max(0, totals.capacity - totals.reserved),
                closed_slots=totals.closed_slots,
                slot_count=totals.slot_count,
                is_all_closed=totals.is_all_closed,
            )
        )

    # 날짜를 고르지 않았으면 이 달의 첫 영업일을 보여 준다.
    # 빈 시간표부터 보여 주면 「데이터가 없다」고 오해한다.
    selected = target_date
    if selected is None or not any(d.date == selected for d in days):
        selected = days[0].date if days else None

    slots: list[CapacitySlot] = []
    if selected is not None:
        slots = [
            CapacitySlot(
                slot_id=s.id,
                start_time=s.start_time.strftime("%H:%M"),
                end_time=s.end_time.strftime("%H:%M"),
                time_label=s.time_label,
                period=s.period,
                capacity=s.capacity,
                reserved=s.reserved_count,
                remaining=s.remaining,
                is_closed=s.is_closed,
            )
            for s in grid.slots_for_date(db, hospital_id, selected)
        ]

    # 회차 목록은 **달 밖의 것도** 전부 준다. 달력이 이 회장이 여는 달로
    # 곧장 건너뛰려면, 지금 보고 있는 달에 아무것도 없어도 다음 회차가
    # 언제인지 알아야 한다. 스무 곳 × 여러 회차를 월 단위로 넘겨 가며
    # 찾게 하는 것은 사람이 할 일이 아니다.
    today = date.today()
    schedule_stats = _schedule_slot_stats(db)
    schedules = [
        _to_schedule_row(s, schedule_stats, today) for s in hospital.schedules
    ]
    selected_schedule_id = next(
        (d.schedule_id for d in days if d.date == selected), None
    )

    return CapacityMonth(
        hospital_id=hospital.id,
        hospital_name=hospital.name,
        month=f"{year:04d}-{mon:02d}",
        days=days,
        selected_date=selected,
        selected_schedule_id=selected_schedule_id,
        schedules=schedules,
        slots=slots,
    )


def update_slots(
    db: Session,
    hospital_id: int,
    payload: SlotUpdateRequest,
    *,
    admin: AdminUser,
    ip_address: str,
) -> SlotUpdateResult:
    """정원을 조정한다.

    **이미 예약된 인원보다 낮은 정원으로는 내릴 수 없다** (BR-09 / M-6).
    내릴 수 있게 두면 오버부킹이 되고, 당일 회장에서 사고가 난다.
    거부한 항목은 조용히 넘기지 않고 무엇을 왜 못 바꿨는지 돌려준다.
    """
    hospital = db.get(Hospital, hospital_id)
    if hospital is None:
        raise MasterDataError("会場が見つかりません。")

    # (회차, 칸 번호, 새 정원, 새 마감) — 그리드를 만지기 전에 계획을 세운다.
    changes: list[tuple[HospitalSchedule, int, int | None, bool | None]] = []
    schedules: dict[int, HospitalSchedule] = {}

    def load(schedule_id: int) -> HospitalSchedule | None:
        if schedule_id not in schedules:
            schedule = db.get(HospitalSchedule, schedule_id)
            if schedule is None or schedule.hospital_id != hospital_id:
                return None
            grid.counts_of(db, schedule)
            schedules[schedule_id] = schedule
        return schedules[schedule_id]

    # --- ① 시간대 개별 지정 -----------------------------------------------
    if payload.items:
        for item in payload.items:
            schedule_id, index = time_grid.split_slot_id(item.slot_id)
            schedule = load(schedule_id)
            if schedule is None or schedule.capacity_at(index) is None:
                continue
            changes.append((schedule, index, item.capacity, item.is_closed))

    # --- ② 날짜 단위 일괄 -------------------------------------------------
    if payload.dates:
        day_schedules = db.execute(
            select(HospitalSchedule)
            .where(
                HospitalSchedule.hospital_id == hospital_id,
                HospitalSchedule.event_date.in_(payload.dates),
            )
            .order_by(HospitalSchedule.event_date)
        ).scalars().all()

        for schedule in day_schedules:
            grid.counts_of(db, schedule)
            schedules[schedule.id] = schedule
            for index in schedule.open_indexes():
                capacity = (
                    max(0, (schedule.capacity_at(index) or 0) + payload.delta)
                    if payload.delta is not None
                    else None
                )
                changes.append((schedule, index, capacity, payload.set_closed))

    if not changes:
        return SlotUpdateResult(updated=0, message="変更対象がありません。")

    updated = 0
    blocked: list[str] = []
    opened: list[str] = []
    updated_slots: list[str] = []

    for schedule, index, capacity, is_closed in changes:
        touched = False
        before = grid.view_at(schedule, index)
        if before is None:
            continue
        where = f"{schedule.event_date} {before.time_label}"

        if capacity is not None and capacity != before.capacity:
            if capacity < before.reserved_count:
                blocked.append(
                    f"{where} — "
                    f"すでに {before.reserved_count}名が予約されているため"
                    f"定員を {capacity}名に減らすことはできません"
                )
            else:
                was_full = before.remaining == 0
                schedule.set_capacity_at(index, capacity)
                touched = True
                after = grid.view_at(schedule, index)
                if was_full and after and after.remaining > 0 and not after.is_closed:
                    opened.append(where)

        if is_closed is not None and is_closed != schedule.is_closed_at(index):
            was_blocked = schedule.is_closed_at(index)
            schedule.set_closed_at(index, is_closed)
            touched = True
            after = grid.view_at(schedule, index)
            if was_blocked and not is_closed and after and after.remaining > 0:
                opened.append(where)

        if touched:
            updated += 1
            updated_slots.append(where)

    audit_service.write_log(
        db,
        admin=admin,
        action="SLOT_BULK_UPDATE" if payload.dates else "SLOT_UPDATE",
        target_type="hospital",
        target_id=hospital.id,
        target_label=hospital.name,
        after={
            "updated": updated,
            "blocked": len(blocked),
            "delta": payload.delta,
            "set_closed": payload.set_closed,
            "dates": [d.isoformat() for d in payload.dates],
            "updated_slots": updated_slots,
        },
        ip_address=ip_address,
    )
    db.commit()

    # 「빈자리가 언제 열리는지 모른다」를 없앤다 (M-7)
    message = f"{updated}件を変更しました。"
    if opened:
        head = ", ".join(opened[:3])
        more = f" ほか {len(opened) - 3}件" if len(opened) > 3 else ""
        message += f" {head}{more} の時間帯が再度受付可能になりました。"
    if blocked:
        message += f" {len(blocked)}件は変更できませんでした。"

    return SlotUpdateResult(updated=updated, blocked=blocked, message=message)


def reservation_impact(
    db: Session,
    hospital_id: int,
    dates: list[date],
) -> ReservationImpact:
    """그 날짜들에 이미 들어와 있는 예약을 센다.

    취소분은 뺀다. 불비(PENDING)는 **뺀 것이 아니다** — 본인은 예약했다고
    생각하고 그 날 온다. 이메일이 빈 사람은 전화 말고 닿을 길이 없다.
    """
    if not dates:
        return ReservationImpact()

    total, with_email = db.execute(
        select(
            func.count(),
            func.sum(case((Reservation.email != "", 1), else_=0)),
        ).where(
            Reservation.hospital_id == hospital_id,
            Reservation.slot_date.in_(dates),
            Reservation.status != "CANCELLED",
        )
    ).one()

    total = int(total or 0)
    with_email = int(with_email or 0)
    return ReservationImpact(
        total=total,
        with_email=with_email,
        without_email=total - with_email,
    )


def set_holiday(
    db: Session,
    hospital_id: int,
    dates: list[date],
    closed: bool,
    *,
    admin: AdminUser,
    ip_address: str,
) -> SlotUpdateResult:
    """휴진일 설정 = 그 날짜의 전 슬롯을 마감한다.

    휴진일을 별도 테이블로 두지 않는 이유
    ------------------------------------
    이용자 화면은 이미 슬롯의 `is_closed` 를 보고 「접수 안 함」을 그린다.
    휴진일 테이블을 따로 만들면 같은 사실이 두 곳에 적히고, 한쪽만 갱신되면
    「달력에는 휴진인데 예약이 된다」가 된다. 슬롯 하나로 통일한다.
    """
    result = update_slots(
        db,
        hospital_id,
        SlotUpdateRequest(dates=dates, set_closed=closed),
        admin=admin,
        ip_address=ip_address,
    )

    # 닫을 때만 붙인다. 다시 여는 길에는 할 일이 남지 않는다.
    if closed:
        result.impact = reservation_impact(db, hospital_id, dates)
    return result


# ==========================================================================
# A-30 옵션 검사
# ==========================================================================

_OPTION_FIELDS = [
    "code",
    "name",
    "description",
    "note",
    "target_gender",
    "target_age_min",
    "target_age_max",
    "is_active",
    "sort_order",
]


def list_exam_options(db: Session) -> list[ExamOptionRow]:
    used = dict(
        db.execute(
            select(ReservationOption.exam_option_id, func.count())
            .group_by(ReservationOption.exam_option_id)
        ).all()
    )

    options = db.execute(
        select(ExamOption).order_by(ExamOption.sort_order, ExamOption.id)
    ).scalars().all()

    return [
        ExamOptionRow(
            id=o.id,
            code=o.code,
            name=o.name,
            description=o.description,
            note=o.note,
            target_gender=o.target_gender,
            target_gender_label=GENDER_LABELS.get(o.target_gender, o.target_gender),
            target_age_min=o.target_age_min,
            target_age_max=o.target_age_max,
            is_active=o.is_active,
            sort_order=o.sort_order,
            used_count=int(used.get(o.id, 0)),
        )
        for o in options
    ]


def save_exam_option(
    db: Session,
    option_id: int | None,
    payload: ExamOptionSaveRequest,
    *,
    admin: AdminUser,
    ip_address: str,
) -> ExamOptionRow:
    duplicate = db.execute(
        select(ExamOption).where(ExamOption.code == payload.code)
    ).scalar_one_or_none()

    if duplicate is not None and duplicate.id != option_id:
        raise MasterDataError(f"検査コード「{payload.code}」は既に使用されています。")

    if option_id:
        option = db.get(ExamOption, option_id)
        if option is None:
            raise MasterDataError("オプション検査が見つかりません。")
        before = audit_service.snapshot(option, _OPTION_FIELDS)
        action = "EXAM_OPTION_UPDATE"
    else:
        option = ExamOption()
        db.add(option)
        before = {}
        action = "EXAM_OPTION_CREATE"

    for field in _OPTION_FIELDS:
        setattr(option, field, getattr(payload, field))

    db.flush()
    after = audit_service.snapshot(option, _OPTION_FIELDS)

    audit_service.write_log(
        db,
        admin=admin,
        action=action,
        target_type="exam_option",
        target_id=option.id,
        target_label=f"{option.code} {option.name}",
        before=before or None,
        after=audit_service.diff(before, after) if before else after,
        ip_address=ip_address,
    )
    db.commit()

    return next(o for o in list_exam_options(db) if o.id == option.id)


def delete_exam_option(
    db: Session,
    option_id: int,
    *,
    admin: AdminUser,
    ip_address: str,
) -> str:
    """옵션 검사를 삭제한다.

    이미 신청된 예약이 있으면 지우지 않고 「비활성」을 권한다.
    지워 버리면 그 예약자가 무엇을 신청했는지가 목록에서 사라진다.
    """
    option = db.get(ExamOption, option_id)
    if option is None:
        raise MasterDataError("オプション検査が見つかりません。")

    used = db.execute(
        select(func.count())
        .select_from(ReservationOption)
        .where(ReservationOption.exam_option_id == option_id)
    ).scalar() or 0

    if used:
        raise MasterDataError(
            f"この検査を申し込んだ予約が {used}件あるため削除できません。"
            "新規申込を防ぐには「有効」をオフにしてください。"
        )

    audit_service.write_log(
        db,
        admin=admin,
        action="EXAM_OPTION_DELETE",
        target_type="exam_option",
        target_id=option.id,
        target_label=f"{option.code} {option.name}",
        before=audit_service.snapshot(option, _OPTION_FIELDS),
        ip_address=ip_address,
    )

    db.delete(option)
    db.commit()
    return f"{option.name} を削除しました。"


def export_exam_options(db: Session) -> bytes:
    """옵션 검사 목록을 CSV(BOM 포함 UTF-8)로 내보낸다."""
    options = db.execute(
        select(ExamOption).order_by(ExamOption.sort_order, ExamOption.id)
    ).scalars().all()

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)

    # CSV 헤더
    writer.writerow([
        "コード",
        "検査名",
        "説明",
        "準備事項",
        "対象性別",
        "最小年齢",
        "最大年齢",
        "表示順",
        "有効フラグ",
    ])

    for o in options:
        writer.writerow([
            o.code,
            o.name,
            o.description,
            o.note,
            o.target_gender,
            str(o.target_age_min),
            str(o.target_age_max),
            str(o.sort_order),
            "1" if o.is_active else "0",
        ])

    return "\ufeff".encode("utf-8") + buffer.getvalue().encode("utf-8")


def import_exam_options(
    db: Session,
    raw_csv: bytes,
    *,
    admin: AdminUser,
    ip_address: str,
    dry_run: bool = False,
) -> dict:
    """CSV 파일을 읽어 옵션 검사 마스터를 갱신/추가한다."""
    try:
        text = raw_csv.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw_csv.decode("cp932")
        except UnicodeDecodeError:
            raise MasterDataError(
                "文字コードを特定できないファイルです。"
                "「CSV UTF-8（カンマ区切り）」で再度保存してください。"
            )

    try:
        delimiter = csv.Sniffer().sniff(text[:1024], delimiters=",\t;").delimiter
    except csv.Error:
        delimiter = ","

    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        headers = next(reader)
    except StopIteration:
        raise MasterDataError("内容が空です。")

    # 필수 헤더가 있는지 간단히 확인 (코드, 검사명 등)
    if "コード" not in headers or "検査名" not in headers:
        raise MasterDataError(
            "ヘッダー行が見つかりません。"
            "「CSV 書き出し」で取得したファイル形式をそのまま維持してください。"
        )

    # 헤더 인덱스 매핑
    idx = {h: i for i, h in enumerate(headers)}

    def get_val(row: list[str], key: str, default: str = "") -> str:
        if key not in idx or idx[key] >= len(row):
            return default
        return row[idx[key]].strip()

    created_list = []
    updated_list = []
    created_count = 0
    updated_count = 0

    for i, row in enumerate(reader, start=2):
        if not any(row):  # 빈 줄 무시
            continue

        code = get_val(row, "コード")
        name = get_val(row, "検査名")

        if not code or not name:
            raise MasterDataError(f"{i}行目: コードと検査名は必須です。")

        try:
            payload = ExamOptionSaveRequest(
                code=code,
                name=name,
                description=get_val(row, "説明"),
                note=get_val(row, "準備事項"),
                target_gender=get_val(row, "対象性別", "ALL").upper(),
                target_age_min=int(get_val(row, "最小年齢", "40")),
                target_age_max=int(get_val(row, "最大年齢", "74")),
                sort_order=int(get_val(row, "並び順", "0")),
                is_active=get_val(row, "使用可否", "1") not in ("0", "false", "False", ""),
            )
        except ValueError as e:
            raise MasterDataError(f"{i}行目: 数値の形式が正しくありません。") from e

        # 기존 확인
        existing = db.execute(
            select(ExamOption).where(ExamOption.code == code)
        ).scalar_one_or_none()

        item_preview = {
            "code": payload.code,
            "name": payload.name,
            "description": payload.description,
            "note": payload.note,
            "target_gender": payload.target_gender,
            "target_age_min": payload.target_age_min,
            "target_age_max": payload.target_age_max,
            "sort_order": payload.sort_order,
            "is_active": payload.is_active,
        }

        if existing:
            updated_count += 1
            updated_list.append(item_preview)
            if not dry_run:
                save_exam_option(db, existing.id, payload, admin=admin, ip_address=ip_address)
        else:
            created_count += 1
            created_list.append(item_preview)
            if not dry_run:
                save_exam_option(db, None, payload, admin=admin, ip_address=ip_address)

    return {
        "created": created_count,
        "updated": updated_count,
        "created_items": created_list,
        "updated_items": updated_list,
    }


# ==========================================================================
# 화면 보조
# ==========================================================================


def hospital_choices(db: Session) -> list[dict]:
    """검색 조건의 회장 선택지."""
    return [
        {
            "id": h.id,
            "code": h.code,
            "name": h.name,
            "region": h.region,
            "event_date": h.event_date.isoformat() if h.event_date else None,
            # 회장 하나에 개최일이 여럿이다. 검색 조건에서 「회장 + 날짜」를
            # 고르게 하려면 목록 단계에서 이 배열이 있어야 한다.
            "schedules": [
                {
                    "id": s.id,
                    "event_date": s.event_date.isoformat(),
                    "weekday": WEEKDAY_JA[s.event_date.weekday()],
                    "is_booking_open": s.is_open_for_booking(),
                    "is_past": s.is_past,
                }
                for s in h.schedules
            ],
            "is_visible": h.is_visible,
        }
        for h in db.execute(
            select(Hospital).order_by(Hospital.sort_order, Hospital.id)
        ).scalars()
    ]


def available_slots(
    db: Session,
    hospital_id: int,
    target_date: date,
) -> list[dict]:
    """일시 변경·우편 접수 화면에서 고를 수 있는 슬롯 목록.

    만석·마감·지난 시간도 **감추지 않고** 이유를 붙여 보여 준다.
    목록에서 사라지면 스태프가 「신청서에 적힌 시간이 없다」며 헤맨다.
    """
    now = datetime.now()
    slots = grid.slots_for_date(db, hospital_id, target_date)

    result = []
    for s in slots:
        if datetime.combine(s.slot_date, s.start_time) <= now:
            reason = "過去の時間"
        elif s.is_closed:
            reason = "受付なし"
        elif s.remaining <= 0:
            reason = "締切"
        else:
            reason = ""

        result.append(
            {
                "slot_id": s.id,
                "time_label": s.time_label,
                "period": s.period,
                "capacity": s.capacity,
                "reserved": s.reserved_count,
                "remaining": s.remaining,
                "selectable": not reason,
                "reason": reason,
            }
        )
    return result

