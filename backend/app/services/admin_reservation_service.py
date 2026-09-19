"""관리 화면 — 예약 검색 · 상세 · 수정 · 취소 · 우편 접수 (A-10 ~ A-13).

이 화면들의 설계 기준은 하나다.
**전화기를 들고 있는 스태프가 상대를 기다리게 하지 않는 것.**

  · 이용자는 예약번호를 모르는 채로 전화한다 → 성명·전화번호·생년월일로도 찾는다 (M-10)
  · 우편 30건을 마법사로 입력하면 하루가 간다 → 1페이지 단일 폼 (M-1)
  · 제1희망이 만석이면 그 자리에서 제2희망으로 넘어간다 (M-2)
  · 몇 번째 연락인지 기억나지 않는다 → 연락 이력을 누적하고 횟수를 보여 준다 (M-3)
"""

import csv
import io
import logging
import re
import unicodedata
from dataclasses import dataclass, field as dataclass_field
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import case, func, or_, select, tuple_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dates import age_on, fiscal_year
from app.core.email_utils import EmailInvalid, normalize_email
from app.core.birth_query import split_keyword
from app.core.reservation_no import SEARCH_FOLD, fold_for_search
from app.core.text_utils import normalize_kana, normalize_name
from app.models.admin import AdminUser
from app.models.exam_option import ExamOption
from app.models.hospital import Hospital, HospitalSchedule, ReservationCount
from app.models.mail import TEMPLATE_LABELS, MailLog
from app.models.reservation import (
    CANCEL_TYPE_LABELS,
    ContactHistory,
    Reservation,
    ReservationOption,
)
from app.models.target_person import TargetPerson
from app.schemas.admin import (
    ContactCreateRequest,
    Page,
    PostalBulkFieldError,
    PostalBulkRequest,
    PostalBulkReservationResult,
    PostalBulkResult,
    PostalReservationRequest,
    PostalReservationResult,
    ReservationContactRow,
    ReservationDetail,
    ReservationMailRow,
    ReservationRow,
    ReservationUpdateRequest,
)
from app.core import time_grid
from app.services import audit_service, reservation_service
from app.services import slot_grid_service as grid
from app.services.slot_grid_service import SlotView
from app.services.reservation_service import ReservationError

STATUS_LABELS = {
    "CONFIRMED": "予約確定",
    "PENDING": "仮受付（要確認）",
    "CANCELLED": "キャンセル",
}
CHANNEL_LABELS = {"WEB": "WEB", "POSTAL": "郵送"}

# 사유 글에서 취소의 종류를 알아내는 말들.
# 種類の列(cancel_type)がまだ空の古い予約にだけ使う。
SAME_DAY_HINTS = ("当日", "連絡不通", "不通", "応答なし", "連絡がつかない", "無断")


def cancel_label(reason: str) -> str:
    """種類の列が空の予約について、理由の文から事前／当日を推し量る。

    これは**古い予約のための保険**である。取り消しの種類は
    `reservations.cancel_type` に入っており、画面も統計もその列を見る。
    文から探すのは当てにならない — 事前キャンセルの理由にも
    「当日は都合がつかないとのこと」のように「当日」が出てくる。
    """
    r = (reason or "").strip()
    if any(k in r for k in SAME_DAY_HINTS):
        return "当日キャンセル"
    return "事前キャンセル"


def format_postal_code(value: str) -> str:
    """우편번호를 `123-4567` 로 맞춘다. 7자리로 읽히지 않으면 손대지 않는다.

    웹 접수와 우편 일괄 입력은 이미 이 모양으로 저장한다. 단건 우편 접수만
    친 그대로(`1600023`) 저장해, 같은 목록에 두 표기가 섞였다.
    """
    text = unicodedata.normalize("NFKC", value or "").strip().removeprefix("〒")
    digits = re.sub(r"[\s\-‐‑‒–—―−ー]", "", text)
    if re.fullmatch(r"[0-9]{7}", digits):
        return f"{digits[:3]}-{digits[3:]}"
    return (value or "").strip()


def reservation_status_label(r: Reservation) -> str:
    """예약의 화면 표기용 상태 라벨."""
    if r.status == "CONFIRMED":
        return STATUS_LABELS["CONFIRMED"]
    if r.status == "PENDING":
        return STATUS_LABELS["PENDING"]
    if r.status == "CANCELLED":
        # 종류가 기록되어 있으면 그대로 쓴다. 비어 있을 때만 사유 글을 본다.
        return CANCEL_TYPE_LABELS.get(r.cancel_type) or cancel_label(r.cancel_reason)
    return r.status


logger = logging.getLogger("kenshin.admin.reservations")

# 우편 접수에서 비어 있으면 불비로 보는 항목 (BR-05)
REQUIRED_FOR_COMPLETE: list[tuple[str, str]] = [
    ("insurer_no", "保険者番号"),
    ("insurance_symbol", "保険証記号"),
    ("insurance_no", "保険証番号"),
    ("postal_code", "郵便番号"),
    ("address", "住所"),
    ("address_detail", "番地"),
]


class AdminReservationError(Exception):
    """관리 화면 조작을 받을 수 없는 이유."""


class PostalBulkValidationError(Exception):
    """일괄 입력의 모든 행을 검사한 뒤 돌려주는 셀 단위 오류."""

    def __init__(self, errors: list[PostalBulkFieldError]) -> None:
        super().__init__("入力内容をご確認ください。")
        self.errors = errors


# ==========================================================================
# 변환
# ==========================================================================


def _reservation_is_holiday(r: Reservation) -> bool:
    """이 예약의 검진일이 통째로 닫혔는가.

    판정은 `HospitalSchedule.is_holiday()` 한 곳에 있다. 필터
    (`is_holiday_slot`)도 같은 기준이라 배지와 목록이 어긋나지 않는다.

    취소된 예약에는 휴진 상태를 붙이지 않는다. 이미 취소된 수검자에게
    일정 변경 연락을 할 이유가 없으며, 취소와 일정변경 요망이 겹치면 혼란을 준다.

    회차 관계(`r.schedule`)를 그대로 본다 — 목록은 `lazy="selectin"` 이라
    한 화면에 질의가 한 번 더 붙을 뿐이고, SQL 로 다시 세는 것보다 읽기 쉽다.
    """
    if getattr(r, "status", None) == "CANCELLED":
        return False
    schedule = getattr(r, "schedule", None)
    return bool(schedule and schedule.is_holiday())

def to_row(r: Reservation) -> ReservationRow:
    return ReservationRow(
        id=r.id,
        reservation_no=r.reservation_no,
        status=r.status,
        status_label=reservation_status_label(r),
        channel=r.channel,
        channel_label=CHANNEL_LABELS.get(r.channel, r.channel),
        full_name=r.full_name,
        full_name_kana=r.full_name_kana,
        gender_label=r.gender_label,
        birth_date=r.birth_date,
        hospital_id=r.hospital_id,
        hospital_name=r.hospital.name if r.hospital else "",
        slot_date=r.slot_date,
        time_label=r.time_label,
        tel_primary=r.tel_primary,
        email=r.email,
        has_defect=r.has_defect,
        contact_count=r.contact_count,
        contact_connected=r.contact_connected,
        is_holiday=_reservation_is_holiday(r),
        option_count=len(r.options),
        # 개수만으로는 목록에서 할 수 있는 일이 없다. 「무엇을 신청했는가」가
        # 보여야 전화 응대 중에 상세를 열지 않고 답할 수 있다.
        # 관계는 `lazy="selectin"` 이라 목록 한 화면에 질의가 한 번 더 붙을 뿐이다.
        option_names=[o.option_name for o in r.options],
        created_at=r.created_at,
    )


def _expires_at(r: Reservation) -> datetime:
    """이 예약이 자동 삭제되는 시각. 상세 화면에 명시한다."""
    return datetime.combine(r.slot_date, r.start_time) + timedelta(
        minutes=settings.RESERVATION_EXPIRE_GRACE_MINUTES
    )


