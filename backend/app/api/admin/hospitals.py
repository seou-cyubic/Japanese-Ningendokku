"""관리 화면 API — 회장 · 정원 관리 (A-20 ~ A-24).

L2(업무 관리자) 이상 전용이다.
화면에서 메뉴를 감추는 것만으로는 부족하다. 주소를 직접 치거나 API 를
직접 부르는 경로가 남으므로 여기서 한 번 더 막는다 (자체 피드백 M-9).
"""

from datetime import date, datetime
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import client_ip, require_business_admin
from app.models.admin import AdminUser
from app.schemas.admin import (
    CapacityResponse,
    HospitalBulkErrorResponse,
    HospitalBulkRequest,
    HospitalBulkResponse,
    HospitalListResponse,
    HospitalSaveRequest,
    HospitalSheetExportRequest,
    HospitalSheetImportResponse,
    HospitalSheetImportResult,
    Ok,
    PostalSheetImportSummary,
    ScheduleInput,
    SlotUpdateRequest,
    ReservationImpactResponse,
    SlotUpdateResponse,
)
from app.services import admin_master_service, audit_service, hospital_sheet_service
from app.services.admin_master_service import (
    HospitalBulkValidationError,
    MasterDataError,
)
from app.services.hospital_sheet_service import HospitalSheetError

router = APIRouter(
    prefix="/hospitals",
    tags=["管理 - 会場・定員"],
    dependencies=[Depends(require_business_admin)],
)


@router.get("", response_model=HospitalListResponse, summary="会場一覧")
def list_hospitals(db: Session = Depends(get_db)) -> HospitalListResponse:
    return HospitalListResponse(data=admin_master_service.list_hospitals(db))


# --------------------------------------------------------------------------
# A-24 회장 일괄 관리 (스프레드시트)
# --------------------------------------------------------------------------
# `/{hospital_id}` 보다 **먼저** 선언한다. 뒤에 두면 `/bulk` 가 회장 id 로
# 해석되어 422 가 난다.


def _download_headers(file_name: str) -> dict[str, str]:
    """한글 파일 이름을 그대로 쓰기 위한 Content-Disposition.

    헤더는 ASCII 만 담을 수 있으므로 RFC 5987 의 `filename*` 로 UTF-8 이름을
    주고, 이를 모르는 오래된 브라우저를 위해 ASCII 이름을 함께 남긴다.
    """
    ascii_name = "hospital-master." + file_name.rsplit(".", 1)[-1]
    return {
        "Content-Disposition": (
            f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(file_name)}"
        ),
        "Cache-Control": "no-store",
    }


@router.get(
    "/bulk",
    summary="会場一括管理表 — 現在のマスタ",
    description=(
        "現在登録されている会場の全件を表の行として返す。画面が開いてすぐにこの"
        "内容を表に表示し、人がセルを修正して「マスタ適用」を押す。\n\n"
        "値はすべて文字列である。表のセルにそのまま入る値であるため、"
        "日付は `YYYY-MM-DD`, 時刻は `HH:MM`, 真/偽は「はい」/「いいえ」だ。"
    ),
)
def hospital_bulk_rows(db: Session = Depends(get_db)) -> dict:
    return {"success": True, "data": {"rows": admin_master_service.hospital_bulk_rows(db)}}


@router.post(
    "/bulk",
    response_model=HospitalBulkResponse,
    summary="会場一括保存",
    description=(
        "表の行を最大200件まで受け取り、会場マスターに反映する。会場コードで"
        "既存の会場を探し、ないコードは新規登録する。\n\n"
        "**全行を先に検証し、1セルでもエラーがあれば1件も"
        "保存しない。** 半分だけ反映されたマスタは何が入ったか誰も"
        "分からない状態になる。\n\n"
        "**表にない会場は削除しない。** 削除は会場管理画面からのみ行う。"
    ),
    responses={
        422: {
            "model": HospitalBulkErrorResponse,
            "description": "行・セル単位の一括検証失敗",
        }
    },
)
def save_hospital_bulk(
    payload: HospitalBulkRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_business_admin),
) -> HospitalBulkResponse | JSONResponse:
    try:
        data = admin_master_service.save_hospitals_bulk(
            db, payload, admin=admin, ip_address=client_ip(request)
        )
    except HospitalBulkValidationError as exc:
        # 전역 HTTPException 처리기는 detail 을 문자열로 바꾸므로, 표가
        # row_no/field 를 그대로 쓸 수 있게 이 응답은 직접 구성한다.
        db.rollback()
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error": {
                    "code": "BULK_VALIDATION_FAILED",
                    "message": "入力内容をご確認ください。",
                },
                "errors": [error.model_dump(mode="json") for error in exc.errors],
            },
        )
    except MasterDataError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return HospitalBulkResponse(data=data)


