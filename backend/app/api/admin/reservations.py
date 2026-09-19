"""관리 화면 API — 예약 검색 · 상세 · 수정 · 취소 · 우편 접수 (A-10 ~ A-13).

전부 L1(일반 스태프) 이상이면 사용할 수 있다.
「예약 정보의 수정과 취소」가 L1 의 업무이기 때문이다 (plan.md §5.2).
"""

from datetime import date, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import client_ip, require_staff
from app.models.admin import AdminUser
from app.schemas.admin import (
    ContactCreateRequest,
    MailResendResponse,
    Ok,
    PostalBulkErrorResponse,
    PostalBulkRequest,
    PostalBulkResponse,
    PostalReservationRequest,
    PostalReservationResponse,
    PostalSheetExportRequest,
    PostalSheetImportResponse,
    PostalSheetImportResult,
    PostalSheetImportSummary,
    ReservationCancelRequest,
    ReservationDetailResponse,
    ReservationSearchResponse,
    ReservationUpdateRequest,
)
from app.services import (
    admin_master_service,
    admin_reservation_service,
    audit_service,
    postal_sheet_service,
)
from app.services.admin_reservation_service import (
    AdminReservationError,
    PostalBulkValidationError,
)
from app.services.postal_sheet_service import PostalSheetError

router = APIRouter(prefix="/reservations", tags=["管理 - 予約"])


def _fail(exc: Exception) -> HTTPException:
    """업무상 거절은 409. 「입력이 틀렸다」가 아니라 「지금은 안 된다」이다."""
    return HTTPException(status_code=409, detail=str(exc))


@router.get(
    "",
    response_model=ReservationSearchResponse,
    summary="予約検索",
    description=(
        "キーワード1枠で予約番号・氏名・フリガナ・電話番号・メールアドレスをすべて検索する。\n\n"
        "電話応対中に「どの欄に入れるべきか」を悩ませないための設計だ。"
        "電話番号はハイフンを抜いて数字だけ入れても探せる。\n\n"
        "`option_id` は「このオプション検査を申し込んだ予約のみ」である。管理画面の"
        "「オプション検査管理」で申込件数をダブルクリックすると、この条件が掛かったまま"
        "遷移してくる。ステータスで絞らないためキャンセルされた予約も一緒に出る — その検査を"
        "申し込んでいたことは事実であり、オプション検査管理の件数も同じ軸で数える。"
    ),
    dependencies=[Depends(require_staff)],
)
def search(
    keyword: str = Query("", description="予約番号・氏名・電話番号・メールアドレス"),
    status: str = Query("", description="CONFIRMED / PENDING / CANCELLED / HOLIDAY(休診日)"),
    channel: str = Query("", description="WEB / POSTAL"),
    hospital_id: int | None = Query(None),
    option_id: int | None = Query(None, description="このオプション検査を申し込んだ予約のみ"),
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    defect_only: bool = Query(False, alias="defect"),
    created_date: date | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(30, ge=1, le=200),
    db: Session = Depends(get_db),
) -> ReservationSearchResponse:
    return ReservationSearchResponse(
        data=admin_reservation_service.search(
            db,
            keyword=keyword,
            status=status,
            channel=channel,
            hospital_id=hospital_id,
            date_from=date_from,
            date_to=date_to,
            defect_only=defect_only,
            option_id=option_id,
            created_date=created_date,
            page=page,
            size=size,
        )
    )


