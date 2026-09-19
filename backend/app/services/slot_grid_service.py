"""정원 그리드를 「슬롯」처럼 읽게 해 주는 어댑터.

왜 이 모듈이 있는가
-------------------
시간표의 저장 모양이 **행(`slots`) 에서 그리드(`hospital_schedules.cap_*`)** 로
바뀌었다. 그런데 그 시간표를 읽는 코드는 백엔드 14개 파일에 흩어져 있고,
전부 「슬롯 하나」를 객체로 다룬다.

    slot.time_label · slot.remaining · slot.availability · slot.is_available

이 모듈은 그리드를 읽어 **예전 `Slot` 과 똑같이 생긴 객체**(`SlotView`)를
돌려준다. 덕분에

    · API 응답 모양이 바뀌지 않는다 → **프런트엔드를 고치지 않아도 된다**
    · 호출처를 한 파일씩 옮길 수 있다 → 어디서 깨졌는지 즉시 안다

전환이 끝난 뒤에도 이 모듈은 남는다. 그리드를 직접 `getattr` 로 만지는
코드가 여기저기 생기면, 격자를 넓힐 때 고칠 자리를 찾을 수 없기 때문이다.
**그리드에 손대는 곳은 여기와 `HospitalSchedule` 의 메서드뿐이다.**

slot_id 는 어디서 오는가
------------------------
`slots` 테이블이 없으므로 자동증가 id 도 없다. 대신 회차와 칸 번호를
한 정수로 접는다 (`time_grid.slot_id`). 프런트엔드는 이 값을 계산에
쓰지 않고 받은 그대로 되돌려 보내므로, 값이 어떻게 만들어지는지 몰라도 된다.
"""

from dataclasses import dataclass
from datetime import date, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import time_grid
from app.models.hospital import HospitalSchedule, ReservationCount

# 남은 좌석이 이 수 이하면 「잔여 적음」. 예전 `Slot.availability` 와 같은 값.
LIMITED_THRESHOLD = 3


# ==========================================================================
# 슬롯 한 칸
# ==========================================================================


@dataclass(frozen=True)
class SlotView:
    """그리드 한 칸을 예전 `Slot` 행처럼 보이게 감싼 것.

    **읽기 전용이다.** 값을 바꾸려면 회차(`HospitalSchedule`)나
    예약 수(`ReservationCount`)를 직접 만져야 한다. 사본에 쓴 값이
    조용히 사라지는 것을 막기 위해 `frozen` 으로 둔다.
    """

    id: int
    index: int
    schedule_id: int
    hospital_id: int
    slot_date: date
    start_time: time
    end_time: time
    capacity: int
    reserved_count: int
    is_closed: bool

    # ----------------------------------------------------------------------
    # 파생 값 — 예전 `Slot` 과 이름·의미가 같아야 한다
    # ----------------------------------------------------------------------

    @property
    def remaining(self) -> int:
        """남은 좌석 수. 음수가 되지 않도록 0 으로 자른다."""
        return max(0, self.capacity - self.reserved_count)

    @property
    def is_available(self) -> bool:
        """예약 가능 여부. (BR-07)"""
        return not self.is_closed and self.remaining > 0

    @property
    def availability(self) -> str:
        """예약 여부 표시 구분.

        색만으로 구분하지 않도록 화면에서는 기호(○ △ ×) · 텍스트 · 색을
        함께 사용한다. (plan.md §12.4)

            AVAILABLE : 여유
            LIMITED   : 잔여 3석 이하 — 서두르시라는 신호
            FULL      : 만석
            CLOSED    : 관리자가 접수를 닫음
        """
        if self.is_closed:
            return "CLOSED"
        if self.remaining <= 0:
            return "FULL"
        if self.remaining <= LIMITED_THRESHOLD:
            return "LIMITED"
        return "AVAILABLE"

    @property
    def time_label(self) -> str:
        """예: 09:00~09:30"""
        return time_grid.label(self.index)

    @property
    def period(self) -> str:
        """오전 / 오후 구분."""
        return time_grid.period(self.index)

    def __repr__(self) -> str:
        return (
            f"<SlotView h={self.hospital_id} {self.slot_date} "
            f"{self.time_label} {self.reserved_count}/{self.capacity}>"
        )


# ==========================================================================
# 회차 → 슬롯
# ==========================================================================


def counts_of(db: Session, schedule: HospitalSchedule) -> ReservationCount:
    """회차의 예약 수 행. 없으면 만든다.

    회차를 만들 때 함께 만들지만, 마이그레이션 이전에 생긴 회차나 손으로
    넣은 회차에는 없을 수 있다. 없다고 터지면 조회 화면이 통째로 멈춘다.
    """
    if schedule.counts is None:
        schedule.counts = ReservationCount(schedule_id=schedule.id)
        db.flush()
    return schedule.counts


