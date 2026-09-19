"""날짜 계산 유틸리티.

일본 회계연도(4/1 ~ 익년 3/31)와 만 연령 계산을 한곳에 모은다.
중복 예약 판정(BR-03)과 옵션 검사 타깃 조건(BR-13)이 이 계산에 의존하므로,
같은 규칙이 여러 곳에 흩어지지 않도록 격리한다.
"""

from datetime import date, timedelta

# 회계연도 시작 월 (일본 회계연도는 4월 1일에 시작한다)
FISCAL_START_MONTH = 4

_ONE_DAY = timedelta(days=1)


def fiscal_year(target: date) -> int:
    """해당 날짜가 속한 회계연도를 구한다.

    4/1 ~ 익년 3/31 을 한 해로 본다. (plan.md 용어 사전 「당해 연도」)

    >>> fiscal_year(date(2026, 4, 1))
    2026
    >>> fiscal_year(date(2027, 3, 31))
    2026
    >>> fiscal_year(date(2026, 3, 31))
    2025
    """
    return target.year if target.month >= FISCAL_START_MONTH else target.year - 1


def fiscal_year_range(year: int) -> tuple[date, date]:
    """회계연도의 시작일과 종료일을 구한다.

    >>> fiscal_year_range(2026)
    (datetime.date(2026, 4, 1), datetime.date(2027, 3, 31))
    """
    start = date(year, FISCAL_START_MONTH, 1)
    end = date(year + 1, FISCAL_START_MONTH, 1) - _ONE_DAY
    return start, end


def age_on(birth_date: date, target: date) -> int:
    """기준일 시점의 만 연령을 구한다.

    생일이 지나지 않았으면 한 살 뺀다.

    >>> age_on(date(1986, 4, 2), date(2026, 4, 1))
    39
    >>> age_on(date(1986, 4, 2), date(2026, 4, 2))
    40
    """
    years = target.year - birth_date.year
    if (target.month, target.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years


# ==========================================================================
# 검진 대상 연령
#
# 특정건강진사 기준으로 **회계연도 말(3/31) 시점의 만 연령**이 40~74세인
# 사람이 대상이다. 생일 기준이 아니라 연도 말 기준이라는 점이 중요하다.
#
# 이 값이 코드 어디에도 정의돼 있지 않아 화면·명부·옵션 검사가 제각각
# 가정하고 있었다. 한곳에 모아 둔다.
#
# ※ 최종 판정은 언제나 대상자 명부(target_persons)다. 아래 범위는
#   명부를 조회하기 전에 명백히 벗어난 입력을 걸러 내기 위한 것이다.
# ==========================================================================

ELIGIBLE_AGE_MIN = 40
ELIGIBLE_AGE_MAX = 74

# 1차 안내에 쓰는 여유폭(년).
#
# 경계 판정을 조금이라도 잘못하면 **대상자인 분을 막아 버린다.** 그쪽이
# 훨씬 나쁘므로 위아래로 넉넉히 벌려 두고, 그 사이는 명부에 맡긴다.
# 20·30대를 걸러 내는 목적에는 이 정도로 충분하다.
SCREEN_MARGIN_YEARS = 2


def _birth_range_for_ages(year: int, age_min: int, age_max: int) -> tuple[date, date]:
    """회계연도 말 시점에 만 age_min ~ age_max 가 되는 생년월일 범위."""
    _, end = fiscal_year_range(year)

    # 가장 늦게 태어나도 되는 날 = 그날 만 age_min 이 되는 날
    latest = date(end.year - age_min, end.month, end.day)
    # 가장 이르게 태어나도 되는 날 = 만 age_max+1 이 되는 날의 다음 날
    earliest = date(end.year - age_max - 1, end.month, end.day) + _ONE_DAY

    return earliest, latest


def eligible_birth_range(year: int) -> tuple[date, date]:
    """검진 대상이 되는 생년월일 범위. 화면 안내에 그대로 쓴다.

    >>> eligible_birth_range(2026)
    (datetime.date(1952, 4, 1), datetime.date(1987, 3, 31))
    """
    return _birth_range_for_ages(year, ELIGIBLE_AGE_MIN, ELIGIBLE_AGE_MAX)


def screening_birth_range(year: int) -> tuple[date, date]:
    """1차 차단에 쓰는 범위. 위아래로 여유를 둔 넓은 범위다.

    이 범위를 **벗어난** 생년월일만 화면에서 되묻는다.
    범위 안이면 명부 조회로 넘긴다.
    """
    return _birth_range_for_ages(
        year,
        ELIGIBLE_AGE_MIN - SCREEN_MARGIN_YEARS,
        ELIGIBLE_AGE_MAX + SCREEN_MARGIN_YEARS,
    )