def to_detail(db: Session, r: Reservation) -> ReservationDetail:
    base = to_row(r).model_dump()

    mails = db.execute(
        select(MailLog)
        .where(MailLog.reservation_id == r.id)
        .order_by(MailLog.sent_at.desc())
    ).scalars().all()

    created_by = ""
    if r.created_by_admin_id:
        author = db.get(AdminUser, r.created_by_admin_id)
        created_by = author.name if author else ""

    return ReservationDetail(
        **base,
        last_name=r.last_name,
        first_name=r.first_name,
        last_name_kana=r.last_name_kana,
        first_name_kana=r.first_name_kana,
        middle_name=r.middle_name,
        middle_name_kana=r.middle_name_kana,
        gender=r.gender,
        insurer_no=r.insurer_no,
        insurance_symbol=r.insurance_symbol,
        insurance_no=r.insurance_no,
        postal_code=r.postal_code,
        address=r.address,
        address_detail=r.address_detail,
        building=r.building,
        tel_mobile=r.tel_mobile,
        tel_home=r.tel_home,
        slot_id=time_grid.slot_id(
            r.schedule_id, time_grid.index_of(r.start_time) or 0
        ),
        start_time=r.start_time.strftime("%H:%M"),
        end_time=r.end_time.strftime("%H:%M"),
        hospital_tel=r.hospital.contact_tel if r.hospital else "",
        hospital_address=r.hospital.address if r.hospital else "",
        fiscal_year=r.fiscal_year,
        memo=r.memo,
        defect_note=r.defect_note,
        cancelled_at=r.cancelled_at,
        cancel_reason=r.cancel_reason,
        cancel_type=r.cancel_type,
        cancel_type_label=CANCEL_TYPE_LABELS.get(r.cancel_type, ""),
        created_by=created_by,
        options=[
            {"id": o.exam_option_id, "code": o.option_code, "name": o.option_name}
            for o in r.options
        ],
        contacts=[
            ReservationContactRow(
                id=c.id,
                contacted_at=c.contacted_at,
                admin_name=c.admin_name,
                method=c.method,
                method_label=c.method_label,
                result=c.result,
                result_label=c.result_label,
                memo=c.memo,
            )
            for c in r.contacts
        ],
        mails=[
            ReservationMailRow(
                id=m.id,
                template_key=m.template_key,
                template_label=TEMPLATE_LABELS.get(m.template_key, m.template_key),
                to_email=m.to_email,
                subject=m.subject,
                status=m.status,
                status_label=m.status_label,
                error_message=m.error_message,
                sent_at=m.sent_at,
            )
            for m in mails
        ],
        expires_at=_expires_at(r),
    )


# ==========================================================================
# A-10 검색
# ==========================================================================

# 전화번호로 볼 수 있는 최소 자릿수. 이보다 짧으면 걸러 낸다.
PHONE_MIN_DIGITS = 4

# 전화번호를 적는 방식이 제각각이라 허용하는 구분 문자.
_PHONE_PUNCT = set("-–—() 　+.")


def phone_digits(keyword: str) -> str:
    """검색어가 전화번호로 보일 때만 숫자만 뽑아 돌려준다. 아니면 빈 문자열.

    검색어에서 무조건 숫자를 뽑으면 안 된다. 예약번호는 영문 대소문자와
    숫자가 섞인 무작위 12자라, 거기서 숫자만 뽑으면 `8` 같은 한 글자가 되고
    `tel LIKE '%8%'` 이 되어 **전화번호에 8이 들어간 예약이 전부 걸린다.**
    예약번호로 검색했는데 남의 예약이 수십 건 나오는 것은 사고다.

    그래서 「숫자와 전화번호용 구분 문자만으로 이루어져 있고, 숫자가
    충분히 많을 때」에만 전화번호 검색으로 본다.

    >>> phone_digits("090-1111-2222")
    '09011112222'
    >>> phone_digits("maEPsZamgk8I")
    ''
    >>> phone_digits("田中")
    ''
    >>> phone_digits("12")
    ''
    >>> phone_digits("０９０-１１１１-２２２２")
    '09011112222'
    """
    # 전각 숫자로 친 검색어도 받아 준다. NFKC 로 반각으로 맞춘다.
    keyword = unicodedata.normalize("NFKC", (keyword or "").strip())
    if not keyword:
        return ""

    if any(not (ch.isdigit() or ch in _PHONE_PUNCT) for ch in keyword):
        return ""

    digits = "".join(ch for ch in keyword if ch.isdigit())
    return digits if len(digits) >= PHONE_MIN_DIGITS else ""


# 「휴진일」 — 이 예약의 검진일이 **통째로 닫혔는가**.
#
# 마감에는 두 가지가 있다.
#
#   전체 휴진    그 날 여는 시간대가 **전부** 닫혔다 → 다른 **날짜**로 옮겨야 한다
#   시간대 마감  한두 칸만 닫혔다 → 같은 날 **다른 시각**으로 옮기면 된다
#
# 이 필터는 앞의 것만 센다. 정원 달력이 빨강으로 그리는 것도, 담당자가
# 「휴진일로 설정」을 눌러 만드는 것도 그것이기 때문이다. 둘을 한 이름으로
# 묶으면 「필터에는 걸리는데 달력은 멀쩡하다」가 된다. 실제로 그랬다.
#
# `closed_mask` 는 16칸을 비트로 접어 둔 값이고, 정원이 `NULL` 인 칸은
# 애초에 열지 않는 시간이라 마감할 것이 없다. 그래서 **여는 칸의 비트**를
# 따로 만들어, 그것이 마감 비트에 모두 들어가는지를 본다.
#
# 칸 번호와 칼럼 이름을 여기서 짓지 않는다 — 격자를 아는 곳은 `time_grid`
# 하나다(그 파일 머리말 참조).
STATUS_HOLIDAY = "HOLIDAY"


def _open_slot_bits():
    """그 회차가 **여는** 칸들의 비트합. 정원이 있는 칸만 센다."""
    parts = []
    for index in range(len(time_grid.TIME_GRID)):
        column = getattr(HospitalSchedule, time_grid.capacity_column(index))
        parts.append(case((column.isnot(None), 1 << index), else_=0))
    return sum(parts[1:], parts[0])


def is_holiday_slot():
    """그 날 여는 시간대가 전부 닫혔는가. **EXISTS 로 건다.**

    `correlate(Reservation)` 이 없으면 서브쿼리가 `reservations` 를 자기
    FROM 에 다시 넣어 바깥 행과 이어지지 않는다. 조건이 아니라 「어떤
    예약이든 하나라도 해당하면 참」이 되어 전부 걸린다. 실제로 그랬다.
    """
    open_bits = _open_slot_bits()
    return (
        select(HospitalSchedule.id)
        .where(
            HospitalSchedule.id == Reservation.schedule_id,
            open_bits != 0,
            HospitalSchedule.closed_mask.op("&")(open_bits) == open_bits,
        )
        .correlate(Reservation)
        .exists()
    )




def _keyword_conditions(keyword: str) -> list:
    """글 토막 하나가 걸리는 칸들 — 번호·성명·후리가나·메일·전화."""
    like = f"%{keyword}%"
    # 예약번호 — 전화로 들은 번호는 대소문자도, 0/O·1/l/I 도 가려지지 않는다.
    # 그래서 **관리자 검색에서만** 양쪽을 같은 규칙으로 뭉개서 견준다.
    # (core/reservation_no.py 의 fold_for_search 와 같은 규칙이어야 한다)
    folded_col = func.lower(Reservation.reservation_no)
    for src, dst in SEARCH_FOLD:
        folded_col = func.replace(folded_col, src, dst)
    conditions = [
        folded_col.like(f"%{fold_for_search(keyword)}%"),
        # 성명·후리가나는 테이블 기본 콜레이션이라 대소문자를 구별하지 않는다.
        Reservation.last_name.like(like),
        Reservation.first_name.like(like),
        Reservation.last_name_kana.like(like),
        Reservation.first_name_kana.like(like),
    ]
    # 메일 — 「@도메인」만 친 것은 받지 않는다. 수진자 대부분이 같은 도메인
    # (gmail·docomo 등)이라 그것으로는 아무도 특정되지 않는다. 「@」 없이 친
    # 것은 @ 앞(로컬 파트)에서만 찾는다.
    if keyword.startswith("@"):
        pass
    elif "@" in keyword:
        conditions.append(Reservation.email.like(like))
    else:
        conditions.append(
            func.substring_index(Reservation.email, "@", 1).like(like)
        )
    # 성+이름을 붙여 친 경우(田中太郎)도 찾아 준다
    normalized = normalize_name(keyword)
    if normalized:
        conditions.append(
            func.concat(Reservation.last_name, Reservation.first_name).like(
                f"%{normalized}%"
            )
        )
    kana = normalize_kana(keyword)
    if kana:
        conditions.append(
            func.concat(
                Reservation.last_name_kana, Reservation.first_name_kana
            ).like(f"%{kana}%")
        )
    digits = phone_digits(keyword)
    if digits:
        # 전화번호는 하이픈 유무가 제각각이라 숫자만으로도 찾을 수 있게 한다
        conditions.append(
            func.replace(Reservation.tel_mobile, "-", "").like(f"%{digits}%")
        )
        conditions.append(
            func.replace(Reservation.tel_home, "-", "").like(f"%{digits}%")
        )
    return conditions


