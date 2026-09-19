"""슬롯 行 → 정원 그리드 마이그레이션.

    python -m scripts.migrate_capacity_grid            # 무엇이 바뀌는지만 본다
    python -m scripts.migrate_capacity_grid --apply    # 실제로 옮긴다
    python -m scripts.migrate_capacity_grid --drop     # 옮긴 뒤 slots 를 지운다

무엇을 옮기는가
---------------
    slots(schedule_id, start_time, capacity, reserved_count, is_closed)   ← 行
        ↓
    hospital_schedules.cap_HHMM · closed_mask                              ← 그리드
    reservation_counts.res_HHMM

그리고 `reservations.slot_id` 를 `schedule_id` 로 바꿔 단다. 예약은 이미
`slot_date` 와 `start_time` 을 자기 行에 갖고 있으므로, 슬롯이 없어져도
「어느 회차의 몇 시」인지 잃지 않는다.

두 벌을 잠시 함께 둔다
----------------------
`--apply` 는 **`slots` 를 지우지 않는다.** 그리드를 채우고 예약을 옮길
뿐이다. 두 벌이 공존하는 동안 `verify_capacity_grid` 가 한 칸씩 대조할
수 있고, 그 대조가 통과한 뒤에 `--drop` 으로 지운다.

    python -m scripts.migrate_capacity_grid --apply
    python -m scripts.verify_capacity_grid
    python -m scripts.migrate_capacity_grid --drop

되돌릴 수 없다
--------------
`--drop` 은 테이블을 지운다. 그 전에 덤프를 떠 두기 바란다.

    mysqldump -u root -p kenshin_reservation > backup.sql
"""

import scripts._console  # noqa: F401  (콘솔 UTF-8 보정)
import sys

from sqlalchemy import select, text

from app.core import time_grid
from app.core.database import Base, SessionLocal, engine
from app.models.hospital import (  # noqa: F401
    Hospital,
    HospitalSchedule,
    ReservationCount,
)
from app.models.reservation import Reservation  # noqa: F401


def columns_of(db, table: str) -> set[str]:
    rows = db.execute(
        text(
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
        ),
        {"t": table},
    ).all()
    return {row[0] for row in rows}


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
# 살펴보기
# --------------------------------------------------------------------------


def survey(db) -> dict:
    info: dict = {
        "has_slots": table_exists(db, "slots"),
        "has_counts": table_exists(db, "reservation_counts"),
    }
    schedule_columns = columns_of(db, "hospital_schedules")
    info["grid_ready"] = set(time_grid.CAPACITY_COLUMNS) <= schedule_columns
    info["has_closed_mask"] = "closed_mask" in schedule_columns

    reservation_columns = columns_of(db, "reservations")
    info["res_has_slot_id"] = "slot_id" in reservation_columns
    info["res_has_schedule_id"] = "schedule_id" in reservation_columns

    info["schedules"] = int(
        db.execute(text("SELECT COUNT(*) FROM hospital_schedules")).scalar() or 0
    )
    info["reservations"] = int(
        db.execute(text("SELECT COUNT(*) FROM reservations")).scalar() or 0
    )
    info["slots"] = (
        int(db.execute(text("SELECT COUNT(*) FROM slots")).scalar() or 0)
        if info["has_slots"] else 0
    )

    if info["has_slots"]:
        off_grid = db.execute(
            text("SELECT DISTINCT start_time FROM slots ORDER BY start_time")
        ).scalars().all()
        info["off_grid"] = [
            t for t in off_grid if time_grid.index_of(_as_time(t)) is None
        ]
    else:
        info["off_grid"] = []

    return info


