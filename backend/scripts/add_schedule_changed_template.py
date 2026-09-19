"""검진일 변경 안내 메일 문구를 추가한다 (마이그레이션).

    python -m scripts.add_schedule_changed_template

`mail_templates.template_key` 는 DB 의 ENUM 이라, 코드에 값을 늘리는 것만으로는
저장되지 않는다. 컬럼을 먼저 넓히고 행을 넣어야 한다.

이미 적용된 DB 에 다시 돌려도 안전하다. 컬럼은 같은 정의로 다시 쓰고,
행은 있으면 건드리지 않는다. 담당자가 화면에서 고친 문구를 되돌리면
안 되기 때문이다.
"""

import scripts._console  # noqa: F401  (콘솔 UTF-8 보정)
import sys

from sqlalchemy import text

from app.core.database import SessionLocal
from app.models.mail import TEMPLATE_KEYS, TEMPLATE_LABELS, MailTemplate
from app.services import mail_service


def main() -> int:
    db = SessionLocal()
    try:
        values = ",".join(f"'{k}'" for k in TEMPLATE_KEYS)

        print("=" * 60)
        print(" 受診日変更のお知らせメール文面を追加")
        print("=" * 60)

        current = db.execute(
            text("SHOW COLUMNS FROM mail_templates LIKE 'template_key'")
        ).one()[1]
        print(f" 現在のカラム : {current}")

        db.execute(text(
            f"ALTER TABLE mail_templates "
            f"MODIFY COLUMN template_key ENUM({values}) NOT NULL"
        ))
        print(f" 新しいカラム : enum({values})")

        added = kept = 0
        for key in TEMPLATE_KEYS:
            exists = db.execute(
                text("SELECT COUNT(*) FROM mail_templates WHERE template_key = :k"),
                {"k": key},
            ).scalar()

            if exists:
                kept += 1
                print(f"   [そのまま] {key:<18} {TEMPLATE_LABELS.get(key, '')}")
                continue

            default = mail_service.DEFAULT_TEMPLATES.get(key)
            if default is None:
                print(f"   [スキップ] {key:<18} 既定の文面がありません")
                continue

            db.add(MailTemplate(
                template_key=key,
                subject=default["subject"],
                body=default["body"],
                updated_by="システム (初期値)",
            ))
            added += 1
            print(f"   [追加]   {key:<18} {TEMPLATE_LABELS.get(key, '')}")

        db.commit()
        print("-" * 60)
        print(f" 追加 {added}件 / そのまま {kept}件")
        print(" 管理画面 → メール文面 から確認できます。")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
