"""데이터베이스 준비 — 생성 · 마이그레이션 · 초기 데이터.

처음 받은 저장소에서 서버를 띄우든, 몇 달 쓴 DB 에 새 코드를 올리든
**같은 한 경로**로 스키마를 최신으로 맞춘다.

    prepare_database()        DB 생성 → 스키마 최신화 → 필수 초기 데이터
    migrate()                 DB 생성 → 스키마 최신화
    drop_all_tables()         DB 안의 테이블을 전부 지운다 (--reset 전용)

어디서 불리는가
---------------
  · `app/main.py` 기동 시 (`DB_AUTO_MIGRATE=true`, 기본값)
  · `python -m scripts.setup_db` / `python -m scripts.init_db`
  · `python -m scripts.import_hospitals`

DB 가 어떤 상태든 받아들인다
----------------------------
    DB 자체가 없다                → 만든다 (utf8mb4)
    DB 는 있고 테이블이 없다        → 0001 부터 전부 만든다
    `alembic_version` 이 있다       → 남은 리비전만 적용한다
    테이블은 있는데 `alembic_version` 이 없다
        (Alembic 도입 전 `create_all` 로 만든 DB)
                                → 모자란 칼럼·인덱스·테이블을 채우고 0001 로 도장
                                  을 찍은 뒤 이어서 적용한다
        · `slots` 테이블이 남은 **아주 옛 구조**면 데이터 이행이 필요하므로
          멈추고 이행 스크립트를 안내한다 (자동으로 데이터를 옮기지 않는다)

동시에 여러 프로세스가 올라와도 안전하다
----------------------------------------
워커를 여러 개 띄우면 각자 마이그레이션을 시도한다. MySQL 의 이름 잠금
(`GET_LOCK`)으로 한 번에 하나만 돌게 하고, 뒤에 온 프로세스는 앞의 것이
끝난 뒤 「이미 최신」을 확인하고 지나간다.
"""

from __future__ import annotations

import logging

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Enum, create_engine, inspect, pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError

import app.models  # noqa: F401  (전 모델을 메타데이터에 등록)
from app.core.config import BACKEND_DIR, settings
from app.core.database import Base

logger = logging.getLogger("kenshin.db")

ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
MIGRATIONS_DIR = BACKEND_DIR / "migrations"

# Alembic 도입 전 DB 를 받아들일 때 찍는 리비전. 그 시점의 모델과 같은 모양이다.
BASELINE_REVISION = "0001"

LOCK_NAME = "kenshin_schema_migration"
LOCK_TIMEOUT_SECONDS = 300

DB_CHARSET = "utf8mb4"
DB_COLLATION = "utf8mb4_general_ci"

# MySQL 오류 번호
_ER_BAD_DB = 1049          # Unknown database


class DatabaseSetupError(RuntimeError):
    """사람이 손을 써야 하는 상태. 메시지에 무엇을 할지 적는다."""


# ==========================================================================
# 데이터베이스
# ==========================================================================


def _validate_db_name(name: str) -> str:
    # 백틱으로 감싸 DDL 에 넣으므로, 백틱이 섞이면 문장이 깨지거나 주입이 된다.
    if not name or "`" in name or len(name) > 64:
        raise DatabaseSetupError(
            f"DB_NAME の値が不正です: {name!r}（1～64文字、` は使用不可）"
        )
    return name


