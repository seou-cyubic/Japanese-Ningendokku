"""`reservation_counts` 를 실제 예약에서 다시 계산한다.

    python -m scripts.recount_reservations            # 어긋난 곳만 보여 준다
    python -m scripts.recount_reservations --apply    # 실제로 맞춘다

왜 필요한가
-----------
`reservation_counts` 는 `reservations` 를 세면 언제든 다시 만들 수 있는
**파생 데이터**다. 그럼에도 따로 두는 이유는 예약 한 건마다 수만 건을
세지 않기 위해서다 (`app/models/hospital.py` 의 `ReservationCount` 참조).

파생 데이터는 어긋난다. 예약 확정 도중에 프로세스가 죽거나, DB 를 손으로
고치거나, 예약을 SQL 로 지우면 카운트만 남는다. **어긋나면 남은 좌석이
전부 틀리므로** 조용히 두면 안 된다.

이 스크립트가 진실이다
----------------------
진실은 `reservations` 이고, 세는 규칙은 하나다 —
**취소되지 않은 예약을 開催回 × 시각으로 센다.** 그 밖의 판정은 없다.
"""

import scripts._console  # noqa: F401  (콘솔 UTF-8 보정)
import sys

from sqlalchemy import func, select

from app.core import time_grid
from app.core.database import SessionLocal
from app.models.hospital import HospitalSchedule, ReservationCount
from app.models.reservation import Reservation


def truth(db) -> dict[tuple[int, int], int]:
    """실제 예약을 (회차, 枠) 으로 센다. 취소는 자리를 차지하지 않는다."""
    counted: dict[tuple[int, int], int] = {}
    rows = db.execute(
        select(Reservation.schedule_id, Reservation.start_time, func.count())
        .where(Reservation.status != "CANCELLED")
        .group_by(Reservation.schedule_id, Reservation.start_time)
    ).all()

    for schedule_id, start, count in rows:
        index = time_grid.index_of(start)
        if index is None:
            continue
        counted[(int(schedule_id), index)] = int(count)
    return counted


def stored(db) -> dict[tuple[int, int], int]:
    values: dict[tuple[int, int], int] = {}
    for counts in db.execute(select(ReservationCount)).scalars():
        for index in time_grid.indexes():
            value = counts.reserved_at(index)
            if value:
                values[(counts.schedule_id, index)] = value
    return values


def main() -> int:
    apply = "--apply" in sys.argv[1:]

    db = SessionLocal()
    try:
        want = truth(db)
        have = stored(db)

        drift = []
        for key in sorted(set(want) | set(have)):
            a, b = want.get(key, 0), have.get(key, 0)
            if a != b:
                drift.append((key, b, a))

        print("=" * 78)
        print(" 予約数の再計算")
        print("=" * 78)
        print(f"  実際に予約がある枠  {len(want)}件")
        print(f"  カウントが入った枠  {len(have)}件")
        print(f"  食い違った枠        {len(drift)}件")
        print("-" * 78)

        if not drift:
            print(" すべて一致しています。修正の必要はありません。")
            print("=" * 78)
            return 0

        for (schedule_id, index), before, after in drift[:40]:
            schedule = db.get(HospitalSchedule, schedule_id)
            when = schedule.event_date if schedule else f"開催回 {schedule_id}"
            print(f"   {when} {time_grid.label(index)}  {before} → {after}")
        if len(drift) > 40:
            print(f"   … ほか {len(drift) - 40}枠")

        if not apply:
            print("-" * 78)
            print(" まだ修正していません。反映するには --apply を付けてください。")
            print("=" * 78)
            return 1

        # 회차마다 한 번씩만 만지도록 묶는다.
        by_schedule: dict[int, list[tuple[int, int]]] = {}
        for (schedule_id, index), _before, after in drift:
            by_schedule.setdefault(schedule_id, []).append((index, after))

        for schedule_id, cells in by_schedule.items():
            counts = db.execute(
                select(ReservationCount).where(
                    ReservationCount.schedule_id == schedule_id
                )
            ).scalar_one_or_none()
            if counts is None:
                schedule = db.get(HospitalSchedule, schedule_id)
                if schedule is None:
                    continue
                counts = ReservationCount(schedule_id=schedule_id)
                db.add(counts)
                db.flush()
            for index, value in cells:
                counts.set_reserved_at(index, value)

        db.commit()
        print("-" * 78)
        print(f" {len(drift)}枠を実際の予約に合わせました。")
        print("=" * 78)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
