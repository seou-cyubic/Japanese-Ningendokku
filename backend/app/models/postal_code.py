"""우편번호 ↔ 주소 (일본우편 KEN_ALL).

이용자가 우편번호와 주소를 손으로 적게 하면 반드시 틀린다.
특히 고령 이용자에게 한자 주소를 정확히 입력하라는 요구는 무리다.
그래서 **주소를 검색해 고르게 하고**, 우편번호·도도부현·시구정촌·정역은
여기서 채워 넣는다. 이용자가 직접 적는 것은 번지와 건물명뿐이다.

데이터 출처
------------
일본우편이 매월 공개하는 「読み仮名データの促音・拗音を小書きで表記するファイル
(utf_ken_all.csv)」. 12만 건 남짓이며 `scripts/import_postal_codes.py` 로 적재한다.

외부 API 를 실시간으로 부르지 않는 이유
--------------------------------------
plan.md §4.2 는 외부 연계를 스코프 밖으로 두고 있다. 예약 접수 도중에 남의 서버가
멈추면 우리 예약이 멈춘다. 데이터를 받아 두면 그 위험이 없고, 검색도 훨씬 빠르다.
"""

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PostalCode(Base):
    """우편번호 1건. 같은 우편번호가 여러 정역에 걸치는 경우가 있어 PK 는 따로 둔다."""

    __tablename__ = "postal_codes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # 하이픈 없는 7자리. 검색·표시 모두 이 값을 기준으로 한다.
    zipcode: Mapped[str] = mapped_column(String(7), nullable=False, comment="우편번호 7자리")

    prefecture: Mapped[str] = mapped_column(String(20), nullable=False, comment="도도부현")
    city: Mapped[str] = mapped_column(String(60), nullable=False, comment="시구정촌")
    town: Mapped[str] = mapped_column(String(120), nullable=False, default="", comment="정역")

    # 후리가나(전각 가타카나). 한자를 못 읽는 경우와 「히라가나로 쳤다」를 위해 둔다.
    prefecture_kana: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    city_kana: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    town_kana: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    # 검색 전용 컬럼. 도도부현+시구정촌+정역을 붙여 둔 값과 그 후리가나다.
    #
    # 왜 따로 두는가 : 이용자는 「千代田区外神田」처럼 **경계를 무시하고** 친다.
    # 컬럼을 나눠 두면 그런 입력이 어느 컬럼에도 걸리지 않는다.
    # 붙여 둔 값 하나에 LIKE 를 걸면 한 번에 잡힌다.
    search_text: Mapped[str] = mapped_column(
        String(200), nullable=False, default="", comment="검색용 — 도도부현+시구정촌+정역"
    )
    search_kana: Mapped[str] = mapped_column(
        String(360), nullable=False, default="", comment="검색용 — 위의 후리가나"
    )

    __table_args__ = (
        Index("ix_postal_zipcode", "zipcode"),
        # 앞부분 일치(「東京都千代…」)는 이 인덱스로 처리된다.
        # 중간 일치(「外神田」)는 전체 훑기가 되지만, 12만 행이라 감당할 수 있다.
        Index("ix_postal_search", "search_text"),
        {"comment": "郵便番号 ↔ 住所 (日本郵便 KEN_ALL)"},
    )

    @property
    def full_address(self) -> str:
        """화면에 그대로 넣을 수 있는 주소 문자열."""
        return f"{self.prefecture}{self.city}{self.town}"

    def __repr__(self) -> str:
        return f"<PostalCode {self.zipcode} {self.full_address}>"