def _apply_search_conditions(
    stmt,
    *,
    keyword: str = "",
    status: str = "",
    channel: str = "",
    hospital_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    defect_only: bool = False,
    option_id: int | None = None,
    created_date: date | None = None,
):
    """검색 조건을 `select(Reservation)` 에 얹는다.

    화면 목록(`search`)과 파일 내려받기(`export_file`)가 **같은 조건**을
    써야 한다. 예전에는 이 뭉치가 두 함수에 그대로 복사돼 있어서, 한쪽에만
    조건을 더하면 「화면에서 거른 것과 내려받은 파일이 다른」 상태가 됐다.
    """
    keyword = (keyword or "").strip()
    # 검색어는 띄어쓰기로 나눠 **AND** 로 건다. 「佐藤 1958-11-03」처럼 통화
    # 중에 들은 순서대로 이어 치면 그대로 좁혀진다.
    #   · 생년월일로 읽히는 토막(서기·和暦·8자리)은 birth_date 범위 조건
    #   · 나머지 토막은 예전과 같은 OR 조건(번호·성명·후리가나·메일·전화)
    # 토막이 하나면 예전과 완전히 같다.
    words, birth_ranges = split_keyword(keyword)
    for word in words:
        stmt = stmt.where(or_(*_keyword_conditions(word)))
    for lo, hi in birth_ranges:
        stmt = stmt.where(Reservation.birth_date >= lo, Reservation.birth_date <= hi)

    if status == STATUS_HOLIDAY:
        # 상태 축에 얹는다. 「확정 / 임시 / 취소」와 같은 질문 —
        # 「이 예약이 지금 어떤 상태인가」 — 이므로 필터를 따로 만들지 않는다.
        # 취소된 예약은 뺀다. 이미 안 오기로 된 사람에게 연락할 일이 없다.
        stmt = stmt.where(is_holiday_slot(), Reservation.status != "CANCELLED")
    elif status in ("CANCELLED_PRIOR", "CANCELLED_NOSHOW"):
        # 종류는 열에 있다. 열이 비어 있는 옛 예약만 사유 글로 가른다.
        reason_says_same_day = or_(*[
            Reservation.cancel_reason.like(f"%{word}%") for word in SAME_DAY_HINTS
        ])
        old_row = Reservation.cancel_type == ""
        if status == "CANCELLED_NOSHOW":
            stmt = stmt.where(
                Reservation.status == "CANCELLED",
                (Reservation.cancel_type == "SAME_DAY")
                | (old_row & reason_says_same_day),
            )
        else:
            stmt = stmt.where(
                Reservation.status == "CANCELLED",
                (Reservation.cancel_type == "ADVANCE")
                | (old_row & ~reason_says_same_day),
            )
    elif status:
        stmt = stmt.where(Reservation.status == status)
    if channel:
        stmt = stmt.where(Reservation.channel == channel)
    if hospital_id:
        stmt = stmt.where(Reservation.hospital_id == hospital_id)
    if date_from:
        stmt = stmt.where(Reservation.slot_date >= date_from)
    if date_to:
        stmt = stmt.where(Reservation.slot_date <= date_to)
    if defect_only:
        stmt = stmt.where(
            Reservation.status != "CANCELLED",
            (
                Reservation.has_defect.is_(True)
                | (Reservation.status == "PENDING")
                | is_holiday_slot()
            ),
        )
    if created_date:
        stmt = stmt.where(func.date(Reservation.created_at) == created_date)
    if option_id:
        # **EXISTS 로 건다.** 조인하면 옵션을 두 개 신청한 예약이 두 줄로
        # 세어져 총 건수가 부풀고, 목록에도 같은 사람이 두 번 나온다.
        #
        # 상태로 좁히지 않는다 — 취소된 예약도 그 검사를 신청했던 것이
        # 사실이고, 옵션 검사 관리의 「N건」 배지도 같은 축으로 센다.
        stmt = stmt.where(
            Reservation.options.any(ReservationOption.exam_option_id == option_id)
        )

    return stmt


def search(
    db: Session,
    *,
    keyword: str = "",
    status: str = "",
    channel: str = "",
    hospital_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    defect_only: bool = False,
    option_id: int | None = None,
    created_date: date | None = None,
    page: int = 1,
    size: int = 30,
) -> Page[ReservationRow]:
    """복합 검색.

    키워드 한 칸으로 예약번호·성명·후리가나·전화번호·이메일을 모두 훑는다.
    전화 응대 중에 「어느 칸에 넣어야 하나」를 고민하게 만들면 안 된다 (M-10).

    `option_id` 는 「이 옵션 검사를 신청한 예약만」이다. 옵션 검사 관리에서
    신청 건수를 더블 클릭하면 이 조건이 걸린 채로 들어온다.
    """
    stmt = _apply_search_conditions(
        select(Reservation),
        keyword=keyword,
        status=status,
        channel=channel,
        hospital_id=hospital_id,
        date_from=date_from,
        date_to=date_to,
        defect_only=defect_only,
        option_id=option_id,
        created_date=created_date,
    )

    total = db.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar() or 0

    page = max(1, page)
    size = min(max(1, size), 200)

    rows = db.execute(
        stmt.order_by(Reservation.slot_date, Reservation.start_time, Reservation.id)
        .offset((page - 1) * size)
        .limit(size)
    ).scalars().unique().all()

    return Page[ReservationRow](
        items=[to_row(r) for r in rows], total=total, page=page, size=size
    )


def export_file(
    db: Session,
    *,
    keyword: str = "",
    status: str = "",
    channel: str = "",
    hospital_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    defect_only: bool = False,
    option_id: int | None = None,
    created_date: date | None = None,
    fmt: str = "xlsx",
) -> tuple[str, bytes, str]:
    # 화면 목록과 **같은 조건**을 쓴다. 조건을 여기 다시 적으면 언젠가
    # 한쪽에만 조건이 늘어난다.
    stmt = _apply_search_conditions(
        select(Reservation),
        keyword=keyword,
        status=status,
        channel=channel,
        hospital_id=hospital_id,
        date_from=date_from,
        date_to=date_to,
        defect_only=defect_only,
        option_id=option_id,
        created_date=created_date,
    )

    reservations = db.execute(
        stmt.order_by(Reservation.slot_date.desc(), Reservation.id.desc())
    ).scalars().unique().all()

    headers = [
        "予約番号",
        "ステータス",
        "受診者名",
        "フリガナ",
        "性別",
        "生年月日",
        "受診会場",
        "受診日",
        "健診時間",
        "連絡先",
        "メールアドレス",
        "受付経路",
        "申込オプション",
        "受付日時",
    ]

    rows = []
    for r in reservations:
        opts_str = ", ".join([o.option_name for o in r.options]) if r.options else "なし"
        gender_lbl = "男性" if r.gender == "M" else "女性"
        rows.append([
            r.reservation_no,
            reservation_status_label(r),
            r.full_name,
            r.full_name_kana,
            gender_lbl,
            r.birth_date.isoformat() if r.birth_date else "",
            r.hospital.name if r.hospital else "",
            r.slot_date.isoformat() if r.slot_date else "",
            r.time_label,
            r.tel_primary,
            r.email or "",
            CHANNEL_LABELS.get(r.channel, r.channel),
            opts_str,
            r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "",
        ])

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    if fmt == "xlsx":
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Alignment, Font, PatternFill
            from openpyxl.utils import get_column_letter

            wb = Workbook()
            ws = wb.active
            ws.title = "予約一覧"

            header_font = Font(bold=True, color="FF0F172A")
            header_fill = PatternFill("solid", fgColor="FFE2E8F0")
            header_align = Alignment(vertical="center", horizontal="left")

            ws.append(headers)
            for col_idx in range(1, len(headers) + 1):
                cell = ws.cell(row=1, column=col_idx)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = header_align

            for r_idx, row_data in enumerate(rows, start=2):
                for c_idx, val in enumerate(row_data, start=1):
                    cell = ws.cell(row=r_idx, column=c_idx)
                    cell.value = val

            ws.freeze_panes = "A2"
            max_col = get_column_letter(len(headers))
            max_row = max(1, len(rows) + 1)
            # 엑셀 헤더에 자동 필터 드롭다운 화살표(AutoFilter)를 활성화
            ws.auto_filter.ref = f"A1:{max_col}{max_row}"

            # 열 너비 자동 맞춤
            col_widths = [16, 12, 16, 18, 10, 14, 28, 14, 16, 16, 24, 12, 30, 20]
            for col_idx, w in enumerate(col_widths, start=1):
                ws.column_dimensions[get_column_letter(col_idx)].width = w

            stream = io.BytesIO()
            wb.save(stream)
            filename = f"reservations_export_{ts}.xlsx"
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            return filename, stream.getvalue(), media_type
        except ImportError:
            pass  # Fallback to CSV if openpyxl is missing

    # CSV Format (UTF-8 BOM)
    output = io.StringIO()
    # BOM 은 여기서 붙이지 않는다 — 아래 encode("utf-8-sig") 가 이미 붙인다.
    # 두 번 붙이면 Excel 첫 칸 머리글에 보이지 않는 글자가 섞여
    # 그 파일을 다시 가져올 때 열 이름이 어긋난다.
    writer = csv.writer(output)
    # CSV 는 색·굵기가 없으므로 머리글을 【】로 감싸 데이터 줄과 구분한다.
    writer.writerow([f"【{h}】" for h in headers])
    for row in rows:
        writer.writerow(row)

    filename = f"reservations_export_{ts}.csv"
    media_type = "text/csv; charset=utf-8-sig"
    # 부르는 쪽은 (이름, 바이트, 미디어 타입) 셋을 받는다. 예전에는 여기에
    # 두 개짜리 return 이 한 줄 먼저 있어서 `format=csv` 가 늘 500 이었다.
    # 화면의 「CSV 내보내기」 버튼이 실제로는 xlsx 를 부르고 있어 드러나지 않았다.
    return filename, output.getvalue().encode("utf-8-sig"), media_type


def get(db: Session, reservation_id: int) -> Reservation:
    reservation = db.get(Reservation, reservation_id)
    if reservation is None:
        raise AdminReservationError("予約が見つかりません。すでに削除された可能性があります。")
    return reservation