def _as_time(value):
    """MySQL 의 TIME 은 드라이버에 따라 `timedelta` 로 온다."""
    if hasattr(value, "hour"):
        return value
    seconds = int(value.total_seconds())
    from datetime import time as _time

    return _time(seconds // 3600, (seconds % 3600) // 60)


# --------------------------------------------------------------------------
# 옮기기
# --------------------------------------------------------------------------


def add_grid_columns(db) -> int:
    """`hospital_schedules` 에 그리드 칼럼을 붙인다.

    `create_all` 은 **이미 있는 테이블은 件드리지 않는다.** 새 테이블만
    만들 뿐이라 칼럼 추가는 여기서 직접 해야 한다. 이것을 빼먹으면
    모델에는 있고 DB 에는 없는 칼럼이 생겨, 첫 조회에서
    `Unknown column 'cap_0900'` 로 터진다.
    """
    existing = columns_of(db, "hospital_schedules")
    added = 0

    for index in time_grid.indexes():
        column = time_grid.capacity_column(index)
        if column in existing:
            continue
        db.execute(
            text(
                f"ALTER TABLE hospital_schedules ADD COLUMN {column} INT NULL "
                f"COMMENT '{time_grid.label(index)} 정원'"
            )
        )
        added += 1

    if "closed_mask" not in existing:
        db.execute(
            text(
                "ALTER TABLE hospital_schedules "
                "ADD COLUMN closed_mask INT NOT NULL DEFAULT 0 "
                "COMMENT '시간대 강제 마감 (16비트)'"
            )
        )
        added += 1

    db.commit()
    return added


def fill_grid(db) -> tuple[int, int, list[str]]:
    """슬롯을 회차의 그리드로 접는다. → (회차 수, 칸 수, 경고)"""
    notes: list[str] = []
    if not table_exists(db, "slots"):
        return 0, 0, ["slots がありません — すでに移行済みか、新規に作成した DB です"]

    schedules = db.execute(select(HospitalSchedule)).scalars().all()
    cells = 0

    for schedule in schedules:
        counts = schedule.counts
        if counts is None:
            counts = ReservationCount(schedule_id=schedule.id)
            db.add(counts)
            schedule.counts = counts

        # 그리드를 먼저 비운다. 두 번 돌렸을 때 예전 값이 남아 있으면
        # 시트에서 빠진 시간대가 계속 살아 있게 된다.
        for index in time_grid.indexes():
            schedule.set_capacity_at(index, None)
            counts.set_reserved_at(index, 0)
        schedule.closed_mask = 0

        for row in db.execute(
            text(
                "SELECT id, start_time, capacity, reserved_count, is_closed "
                "  FROM slots WHERE schedule_id = :sid"
            ),
            {"sid": schedule.id},
        ).all():
            slot_id, start, capacity, reserved, closed = row
            index = time_grid.index_of(_as_time(start))
            if index is None:
                notes.append(
                    f"{schedule.event_date} {start} はグリッドにない時刻のため"
                    f"移行できませんでした (スロット id={slot_id})"
                )
                continue
            schedule.set_capacity_at(index, int(capacity or 0))
            counts.set_reserved_at(index, int(reserved or 0))
            schedule.set_closed_at(index, bool(closed))
            cells += 1

    db.flush()
    return len(schedules), cells, notes


def repoint_reservations(db) -> int:
    """`reservations.slot_id` → `schedule_id`.

    슬롯 id 로 회차를 찾아 채운 뒤, 옛 칼럼과 외래키를 떼어 낸다.
    """
    reservation_columns = columns_of(db, "reservations")

    if "schedule_id" not in reservation_columns:
        db.execute(text("ALTER TABLE reservations ADD COLUMN schedule_id INT NULL"))
        db.commit()
        print("   schedule_id カラムを追加", flush=True)

    filled = 0
    if "slot_id" in reservation_columns:
        filled = db.execute(
            text(
                "UPDATE reservations r "
                "  JOIN slots s ON s.id = r.slot_id "
                "   SET r.schedule_id = s.schedule_id "
                " WHERE r.schedule_id IS NULL"
            )
        ).rowcount
    else:
        # 슬롯이 이미 없는 환경. 회장 + 검진일로 회차를 찾는다.
        filled = db.execute(
            text(
                "UPDATE reservations r "
                "  JOIN hospital_schedules h "
                "    ON h.hospital_id = r.hospital_id AND h.event_date = r.slot_date "
                "   SET r.schedule_id = h.id "
                " WHERE r.schedule_id IS NULL"
            )
        ).rowcount

    db.commit()

    left = int(
        db.execute(
            text("SELECT COUNT(*) FROM reservations WHERE schedule_id IS NULL")
        ).scalar() or 0
    )
    if left:
        raise SystemExit(
            f" 開催回が見つからない予約が {left}件残っています。中断します。\n"
            " (slot_id が指すスロットがないか、会場・受診日がどの開催回とも一致しません)"
        )

    db.execute(
        text("ALTER TABLE reservations MODIFY COLUMN schedule_id INT NOT NULL")
    )

    has_fk = db.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.KEY_COLUMN_USAGE "
            " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'reservations' "
            "   AND COLUMN_NAME = 'schedule_id' "
            "   AND REFERENCED_TABLE_NAME = 'hospital_schedules'"
        )
    ).scalar()
    if not has_fk:
        # RESTRICT 다. 예약이 걸린 회차를 지우려는 시도를 DB 가 막는다 —
        # 예전에 `slots.id` 의 RESTRICT 가 하던 일이 한 층 위로 올라온다.
        db.execute(
            text(
                "ALTER TABLE reservations ADD CONSTRAINT fk_res_schedule "
                "FOREIGN KEY (schedule_id) REFERENCES hospital_schedules(id) "
                "ON DELETE RESTRICT"
            )
        )
        print("   schedule_id 外部キーを追加 (RESTRICT)", flush=True)

    db.commit()
    return filled


