"""공개 API — 옵션 검사 목록 (U-14 정보 입력).

    GET /api/v1/exam-options?gender=F&birth_date=1975-12-15

성별·생년월일을 받아 그 사람이 신청할 수 있는 옵션만 반환한다. (BR-13)
두 값은 U-11 본인 확인에서 이미 확정된 값이므로 이용자가 다시 입력하지 않는다.
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.exam_option import ExamOptionListResponse
from app.services import exam_option_service

router = APIRouter(prefix="/exam-options", tags=["予約 - 情報入力"])


@router.get(
    "",
    response_model=ExamOptionListResponse,
    summary="申込可能なオプション検査一覧",
    description=(
        "性別・年齢ターゲット条件に合致するオプション検査のみを返す。\n\n"
        "申し込めない検査は一覧に一切含めない。"
        "薄く表示するだけでも「なぜ申し込めないのか」というお問い合わせにつながる。"
    ),
)
def list_exam_options(
    gender: str = Query(..., pattern="^[MF]$", description="性別 M=男性 F=女性"),
    birth_date: date = Query(..., description="生年月日 (西暦 YYYY-MM-DD)"),
    db: Session = Depends(get_db),
) -> ExamOptionListResponse:
    data = exam_option_service.list_for_person(
        db, gender=gender, birth_date=birth_date, today=date.today()
    )
    return ExamOptionListResponse(data=data)
