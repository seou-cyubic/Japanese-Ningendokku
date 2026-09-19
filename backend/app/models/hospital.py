"""검진 회장(会場) · 개최 회차 · 정원 그리드 모델.

plan.md §9.1 / §9.4 / BR-07 ~ BR-09

세 층으로 나뉘어 있다
---------------------
    Hospital           장소 그 자체.   이름·주소·좌표·교통편.
    HospitalSchedule   그 장소의 개최 회차. 개최일 + **그 날의 정원 16칸**.
    ReservationCount   같은 모양의 실 예약자 수.

시간표는 행이 아니라 그리드다
-----------------------------
예전에는 `slots` 테이블이 한 회차의 시간표를 최대 16행으로 풀어 두었다.
그러나 마스터 파일도, 관리 화면의 표도, 담당자의 머릿속도 전부 **한 줄에
16칸**이다. 저장만 세로였고, 화면에 낼 때마다 다시 가로로 접어야 했다.

지금은 저장도 가로다. 격자를 아는 코드는 `app/core/time_grid.py` 하나이며,
그리드를 읽는 코드는 `app/services/slot_grid_service.py` 하나다.

왜 회차를 따로 두는가
---------------------
예전에는 `Hospital` 한 행이 개최일까지 들고 있었다. 회장 1곳 = 개최일 1일이
스키마에 못 박혀 있었다는 뜻이다.

그러나 실제 마스터는 **같은 회장이 여러 날 연다.** 시민회관을 7월에 한 번,
10월에 한 번 빌리는 식이다. 개최일을 `Hospital` 에 두면 그 회장을 두 벌
등록하는 수밖에 없고, 그러면 주소·좌표·교통편이 두 곳에 적히게 된다.
한쪽만 고친 순간 이용자에게 안내되는 위치가 회차마다 달라진다.

그래서 **반복되는 사실(개최일)을 반복되지 않는 사실(장소)에서 떼어냈다.**
장소는 한 번만 적히고, 회차는 필요한 만큼 늘어난다.

예약이 회차를 가리킨다
----------------------
`reservations` 는 `schedule_id` 로 회차에 물리고, 그 날의 몇 시인지는
자기 행의 `start_time` 이 답한다. 외래키는 `RESTRICT` 라서
**예약이 걸린 회차는 DB 가 지우지 못하게 막는다.**
"""

from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core import time_grid
from app.core.database import Base


