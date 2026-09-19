"""데이터베이스 초기화 + 테스트 데이터 투입.

    python -m scripts.init_db          # 테이블 생성 + 시드 (기존 데이터 유지)
    python -m scripts.init_db --reset  # 테이블을 지우고 다시 만든다

스키마는 Alembic 마이그레이션(`backend/migrations`)으로 만든다.
DB 가 없으면 만들고, 이미 있으면 남은 리비전만 적용한다(`app/core/db_setup.py`).
처음 설치라면 회장 샘플까지 한 번에 넣는 `python -m scripts.setup_db` 가 편하다.
"""

import scripts._console  # noqa: F401  (콘솔 UTF-8 보정)
import sys
from datetime import date

from sqlalchemy import create_engine, select

from app.core import db_setup
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.core.seed_data import SEED_ADMINS
from app.core.text_utils import normalize_kana, normalize_name
from app.models.admin import AdminUser  # noqa: F401  (메타데이터 등록)
from app.models.exam_option import ExamOption  # noqa: F401
from app.models.hospital import (  # noqa: F401
    Hospital,
    HospitalSchedule,
    ReservationCount,
)
from app.models.mail import MailLog, MailTemplate  # noqa: F401
from app.models.reservation import (  # noqa: F401
    ContactHistory,
    Reservation,
    ReservationOption,
)
from app.models.target_person import TargetPerson  # noqa: F401
from app.services import mail_service

# ==========================================================================
# 테스트용 검진 대상자 명부
#
# · 성명은 일본어, 미들네임은 공란(외국인 전용 항목)
# · 건강보험증은 테스트 케이스이므로 전건 0000-ABCD-0000
# · 기준일 2026-08-05 시점에 전원 만 40~74세 범위 안에 든다
#
# ※ 예약 여부·예약번호는 이 표에 없다. 그것은 명부가 아니라 예약 테이블이
#    답할 일이다. 「이미 예약 있음」 상태를 만들려면 실제 예약을 넣어야 하며,
#    슬롯이 있어야 하므로 별도 스크립트에서 처리한다.
#        python -m scripts.seed_reservations
# ==========================================================================
SEED_PERSONS = [
    # (성, 이름, 성 후리가나, 이름 후리가나, 성별, 생년월일)
    ("田中", "太郎", "タナカ",   "タロウ",   "M", date(1970, 5, 12)),
    ("佐藤", "花子", "サトウ",   "ハナコ",   "F", date(1958, 11, 3)),
    ("鈴木", "一郎", "スズキ",   "イチロウ", "M", date(1965, 2, 20)),
    ("高橋", "美咲", "タカハシ", "ミサキ",   "F", date(1982, 7, 8)),
    ("伊藤", "健二", "イトウ",   "ケンジ",   "M", date(1953, 9, 30)),
    ("渡辺", "由美", "ワタナベ", "ユミ",     "F", date(1975, 12, 15)),
    # 경계값 — 만 74세 (1952-01-25)
    ("山本", "三郎", "ヤマモト", "サブロウ", "M", date(1952, 1, 25)),
    # 경계값 — 만 40세 (1986-04-02)
    ("中村", "恵子", "ナカムラ", "ケイコ",   "F", date(1986, 4, 2)),

    # ------------------------------------------------------------------
    # 동성동명(한자) · 동일 생년월일 · 동일 보험증이지만 읽는 법이 다른 별개의 두 사람.
    # 일본어에서는 같은 한자라도 읽는 법이 다르면 다른 이름이다.
    # 후리가나를 대조 키에 넣지 않으면 이 둘을 구별할 수 없어
    # 「예약 가능」과 「이미 예약 있음」이 뒤바뀌는 오식별이 발생한다.
    # ------------------------------------------------------------------
    ("中田", "健", "ナカタ", "ケン", "M", date(1968, 6, 15)),
    ("中田", "健", "ナカダ", "ケン", "M", date(1968, 6, 15)),
]

INSURER_NO = "0000"
INSURANCE_SYMBOL = "ABCD"
INSURANCE_NO = "0000"

