"""정원 그리드가 슬롯과 한 칸도 다르지 않은지 대조한다.

    python -m scripts.verify_capacity_grid          # slots 가 있으면 대조까지
    python -m scripts.verify_capacity_grid --strict # 경고도 실패로 본다

무엇을 보는가
-------------
    ① slots ↔ 그리드    두 벌이 공존하는 동안만. 정원·예약수·마감이 같은가
    ② 예약 ↔ 예약 수     reservation_counts 가 reservations 와 맞는가
    ③ 회차 ↔ 예약        예약의 schedule_id 가 회장·검진일과 어긋나지 않는가
    ④ 격자 밖 시각        예약의 start_time 이 TIME_GRID 안에 있는가

②는 `slots` 를 지운 뒤에도 계속 유효하다. `reservation_counts` 는
`reservations` 에서 계산할 수 있는 **파생 데이터**라, 어긋나면 남은 좌석이
전부 틀린다. 어긋난 것을 고치는 것은 이 스크립트가 아니라

    python -m scripts.recount_reservations --apply
"""

import scripts._console  # noqa: F401  (콘솔 UTF-8 보정)
import sys
from collections import defaultdict

from sqlalchemy import func, select, text

from app.core import time_grid
from app.core.database import SessionLocal
from app.models.hospital import Hospital, HospitalSchedule, ReservationCount
from app.models.reservation import Reservation
from app.services import slot_grid_service as grid


class Report:
    def __init__(self, strict: bool = False) -> None:
        self.checks = 0
        self.failures: list[str] = []
        self.warnings: list[str] = []
        self.strict = strict

    def check(self, ok: bool, label: str, detail: str = "") -> None:
        self.checks += 1
        if ok:
            print(f"   [OK]   {label}")
            return
        self.failures.append(f"{label}{' — ' + detail if detail else ''}")
        print(f"   [FAIL] {label}")
        if detail:
            print(f"          {detail}")

    def warn(self, label: str) -> None:
        self.warnings.append(label)
        print(f"   [!]    {label}")

    @property
    def failed(self) -> bool:
        return bool(self.failures) or (self.strict and bool(self.warnings))


class _RawSlot:
    """지워지기 직전의 `slots` 행. 대조에 필요한 값만 담는다."""

    def __init__(self, id, schedule_id, start_time, capacity, reserved_count, is_closed):
        self.id = id
        self.schedule_id = schedule_id
        self.start_time = _as_time(start_time)
        self.capacity = int(capacity or 0)
        self.reserved_count = int(reserved_count or 0)
        self.is_closed = bool(is_closed)

    @property
    def time_label(self) -> str:
        index = time_grid.index_of(self.start_time)
        return time_grid.label(index) if index is not None else str(self.start_time)


