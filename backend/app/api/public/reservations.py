"""공개 API — 예약 확정 (U-16 → U-17).

    POST /api/v1/reservations
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.reservation import (
    ReservationCreateRequest,
    ReservationCreateResponse,
)
from app.services.reservation_service import ReservationError, create_web_reservation

router = APIRouter(prefix="/reservations", tags=["予約 - 確定"])


@router.post(
    "",
    response_model=ReservationCreateResponse,
    summary="予約確定および予約番号発行",
    description=(
        "本人確認トークンとスロットID、住所・連絡先・オプション検査を受け取り予約を確定する。\n\n"
        "確定処理はスロット行をロックした状態で行われるため、最後の1枠を "
        "2人が同時に申し込んでも1人のみ成功する。\n\n"
        "**409** — 現在は予約を受け付けられない場合 "
        "(満員・締切・重複予約・本人確認期限切れ)。 "
        "`error.code` で原因を区別し、 `error.message` をそのまま画面に表示する。\n\n"
        "**422** — 入力値自体が誤っている場合。項目別のメッセージを `fields` で返す。"
    ),
    responses={409: {"description": "予約を受け付けられない業務上の理由"}},
)
def create_reservation(
    payload: ReservationCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        data = create_web_reservation(
            db,
            payload,
            ip_address=request.client.host if request.client else "",
        )
    except ReservationError as exc:
        db.rollback()
        # 「입력이 틀렸다」가 아니라 「지금은 받을 수 없다」이므로 409 를 쓴다.
        return JSONResponse(
            status_code=409,
            content={
                "success": False,
                "error": {
                    "code": exc.code.value,
                    "message": exc.message,
                    "hints": exc.hints,
                },
            },
        )

    return ReservationCreateResponse(data=data)
