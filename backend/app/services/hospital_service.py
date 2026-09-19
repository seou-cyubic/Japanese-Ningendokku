"""회장 · 개최 회차 · 예약 슬롯 조회 업무 로직 (U-12).

이용자가 회장을 고르면 그 회장의 예약 가능 날짜와, 선택한 날짜의
30분 단위 시간표(총 좌석 / 예약된 좌석 / 남은 좌석)를 돌려준다.

회장은 여러 날 연다
-------------------
같은 시민회관을 7월에 한 번, 10월에 한 번 빌리는 것이 실제 운영이다.
그래서 「접수 중인가」는 **회장이 아니라 회차마다** 답이 다르다.

    · 회장 목록  — 접수 중인 회차가 **하나라도** 있으면 남긴다
    · 날짜 목록  — 접수 중인 회차의 날짜**만** 남긴다

둘 중 하나만 적용하면 화면이 어긋난다. 목록에만 걸면 눌러서 들어간 뒤
이미 마감된 날짜가 달력에 뜨고, 날짜에만 걸면 고를 날이 하나도 없는
회장이 목록에 남아 「고장난 화면」으로 읽힌다.
"""

from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.hospital import Hospital, HospitalSchedule
from app.services import slot_grid_service as grid
from app.schemas.hospital import (
    AvailabilityResponseData,
    DateSummary,
    HospitalSummary,
    ScheduleSummary,
    SlotDetail,
)

WEEKDAY_JA = ["月", "火", "水", "木", "金", "土", "日"]


def _schedule_open(today: date):
    """접수 중인 회차 조건.

    마감일이 비어 있는 회차는 거르지 않는다. 마스터에 값이 없다는 이유로
    접수를 막으면, 데이터가 덜 들어온 것이 곧 「예약 불가」가 된다.
    개최일이 지난 회차는 마감일과 무관하게 닫는다.
    """
    return (
        HospitalSchedule.is_visible.is_(True),
        HospitalSchedule.event_date >= today,
        or_(
            HospitalSchedule.booking_close_date.is_(None),
            HospitalSchedule.booking_close_date >= today,
        ),
    )


def _has_open_schedule(today: date):
    """접수 중인 회차가 하나라도 있는 회장 조건 (EXISTS).

    회차가 하나도 없는 회장은 걸러진다. 고를 수 있는 날이 없는 회장을
    목록에 남기면, 눌러서 달력을 열었을 때 빈 화면을 보게 된다.
    """
    return (
        select(HospitalSchedule.id)
        .where(HospitalSchedule.hospital_id == Hospital.id, *_schedule_open(today))
        .exists()
    )


def _to_schedule_summary(s: HospitalSchedule, today: date) -> ScheduleSummary:
    return ScheduleSummary(
        id=s.id,
        event_date=s.event_date,
        weekday=WEEKDAY_JA[s.event_date.weekday()],
        booking_close_date=s.booking_close_date,
        open_time=s.open_time,
        reception_end_time=s.reception_end_time,
        is_booking_open=s.is_open_for_booking(today),
        note=s.note,
    )


def _to_summary(h: Hospital, today: date) -> HospitalSummary:
    # 이용자에게는 **아직 접수 중인 회차만** 보여 준다. 지난 회차까지
    # 늘어놓으면 목록이 길어지기만 하고 고를 수 없는 날이 섞인다.
    open_schedules = [
        s for s in h.schedules if s.is_visible and s.is_open_for_booking(today)
    ]
    primary = open_schedules[0] if open_schedules else None

    return HospitalSummary(
        id=h.id,
        code=h.code,
        name=h.name,
        region=h.region,
        area=h.area,
        city=h.city,
        address=h.address,
        tel=h.contact_tel,
        access_info=h.access_info,
        schedules=[_to_schedule_summary(s, today) for s in open_schedules],
        event_date=primary.event_date if primary else None,
        booking_close_date=primary.booking_close_date if primary else None,
        open_time=primary.open_time if primary else None,
        reception_end_time=primary.reception_end_time if primary else None,
        has_parking=h.has_parking,
        latitude=h.latitude,
        longitude=h.longitude,
    )


