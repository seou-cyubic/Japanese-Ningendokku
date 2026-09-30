"""이용자 화면 입장 계정 · 세션.

이용자 화면(첫 화면 · 예약 · 조회 · FAQ)은 처음 들어올 때 로그인을 거친다.
관리 화면 계정(`admin_users`)과는 **따로 둔다.** 이 계정으로는 관리 API 를
하나도 부를 수 없어야 하고, 관리자 계정 목록·권한 체계와 섞이면 그 경계가
흐려진다.

비밀번호는 관리자와 같이 bcrypt 해시만 남긴다. 평문은 어디에도 두지 않는다.

세션은 서버(DB)에 둔다
----------------------
처음에는 관리 화면처럼 서명 쿠키만 썼다. 그러면 로그인 여부가 쿠키 안에만
있어 **서버를 껐다 켜도 로그인이 그대로 살아 있었고**, 로그아웃이나 비밀번호
변경으로도 이미 나간 쿠키를 거둘 수 없었다. 그래서 세션을 `site_sessions`
표에 두고, 쿠키에는 무작위 토큰만 담는다.

  · 서버가 뜰 때 표를 비운다 → 재기동하면 모두 다시 로그인한다
  · 로그아웃 · 비밀번호 변경 · 계정 정지 → 그 계정의 세션 행을 지운다

토큰 원문은 DB 에 두지 않고 SHA-256 해시만 둔다. DB 가 새어도 그 값으로는
쿠키를 만들 수 없다.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SiteUser(Base):
    """이용자 화면 로그인 계정."""

    __tablename__ = "site_users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    login_id: Mapped[str] = mapped_column(
        String(60), nullable=False, unique=True, comment="로그인 ID"
    )
    password_hash: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="bcrypt 해시. 평문은 어디에도 남기지 않는다"
    )
    name: Mapped[str] = mapped_column(
        String(120), nullable=False, default="", comment="계정 설명 (누구에게 나눠 준 계정인가)"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="False 면 로그인 · 기존 세션 모두 막힌다"
    )

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = ({"comment": "利用者画面ログインアカウント"},)

    def __repr__(self) -> str:
        return f"<SiteUser {self.login_id}>"


class SiteSession(Base):
    """이용자 화면 로그인 세션. 쿠키의 토큰 하나당 한 행."""

    __tablename__ = "site_sessions"

    token_hash: Mapped[str] = mapped_column(
        String(64), primary_key=True, comment="쿠키 토큰의 SHA-256 (원문은 두지 않는다)"
    )
    site_user_id: Mapped[int] = mapped_column(
        ForeignKey("site_users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("ix_site_sessions_user", "site_user_id"),
        Index("ix_site_sessions_expires", "expires_at"),
        {"comment": "利用者画面ログインセッション (サーバー起動時に全削除)"},
    )
