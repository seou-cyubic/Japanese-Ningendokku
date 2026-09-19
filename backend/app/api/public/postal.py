"""공개 API — 주소 검색 (U-14 정보 입력).

    GET /api/v1/postal/search?keyword=千代田区外神田

이용자가 우편번호와 한자 주소를 손으로 적게 하면 반드시 틀린다.
주소를 검색해 고르게 하고, 우편번호·주소는 서버가 채워 준다.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import settings
from app.schemas.postal import (
    PostalCandidate,
    PostalContact,
    PostalSearchData,
    PostalSearchResponse,
)
from app.services import postal_import_service, postal_service
from app.services.postal_service import PostalSearchError

router = APIRouter(prefix="/postal", tags=["予約 - 住所検索"])


@router.get(
    "/search",
    response_model=PostalSearchResponse,
    summary="住所・郵便番号検索",
    description=(
        "住所の一部(「千代田区外神田」)または郵便番号(「1010021」)で検索する。"
        "日本郵便が配布する郵便番号データを事前に取り込んで照会するため、"
        "外部サーバーにリアルタイムで依存しない。"
    ),
)
def search_postal(
    keyword: str = Query(..., description="住所の一部または郵便番号", max_length=100),
    db: Session = Depends(get_db),
) -> PostalSearchResponse:
    try:
        rows = postal_service.search(db, keyword)
    except PostalSearchError as exc:
        # 「입력이 짧다」는 이용자가 고칠 수 있는 문제다. 422 로 돌려준다.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # 한 건도 없을 때 「검색 결과가 없다」와 「데이터가 아예 없다」를 가른다.
    #
    # 예전에는 둘 다 빈 목록이었다. 우편번호 데이터를 넣지 않은 환경에서는
    # 무엇을 쳐도 0건이 나오는데, 이용자에게는 「내가 주소를 잘못 쳤다」로
    # 보인다. 아무리 고쳐 쳐도 안 되므로 거기서 예약을 포기한다.
    #
    # 0건일 때만 센다. 검색이 되는 평상시에는 세지 않는다.
    if not rows and not postal_import_service.is_loaded(db, settings.POSTAL_MIN_ROWS):
        raise HTTPException(
            status_code=503,
            detail={
                "message": (
                    "現在、住所検索をご利用いただけません。"
                    "お客様の入力の問題ではございません。"
                ),
                # 막다른 길로 두지 않는다. 주소를 손으로 적게 하지 않는 것이
                # 이 화면의 규칙(form.html 주석)이므로, 남은 길은 전화 접수다.
                "contact": {
                    "tel": settings.CONTACT_TEL,
                    "hours": settings.CONTACT_HOURS,
                },
            },
        )

    items = [
        PostalCandidate(
            zipcode=r.zipcode,
            address=r.full_address,
            prefecture=r.prefecture,
            city=r.city,
            town=r.town,
            kana=f"{r.prefecture_kana}{r.city_kana}{r.town_kana}",
        )
        for r in rows
    ]

    return PostalSearchResponse(
        data=PostalSearchData(
            keyword=keyword,
            total=len(items),
            truncated=len(items) >= postal_service.LIMIT,
            items=items,
            contact=PostalContact(
                tel=settings.CONTACT_TEL, hours=settings.CONTACT_HOURS
            ),
        )
    )