def ensure_database() -> bool:
    """DB 가 없으면 만든다. 만들었으면 True.

    `CREATE DATABASE IF NOT EXISTS` 부터 치지 않고 **접속부터 해 본다.**
    운영 DB 계정에는 CREATE 권한이 없는 것이 보통이라, 이미 있는 DB 에
    CREATE 를 치면 권한 오류로 기동이 멈춘다.
    """
    name = _validate_db_name(settings.DB_NAME)

    engine = create_engine(settings.database_url, poolclass=pool.NullPool)
    try:
        with engine.connect():
            return False
    except OperationalError as exc:
        code = exc.orig.args[0] if exc.orig and exc.orig.args else None
        if code != _ER_BAD_DB:
            raise
    finally:
        engine.dispose()

    server = create_engine(
        settings.server_url, poolclass=pool.NullPool, isolation_level="AUTOCOMMIT"
    )
    try:
        with server.connect() as conn:
            conn.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{name}` "
                    f"CHARACTER SET {DB_CHARSET} COLLATE {DB_COLLATION}"
                )
            )
    finally:
        server.dispose()

    logger.info("データベースを作成しました: %s", name)
    return True


def drop_all_tables(conn: Connection) -> list[str]:
    """DB 안의 테이블을 **전부** 지운다. 모델에 없는 옛 테이블(`slots`)과
    `alembic_version` 까지 지워야 다시 0001 부터 깨끗하게 만들 수 있다."""
    tables = inspect(conn).get_table_names()
    conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
    try:
        for table in tables:
            conn.execute(text(f"DROP TABLE IF EXISTS `{table}`"))
    finally:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    return tables


# ==========================================================================
# Alembic
# ==========================================================================


def alembic_config(connection: Connection | None = None) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    # alembic.ini 의 `%(here)s` 에 기대지 않고 절대 경로를 준다.
    # 어느 디렉터리에서 실행하든 같은 마이그레이션을 찾게 하기 위함이다.
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    # 프로그램에서 부를 때 alembic.ini 의 로깅 설정이 앱 로깅을 덮지 않게 한다.
    cfg.attributes["configure_logger"] = False
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


def head_revision() -> str | None:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(conn: Connection) -> str | None:
    return MigrationContext.configure(conn).get_current_revision()


class _MigrationLock:
    """MySQL 이름 잠금. 커넥션(세션)에 붙으므로 같은 커넥션으로 풀어야 한다."""

    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def __enter__(self) -> "_MigrationLock":
        got = self.conn.execute(
            text("SELECT GET_LOCK(:name, :timeout)"),
            {"name": _lock_key(), "timeout": LOCK_TIMEOUT_SECONDS},
        ).scalar()
        if got != 1:
            raise DatabaseSetupError(
                "別のプロセスがスキーマを更新中のため、"
                f"{LOCK_TIMEOUT_SECONDS}秒待っても完了しませんでした。"
            )
        return self

    def __exit__(self, *_exc) -> None:
        try:
            self.conn.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": _lock_key()})
        except Exception:  # noqa: BLE001 — 커넥션이 끊기면 잠금도 함께 풀린다
            pass


def _lock_key() -> str:
    # 같은 서버에 DB 를 여러 개 두는 개발 환경에서 서로를 기다리지 않게 DB 이름을 붙인다.
    return f"{LOCK_NAME}:{settings.DB_NAME}"[:64]


def migrate(*, seed: bool = False, seed_admins: bool = True) -> dict:
    """DB 를 만들고 스키마를 head 까지 올린다. 무엇을 했는지 돌려준다.

    `seed=True` 면 필수 초기 데이터도 **같은 잠금 안에서** 넣는다. 잠금 밖에서
    넣으면 동시에 뜬 워커들이 같은 메일 문구를 함께 INSERT 해 UNIQUE 위반이 난다.
    """
    created = ensure_database()

    engine = create_engine(settings.database_url, poolclass=pool.NullPool)
    try:
        with engine.connect() as conn:
            with _MigrationLock(conn):
                before = current_revision(conn)
                adopted: list[str] = []
                if before is None and _has_app_tables(conn):
                    adopted = adopt_legacy_schema(conn)

                head = head_revision()
                if current_revision(conn) != head:
                    command.upgrade(alembic_config(conn), "head")
                    conn.commit()
                after = current_revision(conn)

                seeded = seed_required(admins=seed_admins) if seed else None
    finally:
        engine.dispose()

    if before != after:
        logger.info("スキーマを更新しました: %s → %s", before or "(空)", after)

    summary = {
        "database_created": created,
        "adopted_legacy": adopted,
        "from_revision": before,
        "to_revision": after,
    }
    if seeded is not None:
        summary["seeded"] = seeded
    return summary


# ==========================================================================
# Alembic 도입 전 DB 받아들이기
# ==========================================================================


def _app_table_names() -> set[str]:
    return set(Base.metadata.tables)


def _has_app_tables(conn: Connection) -> bool:
    return bool(set(inspect(conn).get_table_names()) & _app_table_names())


def adopt_legacy_schema(conn: Connection) -> list[str]:
    """`create_all` 시절의 DB 를 0001 모양으로 맞추고 도장을 찍는다.

    **더하기만 한다.** 칼럼·인덱스·테이블을 지우거나 타입을 좁히지 않는다.
    데이터를 잃을 수 있는 변경은 자동으로 하지 않는다는 원칙이다.
    """
    insp = inspect(conn)
    tables = set(insp.get_table_names())

    # --- 데이터 이행이 필요한 옛 구조는 멈춘다 -----------------------------
    legacy_markers = []
    if "slots" in tables:
        legacy_markers.append("slots テーブル")
    if "hospitals" in tables:
        hospital_cols = {c["name"] for c in insp.get_columns("hospitals")}
        if "event_date" in hospital_cols:
            legacy_markers.append("hospitals.event_date カラム")
    if "reservations" in tables:
        res_cols = {c["name"] for c in insp.get_columns("reservations")}
        if "slot_id" in res_cols or "schedule_id" not in res_cols:
            legacy_markers.append("reservations.slot_id カラム")
    if legacy_markers:
        raise DatabaseSetupError(
            "旧形式のスキーマ（" + "・".join(legacy_markers) + "）が残っています。"
            "データの移行が必要なため自動では更新しません。\n"
            "  予約データが不要なら : python -m scripts.setup_db --reset\n"
            "  データを残すなら     : README §6 の手順"
            "（migrate_schedules → migrate_capacity_grid）を先に実行してください。"
        )

    ops = Operations(MigrationContext.configure(conn))
    changes: list[str] = []

    # --- 없는 테이블 ------------------------------------------------------
    missing_tables = [
        t for t in Base.metadata.sorted_tables if t.name not in tables
    ]
    if missing_tables:
        Base.metadata.create_all(conn, tables=missing_tables)
        changes += [f"+table {t.name}" for t in missing_tables]

    # --- 없는 칼럼 · 넓어진 ENUM · 없는 인덱스 ----------------------------
    for table in Base.metadata.sorted_tables:
        if table.name not in tables:
            continue

        existing = {c["name"]: c for c in insp.get_columns(table.name)}
        for column in table.columns:
            if column.name not in existing:
                # 키 칼럼은 기존 행에 넣을 값을 정할 수 없다 — 사람이 판단할 일이다.
                if column.primary_key or (column.foreign_keys and not column.nullable):
                    raise DatabaseSetupError(
                        f"{table.name}.{column.name} がありません。"
                        "キー列のため自動では追加できません。"
                    )
                ops.add_column(table.name, column._copy())
                changes.append(f"+column {table.name}.{column.name}")
                continue

            if isinstance(column.type, Enum):
                current = existing[column.name]["type"]
                have = set(getattr(current, "enums", []) or [])
                want = set(column.type.enums)
                if not want <= have:
                    # 옛 값은 남긴다(지우면 그 값을 가진 행이 깨진다).
                    merged = list(column.type.enums) + sorted(have - want)
                    ops.alter_column(
                        table.name,
                        column.name,
                        type_=Enum(*merged, name=column.type.name),
                        existing_nullable=column.nullable,
                        nullable=column.nullable,
                    )
                    changes.append(f"~enum {table.name}.{column.name}")

        index_names = {i["name"] for i in insp.get_indexes(table.name)}
        for index in table.indexes:
            if index.name not in index_names:
                ops.create_index(
                    index.name,
                    table.name,
                    [c.name for c in index.columns],
                    unique=bool(index.unique),
                )
                changes.append(f"+index {table.name}.{index.name}")

    command.stamp(alembic_config(conn), BASELINE_REVISION)
    conn.commit()

    logger.info(
        "Alembic 導入前のスキーマを取り込みました (%s)",
        ", ".join(changes) if changes else "変更なし",
    )
    return changes


# ==========================================================================
# 초기 데이터
# ==========================================================================


def seed_required(*, admins: bool = True) -> dict:
    """앱이 동작하는 데 **반드시 있어야 하는** 행만 넣는다.

      · 메일 문구 — 없으면 메일 관리 화면과 발송이 빈 문구로 돈다
      · 관리자 계정 — 테이블이 **비어 있을 때만.** 없으면 아무도 로그인하지 못한다

    이미 있는 행은 건드리지 않는다. 담당자가 고친 문구·비밀번호를 되돌리면 안 된다.
    검진 대상자 명부·옵션 검사·회장은 넣지 않는다 — 운영 데이터라 설치 스크립트
    (`scripts.setup_db`)가 명시적으로 넣는다.
    """
    from sqlalchemy import func, select

    from app.core.database import SessionLocal
    from app.core.security import hash_password
    from app.core.seed_data import SEED_ADMINS
    from app.models.admin import AdminUser
    from app.services import mail_service

    result = {"mail_templates": 0, "admins": 0}
    db = SessionLocal()
    try:
        from app.models.mail import MailTemplate

        have = set(db.execute(select(MailTemplate.template_key)).scalars())
        for key in mail_service.DEFAULT_TEMPLATES:
            if key not in have:
                mail_service.get_template(db, key)
                result["mail_templates"] += 1

        if admins and not db.execute(select(func.count(AdminUser.id))).scalar():
            for login_id, password, name, email, role in SEED_ADMINS:
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
                result["admins"] += 1

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return result


def prepare_database(*, seed_admins: bool = True) -> dict:
    """기동 시 한 번. DB 생성 → 스키마 최신화 → 필수 초기 데이터."""
    return migrate(seed=True, seed_admins=seed_admins)


def schema_drift(conn: Connection) -> list[str]:
    """모델과 실제 스키마의 차이(칼럼·테이블·인덱스). 주석 차이는 무시한다."""
    from alembic.autogenerate import compare_metadata

    ctx = MigrationContext.configure(conn, opts={"compare_type": True})
    diffs: list[str] = []
    for diff in compare_metadata(ctx, Base.metadata):
        items = diff if isinstance(diff, list) else [diff]
        for item in items:
            kind = item[0]
            if kind in ("add_table_comment", "remove_table_comment", "modify_comment"):
                continue
            if kind == "remove_table" and item[1].name == "alembic_version":
                continue
            diffs.append(_describe_diff(item))
    return diffs


def _describe_diff(item) -> str:
    kind = item[0]
    if kind in ("add_table", "remove_table"):
        return f"{kind} {item[1].name}"
    if kind in ("add_column", "remove_column"):
        return f"{kind} {item[2]}.{item[3].name}"
    if kind in ("add_index", "remove_index"):
        return f"{kind} {item[1].table.name}.{item[1].name}"
    if kind.startswith("modify_"):
        return f"{kind} {item[2]}.{item[3]}"
    return str(kind)


__all__ = [
    "BASELINE_REVISION",
    "DatabaseSetupError",
    "adopt_legacy_schema",
    "alembic_config",
    "current_revision",
    "drop_all_tables",
    "ensure_database",
    "head_revision",
    "migrate",
    "prepare_database",
    "schema_drift",
    "seed_required",
]
