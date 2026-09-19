"""예약 확정 · 예약번호 발행 (plan.md §11.4 / §11.5 / BR-03 / BR-04).

예약 확정은 이 시스템에서 **되돌릴 수 없는 유일한 조작**이다.
이용자는 웹에서 스스로 취소할 수 없으므로(BR-10), 여기서 잘못 확정되면
전부 전화 문의가 된다. 그래서 다음 세 가지를 한 트랜잭션 안에서 처리한다.

    1. 슬롯 행을 잠그고(`SELECT ... FOR UPDATE`) 빈자리를 다시 확인
    2. 중복 예약(BR-03) 재확인
    3. 예약번호 발행 + `reserved_count` 증가 + 예약 INSERT

화면에서 「예약 가능」으로 보였다는 사실은 아무것도 보증하지 않는다.
그 사이에 다른 사람이 마지막 한 자리를 가져갔을 수 있다.
확정 판정은 언제나 잠금 이후의 DB 값으로 한다.
"""

import unicodedata
from datetime import date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import reservation_no as res_no
from app.core import time_grid
from app.core.config import settings
from app.core.dates import fiscal_year
from app.core.security import read_verify_token
from app.core.text_utils import normalize_name
from app.models.admin import AdminUser
from app.models.exam_option import ExamOption
from app.models.hospital import Hospital, HospitalSchedule
from app.models.reservation import Reservation, ReservationOption
from app.models.target_person import TargetPerson
from app.schemas.reservation import (
    ReservationCreateRequest,
    ReservationErrorCode,
    ReservationResult,
    ReservedHospital,
    ReservedOption,
)
from app.services import audit_service, mail_service
from app.services import slot_grid_service as grid
from app.services.slot_grid_service import SlotView

WEEKDAY_JA = ["月", "火", "水", "木", "金", "土", "日"]


