"""본인 확인 토큰 · 관리자 인증.

두 가지를 다룬다.

  1. **본인 확인 토큰** — U-11 을 통과했다는 사실을 다음 단계로 전달한다.
  2. **관리자 세션** — 관리 화면 로그인 상태를 유지한다.

둘 다 서버에 상태를 두지 않는 HMAC 서명 방식(itsdangerous)이라
Redis 없이도 동작한다.

※ plan.md §11.7 은 관리자 세션을 Redis 에 두도록 되어 있다.
   Redis 도입 시 아래 `issue_admin_session` / `read_admin_session` 두 함수의
   내부만 바꾸면 되도록 이 모듈에 격리해 두었다. 호출부는 손대지 않는다.
   서명 쿠키 방식의 한계는 **강제 로그아웃(세션 즉시 무효화)이 안 된다**는
   점이며, 계정 정지(`is_active=False`)는 매 요청 DB 조회로 즉시 반영된다.
"""

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import settings

_SALT_VERIFY = "verify-identity"
_SALT_ADMIN = "admin-session"

_verify_serializer = URLSafeTimedSerializer(settings.SECRET_KEY, salt=_SALT_VERIFY)
_admin_serializer = URLSafeTimedSerializer(settings.SECRET_KEY, salt=_SALT_ADMIN)


# ==========================================================================
# 본인 확인 토큰 (이용자)
# ==========================================================================


def issue_verify_token(person_id: int) -> str:
    """본인 확인 통과 토큰을 발급한다."""
    return _verify_serializer.dumps({"pid": person_id})


def read_verify_token(token: str) -> int | None:
    """토큰에서 대상자 ID 를 꺼낸다.

    만료·위조된 토큰이면 None 을 반환한다.
    """
    try:
        payload = _verify_serializer.loads(token, max_age=settings.VERIFY_TOKEN_TTL)
    except (SignatureExpired, BadSignature):
        return None

    person_id = payload.get("pid")
    return person_id if isinstance(person_id, int) else None


# ==========================================================================
# 비밀번호 (관리자)
# ==========================================================================


def hash_password(plain: str) -> str:
    """bcrypt 해시를 만든다. (plan.md §13.2)"""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """비밀번호를 대조한다. 해시가 깨져 있어도 예외를 밖으로 내보내지 않는다."""
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ==========================================================================
# 관리자 세션
# ==========================================================================

ADMIN_SESSION_COOKIE = "kenshin_admin"


def issue_admin_session(admin_user_id: int) -> str:
    """로그인 세션 토큰을 발급한다."""
    return _admin_serializer.dumps({"uid": admin_user_id})


def read_admin_session(token: str | None) -> int | None:
    """세션 토큰에서 관리자 ID 를 꺼낸다.

    만료·위조된 토큰이면 None 을 반환한다.
    """
    if not token:
        return None

    try:
        payload = _admin_serializer.loads(token, max_age=settings.ADMIN_SESSION_TTL)
    except (SignatureExpired, BadSignature):
        return None

    admin_user_id = payload.get("uid")
    return admin_user_id if isinstance(admin_user_id, int) else None