# ==========================================================================
# 옵션 검사 마스터 (plan.md §9.7 / BR-13)
#
# 기본 검진에 부가하는 추가 검사다. 코스별 구성은 없고 연령·성별 타깃 조건만
# 가진다. 조건에 맞지 않으면 이용자 화면의 선택지에 아예 나타나지 않는다.
#
# 비용 항목은 두지 않는다. 비용은 당일 회장에서 결제하며,
# 결제 기능은 개발 범위에서 제외되어 있다(plan.md §4.2).
#
# ※ 아래 목록과 연령 구간은 일본의 일반적인 인간독(人間ドック) 옵션을 참고한
#    샘플 값이다. 운영하는 기관에 맞춰 관리 화면에서 고친다.
# ==========================================================================
SEED_EXAM_OPTIONS = [
    # (코드, 검사명, 설명, 주의 사항, 성별, 최소연령, 최대연령)
    ("OPT01", "胃内視鏡検査（胃カメラ）",
     "口または鼻から細い内視鏡を挿入し、食道・胃・十二指腸を直接観察します。",
     "検査前日の21時以降は絶食が必要です。", "ALL", 40, 74),

    ("OPT02", "大腸内視鏡検査（大腸カメラ）",
     "大腸全体を内視鏡で観察します。ポリープが見つかった場合は、その場で切除することがあります。",
     "前日の下剤の服用と絶食が必要です。検査時間が長いため、午前の予約をおすすめします。", "ALL", 40, 74),

    ("OPT03", "腹部超音波検査（エコー）",
     "肝臓・胆のう・膵臓・腎臓・脾臓を超音波で観察します。",
     "検査前4時間は絶食が必要です。", "ALL", 40, 74),

    ("OPT04", "胸部CT検査",
     "肺を断層撮影し、胸部X線では見つけにくい小さな病変を確認します。",
     "", "ALL", 50, 74),

    ("OPT05", "子宮頸がん検査（細胞診）",
     "子宮頸部の細胞を採取し、顕微鏡で確認します。",
     "生理期間中は受診いただけません。", "F", 40, 74),

    ("OPT06", "乳がん検査（マンモグラフィ）",
     "乳房をX線で撮影します。",
     "豊胸バッグが入っている方は、事前に受診会場へお問い合わせください。", "F", 40, 74),

    ("OPT07", "前立腺がん検査（PSA）",
     "血液中の前立腺特異抗原（PSA）の値を測定します。",
     "", "M", 50, 74),

    ("OPT08", "骨密度検査",
     "骨の密度を測定し、骨粗鬆症のリスクを確認します。",
     "", "ALL", 50, 74),

    ("OPT09", "頸動脈超音波検査",
     "首の動脈を超音波で観察し、動脈硬化の進行度を確認します。",
     "", "ALL", 40, 74),

    ("OPT10", "ピロリ菌検査",
     "胃がんのリスク因子であるヘリコバクター・ピロリ菌の感染の有無を血液で確認します。",
     "", "ALL", 40, 74),
]


def create_database() -> None:
    """DB 가 없으면 만든다."""
    created = db_setup.ensure_database()
    state = "新規作成" if created else "既存を使用"
    print(f"[1/3] データベース準備 完了 : {settings.DB_NAME} ({state})")


def create_tables(reset: bool) -> None:
    """스키마를 마이그레이션으로 최신화한다. `--reset` 이면 먼저 전부 지운다."""
    if reset:
        engine = create_engine(settings.database_url)
        try:
            with engine.begin() as conn:
                dropped = db_setup.drop_all_tables(conn)
        finally:
            engine.dispose()
        print(f"      既存テーブルを削除 (--reset) : {len(dropped)}件")

    summary = db_setup.migrate()
    if summary["adopted_legacy"]:
        print("      旧スキーマを取り込み : " + ", ".join(summary["adopted_legacy"]))
    print(
        "[2/3] スキーマ更新 完了      : "
        f"{summary['from_revision'] or '(空)'} → {summary['to_revision']}"
    )


