"""처음 설치 — 한 번에 쓸 수 있는 상태까지.

    python -m scripts.setup_db                      # DB · 스키마 · 초기 데이터 · 샘플 회장
    python -m scripts.setup_db --with-reservations  # + 예약 테스트 데이터 50여 건
    python -m scripts.setup_db --no-sample          # 스키마 + 필수 데이터(계정 · 메일 문구)만
    python -m scripts.setup_db --reset              # DB 안의 테이블을 전부 지우고 처음부터
    python -m scripts.setup_db --check              # 아무것도 바꾸지 않고 상태만 본다

몇 번을 돌려도 같은 결과다. 이미 있는 행은 건드리지 않는다.

    1. DB 생성          없으면 만든다 (utf8mb4)
    2. 스키마           Alembic 마이그레이션을 head 까지 (`backend/migrations`)
    3. 초기 데이터      관리자 계정 · 메일 문구 · 옵션 검사 · 검진 대상자 명부(10명)
    4. 샘플 회장        **회장이 하나도 없을 때만** `data/hospitals/sample_venue_master.xlsx`
                        날짜는 오늘 기준으로 앞으로 민다 — 지난 날짜로 넣으면
                        이용자 화면에 회장이 하나도 보이지 않는다
    5. 회장 후리가나    비어 있는 칸만 채운다
    6. (선택) 예약 테스트 데이터

우편번호(주소 찾기) 데이터는 서버가 뜰 때 비어 있으면 백그라운드로 받는다.
인터넷이 없는 환경이면 `python -m scripts.import_postal_codes --file <경로>`.
"""

import scripts._console  # noqa: F401  (콘솔 UTF-8 보정)

import argparse
import sys

from sqlalchemy import create_engine, func, pool, select

from app.core import db_setup
from app.core.config import PROJECT_DIR, settings
from app.core.database import SessionLocal

SAMPLE_SHEET = PROJECT_DIR / "data" / "hospitals" / "sample_venue_master.xlsx"


def _line(char: str = "=") -> None:
    print(char * 70)


def check() -> int:
    """바꾸지 않고 본다. 최신이면 0, 할 일이 있으면 1."""
    head = db_setup.head_revision()
    engine = create_engine(settings.database_url, poolclass=pool.NullPool)
    try:
        with engine.connect() as conn:
            current = db_setup.current_revision(conn)
            drift = db_setup.schema_drift(conn) if current == head else []
    except Exception as exc:  # noqa: BLE001 — 접속 실패도 「상태」로 보여 준다
        print(f"  接続できません : {exc.__class__.__name__}: {exc}")
        return 1
    finally:
        engine.dispose()

    print(f"  リビジョン : {current or '(未適用)'} / 最新 {head}")
    if drift:
        print("  モデルとの差分 :")
        for item in drift:
            print(f"    · {item}")
    ok = current == head and not drift
    print("  → 最新です" if ok else "  → python -m scripts.setup_db を実行してください")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="データベースの初期セットアップ")
    parser.add_argument("--reset", action="store_true", help="テーブルを全て削除して作り直す")
    parser.add_argument("--no-sample", action="store_true", help="サンプル会場・対象者名簿を入れない")
    parser.add_argument("--with-reservations", action="store_true", help="予約テストデータも入れる")
    parser.add_argument("--check", action="store_true", help="状態の確認のみ")
    args = parser.parse_args(argv)

    _line()
    print(" 健康診断予約システム — セットアップ")
    print(f" 接続先 : {settings.DB_USER}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}")
    _line()

    if args.check:
        return check()

    # 1 · 2 --------------------------------------------------------------
    try:
        if args.reset:
            db_setup.ensure_database()
            engine = create_engine(settings.database_url, poolclass=pool.NullPool)
            try:
                with engine.begin() as conn:
                    dropped = db_setup.drop_all_tables(conn)
            finally:
                engine.dispose()
            print(f" [reset] テーブル {len(dropped)}件を削除しました")

        summary = db_setup.migrate()
    except db_setup.DatabaseSetupError as exc:
        print(f"\n[中止] {exc}")
        return 1

    print(f" [1] データベース : {'新規作成' if summary['database_created'] else '既存'}")
    if summary["adopted_legacy"]:
        print(" [2] 旧スキーマ取り込み : " + ", ".join(summary["adopted_legacy"]))
    print(
        f" [2] スキーマ       : {summary['from_revision'] or '(空)'}"
        f" → {summary['to_revision']}"
    )

    # 3 ------------------------------------------------------------------
    # init_db 의 시드 함수를 그대로 쓴다. 같은 값을 두 곳에 적지 않기 위함이다.
    from scripts import init_db

    if not args.no_sample:
        init_db.seed()
    init_db.seed_exam_options()
    init_db.seed_admins()
    init_db.seed_mail_templates()

    # 4 · 5 --------------------------------------------------------------
    if not args.no_sample:
        from app.models.hospital import Hospital
        from scripts import import_hospitals, migrate_hospital_kana

        db = SessionLocal()
        try:
            venue_count = db.execute(select(func.count(Hospital.id))).scalar() or 0
        finally:
            db.close()

        if venue_count:
            print(f" [4] 会場 : 既に {venue_count}件あるため取り込みません")
        elif not SAMPLE_SHEET.exists():
            print(f" [4] 会場 : サンプルファイルがありません ({SAMPLE_SHEET})")
        else:
            _line("-")
            code = import_hospitals.main(["--file", str(SAMPLE_SHEET), "--shift-to-future"])
            if code:
                return code

        _line("-")
        migrate_hospital_kana.main(["--apply"])

    # 6 ------------------------------------------------------------------
    if args.with_reservations and not args.no_sample:
        from scripts import seed_reservations

        _line("-")
        seed_reservations.main([])

    _line()
    print(" セットアップ完了。サーバーを起動してください。")
    print("   python -m uvicorn app.main:app --reload")
    print("   利用者画面 : /        管理画面 : /admin/  (admin / admin1234)")
    _line()
    return 0


if __name__ == "__main__":
    sys.exit(main())
