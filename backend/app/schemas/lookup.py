"""예약 조회 스키마 (U-20).

**읽기 전용이다.** 이 파일에는 요청 본문 스키마가 없다.
받는 것은 예약번호 하나뿐이라 쿼리 파라미터로 충분하고,
고칠 수 있는 것이 없으므로 수정 요청 스키마도 만들지 않는다.
"""

from datetime import date

from pydantic import BaseModel

from app.schemas.reservation import ReservedHospital, ReservedOption


class LookupResult(BaseModel):
    """조회 화면(U-22)이 그대로 그릴 수 있는 형태.

    예약 완료 화면(U-17)과 항목이 거의 같다. 「예약하고 나서 본 화면」과
    「나중에 확인한 화면」이 다르게 생기면 같은 예약인지 의심하게 된다.
    """

    reservation_no: str

    # 확정 / 임시 / 취소. 라벨은 서버가 정해 내려 준다.
    status: str
    status_label: str

    # 검진일이 통째로 휴진이 되었는가.
    # 상태(status)와는 별개다 — 예약은 살아 있고 날짜만 못 쓰게 된 것이라,
    # 「취소」로 내리면 이용자가 예약이 없어진 줄 안다.
    is_holiday: bool = False

    full_name: str
    full_name_kana: str
    gender_label: str
    birth_date: date

    hospital: ReservedHospital
    slot_date: date
    weekday: str
    time_label: str

    postal_code: str
    address: str
    address_detail: str
    building: str
    tel_mobile: str
    tel_home: str
    email: str

    options: list[ReservedOption] = []

    # 접수 경로 (웹 / 우편). 우편 접수 건은 이용자가 신청서를 낸 기억과
    # 화면이 이어지도록 그 사실을 적어 준다.
    channel: str
    channel_label: str

    # --- 안내 --------------------------------------------------------------
    # 「고칠 수 없다」로 끝내지 않고 「어떻게 하면 되는지」를 함께 내려 준다.
    # 화면마다 문구를 박아 두면 규칙이 바뀔 때 한 곳이 남는다. (BR-10 / P-9)
    change_notice: str = ""
    cancel_deadline_days: int = 3

    contact_tel: str = ""
    contact_email: str = ""
    contact_hours: str = ""

    # 검진 시각 + 유예가 지나면 기록이 지워진다. 언제까지 볼 수 있는지 알린다.
    viewable_until: str = ""


class LookupResponse(BaseModel):
    success: bool = True
    data: LookupResult
