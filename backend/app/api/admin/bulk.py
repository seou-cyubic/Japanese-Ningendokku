"""관리 화면 API — 회장 정보 · 정원 일괄 관리 (A-24 분리).

예전에는 표가 하나였고 원본 CSV 모양 그대로였다. 그 표가 세 가지 일을
한꺼번에 하고 있었다 — 파일 가져오기, 회장 정보 고치기, 정원 고치기.

지금은 셋으로 나뉘어 있다.

    POST /hospitals/import        마스터 파일 가져오기 (`hospitals.py`)
    GET/POST /bulk/venues         회장 정보 — 한 행 = 회장 하나
    GET/POST /bulk/capacity       정원     — 한 행 = 회차 하나

가져오기는 **넣을 때 한 번**이고, 두 표는 **그 뒤로 계속**이다.
"""

from datetime import datetime
from urllib.parse import quote

from fastapi import (
    APIRouter, Body, Depends, File, HTTPException, Query, Request, Response, UploadFile
)
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import client_ip, require_business_admin
from app.models.admin import AdminUser
from app.schemas.bulk import (
    BulkErrorResponse,
    CapacityBulkRequest,
    CapacityBulkResponse,
    CapacityGridResponse,
    ExamOptionBulkRequest,
    ExamOptionBulkResponse,
    ExamOptionGridResponse,
    SheetExportRequest,
    SheetImportResponse,
    SheetImportResult,
    SheetImportSummary,
    VenueBulkRequest,
    VenueBulkResponse,
    VenueGridResponse,
)
from app.services import (
    admin_bulk_service,
    audit_service,
    capacity_sheet_service,
    exam_option_sheet_service,
    master_sheet_service,
    venue_sheet_service,
)
from app.services.admin_bulk_service import BulkDataError, BulkValidationError
from app.services.sheet_io import MAX_UPLOAD_BYTES, SheetError

router = APIRouter(
    prefix="/bulk",
    tags=["管理 - 一括管理"],
    dependencies=[Depends(require_business_admin)],
)


def _validation_response(exc: BulkValidationError) -> JSONResponse:
    """셀 단위 오류를 422 로 돌려준다.

    화면이 어느 셀을 붉게 칠할지 알아야 하므로, 상태 코드만으로는 부족하다.
    `errors[]` 의 `row_no` + `field` 가 셀 좌표다.
    """
    return JSONResponse(
        status_code=422,
        content=BulkErrorResponse(errors=exc.errors).model_dump(),
    )


# ==========================================================================
# 회장 정보
# ==========================================================================


@router.get(
    "/venues",
    response_model=VenueGridResponse,
    summary="会場情報表 — 現在のマスタ",
    description=(
        "現在登録されている全会場を表の行として返す。 **1行が会場 "
        "1つ**であり、開催日系の列はない。\n\n"
        "列定義(`columns`)も一緒に渡す。画面が列を書いておくとサーバーと"
        "画面の2箇所を直さなければならず、必ずどちらかを忘れる。"
    ),
)
def venue_grid(db: Session = Depends(get_db)) -> VenueGridResponse:
    return VenueGridResponse(data=admin_bulk_service.venue_grid(db))


@router.post(
    "/venues",
    response_model=VenueBulkResponse,
    summary="会場情報一括保存",
    description=(
        "**1つのセルでもエラーがあれば1件も保存しない。** 半分だけ"
        "反映されたマスタは何が入ったか誰もわからない状態になる。\n\n"
        "**表にない会場は削除しない。** 削除は会場管理画面でのみ"
        "する。\n\n"
        "開催回と定員は **手を付けない。** それは定員表の仕事だ。\n\n"
        "`dry_run=true` なら **何も保存せず** 何が変わるかだけを数えて"
        "返す — 新規・上書き・手を付けない件数とセル別の前/後。"
    ),
    responses={422: {"model": BulkErrorResponse, "description": "セル単位の検証失敗"}},
)
def save_venues(
    payload: VenueBulkRequest,
    request: Request,
    dry_run: bool = Query(False, description="保存せずに結果のみを計算する"),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_business_admin),
):
    try:
        data = admin_bulk_service.save_venues(
            db, payload, admin=admin, ip_address=client_ip(request), dry_run=dry_run
        )
    except BulkValidationError as exc:
        db.rollback()
        return _validation_response(exc)
    except BulkDataError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return VenueBulkResponse(data=data)


