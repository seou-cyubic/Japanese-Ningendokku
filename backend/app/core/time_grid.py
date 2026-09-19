"""검진 시간표의 격자 — 30분 × 16칸.

이 파일이 시간 그리드를 아는 **유일한 곳**이다
---------------------------------------------
회장 마스터의 시간대 열은 원본에서 이미 고정된 격자다.

    9:00～09:30 · 9:30～10:00 · … · 16:30～17:00     (16칸)

예전에는 이 격자를 `slots` 테이블에 **행으로 풀어** 두었다. 한 회차의
시간표가 최대 16행이었다. 그러나 마스터도, 관리 화면의 표도, 담당자의
머릿속도 전부 **한 줄에 16칸**이다. 저장만 세로였다.

지금은 저장도 가로다. `hospital_schedules` 한 행이 그 날의 정원 16칸을
갖고, `reservation_counts` 한 행이 같은 자리의 실 예약자 수를 갖는다.

대가 — 격자가 스키마가 된다
---------------------------
원본이 `8:30` 을 들고 오면 칼럼을 늘려야 한다. 그 대가를 감당할 수 있게
**격자를 아는 코드를 이 파일 하나로 가둔다.** 칼럼 이름도, 인덱스도,
표의 열 이름도 전부 여기서 만든다. 격자를 넓힐 때 고칠 곳은
`TIME_GRID` 한 줄과 마이그레이션 스크립트뿐이다.

    python -m scripts.extend_time_grid --to 17:30
"""

from datetime import time

# --------------------------------------------------------------------------
# 격자
# --------------------------------------------------------------------------
# `(시작, 종료)` 를 시트에 적힌 순서 그대로. 이 순서가 곧 칼럼 순서이며
# 슬롯 인덱스다. **중간을 빼지 않는다** — 점심시간(12:00～13:00)도 자리를
# 지킨다. 자리를 빼면 인덱스가 밀려 예전에 저장한 값이 다른 시간대로 읽힌다.
TIME_GRID: tuple[tuple[time, time], ...] = (
    (time(9, 0), time(9, 30)),
    (time(9, 30), time(10, 0)),
    (time(10, 0), time(10, 30)),
    (time(10, 30), time(11, 0)),
    (time(11, 0), time(11, 30)),
    (time(11, 30), time(12, 0)),
    (time(12, 0), time(12, 30)),
    (time(12, 30), time(13, 0)),
    (time(13, 0), time(13, 30)),
    (time(13, 30), time(14, 0)),
    (time(14, 0), time(14, 30)),
    (time(14, 30), time(15, 0)),
    (time(15, 0), time(15, 30)),
    (time(15, 30), time(16, 0)),
    (time(16, 0), time(16, 30)),
    (time(16, 30), time(17, 0)),
)

SLOT_COUNT = len(TIME_GRID)

# 시작 시각 → 인덱스. 예약이 들고 있는 `start_time` 으로 칸을 찾을 때 쓴다.
_INDEX_OF: dict[time, int] = {start: i for i, (start, _end) in enumerate(TIME_GRID)}


# --------------------------------------------------------------------------
# 칼럼 이름
# --------------------------------------------------------------------------
# `cap_0930` 처럼 **시각을 이름에 남긴다.** `cap_02` 로 두면 SQL 을 눈으로
# 읽을 수 없고, 장애가 났을 때 DB 콘솔에서 무엇을 보고 있는지 알 수 없다.


def _suffix(index: int) -> str:
    start, _end = TIME_GRID[index]
    return f"{start.hour:02d}{start.minute:02d}"


CAPACITY_COLUMNS: tuple[str, ...] = tuple(
    f"cap_{_suffix(i)}" for i in range(SLOT_COUNT)
)
RESERVED_COLUMNS: tuple[str, ...] = tuple(
    f"res_{_suffix(i)}" for i in range(SLOT_COUNT)
)


def capacity_column(index: int) -> str:
    return CAPACITY_COLUMNS[index]


def reserved_column(index: int) -> str:
    return RESERVED_COLUMNS[index]


# --------------------------------------------------------------------------
# 인덱스 · 시각
# --------------------------------------------------------------------------


