"""관리 화면 API — 로그인 · 로그아웃 · 내 정보 (A-00).

세션은 HttpOnly 쿠키에 담는다. JavaScript 에서 읽을 수 없어야
XSS 가 나더라도 세션이 통째로 새어 나가지 않는다. (plan.md §13.2)
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import client_ip, get_current_admin
from app.core.security import ADMIN_SESSION_COOKIE, issue_admin_session
from app.models.admin import AdminUser
from app.schemas.admin import LoginRequest, LoginResponse, Ok
from app.services import admin_auth_service
from app.services.admin_auth_service import AdminAuthError, AdminLoginBlocked

router = APIRouter(tags=["管理 - 認証"])


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="ログイン",
    description=(
        "ログイン成功時にHttpOnlyセッションCookieを返却する。\n\n"
        "失敗原因（IDなし / パスワード不一致）は区別して通知しない。"
        "区別すると有効なID一覧を割り出せてしまう。"
    ),
)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> LoginResponse:
    try:
        admin = admin_auth_service.login(
            db, payload.login_id, payload.password, client_ip(request)
        )
    except AdminLoginBlocked as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except AdminAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    response.set_cookie(
        key=ADMIN_SESSION_COOKIE,
        value=issue_admin_session(admin.id),
        max_age=settings.ADMIN_SESSION_TTL,
        httponly=True,
        secure=settings.ADMIN_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return LoginResponse(data=admin_auth_service.to_me(admin))


@router.post("/logout", response_model=Ok, summary="ログアウト")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> Ok:
    admin_auth_service.logout(db, admin, client_ip(request))
    response.delete_cookie(ADMIN_SESSION_COOKIE, path="/")
    return Ok(message="ログアウトしました。")


@router.get(
    "/me",
    response_model=LoginResponse,
    summary="ログイン状態確認",
    description="画面の初期表示時に呼び出す。401の場合はログイン画面へ遷移させる。",
)
def me(admin: AdminUser = Depends(get_current_admin)) -> LoginResponse:
    return LoginResponse(data=admin_auth_service.to_me(admin))
