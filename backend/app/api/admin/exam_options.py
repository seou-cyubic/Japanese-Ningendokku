"""관리 화면 API — 옵션 검사 관리 (A-30).

L2(업무 관리자) 이상 전용.
타깃 조건(성별·연령)을 여기서 바꾸면 이용자 폼의 선택지가 즉시 달라진다 (BR-13).
"""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, File
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import client_ip, require_business_admin
from app.models.admin import AdminUser
from app.schemas.admin import (
    ExamOptionListResponse,
    ExamOptionSaveRequest,
    Ok,
)
from app.services import admin_master_service
from app.services.admin_master_service import MasterDataError

router = APIRouter(
    prefix="/exam-options",
    tags=["管理 - オプション検査"],
    dependencies=[Depends(require_business_admin)],
)


@router.get(
    "",
    response_model=ExamOptionListResponse,
    summary="オプション検査一覧",
    description="各検査を実際に申し込んだ予約件数(`used_count`)を併せて返す。",
)
def list_options(db: Session = Depends(get_db)) -> ExamOptionListResponse:
    return ExamOptionListResponse(data=admin_master_service.list_exam_options(db))


@router.get(
    "/export",
    summary="オプション検査CSV書き出し",
    description="すべてのオプション検査をCSV（BOM付きUTF-8）でダウンロードする。",
)
def export_options(db: Session = Depends(get_db)) -> Response:
    csv_bytes = admin_master_service.export_exam_options(db)
    filename = f"exam_options_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/import",
    summary="オプション検査CSV取り込み",
    description="アップロードされたCSVをパースし、既存コードは修正、存在しないコードは新規追加する。",
)
async def import_options(
    request: Request,
    file: UploadFile = File(...),
    dry_run: bool = False,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_business_admin),
) -> dict:
    raw_csv = await file.read()
    try:
        result = admin_master_service.import_exam_options(
            db, raw_csv, admin=admin, ip_address=client_ip(request), dry_run=dry_run
        )
    except MasterDataError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if dry_run:
        message = "プレビューデータを読み込みました。"
    else:
        message = f"{result['created']}件追加、{result['updated']}件修正されました。"

    return {
        "success": True,
        "message": message,
        "data": result,
    }


@router.post("", summary="オプション検査登録")
def create_option(
    payload: ExamOptionSaveRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_business_admin),
) -> dict:
    try:
        data = admin_master_service.save_exam_option(
            db, None, payload, admin=admin, ip_address=client_ip(request)
        )
    except MasterDataError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {"success": True, "data": data, "message": "オプション検査を登録しました。"}


@router.put("/{option_id}", summary="オプション検査修正")
def update_option(
    option_id: int,
    payload: ExamOptionSaveRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_business_admin),
) -> dict:
    try:
        data = admin_master_service.save_exam_option(
            db, option_id, payload, admin=admin, ip_address=client_ip(request)
        )
    except MasterDataError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {"success": True, "data": data, "message": "オプション検査を保存しました。"}


@router.delete(
    "/{option_id}",
    response_model=Ok,
    summary="オプション検査削除",
    description=(
        "すでに申し込まれた予約がある場合は削除できない。"
        "新規申し込みのみを防ぐには「使用する」をオフにすればよい。"
    ),
)
def delete_option(
    option_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_business_admin),
) -> Ok:
    try:
        message = admin_master_service.delete_exam_option(
            db, option_id, admin=admin, ip_address=client_ip(request)
        )
    except MasterDataError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return Ok(message=message)