def index_of(start: time) -> int | None:
    """시작 시각으로 칸 번호를 찾는다. 격자에 없는 시각이면 `None`.

    초·마이크로초를 떼고 본다. DB 에서 온 `TIME` 값이 그대로 들어오기 때문.
    """
    return _INDEX_OF.get(start.replace(second=0, microsecond=0))


def start_time(index: int) -> time:
    return TIME_GRID[index][0]


def end_time(index: int) -> time:
    return TIME_GRID[index][1]


def label(index: int) -> str:
    """예: `09:30～10:00`. 화면·메일·파일이 전부 이 표기를 쓴다."""
    start, end = TIME_GRID[index]
    # 波ダッシュは全角チルダ（U+FF5E）を使う。Windows の IME が「から」で
    # 出すのがこの文字で、日本語のサイトでも実務上こちらが使われている。
    # 半角チルダ（U+007E）は日本語の組版では使わない。
    return f"{start.strftime('%H:%M')}～{end.strftime('%H:%M')}"


def period(index: int) -> str:
    """오전 / 오후. 12:00～13:00 은 접수 대상 외이므로 경계가 명확하다."""
    return "AM" if TIME_GRID[index][0].hour < 12 else "PM"


def indexes() -> range:
    return range(SLOT_COUNT)


# --------------------------------------------------------------------------
# 슬롯 식별자
# --------------------------------------------------------------------------
# `slots` 테이블이 사라져도 **화면은 여전히 「그 시간대」를 가리켜야 한다.**
# 프런트엔드는 이 값을 계산에 쓰지 않고 받은 그대로 되돌려 보내므로
# (`schedule.js` 의 `data-slot-id`, `postal.js` 의 `slot_ids`),
# 회차와 칸을 한 정수로 접어 두면 API 모양을 바꾸지 않아도 된다.
#
# 100 을 곱하는 이유는 칸이 16개뿐이라 두 자리로 충분하고, 사람이 값을
# 봤을 때 `3305` 에서 「회차 33 의 5번 칸」을 바로 읽을 수 있기 때문이다.

_STRIDE = 100


def slot_id(schedule_id: int, index: int) -> int:
    return schedule_id * _STRIDE + index


def split_slot_id(value: int) -> tuple[int, int]:
    """`slot_id` → `(schedule_id, index)`.

    범위를 벗어난 인덱스는 그대로 돌려준다. 판정은 부르는 쪽에서 한다 —
    여기서 예외를 던지면 「없는 슬롯」과 「망가진 요청」을 구별할 수 없다.
    """
    return divmod(int(value), _STRIDE)


# --------------------------------------------------------------------------
# 마감 비트마스크
# --------------------------------------------------------------------------
# 「정원 0」과 「정원은 22인데 오늘만 닫음」은 다른 상태다. 마감을 정원 0 으로
# 대신하면 **해제할 때 원래 정원을 잃는다.** 그래서 마감은 정원과 나란한
# 별도의 비트로 둔다. 16칸이므로 정수 하나면 된다.


def is_closed(mask: int, index: int) -> bool:
    return bool((mask or 0) >> index & 1)


def set_closed(mask: int, index: int, closed: bool) -> int:
    mask = mask or 0
    bit = 1 << index
    return mask | bit if closed else mask & ~bit


def closed_indexes(mask: int) -> list[int]:
    return [i for i in indexes() if is_closed(mask, i)]


# --------------------------------------------------------------------------
# 시트 열 이름
# --------------------------------------------------------------------------
# 원본 마스터의 열 이름(`9:30～10:00`)과 관리 화면 표의 열 키를 만든다.
# 임포터와 표가 서로 다른 규칙으로 만들면, 같은 파일을 한쪽으로 넣고
# 다른 쪽으로 내보냈을 때 열이 붙지 않는다.


def sheet_key(index: int) -> str:
    """표의 열 키. `09:30～10:00` — 앞자리 0 을 채운 반각 표기."""
    return label(index)


SHEET_KEYS: tuple[str, ...] = tuple(sheet_key(i) for i in range(SLOT_COUNT))

_KEY_TO_INDEX: dict[str, int] = {key: i for i, key in enumerate(SHEET_KEYS)}


def index_of_sheet_key(key: str) -> int | None:
    return _KEY_TO_INDEX.get(key)
