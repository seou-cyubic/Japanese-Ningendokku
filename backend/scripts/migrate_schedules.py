"""件최 회차 정규화 마이그레이션.

    python -m scripts.migrate_schedules            # 무엇이 바뀌는지만 본다
    python -m scripts.migrate_schedules --apply    # 실제로 옮긴다

무엇을 옮기는가
---------------
예전 스키마는 件최일을 `hospitals` 행에 두었다.

    hospitals(… event_date, booking_close_date, open_time, reception_end_time)
    slots(hospital_id, slot_date, …)

지금은 그 넷이 `hospital_schedules` 로 나갔고, 슬롯이 회차를 가리킨다.

    hospitals(…)
    hospital_schedules(hospital_id, event_date, booking_close_date, …)
    slots(schedule_id, hospital_id, slot_date, …)

이 스크립트는 기존 데이터를 그 모양으로 옮긴다.

    ① hospital_schedules 테이블을 만든다
    ② 회장마다 회차 1件을 만든다 (예전 event_date 로)
    ③ 슬롯 날짜 중 회차가 없는 날짜가 있으면 그 날짜의 회차도 만든다
    ④ slots.schedule_id 를 채운다
    ⑤ hospitals 에서 옮겨 간 4件 칼럼을 지운다

예약이 없는 件발 환경이라면 이 스크립트 대신

    python -m scripts.init_db --reset
    python -m scripts.import_hospitals --reset

쪽이 빠르고 확실하다. 이 스크립트는 **예약이 이미 들어 있는 DB** 를 위한 것이다.

되돌릴 수 없다
--------------
⑤ 에서 칼럼을 지운다. `--apply` 전에 덤프를 떠 두기를 권한다.

    mysqldump -u root -p kenshin_reservation > backup.sql
"""

import scripts._console  # noqa: F401  (콘솔 UTF-8 보정)
import sys

from sqlalchemy import text

from app.core.database import Base, SessionLocal, engine
from app.models.hospital import (  # noqa: F401
    Hospital,
    HospitalSchedule,
    ReservationCount,
)
from app.models.reservation import Reservation  # noqa: F401

LEGACY_COLUMNS = (
    "event_date",
    "booking_close_date",
    "open_time",
    "reception_end_time",
)


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


def plan(db) -> dict:
    """무엇이 얼마나 옮겨지는지 센다. DB 는 고치지 않는다."""
    hospital_columns = columns_of(db, "hospitals")
    legacy = [c for c in LEGACY_COLUMNS if c in hospital_columns]

    info: dict = {
        "legacy_columns": legacy,
        "has_schedule_table": table_exists(db, "hospital_schedules"),
        "slot_has_schedule_id": "schedule_id" in columns_of(db, "slots"),
    }

    info["hospitals"] = int(
        db.execute(text("SELECT COUNT(*) FROM hospitals")).scalar() or 0
    )
    info["slots"] = int(db.execute(text("SELECT COUNT(*) FROM slots")).scalar() or 0)

    if "event_date" in hospital_columns:
        info["with_event_date"] = int(
            db.execute(
                text("SELECT COUNT(*) FROM hospitals WHERE event_date IS NOT NULL")
            ).scalar()
            or 0
        )
    else:
        info["with_event_date"] = 0

    info["slot_dates"] = int(
        db.execute(
            text("SELECT COUNT(DISTINCT hospital_id, slot_date) FROM slots")
        ).scalar()
        or 0
    )
    return info