# ==========================================================================
# 정원
# ==========================================================================


@router.get(
    "/capacity",
    response_model=CapacityGridResponse,
    summary="定員表 — 開催回別時間帯定員",
    description=(
        "開催回全部を表の行として返す。 **1行が開催回1つ**であり、, "
        "会場情報はコードと名前だけ読み取り専用で付く。\n\n"
        "`hospital_id` を渡すとその会場の開催回だけ — 「会場Aの 8/28・8/29・ "
        "8/30 定員を見る」がこの画面が答えるべき最初の質問だ。\n\n"
        "`reserved` はセルに「3 / 22」と書くための読み取り専用値であり、, "
        "`closed` は締切済みの枠だ。"
    ),
)
def capacity_grid(
    hospital_id: int | None = Query(None, description="この会場の開催回だけ"),
    db: Session = Depends(get_db),
) -> CapacityGridResponse:
    return CapacityGridResponse(
        data=admin_bulk_service.capacity_grid(db, hospital_id)
    )


@router.post(
    "/capacity",
    response_model=CapacityBulkResponse,
    summary="定員一括保存",
    description=(
        "**空欄は「その時間帯を開けない」だ。** 0 とは違う — 0は枠は"
        "あるが定員がないことを意味し、画面には満員と表示される。\n\n"
        "**すでに予約された人数より少ない定員には引き下げられない** (BR-09). "
        "この画面は定員専用であるため、暗黙に引き上げたりせず、そのセルに理由を"
        "記載して返却する。\n\n"
        "**表にない開催回は削除しない。** 開催回の削除は会場管理画面でのみ"
        "行う — 予約が入っている開催回はそちらでも拒否される。\n\n"
        "`dry_run=true` の場合、 **何も保存せず** 何が変更されるかのみをカウントして"
        "返却する。特に **定員がなくなるセル**を保存前に警告として通知する。"
    ),
    responses={422: {"model": BulkErrorResponse, "description": "セル単位の検証失敗"}},
)
def save_capacity(
    payload: CapacityBulkRequest,
    request: Request,
    dry_run: bool = Query(False, description="保存せずに結果のみを計算する"),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_business_admin),
):
    try:
        data = admin_bulk_service.save_capacity(
            db, payload, admin=admin, ip_address=client_ip(request), dry_run=dry_run
        )
    except BulkValidationError as exc:
        db.rollback()
        return _validation_response(exc)
    except BulkDataError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return CapacityBulkResponse(data=data)


@router.post(
    "/capacity/closed",
    summary="時間枠の締切・解除",
    description=(
        "1つのセルを締め切るか解除する。定員とは **別個のステータス**であるため、保存エンドポイントも"
        "分けてある。\n\n"
        "締切を定員0で代用しない理由は、そうすると解除時に"
        "元の定員が失われるためである。"
    ),
)
def set_closed(
    request: Request,
    schedule_id: int = Body(..., embed=True),
    cell: str = Body(..., embed=True, description="例: 09:30~10:00"),
    closed: bool = Body(True, embed=True),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_business_admin),
) -> dict:
    try:
        data = admin_bulk_service.set_cell_closed(
            db, schedule_id, cell, closed,
            admin=admin, ip_address=client_ip(request),
        )
    except BulkDataError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {
        "success": True,
        "data": data,
        "message": "締め切りました。" if closed else "締切を解除しました。",
    }


# ==========================================================================
# 옵션 검사
# ==========================================================================


@router.get(
    "/exam-options",
    response_model=ExamOptionGridResponse,
    summary="オプション検査表 — 現在のマスタ",
    description=(
        "現在登録されているオプション検査すべてを表の行として返却する。 "
        "**1行が検査1件**である。\n\n"
        "`_used_count` はその検査を実際に申し込んだ予約件数である。読み取り専用であり、, "
        "**削除できるか**と「使用を無効にすると何が停止するか」がこの数値に"
        "かかっている。"
    ),
)
def exam_option_grid(db: Session = Depends(get_db)) -> ExamOptionGridResponse:
    return ExamOptionGridResponse(data=admin_bulk_service.exam_option_grid(db))


