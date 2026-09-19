"""관리자 로그인 · 계정 관리 (A-00 / A-50).

계정을 **지우지 않는다.** `is_active=False` 로 정지시킬 뿐이다.
계정을 지우면 그 사람이 남긴 조작 로그의 주인이 사라져,
「누가 이 예약을 취소했는가」에 답할 수 없게 된다. (자체 피드백 M-8)
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.admin import ROLE_LABELS, AdminUser
from app.schemas.admin import (
    AccountCreateRequest,
    AccountRow,
    AccountUpdateRequest,
    AdminMe,
)
from app.services import audit_service


class AdminAuthError(Exception):
    """로그인 실패. 원인을 구분해서 알려 주지 않는다."""


# 로그인 실패 문구를 한 가지로 통일한다.
# 「그런 ID 는 없습니다」와 「비밀번호가 틀립니다」를 구분해서 알려 주면
# ID 목록을 캐낼 수 있다. (plan.md §13.2)
MSG_LOGIN_FAILED = "ログインIDまたはパスワードが正しくありません。"
MSG_INACTIVE = "利用停止中のアカウントです。システム管理者にお問い合わせください。"


def to_me(admin: AdminUser) -> AdminMe:
    return AdminMe(
        id=admin.id,
        login_id=admin.login_id,
        name=admin.name,
        email=admin.email,
        role=admin.role,
        role_label=admin.role_label,
        level=admin.level,
        last_login_at=admin.last_login_at,
    )


def to_row(admin: AdminUser) -> AccountRow:
    return AccountRow(
        id=admin.id,
        login_id=admin.login_id,
        name=admin.name,
        email=admin.email,
        role=admin.role,
        role_label=admin.role_label,
        level=admin.level,
        is_active=admin.is_active,
        last_login_at=admin.last_login_at,
        created_at=admin.created_at,
    )


# 로그인 시도 제한의 기록 열쇠. 예약 조회의 시도 기록 표(`lookup_attempts`)를
# 함께 쓰되, 앞머리로 갈라 서로의 횟수가 섞이지 않게 한다.
LOGIN_ATTEMPT_PREFIX = "admin-login:"

MSG_TOO_MANY = (
    "ログインの試行回数が上限に達しました。しばらく時間をおいてから"
    "再度お試しください。"
)


class AdminLoginBlocked(AdminAuthError):
    """시도 횟수를 넘겨 잠시 막힌 상태."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(MSG_TOO_MANY)
        self.retry_after = retry_after


def _attempt_key(ip_address: str) -> str:
    return (LOGIN_ATTEMPT_PREFIX + (ip_address or ""))[:64] if ip_address else ""