@router.post(
    "/bulk/export",
    summary="会場マスター表書き出し (CSV / Excel)",
    description=(
        "画面の表をそのままファイルとして返す。 **検証しない** — 形式が"
        "間違った値もそのまま含める。Excelで修正して再度取り込むことがこの"
        "機能の主な使い方であるためだ。\n\n"
        "Excel ファイルはすべてのセルを文字列書式で書き込み、会場コードの先頭の0や"
        "日付表記が開いたときに変わらないようにする。"
    ),
    response_class=Response,
)
def export_hospital_sheet(
    payload: HospitalSheetExportRequest,
    request: Request,
    file_format: str = Query(
        "csv", alias="format", pattern="^(csv|xlsx)$", description="csv / xlsx"
    ),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_business_admin),
) -> Response:
    rows = hospital_sheet_service.normalize_export_rows(payload.rows)

    try:
        if file_format == "xlsx":
            content = hospital_sheet_service.build_xlsx(rows)
            media_type = (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            content = hospital_sheet_service.build_csv(rows)
            media_type = "text/csv; charset=utf-8"
    except HospitalSheetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit_service.write_log(
        db,
        admin=admin,
        action="HOSPITAL_BULK_EXPORT",
        target_type="hospital",
        target_label=f"会場マスター表 {len(rows)}行 ({file_format.upper()})",
        after={"format": file_format, "rows": len(rows)},
        ip_address=client_ip(request),
    )
    db.commit()

    return Response(
        content=content,
        media_type=media_type,
        headers=_download_headers(
            hospital_sheet_service.export_file_name(file_format, datetime.now())
        ),
    )


@router.post(
    "/bulk/import",
    response_model=HospitalSheetImportResponse,
    summary="会場マスター表取り込み (CSV / Excel)",
    description=(
        "CSV(.csv) またはExcel(.xlsx)ファイルを画面の表に変換して返す。 "
        "**保存しない** — 人が表で確認して修正した後に"
        "「マスタ適用」を押して初めて反映される。\n\n"
        "見出し行は自動で探す。元の会場マスターの日本語列名"
        "(`会場名`・`開催日`・`予約終了` など)もそのままマッチするため、担当者が受け取った"
        "ファイルを修正せずにアップロードできる。\n\n"
        "日本語Excelが保存したCP932、韓国語WindowsのCP949 CSVも読み込む。"
    ),
)
async def import_hospital_sheet(
    request: Request,
    file: UploadFile = File(..., description="CSV またはXLSXファイル"),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_business_admin),
) -> HospitalSheetImportResponse:
    from app.services.sheet_io import MAX_UPLOAD_BYTES

    # 상한을 넘는 파일을 메모리에 다 올리지 않도록 읽으면서 끊는다.
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()

    try:
        parsed = hospital_sheet_service.parse_upload(file.filename or "", raw)
    except HospitalSheetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit_service.write_log(
        db,
        admin=admin,
        action="HOSPITAL_BULK_IMPORT",
        target_type="hospital",
        target_label=f"会場マスター表 {len(parsed.rows)}行 ({parsed.kind})",
        after={
            "kind": parsed.kind,
            "rows": len(parsed.rows),
            "header_mode": parsed.header_mode,
            "encoding": parsed.encoding,
            "sheet": parsed.sheet_name,
        },
        ip_address=client_ip(request),
    )
    db.commit()

    return HospitalSheetImportResponse(
        data=HospitalSheetImportResult(
            rows=parsed.rows,
            summary=PostalSheetImportSummary(
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


@router.post("", summary="会場登録")
def create_hospital(
    payload: HospitalSaveRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_business_admin),
) -> dict:
    try:
        data = admin_master_service.save_hospital(
            db, None, payload, admin=admin, ip_address=client_ip(request)
        )
    except MasterDataError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {"success": True, "data": data, "message": "会場を登録しました。"}


@router.put("/{hospital_id}", summary="会場修正")
def update_hospital(
    hospital_id: int,
    payload: HospitalSaveRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_business_admin),
) -> dict:
    try:
        data = admin_master_service.save_hospital(
            db, hospital_id, payload, admin=admin, ip_address=client_ip(request)
        )
    except MasterDataError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {"success": True, "data": data, "message": "会場情報を保存しました。"}


@router.delete(
    "/{hospital_id}",
    response_model=Ok,
    summary="会場削除",
    description=(
        "今後の予約が残っていれば削除できない。"
        "予約画面で隠すには「予約画面表示」をオフにすればよい。"
    ),
)
def delete_hospital(
    hospital_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_business_admin),
) -> Ok:
    try:
        message = admin_master_service.delete_hospital(
            db, hospital_id, admin=admin, ip_address=client_ip(request)
        )
    except MasterDataError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return Ok(message=message)


