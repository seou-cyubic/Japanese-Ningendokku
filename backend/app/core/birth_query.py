"""검색어 속의 생년월일을 읽는다.

창구에서 실제로 듣는 말은 「昭和33年11月3日」이지 「1958-11-03」이 아니다.
그래서 서기·和暦·8자리 숫자를 모두 같은 값으로 읽고, 연도만 친 경우는
그 해 전체를 범위로 돌려준다.

    >>> parse_birth_query("1958-11-03")
    (datetime.date(1958, 11, 3), datetime.date(1958, 11, 3))
    >>> parse_birth_query("19581103")
    (datetime.date(1958, 11, 3), datetime.date(1958, 11, 3))
    >>> parse_birth_query("S33.11.3")
    (datetime.date(1958, 11, 3), datetime.date(1958, 11, 3))
    >>> parse_birth_query("昭和33年11月3日")
    (datetime.date(1958, 11, 3), datetime.date(1958, 11, 3))
    >>> parse_birth_query("Ｈ１.１.８")
    (datetime.date(1989, 1, 8), datetime.date(1989, 1, 8))
    >>> parse_birth_query("1958")
    (datetime.date(1958, 1, 1), datetime.date(1958, 12, 31))
    >>> parse_birth_query("昭和33年")
    (datetime.date(1958, 1, 1), datetime.date(1958, 12, 31))
    >>> parse_birth_query("1958-11")
    (datetime.date(1958, 11, 1), datetime.date(1958, 11, 30))
    >>> parse_birth_query("田中") is None
    True
    >>> parse_birth_query("0901") is None
    True
    >>> parse_birth_query("2099-01-01") is None
    True
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import date

# 연호 → 원년의 서기. 「元年」은 1년으로 읽는다.
_ERA_BASE = {
    "M": 1868, "T": 1912, "S": 1926, "H": 1989, "R": 2019,
    "明治": 1868, "大正": 1912, "昭和": 1926, "平成": 1989, "令和": 2019,
    "明": 1868, "大": 1912, "昭": 1926, "平": 1989, "令": 2019,
}

# 태어난 해로 받아들이는 범위. 이보다 밖이면 생년월일이 아니라 다른 숫자다.
_YEAR_MIN = 1900


def _year_max() -> int:
    return date.today().year


_SEP = r"[./\-年]"
_RE_WESTERN = re.compile(
    rf"^(\d{{4}}){_SEP}\s*(\d{{1,2}})(?:{_SEP}\s*(\d{{1,2}}))?[日]?$"
)
_RE_WESTERN_YEAR = re.compile(r"^(\d{4})年?$")
_RE_DIGITS8 = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_RE_ERA = re.compile(
    r"^(明治|大正|昭和|平成|令和|[MTSHR]|[明大昭平令])"
    r"\s*(元|\d{1,2})"
    r"(?:[./\-年]\s*(\d{1,2})(?:[./\-月]\s*(\d{1,2}))?[日]?|年)?$"
)


def _month_range(year: int, month: int) -> tuple[date, date] | None:
    if not 1 <= month <= 12:
        return None
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def _build(year: int, month: int | None, day: int | None) -> tuple[date, date] | None:
    if not _YEAR_MIN <= year <= _year_max():
        return None
    if month is None:
        return date(year, 1, 1), date(year, 12, 31)
    if day is None:
        return _month_range(year, month)
    try:
        d = date(year, month, day)
    except ValueError:
        return None
    if d > date.today():
        return None
    return d, d


def parse_birth_query(token: str) -> tuple[date, date] | None:
    """검색어 한 토막을 생년월일(범위)로 읽는다. 못 읽으면 None."""
    s = unicodedata.normalize("NFKC", (token or "").strip())
    s = s.replace("　", "").replace(" ", "")
    if not s:
        return None
    s = s.upper()

    m = _RE_DIGITS8.match(s)
    if m:
        return _build(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    m = _RE_WESTERN.match(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), m.group(3)
        return _build(y, mo, int(d) if d else None)

    m = _RE_WESTERN_YEAR.match(s)
    if m:
        return _build(int(m.group(1)), None, None)

    m = _RE_ERA.match(s)
    if m:
        base = _ERA_BASE.get(m.group(1))
        if base is None:
            return None
        n = 1 if m.group(2) == "元" else int(m.group(2))
        if n < 1:
            return None
        year = base + n - 1
        mo = int(m.group(3)) if m.group(3) else None
        d = int(m.group(4)) if m.group(4) else None
        if mo is None and d is not None:
            return None
        return _build(year, mo, d)

    return None


def split_keyword(keyword: str) -> tuple[list[str], list[tuple[date, date]]]:
    """검색어를 띄어쓰기로 나눠 「글 토막」과 「생년월일 범위」로 가른다.

    >>> split_keyword("佐藤 1958-11-03")
    (['佐藤'], [(datetime.date(1958, 11, 3), datetime.date(1958, 11, 3))])
    >>> split_keyword("佐藤 花子")
    (['佐藤', '花子'], [])
    >>> split_keyword("")
    ([], [])
    """
    words: list[str] = []
    dates: list[tuple[date, date]] = []
    for tok in re.split(r"[\s　]+", (keyword or "").strip()):
        if not tok:
            continue
        rng = parse_birth_query(tok)
        if rng:
            dates.append(rng)
        else:
            words.append(tok)
    return words, dates


def era_label(d: date | None) -> str:
    """1958-11-03 → 'S33'. 창구에서 和暦로 묻는 사람을 위해 짧게 붙인다.

    >>> era_label(date(1958, 11, 3))
    'S33'
    >>> era_label(date(1989, 1, 7))
    'S64'
    >>> era_label(date(1989, 1, 8))
    'H1'
    >>> era_label(date(2019, 5, 1))
    'R1'
    >>> era_label(None)
    ''
    """
    if not d:
        return ""
    for start, code in (
        (date(2019, 5, 1), "R"),
        (date(1989, 1, 8), "H"),
        (date(1926, 12, 25), "S"),
        (date(1912, 7, 30), "T"),
        (date(1868, 1, 25), "M"),
    ):
        if d >= start:
            return f"{code}{d.year - start.year + 1}"
    return ""
