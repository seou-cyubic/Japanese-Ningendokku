"""일본우편 우편번호 데이터(KEN_ALL)를 MySQL 로 적재한다.

    python -m scripts.import_postal_codes            # 내려받아 적재 (이미 있으면 件너뜀)
    python -m scripts.import_postal_codes --reset    # 전부 지우고 다시 적재
    python -m scripts.import_postal_codes --file utf_ken_all.csv   # 받아 둔 파일로 적재

데이터는 일본우편이 매월 갱신한다. 주소가 새로 생기거나 없어지므로
**반년에 한 번 정도는 다시 돌려 두는 것이 좋다.** 다시 돌려도 결과는 같다(멱등).

적재 로직 자체는 `app/services/postal_import_service.py` 에 있다
------------------------------------------------------------------
같은 일을 서버도 한다(기동 시 자동 적재). 두 곳에 적어 두면 한쪽만 고치게
되고, 특히 「무엇을 적재됨으로 볼 것인가」라는 판정이 갈린다.
이 파일은 그 서비스를 부르고 사람이 읽을 출력을 내는 껍데기다.

원본 형식과 「사람이 읽으라고 넣은 말」의 처리는 서비스 쪽 주석에 있다.
"""

import scripts._console  # noqa: F401  (콘솔 UTF-8 보정)

import argparse
import sys
from pathlib import Path

from app.core.database import SessionLocal
from app.core.config import settings
from app.services import postal_import_service as importer
from app.services.postal_import_service import PostalImportError

# 예전 이름으로 부르던 곳이 있어 남겨 둔다.
KEN_ALL_URL = importer.KEN_ALL_URL


def main() -> int:
    parser = argparse.ArgumentParser(description="日本郵便の郵便番号データを取り込む")
    parser.add_argument("--reset", action="store_true", help="既存データを削除して取り込み直す")
    parser.add_argument("--file", type=Path, default=None, help="ダウンロード済み CSV ファイルのパス")
    args = parser.parse_args()

    print("=" * 70)
    print(" 郵便番号データ取り込み (日本郵便 KEN_ALL)")
    print("=" * 70)

    importer.ensure_table()

    db = SessionLocal()
    try:
        existing = importer.count(db)

        if existing and not args.reset:
            print(f"  すでに {existing:,}件あります。取り込み直すには --reset を付けてください。")
            return 0

        def log(message: str) -> None:
            print(f"  {message}")

        def progress(done: int, total: int) -> None:
            print(f"\r  取り込み中 : {done:,} / {total:,}", end="", flush=True)
            if done >= total:
                print()

        try:
            result = importer.load(
                db,
                reset=True,
                source=args.file,
                log=log,
                progress=progress,
            )
        except PostalImportError as exc:
            print("-" * 70)
            print(f"  取り込めませんでした : {exc}")
            print("=" * 70)
            return 1

        if result.skipped:
            print(f"  スキップしました : {'; '.join(result.warnings) or '取り込み済み'}")
            return 0

        print("-" * 70)
        if result.deleted:
            print(f"  既存 {result.deleted:,}件を削除 (--reset)")
        print(f"  取り込み完了 : {result.total:,}件")

        sample = importer.sample(db, "1010021")
        if sample:
            print(f"  確認 : {sample.zipcode} → {sample.full_address}")

        if result.total < settings.POSTAL_MIN_ROWS:
            print(
                f"  ※ 基準({settings.POSTAL_MIN_ROWS:,}件)より少ないです。"
                "サーバーはこのデータを「不完全」とみなします。"
            )

        print("=" * 70)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