class Hospital(Base):
    """검진 회장 1곳 — **장소**. 개최일은 `schedules` 가 가진다."""

    __tablename__ = "hospitals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    code: Mapped[str] = mapped_column(
        String(20), nullable=False, unique=True, comment="회장 코드 (会場番号 연계 키)"
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False, comment="회장명")

    # 회장명 읽기(요미가나). 히라가나로 적어 둔다.
    #
    # 회장명이 한자·가타카나라 「さんぷる」로는 サンプル会館 A 를 찾을 수 없다.
    # 예전에는 관리 화면(`hospitals.js`)이 회장 20곳의 읽기를 **화면 파일에
    # 박아** 두고 있었다. 회장이 바뀌면 코드를 고쳐야 했고, 화면을 하나 더
    # 만들면 그 표도 복사해야 했다. 읽기는 회장에 딸린 사실이므로 여기 둔다.
    #
    # 비어 있어도 된다. 그때는 한자·코드·지역·주소로만 걸린다.
    name_kana: Mapped[str] = mapped_column(
        String(200), nullable=False, default="", comment="회장명 요미가나 (검색용)"
    )

    # --- 소재지 ----------------------------------------------------------
    # `region` 은 地域 + 区・市町村 를 이어 붙인 표시용 값이다 (예: 東京都港区).
    # 이용자가 목록에서 읽는 것은 이 한 줄이며, **거르는 축은 `area`** 다.
    # region 으로 거르면 회장마다 값이 달라 선택지가 20개가 되어 필터의 뜻이 없다.
    area: Mapped[str] = mapped_column(
        String(40), nullable=False, default="", comment="地域 (지역 필터의 축)"
    )
    city: Mapped[str] = mapped_column(
        String(60), nullable=False, default="", comment="区・市町村"
    )
    region: Mapped[str] = mapped_column(
        String(100), nullable=False, default="", comment="표시용 — 地域+区市町村"
    )
    postal_code: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    address: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    # 비워 두면 공통 문의처(.env 의 CONTACT_TEL)를 쓴다. `contact_tel` 참조.
    # 회장은 당일에만 빌리는 장소라 그곳의 번호로 걸어도 받는 사람이 없다.
    tel: Mapped[str] = mapped_column(
        String(30), nullable=False, default="", comment="비우면 공통 문의처를 사용"
    )

    # --- 교통편 ----------------------------------------------------------
    # 원본이 「交通情報」와 「アクセス時間」 두 칸으로 나뉘어 있다. 나뉜 채로
    # 보관하고 화면에 낼 때만 잇는다(`access_info`). 합쳐서 넣어 두면
    # 「도보 5분」만 고치고 싶을 때 문자열을 다시 갈라야 한다.
    transit_info: Mapped[str] = mapped_column(
        String(200), nullable=False, default="", comment="交通情報 — 최기역·출구"
    )
    access_minutes: Mapped[str] = mapped_column(
        String(40), nullable=False, default="", comment="アクセス時間 — 徒歩5分"
    )

    has_parking: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="駐車場 유무"
    )

    # 좌표는 반드시 배정밀도(DOUBLE)로 둔다.
    #
    # `Float` 은 MySQL 에서 단정밀도 FLOAT 이 되어 유효숫자가 7자리뿐이다.
    # 원본의 35.6584491 은 9자리라 FLOAT 에 넣는 순간 35.6584 로 잘리고,
    # 그것은 지도 위에서 **100m 넘게 어긋난 위치**다. 회장을 못 찾는다는
    # 문의가 되기에 충분한 거리다.
    latitude: Mapped[float | None] = mapped_column(Double, nullable=True, comment="緯度")
    longitude: Mapped[float | None] = mapped_column(Double, nullable=True, comment="経度")

    is_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="예약 화면 표시/비표시"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # 회차는 회장을 읽을 때 거의 항상 같이 본다(목록·달력·메일 전부).
    # `selectin` 으로 한 번에 가져오지 않으면 회장 20곳에 쿼리가 20번 더 난다.
    schedules: Mapped[list["HospitalSchedule"]] = relationship(
        back_populates="hospital",
        cascade="all, delete-orphan",
        order_by="HospitalSchedule.event_date",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_hospital_visible", "is_visible", "sort_order"),
        {"comment": "受診会場マスター — 場所"},
    )

    # ----------------------------------------------------------------------
    # 파생 값
    # ----------------------------------------------------------------------

    @property
    def contact_tel(self) -> str:
        """이용자에게 보여 줄 문의처 전화번호.

        회장은 검진 당일에만 빌리는 장소라 **그 장소의 번호를 안내할 수 없다.**
        걸어도 받는 사람이 없거나, 검진과 무관한 시설 직원이 받는다.
        그래서 예약 센터 번호 하나로 통일하며, 값은 `.env` 의 `CONTACT_TEL`
        한 곳에만 둔다. DB 로 복사해 두면 번호를 바꿨을 때 예전 값이 남는다.

        회장별로 다른 번호를 안내해야 하는 예외가 생기면 `tel` 에 넣는다.
        """
        if self.tel:
            return self.tel
        from app.core.config import settings

        return settings.CONTACT_TEL

    @property
    def access_info(self) -> str:
        """교통편 한 줄. 예: 「都営大江戸線「赤羽橋駅」赤羽橋口 徒歩5分」

        화면·메일·파일이 전부 이 한 줄을 쓴다. 두 칸을 각각 읽어 잇는 코드가
        여러 곳에 생기면 어디는 공백이고 어디는 쉼표가 된다.
        """
        return " ".join(part for part in (self.transit_info, self.access_minutes) if part)

    # --- 회차 파생 값 ------------------------------------------------------
    #
    # 아래 네 개(`event_date` · `booking_close_date` · `open_time` ·
    # `reception_end_time`)는 **읽기 전용 호환 값**이다. 예전에는 칼럼이었고,
    # 화면·메일·파일 등 스무 곳 남짓이 이 이름으로 읽는다. 회차로 옮기면서
    # 그 스무 곳을 한꺼번에 고치는 대신, 「대표 회차」의 값을 돌려주게 했다.
    #
    # **쓰기는 되지 않는다.** 값을 넣어야 하는 곳은 회차를 직접 다루어야
    # 한다. 대입이 조용히 먹히면 「저장했는데 안 바뀐다」가 되므로, 애초에
    # 프로퍼티로 두어 대입하면 그 자리에서 터지게 한다.

    def upcoming_schedules(self, today: date | None = None) -> list["HospitalSchedule"]:
        """아직 지나지 않은 회차. 개최일 순."""
        today = today or date.today()
        return [s for s in self.schedules if s.event_date >= today]

    @property
    def primary_schedule(self) -> "HospitalSchedule | None":
        """대표 회차 — 가장 이른 미래 회차. 전부 지났으면 가장 최근 회차.

        지난 회차라도 돌려주는 이유는, 개최가 끝난 회장의 목록·감사 로그가
        「개최일 없음」으로 보이면 데이터가 사라진 것처럼 읽히기 때문이다.
        """
        if not self.schedules:
            return None
        upcoming = self.upcoming_schedules()
        if upcoming:
            return min(upcoming, key=lambda s: s.event_date)
        return max(self.schedules, key=lambda s: s.event_date)

    @property
    def event_date(self) -> date | None:
        schedule = self.primary_schedule
        return schedule.event_date if schedule else None

    @property
    def event_dates(self) -> list[date]:
        return sorted(s.event_date for s in self.schedules)

    @property
    def booking_close_date(self) -> date | None:
        schedule = self.primary_schedule
        return schedule.booking_close_date if schedule else None

    @property
    def open_time(self) -> time | None:
        schedule = self.primary_schedule
        return schedule.open_time if schedule else None

    @property
    def reception_end_time(self) -> time | None:
        schedule = self.primary_schedule
        return schedule.reception_end_time if schedule else None

    @property
    def schedule_count(self) -> int:
        return len(self.schedules)

    def is_open_for_booking(self, today: date | None = None) -> bool:
        """웹에서 접수를 받는 회차가 하나라도 있는가.

        회차가 하나도 없으면 **받지 않는다.** 예전에는 「마감일이 비어 있는
        회장은 거르지 않는다」였는데, 그때는 개최일이 회장 칸이라 값이 없는
        것과 아직 안 넣은 것을 구별할 수 없었다. 지금은 회차가 없다는 것이
        곧 「열리는 날이 하나도 없다」는 뜻이라 애매할 것이 없다.
        """
        return any(s.is_open_for_booking(today) for s in self.schedules)

    def __repr__(self) -> str:
        return f"<Hospital {self.code} {self.name}>"