class ReservationError(Exception):
    """예약을 받을 수 없는 업무상의 이유.

    입력값 오류(422)와 구별한다. 이쪽은 「입력은 맞지만 지금은 안 된다」이며,
    이용자에게 다음 행동을 알려 줘야 한다.
    """

    def __init__(
        self,
        code: ReservationErrorCode,
        message: str,
        *,
        hints: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hints = hints or []


# --------------------------------------------------------------------------
# 안내 문구
# --------------------------------------------------------------------------

MSG_VERIFY_REQUIRED = (
    "本人確認から時間が長く経過したため、最初から確認し直す必要があります。"
    "お手数ですが、本人確認から再度お手続きください。"
)
MSG_SLOT_FULL = (
    "ご選択いただいた時間は、先ほど他の方の予約により締切となりました。"
    "他の時間や別の日程をご選択ください。"
)
MSG_SLOT_CLOSED = "ご選択いただいた時間は現在受け付けておりません。他の時間をご選択ください。"
MSG_SLOT_PAST = "ご選択いただいた時間は既に過ぎています。別の日程をご選択ください。"
MSG_SLOT_NOT_FOUND = "ご選択いただいた時間が見つかりません。会場と日時を再度ご選択ください。"
MSG_BOOKING_CLOSED = (
    "ご選択いただいた会場はインターネット受付が締切となりました。"
    "他の会場をご選択いただくか、以下のお問い合わせ先までお電話ください。"
)
MSG_DUPLICATE = (
    "今年、既に予約された履歴があります。"
    "健康診断は1年に1回のみお申し込みいただけます。"
)


# ==========================================================================
# 예약번호 발행
# ==========================================================================


ISSUE_RETRY = 8


def issue_reservation_no(db: Session) -> str:
    """아직 쓰이지 않은 예약번호를 하나 발행한다. (plan.md §11.5)

    번호는 무작위 12자이므로 순번을 세지 않는다. 회장도 회계연도도 보지 않는다.
    이미 있는 번호가 나올 확률은 사실상 0 이지만, 「사실상 0」에 시스템을
    맡기지는 않는다. 나올 때까지 다시 뽑되 횟수를 제한한다.

    여기서의 조회는 `reservation_no` 컬럼을 그대로 보므로, 그 컬럼에 지정된
    `utf8mb4_bin` 콜레이션에 따라 **대소문자를 구별해** 판정된다.
    UNIQUE 제약도 같은 콜레이션을 쓰므로 두 판정이 어긋나지 않는다.
    (core/reservation_no.py · models/reservation.py)
    최종 안전장치는 `reservation_no` 의 UNIQUE 제약이다.
    """
    for _ in range(ISSUE_RETRY):
        candidate = res_no.generate()
        taken = db.execute(
            select(Reservation.id)
            .where(Reservation.reservation_no == candidate)
            .limit(1)
        ).scalar()
        if taken is None:
            return candidate

    # 여기에 닿았다면 난수원이 고장 났다고 보는 편이 맞다.
    # 잘못된 번호로 예약을 확정하느니 확정하지 않는 쪽이 낫다.
    raise RuntimeError("予約番号を発行できなかった。乱数生成器を確認すること。")


# ==========================================================================
# 중복 예약 판정 (BR-03)
# ==========================================================================


def find_duplicate(
    db: Session,
    *,
    target_person_id: int | None,
    last_name: str,
    first_name: str,
    birth_date: date,
    tel_mobile: str,
    tel_home: str,
    year: int,
    exclude_id: int | None = None,
) -> Reservation | None:
    """당해 연도에 이미 유효한 예약이 있는지 찾는다.

    1순위는 **대상자 ID** 다. 명부에서 사람을 특정한 뒤 그 ID 로 예약을 찾는
    것이 가장 정확하다. 표기 흔들림이나 전화번호 변경에 흔들리지 않는다.

    2순위는 「성명 + 생년월일 + 전화번호」다 (BR-03). 우편 접수처럼
    명부와 연결되지 않은 예약을 잡기 위한 그물이며,
    **보험자 번호는 쓰지 않는다** — 가족이 공유하는 경우가 있다 (Q39).
    """
    base = select(Reservation).where(
        Reservation.fiscal_year == year,
        Reservation.status != "CANCELLED",
    )
    if exclude_id is not None:
        base = base.where(Reservation.id != exclude_id)

    if target_person_id is not None:
        found = db.execute(
            base.where(Reservation.target_person_id == target_person_id).limit(1)
        ).scalars().first()
        if found is not None:
            return found

    def phone_digits(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value or "")
        return "".join(character for character in normalized if character.isdigit())

    phones = {
        digits
        for digits in (phone_digits(tel_mobile), phone_digits(tel_home))
        if digits
    }
    if not phones:
        return None

    # 하이픈·전각 숫자·성명 공백 표기가 달라도 같은 사람을 잡아야 한다.
    # DB 함수만으로 NFKC 정규화를 재현하기 어렵기 때문에, 회계연도와
    # 생년월일로 충분히 좁힌 뒤 마지막 비교를 Python 에서 수행한다.
    candidates = db.execute(
        base.where(Reservation.birth_date == birth_date)
    ).scalars().all()
    normalized_last = normalize_name(last_name)
    normalized_first = normalize_name(first_name)
    for candidate in candidates:
        if normalize_name(candidate.last_name) != normalized_last:
            continue
        if normalize_name(candidate.first_name) != normalized_first:
            continue
        candidate_phones = {
            digits
            for digits in (
                phone_digits(candidate.tel_mobile),
                phone_digits(candidate.tel_home),
            )
            if digits
        }
        if phones.intersection(candidate_phones):
            return candidate
    return None


# ==========================================================================
# 슬롯 확보
# ==========================================================================


def lock_slot(db: Session, slot_id: int, now: datetime) -> SlotView:
    """그 날의 예약 수 행을 잠그고 예약 가능한지 판정한다.

    잠근 뒤에 판정하는 것이 핵심이다. 판정하고 나서 잠그면 그 사이에
    다른 트랜잭션이 마지막 한 자리를 가져갈 수 있다.

    잠금 단위가 넓어졌다
    --------------------
    예전에는 슬롯 한 행을 잠갔다. 지금은 그 날의 예약 수 한 행을 잠그므로
    **같은 날 다른 시간대를 고른 두 사람이 서로를 기다린다.** 회장 1곳의
    하루가 161명이고 웹 접수가 초당 몇 건 수준이라 이 규모에서는 문제가
    되지 않는다.

    대신 얻는 것이 있다 — 잠그는 것은 `reservation_counts` 이고
    **마스터 행(`hospital_schedules`)은 잠그지 않는다.** 담당자가 정원을
    고치는 동안에도 예약이 들어온다.
    """
    schedule_id, index = time_grid.split_slot_id(slot_id)

    # 잠금이 먼저다. 회차를 읽고 나서 잠그면 그 사이에 값이 바뀐다.
    counts = grid.lock_counts(db, schedule_id)
    if counts is None:
        raise ReservationError(ReservationErrorCode.SLOT_NOT_FOUND, MSG_SLOT_NOT_FOUND)

    schedule = db.get(HospitalSchedule, schedule_id)
    slot = grid.view_at(schedule, index) if schedule else None

    if slot is None:
        raise ReservationError(ReservationErrorCode.SLOT_NOT_FOUND, MSG_SLOT_NOT_FOUND)

    if datetime.combine(slot.slot_date, slot.start_time) <= now:
        raise ReservationError(ReservationErrorCode.SLOT_PAST, MSG_SLOT_PAST)

    if slot.is_closed:
        raise ReservationError(ReservationErrorCode.SLOT_CLOSED, MSG_SLOT_CLOSED)

    if slot.reserved_count >= slot.capacity:
        raise ReservationError(
            ReservationErrorCode.SLOT_FULL,
            MSG_SLOT_FULL,
            hints=[
                "同じ会場の別の時間帯に空きがある場合があります",
                "別の日程をご選択いただくと、空きのある時間帯が見つかる場合があります",
            ],
        )

    return slot


# ==========================================================================
# 예약 확정 (웹)
# ==========================================================================


def create_web_reservation(
    db: Session,
    payload: ReservationCreateRequest,
    *,
    now: datetime | None = None,
    ip_address: str = "",
) -> ReservationResult:
    """U-16 「이 내용으로 예약」의 처리 본체."""
    now = now or datetime.now()

    # --- ① 본인 확인 토큰 -------------------------------------------------
    person_id = read_verify_token(payload.verify_token)
    if person_id is None:
        raise ReservationError(
            ReservationErrorCode.VERIFY_REQUIRED,
            MSG_VERIFY_REQUIRED,
            hints=["本人確認はセキュリティのため、30分が経過すると無効になります"],
        )

    person = db.get(TargetPerson, person_id)
    if person is None:
        raise ReservationError(ReservationErrorCode.VERIFY_REQUIRED, MSG_VERIFY_REQUIRED)

    # --- ② 슬롯 잠금 ------------------------------------------------------
    slot = lock_slot(db, payload.slot_id, now)
    hospital = db.get(Hospital, slot.hospital_id)
    if hospital is None:
        raise ReservationError(ReservationErrorCode.SLOT_NOT_FOUND, MSG_SLOT_NOT_FOUND)

    # 접수 마감일(予約終了)을 여기서 한 번 더 본다. 목록에서 이미 걸렀지만,
    # 화면을 열어 둔 채 자정을 넘기면 마감된 회차로 요청이 들어온다.
    #
    # **회장이 아니라 회차를 본다.** 같은 회장이 여러 날 열기 때문에,
    # 회장 하나의 마감일로 판정하면 9월 회차가 끝났다는 이유로 아직 한 달
    # 남은 12월 회차까지 막히거나, 그 반대가 된다.
    #
    # 막는 것은 **웹 접수뿐이다.** 우편 신청서를 스태프가 대신 넣는 경로
    # (`admin_reservation_service.create_postal`)는 막지 않는다. 마감일 직전에
    # 부친 우편은 마감 뒤에 도착하는 것이 정상이고, 그것을 넣지 못하면
    # 종이로 신청한 사람만 접수가 안 되는 셈이 된다. 대신 관리 화면의
    # 회장 목록에 마감 여부를 표시해 스태프가 알고 넣게 한다.
    schedule = db.get(HospitalSchedule, slot.schedule_id)
    if schedule is not None and not schedule.is_open_for_booking(now.date()):
        closed_on = schedule.booking_close_date or schedule.event_date
        raise ReservationError(
            ReservationErrorCode.BOOKING_CLOSED,
            MSG_BOOKING_CLOSED,
            hints=[
                f"{hospital.name} {schedule.event_date.isoformat()} 開催回の"
                f"インターネット受付は {closed_on.isoformat()} に締め切られました",
                "同じ会場の別の日程や、他の会場はまだ受付中の場合があります",
            ],
        )

    year = fiscal_year(slot.slot_date)

    # --- ③ 중복 예약 재확인 (BR-03) ---------------------------------------
    # U-11 에서도 확인했지만, 그 사이에 우편 접수로 등록되었을 수 있다.
    duplicate = find_duplicate(
        db,
        target_person_id=person.id,
        last_name=person.last_name,
        first_name=person.first_name,
        birth_date=person.birth_date,
        tel_mobile=payload.tel_mobile,
        tel_home=payload.tel_home,
        year=year,
    )
    if duplicate is not None:
        # 여기서도 예약번호를 알려 주지 않는다. 본인 확인 화면과 같은 이유다.
        # (services/verify_service.py 의 ALREADY_RESERVED 분기)
        raise ReservationError(
            ReservationErrorCode.DUPLICATE_RESERVATION,
            MSG_DUPLICATE,
            hints=[
                "予約内容は予約時にご案内した予約番号でご確認いただけます",
                "予約番号をお忘れの場合や予約の変更・キャンセルをご希望の場合は、下記連絡先までお電話ください",
            ],
        )

    # --- ④ 예약 생성 ------------------------------------------------------
    reservation = Reservation(
        reservation_no=issue_reservation_no(db),
        schedule_id=slot.schedule_id,
        hospital_id=hospital.id,
        slot_date=slot.slot_date,
        start_time=slot.start_time,
        end_time=slot.end_time,
        channel="WEB",
        status="CONFIRMED",
        target_person_id=person.id,
        # 신원은 명부 값을 복사한다. 화면에서 온 값을 믿지 않는다.
        last_name=person.last_name,
        first_name=person.first_name,
        last_name_kana=person.last_name_kana,
        first_name_kana=person.first_name_kana,
        middle_name=person.middle_name,
        middle_name_kana=person.middle_name_kana,
        gender=person.gender,
        birth_date=person.birth_date,
        insurer_no=person.insurer_no,
        insurance_symbol=person.insurance_symbol,
        insurance_no=person.insurance_no,
        postal_code=payload.postal_code,
        address=payload.address,
        address_detail=payload.address_detail,
        building=payload.building,
        tel_mobile=payload.tel_mobile,
        tel_home=payload.tel_home,
        email=payload.email,
        fiscal_year=year,
    )
    db.add(reservation)

    grid.reserved_delta(db, slot.schedule_id, slot.index, 1)
    db.flush()

    _attach_options(db, reservation, [o.id for o in payload.options])
    db.flush()

    # --- ⑤ 완료 메일 (BR-11) ----------------------------------------------
    # 발송 실패가 예약을 깨뜨리지 않는다. 실패는 이력에 남기고 사람이 본다.
    mail_log = mail_service.send_reserve_complete(db, reservation)

    audit_service.write_system_log(
        db,
        action="RESERVATION_CREATE_WEB",
        target_type="reservation",
        target_id=reservation.id,
        target_label=f"{reservation.reservation_no} {reservation.full_name}",
        after={
            "reservation_no": reservation.reservation_no,
            "hospital": hospital.name,
            "slot_date": reservation.slot_date,
            "time": reservation.time_label,
        },
    )

    db.commit()
    db.refresh(reservation)

    return build_result(reservation, hospital, mail_log_status=mail_log.status)


def _attach_options(db: Session, reservation: Reservation, option_ids: list[int]) -> None:
    """옵션 검사를 붙인다.

    타깃 조건(BR-13)에 맞지 않는 옵션이 섞여 들어오면 조용히 버린다.
    화면에는 조건에 맞는 것만 나오므로, 맞지 않는 값이 온 것은
    이용자의 선택이 아니라 조작이거나 화면 갱신 지연이다.
    """
    if not option_ids:
        return

    from app.core.dates import age_on

    age = age_on(reservation.birth_date, reservation.slot_date)

    options = db.execute(
        select(ExamOption).where(ExamOption.id.in_(option_ids))
    ).scalars().all()

    for option in options:
        if not option.matches(reservation.gender, age):
            continue
        db.add(
            ReservationOption(
                reservation_id=reservation.id,
                exam_option_id=option.id,
                option_code=option.code,
                option_name=option.name,
            )
        )


# ==========================================================================
# 응답 조립
# ==========================================================================


def build_result(
    reservation: Reservation,
    hospital: Hospital | None = None,
    *,
    mail_log_status: str = "",
) -> ReservationResult:
    hospital = hospital or reservation.hospital

    # 메일 안내 문구.
    # 「보냈다 / 못 보냈다」를 얼버무리지 않는다. 오지 않은 메일을 기다리게 하면
    # 그것이 그대로 문의 전화가 된다. 못 보낸 경우에는 예약 자체는 멀쩡하다는
    # 사실과, 지금 무엇을 하면 되는지(번호를 적는다)를 함께 말한다.
    mail_sent = mail_log_status == "SUCCESS"
    if mail_sent:
        mail_message = (
            f"{reservation.email} 宛てに予約番号を記載した確認メールをお送りしました。"
        )
    elif not reservation.email:
        mail_message = (
            "メールアドレスを登録されていないため、確認メールをお送りできませんでした。"
            "上記の予約番号を必ずお控えいただくか、この画面を印刷してください。"
        )
    else:
        mail_message = (
            "予約は正常に受け付けられましたが、確認メールはまだお送りできておりません。"
            "上記の予約番号を必ずお控えいただくか、この画面を印刷してください。"
        )

    return ReservationResult(
        reservation_no=reservation.reservation_no,
        status=reservation.status,
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
        options=[
            ReservedOption(code=o.option_code, name=o.option_name)
            for o in reservation.options
        ],
        mail_sent=mail_sent,
        mail_message=mail_message,
        contact_tel=settings.CONTACT_TEL,
        contact_email=settings.CONTACT_EMAIL,
        contact_hours=settings.CONTACT_HOURS,
    )


# ==========================================================================
# 관리자 조작 — 취소 · 슬롯 이동
# ==========================================================================


def release_slot(db: Session, reservation: Reservation) -> SlotView | None:
    """예약이 잡고 있던 자리를 되돌린다. (취소 · 일시 변경 시)

    예약은 `schedule_id` 와 `start_time` 으로 자기 칸을 안다. 슬롯 행이
    없어도 어느 자리를 비워야 하는지 잃지 않는다.
    """
    index = time_grid.index_of(reservation.start_time)
    if index is None:
        return None

    counts = grid.lock_counts(db, reservation.schedule_id)
    if counts is None:
        return None

    counts.add_at(index, -1)

    schedule = db.get(HospitalSchedule, reservation.schedule_id)
    return grid.view_at(schedule, index) if schedule else None


def occupy_slot(db: Session, slot_id: int, now: datetime) -> SlotView:
    """새 슬롯에 자리를 잡는다. 관리자 조작이라도 오버부킹은 허용하지 않는다 (BR-04)."""
    return lock_slot(db, slot_id, now)


def cancel(
    db: Session,
    reservation: Reservation,
    *,
    reason: str,
    cancel_type: str = "",
    admin: AdminUser | None,
    ip_address: str = "",
) -> SlotView | None:
    """예약을 취소하고 정원을 즉시 되돌린다 (BR-10).

    취소된 예약을 지우지 않는 이유는, 「취소했다」는 사실 자체가
    문의 대응에 필요하기 때문이다. 검진일이 지나면 자동 정리로 사라진다.
    """
    before = audit_service.snapshot(reservation, ["status", "cancel_reason", "cancel_type"])

    slot = release_slot(db, reservation)

    reservation.status = "CANCELLED"
    reservation.cancelled_at = datetime.now()
    reservation.cancel_reason = reason[:255]
    reservation.cancel_type = cancel_type

    audit_service.write_log(
        db,
        admin=admin,
        action="RESERVATION_CANCEL",
        target_type="reservation",
        target_id=reservation.id,
        target_label=f"{reservation.reservation_no} {reservation.full_name}",
        before=before,
        after=audit_service.snapshot(reservation, ["status", "cancel_reason", "cancel_type"]),
        ip_address=ip_address,
    )

    return slot


def released_seat_message(slot: SlotView | None, hospital_name: str) -> str:
    """「빈자리가 언제 열리는지 모른다」를 없애기 위한 즉시 피드백 (M-7)."""
    if slot is None:
        return "ご予約をキャンセルしました。"
    return (
        f"{hospital_name} {slot.slot_date.isoformat()} {slot.time_label} の時間帯に "
        f"1枠の空きが発生しました。（残り {slot.remaining}枠）"
    )

