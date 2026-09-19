"""본인 확인(U-11) 요청·응답 스키마."""

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.text_utils import (
    is_fullwidth_katakana,
    normalize_code,
    normalize_kana,
    normalize_name,
)


class VerifyStatus(str, Enum):
    """본인 확인 결과.

    모든 결과가 「정상 처리」이므로 HTTP 200 으로 반환한다.
    입력값 자체가 잘못된 경우(필수 누락 등)만 422 검증 오류가 된다.
    """

    ELIGIBLE = "ELIGIBLE"                  # 검진 대상자 · 예약 가능 → 다음 단계로
    ALREADY_RESERVED = "ALREADY_RESERVED"  # 검진 대상자 · 이미 예약 있음
    NOT_ELIGIBLE = "NOT_ELIGIBLE"          # 명부에 없음 → 검진 대상자 아님
    KANA_MISMATCH = "KANA_MISMATCH"        # 한자는 일치하나 후리가나가 다름
    GENDER_MISMATCH = "GENDER_MISMATCH"    # 성명은 일치하나 성별이 다름
    AMBIGUOUS = "AMBIGUOUS"                # 완전 일치가 2명 이상 → 담당자 확인 필요


class VerifyRequest(BaseModel):
    """본인 확인 입력.

    성명은 성(姓)·이름(名)을 분리해 받고, 후리가나도 각각 받는다.
      한자   : 성 田中 / 이름 太郎
      후리가나: 성 タナカ / 이름 タロウ  ← 전각 가타카나

    대조 키는 「성(한자) + 이름(한자) + **성 후리가나 + 이름 후리가나**
    + 생년월일 + 건강보험증(보험자 번호/기호/번호)」이다.
    (plan.md BR-01 텍스트에 의한 간이 확인)

    후리가나도 대조 키에 포함한다. 일본어는 같은 한자라도 읽는 법이 다르면
    다른 사람이므로(中田 = ナカタ / ナカダ), 후리가나를 빼면 동성동명인
    두 사람을 구별하지 못해 오식별이 발생한다.
    자세한 근거는 services/verify_service.py 상단 주석 참조.
    """

    # min_length 제약을 두지 않는다. 제약이 먼저 걸리면 Pydantic 의 영문 기본
    # 메시지가 그대로 이용자에게 노출되므로, 아래 검증기에서 한국어로 안내한다.
    last_name: str = Field(..., max_length=60, description="姓（漢字） 例: 田中")
    first_name: str = Field(..., max_length=60, description="名（漢字） 例: 太郎")
    last_name_kana: str = Field(
        ..., max_length=60, description="姓フリガナ（全角カタカナ） 例: タナカ"
    )
    first_name_kana: str = Field(
        ..., max_length=60, description="名フリガナ（全角カタカナ） 例: タロウ"
    )

    # 미들네임 — 외국인 전용. 해당자만 입력하므로 임의 항목이다.
    # 후리가나도 임의 항목이며, 입력했다면 형식만 검사한다.
    middle_name: str = Field("", max_length=120, description="ミドルネーム（表記）")
    middle_name_kana: str = Field(
        "", max_length=120, description="ミドルネームフリガナ（全角カタカナ）"
    )

    gender: Literal["M", "F"] = Field(
        ..., description="性別 M=男性 F=女性（戸籍上の性別）"
    )
    birth_date: date = Field(..., description="生年月日 (西暦 YYYY-MM-DD)")

    insurer_no: str = Field(..., max_length=20, description="保険者番号")
    insurance_symbol: str = Field(..., max_length=20, description="記号")
    insurance_no: str = Field(..., max_length=20, description="番号")

    # --- 한자 성명 -------------------------------------------------------

    @field_validator("last_name")
    @classmethod
    def _check_last_name(cls, v: str) -> str:
        v = v.strip()
        if not normalize_name(v):
            raise ValueError("姓を漢字で入力してください。")
        return v

    @field_validator("first_name")
    @classmethod
    def _check_first_name(cls, v: str) -> str:
        v = v.strip()
        if not normalize_name(v):
            raise ValueError("名を漢字で入力してください。")
        return v

    # --- 후리가나 --------------------------------------------------------
    # 반각 가타카나·히라가나로 들어와도 전각 가타카나로 자동 변환한 뒤 검사한다.

    @field_validator("last_name_kana")
    @classmethod
    def _check_last_name_kana(cls, v: str) -> str:
        v = normalize_kana(v)
        if not v:
            raise ValueError("姓のフリガナを全角カタカナで入力してください。")
        if not is_fullwidth_katakana(v):
            raise ValueError(
                "姓のフリガナは全角カタカナのみで入力してください。（例: タナカ）"
            )
        return v

    @field_validator("first_name_kana")
    @classmethod
    def _check_first_name_kana(cls, v: str) -> str:
        v = normalize_kana(v)
        if not v:
            raise ValueError("名のフリガナを全角カタカナで入力してください。")
        if not is_fullwidth_katakana(v):
            raise ValueError(
                "名のフリガナは全角カタカナのみで入力してください。（例: タロウ）"
            )
        return v

    # --- 미들네임 (임의) --------------------------------------------------
    # 해당자만 입력하므로 비어 있으면 그대로 통과시킨다.

    @field_validator("middle_name")
    @classmethod
    def _clean_middle_name(cls, v: str) -> str:
        return (v or "").strip()

    @field_validator("middle_name_kana")
    @classmethod
    def _check_middle_name_kana(cls, v: str) -> str:
        v = normalize_kana(v)
        if not v:
            return ""
        if not is_fullwidth_katakana(v):
            raise ValueError(
                "ミドルネームのフリガナは全角カタカナのみで入力してください。（例: ウィリアム）"
            )
        return v

    # --- 보험증 · 생년월일 -----------------------------------------------

    @field_validator("insurer_no", "insurance_symbol", "insurance_no")
    @classmethod
    def _normalize_card(cls, v: str) -> str:
        v = normalize_code(v)
        if not v:
            raise ValueError("健康保険証の番号を入力してください。")
        return v

    @field_validator("birth_date")
    @classmethod
    def _not_future(cls, v: date) -> date:
        from datetime import date as _date

        if v > _date.today():
            raise ValueError("生年月日が正しくありません。")
        return v


