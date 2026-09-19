"""건강검진 예약 시스템 — FastAPI 진입점.

프런트엔드(Vanilla HTML/CSS/JS)를 같은 오리진에서 함께 서빙한다.
동일 오리진이므로 CORS 설정이 필요 없고, 이용자는 주소 하나만 알면 된다.

    실행:  python -m uvicorn app.main:app --reload
    화면:  http://127.0.0.1:8000/
    관리:  http://127.0.0.1:8000/admin/
    문서:  http://127.0.0.1:8000/docs
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.exceptions import RequestValidationError

from app.api import admin as admin_api
from app.api.public import exam_options as exam_options_api
from app.api.public import hospitals as hospitals_api
from app.api.public import lookup as lookup_api
from app.api.public import postal as postal_api
from app.api.public import reservations as reservations_api
from app.api.public import verify as verify_api
from app.core.config import (
    DEFAULT_ADMIN_PASSWORDS,
    DEFAULT_SECRET_KEY,
    FRONTEND_DIR,
    settings,
)

logger = logging.getLogger("kenshin")


# --------------------------------------------------------------------------
# 기간이 지난 예약 자동 삭제
#
# 「8월 7일 09:00 예약은 8월 7일 10:00 에 삭제」 규칙을 지키려면 누군가
# 주기적으로 확인해야 한다. 외부 스케줄러(cron·APScheduler)를 붙이면
# 배포 대상이 하나 늘어나므로, 우선 앱 안의 백그라운드 태스크로 돌린다.
#
# 운영에서 워커를 여러 개 띄우면 모든 워커가 같은 작업을 하게 되지만,
# DELETE 는 멱등이라 결과가 달라지지 않는다. (중복 실행이 안전한 작업)
# --------------------------------------------------------------------------


async def _purge_loop() -> None:
    from app.core.database import SessionLocal
    from app.services import purge_service

    interval = settings.RESERVATION_PURGE_INTERVAL_MINUTES * 60

    while True:
        try:
            await asyncio.sleep(interval)
            db = SessionLocal()
            try:
                deleted = await asyncio.to_thread(purge_service.purge_expired, db)
                if deleted:
                    logger.info("受診時刻を過ぎた予約 %d件を削除しました。", deleted)
            finally:
                db.close()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — 정리 실패로 서버를 멈추지 않는다
            logger.exception("予約の自動整理中にエラーが発生しました。")


# --------------------------------------------------------------------------
# 우편번호(주소) 데이터 확인
#
# 「주소 찾기」(U-14)가 이 데이터 위에서 돈다. 넣지 않으면 검색이 **조용히
# 0건**을 돌려주고, 화면에도 로그에도 원인이 남지 않는다. 「검색해도 아무것도
# 안 나온다」는 문의가 들어와야 비로소 알게 되는 종류의 고장이다.
#
# 그래서 뜰 때 한 번 세어 보고, 비어 있으면 채운다. 내려받기 + 적재에
# 1~2분이 걸리므로 **기동을 막지 않는다** — 스레드에 넘기고 서버는 먼저 뜬다.
# 그 사이 주소 검색은 503 을 돌려주고(`api/public/postal.py`), 이용자에게는
# 「직접 입력해 주세요」가 뜬다.
#
# 실패해도 서버는 뜬다. 주소 검색이 안 되는 것과 예약을 아예 못 받는 것은
# 심각도가 전혀 다르다.
# --------------------------------------------------------------------------


async def _check_postal_data() -> None:
    from app.core.database import SessionLocal
    from app.services import postal_import_service

    try:
        await asyncio.to_thread(
            postal_import_service.run_startup_import,
            SessionLocal,
            auto=settings.POSTAL_AUTO_IMPORT,
            minimum=settings.POSTAL_MIN_ROWS,
            source=settings.POSTAL_SOURCE_FILE,
        )
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 — 여기까지 새어 나오면 안 되지만, 서버는 뜬다
        logger.exception("郵便番号データの確認中にエラーが発生しました。")


# --------------------------------------------------------------------------
# 기동 전 안전장치 — 기본 서명 키 · 기본 관리자 비밀번호
#
# `SECRET_KEY` 의 기본값은 저장소에 그대로 적혀 있다. 그 값을 쓰는 서버는
# 누구나 관리자 세션 쿠키를 위조해 만들 수 있다. 로그인 화면을 뚫을 필요도
# 없다 — 쿠키 하나면 관리 화면이 통째로 열린다.
#
# 그런데도 지금까지는 **아무 말 없이 떴다.** 교체를 빠뜨린 배포는 사고가
# 나기 전까지 아무도 모른다. 그래서 운영 모드에서는 기동을 거부한다.
# 로컬 개발(기본 ENV)에서는 편의를 위해 기본값을 허용하되, 한 줄 경고를 남긴다.
#
# 기본 관리자 비밀번호는 **막지 않고 경고만** 한다. DB 를 읽어야 알 수 있는
# 값이라, DB 가 잠깐 흔들린다고 서버가 못 뜨는 쪽이 더 위험하기 때문이다.
# --------------------------------------------------------------------------


class InsecureConfigError(RuntimeError):
    """기본 비밀값 그대로 운영 모드로 띄우려 할 때."""


def _check_secret_key() -> None:
    if not settings.uses_default_secret_key:
        return
    if settings.is_production:
        raise InsecureConfigError(
            f"SECRET_KEY が既定値（{DEFAULT_SECRET_KEY}）のままです。"
            "この値は公開リポジトリに記載されており、管理画面のセッション"
            "クッキーを誰でも偽造できます。backend/.env の SECRET_KEY を"
            "ランダムな値に変更してから起動してください。"
            "（例: python -c \"import secrets;print(secrets.token_urlsafe(48))\"）"
        )
    logger.warning(
        "SECRET_KEY が既定値のままです。開発用としてこのまま起動しますが、"
        "本番環境（ENV=production / ADMIN_COOKIE_SECURE=true）では起動を拒否します。"
    )


def _warn_default_admin_passwords() -> None:
    """기본 비밀번호가 남아 있으면 경고. 실패해도 기동은 막지 않는다."""
    from app.core.database import SessionLocal
    from app.core.security import verify_password
    from app.models.admin import AdminUser

    try:
        db = SessionLocal()
        try:
            left = [
                a.login_id
                for a in db.query(AdminUser).filter(
                    AdminUser.login_id.in_(tuple(DEFAULT_ADMIN_PASSWORDS))
                )
                if verify_password(DEFAULT_ADMIN_PASSWORDS[a.login_id],
                                   a.password_hash)
            ]
        finally:
            db.close()
    except Exception:  # noqa: BLE001 — 확인에 실패해도 서버는 뜬다
        logger.debug("既定パスワードの確認をスキップしました。", exc_info=True)
        return

    if left:
        logger.warning(
            "既定のパスワードのままの管理者アカウントがあります: %s。"
            "README §4 に記載された値のため、公開前に必ず変更してください。",
            " / ".join(sorted(left)),
        )


# --------------------------------------------------------------------------
# 데이터베이스 준비 — DB 생성 · 마이그레이션 · 필수 초기 데이터
#
# 저장소를 받은 사람이 `.env` 만 채우고 서버를 띄우면 그대로 돌아가야 한다.
# 예전에는 `init_db` 를 먼저 돌리지 않으면 모든 API 가 「Table doesn't exist」
# 로 500 을 냈고, 코드를 올린 뒤 칼럼 추가 스크립트를 빠뜨리면 특정 화면만
# 조용히 500 이 났다(메일 문구 화면의 ENUM 이 그 예다).
#
# **여기서는 기동을 멈추지 않는다.** DB 가 잠깐 안 뜬 것으로 서버까지 못
# 뜨면 원인을 화면에서 볼 수조차 없다. 대신 로그에 무엇을 할지 크게 적는다.
# --------------------------------------------------------------------------


def _prepare_database() -> None:
    from app.core import db_setup

    try:
        summary = db_setup.prepare_database()
    except db_setup.DatabaseSetupError as exc:
        logger.error("データベースを準備できませんでした。\n%s", exc)
        return
    except Exception:  # noqa: BLE001 — 접속 실패 등. 서버는 뜬다
        logger.exception(
            "データベースを準備できませんでした。backend/.env の DB_* を確認し、"
            "python -m scripts.setup_db を実行してください。"
        )
        return

    seeded = summary["seeded"]
    if summary["from_revision"] != summary["to_revision"] or any(seeded.values()):
        logger.info(
            "データベース準備完了 — スキーマ %s → %s / 管理者 %d件・メール文面 %d件を投入",
            summary["from_revision"] or "(空)",
            summary["to_revision"],
            seeded["admins"],
            seeded["mail_templates"],
        )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task: asyncio.Task | None = None
    postal_task: asyncio.Task | None = None

    _check_secret_key()
    if settings.DB_AUTO_MIGRATE:
        # 우편번호 확인·자동 정리보다 **먼저** 끝나야 한다. 테이블이 없는 채로
        # 그 둘이 돌면 첫 기동 로그가 오류로 덮인다.
        await asyncio.to_thread(_prepare_database)
    if settings.is_production:
        await asyncio.to_thread(_warn_default_admin_passwords)

    if settings.RESERVATION_PURGE_INTERVAL_MINUTES > 0:
        task = asyncio.create_task(_purge_loop())
        logger.info(
            "予約の自動整理を開始 — %d分ごと / 受診時刻 +%d分の経過で削除",
            settings.RESERVATION_PURGE_INTERVAL_MINUTES,
            settings.RESERVATION_EXPIRE_GRACE_MINUTES,
        )

    postal_task = asyncio.create_task(_check_postal_data())

    yield

    for pending in (task, postal_task):
        if pending is None:
            continue
        pending.cancel()
        try:
            await pending
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="健康診断予約システム API",
    description="医療法人 Sample Group 健康診断予約システム",
    version="0.2.0",
    lifespan=lifespan,
)

# --------------------------------------------------------------------------
# API 라우터
# --------------------------------------------------------------------------
api_router = APIRouter(prefix="/api/v1")
api_router.include_router(verify_api.router)
api_router.include_router(hospitals_api.router)
api_router.include_router(exam_options_api.router)
api_router.include_router(postal_api.router)
api_router.include_router(lookup_api.router)
api_router.include_router(reservations_api.router)
api_router.include_router(admin_api.router)


@api_router.get("/health", tags=["システム"], summary="ヘルスチェック")
def health() -> dict:
    return {"success": True, "data": {"status": "ok"}}


@api_router.get("/contact", tags=["システム"], summary="お問い合わせ先")
def contact() -> dict:
    """문의처(전화 · 메일 · 접수 시간). 값은 `.env` 의 `CONTACT_*` 한 곳에만 둔다.

    첫 화면과 FAQ 가 번호를 HTML 에 박아 두어, 설정을 바꿔도 그 두 화면만
    예전 번호를 안내했다. 화면은 이 값을 읽어 채운다.
    """
    from app.services import lookup_service

    return {"success": True, "data": lookup_service.contact()}


app.include_router(api_router)


# --------------------------------------------------------------------------
# 오류 응답 규약 (plan.md §10.3)
# 프런트가 항목 바로 아래에 메시지를 표시할 수 있도록 fields 를 함께 준다.
# --------------------------------------------------------------------------
@app.exception_handler(RequestValidationError)
def on_validation_error(_request, exc: RequestValidationError) -> JSONResponse:
    fields = []
    for err in exc.errors():
        # loc 예: ("body", "birth_date")
        loc = [str(p) for p in err["loc"] if p not in ("body", "query", "path")]
        fields.append(
            {
                "name": ".".join(loc) or "_",
                "message": err["msg"].removeprefix("Value error, "),
            }
        )

    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "入力内容をご確認ください。",
            },
            "fields": fields,
        },
    )


_NOT_FOUND_HTML = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ページが見つかりません｜健康診断予約</title>
<style>body{font-family:Meiryo,sans-serif;margin:0;padding:64px 16px;text-align:center;color:#1F2A28;background:#F6F8F7}
a{color:#0B6E5B;font-weight:700}</style></head>
<body><h1>ページが見つかりません</h1>
<p>お探しのページは移動したか、削除された可能性があります。</p>
<p><a href="/">最初の画面へ</a></p></body></html>"""


