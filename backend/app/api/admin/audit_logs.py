"""관리 화면 API — 조작 로그 (A-60).

L3(시스템 관리자) 전용.
여기서 답할 수 있어야 하는 질문은 하나다 — 「이 예약, 누가 언제 이렇게 만들었나?」
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import client_ip, require_system_admin
from app.models.admin import AdminUser
from app.schemas.admin import AuditLogResponse
from app.services import admin_audit_service, admin_revert_service, audit_service

router = APIRouter(
    prefix="/audit-logs",
    tags=["管理 - 操作ログ"],
    dependencies=[Depends(require_system_admin)],
)


@router.get(
    "",
    response_model=AuditLogResponse,
    summary="操作ログ照会",
    description=(
        "変更前後をJSONのまま残しているため、何が何に変わったのか"
        "行を展開して確認できる。"
    ),
)
def list_logs(
    keyword: str = Query("", description="対象・担当者"),
    action: str = Query("", description="操作種別"),
    admin_user_id: int | None = Query(None),
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    log_id_from: int | None = Query(None, description="ログID（開始）"),
    log_id_to: int | None = Query(None, description="ログID（終了）"),
    page: int = Query(1, ge=1),
    size: int = Query(40, ge=1, le=200),
    db: Session = Depends(get_db),
) -> AuditLogResponse:
    return AuditLogResponse(
        data=admin_audit_service.list_logs(
            db,
            keyword=keyword,
            action=action,
            admin_user_id=admin_user_id,
            date_from=date_from,
            date_to=date_to,
            log_id_from=log_id_from,
            log_id_to=log_id_to,
            page=page,
            size=size,
        )
    )


@router.get(
    "/export-csv",
    summary="操作ログCSV書き出し",
    description="現在のフィルター条件に該当する操作ログ履歴をCSVファイルとしてダウンロードします。",
)
def export_logs_csv(
    keyword: str = Query("", description="対象・担当者"),
    action: str = Query("", description="操作種別"),
    admin_user_id: int | None = Query(None),
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    log_id_from: int | None = Query(None, description="ログID（開始）"),
    log_id_to: int | None = Query(None, description="ログID（終了）"),
    format: str = Query("csv", alias="format", pattern="^(csv|xlsx)$"),
    db: Session = Depends(get_db),
):
    from fastapi.responses import Response

    filename, file_bytes, media_type = admin_audit_service.export_file(
        db,
        keyword=keyword,
        action=action,
        admin_user_id=admin_user_id,
        date_from=date_from,
        date_to=date_to,
        log_id_from=log_id_from,
        log_id_to=log_id_to,
        fmt=format,
    )
    return Response(
        content=file_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/filters", summary="フィルター選択肢")
def filters(db: Session = Depends(get_db)) -> dict:
    return {
        "success": True,
        "data": {
            "actions": admin_audit_service.action_choices(),
            "admins": [
                {"id": a.id, "name": a.name, "login_id": a.login_id}
                for a in audit_service.list_admin_choices(db)
            ],
        },
    }


# ==========================================================================
# 일괄 저장 되돌리기
# ==========================================================================
#
# 표에서 「저장」을 한 번 누른 것을 통째로 되돌린다. 근거는 조작 로그다 —
# 일괄 저장은 로그마다 같은 `batch_id` 를 남기므로 그 열쇠로 모을 수 있다.
#
# 되돌리기 자체가 되돌릴 수 없는 조작이라, **반드시 미리보기를 먼저** 보게
# 한다. 그 사이 남이 고친 칸이 있으면 그 행은 건너뛰고 이유를 말한다.


@router.get(
    "/batches",
    summary="一括保存一覧",
    description=(
        "元に戻すことが可能な一括保存を新しい順に返す。1行が「テーブルで保存を "
        "1回クリックしたもの」である。\n\n"
        "個別の操作はここには表示されない — まとめるものがないためだ。"
    ),
)
def list_batches(
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    return {
        "success": True,
        "data": admin_audit_service.list_batches(db, limit=limit),
    }


@router.get(
    "/batches/{batch_id}",
    summary="元に戻すと何がどうなるか",
    description=(
        "**何も変更しない。** 元に戻したときに各行がどうなるかだけを"
        "計算して返す。\n\n"
        "`plan` が `RESTORE` であれば値を元に戻し、, `DELETE` であればこの保存で新規に"
        "作成されたものを削除し、, `SKIP` であれば手を加えない。 `SKIP` には必ず "
        "`reason` が付く — その後に誰かが修正したか、予約が入ったか、, "
        "元に戻すと定員が予約数を下回る場合だ。"
    ),
)
def preview_batch(batch_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        plan = admin_revert_service.build_plan(db, batch_id)
    except admin_revert_service.RevertError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"success": True, "data": plan.as_dict()}


@router.post(
    "/batches/{batch_id}/revert",
    summary="一括保存を元に戻す",
    description=(
        "プレビューの計画を **ここで再計算して** 実行する。人が確認画面を"
        "見ている間に他のスタッフが同じ値を修正した可能性があり、その場合は"
        "元に戻さないのが正しい。\n\n"
        "**記録を削除しない。** 「元に戻す」は新規操作(`BATCH_REVERT`)として"
        "残り、元のログはそのまま残る。同じ保存を2回元に戻すことはできない。"
    ),
)
def revert_batch(
    batch_id: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_system_admin),
) -> dict:
    try:
        data = admin_revert_service.revert(
            db, batch_id, admin=admin, ip_address=client_ip(request)
        )
    except admin_revert_service.RevertError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    parts = []
    if data["reverted_count"]:
        parts.append(f"{data['reverted_count']}件を元に戻しました")
    if data["deleted_count"]:
        parts.append(f"新規作成された {data['deleted_count']}件を削除しました")
    if data["skipped_count"]:
        parts.append(f"{data['skipped_count']}件はスキップしました")

    return {
        "success": True,
        "data": data,
        "message": " · ".join(parts) + "。",
    }


@router.post(
    "/{log_id}/restore",
    summary="削除を元に戻す",
    description=(
        "削除の操作ログ（会場・オプション検査）1件から、削除前の内容で登録し直す。\n\n"
        "同じコードがすでにある場合、または復元済みの削除は409で拒否する。"
        "会場は、削除時に日程を記録していれば日程と定員も復元する。"
        "元に戻す操作は新規操作(`RECORD_RESTORE`)として残る。"
    ),
)
def restore_deleted(
    log_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_system_admin),
) -> dict:
    try:
        data = admin_revert_service.restore_deleted(
            db, log_id, admin=admin, ip_address=client_ip(request)
        )
    except admin_revert_service.RevertError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    message = f"{data['label']} を元に戻しました。"
    if data["schedules_restored"]:
        message += f"（開催日程 {data['schedules_restored']}件を含む）"
    return {"success": True, "data": data, "message": message}