def login(db: Session, login_id: str, password: str, ip_address: str) -> AdminUser:
    """로그인. 실패도 조작 로그에 남긴다 (침입 시도 추적).

    예약 조회와 같이 **IP 하나당 실패 횟수를 센다.** 관리자 비밀번호는 예약번호보다
    훨씬 짧고 사람이 고른 값이라, 제한 없이 두드리게 두면 조작 로그만 쌓일 뿐
    막을 방법이 없다. (5분에 10번 → 10분 차단, `lookup_service` 와 같은 기준)
    """
    from app.services import lookup_service

    key = _attempt_key(ip_address)
    try:
        lookup_service.check_rate(db, key)
    except lookup_service.LookupBlocked as exc:
        raise AdminLoginBlocked(exc.retry_after) from exc

    admin = db.execute(
        select(AdminUser).where(AdminUser.login_id == login_id)
    ).scalar_one_or_none()

    if admin is None or not verify_password(password, admin.password_hash):
        audit_service.write_log(
            db,
            admin=None,
            action="ADMIN_LOGIN_FAILED",
            target_type="admin_user",
            target_label=login_id,
            ip_address=ip_address,
        )
        db.commit()
        lookup_service.record_failure(db, key)
        raise AdminAuthError(MSG_LOGIN_FAILED)

    if not admin.is_active:
        audit_service.write_log(
            db,
            admin=admin,
            action="ADMIN_LOGIN_FAILED",
            target_type="admin_user",
            target_id=admin.id,
            target_label=f"{login_id} (停止されたアカウント)",
            ip_address=ip_address,
        )
        db.commit()
        raise AdminAuthError(MSG_INACTIVE)

    admin.last_login_at = datetime.now()

    audit_service.write_log(
        db,
        admin=admin,
        action="ADMIN_LOGIN",
        target_type="admin_user",
        target_id=admin.id,
        target_label=admin.name,
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(admin)
    return admin


def logout(db: Session, admin: AdminUser, ip_address: str) -> None:
    audit_service.write_log(
        db,
        admin=admin,
        action="ADMIN_LOGOUT",
        target_type="admin_user",
        target_id=admin.id,
        target_label=admin.name,
        ip_address=ip_address,
    )
    db.commit()


# ==========================================================================
# A-50 계정 관리 (L3 전용)
# ==========================================================================


def list_accounts(db: Session) -> list[AccountRow]:
    stmt = select(AdminUser).order_by(
        AdminUser.is_active.desc(), AdminUser.role, AdminUser.login_id
    )
    return [to_row(a) for a in db.execute(stmt).scalars()]


# 시스템 관리자(L3)는 화면에서 **만들 수도, 승격시킬 수도 없다.**
#
# L3 는 계정 관리·메일 문안·조작 로그까지 전부 볼 수 있는 자리라, 한 번
# 늘어나면 「누가 왜 늘렸는지」를 따질 수 있는 사람도 같이 늘어난다.
# 첫 L3 는 설치할 때 `scripts/init_db` 가 심고, 그 뒤로는 DB 를 직접
# 만질 수 있는 사람만 늘릴 수 있게 둔다 (README §11).
#
# 엔드포인트 자체가 L3 전용이라 「외부 침입」을 막는 장치는 아니다.
# 실수로 한 번 더 만드는 것을 막고, 문서가 약속한 통제를 코드로 세운다.
SYSTEM_ADMIN_BLOCKED = (
    "システム管理者(L3)アカウントはこの画面から作成・変更できません。"
    "必要な場合はシステム担当者にご依頼ください。"
)


def _reject_system_admin_role(role: str) -> None:
    if role == "SYSTEM_ADMIN":
        raise AdminAuthError(SYSTEM_ADMIN_BLOCKED)


def create_account(
    db: Session,
    payload: AccountCreateRequest,
    *,
    admin: AdminUser,
    ip_address: str,
) -> AccountRow:
    _reject_system_admin_role(payload.role)

    exists = db.execute(
        select(func.count())
        .select_from(AdminUser)
        .where(AdminUser.login_id == payload.login_id)
    ).scalar()

    if exists:
        raise AdminAuthError("すでに使用されているログインIDです。")

    account = AdminUser(
        login_id=payload.login_id,
        password_hash=hash_password(payload.password),
        name=payload.name,
        email=payload.email,
        role=payload.role,
        is_active=payload.is_active,
    )
    db.add(account)
    db.flush()

    audit_service.write_log(
        db,
        admin=admin,
        action="ACCOUNT_CREATE",
        target_type="admin_user",
        target_id=account.id,
        target_label=f"{account.login_id} ({ROLE_LABELS.get(account.role, account.role)})",
        after={
            "login_id": account.login_id,
            "name": account.name,
            "role": account.role,
            "is_active": account.is_active,
        },
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(account)
    return to_row(account)


def update_account(
    db: Session,
    account_id: int,
    payload: AccountUpdateRequest,
    *,
    admin: AdminUser,
    ip_address: str,
) -> AccountRow:
    account = db.get(AdminUser, account_id)
    if account is None:
        raise AdminAuthError("アカウントが見つかりません。")

    # 승격 차단. 이미 L3 인 계정을 그대로 두는 저장은 통과시켜야 한다 —
    # 그렇지 않으면 L3 본인의 이름·메일조차 고칠 수 없다.
    if account.role != "SYSTEM_ADMIN":
        _reject_system_admin_role(payload.role)

    # 마지막 시스템 관리자가 스스로를 강등·정지시키면 아무도 계정을
    # 관리할 수 없게 된다. 되돌릴 방법이 화면에 없으므로 여기서 막는다.
    if account.role == "SYSTEM_ADMIN" and (
        payload.role != "SYSTEM_ADMIN" or not payload.is_active
    ):
        remaining = db.execute(
            select(func.count())
            .select_from(AdminUser)
            .where(
                AdminUser.role == "SYSTEM_ADMIN",
                AdminUser.is_active.is_(True),
                AdminUser.id != account.id,
            )
        ).scalar()
        if not remaining:
            raise AdminAuthError(
                "最後のシステム管理者です。"
                "他のアカウントをシステム管理者に指定してから変更してください。"
            )

    fields = ["name", "email", "role", "is_active"]
    before = audit_service.snapshot(account, fields)

    account.name = payload.name
    account.email = payload.email
    account.role = payload.role
    account.is_active = payload.is_active

    password_changed = bool(payload.password)
    if password_changed:
        if len(payload.password) < 8:
            raise AdminAuthError("パスワードは8文字以上である必要があります。")
        account.password_hash = hash_password(payload.password)

    after = audit_service.snapshot(account, fields)
    changed = audit_service.diff(before, after)
    if password_changed:
        changed["password"] = {"before": "***", "after": "変更済み"}

    audit_service.write_log(
        db,
        admin=admin,
        action="ACCOUNT_PASSWORD_RESET" if password_changed and not changed else "ACCOUNT_UPDATE",
        target_type="admin_user",
        target_id=account.id,
        target_label=account.login_id,
        before=before,
        after=changed,
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(account)
    return to_row(account)