def views_of(schedule: HospitalSchedule) -> list[SlotView]:
    """그 회차가 실제로 여는 시간대만. 시각 순.

    **정원이 `NULL` 인 칸은 돌려주지 않는다.** 그 칸은 「정원 0」이 아니라
    「그 시간대를 아예 열지 않음」이다. 점심시간을 만석으로 보여 줄 수는 없다.
    """
    counts = schedule.counts
    views: list[SlotView] = []

    for index in time_grid.indexes():
        capacity = schedule.capacity_at(index)
        if capacity is None:
            continue
        views.append(
            SlotView(
                id=time_grid.slot_id(schedule.id, index),
                index=index,
                schedule_id=schedule.id,
                hospital_id=schedule.hospital_id,
                slot_date=schedule.event_date,
                start_time=time_grid.start_time(index),
                end_time=time_grid.end_time(index),
                capacity=capacity,
                reserved_count=counts.reserved_at(index) if counts else 0,
                is_closed=schedule.is_closed_at(index),
            )
        )
    return views


def view_at(schedule: HospitalSchedule, index: int) -> SlotView | None:
    """한 칸만. 열지 않는 시간대면 `None`."""
    if not 0 <= index < time_grid.SLOT_COUNT:
        return None
    if schedule.capacity_at(index) is None:
        return None
    counts = schedule.counts
    return SlotView(
        id=time_grid.slot_id(schedule.id, index),
        index=index,
        schedule_id=schedule.id,
        hospital_id=schedule.hospital_id,
        slot_date=schedule.event_date,
        start_time=time_grid.start_time(index),
        end_time=time_grid.end_time(index),
        capacity=schedule.capacity_at(index),
        reserved_count=counts.reserved_at(index) if counts else 0,
        is_closed=schedule.is_closed_at(index),
    )


# ==========================================================================
# 조회
# ==========================================================================