@router.post(
    "/exam-options",
    response_model=ExamOptionBulkResponse,
    summary="オプション検査一括保存",
    description=(
        "**1つのセルでもエラーがあれば1件も保存しない。**\n\n"
        "**表にない検査は削除しない。** 削除は表の行メニューからのみ行い、, "
        "申込済みの予約がある場合はそちらでも拒否される。\n\n"
        "`dry_run=true` の場合、 **何も保存せず** 何が変更されるかのみをカウントして"
        "返却する。保存前に「新規何件・上書き何件」を表示する"
        "ためのエンドポイントである。"
    ),
    responses={422: {"model": BulkErrorResponse, "description": "セル単位の検証失敗"}},
)
def save_exam_options(
    payload: ExamOptionBulkRequest,
    request: Request,
    dry_run: bool = Query(False, description="保存せずに結果のみを計算する"),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_business_admin),
):
    try:
        data = admin_bulk_service.save_exam_options(
            db, payload, admin=admin, ip_address=client_ip(request), dry_run=dry_run
        )
    except BulkValidationError as exc:
        db.rollback()
        return _validation_response(exc)
    except BulkDataError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return ExamOptionBulkResponse(data=data)


@router.delete(
    "/exam-options/{option_id}",
    summary="オプション検査削除",
    description=(
        "表では行えない処理のため個別に設けている。\n\n"
        "**すでに申込済みの予約がある場合は拒否する。** 削除してしまうとその予約者が"
        "何を申し込んだかが一覧から消えてしまう。新規申込のみを防ぎたい場合は"
        "表で「使用」をオフにするのが適切である。"
    ),
)
def delete_exam_option(
    option_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_business_admin),
) -> dict:
    from app.services.admin_master_service import MasterDataError, delete_exam_option

    try:
        message = delete_exam_option(
            db, option_id, admin=admin, ip_address=client_ip(request)
        )
    except MasterDataError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {"success": True, "data": {"id": option_id}, "message": message}


# ==========================================================================
# 파일 입출력 (CSV · Excel)
# ==========================================================================
#
# 표 셋이 같은 모양으로 파일을 주고받는다. 열 정의만 다르고, 인코딩 판정·
# 제목 줄 탐색·수식 인젝션 방어는 `sheet_io.SheetFormat` 한 곳에 있다.
#
# 내보내기가 POST 인 이유
# ----------------------
# **화면의 표를 그대로** 내보내기 때문이다. DB 를 다시 읽으면 「고치던 값을
# Excel 로 꺼내 마저 고친다」는 실제 사용법과 어긋난다. 그래서 검증도 하지
# 않는다 — 형식이 틀린 값을 꺼내려는 것이 이 버튼의 가장 흔한 쓰임이다.
#
# 가져오기는 **저장하지 않는다.** 표에 올려 두고, 사람이 확인한 뒤 저장을
# 누른다.


def _download_headers(file_name: str) -> dict[str, str]:
    """한글·일본어 파일 이름을 헤더에 담는다.

    Content-Disposition 은 ASCII 만 담을 수 있어, 비ASCII 이름은
    `filename*=UTF-8''…` 로 준다. 옛 브라우저를 위해 ASCII 대체 이름도 함께.
    """
    quoted = quote(file_name)
    return {
        "Content-Disposition": (
            f"attachment; filename=\"download.csv\"; filename*=UTF-8''{quoted}"
        )
    }


_SHEETS = {
    "venues": ("会場", venue_sheet_service),
    "capacity": ("定員", capacity_sheet_service),
    "exam-options": ("オプション検査", exam_option_sheet_service),
}


def _sheet_of(name: str):
    entry = _SHEETS.get(name)
    if entry is None:
        raise HTTPException(status_code=404, detail="不明な表です。")
    return entry