def _as_time(value):
    """MySQL 의 TIME 은 드라이버에 따라 `timedelta` 로 온다."""
    if hasattr(value, "hour"):
        return value
    from datetime import time as _time

    seconds = int(value.total_seconds())
    return _time(seconds // 3600, (seconds % 3600) // 60)


def table_exists(db, table: str) -> bool:
    return bool(
        db.execute(
            text(
                "SELECT 1 FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
            ),
            {"t": table},
        ).scalar()
    )


# --------------------------------------------------------------------------
# ① slots ↔ 그리드
# --------------------------------------------------------------------------


def check_against_slots(db, report: Report) -> None:
    print("\n ① slots ↔ 정원 그리드")

    if not table_exists(db, "slots"):
        print("   [i]    slots 가 이미 없습니다 — 이 대조는 건너뜁니다")
        return

    # `Slot` 모델은 이미 지워졌다. 테이블만 남아 있는 과도기 상태를 위해
    # ORM 없이 원시 SQL 로 읽는다. 이 분기는 `--drop` 뒤로는 돌지 않는다.
    slots = [
        _RawSlot(*row)
        for row in db.execute(
            text(
                "SELECT id, schedule_id, start_time, capacity, reserved_count, "
                "       is_closed FROM slots"
            )
        ).all()
    ]
    if not slots:
        print("   [i]    slots 가 비어 있습니다")
        return

    mismatched: list[str] = []
    orphan: list[str] = []

    for slot in slots:
        schedule = db.get(HospitalSchedule, slot.schedule_id)
        if schedule is None:
            orphan.append(f"슬롯 {slot.id} 의 회차 {slot.schedule_id} 가 없습니다")
            continue

        index = time_grid.index_of(slot.start_time)
        if index is None:
            orphan.append(
                f"{schedule.event_date} {slot.start_time} 은 격자 밖 시각입니다"
            )
            continue

        view = grid.view_at(schedule, index)
        if view is None:
            mismatched.append(
                f"{schedule.event_date} {slot.time_label} — 그리드가 비어 있습니다 "
                f"(슬롯은 정원 {slot.capacity})"
            )
            continue

        if view.capacity != slot.capacity:
            mismatched.append(
                f"{schedule.event_date} {slot.time_label} 정원 "
                f"슬롯 {slot.capacity} ≠ 그리드 {view.capacity}"
            )
        if view.reserved_count != slot.reserved_count:
            mismatched.append(
                f"{schedule.event_date} {slot.time_label} 예약 수 "
                f"슬롯 {slot.reserved_count} ≠ 그리드 {view.reserved_count}"
            )
        if view.is_closed != slot.is_closed:
            mismatched.append(
                f"{schedule.event_date} {slot.time_label} 마감 "
                f"슬롯 {slot.is_closed} ≠ 그리드 {view.is_closed}"
            )

    report.check(
        not orphan,
        f"슬롯 {len(slots)}행이 전부 회차와 격자에 들어맞는다",
        " / ".join(orphan[:3]),
    )
    report.check(
        not mismatched,
        "슬롯과 그리드의 정원·예약수·마감이 같다",
        " / ".join(mismatched[:5]) + (f" 외 {len(mismatched) - 5}건" if len(mismatched) > 5 else ""),
    )

    # 반대 방향 — 그리드에만 있는 칸
    grid_cells = 0
    for schedule in db.execute(select(HospitalSchedule)).scalars():
        grid_cells += len(schedule.open_indexes())
    report.check(
        grid_cells == len(slots),
        f"칸 수가 같다 (슬롯 {len(slots)} / 그리드 {grid_cells})",
        "그리드에만 있거나 슬롯에만 있는 칸이 있습니다",
    )


# --------------------------------------------------------------------------
# ② 예약 ↔ 예약 수
# --------------------------------------------------------------------------


def check_counts(db, report: Report) -> None:
    print("\n ② reservations ↔ reservation_counts")

    # 취소된 예약은 자리를 차지하지 않는다. 예약 확정·취소 경로가 카운트를
    # 올리고 내리므로, 살아 있는 예약만 세는 것이 진실이다.
    rows = db.execute(
        select(
            Reservation.schedule_id,
            Reservation.start_time,
            func.count(),
        )
        .where(Reservation.status != "CANCELLED")
        .group_by(Reservation.schedule_id, Reservation.start_time)
    ).all()

    truth: dict[tuple[int, int], int] = {}
    off_grid: list[str] = []
    for schedule_id, start, count in rows:
        index = time_grid.index_of(start)
        if index is None:
            off_grid.append(f"회차 {schedule_id} 의 {start} 은 격자 밖입니다")
            continue
        truth[(schedule_id, index)] = int(count)

    report.check(
        not off_grid,
        "모든 예약의 시각이 격자 안에 있다",
        " / ".join(off_grid[:3]),
    )

    stored: dict[tuple[int, int], int] = {}
    for counts in db.execute(select(ReservationCount)).scalars():
        for index in time_grid.indexes():
            value = counts.reserved_at(index)
            if value:
                stored[(counts.schedule_id, index)] = value

    drift: list[str] = []
    for key in set(truth) | set(stored):
        want = truth.get(key, 0)
        have = stored.get(key, 0)
        if want != have:
            schedule = db.get(HospitalSchedule, key[0])
            when = schedule.event_date if schedule else f"회차 {key[0]}"
            drift.append(
                f"{when} {time_grid.label(key[1])} — 예약 {want}건인데 {have} 로 적혀 있습니다"
            )

    report.check(
        not drift,
        f"예약 수가 실제 예약과 맞는다 (칸 {len(set(truth) | set(stored))}개 대조)",
        " / ".join(drift[:5])
        + (f" 외 {len(drift) - 5}건" if len(drift) > 5 else "")
        + "  → python -m scripts.recount_reservations --apply",
    )


# --------------------------------------------------------------------------
# ③ 회차 ↔ 예약
# --------------------------------------------------------------------------


def check_reservation_links(db, report: Report) -> None:
    print("\n ③ 예약이 가리키는 회차")

    wrong = db.execute(
        select(func.count())
        .select_from(Reservation)
        .join(HospitalSchedule, Reservation.schedule_id == HospitalSchedule.id)
        .where(
            (Reservation.slot_date != HospitalSchedule.event_date)
            | (Reservation.hospital_id != HospitalSchedule.hospital_id)
        )
    ).scalar() or 0

    report.check(
        wrong == 0,
        "예약의 회장·검진일이 회차와 일치한다",
        f"어긋난 예약 {wrong}건",
    )

    orphan = db.execute(
        select(func.count())
        .select_from(Reservation)
        .outerjoin(HospitalSchedule, Reservation.schedule_id == HospitalSchedule.id)
        .where(HospitalSchedule.id.is_(None))
    ).scalar() or 0

    report.check(orphan == 0, "회차가 없는 예약이 없다", f"{orphan}건")


# --------------------------------------------------------------------------
# ④ 그리드 구조
# --------------------------------------------------------------------------


def check_grid_shape(db, report: Report) -> None:
    print("\n ④ 그리드 구조")

    schedules = db.execute(select(HospitalSchedule)).scalars().all()

    no_counts = [s for s in schedules if s.counts is None]
    report.check(
        not no_counts,
        "모든 회차에 예약 수 행이 있다",
        f"없는 회차 {len(no_counts)}건",
    )

    empty = [s for s in schedules if not s.open_indexes()]
    if empty:
        report.warn(
            f"시간표가 비어 있는 회차 {len(empty)}건 — 이용자 화면에 그 날짜가 뜨지 않습니다 "
            f"({', '.join(str(s.event_date) for s in empty[:5])}"
            f"{' …' if len(empty) > 5 else ''})"
        )

    # 예약이 있는데 정원이 그보다 작은 칸 — 오버부킹 상태
    over: list[str] = []
    for schedule in schedules:
        for view in grid.views_of(schedule):
            if view.reserved_count > view.capacity:
                over.append(
                    f"{schedule.event_date} {view.time_label} "
                    f"예약 {view.reserved_count} > 정원 {view.capacity}"
                )
    report.check(
        not over,
        "정원을 넘긴 칸이 없다",
        " / ".join(over[:5]),
    )


# --------------------------------------------------------------------------


def summary(db) -> None:
    print("\n 지금 그리드에 들어 있는 것")
    hospitals = db.execute(
        select(Hospital).order_by(Hospital.sort_order, Hospital.id)
    ).scalars().all()

    totals = defaultdict(int)
    for hospital in hospitals:
        if not hospital.schedules:
            continue
        for schedule in hospital.schedules:
            t = grid.totals_of(schedule)
            totals["회차"] += 1
            totals["칸"] += t.slot_count
            totals["정원"] += t.capacity
            totals["예약"] += t.reserved

    print(f"   회장 {len(hospitals)}곳 · 회차 {totals['회차']}건 · "
          f"칸 {totals['칸']}개 · 정원 {totals['정원']} · 예약 {totals['예약']}")


def main() -> int:
    strict = "--strict" in sys.argv[1:]
    report = Report(strict)

    db = SessionLocal()
    try:
        print("=" * 78)
        print(" 정원 그리드 검증")
        print("=" * 78)

        check_against_slots(db, report)
        check_counts(db, report)
        check_reservation_links(db, report)
        check_grid_shape(db, report)
        summary(db)

        print("\n" + "=" * 78)
        if report.failed:
            print(f" 확인 {report.checks}건 중 {len(report.failures)}건 실패")
            for line in report.failures:
                print(f"   · {line}")
            if strict and report.warnings:
                print(f" 경고 {len(report.warnings)}건 (--strict)")
            print("=" * 78)
            return 1

        note = f" · 경고 {len(report.warnings)}건" if report.warnings else ""
        print(f" 확인 {report.checks}건 전부 통과{note}")
        print("=" * 78)
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
