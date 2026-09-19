"""조작 로그에 `batch_id` 칼럼 추가.

    python -m scripts.migrate_audit_batch            # 무엇이 바뀌는지만 본다
    python -m scripts.migrate_audit_batch --apply    # 실제로 추가한다

왜 필요한가
-----------
표에서 「저장」을 한 번 누르면 회장 21곳이 각각 로그 한 줄을 남긴다.
목록에서는 21줄이 그냥 나란히 보일 뿐이라, **어디부터 어디까지가 한 번의
조작이었는지** 알 수 없었다. 「아까 그 저장을 되돌리고 싶다」에 답하려면
그 경계가 있어야 한다.

이 칼럼이 그 경계다. 일괄 저장은 시작할 때 열쇠를 하나 만들어 그 저장에서
나오는 모든 로그에 같은 값을 준다.

이미 쌓인 로그는 어떻게 되는가
------------------------------
빈 문자열로 남는다. **되돌릴 수 없다** — 어느 로그가 한 덩어리였는지
지금 와서는 알 수 없기 때문이다. 시각으로 추측해 묶는 방법도 있지만,
잘못 묶으면 남의 조작까지 되돌린다. 되돌리기는 이 마이그레이션 뒤에
저장한 것부터 쓸 수 있다.
"""

import scripts._console  # noqa: F401  (콘솔 UTF-8 보정)

import argparse
import sys

from sqlalchemy import text

from app.core.database import SessionLocal

COLUMN_SQL = (
    "ALTER TABLE audit_logs "
    "ADD COLUMN batch_id VARCHAR(40) NOT NULL DEFAULT '' "
    "COMMENT '한 번의 일괄 저장을 묶는 열쇠' AFTER after_json"
)
INDEX_SQL = "CREATE INDEX ix_audit_batch ON audit_logs (batch_id)"


def has_column(db, table: str, column: str) -> bool:
    return db.execute(
        text(
            "SELECT 1 FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = :t AND COLUMN_NAME = :c"
        ),
        {"t": table, "c": column},
    ).first() is not None


def has_index(db, table: str, index: str) -> bool:
    return db.execute(
        text(
            "SELECT 1 FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = :t AND INDEX_NAME = :i"
        ),
        {"t": table, "i": index},
    ).first() is not None


def main() -> int:
    parser = argparse.ArgumentParser(description="操作ログに batch_id カラムを追加する")
    parser.add_argument("--apply", action="store_true", help="実際に反映する")
    args = parser.parse_args()

    print("=" * 70)
    print(" 操作ログ batch_id マイグレーション")
    print("=" * 70)

    db = SessionLocal()
    try:
        column_ok = has_column(db, "audit_logs", "batch_id")
        index_ok = column_ok and has_index(db, "audit_logs", "ix_audit_batch")

        if column_ok:
            print("  カラム : すでにあります。")
        elif args.apply:
            db.execute(text(COLUMN_SQL))
            db.commit()
            print("  カラム : audit_logs.batch_id を作成しました。")
        else:
            print("  カラム : ありません。--apply を付けると作成します。")
            print(f"         {COLUMN_SQL}")

        if index_ok:
            print("  インデックス : すでにあります。")
        elif args.apply:
            db.execute(text(INDEX_SQL))
            db.commit()
            print("  インデックス : ix_audit_batch を作成しました。")
        else:
            print("  インデックス : ありません。--apply を付けると作成します。")
            print(f"         {INDEX_SQL}")

        if args.apply:
            total = db.execute(text("SELECT COUNT(*) FROM audit_logs")).scalar() or 0
            print("-" * 70)
            print(f"  既存のログ {total:,}件は batch_id が空です。")
            print("  元に戻す操作は、これ以降に保存したものにしか使えません —")
            print("  どのログが 1 つのまとまりだったのか、今からでは分からないためです。")
        else:
            print()
            print("  ※ まだ反映していません。--apply を付けて実行し直してください。")

        print("=" * 70)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