@router.post(
    "/{sheet}/export",
    summary="表書き出し (CSV / Excel)",
    description=(
        "画面の表をそのままファイルとして返す。 `sheet` は `venues` ・ "
        "`capacity` · `exam-options`.\n\n"
        "**検証しない** — 形式が不正な値もそのまま格納する。Excelで"
        "直して再度取り込むことがこの機能の主な用途であるためだ。\n\n"
        "Excel ファイルはすべてのセルを文字列書式で書き込み、会場コードの先頭の0や"
        "日付表記が開いたときに変わらないようにする。"
    ),
    response_class=Response,
)
def export_sheet(
    sheet: str,
    payload: SheetExportRequest,
    request: Request,
    file_format: str = Query(
        "csv", alias="format", pattern="^(csv|xlsx)$", description="csv / xlsx"
    ),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_business_admin),
) -> Response:
    if sheet in ("venues", "capacity"):
        label = "会場・定員"
        master_rows = master_sheet_service.build_master_rows(db, sheet, payload.rows)
        try:
            if file_format == "xlsx":
                content = master_sheet_service.build_xlsx(master_rows)
                media_type = (
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            else:
                content = master_sheet_service.build_csv(master_rows)
                media_type = "text/csv; charset=utf-8-sig"
        except SheetError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        file_name = master_sheet_service.export_file_name(file_format, datetime.now())
        rows_len = len(master_rows)
        audit_sample = master_rows[:50]
    else:
        label, service = _sheet_of(sheet)
        rows = service.normalize_export_rows(payload.rows)
        try:
            if file_format == "xlsx":
                content = service.build_xlsx(rows)
                media_type = (
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            else:
                content = service.build_csv(rows)
                media_type = "text/csv; charset=utf-8"
        except SheetError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        file_name = service.export_file_name(file_format, datetime.now())
        rows_len = len(rows)
        audit_sample = rows[:50]

    audit_service.write_log(
        db,
        admin=admin,
        action="BULK_SHEET_EXPORT",
        target_type=sheet,
        target_label=f"{label} 表 {rows_len}行 ({file_format.upper()})",
        after={"sheet": sheet, "format": file_format, "rows": rows_len, "data": audit_sample},
        ip_address=client_ip(request),
    )
    db.commit()

    return Response(
        content=content,
        media_type=media_type,
        headers=_download_headers(file_name),
    )


@router.post(
    "/{sheet}/import",
    response_model=SheetImportResponse,
    summary="表取り込み (CSV / Excel)",
    description=(
        "CSV(.csv) またはExcel(.xlsx)ファイルを画面の表に変換して返す。 "
        "**保存しない** — 人が表で確認して修正した後に保存を押して初めて"
        "反映される。\n\n"
        "見出し行は自動的に探す。元マスタの日本語列名"
        "(`会場名`・`開催日`・`予約終了` など)もそのまま紐づく。\n\n"
        "**列の順序ではなく見出しを見る。** そのため画面の列順を変更しても"
        "以前書き出したファイルをそのまま再度取り込むことができる。\n\n"
        "日本語Excelが保存したCP932、韓国語WindowsのCP949 CSVも読み込む。"
    ),
)
async def import_sheet(
    sheet: str,
    request: Request,
    file: UploadFile = File(..., description="CSV またはXLSXファイル"),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_business_admin),
) -> SheetImportResponse:
    label, service = _sheet_of(sheet)

    # 상한을 넘는 파일을 메모리에 다 올리지 않도록 읽으면서 끊는다.
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()

    try:
        parsed = service.parse_upload(file.filename or "", raw)
    except SheetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit_service.write_log(
        db,
        admin=admin,
        action="BULK_SHEET_IMPORT",
        target_type=sheet,
        target_label=f"{label} 表 {len(parsed.rows)}行 ({parsed.kind})",
        after={
            "sheet": sheet,
            "kind": parsed.kind,
            "rows": len(parsed.rows),
            "header_mode": parsed.header_mode,
            "encoding": parsed.encoding,
            "data": parsed.rows[:50],
        },
        ip_address=client_ip(request),
    )
    db.commit()

    return SheetImportResponse(
        data=SheetImportResult(
            rows=parsed.rows,
            summary=SheetImportSummary(
                file_name=file.filename or "",
                kind=parsed.kind,
                encoding=parsed.encoding,
                sheet_name=parsed.sheet_name,
                header_mode=parsed.header_mode,
                total_rows=len(parsed.rows),
                blank_rows=parsed.blank_rows,
                matched_columns=parsed.matched_columns,
                ignored_columns=parsed.ignored_columns,
                warnings=parsed.warnings,
            ),
        )
    )
