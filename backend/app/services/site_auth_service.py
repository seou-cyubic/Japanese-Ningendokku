"""이용자 화면 입장 로그인 · 세션.

관리 화면 로그인(`admin_auth_service`)과 같은 규칙을 따른다.

  · 실패 원인(ID 없음 / 비밀번호 틀림)을 구분해 알리지 않는다.
  · IP 하나당 실패 횟수를 센다 (5분에 10번 → 10분 차단, `lookup_service` 기준).
    예약 조회의 시도 기록 표를 함께 쓰되 앞머리로 갈라 횟수가 섞이지 않게 한다.

세션은 `site_sessions` 표에 둔다 (`app/models/site_user.py` 머리말 참조).
서버가 뜰 때 `clear_all_sessions` 로 비우므로, 재기동하면 모두 다시 로그인한다.

조작 로그(`audit_logs`)에는 남기지 않는다. 그 표는 **관리자가 한 일**의
기록이고, 이용자 화면 입장까지 섞으면 정작 찾아야 할 관리 조작이 묻힌다.
"""

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import verify_password
from app.models.site_user import SiteSession, SiteUser

LOGIN_ATTEMPT_PREFIX = "site-login:"

MSG_LOGIN_FAILED = "ログインIDまたはパスワードが正しくありません。"
MSG_INACTIVE = "このアカウントは現在ご利用いただけません。"
MSG_TOO_MANY = (
    "ログインの試行回数が上限に達しました。しばらく時間をおいてから"
    "再度お試しください。"
)


class SiteAuthError(Exception):
    """로그인 실패."""


class SiteLoginBlocked(SiteAuthError):
    """시도 횟수를 넘겨 잠시 막힌 상태."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(MSG_TOO_MANY)
        self.retry_after = retry_after


def _attempt_key(ip_address: str) -> str:
    return (LOGIN_ATTEMPT_PREFIX + ip_address)[:64] if ip_address else ""


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def login(db: Session, login_id: str, password: str, ip_address: str) -> tuple[SiteUser, str]:
    """로그인하고 새 세션을 만든다. (계정, 쿠키에 넣을 토큰) 을 돌려준다."""
    from app.services import lookup_service

    key = _attempt_key(ip_address)
    try:
        lookup_service.check_rate(db, key)
    except lookup_service.LookupBlocked as exc:
        raise SiteLoginBlocked(exc.retry_after) from exc

    user = db.execute(
        select(SiteUser).where(SiteUser.login_id == login_id)
    ).scalar_one_or_none()

    if user is None or not verify_password(password, user.password_hash):
        lookup_service.record_failure(db, key)
        raise SiteAuthError(MSG_LOGIN_FAILED)

    if not user.is_active:
        raise SiteAuthError(MSG_INACTIVE)

    now = datetime.now()
    # 기한이 지난 세션은 로그인할 때마다 조금씩 치운다
    db.execute(delete(SiteSession).where(SiteSession.expires_at < now))

    token = secrets.token_urlsafe(32)
    db.add(SiteSession(
        token_hash=_hash_token(token),
        site_user_id=user.id,
        expires_at=now + timedelta(seconds=settings.SITE_SESSION_TTL),
    ))
    user.last_login_at = now
    db.commit()
    db.refresh(user)
    return user, token


def logout(db: Session, token: str | None) -> None:
    if not token:
        return
    db.execute(delete(SiteSession).where(SiteSession.token_hash == _hash_token(token)))
    db.commit()


def current_user(db: Session, token: str | None) -> SiteUser | None:
    """쿠키의 세션이 살아 있는 계정을 돌려준다. 아니면 None.

    세션 행이 있고, 기한이 남아 있고, 계정이 정지되지 않았을 때만 통과한다.
    """
    if not token:
        return None

    session = db.get(SiteSession, _hash_token(token))
    if session is None or session.expires_at <= datetime.now():
        return None

    user = db.get(SiteUser, session.site_user_id)
    if user is None or not user.is_active:
        return None
    return user


def end_sessions_of(db: Session, site_user_id: int) -> int:
    """한 계정의 세션을 모두 끊는다 (비밀번호 변경 · 계정 정지). 커밋은 호출부가 한다."""
    return db.execute(
        delete(SiteSession).where(SiteSession.site_user_id == site_user_id)
    ).rowcount or 0


def clear_all_sessions(db: Session) -> int:
    """모든 세션을 끊는다. 서버가 뜰 때 부른다."""
    deleted = db.execute(delete(SiteSession)).rowcount or 0
    db.commit()
    return deleted


def to_me(user: SiteUser) -> dict:
    return {"login_id": user.login_id, "name": user.name}
