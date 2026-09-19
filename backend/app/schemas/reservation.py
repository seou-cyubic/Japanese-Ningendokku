"""예약 확정(U-17) 요청·응답 스키마."""

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.email_utils import EmailInvalid, normalize_email
from app.core.text_utils import format_phone, normalize_code


class ReservationErrorCode(str, Enum):
    """예약을 받을 수 없는 이유 (plan.md §10.3).

    이용자에게는 「무엇이 잘못됐는지」가 아니라 「이제 무엇을 하면 되는지」를
    보여 준다. 화면 문구는 서버가 결정해서 내려보낸다.
    """

    VERIFY_REQUIRED = "VERIFY_REQUIRED"            # 본인 확인 토큰 없음·만료
    SLOT_NOT_FOUND = "SLOT_NOT_FOUND"              # 슬롯이 사라짐
    SLOT_FULL = "SLOT_FULL"                        # 방금 만석이 됨
    SLOT_CLOSED = "SLOT_CLOSED"                    # 관리자가 마감함
    SLOT_PAST = "SLOT_PAST"                        # 이미 지난 시간
    BOOKING_CLOSED = "BOOKING_CLOSED"              # 그 회장의 접수 마감일이 지남
    DUPLICATE_RESERVATION = "DUPLICATE_RESERVATION"  # 당해 연도 중복 (BR-03)


class ReservationOptionInput(BaseModel):
    """이용자가 고른 옵션 검사. 신뢰하는 것은 `id` 뿐이다."""

    id: int


class ReservationCreateRequest(BaseModel):
    """예약 확정 요청.

    성명·성별·생년월일·보험증은 **받지 않는다.**
    본인 확인(U-11)을 통과한 대상자의 명부 값을 서버가 그대로 복사한다.
    화면에서 보내온 값을 믿으면 확인을 통과한 사람과 예약자가 달라질 수 있다.
    """

    verify_token: str = Field(..., description="U-11 で発行された本人確認トークン")
    slot_id: int = Field(..., description="予約する枠 ID")

    postal_code: str = Field(..., max_length=10, description="郵便番号 (例: 101-0021)")
    address: str = Field(..., max_length=255, description="住所")
    address_detail: str = Field(..., max_length=255, description="番地")
    building: str = Field("", max_length=255, description="アパート・マンション名 [任意]")

    tel_mobile: str = Field("", max_length=30, description="携帯電話")
    tel_home: str = Field("", max_length=30, description="固定電話")
    email: str = Field("", max_length=255, description="メールアドレス [任意]")

    options: list[ReservationOptionInput] = Field(default_factory=list)

    # --- 필수 항목 (BR-05) ------------------------------------------------

    @field_validator("postal_code")
    @classmethod
    def _check_postal(cls, v: str) -> str:
        digits = "".join(ch for ch in normalize_code(v) if ch.isdigit())
        if len(digits) != 7:
            raise ValueError("郵便番号は数字7桁です。(例: 101-0021)")
        return f"{digits[:3]}-{digits[3:]}"

    @field_validator("address")
    @classmethod
    def _check_address(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("住所を入力してください。")
        return v

    @field_validator("address_detail")
    @classmethod
    def _check_address_detail(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("番地を入力してください。")
        return v

    @field_validator("building")
    @classmethod
    def _strip(cls, v: str) -> str:
        return (v or "").strip()

    @field_validator("tel_mobile", "tel_home")
    @classmethod
    def _format_phone(cls, v: str) -> str:
        # 予約画面は3つの欄に分かれているので必ずハイフンが入るが、
        # 郵送・管理画面と同じ規則を通しておく(core/text_utils.py)。
        return format_phone(v)

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        # 임의 항목이므로 비어 있으면 통과. 적었다면 형식을 본다.
        # 검증은 email-validator 에 맡긴다. 정규식을 직접 짜면 반드시 틀린다.
        # (core/email_utils.py 에 이유를 적어 두었다)
        try:
            return normalize_email(v)
        except EmailInvalid as exc:
            raise ValueError(str(exc)) from exc

    @model_validator(mode="after")
    def _require_one_phone(self) -> "ReservationCreateRequest":
        # 전화번호는 둘 중 최소 1개가 필수다 (BR-05).
        # 항목 하나만으로는 판정할 수 없어 필드 검증기가 아니라 여기서 본다.
        if not self.tel_mobile and not self.tel_home:
            raise ValueError(
                "携帯電話と固定電話のどちらかを入力してください。"
                "連絡が取れないと予約を確定できません。"
            )
        return self


class ReservedHospital(BaseModel):
    id: int
    name: str
    address: str
    tel: str
    access_info: str


class ReservedOption(BaseModel):
    code: str
    name: str


class ReservationResult(BaseModel):
    """예약 완료 화면(U-17)이 그대로 그릴 수 있는 형태로 내려준다."""

    reservation_no: str
    status: str

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

    # 메일을 실제로 보냈는지. 완료 화면의 안내 문구가 갈린다.
    mail_sent: bool = False
    mail_message: str = ""

    contact_tel: str = ""
    contact_email: str = ""
    contact_hours: str = ""


class ReservationCreateResponse(BaseModel):
    success: bool = True
    data: ReservationResult
