"""예약 조회 (U-20).

    예약번호 하나만 받아 예약 내용을 보여 준다. **읽기 전용이다.**

왜 예약번호만 받는가
--------------------
예약번호는 무작위 12자이고 대소문자를 구별한다(core/reservation_no.py).
62^12 ≈ 3.2 × 10^21 가지이므로 **번호 자체가 열쇠**다.
반대로 성명·생년월일·보험증은 가족이나 동거인이라면 알 수 있는 정보라
열쇠가 될 수 없다. 그래서 본인 확인 화면은 예약번호를 알려 주지 않는다.
(services/verify_service.py 의 ALREADY_RESERVED 분기)

여기서 고칠 수 있는 것은 없다
-----------------------------
변경·취소는 웹에서 할 수 없다(BR-10). 전화로만 접수하며 검진일 3일 전까지다.
이 화면은 「무엇을 예약했는지」를 확인시켜 주는 것까지가 역할이며,
바꾸는 길은 전화번호를 크게 보여 주는 것으로 안내한다.

추측을 막는다
-------------
번호가 열쇠이므로 **찍어 맞히는 시도**가 유일한 공격 경로다.
아무리 넓은 공간이라도 무제한으로 두드릴 수 있게 두지 않는다.
IP 단위로 시도 횟수를 제한한다. (plan.md §13.2)
"""

from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core import reservation_no as res_no
from app.core.config import settings
from app.models.lookup_attempt import LookupAttempt
from app.models.reservation import Reservation
from app.schemas.lookup import LookupResult
from app.schemas.reservation import ReservedHospital, ReservedOption

# --------------------------------------------------------------------------
# 시도 횟수 제한
# --------------------------------------------------------------------------
# 한 IP 가 이 구간(초) 안에 이만큼 실패하면 잠시 막는다.
# 정상 이용자는 자기 번호를 보고 옮겨 적으므로 몇 번이면 충분하지만,
# 12자를 손으로 치다 보면 두세 번은 틀린다. 그 여유는 남긴다.
FAIL_LIMIT = 10
WINDOW_SECONDS = 300      # 5분
BLOCK_SECONDS = 600       # 10분

# 성공한 조회는 세지 않는다. 자기 예약을 여러 번 확인하는 것은 정상이다.


