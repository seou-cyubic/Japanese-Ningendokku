"""Alembic 실행 환경.

접속 정보는 `app.core.config.settings` 에서 읽는다. `alembic.ini` 에 URL 을
적지 않는 이유는 비밀번호가 저장소에 들어가지 않게 하기 위해서다.

`app.core.db_setup` 이 프로그램에서 부를 때는 이미 연 커넥션을
`config.attributes["connection"]` 으로 넘긴다. 그 커넥션이 MySQL 잠금
(`GET_LOCK`)을 쥐고 있으므로, 같은 커넥션 위에서 돌아야 잠금이 의미가 있다.
"""

from alembic import context
from sqlalchemy import create_engine, pool

import app.models  # noqa: F401  (전 모델을 메타데이터에 등록)
from app.core.config import settings
from app.core.database import Base

config = context.config
target_metadata = Base.metadata


def _configure(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=False,
    )


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _configure(connection)
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = create_engine(settings.database_url, poolclass=pool.NullPool)
    with engine.connect() as conn:
        _configure(conn)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