def drop_slots(db) -> None:
    """`slots` 와 `reservations.slot_id` 를 지운다. 대조가 끝난 뒤에만."""
    reservation_columns = columns_of(db, "reservations")

    if "slot_id" in reservation_columns:
        fk = db.execute(
            text(
                "SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE "
                " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'reservations' "
                "   AND COLUMN_NAME = 'slot_id' AND REFERENCED_TABLE_NAME = 'slots'"
            )
        ).scalar()
        if fk:
            db.execute(text(f"ALTER TABLE reservations DROP FOREIGN KEY {fk}"))
        db.execute(text("ALTER TABLE reservations DROP COLUMN slot_id"))
        print(" reservations.slot_id を削除", flush=True)

    if table_exists(db, "slots"):
        db.execute(text("DROP TABLE slots"))
        print(" slots テーブルを削除", flush=True)

    db.commit()


# --------------------------------------------------------------------------


def main() -> int:
    argv = sys.argv[1:]
    apply = "--apply" in argv
    drop = "--drop" in argv

    db = SessionLocal()
    try:
        info = survey(db)

        print("=" * 78)
        print(" スロット行 → 定員グリッド")
        print("=" * 78)
        print(f"  開催回          {info['schedules']}件")
        print(f"  スロット        {info['slots']}行")
        print(f"  予約            {info['reservations']}件")
        print()
        print(f"  cap_* グリッド  {'あり' if info['grid_ready'] else 'なし — 作成します'}")
        print(f"  closed_mask      {'あり' if info['has_closed_mask'] else 'なし — 作成します'}")
        print(f"  reservation_counts {'あり' if info['has_counts'] else 'なし — 作成します'}")
        print(f"  reservations.schedule_id "
              f"{'あり' if info['res_has_schedule_id'] else 'なし — 追加します'}")

        if info["off_grid"]:
            print()
            print("   グリッドにない時刻がスロットにあります :")
            for value in info["off_grid"]:
                print(f"     {value}")
            print("   → app/core/time_grid.py の TIME_GRID を先に広げてください。")

        print("-" * 78)

        if not apply and not drop:
            print(" まだ何も変更していません。")
            print(" 移行するには --apply、その後の照合が済んだら --drop")
            print("=" * 78)
            return 0

        if apply:
            # 열린 트랜잭션이 있으면 DDL 이 메타데이터 락을 기다린다.
            db.commit()
            Base.metadata.create_all(bind=engine)   # 새 테이블(reservation_counts)
            added = add_grid_columns(db)            # 기존 테이블의 새 칼럼
            print(f" ① テーブル確認・グリッドカラム {added}個を追加", flush=True)

            schedules, cells, notes = fill_grid(db)
            db.commit()
            print(f" ② 開催回 {schedules}件 / 枠 {cells}個をグリッドにまとめました", flush=True)

            moved = repoint_reservations(db)
            print(f" ③ 予約 {moved}件を開催回に紐づけ直しました", flush=True)

            if notes:
                print("\n 確認が必要な項目")
                for line in notes:
                    print(f"   · {line}")

            print("-" * 78)
            print(" 移行しました。slots はまだ残っています — 照合後に --drop してください。")
            print("   python -m scripts.verify_capacity_grid")

        if drop:
            db.commit()
            drop_slots(db)
            print("-" * 78)
            print(" slots を削除しました。")

        print("=" * 78)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
