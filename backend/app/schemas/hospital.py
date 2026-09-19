"""회장 · 예약 슬롯 조회 스키마 (U-12 회장 + 일시 선택)."""

from datetime import date, time

from pydantic import BaseModel


class ScheduleSummary(BaseModel):
    """개최 회차 하나. 회장 목록에서 「언제 여는가」를 답한다."""

    id: int
    event_date: date
    weekday: str
    booking_close_date: date | None = None
    open_time: time | None = None
    reception_end_time: time | None = None
    is_booking_open: bool = True
    note: str = ""


class HospitalSummary(BaseModel):
    """회장 목록 항목.

    `region` 은 목록에 그대로 찍는 표시용 한 줄(東京都港区)이고,
    거르는 축은 `area` 다. region 으로 거르면 회장마다 값이 달라
    선택지가 회장 수만큼 생겨 필터의 뜻이 없어진다.
    """

    id: int
    code: str
    name: str
    region: str
    area: str
    city: str
    address: str
    tel: str
    access_info: str

    # 회장은 여러 날 열 수 있다. 목록에서 개최일을 함께 보여 주지 않으면
    # 달력을 열고 나서야 며칠이 있는지 알게 된다.
    schedules: list[ScheduleSummary] = []

    # 아래 네 개는 **대표 회차**(가장 이른 접수 중인 회차)의 값이다.
    # 목록 한 줄에 날짜 하나만 찍는 자리가 아직 여럿 남아 있어 남겨 둔다.
    # 회차가 여럿인 회장을 제대로 보여 주려면 `schedules` 를 쓴다.
    event_date: date | None = None
    booking_close_date: date | None = None
    open_time: time | None = None
    reception_end_time: time | None = None
    has_parking: bool = False
    latitude: float | None = None
    longitude: float | None = None


class HospitalListResponse(BaseModel):
    success: bool = True
    data: list[HospitalSummary]


class DateSummary(BaseModel):
    """날짜별 예약 현황 요약. 날짜 선택 버튼에 표시한다."""

    date: date
    weekday: str            # 월 화 수 목 금 토 일
    schedule_id: int | None = None
    total_capacity: int
    total_reserved: int
    remaining: int
    availability: str       # AVAILABLE / LIMITED / FULL

    # 그 날이 통째로 휴진인가. 자리가 차서 못 받는 것(FULL)과 그 날 아예
    # 열지 않는 것은 이용자가 할 일이 다르다 — 앞은 다른 시각을 보면 되고,
    # 뒤는 다른 날이나 다른 회장을 봐야 한다.
    is_holiday: bool = False


class SlotDetail(BaseModel):
    """30분 단위 슬롯 상세."""

    slot_id: int
    period: str             # AM / PM
    start_time: str         # 09:00
    end_time: str           # 09:30
    time_label: str         # 09:00~09:30
    capacity: int           # 총 예약 가능 좌석
    reserved: int           # 현재 예약된 좌석
    remaining: int          # 남은 좌석
    availability: str       # AVAILABLE / LIMITED / FULL / CLOSED
    is_available: bool


class AvailabilityResponseData(BaseModel):
    hospital: HospitalSummary
    dates: list[DateSummary]          # 선택 가능한 날짜 목록
    selected_date: date | None = None
    slots: list[SlotDetail] = []      # 선택한 날짜의 슬롯
    total_capacity: int = 0
    total_reserved: int = 0
    total_remaining: int = 0


class AvailabilityResponse(BaseModel):
    success: bool = True
    data: AvailabilityResponseData
