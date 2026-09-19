"""관리 화면 인증·권한 의존성 (plan.md §5.2 / §13.2).

권한 검사는 **화면과 API 양쪽에서** 한다.
화면에서 메뉴를 감추는 것은 실수 방지일 뿐 보안이 아니다.
주소를 직접 치거나 API 를 직접 부르는 경로가 항상 남는다. (자체 피드백 M-9)

사용법

    @router.get("", dependencies=[Depends(require_business_admin)])
    def list_hospitals(...): ...

    # 조작자를 로그에 남겨야 하는 경우
    def cancel(..., admin: AdminUser = Depends(require_staff)): ...
"""

from fastapi import Cookie, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import ADMIN_SESSION_COOKIE, read_admin_session
from app.models.admin import AdminUser

# 권한 레벨 (models/admin.py 의 ROLE_LEVELS 와 같은 축)
LEVEL_STAFF = 1           # L1 일반 스태프
LEVEL_BUSINESS_ADMIN = 2  # L2 업무 관리자
LEVEL_SYSTEM_ADMIN = 3    # L3 시스템 관리자


def get_current_admin(
    db: Session = Depends(get_db),
    session_token: str | None = Cookie(default=None, alias=ADMIN_SESSION_COOKIE),
) -> AdminUser:
    """로그인한 관리자를 돌려준다. 아니면 401."""
    admin_user_id = read_admin_session(session_token)
    if admin_user_id is None:
        raise HTTPException(status_code=401, detail="ログインが必要です。")

    admin = db.get(AdminUser, admin_user_id)
    if admin is None or not admin.is_active:
        # 계정 정지는 즉시 반영되어야 한다. 서명 쿠키는 스스로 무효화되지
        # 않으므로, 매 요청마다 DB 의 is_active 를 확인한다.
        raise HTTPException(status_code=401, detail="利用できないアカウントです。")

    return admin


def _require(level: int):
    def dependency(admin: AdminUser = Depends(get_current_admin)) -> AdminUser:
        if not admin.can(level):
            raise HTTPException(
                status_code=403,
                detail="この機能を利用する権限がありません。担当者にお問い合わせください。",
            )
        return admin

    return dependency


require_staff = _require(LEVEL_STAFF)
require_business_admin = _require(LEVEL_BUSINESS_ADMIN)
require_system_admin = _require(LEVEL_SYSTEM_ADMIN)


def client_ip(request: Request) -> str:
    """접속 IP. 조작 로그와 **조회 시도 횟수 제한**에 쓴다.

    `X-Forwarded-For` 는 **기본적으로 믿지 않는다.**
    이 헤더는 누구나 마음대로 적어 보낼 수 있다. 그대로 믿으면
    예약 조회(U-20)의 시도 횟수 제한을 헤더 값만 바꿔 가며 무한히
    우회할 수 있다. 로그도 마찬가지로 아무 주소나 남길 수 있게 된다.

    리버스 프록시(Nginx 등) 뒤에 둔 경우에만 `TRUST_PROXY_HEADER=true` 로
    켠다. 그때는 프록시가 헤더를 덮어쓰므로 첫 값이 실제 이용자다.
    프록시 없이 켜면 위의 우회가 그대로 열리므로 기본값은 꺼짐이다.
    """
    if settings.TRUST_PROXY_HEADER:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()

    return request.client.host if request.client else ""
