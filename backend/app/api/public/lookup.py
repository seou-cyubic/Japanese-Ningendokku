"""공개 API — 예약 조회 (U-20).

    POST /api/v1/lookup      {"reservation_no": "aK9mQ2xR7bTz"}   ← 화면이 쓰는 길
    GET  /api/v1/lookup?reservation_no=aK9mQ2xR7bTz               ← 하위호환(비권장)

**읽기 전용이다.** 여기 있는 POST 는 「값을 바꾸는 POST」가 아니라
**예약번호를 URL 에 남기지 않기 위한 POST** 다. 변경·취소는 웹에서 할 수
없다(BR-10). 전화로만 접수한다. PATCH·DELETE 는 앞으로도 두지 않는다.

왜 GET 을 그대로 두지 않는가
----------------------------
예약번호는 성함·생년월일·주소·보험증번호·전화까지 전부 여는 **유일한
열쇠**다. 그런데 쿼리스트링은 리버스 프록시와 서버의 접근 로그, 브라우저
히스토리, Referer 헤더에 그대로 남는다. 로그를 볼 수 있는 사람이라면
누구나 열쇠 꾸러미를 쥐는 셈이 된다.

GET 은 메일에 이미 나간 조회 링크(`lookup.html?reservation_no=…`)를 위해
당분간 남긴다. **운영 시 주의**: 리버스 프록시(Nginx 등)의 접근 로그에서
`reservation_no` 를 마스킹하도록 설정해 두는 것을 권한다.

로그인을 요구하지 않는 이유
---------------------------
예약번호가 곧 열쇠다. 무작위 12자·대소문자 구별이라 찍어 맞힐 수 없다.
로그인을 붙이면 고령 이용자에게 계정을 만들게 하는 셈이라
「예약 내용을 잊었다」는 가장 흔한 문의를 오히려 늘린다.

대신 **시도 횟수를 IP 단위로 제한**한다. 번호가 열쇠인 이상,
무제한으로 두드릴 수 있게 두면 언젠가는 열린다. (plan.md §13.2)
"""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import client_ip
from app.schemas.lookup import LookupResponse
from app.services import lookup_service, mail_service
from app.services.lookup_service import LookupBlocked, LookupNotFound

router = APIRouter(prefix="/lookup", tags=["予約 - 照会"])

# 「번호가 틀렸다」와 「그 예약은 없다」를 구별해 알려 주지 않는다.
# 구별해 주면 어떤 번호가 실재하는지를 알려 주는 셈이 된다.
MSG_NOT_FOUND = (
    "入力された予約番号で予約が見つかりませんでした。"
    "予約番号をもう一度ご確認ください。"
)
HINTS_NOT_FOUND = [
    "予約番号は英数字混在の12文字です",
    "英字の大文字と小文字を区別します。案内メールに記載されたとおりに入力してください。",
    "受診日を過ぎた予約は照会できません",
    "予約番号をお忘れの場合は、以下のお問い合わせ先までお電話ください",
]

MSG_BLOCKED = (
    "照会の試行回数が多すぎるため、一時的に照会を制限しています。"
    "しばらくしてからもう一度お試しいただくか、以下のお問い合わせ先までお電話ください。"
)


def _error(status: int, code: str, message: str, hints: list[str]) -> JSONResponse:
    contact = lookup_service.contact()
    return JSONResponse(
        status_code=status,
        content={
            "success": False,
            "error": {
                "code": code,
                "message": message,
                "hints": hints,
                # 막힌 이용자에게 다음 행동을 함께 준다. 거절 문구만 띄우면
                # 그대로 전화가 되는데, 그 전화번호조차 화면에 없으면 최악이다.
                "contact": contact,
            },
        },
    )


class LookupRequest(BaseModel):
    reservation_no: str = Field(..., max_length=32)


def _lookup(request: Request, reservation_no: str, db: Session):
    """조회 본체. GET·POST 가 같은 판정을 쓰도록 한곳에 둔다."""
    ip = client_ip(request)

    try:
        reservation = lookup_service.find(db, reservation_no, ip=ip)
    except LookupBlocked as exc:
        return _error(
            429,
            "TOO_MANY_ATTEMPTS",
            MSG_BLOCKED,
            [f"約 {max(1, exc.retry_after // 60)}分後に再度お試しいただけます"],
        )
    except LookupNotFound:
        return _error(404, "NOT_FOUND", MSG_NOT_FOUND, HINTS_NOT_FOUND)

    return LookupResponse(data=lookup_service.build_result(reservation))


@router.post(
    "",
    response_model=LookupResponse,
    summary="予約照会",
    description=(
        "予約番号から予約内容を照会する。読み取り専用であり変更・キャンセルは"
        "提供しない。予約番号は大文字・小文字を区別する。\n\n"
        "予約番号は氏名・生年月日・住所・保険証番号・電話までを開く唯一の鍵で"
        "あるため、URL(クエリ文字列)ではなく**本文**で受け取る — アクセスログや"
        "ブラウザ履歴に残さないためである。"
    ),
)
def lookup_post(
    request: Request,
    payload: LookupRequest,
    db: Session = Depends(get_db),
):
    return _lookup(request, payload.reservation_no, db)


@router.get(
    "",
    response_model=LookupResponse,
    summary="予約照会(旧・非推奨)",
    deprecated=True,
    description=(
        "**非推奨。** 予約番号がクエリ文字列としてアクセスログ・ブラウザ履歴に"
        "残るため、新しい画面は `POST /api/v1/lookup` を使う。\n\n"
        "すでに送信済みの案内メールに含まれる照会リンクのために当面残している。"
        "リバースプロキシのアクセスログでは `reservation_no` をマスクすること。"
    ),
)
def lookup(
    request: Request,
    reservation_no: str = Query(..., description="予約番号（英数字12文字）", max_length=32),
    db: Session = Depends(get_db),
):
    return _lookup(request, reservation_no, db)


class SendEmailRequest(BaseModel):
    reservation_no: str


@router.post(
    "/send-email",
    summary="メールで予約内容を受け取る",
    description="予約内容確認ページに直接アクセスできるリンクをメールで送信する。",
)
def send_email(
    request: Request,
    payload: SendEmailRequest,
    db: Session = Depends(get_db),
):
    ip = client_ip(request)

    try:
        reservation = lookup_service.find(db, payload.reservation_no, ip=ip)
    except LookupBlocked as exc:
        return _error(
            429,
            "TOO_MANY_ATTEMPTS",
            MSG_BLOCKED,
            [f"約 {max(1, exc.retry_after // 60)}分後に再度お試しいただけます"],
        )
    except LookupNotFound:
        return _error(404, "NOT_FOUND", MSG_NOT_FOUND, HINTS_NOT_FOUND)

    if not reservation.email:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": {
                    "code": "NO_EMAIL",
                    "message": "メールアドレスをご登録いただいていないご予約のため、確認リンクをお送りできません。お手数ですが健康診断予約センターまでお電話ください。",
                    "hints": [],
                    "contact": lookup_service.contact(),
                },
            },
        )

    log = mail_service.send_lookup_link(db, reservation)
    db.commit()

    # 요청은 받았어도 실제로 나가지 않았을 수 있다(발송 설정 없음 · 실패).
    # 화면이 「送信しました」라고 말하지 않도록 결과를 함께 준다.
    return {"success": True, "data": {"delivered": log.status == "SUCCESS"}}
