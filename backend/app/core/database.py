"""데이터베이스 연결 및 세션 관리."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,   # 끊어진 커넥션 자동 감지
    pool_recycle=3600,    # MySQL wait_timeout 대비
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """전 모델의 공통 베이스."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI 의존성. 요청 단위로 세션을 열고 닫는다."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