def _schedules(
    db: Session,
    *,
    hospital_id: int | None = None,
    schedule_id: int | None = None,
    on: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    visible_only: bool = False,
) -> list[HospitalSchedule]:
    stmt = select(HospitalSchedule)
    if hospital_id is not None:
        stmt = stmt.where(HospitalSchedule.hospital_id == hospital_id)
    if schedule_id is not None:
        stmt = stmt.where(HospitalSchedule.id == schedule_id)
    if on is not None:
        stmt = stmt.where(HospitalSchedule.event_date == on)
    if date_from is not None:
        stmt = stmt.where(HospitalSchedule.event_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(HospitalSchedule.event_date <= date_to)
    if visible_only:
        stmt = stmt.where(HospitalSchedule.is_visible.is_(True))
    return list(
        db.execute(stmt.order_by(HospitalSchedule.event_date)).scalars()
    )


def schedule_of(db: Session, schedule_id: int) -> HospitalSchedule | None:
    return db.get(HospitalSchedule, schedule_id)


def slots_for_date(db: Session, hospital_id: int, on: date) -> list[SlotView]:
    """회장의 그 날 시간표. 예전 `select(Slot).where(hospital_id, slot_date)` 자리."""
    schedules = _schedules(db, hospital_id=hospital_id, on=on)
    if not schedules:
        return []
    return views_of(schedules[0])


def slots_for_schedule(db: Session, schedule_id: int) -> list[SlotView]:
    schedule = db.get(HospitalSchedule, schedule_id)
    return views_of(schedule) if schedule else []


def slots_in_range(
    db: Session,
    hospital_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[SlotView]:
    views: list[SlotView] = []
    for schedule in _schedules(
        db, hospital_id=hospital_id, date_from=date_from, date_to=date_to
    ):
        views.extend(views_of(schedule))
    return views


def find(db: Session, slot_id: int) -> SlotView | None:
    """프런트가 되돌려 보낸 `slot_id` 로 그 칸을 찾는다."""
    schedule_id, index = time_grid.split_slot_id(slot_id)
    schedule = db.get(HospitalSchedule, schedule_id)
    if schedule is None:
        return None
    return view_at(schedule, index)


def find_many(db: Session, slot_ids: list[int]) -> dict[int, SlotView]:
    """여러 칸을 한 번에. 회차 단위로 묶어 회차 수만큼만 조회한다."""
    by_schedule: dict[int, list[int]] = {}
    for value in slot_ids:
        schedule_id, index = time_grid.split_slot_id(value)
        by_schedule.setdefault(schedule_id, []).append(index)

    if not by_schedule:
        return {}

    schedules = db.execute(
        select(HospitalSchedule).where(HospitalSchedule.id.in_(by_schedule))
    ).scalars()

    found: dict[int, SlotView] = {}
    for schedule in schedules:
        for index in by_schedule.get(schedule.id, []):
            view = view_at(schedule, index)
            if view is not None:
                found[view.id] = view
    return found


# ==========================================================================
# 집계
# ==========================================================================
# 예전에는 `SUM(capacity)` 를 DB 에 시켰다. 그리드가 되면서 16개 칼럼을
# 더하는 SQL 이 되는데, 그것은 읽을 수 없고 격자가 넓어지면 같이 자란다.
#
# 대상이 회장 25곳 × 회차 두엇 = 수십 행뿐이므로 **파이썬에서 더한다.**
# 행이 수천 개가 되면 그때 다시 생각한다.


@dataclass(frozen=True)
class GridTotals:
    """한 회차(또는 한 날)의 합계."""

    capacity: int = 0
    reserved: int = 0
    remaining: int = 0          # 마감된 칸은 제외
    slot_count: int = 0
    closed_slots: int = 0

    @property
    def is_all_closed(self) -> bool:
        return bool(self.slot_count) and self.closed_slots == self.slot_count

    @property
    def availability(self) -> str:
        """날짜 단위 표시 구분. 슬롯보다 기준이 느슨하다 (5석)."""
        if self.remaining <= 0:
            return "FULL"
        if self.remaining <= 5:
            return "LIMITED"
        return "AVAILABLE"


def totals_of(schedule: HospitalSchedule) -> GridTotals:
    capacity = reserved = remaining = slot_count = closed = 0

    for view in views_of(schedule):
        slot_count += 1
        capacity += view.capacity
        reserved += view.reserved_count
        if view.is_closed:
            closed += 1
        else:
            remaining += view.remaining

    return GridTotals(
        capacity=capacity,
        reserved=reserved,
        remaining=remaining,
        slot_count=slot_count,
        closed_slots=closed,
    )


def totals_by_schedule(db: Session, schedule_ids=None) -> dict[int, GridTotals]:
    """회차 id → 합계. 목록 화면이 회차마다 조회하지 않도록 한 번에 준다."""
    stmt = select(HospitalSchedule)
    if schedule_ids is not None:
        stmt = stmt.where(HospitalSchedule.id.in_(list(schedule_ids)))
    return {s.id: totals_of(s) for s in db.execute(stmt).scalars()}


def totals_by_hospital(db: Session) -> dict[int, GridTotals]:
    """회장 id → 그 회장 전 회차의 합계. `slot_count` 는 칸의 총 수다."""
    merged: dict[int, GridTotals] = {}
    for schedule in db.execute(select(HospitalSchedule)).scalars():
        one = totals_of(schedule)
        prev = merged.get(schedule.hospital_id, GridTotals())
        merged[schedule.hospital_id] = GridTotals(
            capacity=prev.capacity + one.capacity,
            reserved=prev.reserved + one.reserved,
            remaining=prev.remaining + one.remaining,
            slot_count=prev.slot_count + one.slot_count,
            closed_slots=prev.closed_slots + one.closed_slots,
        )
    return merged


def open_days_by_hospital(db: Session) -> dict[int, int]:
    """회장 id → 시간표가 있는 날짜 수. 예전 `COUNT(DISTINCT slot_date)`."""
    days: dict[int, int] = {}
    for schedule in db.execute(select(HospitalSchedule)).scalars():
        if schedule.open_indexes():
            days[schedule.hospital_id] = days.get(schedule.hospital_id, 0) + 1
    return days


# ==========================================================================
# 예약 확정 — 잠금
# ==========================================================================


def lock_counts(db: Session, schedule_id: int) -> ReservationCount | None:
    """예약 수 행을 잠근다. 예약 확정은 반드시 이 뒤에 판정한다.

    잠금 단위가 「시간대 한 줄」에서 **「하루 한 행」** 으로 넓어졌다.
    같은 날 다른 시간대를 고른 두 사람이 서로를 기다린다는 뜻이다.
    회장 1곳의 하루가 161명이고 웹 접수가 초당 몇 건 수준이라 이 규모에서는
    문제가 되지 않는다. 대신 **마스터 행(`hospital_schedules`)은 잠그지
    않으므로**, 담당자가 정원을 고치는 동안에도 예약이 들어온다.
    """
    counts = db.execute(
        select(ReservationCount)
        .where(ReservationCount.schedule_id == schedule_id)
        .with_for_update()
    ).scalar_one_or_none()

    if counts is None:
        # 회차는 있는데 카운트 행이 없는 경우. 만들어 두고 다시 잠근다.
        schedule = db.get(HospitalSchedule, schedule_id)
        if schedule is None:
            return None
        counts_of(db, schedule)
        counts = db.execute(
            select(ReservationCount)
            .where(ReservationCount.schedule_id == schedule_id)
            .with_for_update()
        ).scalar_one_or_none()

    return counts


def reserved_delta(db: Session, schedule_id: int, index: int, delta: int) -> int:
    """예약 수를 증감한다. 잠금은 부르는 쪽이 이미 잡았다고 본다."""
    counts = db.execute(
        select(ReservationCount).where(ReservationCount.schedule_id == schedule_id)
    ).scalar_one_or_none()
    if counts is None:
        schedule = db.get(HospitalSchedule, schedule_id)
        if schedule is None:
            return 0
        counts = counts_of(db, schedule)
    return counts.add_at(index, delta)


def reserved_delta_for_slot(db: Session, slot_id: int, delta: int) -> int:
    schedule_id, index = time_grid.split_slot_id(slot_id)
    return reserved_delta(db, schedule_id, index, delta)