class ContactInfo(BaseModel):
    """문의처. 검진 대상자가 아닌 경우 화면에 안내한다."""

    tel: str
    email: str
    hours: str


class VerifiedPerson(BaseModel):
    """확인된 대상자 정보. 다음 단계 폼의 초기값으로 사용한다."""

    last_name: str
    first_name: str
    last_name_kana: str
    first_name_kana: str
    full_name: str
    full_name_kana: str
    middle_name: str
    middle_name_kana: str
    gender: str
    gender_label: str
    birth_date: date
    insurance_card_no: str


class VerifyResponseData(BaseModel):
    status: VerifyStatus
    # 화면 제목·본문·원인 안내를 서버가 결정한다.
    # 결과 종류가 늘어나도 프런트를 고치지 않아도 되게 하기 위함이다.
    title: str
    message: str
    hints: list[str] = []
    person: VerifiedPerson | None = None
    # 예약번호는 이 응답에 **절대 담지 않는다.**
    # 여기 입력하는 값(성명·생년월일·보험증)은 가족이나 동거인이라면 알 수 있다.
    # 그것만으로 예약번호가 나오면 예약 조회(U-20)가 통째로 열린다.
    # (services/verify_service.py 의 ALREADY_RESERVED 분기 참조)
    contact: ContactInfo | None = None
    # ELIGIBLE 인 경우에만 발급. 다음 단계에서 본인 확인 통과를 증명한다.
    verify_token: str | None = None


class VerifyResponse(BaseModel):
    success: bool = True
    data: VerifyResponseData
