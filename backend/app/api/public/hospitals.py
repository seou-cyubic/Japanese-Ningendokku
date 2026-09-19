"""공개 API — 회장 목록 및 예약 가능 시간 조회 (U-12).

    GET /api/v1/hospitals
    GET /api/v1/hospitals/{hospital_id}/availability?date=YYYY-MM-DD
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.hospital import AvailabilityResponse, HospitalListResponse
from app.services import hospital_service

router = APIRouter(prefix="/hospitals", tags=["予約 - 会場・日時"])


@router.get(
    "",
    response_model=HospitalListResponse,
    summary="会場一覧",
    description="予約画面に表示するように設定された会場一覧を返す。",
)
def list_hospitals(db: Session = Depends(get_db)) -> HospitalListResponse:
    return HospitalListResponse(data=hospital_service.list_hospitals(db))


@router.get(
    "/{hospital_id}/availability",
    response_model=AvailabilityResponse,
    summary="予約可能日および30分単位のタイムスケジュール",
    description=(
        "選択した会場の予約可能日一覧と、指定した日付の30分単位のタイムスケジュールを"
        "返す。各時間帯の総定員 / 予約数 / 残りと"
        "予約可否(AVAILABLE・LIMITED・FULL・CLOSED)を含む。\n\n"
        "`date` を省略すると、予約可能な最も早い日付を自動選択する。"
    ),
)
def get_availability(
    hospital_id: int,
    date_: date | None = Query(
        None, alias="date", description="照会する日付 (YYYY-MM-DD)"
    ),
    db: Session = Depends(get_db),
) -> AvailabilityResponse:
    hospital = hospital_service.get_hospital(db, hospital_id)
    if hospital is None:
        raise HTTPException(status_code=404, detail="会場が見つかりません。")

    data = hospital_service.get_availability(
        db, hospital, date_, today=date.today()
    )
    return AvailabilityResponse(data=data)