class HospitalSchedule(Base):
    """회장이 여는 하루 — **개최 회차**.

    「サンプル会館 A를 2026-07-17 에 연다」가 한 행이다. 같은 회장이
    10월에 또 열면 행이 하나 더 생긴다.
    """

    __tablename__ = "hospital_schedules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    hospital_id: Mapped[int] = mapped_column(
        ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False
    )

    event_date: Mapped[date] = mapped_column(Date, nullable=False, comment="開催日")

    # 이 날을 지나면 웹에서 접수하지 않는다 (원본은 전부 개최일 - 14일).
    booking_close_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="予約終了 — 이 날까지 접수"
    )

    # 개시·접수 종료 시각을 회차에 둔 이유는, 같은 회장이라도 날에 따라
    # 여는 시각이 다르기 때문이다(오전만 여는 날이 있다). 회장에 두면
    # 한 날의 시각을 고치는 것이 다른 날까지 바꾼다.
    open_time: Mapped[time | None] = mapped_column(
        Time, nullable=True, comment="開始時刻"
    )
    reception_end_time: Mapped[time | None] = mapped_column(
        Time, nullable=True, comment="受付終了"
    )

    is_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="이 회차만 감출 때 사용"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    note: Mapped[str] = mapped_column(
        String(200), nullable=False, default="", comment="회차 메모 (오전만 개최 등)"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # --- 정원 그리드 -------------------------------------------------------
    # 30분 × 16칸. 열 이름과 순서는 `app/core/time_grid.py` 가 정한다.
    #
    # `NULL` 은 「그 시간대를 아예 열지 않음」이고 `0` 은 「자리는 있으나
    # 정원이 없음」이다. 원본 마스터의 빈 칸(점심시간 등)이 전자다.
    # 둘을 같게 두면 시트를 다시 내보냈을 때 없던 시간대가 `0` 으로 생긴다.
    cap_0900: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="09:00～09:30 정원"
    )
    cap_0930: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="09:30～10:00 정원"
    )
    cap_1000: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="10:00～10:30 정원"
    )
    cap_1030: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="10:30～11:00 정원"
    )
    cap_1100: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="11:00～11:30 정원"
    )
    cap_1130: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="11:30～12:00 정원"
    )
    cap_1200: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="12:00～12:30 정원"
    )
    cap_1230: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="12:30～13:00 정원"
    )
    cap_1300: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="13:00～13:30 정원"
    )
    cap_1330: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="13:30～14:00 정원"
    )
    cap_1400: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="14:00～14:30 정원"
    )
    cap_1430: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="14:30～15:00 정원"
    )
    cap_1500: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="15:00～15:30 정원"
    )
    cap_1530: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="15:30～16:00 정원"
    )
    cap_1600: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="16:00～16:30 정원"
    )
    cap_1630: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="16:30～17:00 정원"
    )

    # 관리자 강제 마감. 비트 i 가 1이면 i번째 칸이 닫혀 있다.
    #
    # 정원 0 으로 대신하지 않는 이유 — 「정원은 22인데 오늘만 닫음」을
    # 정원 0 으로 적으면 **해제할 때 원래 22를 잃는다.** 휴진일 기능이
    # 하는 일이 정확히 그 켜고 끄기다.
    closed_mask: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="시간대 강제 마감 (16비트)"
    )

    hospital: Mapped[Hospital] = relationship(back_populates="schedules")
    counts: Mapped["ReservationCount | None"] = relationship(
        back_populates="schedule",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="selectin",
    )

    # ----------------------------------------------------------------------
    # 그리드 읽기 · 쓰기
    # ----------------------------------------------------------------------
    # 칼럼을 `getattr` 로 만지는 코드가 여기 말고 다른 곳에 생기면, 격자를
    # 넓힐 때 고칠 자리를 찾지 못한다. 바깥에서는 이 메서드만 쓴다.

    def capacity_at(self, index: int) -> int | None:
        return getattr(self, time_grid.capacity_column(index))

    def set_capacity_at(self, index: int, value: int | None) -> None:
        setattr(self, time_grid.capacity_column(index), value)

    def capacity_row(self) -> list[int | None]:
        return [self.capacity_at(i) for i in time_grid.indexes()]

    def open_indexes(self) -> list[int]:
        """정원이 적혀 있는 칸. 「그 날 실제로 여는 시간대」다."""
        return [i for i in time_grid.indexes() if self.capacity_at(i) is not None]

    def is_closed_at(self, index: int) -> bool:
        return time_grid.is_closed(self.closed_mask, index)

    def is_holiday(self) -> bool:
        """이 날이 **통째로** 닫혔는가. 곧 「갑작스러운 휴진」이다.

        한두 칸만 마감된 날은 휴진이 아니다 — 같은 날 다른 시각으로 옮기면
        되므로 연락할 일이 없다. 여는 칸이 **전부** 닫혀야 그 날 오시기로 한
        분들께 전화를 드려야 한다.

        정원이 한 칸도 없는 날(시간표를 아직 안 넣은 회차)은 휴진이 아니다.
        열었다가 닫은 것과 아직 열지 않은 것은 다른 일이다.

        판정이 여기 하나로 있어야 관리 화면의 「휴진일」 배지·필터와 이용자
        화면의 안내가 어긋나지 않는다. 예전에 관리자 쪽만 고쳤다가 배지는
        붙는데 필터에는 안 걸리는 예약이 생긴 적이 있다.
        """
        opened = self.open_indexes()
        if not opened:
            return False
        return all(self.is_closed_at(i) for i in opened)

    def set_closed_at(self, index: int, closed: bool) -> None:
        self.closed_mask = time_grid.set_closed(self.closed_mask, index, closed)

    @property
    def total_capacity(self) -> int:
        return sum(c for c in self.capacity_row() if c)

    @property
    def slot_count(self) -> int:
        return len(self.open_indexes())

    __table_args__ = (
        # 같은 회장이 같은 날 두 번 열 수는 없다. 시트에 같은 줄이 두 번
        # 들어오는 것이 가장 흔한 실수이므로 DB 에서 막는다.
        UniqueConstraint("hospital_id", "event_date", name="uq_schedule_unique"),
        Index("ix_schedule_hospital", "hospital_id", "event_date"),
        Index("ix_schedule_open", "event_date", "booking_close_date"),
        {"comment": "会場別開催回"},
    )

    # ----------------------------------------------------------------------
    # 파생 값
    # ----------------------------------------------------------------------

    def is_open_for_booking(self, today: date | None = None) -> bool:
        """오늘 웹에서 접수를 받는 회차인가.

        마감일이 비어 있으면 거르지 않는다 — 마스터에 값이 없다는 이유로
        접수를 막으면, 데이터가 덜 들어온 것이 곧 「예약 불가」가 된다.
        개최일이 지난 회차는 마감일과 무관하게 닫는다.
        """
        today = today or date.today()
        if self.event_date < today:
            return False
        if self.booking_close_date is None:
            return True
        return today <= self.booking_close_date

    @property
    def is_past(self) -> bool:
        return self.event_date < date.today()

    @property
    def label(self) -> str:
        """예: 2026-07-17 (09:30～15:00)"""
        if self.open_time and self.reception_end_time:
            return (
                f"{self.event_date.isoformat()} "
                f"({self.open_time.strftime('%H:%M')}～"
                f"{self.reception_end_time.strftime('%H:%M')})"
            )
        return self.event_date.isoformat()

    def __repr__(self) -> str:
        return f"<HospitalSchedule h={self.hospital_id} {self.event_date}>"


