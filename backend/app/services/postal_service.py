"""주소 검색 (U-14 정보 입력의 우편번호 칸).

이용자가 아는 것은 「자기 집 주소」다. 우편번호는 대개 기억하지 못한다.
그래서 **주소를 쳐서 고르게 하고** 우편번호를 우리가 채운다.
숫자를 쳤을 때만 우편번호 검색으로 본다.

검색을 어떻게 좁히는가
----------------------
이용자는 경계를 무시하고 친다. 「千代田区外神田」처럼 시구정촌과 정역을
붙여 치거나, 「외신전」만 치거나, 공백을 넣기도 한다.
그래서 도도부현+시구정촌+정역을 붙여 둔 `search_text` 한 컬럼에 건다.

여러 낱말을 치면(「東京 千代田」) **모두 포함**하는 것만 남긴다.
낱말이 늘수록 결과가 줄어드는 쪽이 이용자의 기대에 맞는다.
"""

import unicodedata

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.postal_code import PostalCode

# 한 번에 돌려주는 최대 건수.
# 화면에서 스크롤로 훑을 수 있는 양을 넘기면 고르기가 더 어려워진다.
LIMIT = 30

# 이보다 짧은 검색어는 받지 않는다. 한 글자로는 수천 건이 걸려 의미가 없다.
MIN_LENGTH = 2

# 낱말을 너무 많이 넣으면 조건이 길어지기만 한다.
MAX_TERMS = 5


class PostalSearchError(Exception):
    """검색어가 검색할 수 있는 모양이 아니다."""


# 우편번호 사이에 들어올 수 있는 「하이픈처럼 생긴」 글자들.
# 일본어 IME 로 치면 `-` 키가 장음 「ー」가 되고, 복사해 온 주소에는 마이너스
# 「−」나 대시가 섞인다. 전부 하이픈으로 보지 않으면 「105ー0011」이 0건이다.
_HYPHENS = "-‐‑‒–—―−－ーｰ"

# 우편번호 앞에 붙여 쓰는 기호. 「〒105-0011」 그대로 붙여넣는 사람이 많다.
_POSTAL_MARKS = "〒"


def normalize(value: str) -> str:
    """전각/반각 흔들림을 흡수한다. 「１０１」과 「101」이 같아야 한다."""
    return unicodedata.normalize("NFKC", (value or "").strip())


def to_katakana(value: str) -> str:
    """히라가나 → 가타카나. 읽기(`search_kana`)는 가타카나로 저장되어 있다."""
    return "".join(
        chr(ord(ch) + 0x60) if "ぁ" <= ch <= "ゖ" else ch for ch in value
    )


def _looks_like_postal(keyword: str) -> bool:
    """숫자 · 하이픈류 · 〒 · 공백만으로 되어 있으면 우편번호로 본다."""
    return any(ch.isdigit() for ch in keyword) and all(
        ch.isdigit() or ch in _HYPHENS or ch in _POSTAL_MARKS or ch.isspace()
        for ch in keyword
    )


def _escape_like(term: str) -> str:
    """`%` · `_` 를 글자 그대로 찾게 한다. 그대로 두면 「_」 한 글자가 아무 글자와 맞는다."""
    return term.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def digits_only(value: str) -> str:
    """우편번호로 볼 수 있는 숫자만 뽑는다. 하이픈은 있어도 없어도 된다."""
    return "".join(ch for ch in value if ch.isdigit())


def search(db: Session, keyword: str) -> list[PostalCode]:
    """주소 또는 우편번호로 후보를 찾는다.

    >>> # search(db, "1010021")        → 우편번호로 1건
    >>> # search(db, "千代田区外神田")  → 주소로 1건
    >>> # search(db, "東京 千代田")     → 두 낱말을 모두 포함하는 것만
    """
    keyword = normalize(keyword)

    if len(keyword) < MIN_LENGTH:
        raise PostalSearchError(
            f"{MIN_LENGTH}文字以上入力してください。"
            "例えば「千代田区」のように市区町村名のみ入力しても構いません。"
        )

    digits = digits_only(keyword)

    # --- 우편번호로 찾기 --------------------------------------------------
    # 숫자와 하이픈만으로 이루어져 있을 때만 우편번호로 본다.
    # 주소에 섞인 숫자(「1丁目」)를 우편번호로 오해하지 않기 위함이다.
    if _looks_like_postal(keyword):
        stmt = (
            select(PostalCode)
            .where(PostalCode.zipcode.like(f"{digits}%"))
            .order_by(PostalCode.zipcode, PostalCode.city, PostalCode.town)
            .limit(LIMIT)
        )
        return list(db.execute(stmt).scalars().all())

    # --- 주소로 찾기 ------------------------------------------------------
    terms = [t for t in keyword.split() if t][:MAX_TERMS] or [keyword]

    stmt = select(PostalCode)
    for term in terms:
        # 한자로 친 경우와 가나로 친 경우를 모두 받는다. 읽기는 가타카나로
        # 저장되어 있으므로 히라가나(「みなとく」)는 가타카나로 바꿔 대조한다.
        pattern = f"%{_escape_like(term)}%"
        kana_pattern = f"%{_escape_like(to_katakana(term))}%"
        stmt = stmt.where(
            PostalCode.search_text.like(pattern)
            | PostalCode.search_kana.like(kana_pattern)
        )

    # 앞에서부터 일치하는 것을 위로 올린다.
    # 「新宿」을 쳤을 때 「新宿区…」가 「○○市新宿町」보다 먼저 나와야 한다.
    head_match = case(
        (PostalCode.search_text.like(f"{_escape_like(terms[0])}%"), 0), else_=1
    )

    stmt = stmt.order_by(
        head_match,
        func.char_length(PostalCode.search_text),   # 짧은 주소가 대개 상위 행정구역
        PostalCode.zipcode,
    ).limit(LIMIT)

    return list(db.execute(stmt).scalars().all())

