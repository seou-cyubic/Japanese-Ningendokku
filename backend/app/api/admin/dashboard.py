from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_staff
from app.schemas.admin import DashboardResponse
from app.services import admin_dashboard_service

router = APIRouter(tags=["管理 - ダッシュボード"], dependencies=[Depends(require_staff)])


@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    summary="本日のタスクおよび健診統計",
    description=(
        "対応が必要な予約、本日の健診状況、直近の受付、メール送信失敗および"
        "性別・年齢別・受付経路・オプション検査の統計をまとめて返す。"
    ),
)
def dashboard(
    hospital_id: int | None = Query(None, description="会場IDフィルター (任意)"),
    year: int | None = Query(None, description="年フィルター (任意)"),
    month: int | None = Query(None, description="月フィルター (任意)"),
    date: str | None = Query(None, description="日付フィルター YYYY-MM-DD (任意)"),
    week_start: str | None = Query(None, description="週開始日 YYYY-MM-DD (任意)"),
    week_end: str | None = Query(None, description="週終了日 YYYY-MM-DD (任意)"),
    db: Session = Depends(get_db),
) -> DashboardResponse:
    return DashboardResponse(
        data=admin_dashboard_service.build(
            db,
            hospital_id=hospital_id,
            year=year,
            month=month,
            date_str=date,
            week_start=week_start,
            week_end=week_end,
        )
    )


@router.get(
    "/dashboard/attention-count",
    summary="対応が必要な予約件数（リアルタイムバッジ用）",
    description="ナビゲーションバーの要対応バッジをリアルタイムに更新するための軽量エンドポイント",
)
def attention_count(db: Session = Depends(get_db)):
    return {"data": {"count": admin_dashboard_service.get_attention_count(db)}}


@router.get(
    "/dashboard/export-csv",
    summary="ダッシュボード統計 CSV / Excel 書き出し",
    description="健診統計タブで選んだ会場・期間の統計を、表を2段に並べたCSV（またはシートを分けたExcel）でダウンロードする。",
)
def export_dashboard_csv(
    hospital_id: int | None = Query(None, description="会場IDフィルター (任意)"),
    format: str = Query("csv", alias="format", pattern="^(csv|xlsx)$"),
    part: str = Query(
        "all",
        pattern="^(all|summary|age|option|time|venue)(,(summary|age|option|time|venue))*$",
        description=(
            "CSVで書き出す表。all=まとめて1枚。"
            "カンマ区切りで2つ以上指定するとZIPにまとめて返す"
        ),
    ),
    year: int | None = Query(None, description="年フィルター (任意)"),
    month: int | None = Query(None, description="月フィルター (任意)"),
    date: str | None = Query(None, description="日付フィルター YYYY-MM-DD (任意)"),
    week_start: str | None = Query(None, description="期間開始日 YYYY-MM-DD (任意)"),
    week_end: str | None = Query(None, description="期間終了日 YYYY-MM-DD (任意)"),
    db: Session = Depends(get_db),
):
    picked = [p for p in part.split(",") if p and p != "all"]
    if len(picked) > 1:
        # 2つ以上選ばれたときは、1つのZIPにまとめて渡す（解凍すると1フォルダになる）。
        filename, file_bytes, media_type = admin_dashboard_service.export_parts_zip(
            db,
            hospital_id=hospital_id,
            parts=picked,
            year=year,
            month=month,
            date_str=date,
            week_start=week_start,
            week_end=week_end,
        )
        return Response(
            content=file_bytes,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    filename, file_bytes, media_type = admin_dashboard_service.export_file(
        db,
        hospital_id=hospital_id,
        fmt=format,
        part=part,
        year=year,
        month=month,
        date_str=date,
        week_start=week_start,
        week_end=week_end,
    )
    return Response(
        content=file_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
