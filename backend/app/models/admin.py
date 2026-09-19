"""관리자 계정 · 조작 로그 모델 (plan.md §9.9).

권한은 3단계다 (§5.2). 상위 권한은 하위 권한의 기능을 전부 포함한다.

    L3  SYSTEM_ADMIN   시스템 관리자 — 계정 관리 · 메일 템플릿 · 조작 로그
    L2  BUSINESS_ADMIN 업무 관리자   — 회장 · 정원 · 옵션 검사 + L1
    L1  STAFF          일반 스태프   — 예약 검색 · 수정 · 취소 · 우편 접수 입력

모든 관리자 조작은 예외 없이 `audit_logs` 에 남긴다.
스태프가 무엇을 했는지 추적할 수 없으면 문의에 답할 수 없다. (자체 피드백 M-8)
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    JSON,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

ROLE_SYSTEM_ADMIN = "SYSTEM_ADMIN"
ROLE_BUSINESS_ADMIN = "BUSINESS_ADMIN"
ROLE_STAFF = "STAFF"

ADMIN_ROLES = (ROLE_SYSTEM_ADMIN, ROLE_BUSINESS_ADMIN, ROLE_STAFF)

# 권한 레벨. 숫자가 클수록 상위 권한이며, 비교 한 줄로 판정할 수 있다.
ROLE_LEVELS: dict[str, int] = {
    ROLE_STAFF: 1,
    ROLE_BUSINESS_ADMIN: 2,
    ROLE_SYSTEM_ADMIN: 3,
}

ROLE_LABELS: dict[str, str] = {
    ROLE_SYSTEM_ADMIN: "システム管理者",
    ROLE_BUSINESS_ADMIN: "業務管理者",
    ROLE_STAFF: "一般スタッフ",
}


class AdminUser(Base):
    """관리 화면 로그인 계정."""

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    login_id: Mapped[str] = mapped_column(
        String(60), nullable=False, unique=True, comment="로그인 ID"
    )
    password_hash: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="bcrypt 해시. 평문은 어디에도 남기지 않는다"
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False, comment="담당자명")
    email: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    role: Mapped[str] = mapped_column(
        Enum(*ADMIN_ROLES, name="admin_role_enum"),
        nullable=False,
        default=ROLE_STAFF,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="퇴직·휴직 시 False. 계정을 지우지 않는 것은 조작 로그를 살리기 위함",
    )

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = ({"comment": "管理画面ログインアカウント"},)

    @property
    def level(self) -> int:
        return ROLE_LEVELS.get(self.role, 0)

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role)

    def can(self, required_level: int) -> bool:
        """요구 권한 이상인지 판정한다. (L3 ⊃ L2 ⊃ L1)"""
        return self.is_active and self.level >= required_level

    def __repr__(self) -> str:
        return f"<AdminUser {self.login_id} {self.role}>"


class AuditLog(Base):
    """관리자 조작 로그.

    변경 전후를 JSON 으로 통째로 남긴다. 컬럼별로 쪼개 두면
    스키마가 바뀔 때마다 로그 구조까지 따라 바꿔야 한다.
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    admin_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True
    )
    admin_login_id: Mapped[str] = mapped_column(
        String(60), nullable=False, default="", comment="계정이 지워져도 남는 조작자 표기"
    )
    admin_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    action: Mapped[str] = mapped_column(
        String(60), nullable=False, comment="예: RESERVATION_CANCEL"
    )
    target_type: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    target_id: Mapped[int | None] = mapped_column(nullable=True)
    target_label: Mapped[str] = mapped_column(
        String(255), nullable=False, default="", comment="목록에서 바로 알아볼 표기"
    )

    before_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # 한 번의 일괄 저장에서 나온 로그를 묶는 열쇠.
    #
    # 표에서 「저장」을 한 번 누르면 회장 21곳이 각각 로그 한 줄을 남긴다.
    # 목록에서는 21줄이 그냥 나란히 보일 뿐이라, **어디부터 어디까지가 한
    # 번의 조작이었는지** 알 수 없었다. 「아까 그 저장을 되돌리고 싶다」에
    # 답하려면 그 경계가 있어야 한다.
    #
    # 낱개 조작은 비어 있다. 묶을 것이 없기 때문이다.
    batch_id: Mapped[str] = mapped_column(
        String(40), nullable=False, default="", comment="한 번의 일괄 저장을 묶는 열쇠"
    )

    ip_address: Mapped[str] = mapped_column(String(45), nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_audit_created", "created_at"),
        Index("ix_audit_admin", "admin_user_id", "created_at"),
        Index("ix_audit_target", "target_type", "target_id"),
        Index("ix_audit_batch", "batch_id"),
        {"comment": "管理画面操作ログ"},
    )

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} {self.target_type}:{self.target_id}>"