class LookupBlocked(Exception):
    """시도 횟수를 넘겨 잠시 막힌 상태."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("照会の試行回数が多すぎます。")
        self.retry_after = retry_after


class LookupNotFound(Exception):
    """그런 예약번호가 없다.

    「번호가 틀렸다」와 「그 예약은 이미 지났다」를 구별해 알려 주지 않는다.
    구별해 주면 어떤 번호가 실재했는지를 알려 주는 셈이 된다.
    """


def check_rate(db: Session, ip: str) -> None:
    """이 IP 가 더 시도해도 되는지 본다. 안 되면 예외를 던진다."""
    if not ip:
        return

    record = db.get(LookupAttempt, ip)
    if record is None:
        return

    now = datetime.now()

    if record.blocked_until is not None and record.blocked_until > now:
        raise LookupBlocked(int((record.blocked_until - now).total_seconds()) + 1)

    # 구간을 넘겼으면 기록을 버린다. 오래된 실패까지 계속 세면
    # 하루에 몇 번씩 조회하는 정상 이용자도 언젠가 막힌다.
    if (now - record.window_start).total_seconds() >= WINDOW_SECONDS:
        db.delete(record)
        db.commit()


def record_failure(db: Session, ip: str) -> None:
    """빗나간 조회를 한 건 센다. 한도에 닿으면 그 시점부터 막힌다."""
    if not ip:
        return

    now = datetime.now()
    record = db.get(LookupAttempt, ip)

    if record is None:
        record = LookupAttempt(
            ip_address=ip, fail_count=0, window_start=now, blocked_until=None
        )
        db.add(record)
    elif (now - record.window_start).total_seconds() >= WINDOW_SECONDS:
        # 구간이 지났으면 0부터 다시 센다
        record.fail_count = 0
        record.window_start = now

    record.fail_count += 1

    if record.fail_count >= FAIL_LIMIT:
        record.blocked_until = now + timedelta(seconds=BLOCK_SECONDS)
        # 막은 뒤에는 다시 0부터 센다. 풀린 직후에 곧바로 다시 막히지 않게 한다.
        record.fail_count = 0
        record.window_start = now

    db.commit()


def reset(db: Session, ip: str = "") -> int:
    """시도 기록을 지운다. 인자가 없으면 전부.

    검증 스크립트가 쓴다. 「몇 번째 실행인지에 따라 결과가 달라지는」 검증은
    아무것도 증명하지 못하므로, 매 실행 전에 이 상태를 지울 수 있어야 한다.
    """
    stmt = delete(LookupAttempt)
    if ip:
        stmt = stmt.where(LookupAttempt.ip_address == ip)

    removed = db.execute(stmt).rowcount or 0
    db.commit()
    return removed


# --------------------------------------------------------------------------
# 조회
# --------------------------------------------------------------------------


def find(db: Session, reservation_no: str, *, ip: str = "") -> Reservation:
    """예약번호로 예약을 찾는다. 없으면 `LookupNotFound`.

    형식이 틀린 번호는 DB 를 보기 전에 걸러 낸다. 영숫자 12자가 아니면
    존재할 수 없는 번호이므로 조회할 이유가 없다.
    다만 **실패로는 센다.** 형식만 바꿔 가며 두드리는 것도 시도이기 때문이다.
    """
    check_rate(db, ip)

    value = (reservation_no or "").strip()

    if not res_no.is_valid(value):
        record_failure(db, ip)
        raise LookupNotFound()

    # 컬럼 콜레이션이 `utf8mb4_bin` 이라 이 비교는 대소문자를 구별한다.
    found = db.execute(
        select(Reservation).where(Reservation.reservation_no == value)
    ).scalars().unique().one_or_none()

    if found is None:
        record_failure(db, ip)
        raise LookupNotFound()

    return found


# --------------------------------------------------------------------------
# 화면 문구
# --------------------------------------------------------------------------

# 변경·취소를 접수하는 기한 (검진일 며칠 전까지). BR-10
CANCEL_DEADLINE_DAYS = 3

STATUS_LABELS = {
    "CONFIRMED": "予約確定",
    "PENDING": "仮受付（担当者確認中）",
    "CANCELLED": "キャンセル済み",
}
CHANNEL_LABELS = {"WEB": "インターネット受付", "POSTAL": "郵送受付"}

WEEKDAY_JA = ["月", "火", "水", "木", "金", "土", "日"]


def contact() -> dict[str, str]:
    """문의처. 조회에 실패한 사람에게도 함께 내려 준다.

    막힌 이용자에게 거절 문구만 주면 그대로 전화가 되는데,
    그 전화번호조차 화면에 없으면 어디로 걸어야 할지부터 찾아야 한다.
    """
    return {
        "tel": settings.CONTACT_TEL,
        "email": settings.CONTACT_EMAIL,
        "hours": settings.CONTACT_HOURS,
    }


def _change_notice(reservation: Reservation) -> str:
    """「고칠 수 없다」로 끝내지 않고 「어떻게 하면 되는지」를 말한다. (P-9)

    상태에 따라 할 말이 다르다. 취소된 예약에 「3일 전까지 전화하세요」는 무의미하다.
    """
    if reservation.status == "CANCELLED":
        return (
            "この予約はキャンセルされました。再度お申し込みいただく場合は、トップ画面の"
            "「予約する」から新しくお申し込みください。"
        )

    if reservation.status == "PENDING":
        return (
            "受付はいたしましたが、確認が必要な項目があるため担当者が確認中です。"
            "まもなくご連絡いたします。お急ぎの場合は下記の番号へお電話ください。"
        )

    # 「아래 회장 또는 문의처로」였다. 그런데 회장은 검진 당일에만 빌리는
    # 장소라 고유 전화번호가 없어(20곳 전부 빈칸) 걸 곳이 예약 센터뿐이다.
    # 회장 칸에는 이제 이름과 주소만 적으므로 문구도 맞춘다.
    return (
        "ご予約の変更・キャンセルは、このサイトではお受けできません。"
        f"受診日の{CANCEL_DEADLINE_DAYS}日前までに下記の予約センターへ"
        "お電話いただければ、担当者が対応いたします。"
    )


def _viewable_until(reservation: Reservation) -> datetime:
    """이 화면에서 볼 수 있는 마지막 시각.

    검진 시각 + 유예가 지나면 예약 기록 자체가 지워진다(purge_service).
    「어제까지 보였는데 오늘은 안 보인다」가 문의가 되지 않도록 미리 알린다.
    """
    return datetime.combine(reservation.slot_date, reservation.start_time) + timedelta(
        minutes=settings.RESERVATION_EXPIRE_GRACE_MINUTES
    )


def build_result(reservation: Reservation) -> LookupResult:
    """조회 화면이 그대로 그릴 수 있는 형태로 만든다."""
    hospital = reservation.hospital

    return LookupResult(
        reservation_no=reservation.reservation_no,
        status=reservation.status,
        status_label=STATUS_LABELS.get(reservation.status, reservation.status),
        # 취소된 예약에는 붙이지 않는다. 이미 없어진 예약에 「이 날은 검진을
        # 하지 않습니다」를 더하면 무엇을 하라는 말인지 알 수 없다.
        is_holiday=(
            reservation.status != "CANCELLED"
            and reservation.schedule is not None
            and reservation.schedule.is_holiday()
        ),
        full_name=reservation.full_name,
        full_name_kana=reservation.full_name_kana,
        gender_label=reservation.gender_label,
        birth_date=reservation.birth_date,
        hospital=ReservedHospital(
            id=hospital.id,
            name=hospital.name,
            address=hospital.address,
            tel=hospital.contact_tel,
            access_info=hospital.access_info,
        ),
        slot_date=reservation.slot_date,
        weekday=WEEKDAY_JA[reservation.slot_date.weekday()],
        time_label=reservation.time_label,
        postal_code=reservation.postal_code,
        address=reservation.address,
        address_detail=reservation.address_detail,
        building=reservation.building,
        tel_mobile=reservation.tel_mobile,
        tel_home=reservation.tel_home,
        email=reservation.email,
        # 옵션 이름은 예약 시점의 값이 행에 복사되어 있다.
        # 마스터의 이름이 나중에 바뀌어도 「그때 신청한 것」이 그대로 보인다.
        options=[
            ReservedOption(code=o.option_code, name=o.option_name)
            for o in reservation.options
        ],
        channel=reservation.channel,
        channel_label=CHANNEL_LABELS.get(reservation.channel, reservation.channel),
        change_notice=_change_notice(reservation),
        cancel_deadline_days=CANCEL_DEADLINE_DAYS,
        contact_tel=settings.CONTACT_TEL,
        contact_email=settings.CONTACT_EMAIL,
        contact_hours=settings.CONTACT_HOURS,
        viewable_until=_viewable_until(reservation).strftime("%Y-%m-%d %H:%M"),
    )