@router.get(
    "/export-csv",
    summary="予約検索結果 CSV / Excel書き出し",
    description="現在の検索条件に合致するすべての予約一覧をCSVまたはExcelファイルでダウンロードします。",
    dependencies=[Depends(require_staff)],
)
def export_reservations_csv(
    keyword: str = Query("", description="予約番号・氏名・電話番号・メールアドレス"),
    status: str = Query("", description="CONFIRMED / PENDING / CANCELLED / HOLIDAY(休診日)"),
    channel: str = Query("", description="WEB / POSTAL"),
    hospital_id: int | None = Query(None),
    option_id: int | None = Query(None, description="このオプション検査を申し込んだ予約のみ"),
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    defect_only: bool = Query(False, alias="defect"),
    created_date: date | None = Query(None),
    format: str = Query("csv", alias="format", pattern="^(csv|xlsx)$"),
    db: Session = Depends(get_db),
):
    filename, file_bytes, media_type = admin_reservation_service.export_file(
        db,
        keyword=keyword,
        status=status,
        channel=channel,
        hospital_id=hospital_id,
        date_from=date_from,
        date_to=date_to,
        defect_only=defect_only,
        option_id=option_id,
        created_date=created_date,
        fmt=format,
    )
    return Response(
        content=file_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/filters",
    summary="検索条件の選択肢",
    description="会場一覧など検索画面が必要とする選択肢を一度に与える。",
    dependencies=[Depends(require_staff)],
)
def filters(db: Session = Depends(get_db)) -> dict:
    return {
        "success": True,
        "data": {
            "hospitals": admin_master_service.hospital_choices(db),
            "statuses": [
                {"value": "CONFIRMED", "label": "予約確定"},
                {"value": "PENDING", "label": "仮受付（要確認）"},
                {"value": "CANCELLED_PRIOR", "label": "事前キャンセル"},
                {"value": "CANCELLED_NOSHOW", "label": "当日キャンセル"},
                {"value": "HOLIDAY", "label": "日程変更要（要連絡）"},
            ],
            "channels": [
                {"value": "WEB", "label": "WEB"},
                {"value": "POSTAL", "label": "郵送"},
            ],
            "exam_options": [
                {"id": o.id, "code": o.code, "name": o.name, "is_active": o.is_active}
                for o in admin_master_service.list_exam_options(db)
            ],
        },
    }


@router.get(
    "/slots",
    summary="選択可能な受診日時",
    description=(
        "日時変更（A-11）と郵送受付（A-13）で使用する。\n\n"
        "満員・締切・過去の時間も一覧から隠さず、理由を付けて返す。"
        "消えるとスタッフが「申込書に記載された時間がない」と迷うからだ。"
    ),
    dependencies=[Depends(require_staff)],
)
def slots(
    hospital_id: int = Query(...),
    target_date: date = Query(..., alias="date"),
    db: Session = Depends(get_db),
) -> dict:
    return {
        "success": True,
        "data": admin_master_service.available_slots(db, hospital_id, target_date),
    }


@router.post(
    "/postal",
    response_model=PostalReservationResponse,
    summary="郵送受付入力（A-13）",
    description=(
        "紙の申込書をスタッフが代理登録する。\n\n"
        "希望日時を順番に複数受け取り、第1希望が満員なら第2・第3希望へ"
        "自動的に繰り下がる。郵送だからといって定員超過を許容することはない。\n\n"
        "必須項目が空の場合は基本的に拒否するが、, `allow_defect=true` で"
        "仮受付（PENDING）として登録できる。後から電話で埋める。"
    ),
    dependencies=[Depends(require_staff)],
)
def create_postal(
    payload: PostalReservationRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_staff),
) -> PostalReservationResponse:
    try:
        data = admin_reservation_service.create_postal(
            db, payload, admin=admin, ip_address=client_ip(request)
        )
    except AdminReservationError as exc:
        db.rollback()
        raise _fail(exc) from exc

    return PostalReservationResponse(data=data)


@router.post(
    "/postal/bulk",
    response_model=PostalBulkResponse,
    summary="郵送受付一括入力",
    description=(
        "スプレッドシートグリッドの行を最大200行まで受け取り、完全な空行は無視する。"
        "会場はコードまたは正確な会場名、オプションはコードで受け取る。すべての行を先に"
        "検証し、1セルでもエラーがあれば予約を1件も保存しない。"
    ),
    dependencies=[Depends(require_staff)],
    responses={
        422: {
            "model": PostalBulkErrorResponse,
            "description": "行・セル単位の一括検証失敗",
        }
    },
)
def create_postal_bulk(
    payload: PostalBulkRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_staff),
) -> PostalBulkResponse | JSONResponse:
    try:
        data = admin_reservation_service.create_postal_bulk(
            db,
            payload,
            admin=admin,
            ip_address=client_ip(request),
        )
    except PostalBulkValidationError as exc:
        # 전역 HTTPException 처리기는 detail 을 문자열로 바꾸므로, 그리드가
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

    return PostalBulkResponse(data=data)


