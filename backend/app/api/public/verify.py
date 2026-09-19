"""공개 API — 본인 확인 (U-11).

POST /api/v1/reservations/verify
GET  /api/v1/reservations/eligibility
"""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dates import (
    ELIGIBLE_AGE_MAX,
    ELIGIBLE_AGE_MIN,
    eligible_birth_range,
    fiscal_year,
    screening_birth_range,
)
from app.schemas.verify import VerifyRequest, VerifyResponse
from app.services.verify_service import verify_identity

router = APIRouter(prefix="/reservations", tags=["予約 - 本人確認"])


@router.post(
    "/verify",
    response_model=VerifyResponse,
    summary="本人確認および健診対象者の判別",
    description=(
        "氏名・生年月日・健康保険証情報を健診対象者名簿と照合する。\n\n"
        "- `ELIGIBLE` : 健診対象者であり予約可能 (verify_token発行)\n"
        "- `ALREADY_RESERVED` : 健診対象者であるが既に予約が存在\n"
        "- `NOT_ELIGIBLE` : 名簿になし (お問い合わせ先案内)"
    ),
)
def verify(payload: VerifyRequest, db: Session = Depends(get_db)) -> VerifyResponse:
    return VerifyResponse(data=verify_identity(db, payload))


# --------------------------------------------------------------------------
# 검진 대상 생년월일 범위
#
# 화면이 생년월일 입력 직후에 「명백히 대상 밖」인지 되묻기 위해 쓴다.
# 규칙을 화면에 복사해 두면 제도가 바뀌었을 때 한쪽만 고쳐져 조용히 어긋난다.
# 기준은 core/dates.py 한 곳에 두고, 화면은 받아서 표시만 한다.
#
#   eligible_*   실제 대상 범위. 안내 문구에 그대로 쓴다
#   screening_*  되묻기 판정용. 위아래로 여유를 둔 넓은 범위이며,
#                이 범위를 벗어날 때만 화면에서 확인을 요청한다
#
# 최종 판정은 언제나 대상자 명부다. 이 값으로 예약을 거절하지 않는다.
# --------------------------------------------------------------------------
@router.get(
    "/eligibility",
    summary="健診対象生年月日範囲",
    description="画面が生年月日の再確認判定に使う。最終判定は対象者名簿が行う。",
)
def eligibility() -> dict:
    year = fiscal_year(date.today())
    eligible_from, eligible_to = eligible_birth_range(year)
    screen_from, screen_to = screening_birth_range(year)

    return {
        "success": True,
        "data": {
            "fiscal_year": year,
            "age_min": ELIGIBLE_AGE_MIN,
            "age_max": ELIGIBLE_AGE_MAX,
            "eligible_from": eligible_from.isoformat(),
            "eligible_to": eligible_to.isoformat(),
            "screening_from": screen_from.isoformat(),
            "screening_to": screen_to.isoformat(),
        },
    }