# ==========================================================================
# A-11 수정
# ==========================================================================

_EDITABLE_FIELDS = [
    "last_name",
    "first_name",
    "last_name_kana",
    "first_name_kana",
    "middle_name",
    "middle_name_kana",
    "gender",
    "birth_date",
    "insurer_no",
    "insurance_symbol",
    "insurance_no",
    "postal_code",
    "address",
    "address_detail",
    "building",
    "tel_mobile",
    "tel_home",
    "email",
    "status",
    "has_defect",
    "defect_note",
    "memo",
]


def update(
    db: Session,
    reservation_id: int,
    payload: ReservationUpdateRequest,
    *,
    admin: AdminUser,
    ip_address: str,
) -> tuple[ReservationDetail, str]:
    """예약 내용을 고친다.

    일시 변경은 「원래 슬롯 반납 → 새 슬롯 확보」 순서로 한다.
    새 슬롯이 만석이면 원래 예약을 그대로 둔다. 반납부터 하면
    새 슬롯을 못 잡았을 때 이용자가 자리를 잃는다.
    """
    reservation = get(db, reservation_id)
    if reservation.status == "CANCELLED":
        raise AdminReservationError(
            "キャンセルされた予約は修正できません。必要な場合は新規に受付してください。"
        )

    before = audit_service.snapshot(reservation, _EDITABLE_FIELDS + ["schedule_id", "slot_date", "time_label", "option_names"])
    messages: list[str] = []

    # --- 검진 일시 변경 ---------------------------------------------------
    current_slot_id = time_grid.slot_id(
        reservation.schedule_id, time_grid.index_of(reservation.start_time) or 0
    )
    # 일시를 옮겼는지, 옮겼다면 **옛 일시가 무엇이었는지**를 여기서 붙잡는다.
    # 아래에서 reservation 의 값을 새 슬롯으로 덮어쓰므로, 그 뒤에는 꺼낼 수
    # 없다. 「검진일 변경 안내」 메일의 「변경 전」이 이 값이다.
    # 서식은 보낼 때 한다 — `format_date_ja` 가 mail_service 에 있고, 이 모듈은
    # 그것을 함수 안에서만 부른다(순환 import 를 피하기 위해서다).
    moved_from: tuple[object, str] | None = None

    if payload.slot_id and payload.slot_id != current_slot_id:
        moved_from = (reservation.slot_date, reservation.time_label or "-")
        try:
            new_slot = reservation_service.occupy_slot(
                db, payload.slot_id, datetime.now()
            )
        except ReservationError as exc:
            raise AdminReservationError(exc.message) from exc

        old_slot = reservation_service.release_slot(db, reservation)
        grid.reserved_delta(db, new_slot.schedule_id, new_slot.index, 1)

        reservation.schedule_id = new_slot.schedule_id
        reservation.hospital_id = new_slot.hospital_id
        reservation.slot_date = new_slot.slot_date
        reservation.start_time = new_slot.start_time
        reservation.end_time = new_slot.end_time
        reservation.fiscal_year = fiscal_year(new_slot.slot_date)

        if old_slot is not None:
            messages.append(
                f"以前の時間帯({old_slot.slot_date} {old_slot.time_label})に "
                f"1枠の空きが出ました。"
            )

    # --- 값 갱신 ----------------------------------------------------------
    for field in (
        "last_name", "first_name", "last_name_kana", "first_name_kana",
        "middle_name", "middle_name_kana", "insurer_no", "insurance_symbol", "insurance_no",
        "postal_code", "address", "address_detail", "building",
        "tel_mobile", "tel_home", "email", "defect_note", "memo"
    ):
        val = getattr(payload, field)
        if val is not None:
            setattr(reservation, field, val or "")
            
    if payload.gender is not None:
        reservation.gender = payload.gender
    if payload.birth_date is not None:
        reservation.birth_date = payload.birth_date

    if payload.status is not None:
        reservation.status = payload.status
    if payload.has_defect is not None:
        reservation.has_defect = payload.has_defect

    # 불비 표시를 끄면 사유도 함께 지운다. 남겨 두면 목록에서 오해를 부른다.
    if not reservation.has_defect:
        reservation.defect_note = ""

    # --- 옵션 검사 --------------------------------------------------------
    if payload.option_ids is not None:
        db.execute(
            ReservationOption.__table__.delete().where(
                ReservationOption.reservation_id == reservation.id
            )
        )
        _attach_options(db, reservation, payload.option_ids, enforce_target=False)

    db.flush()

    after = audit_service.snapshot(reservation, _EDITABLE_FIELDS + ["schedule_id", "slot_date", "time_label", "option_names"])
    diff = audit_service.diff(before, after)
    
    if diff:
        audit_service.write_log(
            db,
            admin=admin,
            action="RESERVATION_UPDATE",
            target_type="reservation",
            target_id=reservation.id,
            target_label=f"{reservation.reservation_no} {reservation.full_name}",
            before=before,
            after=diff,
            ip_address=ip_address,
        )
        
    # 안내 메일. **일시를 옮겼고, 담당자가 보내겠다고 답했을 때만** 나간다.
    #
    # 커밋 전에 보내면 발송은 됐는데 저장이 실패하는 경우가 생긴다. 그렇다고
    # 커밋 뒤로 미루면 메일 실패가 저장을 되돌리지 못한다 — 그것이 맞다.
    # 이미 옮긴 예약을 메일이 안 나갔다는 이유로 되돌리면 담당자가 전화로
    # 합의한 내용과 화면이 어긋난다. 실패는 `mail_logs` 에 남는다.
    db.commit()
    db.refresh(reservation)

    if moved_from and payload.notify_change:
        from app.services import mail_service

        log = mail_service.send_schedule_changed(
            db,
            reservation,
            mail_service.format_date_ja(moved_from[0]) if moved_from[0] else "-",
            moved_from[1],
        )
        db.commit()
        messages.append(
            "変更案内メールを送信しました。"
            if log.status == "SUCCESS"
            else f"変更案内メールを送信できませんでした ({log.error_message})."
        )

    return to_detail(db, reservation), " ".join(messages) or "予約内容を保存しました。"


def _attach_options(
    db: Session,
    reservation: Reservation,
    option_ids: list[int],
    *,
    enforce_target: bool = True,
) -> None:
    """옵션 검사를 붙인다.

    관리 화면에서는 타깃 조건을 강제하지 않는다(`enforce_target=False`).
    종이 신청서에 적혀 온 것을 스태프가 그대로 입력하는 자리이며,
    조건 판단은 회장이 한다.
    """
    if not option_ids:
        return

    age = age_on(reservation.birth_date, reservation.slot_date)
    options = db.execute(
        select(ExamOption).where(ExamOption.id.in_(option_ids))
    ).scalars().all()

    for option in options:
        if enforce_target and not option.matches(reservation.gender, age):
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
# A-12 취소
# ==========================================================================


def cancel(
    db: Session,
    reservation_id: int,
    reason: str,
    *,
    cancel_type: str = "ADVANCE",
    admin: AdminUser,
    ip_address: str,
) -> tuple[ReservationDetail, str]:
    reservation = get(db, reservation_id)
    if reservation.status == "CANCELLED":
        raise AdminReservationError("既にキャンセルされた予約です。")

    hospital_name = reservation.hospital.name if reservation.hospital else ""
    slot = reservation_service.cancel(
        db, reservation, reason=reason, cancel_type=cancel_type,
        admin=admin, ip_address=ip_address
    )
    db.commit()
    db.refresh(reservation)

    return (
        to_detail(db, reservation),
        reservation_service.released_seat_message(slot, hospital_name),
    )


# ==========================================================================
# 연락 이력 (M-3)
# ==========================================================================