def _download_headers(file_name: str) -> dict[str, str]:
    """한글 파일 이름을 그대로 쓰기 위한 Content-Disposition.

    헤더는 ASCII 만 담을 수 있으므로 RFC 5987 의 `filename*` 로 UTF-8 이름을
    주고, 이를 모르는 오래된 브라우저를 위해 ASCII 이름을 함께 남긴다.

    `no-store` 는 개인정보가 담긴 파일이기 때문이다. 프록시·브라우저 캐시에
    남으면 다음 사람이 뒤로 가기로 같은 파일을 열 수 있다.
    """
    ascii_name = "postal-bulk." + file_name.rsplit(".", 1)[-1]
    return {
        "Content-Disposition": (
            f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(file_name)}"
        ),
        "Cache-Control": "no-store",
    }


@router.post(
    "/postal/bulk/export",
    summary="一括入力表書き出し（CSV / Excel）",
    description=(
        "画面の表をそのままファイルとして返す。 **検証しない** — "
        "形式が間違っている値もそのまま含める。Excel で修正して再度取り込むのが"
        "この機能の主な使い方だからだ。\n\n"
        "行を空にして送ると、見出し行だけがある **空の書式**になる。 "
        "Excel ファイルはすべてのセルを文字列書式で書き出し、郵便番号の先頭の 0 や"
        "日付表記が開いたときに変わらないようにする。"
    ),
    dependencies=[Depends(require_staff)],
    response_class=Response,
    responses={
        200: {
            "content": {
                "text/csv": {},
                (
                    "application/vnd.openxmlformats-officedocument"
                    ".spreadsheetml.sheet"
                ): {},
            },
            "description": "表ファイル",
        }
    },
)
def export_postal_bulk_sheet(
    payload: PostalSheetExportRequest,
    request: Request,
    file_format: str = Query(
        "csv", alias="format", pattern="^(csv|xlsx)$", description="csv / xlsx"
    ),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_staff),
) -> Response:
    rows = postal_sheet_service.normalize_export_rows(payload.rows)

    try:
        if file_format == "xlsx":
            content = postal_sheet_service.build_xlsx(rows)
            media_type = (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            content = postal_sheet_service.build_csv(rows)
            media_type = "text/csv; charset=utf-8"
    except PostalSheetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 개인정보가 담긴 파일이 시스템 밖으로 나가는 순간이므로 이력을 남긴다
    # (plan.md §13.4). 내용은 남기지 않는다 — 건수만으로 충분하다.
    audit_service.write_log(
        db,
        admin=admin,
        action="POSTAL_BULK_EXPORT",
        target_type="reservation",
        target_label=f"郵送一括入力表 {len(rows)}行 ({file_format.upper()})",
        after={"format": file_format, "rows": len(rows)},
        ip_address=client_ip(request),
    )
    db.commit()

    return Response(
        content=content,
        media_type=media_type,
        headers=_download_headers(
            postal_sheet_service.export_file_name(file_format, datetime.now())
        ),
    )


@router.post(
    "/postal/bulk/import",
    response_model=PostalSheetImportResponse,
    summary="一括入力表の取り込み (CSV / Excel)",
    description=(
        "CSV(.csv) またはExcel(.xlsx)ファイルを画面の表に変換して返します。 "
        "**保存しません** — 人が表で確認して修正した後に"
        "「予約を適用する」を押して初めて予約が作成されます。\n\n"
        "ヘッダー行は自動で検出します。会場が使用する別名(`生年月日`, "
        "`birth_date` など)も既知の表記であれば自動でマッピングされます。列名を全く"
        "検出できない場合は、列数がフォーマットと完全に一致する場合にのみ順番通りに"
        "取り込みます — 憶測でマッピングすると、姓と名が入れ替わった予約が気付かないうちに"
        "作成されてしまいます。\n\n"
        "日本語Excelが保存したCP932、韓国語WindowsのCP949 CSVも読み込みます。"
    ),
    dependencies=[Depends(require_staff)],
)
async def import_postal_bulk_sheet(
    request: Request,
    file: UploadFile = File(..., description="CSV またはXLSXファイル"),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_staff),
) -> PostalSheetImportResponse:
    # 상한을 넘는 파일을 메모리에 다 올리지 않도록 읽으면서 끊는다.
    raw = await file.read(postal_sheet_service.MAX_UPLOAD_BYTES + 1)
    await file.close()

    try:
        parsed = postal_sheet_service.parse_upload(file.filename or "", raw)
    except PostalSheetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit_service.write_log(
        db,
        admin=admin,
        action="POSTAL_BULK_IMPORT",
        target_type="reservation",
        target_label=f"郵送一括入力表 {len(parsed.rows)}行 ({parsed.kind})",
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

    return PostalSheetImportResponse(
        data=PostalSheetImportResult(
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


@router.get(
    "/{reservation_id}",
    response_model=ReservationDetailResponse,
    summary="予約詳細",
    dependencies=[Depends(require_staff)],
)
def detail(
    reservation_id: int, db: Session = Depends(get_db)
) -> ReservationDetailResponse:
    try:
        reservation = admin_reservation_service.get(db, reservation_id)
    except AdminReservationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return ReservationDetailResponse(
        data=admin_reservation_service.to_detail(db, reservation)
    )


@router.put(
    "/{reservation_id}",
    summary="予約修正",
    description=(
        "住所・連絡先・オプション・メモ・ステータスを修正する。受診日時も変更できる。\n\n"
        "氏名・生年月日・保険証は修正できない。本人確認の根拠であり、"
        "修正が必要な状況であれば、それは別人の予約である。"
    ),
    dependencies=[Depends(require_staff)],
)
def update(
    reservation_id: int,
    payload: ReservationUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_staff),
) -> dict:
    try:
        data, message = admin_reservation_service.update(
            db, reservation_id, payload, admin=admin, ip_address=client_ip(request)
        )
    except AdminReservationError as exc:
        db.rollback()
        raise _fail(exc) from exc

    return {"success": True, "data": data, "message": message}


@router.post(
    "/{reservation_id}/cancel",
    summary="予約キャンセル (A-12)",
    description=(
        "キャンセル後直ちに定員を元に戻し、その枠を再度受付可能にする (BR-10)。\n\n"
        "予約レコードは削除しない。「キャンセルした」という事実がお問い合わせ対応に必要である。"
    ),
    dependencies=[Depends(require_staff)],
)
def cancel(
    reservation_id: int,
    payload: ReservationCancelRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_staff),
) -> dict:
    try:
        data, message = admin_reservation_service.cancel(
            db,
            reservation_id,
            payload.reason,
            cancel_type=payload.cancel_type,
            admin=admin,
            ip_address=client_ip(request),
        )
    except AdminReservationError as exc:
        db.rollback()
        raise _fail(exc) from exc

    return {"success": True, "data": data, "message": message}


@router.post(
    "/{reservation_id}/contacts",
    summary="連絡履歴追加",
    description=(
        "不備確認の電話・メールを記録する。\n\n"
        "3回連絡してもつながらない場合は予約をキャンセルすることになっているため(BR-06), "
        "累積回数も併せて返却する。"
    ),
    dependencies=[Depends(require_staff)],
)
def add_contact(
    reservation_id: int,
    payload: ContactCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_staff),
) -> dict:
    try:
        data, message = admin_reservation_service.add_contact(
            db, reservation_id, payload, admin=admin, ip_address=client_ip(request)
        )
    except AdminReservationError as exc:
        db.rollback()
        raise _fail(exc) from exc

    return {"success": True, "data": data, "message": message}


@router.post(
    "/{reservation_id}/resend-mail",
    response_model=MailResendResponse,
    summary="確認メール再送信",
    description="「メールが届かない」というお問い合わせの標準対応。",
    dependencies=[Depends(require_staff)],
)
def resend_mail(
    reservation_id: int,
    request: Request,
    template_key: str = Query("RESERVE_COMPLETE"),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_staff),
) -> MailResendResponse:
    try:
        delivered, message = admin_reservation_service.resend_mail(
            db, reservation_id, template_key, admin=admin, ip_address=client_ip(request)
        )
    except AdminReservationError as exc:
        db.rollback()
        raise _fail(exc) from exc

    return MailResendResponse(message=message, delivered=delivered)