class ReservationCount(Base):
    """회차의 실 예약자 수 — 정원 그리드와 **같은 모양**.

    왜 회차 행에 같이 넣지 않는가
    -----------------------------
    한 테이블에 두면 예약이 한 건 들어올 때마다 마스터 행을 잠근다.
    담당자가 정원을 고치는 동안 이용자의 예약이 막히고, 그 반대도 된다.
    나눠 두면 **마스터 편집과 예약 접수가 서로를 기다리지 않는다.**

    이 표는 `reservations` 에서 계산할 수 있는 파생 값이다
    ---------------------------------------------------
    그래서 어긋날 수 있고, 어긋나면 남은 좌석이 전부 틀린다.
    대조·재계산은 스크립트가 상시 맡는다.

        python -m scripts.recount_reservations --check
        python -m scripts.recount_reservations --apply
    """

    __tablename__ = "reservation_counts"

    # 회차와 1:1 이므로 회차 id 를 그대로 기본키로 쓴다. 대리키를 하나 더
    # 두면 「회차에 카운트 행이 둘」인 상태가 만들어질 수 있다.
    schedule_id: Mapped[int] = mapped_column(
        ForeignKey("hospital_schedules.id", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )

    res_0900: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="09:00～09:30 예약 수"
    )
    res_0930: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="09:30～10:00 예약 수"
    )
    res_1000: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="10:00～10:30 예약 수"
    )
    res_1030: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="10:30～11:00 예약 수"
    )
    res_1100: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="11:00～11:30 예약 수"
    )
    res_1130: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="11:30～12:00 예약 수"
    )
    res_1200: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="12:00～12:30 예약 수"
    )
    res_1230: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="12:30～13:00 예약 수"
    )
    res_1300: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="13:00～13:30 예약 수"
    )
    res_1330: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="13:30～14:00 예약 수"
    )
    res_1400: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="14:00～14:30 예약 수"
    )
    res_1430: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="14:30～15:00 예약 수"
    )
    res_1500: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="15:00～15:30 예약 수"
    )
    res_1530: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="15:30～16:00 예약 수"
    )
    res_1600: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="16:00～16:30 예약 수"
    )
    res_1630: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="16:30～17:00 예약 수"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    schedule: Mapped[HospitalSchedule] = relationship(back_populates="counts")

    __table_args__ = ({"comment": "開催回別時間帯予約数 (reservations から派生)"},)

    # ----------------------------------------------------------------------

    def reserved_at(self, index: int) -> int:
        return getattr(self, time_grid.reserved_column(index)) or 0

    def set_reserved_at(self, index: int, value: int) -> None:
        setattr(self, time_grid.reserved_column(index), max(0, value))

    def add_at(self, index: int, delta: int) -> int:
        """한 칸을 증감하고 결과를 돌려준다. 음수로 내려가지 않는다."""
        value = max(0, self.reserved_at(index) + delta)
        self.set_reserved_at(index, value)
        return value

    def reserved_row(self) -> list[int]:
        return [self.reserved_at(i) for i in time_grid.indexes()]

    @property
    def total_reserved(self) -> int:
        return sum(self.reserved_row())

    def __repr__(self) -> str:
        return f"<ReservationCount s={self.schedule_id} {self.total_reserved}名>"
