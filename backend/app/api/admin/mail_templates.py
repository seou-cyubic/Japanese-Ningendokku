"""관리 화면 API — 메일 템플릿 · 발송 이력 (A-40).

L3(시스템 관리자) 전용이다.
메일 문구는 전 이용자에게 나가는 대외 문서이므로 최상위 권한에서만 만진다.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import client_ip, require_system_admin
from app.models.admin import AdminUser
from app.schemas.admin import (
    MailLogResponse,
    MailTemplateListResponse,
    MailTemplatePreviewResponse,
    MailTemplateSaveRequest,
)
from app.services import admin_mail_service
from app.services.admin_mail_service import MailTemplateError

router = APIRouter(
    prefix="/mail-templates",
    tags=["管理 - メール"],
    dependencies=[Depends(require_system_admin)],
)


@router.get(
    "",
    response_model=MailTemplateListResponse,
    summary="メールテンプレート一覧",
    description=(
        "2種類（予約完了・リマインド）の件名・本文と、"
        "本文で使用できる置換変数一覧を併せて返す。"
    ),
)
def list_templates(db: Session = Depends(get_db)) -> MailTemplateListResponse:
    return MailTemplateListResponse(data=admin_mail_service.list_templates(db))


@router.put("/{template_key}", summary="メールテンプレート保存")
def save_template(
    template_key: str,
    payload: MailTemplateSaveRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_system_admin),
) -> dict:
    try:
        data = admin_mail_service.save_template(
            db, template_key, payload, admin=admin, ip_address=client_ip(request)
        )
    except MailTemplateError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {"success": True, "data": data, "message": "メール文面を保存しました。"}


@router.post(
    "/{template_key}/preview",
    response_model=MailTemplatePreviewResponse,
    summary="プレビュー",
    description=(
        "実際の予約1件の値を埋め込んで置換結果を表示する。\n\n"
        "**保存する前に** 確認できなければならない。"
        "保存後にしか結果が分からないようでは、誤ったメールがすでに送信された後だ。"
    ),
)
def preview(
    template_key: str,
    payload: MailTemplateSaveRequest,
    db: Session = Depends(get_db),
) -> MailTemplatePreviewResponse:
    return MailTemplatePreviewResponse(
        data=admin_mail_service.preview(db, template_key, payload)
    )


@router.get(
    "/logs",
    response_model=MailLogResponse,
    summary="メール送信履歴",
    description="失敗した件は予約詳細から再送信できる。",
)
def logs(
    status: str = Query("", description="SUCCESS / FAILED / SKIPPED"),
    keyword: str = Query("", description="予約番号またはメールアドレス"),
    page: int = Query(1, ge=1),
    size: int = Query(30, ge=1, le=200),
    db: Session = Depends(get_db),
) -> MailLogResponse:
    return MailLogResponse(
        data=admin_mail_service.list_logs(
            db, status=status, keyword=keyword, page=page, size=size
        )
    )
