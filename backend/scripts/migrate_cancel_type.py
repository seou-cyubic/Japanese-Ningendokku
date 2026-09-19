"""reservations 에 cancel_type 열을 더한다.

취소를 事前キャンセル / 当日キャンセル 로 나눠 세기 위한 열이다.
이미 있으면 아무것도 하지 않는다. 여러 번 돌려도 안전하다.

    python -m scripts.migrate_cancel_type
"""
import scripts._console  # noqa: F401  (콘솔 인코딩 보정)

from sqlalchemy import text

from app.core.database import SessionLocal


def line(text_: str) -> None:
    print(text_)


def main() -> None:
    print("=" * 70)
    print(" 予約キャンセルの種類 (cancel_type) 列の追加")
    print("=" * 70)
    db = SessionLocal()
    try:
        exists = db.execute(text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() "
            "AND table_name = 'reservations' AND column_name = 'cancel_type'"
        )).scalar()

        if exists:
            line(" すでに cancel_type 列があります。何もしません。")
        else:
            db.execute(text(
                "ALTER TABLE reservations "
                "ADD COLUMN cancel_type VARCHAR(16) NOT NULL DEFAULT '' "
                "AFTER cancel_reason"
            ))
            db.commit()
            line(" cancel_type 列を追加しました。")

        counts = db.execute(text(
            "SELECT cancel_type, COUNT(*) FROM reservations "
            "WHERE status = 'CANCELLED' GROUP BY cancel_type"
        )).all()
        for value, count in counts:
            label = {"ADVANCE": "事前キャンセル", "SAME_DAY": "当日キャンセル"}.get(
                value, "（種類なし＝この区分より前の取り消し）"
            )
            line(f" {label}: {count}件")
    finally:
        db.close()


if __name__ == "__main__":
    main()