def migrate(db) -> None:
    # 세션이 이미 트랜잭션을 열어 두었으면 DDL 이 메타데이터 락을 기다린다.
    # `plan()` 의 SELECT 가 그 트랜잭션을 열어 놓은 상태라, 여기서 끊지
    # 않으면 아래 `CREATE TABLE`·`ALTER TABLE` 이 조용히 멈춘 채 돌아오지
    # 않는다. 화면에는 아무것도 안 뜨고 그저 멈춰 있는 것으로 보인다.
    db.commit()

    hospital_columns = columns_of(db, "hospitals")
    slot_columns = columns_of(db, "slots")
    db.commit()

    # --- ① 회차 테이블 ---------------------------------------------------
    # `create_all` 은 이미 있는 테이블은 건드리지 않는다.
    Base.metadata.create_all(bind=engine)
    print(" ① hospital_schedules テーブルの確認完了", flush=True)

    # --- ② 회장마다 예전 개최일로 회차 1건 --------------------------------
    if "event_date" in hospital_columns:
        created = db.execute(
            text(
                "INSERT INTO hospital_schedules "
                "  (hospital_id, event_date, booking_close_date, open_time, "
                "   reception_end_time, is_visible, sort_order, note, "
                "   created_at, updated_at) "
                "SELECT h.id, h.event_date, h.booking_close_date, h.open_time, "
                "       h.reception_end_time, 1, 0, '', NOW(), NOW() "
                "  FROM hospitals h "
                " WHERE h.event_date IS NOT NULL "
                "   AND NOT EXISTS ("
                "       SELECT 1 FROM hospital_schedules s "
                "        WHERE s.hospital_id = h.id AND s.event_date = h.event_date)"
            )
        ).rowcount
        print(f" ② 旧 開催日 → 開催回 {created}件を作成", flush=True)
    else:
        print(" ② hospitals.event_date はすでにありません — スキップします", flush=True)

    # --- ③ 회차가 없는 슬롯 날짜를 회차로 --------------------------------
    # 예전에도 슬롯은 회장×날짜였다. 개최일 칸에 없는 날짜에 슬롯이 있는
    # 경우(정원 관리에서 손으로 만든 날)를 잃지 않기 위한 단계다.
    orphan = db.execute(
        text(
            "INSERT INTO hospital_schedules "
            "  (hospital_id, event_date, booking_close_date, open_time, "
            "   reception_end_time, is_visible, sort_order, note, "
            "   created_at, updated_at) "
            "SELECT DISTINCT sl.hospital_id, sl.slot_date, NULL, NULL, NULL, "
            "       1, 0, 'スロットから復元', NOW(), NOW() "
            "  FROM slots sl "
            " WHERE NOT EXISTS ("
            "     SELECT 1 FROM hospital_schedules s "
            "      WHERE s.hospital_id = sl.hospital_id "
            "        AND s.event_date = sl.slot_date)"
        )
    ).rowcount
    print(f" ③ 開催回がなかったスロットの日付 → 開催回 {orphan}件を追加作成", flush=True)

    db.commit()

    # --- ④ slots.schedule_id -------------------------------------------
    if "schedule_id" not in slot_columns:
        # 먼저 NULL 허용으로 붙이고, 채운 뒤에 NOT NULL 로 조인다.
        # 처음부터 NOT NULL 로 만들면 기존 행이 0 으로 채워져 어느 회차에도
        # 속하지 않는 슬롯이 생긴다.
        db.execute(text("ALTER TABLE slots ADD COLUMN schedule_id INT NULL"))
        print(" ④ slots.schedule_id カラムを追加", flush=True)

    filled = db.execute(
        text(
            "UPDATE slots sl "
            "  JOIN hospital_schedules s "
            "    ON s.hospital_id = sl.hospital_id AND s.event_date = sl.slot_date "
            "   SET sl.schedule_id = s.id "
            " WHERE sl.schedule_id IS NULL OR sl.schedule_id <> s.id"
        )
    ).rowcount
    print(f" ④ slots.schedule_id を取り込み — {filled}件", flush=True)

    left = int(
        db.execute(
            text("SELECT COUNT(*) FROM slots WHERE schedule_id IS NULL")
        ).scalar()
        or 0
    )
    if left:
        raise SystemExit(
            f" 開催回が見つからないスロットが {left}件残っています。中断します。\n"
            " (hospital_id・slot_date がどの開催回とも一致しません)"
        )

    db.execute(text("ALTER TABLE slots MODIFY COLUMN schedule_id INT NOT NULL"))

    has_fk = db.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.KEY_COLUMN_USAGE "
            " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'slots' "
            "   AND COLUMN_NAME = 'schedule_id' "
            "   AND REFERENCED_TABLE_NAME = 'hospital_schedules'"
        )
    ).scalar()
    if not has_fk:
        db.execute(
            text(
                "ALTER TABLE slots ADD CONSTRAINT fk_slot_schedule "
                "FOREIGN KEY (schedule_id) REFERENCES hospital_schedules(id) "
                "ON DELETE CASCADE"
            )
        )
        print(" ④ slots.schedule_id 外部キーを追加", flush=True)

    # --- ⑤ 옮겨 간 칼럼 제거 ---------------------------------------------
    hospital_columns = columns_of(db, "hospitals")
    for column in LEGACY_COLUMNS:
        if column in hospital_columns:
            db.execute(text(f"ALTER TABLE hospitals DROP COLUMN {column}"))
            print(f" ⑤ hospitals.{column} を削除", flush=True)

    db.commit()


def main() -> int:
    apply = "--apply" in sys.argv[1:]

    db = SessionLocal()
    try:
        info = plan(db)

        print("=" * 78)
        print(" 開催回の正規化マイグレーション")
        print("=" * 78)
        print(f"  会場            {info['hospitals']}件")
        print(f"  スロット        {info['slots']}件")
        print(f"  会場×日付       {info['slot_dates']}組  ← 作成される開催回の上限")
        print(f"  開催日 のある会場 {info['with_event_date']}件")
        print()
        print(f"  hospital_schedules テーブル : "
              f"{'あり' if info['has_schedule_table'] else 'なし — 作成します'}")
        print(f"  slots.schedule_id         : "
              f"{'あり' if info['slot_has_schedule_id'] else 'なし — 追加します'}")
        print(f"  hospitals の旧カラム        : "
              f"{', '.join(info['legacy_columns']) or 'なし (整理済み)'}")
        print("-" * 78)

        if not apply:
            print(" まだ何も変更していません。")
            print(" 実際に移行するには --apply を付けて実行し直してください。")
            print(" 元に戻せないため、先にダンプを取得してください。")
            print("=" * 78)
            return 0

        migrate(db)

        after = int(
            db.execute(text("SELECT COUNT(*) FROM hospital_schedules")).scalar() or 0
        )
        print("-" * 78)
        print(f" 完了 — 開催回 {after}件")
        print("=" * 78)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
