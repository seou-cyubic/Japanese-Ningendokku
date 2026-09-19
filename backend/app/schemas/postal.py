"""주소 검색 스키마 (U-14 우편번호 칸)."""

from pydantic import BaseModel


class PostalCandidate(BaseModel):
    """검색 결과 1건. 화면이 그대로 각 칸에 넣을 수 있는 모양으로 내려준다."""

    # 하이픈 없는 7자리. 화면에서 앞 3 / 뒤 4 로 나눠 넣는다.
    zipcode: str
    # 도도부현 + 시구정촌 + 정역. 「주소」 칸에 그대로 들어간다.
    address: str
    # 화면 목록에서 굵게/작게 나눠 보여 주기 위해 조각도 함께 준다.
    prefecture: str
    city: str
    town: str
    kana: str = ""


class PostalContact(BaseModel):
    tel: str = ""
    hours: str = ""


class PostalSearchData(BaseModel):
    keyword: str
    total: int
    # LIMIT 에 걸려 잘렸는가. 「더 좁혀 주세요」를 안내할지 판단한다.
    truncated: bool = False
    items: list[PostalCandidate] = []

    # 문의처.
    #
    # 이 화면에는 **주소를 직접 입력하는 칸이 없다.** 검색에 나오지 않는 주소는
    # 넣을 수 없으며, 그것이 의도한 동작이다 — 손으로 적게 하면 우편번호와
    # 주소가 어긋난 채 접수되고 걸러 낼 방법이 없다.
    #
    # 다만 막다른 길을 만들면 안 된다. 찾지 못한 이용자에게는
    # 「전화해 주세요」와 그 번호를 그 자리에서 보여 준다. (plan.md P-9)
    contact: PostalContact = PostalContact()


class PostalSearchResponse(BaseModel):
    success: bool = True
    data: PostalSearchData
