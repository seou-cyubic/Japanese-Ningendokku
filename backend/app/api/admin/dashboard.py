from urllib.parse import quote
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
    summary="健診統計 CSV 書き出し（表ごと）",
    description=(
        "健診統計タブで選んだ会場・期間で、選んだ表をCSVで書き出す。"
        "1つならCSV1つ、2つ以上ならZIP（解凍すると1つのフォルダ）で返す。"
    ),
)
def export_dashboard_csv(
    hospital_id: int | None = Query(None, description="会場IDフィルター (任意)"),
    part: str = Query(
        ...,
        pattern="^(summary|age|option|time|venue)(,(summary|age|option|time|venue))*$",
        description="書き出す表。カンマ区切りで2つ以上指定するとZIPにまとめて返す",
    ),
    year: int | None = Query(None, description="年フィルター (任意)"),
    month: int | None = Query(None, description="月フィルター (任意)"),
    date: str | None = Query(None, description="日付フィルター YYYY-MM-DD (任意)"),
    week_start: str | None = Query(None, description="期間開始日 YYYY-MM-DD (任意)"),
    week_end: str | None = Query(None, description="期間終了日 YYYY-MM-DD (任意)"),
    db: Session = Depends(get_db),
):
    picked = [p for p in dict.fromkeys(part.split(",")) if p]
    period = dict(year=year, month=month, date_str=date, week_start=week_start, week_end=week_end)
    if len(picked) > 1:
        # 2つ以上選ばれたときは、1つのZIPにまとめて渡す（解凍すると1フォルダになる）。
        filename, file_bytes, media_type = admin_dashboard_service.export_parts_zip(
            db, hospital_id=hospital_id, parts=picked, **period
        )
    else:
        filename, file_bytes, media_type = admin_dashboard_service.export_file(
            db, hospital_id=hospital_id, part=picked[0], **period
        )
    return Response(
        content=file_bytes,
        media_type=media_type,
        headers=_download_headers(filename),
    )

def _download_headers(file_name: str) -> dict[str, str]:
    """일본어 파일 이름을 그대로 쓰기 위한 Content-Disposition.

    헤더는 ASCII 만 담을 수 있다. 「2026年09月_西区民センター_集計.csv」를 그대로 넣으면
    응답을 만들다 오류가 난다. RFC 5987 의 `filename*` 로 UTF-8 이름을 주고,
    이를 모르는 오래된 브라우저를 위해 ASCII 이름을 함께 남긴다.
    """
    ascii_name = "health-stats." + file_name.rsplit(".", 1)[-1]
    return {
        "Content-Disposition": (
            f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(file_name)}"
        ),
        "Cache-Control": "no-store",
    }