def add_contact(
    db: Session,
    reservation_id: int,
    payload: ContactCreateRequest,
    *,
    admin: AdminUser,
    ip_address: str,
) -> tuple[ReservationDetail, str]:
    reservation = get(db, reservation_id)

    db.add(
        ContactHistory(
            reservation_id=reservation.id,
            contacted_at=datetime.now(),
            admin_user_id=admin.id,
            admin_name=admin.name,
            method=payload.method,
            result=payload.result,
            memo=payload.memo,
        )
    )
    db.flush()
    db.refresh(reservation)

    count = reservation.contact_count

    audit_service.write_log(
        db,
        admin=admin,
        action="CONTACT_ADD",
        target_type="reservation",
        target_id=reservation.id,
        target_label=f"{reservation.reservation_no} {reservation.full_name}",
        after={"method": payload.method, "result": payload.result, "count": count},
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(reservation)

    if count >= 3 and payload.result == "NO_ANSWER":
        message = (
            f"連絡 {count}回目です。3回連絡してもつながらない場合は"
            "予約をキャンセルすることになっています。"
        )
    else:
        message = f"連絡履歴を記録しました。(累計 {count}回)"

    return to_detail(db, reservation), message


# ==========================================================================
# A-13 우편 접수 입력
# ==========================================================================


def _find_target_person(db: Session, payload: PostalReservationRequest) -> TargetPerson | None:
    """명부에서 같은 사람을 찾는다.

    찾으면 `target_person_id` 를 채워 중복 판정을 정확하게 만든다.
    못 찾아도 등록은 막지 않는다. 명부 누락은 스태프가 전화로 확인할 일이지,
    종이 신청서를 반려할 이유가 아니다.
    """
    candidates = db.execute(
        select(TargetPerson).where(TargetPerson.birth_date == payload.birth_date)
    ).scalars().all()

    last = normalize_name(payload.last_name)
    first = normalize_name(payload.first_name)

    matched = [
        p
        for p in candidates
        if normalize_name(p.last_name) == last
        and normalize_name(p.first_name) == first
        and p.gender == payload.gender
    ]

    if len(matched) == 1:
        return matched[0]

    # 동성동명이면 후리가나로 한 번 더 좁힌다
    if len(matched) > 1 and payload.last_name_kana and payload.first_name_kana:
        kana_last = normalize_kana(payload.last_name_kana)
        kana_first = normalize_kana(payload.first_name_kana)
        narrowed = [
            p
            for p in matched
            if normalize_kana(p.last_name_kana) == kana_last
            and normalize_kana(p.first_name_kana) == kana_first
        ]
        if len(narrowed) == 1:
            return narrowed[0]

    # 2명 이상 남으면 특정하지 않는다. 추측으로 고르면 다른 사람의 예약이 된다.
    return None


@dataclass(frozen=True)
class _PostalSlotChoice:
    slot_id: int
    rank: int


def _stage_postal(
    db: Session,
    payload: PostalReservationRequest,
    choices: list[_PostalSlotChoice],
    *,
    admin: AdminUser,
    ip_address: str,
    now: datetime,
) -> tuple[Reservation, PostalReservationResult]:
    """예약과 감사 로그를 현재 트랜잭션에 추가하되 커밋·메일 발송은 하지 않는다."""
    if not choices:
        raise AdminReservationError("ご希望の受診日時を1つ以上お選びください。")

    person = _find_target_person(db, payload)

    missing = [
        label for field_name, label in REQUIRED_FOR_COMPLETE
        if not getattr(payload, field_name, "")
    ]
    if not payload.tel_mobile and not payload.tel_home:
        missing.append("電話番号")

    if missing and not payload.allow_defect:
        raise AdminReservationError(
            "次の項目が未入力です — "
            + ", ".join(missing)
            + ". ご本人に確認の上入力するか、「不備状態で仮受付」を"
            "選択して登録してください。"
        )

    slot: SlotView | None = None
    used_choice = 0
    skipped: list[str] = []

    for choice in sorted(choices, key=lambda item: item.rank):
        try:
            slot = reservation_service.lock_slot(db, choice.slot_id, now)
            used_choice = choice.rank
            break
        except ReservationError as exc:
            candidate = grid.find(db, choice.slot_id)
            where = (
                f"第{choice.rank}希望 {candidate.slot_date} {candidate.time_label}"
                if candidate
                else f"第{choice.rank}希望"
            )
            skipped.append(f"{where} — {exc.message}")

    if slot is None:
        raise AdminReservationError(
            "選択された希望日時がすべて予約できない状態です。"
            + " / ".join(skipped)
        )

    hospital = db.get(Hospital, slot.hospital_id)
    if hospital is None:
        raise AdminReservationError("選択された会場が見つかりません。")
    year = fiscal_year(slot.slot_date)

    duplicate = reservation_service.find_duplicate(
        db,
        target_person_id=person.id if person else None,
        last_name=payload.last_name,
        first_name=payload.first_name,
        birth_date=payload.birth_date,
        tel_mobile=payload.tel_mobile,
        tel_home=payload.tel_home,
        year=year,
    )
    if duplicate is not None:
        raise AdminReservationError(
            f"今年度すでに予約されている方です。(予約番号 {duplicate.reservation_no} / "
            f"{duplicate.slot_date} {duplicate.time_label})"
        )

    has_defect = bool(missing)
    reservation = Reservation(
        reservation_no=reservation_service.issue_reservation_no(db),
        schedule_id=slot.schedule_id,
        hospital_id=hospital.id,
        slot_date=slot.slot_date,
        start_time=slot.start_time,
        end_time=slot.end_time,
        channel="POSTAL",
        status="PENDING" if has_defect else "CONFIRMED",
        target_person_id=person.id if person else None,
        last_name=payload.last_name.strip(),
        first_name=payload.first_name.strip(),
        last_name_kana=normalize_kana(payload.last_name_kana),
        first_name_kana=normalize_kana(payload.first_name_kana),
        middle_name=payload.middle_name.strip(),
        middle_name_kana=normalize_kana(payload.middle_name_kana),
        gender=payload.gender,
        birth_date=payload.birth_date,
        insurer_no=payload.insurer_no.strip(),
        insurance_symbol=payload.insurance_symbol.strip(),
        insurance_no=payload.insurance_no.strip(),
        postal_code=format_postal_code(payload.postal_code),
        address=payload.address.strip(),
        address_detail=payload.address_detail.strip(),
        building=payload.building.strip(),
        tel_mobile=payload.tel_mobile.strip(),
        tel_home=payload.tel_home.strip(),
        email=payload.email.strip(),
        fiscal_year=year,
        memo=payload.memo,
        has_defect=has_defect,
        defect_note=", ".join(missing),
        created_by_admin_id=admin.id,
    )
    db.add(reservation)
    grid.reserved_delta(db, slot.schedule_id, slot.index, 1)
    db.flush()

    _attach_options(db, reservation, payload.option_ids, enforce_target=False)
    db.flush()

    audit_service.write_log(
        db,
        admin=admin,
        action="RESERVATION_CREATE_POSTAL",
        target_type="reservation",
        target_id=reservation.id,
        target_label=f"{reservation.reservation_no} {reservation.full_name}",
        after={
            "hospital": hospital.name,
            "slot_date": reservation.slot_date,
            "time": reservation.time_label,
            "choice": used_choice,
            "status": reservation.status,
            "defect": reservation.defect_note,
        },
        ip_address=ip_address,
    )

    if has_defect:
        message = (
            f"仮受付として登録しました。未入力の項目({reservation.defect_note})を"
            "ご本人に確認の上、「確定」に変更してください。"
        )
    elif used_choice > 1:
        message = f"第{used_choice}希望日時で登録しました。"
    else:
        message = "予約を登録しました。"

    result = PostalReservationResult(
        id=reservation.id,
        reservation_no=reservation.reservation_no,
        status=reservation.status,
        status_label=reservation_status_label(reservation),
        hospital_name=hospital.name,
        slot_date=reservation.slot_date,
        time_label=reservation.time_label,
        used_choice=used_choice,
        skipped=skipped,
        has_defect=has_defect,
        defect_note=reservation.defect_note,
        message=message,
    )
    return reservation, result


def _send_postal_completion_emails(
    db: Session, reservations: list[Reservation]
) -> None:
    """예약 커밋이 끝난 뒤 확인 메일과 메일 로그를 별도 트랜잭션으로 처리한다."""
    try:
        eligible = [
            reservation
            for reservation in reservations
            if reservation.status == "CONFIRMED" and reservation.email
        ]
        if not eligible:
            return

        from app.services import mail_service

        for reservation in eligible:
            mail_service.send_reserve_complete(db, reservation)
        db.commit()
    except Exception:  # 메일 실패로 이미 커밋한 예약을 실패로 보이지 않는다
        db.rollback()
        logger.exception("郵送受付の確認メール記録中にエラーが発生しました。")


def create_postal(
    db: Session,
    payload: PostalReservationRequest,
    *,
    admin: AdminUser,
    ip_address: str,
) -> PostalReservationResult:
    """단건 우편 신청서를 대리 등록한다. 기존 API 계약은 그대로 유지한다."""
    choices = [
        _PostalSlotChoice(slot_id=slot_id, rank=index)
        for index, slot_id in enumerate(payload.slot_ids, start=1)
    ]
    reservation, result = _stage_postal(
        db,
        payload,
        choices,
        admin=admin,
        ip_address=ip_address,
        now=datetime.now(),
    )

    # 실제 SMTP 는 예약 트랜잭션이 성공하기 전에는 절대로 호출하지 않는다.
    db.commit()
    _send_postal_completion_emails(db, [reservation])
    return result


# ==========================================================================
# A-13 우편 접수 일괄 입력
# ==========================================================================

BULK_MAX_WISHES = 3
BULK_MAX_OPTIONS = 100
BULK_MEMO_MAX_LENGTH = 10_000

_BULK_TEXT_LIMITS: dict[str, int] = {
    "last_name": 60,
    "first_name": 60,
    "last_name_kana": 60,
    "first_name_kana": 60,
    "middle_name": 120,
    "middle_name_kana": 120,
    "insurer_no": 30,
    "insurance_symbol": 30,
    "insurance_no": 30,
    "postal_code": 10,
    "address": 255,
    "address_detail": 255,
    "building": 255,
    "tel_mobile": 30,
    "tel_home": 30,
    "email": 255,
    "memo": BULK_MEMO_MAX_LENGTH,
}


@dataclass(frozen=True)
class _BulkWishSpec:
    rank: int
    hospital_id: int
    slot_date: date
    start_time: time


@dataclass
class _BulkCandidate:
    input_index: int
    row_no: int
    raw: dict[str, Any]
    values: dict[str, Any] = dataclass_field(default_factory=dict)
    wish_specs: list[_BulkWishSpec] = dataclass_field(default_factory=list)
    option_ids: list[int] = dataclass_field(default_factory=list)
    choices: list[_PostalSlotChoice] = dataclass_field(default_factory=list)
    payload: PostalReservationRequest | None = None
    errors: list[PostalBulkFieldError] = dataclass_field(default_factory=list)
    planned_choice: _PostalSlotChoice | None = None
    target_person_id: int | None = None


def _bulk_error(candidate: _BulkCandidate, field_name: str, message: str) -> None:
    candidate.errors.append(
        PostalBulkFieldError(
            row_no=candidate.row_no,
            field=field_name,
            message=message,
        )
    )


def _bulk_has_value(value: Any) -> bool:
    """완전히 빈 그리드 행을 가린다. 문자열/숫자 ``0`` 은 값으로 본다."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, bool):
        # 잘못 붙여넣은 False 도 "빈 셀"이 아니라 형식 오류로 잡아야 한다.
        return True
    if isinstance(value, dict):
        return any(_bulk_has_value(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_bulk_has_value(item) for item in value)
    return True


def _bulk_row_number(value: Any, fallback: int) -> tuple[int, str]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return fallback, ""
    if isinstance(value, bool):
        return fallback, "行番号は1以上の整数で入力してください。"

    normalized = unicodedata.normalize("NFKC", str(value)).strip()
    if not re.fullmatch(r"[0-9]+", normalized):
        return fallback, "行番号は1以上の整数で入力してください。"
    number = int(normalized)
    if not 1 <= number <= 1_000_000:
        return fallback, "行番号は1以上1,000,000以下で入力してください。"
    return number, ""


def _bulk_text(
    candidate: _BulkCandidate,
    field_name: str,
    value: Any,
    max_length: int,
) -> str:
    if value is None:
        return ""
    if isinstance(value, (bool, dict, list, tuple)):
        _bulk_error(candidate, field_name, "文字列で入力してください。")
        return ""
    if not isinstance(value, (str, int, float)):
        _bulk_error(candidate, field_name, "文字列で入力してください。")
        return ""

    # Excel 붙여넣기에서 흔한 전각 영숫자도 DB 에 넣기 전에 통일한다.
    # 정규화는 문자를 늘릴 수 있으므로 길이 제한은 반드시 그 뒤에 검사한다.
    text_value = unicodedata.normalize("NFKC", str(value)).strip()
    if len(text_value) > max_length:
        _bulk_error(
            candidate,
            field_name,
            f"{max_length}文字以下で入力してください。",
        )
        return ""
    return text_value


def _bulk_gender(candidate: _BulkCandidate, value: Any) -> str:
    raw = _bulk_text(candidate, "gender", value, 10)
    normalized = unicodedata.normalize("NFKC", raw).strip().casefold()
    aliases = {
        "m": "M",
        "male": "M",
        "男": "M",
        "男性": "M",
        "男": "M",
        "男性": "M",
        "f": "F",
        "female": "F",
        "女": "F",
        "女性": "F",
        "女": "F",
        "女性": "F",
    }
    gender = aliases.get(normalized, "")
    if not gender:
        _bulk_error(candidate, "gender", "性別はM(男性)またはF(女性)で入力してください。")
    return gender


def _bulk_date(candidate: _BulkCandidate, field_name: str, value: Any) -> date | None:
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    else:
        raw = _bulk_text(candidate, field_name, value, 32)
        if not raw:
            _bulk_error(candidate, field_name, "日付を入力してください。")
            return None
        normalized = unicodedata.normalize("NFKC", raw).strip()
        normalized = (
            normalized.replace("年", "-").replace("月", "-").replace("日", "")
        )
        parsed = None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
            try:
                parsed = datetime.strptime(normalized, fmt).date()
                break
            except ValueError:
                continue
        if parsed is None:
            _bulk_error(
                candidate,
                field_name,
                "日付はYYYY-MM-DD形式で入力してください。",
            )
            return None
    return parsed


def _bulk_time(candidate: _BulkCandidate, field_name: str, value: Any) -> time | None:
    if isinstance(value, datetime):
        parsed = value.time().replace(microsecond=0)
    elif isinstance(value, time):
        parsed = value.replace(microsecond=0)
    else:
        raw = _bulk_text(candidate, field_name, value, 20)
        if not raw:
            _bulk_error(candidate, field_name, "開始時刻を入力してください。")
            return None
        normalized = unicodedata.normalize("NFKC", raw).strip()
        matched = re.fullmatch(r"([0-9]{1,2}):([0-9]{2})(?::([0-9]{2}))?", normalized)
        if not matched:
            _bulk_error(candidate, field_name, "時刻はHH:MM形式で入力してください。")
            return None
        try:
            parsed = time(
                int(matched.group(1)),
                int(matched.group(2)),
                int(matched.group(3) or 0),
            )
        except ValueError:
            _bulk_error(candidate, field_name, "正しい時刻を入力してください。")
            return None
    return parsed


def _bulk_bool(candidate: _BulkCandidate, field_name: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, str) and not value.strip()):
        return False
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        normalized = unicodedata.normalize("NFKC", str(value)).strip().casefold()
        if normalized in {"1", "true", "yes", "y", "はい", "許可"}:
            return True
        if normalized in {"0", "false", "no", "n", "いいえ", "不許可"}:
            return False
    _bulk_error(candidate, field_name, "はい/いいえの値で入力してください。")
    return False


def _hospital_key(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "").strip()


def _parse_option_codes(
    candidate: _BulkCandidate,
    raw_value: Any,
    options_by_code: dict[str, ExamOption],
) -> list[int]:
    if raw_value is None or raw_value == "":
        return []
    if isinstance(raw_value, str):
        if len(raw_value) > 4_000:
            _bulk_error(candidate, "option_codes", "オプションコードの入力が長すぎます。")
            return []
        values: list[Any] = re.split(r"[;,，、\n\r]+", raw_value)
    elif isinstance(raw_value, list):
        values = raw_value
    else:
        _bulk_error(
            candidate,
            "option_codes",
            "オプションコードは配列またはセミコロン区切りの文字列で入力してください。",
        )
        return []

    if len(values) > BULK_MAX_OPTIONS:
        _bulk_error(
            candidate,
            "option_codes",
            f"オプション検査は最大 {BULK_MAX_OPTIONS}個まで入力できます。",
        )
        return []

    result: list[int] = []
    seen: set[int] = set()
    for value in values:
        code = _bulk_text(candidate, "option_codes", value, 20)
        if not code:
            continue
        option = options_by_code.get(_hospital_key(code).casefold())
        if option is None:
            _bulk_error(
                candidate,
                "option_codes",
                f"未登録のオプションコードです: {code}",
            )
            continue
        if not option.is_active:
            _bulk_error(
                candidate,
                "option_codes",
                f"現在利用できないオプションコードです: {code}",
            )
            continue
        if option.id in seen:
            _bulk_error(
                candidate,
                "option_codes",
                f"オプションコードが重複しています: {code}",
            )
            continue
        result.append(option.id)
        seen.add(option.id)
    return result


def _parse_wishes(
    candidate: _BulkCandidate,
    raw_value: Any,
    hospitals_by_code: dict[str, Hospital],
    hospitals_by_name: dict[str, list[Hospital]],
) -> list[_BulkWishSpec]:
    if raw_value is None or raw_value == "":
        raw_wishes: list[Any] = []
    elif isinstance(raw_value, list):
        raw_wishes = raw_value
    else:
        _bulk_error(candidate, "wishes", "希望日時は配列で入力してください。")
        return []

    if len(raw_wishes) > BULK_MAX_WISHES:
        _bulk_error(candidate, "wishes", "希望日時は最大3件まで入力できます。")
        raw_wishes = raw_wishes[:BULK_MAX_WISHES]

    specs: list[_BulkWishSpec] = []
    used_ranks: set[int] = set()
    for index, raw_wish in enumerate(raw_wishes, start=1):
        if not _bulk_has_value(raw_wish):
            continue
        if not isinstance(raw_wish, dict):
            _bulk_error(
                candidate,
                "wishes",
                f"第{index}希望の値の構造を確認してください。",
            )
            continue

        raw_rank = raw_wish.get("rank")
        if raw_rank is None or (isinstance(raw_rank, str) and not raw_rank.strip()):
            rank = index
        else:
            normalized_rank = unicodedata.normalize("NFKC", str(raw_rank)).strip()
            if isinstance(raw_rank, bool) or not re.fullmatch(
                r"[1-3]", normalized_rank
            ):
                _bulk_error(
                    candidate,
                    "wishes",
                    "希望順位は1、2、3のいずれかである必要があります。",
                )
                continue
            rank = int(normalized_rank)

        if rank in used_ranks:
            _bulk_error(candidate, "wishes", f"第{rank}希望が重複しています。")
            continue
        used_ranks.add(rank)

        hospital_field = f"wish{rank}_hospital"
        date_field = f"wish{rank}_date"
        time_field = f"wish{rank}_time"
        before = len(candidate.errors)

        hospital_text = _bulk_text(
            candidate, hospital_field, raw_wish.get("hospital"), 120
        )
        hospital: Hospital | None = None
        if not hospital_text:
            _bulk_error(
                candidate,
                hospital_field,
                "会場コードまたは会場名を入力してください。",
            )
        else:
            hospital_key = _hospital_key(hospital_text)
            hospital = hospitals_by_code.get(hospital_key.casefold())
            if hospital is None:
                named = hospitals_by_name.get(hospital_key, [])
                if len(named) == 1:
                    hospital = named[0]
                elif len(named) > 1:
                    _bulk_error(
                        candidate,
                        hospital_field,
                        "同名の会場が複数存在します。会場コードを入力してください。",
                    )
                else:
                    _bulk_error(
                        candidate,
                        hospital_field,
                        "登録された会場コードまたは正確な会場名ではありません。",
                    )

        wish_date = _bulk_date(candidate, date_field, raw_wish.get("date"))
        wish_time = _bulk_time(candidate, time_field, raw_wish.get("time"))
        if len(candidate.errors) == before and hospital and wish_date and wish_time:
            specs.append(
                _BulkWishSpec(
                    rank=rank,
                    hospital_id=hospital.id,
                    slot_date=wish_date,
                    start_time=wish_time,
                )
            )

    return sorted(specs, key=lambda item: item.rank)


def _slot_unavailable_reason(slot: SlotView, now: datetime, remaining: int) -> str:
    if datetime.combine(slot.slot_date, slot.start_time) <= now:
        return "過去の日時"
    if slot.is_closed:
        return "受付締切"
    if remaining <= 0:
        return "満員"
    return ""


def _normalized_phone_digits(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    return "".join(character for character in normalized if character.isdigit())


def _is_intra_bulk_duplicate(
    left: _BulkCandidate,
    right: _BulkCandidate,
    *,
    left_year: int,
    right_year: int,
) -> bool:
    if left_year != right_year or left.payload is None or right.payload is None:
        return False
    if (
        left.target_person_id is not None
        and left.target_person_id == right.target_person_id
    ):
        return True

    left_phones = {
        digits
        for digits in (
            _normalized_phone_digits(left.payload.tel_mobile),
            _normalized_phone_digits(left.payload.tel_home),
        )
        if digits
    }
    right_phones = {
        digits
        for digits in (
            _normalized_phone_digits(right.payload.tel_mobile),
            _normalized_phone_digits(right.payload.tel_home),
        )
        if digits
    }
    same_name_and_birth = bool(
        normalize_name(left.payload.last_name)
        == normalize_name(right.payload.last_name)
        and normalize_name(left.payload.first_name)
        == normalize_name(right.payload.first_name)
        and left.payload.birth_date == right.payload.birth_date
    )
    if not same_name_and_birth:
        return False
    if left_phones.intersection(right_phones):
        return True

    # 명부에도 연결되지 않고 전화번호도 없는 불비 행은 이후에 같은 사람인지
    # 가를 단서가 없다. 같은 배치 안에서는 보수적으로 중복으로 막는다.
    return bool(
        not left_phones
        and not right_phones
        and left.target_person_id is None
        and right.target_person_id is None
    )


def _prepare_postal_bulk(
    db: Session,
    request: PostalBulkRequest,
    *,
    now: datetime,
) -> list[_BulkCandidate]:
    hospitals = list(db.execute(select(Hospital)).scalars().all())
    hospitals_by_code = {
        _hospital_key(hospital.code).casefold(): hospital for hospital in hospitals
    }
    hospitals_by_name: dict[str, list[Hospital]] = {}
    for hospital in hospitals:
        hospitals_by_name.setdefault(_hospital_key(hospital.name), []).append(hospital)

    options = list(db.execute(select(ExamOption)).scalars().all())
    options_by_code = {
        _hospital_key(option.code).casefold(): option for option in options
    }

    candidates: list[_BulkCandidate] = []
    seen_row_numbers: dict[int, _BulkCandidate] = {}

    for input_index, row in enumerate(request.rows, start=1):
        raw = row.model_dump()
        content = {
            key: value
            for key, value in raw.items()
            if key != "row_no"
            and not (key == "allow_defect" and value is False)
        }
        if not any(_bulk_has_value(value) for value in content.values()):
            continue

        row_no, row_no_error = _bulk_row_number(raw.get("row_no"), input_index)
        candidate = _BulkCandidate(
            input_index=input_index,
            row_no=row_no,
            raw=raw,
        )
        candidates.append(candidate)
        if row_no_error:
            _bulk_error(candidate, "row_no", row_no_error)

        prior = seen_row_numbers.get(row_no)
        if prior is not None:
            _bulk_error(prior, "row_no", "行番号が重複しています。")
            _bulk_error(candidate, "row_no", "行番号が重複しています。")
        else:
            seen_row_numbers[row_no] = candidate

        for field_name, max_length in _BULK_TEXT_LIMITS.items():
            candidate.values[field_name] = _bulk_text(
                candidate,
                field_name,
                raw.get(field_name),
                max_length,
            )

        # 표기 차이로 같은 전화번호가 다른 사람처럼 보이지 않게 저장값도
        # 최소한으로 정규화한다. 구분 하이픈은 남겨 사람이 읽기 쉽게 한다.
        for phone_field in ("tel_mobile", "tel_home"):
            candidate.values[phone_field] = re.sub(
                r"\s+",
                "",
                candidate.values[phone_field].translate(
                    str.maketrans({"–": "-", "—": "-", "−": "-", "ー": "-"})
                ),
            )
        candidate.values["postal_code"] = re.sub(
            r"\s+", "", candidate.values["postal_code"]
        )
        if candidate.values["postal_code"]:
            compact_postal = candidate.values["postal_code"].removeprefix("〒")
            matched_postal = re.fullmatch(r"([0-9]{3})-?([0-9]{4})", compact_postal)
            if matched_postal:
                candidate.values["postal_code"] = (
                    f"{matched_postal.group(1)}-{matched_postal.group(2)}"
                )
            else:
                _bulk_error(
                    candidate,
                    "postal_code",
                    "郵便番号は7桁の数字（例: 123-4567）で入力してください。",
                )

        for field_name, label in (("last_name", "姓"), ("first_name", "名")):
            if not candidate.values[field_name]:
                _bulk_error(candidate, field_name, f"{label}を入力してください。")

        candidate.values["gender"] = _bulk_gender(candidate, raw.get("gender"))
        birth_date = _bulk_date(candidate, "birth_date", raw.get("birth_date"))
        if birth_date and birth_date > date.today():
            _bulk_error(candidate, "birth_date", "生年月日に未来の日付は指定できません。")
        candidate.values["birth_date"] = birth_date

        email = candidate.values["email"]
        if email:
            try:
                candidate.values["email"] = normalize_email(email)
            except EmailInvalid as exc:
                _bulk_error(candidate, "email", str(exc))

        allow_defect = _bulk_bool(candidate, "allow_defect", raw.get("allow_defect"))
        candidate.values["allow_defect"] = allow_defect

        if not allow_defect:
            for field_name, label in REQUIRED_FOR_COMPLETE:
                if not candidate.values[field_name]:
                    _bulk_error(
                        candidate,
                        field_name,
                        f"{label}が未入力です。不備一時受付を"
                        "許可するか、値を入力してください。",
                    )
            if not candidate.values["tel_mobile"] and not candidate.values["tel_home"]:
                _bulk_error(
                    candidate,
                    "tel_mobile",
                    "携帯電話と固定電話のいずれかを入力するか、不備一時"
                    "受付を許可してください。",
                )

        candidate.option_ids = _parse_option_codes(
            candidate, raw.get("option_codes"), options_by_code
        )
        candidate.wish_specs = _parse_wishes(
            candidate,
            raw.get("wishes"),
            hospitals_by_code,
            hospitals_by_name,
        )
        if not candidate.wish_specs and not any(
            error.field == "wishes" or error.field.startswith("wish")
            for error in candidate.errors
        ):
            _bulk_error(candidate, "wishes", "希望受診日時を1件以上入力してください。")

    if not candidates:
        raise PostalBulkValidationError(
            [
                PostalBulkFieldError(
                    row_no=0,
                    field="rows",
                    message="入力された行がありません。",
                )
            ]
        )

    slot_keys = {
        (spec.hospital_id, spec.slot_date, spec.start_time)
        for candidate in candidates
        for spec in candidate.wish_specs
    }
    # 「회장 + 날짜 + 시각」으로 칸을 찾는다. 예전에는 슬롯 행을 그 셋으로
    # 조회했다. 지금은 회장·날짜로 **회차**를 찾고, 시각이 격자의 몇 번째
    # 칸인지는 `time_grid` 가 답한다.
    slots_by_key: dict[tuple, SlotView] = {}
    if slot_keys:
        wanted_days = {(hid, day) for hid, day, _start in slot_keys}
        schedules = db.execute(
            select(HospitalSchedule).where(
                tuple_(
                    HospitalSchedule.hospital_id, HospitalSchedule.event_date
                ).in_(list(wanted_days))
            )
        ).scalars().all()

        by_day = {(s.hospital_id, s.event_date): s for s in schedules}
        for hospital_id, day, start in slot_keys:
            schedule = by_day.get((hospital_id, day))
            if schedule is None:
                continue
            index = time_grid.index_of(start)
            if index is None:
                continue
            view = grid.view_at(schedule, index)
            if view is not None:
                slots_by_key[(hospital_id, day, start)] = view

    for candidate in candidates:
        used_slot_ids: set[int] = set()
        for spec in candidate.wish_specs:
            slot = slots_by_key.get(
                (spec.hospital_id, spec.slot_date, spec.start_time)
            )
            if slot is None:
                _bulk_error(
                    candidate,
                    f"wish{spec.rank}_time",
                    "該当する会場・日付・時刻の予約枠が見つかりません。",
                )
                continue
            if slot.id in used_slot_ids:
                _bulk_error(
                    candidate,
                    f"wish{spec.rank}_time",
                    "同じ受診日時が他の希望順位と重複しています。",
                )
                continue
            used_slot_ids.add(slot.id)
            candidate.choices.append(
                _PostalSlotChoice(slot_id=slot.id, rank=spec.rank)
            )

        if not candidate.choices and not any(
            error.field == "wishes" or error.field.startswith("wish")
            for error in candidate.errors
        ):
            _bulk_error(candidate, "wishes", "有効な希望受診日時がありません。")

        if candidate.errors:
            continue

        candidate.payload = PostalReservationRequest(
            **candidate.values,
            slot_ids=[choice.slot_id for choice in candidate.choices],
            option_ids=candidate.option_ids,
        )

    # 현재 정원으로 입력 순서대로 배정 가능성을 시뮬레이션한다. 확정할 때는
    # 다시 FOR UPDATE 로 잠그고 검사하므로 이 값만 믿고 저장하지 않는다.
    # `slots` は 2026-08-28 の「スロット照会方式の変更」で削除された変数で、
    # ここだけ参照が残っていたため一括登録が必ず NameError で落ちていた。
    # いまの持ち主は `slots_by_key`（キー: 会場・日付・時刻）である。
    slot_views = list(slots_by_key.values())
    virtual_remaining = {
        slot.id: max(0, slot.capacity - slot.reserved_count) for slot in slot_views
    }
    slots_by_id = {slot.id: slot for slot in slot_views}
    for candidate in candidates:
        if candidate.errors or candidate.payload is None:
            continue
        skipped: list[str] = []
        for choice in sorted(candidate.choices, key=lambda item: item.rank):
            slot = slots_by_id[choice.slot_id]
            reason = _slot_unavailable_reason(
                slot, now, virtual_remaining.get(slot.id, 0)
            )
            if reason:
                skipped.append(f"第{choice.rank}希望 {reason}")
                continue
            candidate.planned_choice = choice
            virtual_remaining[slot.id] -= 1
            break
        if candidate.planned_choice is None:
            _bulk_error(
                candidate,
                "wishes",
                "希望日時がすべて予約不可です。" + " / ".join(skipped),
            )

    # 기존 예약 및 같은 일괄 입력 안의 중복을 모두 쓰기 전에 확인한다.
    duplicate_candidates: list[tuple[_BulkCandidate, int]] = []
    for candidate in candidates:
        if (
            candidate.errors
            or candidate.payload is None
            or candidate.planned_choice is None
        ):
            continue
        planned_slot = slots_by_id[candidate.planned_choice.slot_id]
        year = fiscal_year(planned_slot.slot_date)
        person = _find_target_person(db, candidate.payload)
        candidate.target_person_id = person.id if person else None
        duplicate = reservation_service.find_duplicate(
            db,
            target_person_id=candidate.target_person_id,
            last_name=candidate.payload.last_name,
            first_name=candidate.payload.first_name,
            birth_date=candidate.payload.birth_date,
            tel_mobile=candidate.payload.tel_mobile,
            tel_home=candidate.payload.tel_home,
            year=year,
        )
        if duplicate is not None:
            _bulk_error(
                candidate,
                "last_name",
                f"今年度すでに予約されている方です。(予約番号 {duplicate.reservation_no} / "
                f"{duplicate.slot_date} {duplicate.time_label})",
            )
            continue

        prior_duplicate = next(
            (
                prior
                for prior, prior_year in duplicate_candidates
                if _is_intra_bulk_duplicate(
                    prior,
                    candidate,
                    left_year=prior_year,
                    right_year=year,
                )
            ),
            None,
        )
        if prior_duplicate is not None:
            _bulk_error(
                candidate,
                "last_name",
                f"同じ一括入力の {prior_duplicate.row_no}行と重複している予約です。",
            )
        else:
            duplicate_candidates.append((candidate, year))

    errors = [
        error
        for candidate in sorted(candidates, key=lambda item: item.input_index)
        for error in candidate.errors
    ]
    if errors:
        raise PostalBulkValidationError(errors)
    return candidates


def create_postal_bulk(
    db: Session,
    request: PostalBulkRequest,
    *,
    admin: AdminUser,
    ip_address: str,
) -> PostalBulkResult:
    """최대 200개 그리드 행에서 빈 행을 빼고 검증한 뒤 원자적으로 저장한다."""
    now = datetime.now()
    candidates = _prepare_postal_bulk(db, request, now=now)

    # 여러 일괄 요청이 반대 순서의 희망을 가져도 데드락 가능성을 낮추도록
    # 참조할 수 있는 **회차의 예약 수 행**을 id 오름차순으로 먼저 잠근다.
    # 잠금 대상이 슬롯 행에서 회차 한 행으로 줄었으므로, 같은 날의 여러
    # 희망이 이제 잠금 하나로 묶인다. populate_existing 은 검증 쿼리 뒤
    # 변경된 최신 예약 수를 identity map 에 다시 채운다.
    schedule_ids = sorted(
        {
            time_grid.split_slot_id(choice.slot_id)[0]
            for candidate in candidates
            for choice in candidate.choices
        }
    )
    if schedule_ids:
        db.execute(
            select(ReservationCount)
            .where(ReservationCount.schedule_id.in_(schedule_ids))
            .order_by(ReservationCount.schedule_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalars().all()

    reservations: list[Reservation] = []
    results: list[PostalBulkReservationResult] = []
    for candidate in candidates:
        assert candidate.payload is not None  # 검증을 통과한 후보만 여기까지 온다
        try:
            reservation, result = _stage_postal(
                db,
                candidate.payload,
                candidate.choices,
                admin=admin,
                ip_address=ip_address,
                now=now,
            )
        except AdminReservationError as exc:
            field_name = "last_name" if "すでに予約" in str(exc) else "wishes"
            raise PostalBulkValidationError(
                [
                    PostalBulkFieldError(
                        row_no=candidate.row_no,
                        field=field_name,
                        message=str(exc),
                    )
                ]
            ) from exc
        reservations.append(reservation)
        results.append(
            PostalBulkReservationResult(
                row_no=candidate.row_no,
                **result.model_dump(),
            )
        )

    # 예약·옵션·좌석수·감사 로그가 모두 같은 커밋에 들어간다. 한 행이라도
    # flush/commit 에 실패하면 호출부의 rollback 으로 전체가 되돌아간다.
    db.commit()

    # SMTP 는 위 커밋 이후에만 실행하며, 메일 이력도 별도 트랜잭션이다.
    _send_postal_completion_emails(db, reservations)
    return PostalBulkResult(created_count=len(results), rows=results)


# ==========================================================================
# 메일 재발송
# ==========================================================================


def resend_mail(
    db: Session,
    reservation_id: int,
    template_key: str,
    *,
    admin: AdminUser,
    ip_address: str,
) -> tuple[bool, str]:
    """확인 메일을 다시 보낸다. 「메일이 안 왔다」는 문의의 표준 대응이다.

    (실제로 나갔는가, 화면 문구)를 돌려준다. 발송 API 가 없거나 실패해도
    요청 자체는 처리된 것이라 200 이지만, 화면이 「보냈습니다」로 읽으면 안 된다.
    """
    from app.services import mail_service

    reservation = get(db, reservation_id)
    if not reservation.email:
        raise AdminReservationError(
            "この予約にはメールアドレスが登録されていません。"
            "アドレスを先に登録してから再度お試しください。"
        )
    # 취소된 예약에 「予約が確定しました」를 다시 보내면, 받은 사람은 예약이
    # 살아 있다고 믿고 당일에 온다. 화면에서 단추를 감추는 것과 별개로 막는다.
    if reservation.status == "CANCELLED":
        raise AdminReservationError(
            "キャンセルされた予約には確認メールを再送信できません。"
        )

    log = mail_service.send(db, reservation, template_key)

    audit_service.write_log(
        db,
        admin=admin,
        action="MAIL_RESEND",
        target_type="reservation",
        target_id=reservation.id,
        target_label=f"{reservation.reservation_no} → {reservation.email}",
        after={"template": template_key, "status": log.status},
        ip_address=ip_address,
    )
    db.commit()

    if log.status == "SUCCESS":
        return True, f"{reservation.email} へ再送信しました。"
    return False, f"送信できませんでした。({log.error_message})"