@app.exception_handler(StarletteHTTPException)
def on_http_error(request, exc: StarletteHTTPException) -> Response:
    # 화면 주소를 잘못 치거나 옛 링크로 온 사람에게 JSON 을 그대로 보여 주지 않는다.
    # API 는 지금까지와 같이 JSON 이다 — 화면 스크립트가 그 모양을 읽는다.
    if exc.status_code == 404 and not request.url.path.startswith("/api/"):
        return HTMLResponse(_NOT_FOUND_HTML, status_code=404)

    # 상태 코드마다 의미가 다르므로 화면이 구분할 수 있게 코드를 나눠 준다.
    code = {
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        503: "UNAVAILABLE",
    }.get(exc.status_code, "HTTP_ERROR")

    # detail 은 보통 문장 하나지만, 화면이 **문장 말고 더 필요한 것**이 있는
    # 경우가 있다. 주소 검색이 그렇다 — 데이터가 없어 검색을 못 할 때
    # 「전화로 접수해 드립니다」와 그 번호를 함께 줘야 이용자가 막히지 않는다.
    #
    #     raise HTTPException(503, detail={"message": "…", "contact": {...}})
    #
    # 그때만 dict 로 준다. 문자열이면 지금까지와 똑같이 동작한다.
    detail = exc.detail
    extra: dict = {}
    if isinstance(detail, dict):
        message = str(detail.get("message", ""))
        extra = {k: v for k, v in detail.items() if k != "message"}
    else:
        message = str(detail)

    error: dict = {"code": code, "message": message}
    error.update(extra)

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": error,
        },
        headers=getattr(exc, "headers", None),
    )


# --------------------------------------------------------------------------
# 프런트엔드 정적 파일
# ※ API 라우터보다 뒤에 마운트해야 /api/* 가 가려지지 않는다.
# --------------------------------------------------------------------------
class RevalidatingStaticFiles(StaticFiles):
    """쓰기 전에 반드시 서버에 물어보게 한다.

    Cache-Control 을 붙이지 않으면 브라우저가 휴리스틱 캐싱을 하는데,
    그러면 HTML 만 새로 받고 CSS/JS 는 옛것을 쓰는 어긋난 상태가 생긴다.
    화면이 깨지거나 목록이 안 뜨는데 서버·코드는 멀쩡한 상황이 여기서 나온다.

    no-cache 는 「캐시하지 말라」가 아니라 「쓰기 전에 검사하라」는 뜻이다.
    ETag 가 그대로면 304 를 받으므로 전송량은 늘지 않는다.
    """

    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(
        FRONTEND_DIR / "index.html",
        headers={"Cache-Control": "no-cache"},
    )


app.mount("/", RevalidatingStaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
