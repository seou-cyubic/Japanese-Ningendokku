"""관리 화면 API — 관리자 계정 관리 (A-50).

L3(시스템 관리자) 전용 (plan.md §5.2).
계정은 **삭제하지 않는다.** 정지(`is_active=false`)만 한다.
지우면 그 사람이 남긴 조작 로그의 주인이 사라진다.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import client_ip, require_system_admin
from app.models.admin import ROLE_LABELS, AdminUser
from app.schemas.admin import (
    AccountCreateRequest,
    AccountListResponse,
    AccountUpdateRequest,
)
from app.services import admin_auth_service
from app.services.admin_auth_service import AdminAuthError

router = APIRouter(
    prefix="/accounts",
    tags=["管理 - アカウント"],
    dependencies=[Depends(require_system_admin)],
)


@router.get("", response_model=AccountListResponse, summary="アカウント一覧")
def list_accounts(db: Session = Depends(get_db)) -> AccountListResponse:
    return AccountListResponse(data=admin_auth_service.list_accounts(db))


@router.get(
    "/roles",
    summary="権限の選択肢",
    description=(
        "3段階の権限と各段階で可能な操作を合わせて返す。\n\n"
        "システム管理者(L3)は `selectable: false` で返す — この画面から"
        "L3 アカウントを新規作成したり、他のアカウントを L3 に昇格させたりは"
        "できない(サーバー側でも拒否する)。既存の L3 を表示するための項目である。"
    ),
)
def roles() -> dict:
    return {
        "success": True,
        "data": [
            {
                "value": "SYSTEM_ADMIN",
                "label": ROLE_LABELS["SYSTEM_ADMIN"],
                "level": 3,
                "can": "全機能 + アカウント管理 + メール文面編集 + 操作ログ閲覧",
                # 화면 드롭다운에서 빼기 위한 표시. 서버도 같은 판정을
                # 한 번 더 한다 (`admin_auth_service._reject_system_admin_role`).
                "selectable": False,
            },
            {
                "value": "BUSINESS_ADMIN",
                "label": ROLE_LABELS["BUSINESS_ADMIN"],
                "level": 2,
                "can": "会場・定員・オプション検査管理 + 一般スタッフの全機能",
                "selectable": True,
            },
            {
                "value": "STAFF",
                "label": ROLE_LABELS["STAFF"],
                "level": 1,
                "can": "予約検索・修正・キャンセル + 郵送受付入力",
                "selectable": True,
            },
        ],
    }


@router.post("", summary="アカウント登録")
def create_account(
    payload: AccountCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_system_admin),
) -> dict:
    try:
        data = admin_auth_service.create_account(
            db, payload, admin=admin, ip_address=client_ip(request)
        )
    except AdminAuthError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {"success": True, "data": data, "message": "アカウントを登録しました。"}


@router.put(
    "/{account_id}",
    summary="アカウント修正",
    description=(
        "パスワードを空欄にした場合は変更しない。\n\n"
        "最後のシステム管理者を降格・停止させる操作は拒否する。"
        "許可すると誰もアカウントを管理できない状態になり、, "
        "画面からは元に戻す方法がない。"
    ),
)
def update_account(
    account_id: int,
    payload: AccountUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_system_admin),
) -> dict:
    try:
        data = admin_auth_service.update_account(
            db, account_id, payload, admin=admin, ip_address=client_ip(request)
        )
    except AdminAuthError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {"success": True, "data": data, "message": "アカウント情報を保存しました。"}