# --------------------------------------------------------------------------
# 개최 회차
# --------------------------------------------------------------------------
# 회장 저장(`PUT /{id}`)으로도 회차를 함께 보낼 수 있지만, 회차만 손보는
# 길을 따로 둔다. 「10월 회차 하나를 추가한다」에 회장 정보 전체를 실어
# 보내게 하면, 그 사이 다른 사람이 고친 주소를 화면이 들고 있던 옛 값으로
# 되돌려 버린다.


@router.get(
    "/{hospital_id}/schedules",
    summary="開催回一覧",
    description="会場が開く日すべて。過去の開催回も含む。",
)
def list_schedules(hospital_id: int, db: Session = Depends(get_db)) -> dict:
    try:
        data = admin_master_service.list_schedules(db, hospital_id)
    except MasterDataError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {"success": True, "data": data}


@router.put(
    "/{hospital_id}/schedules",
    summary="開催回保存（一覧全体）",
    description=(
        "送信した一覧がその会場の開催回の **すべて**となる。一覧にない開催回は"
        "削除する。\n\n"
        "**予約が入っている開催回は削除せず拒否する。** 削除するとその日に予約した"
        "人たちの受診日がどこから来たのか説明できなくなる。画面で"
        "隠すにはその開催回の「表示」をオフにすればよい。"
    ),
)
def save_schedules(
    hospital_id: int,
    request: Request,
    schedules: list[ScheduleInput] = Body(..., embed=True),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_business_admin),
) -> dict:
    try:
        data = admin_master_service.save_schedules(
            db, hospital_id, schedules, admin=admin, ip_address=client_ip(request)
        )
    except MasterDataError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {"success": True, "data": data, "message": "開催回を保存しました。"}


@router.get(
    "/{hospital_id}/capacity",
    response_model=CapacityResponse,
    summary="定員管理カレンダー (A-22)",
    description=(
        "1か月分の日付別定員状況と、選択した日付の30分単位のタイムテーブルを返す。\n\n"
        "20個の会場 × 365日 × 12スロットを1つずつ操作することは不可能なため、, "
        "カレンダーで日付を複数選んで一度に調整するフローを前提とする。"
    ),
)
def capacity(
    hospital_id: int,
    month: str | None = Query(None, description="YYYY-MM"),
    target_date: date | None = Query(None, alias="date"),
    db: Session = Depends(get_db),
) -> CapacityResponse:
    try:
        data = admin_master_service.capacity_month(db, hospital_id, month, target_date)
    except MasterDataError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return CapacityResponse(data=data)


@router.put(
    "/{hospital_id}/capacity",
    response_model=SlotUpdateResponse,
    summary="定員変更（個別・一括）",
    description=(
        "`items` でスロットを個別指定するか、, `dates` + `delta` / `set_closed` で"
        "日付単位の一括調整を行う。\n\n"
        "**すでに予約された人数より低い定員には下げられない。** "
        "拒否された項目は理由とともに `blocked` で返す。"
    ),
)
def update_capacity(
    hospital_id: int,
    payload: SlotUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_business_admin),
) -> SlotUpdateResponse:
    try:
        data = admin_master_service.update_slots(
            db, hospital_id, payload, admin=admin, ip_address=client_ip(request)
        )
    except MasterDataError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return SlotUpdateResponse(data=data)


@router.get(
    "/{hospital_id}/reservation-impact",
    response_model=ReservationImpactResponse,
    summary="その日付の予約件数",
    description=(
        "休診で締め切る **前に** 事前に確認する場だ。"
        "スロットを締め切っても予約は削除されない。その人たちはその日そのまま"
        "会場に来る。確認ダイアログが3件と128件を同じ文言で尋ねると"
        "担当者が規模を知らないまま押すことになる。"
        "メールアドレスが空の人は電話以外に連絡手段がなく、別途数える。"
    ),
)
def get_reservation_impact(
    hospital_id: int,
    dates: list[date] = Query(..., description="YYYY-MM-DD. 複数の場合は繰り返し渡す"),
    db: Session = Depends(get_db),
) -> ReservationImpactResponse:
    return ReservationImpactResponse(
        data=admin_master_service.reservation_impact(db, hospital_id, dates)
    )


@router.post(
    "/{hospital_id}/holidays",
    response_model=SlotUpdateResponse,
    summary="休診日設定・解除",
    description=(
        "指定した日付の全スロットを締切（または解除）する。\n\n"
        "休診日を別テーブルに置かない理由は、同じ事実が2か所に書かれると"
        "「カレンダーでは休診なのに予約ができる」となるためだ。"
    ),
)
def set_holidays(
    hospital_id: int,
    request: Request,
    dates: list[date] = Body(..., embed=True),
    closed: bool = Body(True, embed=True),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_business_admin),
) -> SlotUpdateResponse:
    try:
        data = admin_master_service.set_holiday(
            db, hospital_id, dates, closed, admin=admin, ip_address=client_ip(request)
        )
    except MasterDataError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return SlotUpdateResponse(data=data)
