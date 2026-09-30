"""공개 API — 이용자 화면 입장 로그인.

    POST /api/v1/site/login    {"login_id": "test", "password": "…"}
    POST /api/v1/site/logout
    GET  /api/v1/site/me        로그인 상태 확인 (401 이면 로그인 화면으로)

이용자 화면과 공개 API 는 이 로그인을 거친 사람만 쓸 수 있다. 막는 일은
`app/main.py` 의 미들웨어(`site_auth_gate`)가 하고, 여기서는 쿠키를 주고
거둔다. 관리 화면 로그인(`api/admin/auth.py`)과 같은 모양이다 — 쿠키는
HttpOnly 라 JavaScript 는 토큰을 만지지 않는다. 다만 세션 자체는 서버(DB)에
두어, 서버를 다시 켜면 모두 끊긴다 (`site_auth_service` 참조).
"""

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import client_ip
from app.core.security import SITE_SESSION_COOKIE
from app.schemas.admin import LoginRequest
from app.services import site_auth_service
from app.services.site_auth_service import SiteAuthError, SiteLoginBlocked

router = APIRouter(prefix="/site", tags=["利用者画面 - 認証"])


@router.post(
    "/login",
    summary="利用者画面ログイン",
    description=(
        "成功時にHttpOnlyセッションCookieを返却する。"
        "失敗原因（IDなし / パスワード不一致）は区別して通知しない。"
    ),
)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    try:
        user, token = site_auth_service.login(
            db, payload.login_id, payload.password, client_ip(request)
        )
    except SiteLoginBlocked as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except SiteAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    response.set_cookie(
        key=SITE_SESSION_COOKIE,
        value=token,
        max_age=settings.SITE_SESSION_TTL,
        httponly=True,
        secure=settings.ADMIN_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return {"success": True, "data": site_auth_service.to_me(user)}


@router.post("/logout", summary="利用者画面ログアウト")
def logout(
    response: Response,
    db: Session = Depends(get_db),
    token: str | None = Cookie(default=None, alias=SITE_SESSION_COOKIE),
) -> dict:
    # 쿠키만 지우면 복사해 둔 쿠키로 계속 들어올 수 있다. 서버의 세션도 지운다.
    site_auth_service.logout(db, token)
    response.delete_cookie(SITE_SESSION_COOKIE, path="/")
    return {"success": True, "message": "ログアウトしました。"}


@router.get("/me", summary="利用者画面ログイン状態確認")
def me(
    db: Session = Depends(get_db),
    token: str | None = Cookie(default=None, alias=SITE_SESSION_COOKIE),
) -> dict:
    user = site_auth_service.current_user(db, token)
    if user is None:
        raise HTTPException(status_code=401, detail="ログインが必要です。")
    return {"success": True, "data": site_auth_service.to_me(user)}