def list_hospitals(db: Session, today: date | None = None) -> list[HospitalSummary]:
    """예약 화면에 표시할 회장 목록. (BR-14 표시/비표시 + 접수 마감일 반영)"""
    today = today or date.today()
    stmt = (
        select(Hospital)
        .where(Hospital.is_visible.is_(True), _has_open_schedule(today))
        .order_by(Hospital.sort_order, Hospital.id)
    )
    return [_to_summary(h, today) for h in db.execute(stmt).scalars()]


def get_hospital(
    db: Session, hospital_id: int, today: date | None = None
) -> Hospital | None:
    today = today or date.today()
    return db.execute(
        select(Hospital).where(
            Hospital.id == hospital_id,
            Hospital.is_visible.is_(True),
            _has_open_schedule(today),
        )
    ).scalar_one_or_none()


def _date_summaries(db: Session, hospital_id: int, today: date) -> list[DateSummary]:
    """접수 중인 회차의 날짜별 합계.

    예전에는 슬롯 수백 행을 DB 에서 `SUM` 했다. 지금은 한 회차가 한 행이라
    **회장 1곳에 많아야 서너 행**이며, 합계는 그리드 16칸을 더하면 된다.
    16개 칼럼을 더하는 SQL 을 쓰는 것보다 파이썬에서 더하는 편이 읽기 쉽고,
    격자가 넓어져도 이 코드는 그대로다.

    마감된 회차의 날짜는 애초에 가져오지 않는다 (`_schedule_open`).
    """
    stmt = (
        select(HospitalSchedule)
        .where(HospitalSchedule.hospital_id == hospital_id, *_schedule_open(today))
        .order_by(HospitalSchedule.event_date)
    )

    summaries: list[DateSummary] = []

    for schedule in db.execute(stmt).scalars():
        totals = grid.totals_of(schedule)
        if not totals.slot_count:
            # 시간표가 아직 없는 회차. 고를 수 있는 시간이 없으므로 날짜
            # 목록에 내지 않는다 — 눌러도 빈 시간표만 뜬다.
            continue

        summaries.append(
            DateSummary(
                date=schedule.event_date,
                weekday=WEEKDAY_JA[schedule.event_date.weekday()],
                schedule_id=schedule.id,
                total_capacity=totals.capacity,
                total_reserved=totals.reserved,
                remaining=totals.remaining,
                availability=totals.availability,
                is_holiday=schedule.is_holiday(),
            )
        )

    return summaries


def _slot_details(db: Session, hospital_id: int, target: date) -> list[SlotDetail]:
    return [
        SlotDetail(
            slot_id=s.id,
            period=s.period,
            start_time=s.start_time.strftime("%H:%M"),
            end_time=s.end_time.strftime("%H:%M"),
            time_label=s.time_label,
            capacity=s.capacity,
            reserved=s.reserved_count,
            remaining=s.remaining,
            availability=s.availability,
            is_available=s.is_available,
        )
        for s in grid.slots_for_date(db, hospital_id, target)
    ]


def get_availability(
    db: Session,
    hospital: Hospital,
    target_date: date | None,
    today: date,
) -> AvailabilityResponseData:
    """회장의 예약 가능 날짜 + 선택한 날짜의 시간표를 반환한다."""
    dates = _date_summaries(db, hospital.id, today)

    # 날짜를 지정하지 않았으면 예약 가능한 가장 이른 날을 기본 선택한다.
    # 만석인 날을 먼저 보여 주면 「예약이 안 되는 곳」처럼 보인다.
    if target_date is None:
        selectable = [d for d in dates if d.availability != "FULL"]
        target_date = (selectable or dates)[0].date if dates else None
    elif not any(d.date == target_date for d in dates):
        # 마감된 회차의 날짜를 주소창으로 직접 넣은 경우다. 빈 시간표를
        # 돌려주는 대신 고를 수 있는 날로 되돌린다.
        target_date = dates[0].date if dates else None

    slots = _slot_details(db, hospital.id, target_date) if target_date else []

    return AvailabilityResponseData(
        hospital=_to_summary(hospital, today),
        dates=dates,
        selected_date=target_date,
        slots=slots,
        total_capacity=sum(s.capacity for s in slots),
        total_reserved=sum(s.reserved for s in slots),
        total_remaining=sum(s.remaining for s in slots if s.availability != "CLOSED"),
    )