def seed() -> None:
    db = SessionLocal()
    try:
        inserted = skipped = 0

        for last, first, last_kana, first_kana, gender, birth in SEED_PERSONS:
            last_kana_norm = normalize_kana(last_kana)
            first_kana_norm = normalize_kana(first_kana)

            # 후리가나까지 포함해야 동성동명·다른 읽기의 두 사람이 합쳐지지 않는다
            exists = None
            for candidate in db.execute(
                select(TargetPerson).where(TargetPerson.birth_date == birth)
            ).scalars():
                if (
                    normalize_name(candidate.last_name) == normalize_name(last)
                    and normalize_name(candidate.first_name) == normalize_name(first)
                    and candidate.last_name_kana == last_kana_norm
                    and candidate.first_name_kana == first_kana_norm
                ):
                    exists = candidate
                    break

            if exists:
                skipped += 1
                continue

            db.add(
                TargetPerson(
                    last_name=last,
                    first_name=first,
                    # 후리가나는 전각 가타카나로 정규화해 보관한다
                    last_name_kana=last_kana_norm,
                    first_name_kana=first_kana_norm,
                    # 외국인 전용 항목 → 전건 공란
                    middle_name="",
                    middle_name_kana="",
                    gender=gender,
                    birth_date=birth,
                    insurer_no=INSURER_NO,
                    insurance_symbol=INSURANCE_SYMBOL,
                    insurance_no=INSURANCE_NO,
                )
            )
            inserted += 1

        db.commit()
        print(f"[3/3] シードデータ投入 完了 : 新規 {inserted}件 / 既存 {skipped}件")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def seed_admins() -> None:
    """관리 화면 초기 계정. 이미 있으면 비밀번호를 件드리지 않는다."""
    db = SessionLocal()
    try:
        inserted = skipped = 0

        for login_id, password, name, email, role in SEED_ADMINS:
            exists = db.execute(
                select(AdminUser).where(AdminUser.login_id == login_id)
            ).scalar_one_or_none()

            if exists:
                skipped += 1
                continue

            db.add(
                AdminUser(
                    login_id=login_id,
                    password_hash=hash_password(password),
                    name=name,
                    email=email,
                    role=role,
                    is_active=True,
                )
            )
            inserted += 1

        db.commit()
        print(f"      管理者アカウント投入 完了 : 新規 {inserted}件 / 既存 {skipped}件")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def seed_mail_templates() -> None:
    """메일 템플릿 초기값. 관리 화면(A-40)에서 이후 편집한다."""
    db = SessionLocal()
    try:
        for key in mail_service.DEFAULT_TEMPLATES:
            mail_service.get_template(db, key)
        db.commit()
        print("      メール文面 準備完了 : 予約完了・リマインド")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def seed_exam_options() -> None:
    """옵션 검사 마스터를 투입한다. 코드가 이미 있으면 件너뛴다."""
    db = SessionLocal()
    try:
        inserted = skipped = 0

        for order, (code, name, desc, note, gender, age_min, age_max) in enumerate(
            SEED_EXAM_OPTIONS, start=1
        ):
            exists = db.execute(
                select(ExamOption).where(ExamOption.code == code)
            ).scalar_one_or_none()

            if exists:
                skipped += 1
                continue

            db.add(
                ExamOption(
                    code=code,
                    name=name,
                    description=desc,
                    note=note,
                    target_gender=gender,
                    target_age_min=age_min,
                    target_age_max=age_max,
                    is_active=True,
                    sort_order=order,
                )
            )
            inserted += 1

        db.commit()
        print(f"      オプション検査投入 完了  : 新規 {inserted}件 / 既存 {skipped}件")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> int:
    reset = "--reset" in sys.argv

    print("=" * 62)
    print(" 健康診断予約システム — DB 初期化")
    print(f" 接続先 : {settings.DB_USER}@{settings.DB_HOST}:{settings.DB_PORT}")
    print("=" * 62)

    try:
        create_database()
        create_tables(reset)
    except db_setup.DatabaseSetupError as exc:
        print(f"\n[中止] {exc}")
        return 1

    seed()
    seed_exam_options()
    seed_admins()
    seed_mail_templates()

    # 결과 확인
    db = SessionLocal()
    try:
        rows = db.execute(
            select(TargetPerson).order_by(TargetPerson.id)
        ).scalars().all()

        print("\n--- 登録された受診対象者 ---------------------------------------------")
        for p in rows:
            print(f"  [{p.id}] {p.last_name} {p.first_name}"
                  f"  ({p.last_name_kana} {p.first_name_kana})")
            print(f"       {p.gender} / {p.birth_date.isoformat()}"
                  f" / {p.insurance_card_no}")
        print("-" * 70)
        print(f"合計 {len(rows)}名")

        print("\n--- 管理画面アカウント (開発用パスワード) ----------------------------")
        for login_id, password, name, _email, role in SEED_ADMINS:
            print(f"  {login_id:<8} / {password:<12} {name} ({role})")
        print("-" * 70)
        print("  ⚠️ 本番投入前に必ずパスワードを変更すること\n")

        print("続けて次の順に実行してください。（まとめて行うなら python -m scripts.setup_db）")
        print("  python -m scripts.import_hospitals      ← 会場マスター Excel")
        print("  python -m scripts.import_postal_codes   ← 郵便番号 (住所検索)")
        print("  python -m scripts.seed_reservations     ← 予約テストデータ\n")
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
