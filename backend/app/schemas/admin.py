"""관리 화면(A-00 ~ A-60) 요청·응답 스키마.

응답은 전부 `{ "success": true, "data": ... }` 규약을 따른다 (plan.md §10.3).
목록 화면은 `items` + `total` + `page` 형태로 통일한다.
"""

import re
from datetime import date, datetime, time
from typing import Any, Generic, Literal, TypeVar

from app.core.email_utils import EmailInvalid, normalize_email
from app.core.text_utils import format_phone
from pydantic import BaseModel, Field, field_validator

T = TypeVar("T")


# ==========================================================================
# 공통
# ==========================================================================


class Ok(BaseModel):
    """데이터가 필요 없는 조작의 응답."""

    success: bool = True
    message: str = ""


class MailResendResponse(Ok):
    """메일 재발송. 요청은 처리됐어도 **실제로 나갔는지**는 따로 알린다."""

    delivered: bool = False


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.size))


# ==========================================================================
# A-00 로그인
# ==========================================================================


class LoginRequest(BaseModel):
    login_id: str = Field(..., max_length=60)
    password: str = Field(..., max_length=200)

    @field_validator("login_id")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("ログインIDを入力してください。")
        return v

    @field_validator("password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        if not v:
            raise ValueError("パスワードを入力してください。")
        return v


class AdminMe(BaseModel):
    """로그인한 관리자 정보. 화면은 이 값으로 메뉴를 구성한다."""

    id: int
    login_id: str
    name: str
    email: str
    role: str
    role_label: str
    level: int
    last_login_at: datetime | None = None


class LoginResponse(BaseModel):
    success: bool = True
    data: AdminMe


# ==========================================================================
# A-01 대시보드
# ==========================================================================


class DashboardCounter(BaseModel):
    key: str
    label: str
    value: int
    unit: str = "件"
    tone: Literal["neutral", "primary", "warn", "danger"] = "neutral"
    hint: str = ""
    link: str = ""


class DashboardTodayRow(BaseModel):
    hospital_id: int
    hospital_name: str
    reserved: int
    capacity: int
    remaining: int


class DashboardMailFailure(BaseModel):
    id: int
    reservation_no: str
    to_email: str
    template_label: str
    error_message: str
    sent_at: datetime
    # 「지금 처리할 일」에서 확인 전화 건과 한 줄로 섞이므로,
    # 같은 기준(검진일까지 며칠)으로 줄을 세울 수 있어야 한다.
    full_name: str = ""
    slot_date: date | None = None


class DashboardRecent(BaseModel):
    id: int
    reservation_no: str
    full_name: str
    hospital_name: str
    slot_date: date
    time_label: str
    channel: str
    # 화면이 색을 고를 때 쓴다. `channel` 은 사람이 읽는 라벨이라
    # 문구를 다듬는 순간 색 판정이 조용히 깨진다.
    channel_code: str = ""
    status: str
    # 「무엇이 빠졌는지」. 「임시 (확인 필요)」라고만 하면 담당자가 예약을
    # 열어 봐야 알 수 있다. 목록에서 바로 보이면 전화하기 전에 준비가 된다.
    defect_note: str = ""
    # 전화 응대가 이 시스템의 주 업무다(변경·취소가 전화로만 된다).
    # 목록에서 번호가 바로 보이면 예약을 열지 않고도 걸 수 있다.
    tel: str = ""
    created_at: datetime


class DashboardAgeBucket(BaseModel):
    label: str
    male: int
    female: int


class DashboardGenderStats(BaseModel):
    male: int
    female: int
    age_buckets: list[DashboardAgeBucket]


class DashboardChannelStats(BaseModel):
    web: int
    postal: int
    # 受付の内訳(취소를 뺀 Web·郵送 + 취소)을 그리기 위한 값. web/postal 은 취소 포함.
    web_cancelled: int = 0
    postal_cancelled: int = 0
    web_pending: int = 0
    postal_pending: int = 0


class DashboardStatusStats(BaseModel):
    confirmed: int
    pending: int
    cancelled: int
    # 취소의 내역. 둘을 더해도 cancelled 와 다를 수 있다 —
    # 구분이 생기기 전에 취소된 건은 어느 쪽도 아니다.
    cancelled_advance: int = 0
    cancelled_same_day: int = 0
    total: int


class DashboardOptionStat(BaseModel):
    code: str
    name: str
    count: int
    percentage: int


class DashboardSeriesPoint(BaseModel):
    label: str
    count: int


class DashboardSeries(BaseModel):
    # 健診統計의 곡선. 하루면 시간대별, 31일 이하면 날짜별, 넘으면 월별.
    # CSV 의 日別/月別 규칙과 같다.
    kind: Literal["hour", "day", "month"]
    label: str
    points: list[DashboardSeriesPoint]
    start: date | None = None
    end: date | None = None


class DashboardData(BaseModel):
    counters: list[DashboardCounter]
    today: date
    today_rows: list[DashboardTodayRow]
    attention: list[DashboardRecent]     # 대응이 필요한 예약 (임시·불비)
    # 휴진으로 닫힌 날에 남아 있는 예약. 연락하지 않으면 그 날 회장에 온다.
    holiday: list[DashboardRecent] = []
    recent: list[DashboardRecent]        # 최근 접수
    mail_failures: list[DashboardMailFailure]

    # 목록은 앞의 몇 건만 내려준다. 화면이 「30건 중 5건」처럼 적으려면
    # 전체 건수를 따로 알아야 한다.
    attention_total: int = 0
    holiday_total: int = 0
    holiday_urgent_total: int = 0
    mail_failed_total: int = 0
    # 검진일이 코앞인 건. 30건이 밀려 있어도 먼저 손대야 할 것은 이쪽이다.
    urgent_total: int = 0
    # 오늘 검진이 없을 때 「그럼 언제인가」에 답한다.
    next_exam_date: date | None = None

    purge_pending: int                   # 다음 정리에서 삭제될 예약 수
    purge_grace_minutes: int
    # 최근 24시간 메일 발송 실적. 화면의 「送信成功率」이 쓴다.
    # SKIPPED(메일 미설정으로 보내지 않음)는 성공에도 실패에도 넣지 않는다.
    # 넣으면 「설정을 안 해서 안 보냈다」가 「실패했다」로 읽힌다.
    mail_24h_success: int = 0
    mail_24h_failed: int = 0
    mail_24h_skipped: int = 0
    # 健診統計에서 고른 기간(日別·週別·月別)의 메일 발송 실적. 기준은 발송 일시.
    mail_period_success: int = 0
    mail_period_failed: int = 0
    mail_period_skipped: int = 0
    # 같은 기간에 자동 삭제된 예약 수. 조작 로그(RESERVATION_PURGE)의 deleted 를 더한다.
    purge_period_deleted: int = 0
    gender_stats: DashboardGenderStats | None = None
    channel_stats: DashboardChannelStats | None = None
    status_stats: DashboardStatusStats | None = None
    options: list[DashboardOptionStat] | None = None
    stats_series: DashboardSeries | None = None


class DashboardResponse(BaseModel):
    success: bool = True
    data: DashboardData


# ==========================================================================
# A-10 / A-11 예약
# ==========================================================================


class ReservationRow(BaseModel):
    """예약 목록 1행."""

    id: int
    reservation_no: str
    status: str
    status_label: str
    channel: str
    channel_label: str

    full_name: str
    full_name_kana: str
    gender_label: str
    birth_date: date

    hospital_id: int
    hospital_name: str
    slot_date: date
    time_label: str

    tel_primary: str
    email: str

    has_defect: bool
    contact_count: int
    # 한 번이라도 통화가 됐는가. 횟수만 보내면 목록이 「3회 부재중」과
    # 「통화 후 유지」를 가릴 수 없어, 모두 「応答なし」로 보인다.
    contact_connected: bool = False

    # 이 예약의 시간대가 회차에서 닫혀 있는가(휴진). 목록·상세에 배지로 뜬다.
    # 담당자가 전화로 새 날짜를 잡아 옮기면 저절로 꺼진다 — 따로 지울 것이 없다.
    is_holiday: bool = False

    # 신청한 옵션 검사. 개수와 이름을 함께 준다 — 목록에서 「무엇을
    # 신청했는가」가 보여야 상세를 열지 않고 답할 수 있다.
    option_count: int
    option_names: list[str] = []

    created_at: datetime


class ReservationContactRow(BaseModel):
    id: int
    contacted_at: datetime
    admin_name: str
    method: str
    method_label: str
    result: str
    result_label: str
    memo: str


class ReservationMailRow(BaseModel):
    id: int
    template_key: str
    template_label: str
    to_email: str
    subject: str
    status: str
    status_label: str
    error_message: str
    sent_at: datetime


class ReservationDetail(ReservationRow):
    """예약 상세. 목록 항목에 입력값 전체를 더한 것."""

    last_name: str
    first_name: str
    last_name_kana: str
    first_name_kana: str
    middle_name: str
    middle_name_kana: str
    gender: str

    insurer_no: str
    insurance_symbol: str
    insurance_no: str

    postal_code: str
    address: str
    address_detail: str
    building: str
    tel_mobile: str
    tel_home: str

    slot_id: int
    start_time: str
    end_time: str
    hospital_tel: str
    hospital_address: str

    fiscal_year: int
    memo: str
    defect_note: str
    cancelled_at: datetime | None = None
    cancel_reason: str = ""
    cancel_type: str = ""
    cancel_type_label: str = ""
    created_by: str = ""

    options: list[dict] = []
    contacts: list[ReservationContactRow] = []
    mails: list[ReservationMailRow] = []

    expires_at: datetime | None = None  # 이 시각에 자동 삭제된다


class ReservationSearchResponse(BaseModel):
    success: bool = True
    data: Page[ReservationRow]


class ReservationDetailResponse(BaseModel):
    success: bool = True
    data: ReservationDetail


class ReservationUpdateRequest(BaseModel):
    """예약 상세 수정 (A-11).

    수검자 정보(성명, 생년월일 등) 수정은 오탈자 정정 목적으로만 허용한다.
    실제로 다른 사람의 예약이라면 이 예약을 취소하고 새로 접수하도록 UI에서 안내한다.
    """

    last_name: str | None = Field(None, max_length=60)
    first_name: str | None = Field(None, max_length=60)
    last_name_kana: str | None = Field(None, max_length=60)
    first_name_kana: str | None = Field(None, max_length=60)
    middle_name: str | None = Field(None, max_length=120)
    middle_name_kana: str | None = Field(None, max_length=120)
    gender: Literal["M", "F"] | None = None
    birth_date: date | None = None
    insurer_no: str | None = Field(None, max_length=30)
    insurance_symbol: str | None = Field(None, max_length=30)
    insurance_no: str | None = Field(None, max_length=30)

    postal_code: str = Field("", max_length=10)
    address: str = Field("", max_length=255)
    address_detail: str = Field("", max_length=255)
    building: str = Field("", max_length=255)
    tel_mobile: str = Field("", max_length=30)
    tel_home: str = Field("", max_length=30)
    email: str = Field("", max_length=255)

    slot_id: int | None = Field(None, description="受診日時を変更する場合の新しいスロット ID")

    # 일시를 옮겼을 때만 본다. 담당자는 전화로 새 날짜를 합의한 뒤 화면에서
    # 옮기므로, 메일은 **합의 내용을 남기는 확인용**이다. 그래서 자동이
    # 아니라 「보낼까요」에 사람이 답한다.
    notify_change: bool = Field(
        False, description="日時変更後に「受診日変更案内」メールを送信するかどうか"
    )

    status: Literal["CONFIRMED", "PENDING"] | None = None
    has_defect: bool | None = None
    defect_note: str = Field("", max_length=255)
    memo: str = ""

    option_ids: list[int] | None = None

    @field_validator("tel_mobile", "tel_home")
    @classmethod
    def _format_phone(cls, v):
        # 하이픈 없이 적어도 저장할 때 표기를 맞춘다. 시외국번 길이를
        # 알 수 없는 번호는 적은 그대로 둔다(core/text_utils.py 참조).
        return format_phone(v if isinstance(v, str) else v)
    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        # 스태프가 대신 입력하는 값이라 오타를 본인이 확인해 줄 수 없다.
        # 형식 검증은 이용자 화면과 같은 기준으로 건다. (core/email_utils.py)
        try:
            return normalize_email(v)
        except EmailInvalid as exc:
            raise ValueError(str(exc)) from exc


class ReservationCancelRequest(BaseModel):
    reason: str = Field("", max_length=255)
    # ADVANCE  事前キャンセル — 本人からの電話などで事前に取り消し
    # SAME_DAY 当日キャンセル — 連絡が取れないなど当日に確認された取り消し
    cancel_type: Literal["ADVANCE", "SAME_DAY"] = "ADVANCE"


class ContactCreateRequest(BaseModel):
    method: Literal["TEL", "MAIL"] = "TEL"
    result: Literal["CONNECTED", "NO_ANSWER"] = "NO_ANSWER"
    memo: str = ""


# ==========================================================================
# A-13 우편 접수 입력
# ==========================================================================


class PostalReservationRequest(BaseModel):
    """우편 신청서 대리 등록.

    웹 예약과 달리 **본인 확인을 강제하지 않는다.** 스태프가 종이 신청서를
    보고 입력하는 화면이며, 명부에 없는 사람도 등록할 수 있어야 한다.
    명부와 연결되면 `target_person_id` 를 채워 중복 판정 정확도를 높인다.

    희망 슬롯은 제1~제3희망까지 받는다. 제1희망이 만석이면 그 자리에서
    다음 희망으로 넘어가야 하기 때문이다 (자체 피드백 M-2).
    """

    last_name: str = Field(..., max_length=60)
    first_name: str = Field(..., max_length=60)
    last_name_kana: str = Field("", max_length=60)
    first_name_kana: str = Field("", max_length=60)
    middle_name: str = Field("", max_length=120)
    middle_name_kana: str = Field("", max_length=120)

    gender: Literal["M", "F"]
    birth_date: date

    insurer_no: str = Field("", max_length=30)
    insurance_symbol: str = Field("", max_length=30)
    insurance_no: str = Field("", max_length=30)

    postal_code: str = Field("", max_length=10)
    address: str = Field("", max_length=255)
    address_detail: str = Field("", max_length=255)
    building: str = Field("", max_length=255)

    tel_mobile: str = Field("", max_length=30)
    tel_home: str = Field("", max_length=30)
    email: str = Field("", max_length=255)

    slot_ids: list[int] = Field(
        default_factory=list, description="希望スロット (第1希望から順に)"
    )
    option_ids: list[int] = Field(default_factory=list)

    # 불비가 있어도 일단 등록해 두고 나중에 연락한다 (BR-06)
    allow_defect: bool = Field(
        False, description="必須項目が空であっても仮受付 (PENDING) として登録する"
    )
    memo: str = ""

    @field_validator("tel_mobile", "tel_home")
    @classmethod
    def _format_phone(cls, v):
        # 하이픈 없이 적어도 저장할 때 표기를 맞춘다. 시외국번 길이를
        # 알 수 없는 번호는 적은 그대로 둔다(core/text_utils.py 참조).
        return format_phone(v if isinstance(v, str) else v)
    @field_validator("birth_date")
    @classmethod
    def _not_future(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("生年月日が正しくありません。")
        return v

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        # 스태프가 대신 입력하는 값이라 오타를 본인이 확인해 줄 수 없다.
        # 형식 검증은 이용자 화면과 같은 기준으로 건다. (core/email_utils.py)
        try:
            return normalize_email(v)
        except EmailInvalid as exc:
            raise ValueError(str(exc)) from exc


class PostalReservationResult(BaseModel):
    id: int
    reservation_no: str
    status: str
    status_label: str
    hospital_name: str
    slot_date: date
    time_label: str
    used_choice: int          # 몇 번째 희망으로 잡혔는지
    skipped: list[str] = []   # 건너뛴 희망과 그 이유
    has_defect: bool
    defect_note: str
    message: str


class PostalReservationResponse(BaseModel):
    success: bool = True
    data: PostalReservationResult


class PostalBulkRow(BaseModel):
    """스프레드시트에서 넘어오는 우편 접수 한 행.

    셀 값은 일부러 ``Any`` 로 받는다. 날짜·성별처럼 형식이 틀린 셀을
    Pydantic 이 요청 입구에서 먼저 거절하면 어느 ``row_no`` 의 어느 셀이
    잘못됐는지 일괄 검증 결과에 담을 수 없기 때문이다. 실제 형식·길이·업무
    규칙 검증은 ``admin_reservation_service`` 에서 모든 행을 모아 수행한다.
    """

    row_no: Any = None

    last_name: Any = ""
    first_name: Any = ""
    last_name_kana: Any = ""
    first_name_kana: Any = ""
    middle_name: Any = ""
    middle_name_kana: Any = ""
    gender: Any = ""
    birth_date: Any = ""

    insurer_no: Any = ""
    insurance_symbol: Any = ""
    insurance_no: Any = ""

    postal_code: Any = ""
    address: Any = ""
    address_detail: Any = ""
    building: Any = ""
    tel_mobile: Any = ""
    tel_home: Any = ""
    email: Any = ""

    # [{rank: 1, hospital: "H001 또는 회장명", date: "YYYY-MM-DD", time: "HH:MM"}]
    wishes: Any = Field(default_factory=list)
    # ["OP01", "OP02"] 또는 Excel 붙여넣기에서 쓰기 쉬운 "OP01;OP02"
    option_codes: Any = Field(default_factory=list)
    allow_defect: Any = False
    memo: Any = ""
    @field_validator("tel_mobile", "tel_home")
    @classmethod
    def _format_phone(cls, v):
        # 하이픈 없이 적어도 저장할 때 표기를 맞춘다. 시외국번 길이를
        # 알 수 없는 번호는 적은 그대로 둔다(core/text_utils.py 참조).
        return format_phone(v if isinstance(v, str) else v)


class PostalBulkRequest(BaseModel):
    rows: list[PostalBulkRow] = Field(..., min_length=1, max_length=200)


class PostalBulkFieldError(BaseModel):
    row_no: int
    field: str
    message: str


class PostalBulkError(BaseModel):
    code: Literal["BULK_VALIDATION_FAILED"] = "BULK_VALIDATION_FAILED"
    message: str = "入力内容をご確認ください。"


class PostalBulkErrorResponse(BaseModel):
    success: Literal[False] = False
    error: PostalBulkError = Field(default_factory=PostalBulkError)
    errors: list[PostalBulkFieldError]


class PostalBulkReservationResult(PostalReservationResult):
    row_no: int


class PostalBulkResult(BaseModel):
    created_count: int
    rows: list[PostalBulkReservationResult]


class PostalBulkResponse(BaseModel):
    success: bool = True
    data: PostalBulkResult


# --------------------------------------------------------------------------
# 일괄 입력 표의 파일 입출력 (CSV / Excel)
# --------------------------------------------------------------------------
# 화면과 주고받는 단위는 **열 키를 그대로 쓴 평탄한 행**이다.
# 열 라벨·순서·파일 서식은 `postal_sheet_service` 한 곳에만 있다.


class PostalSheetExportRequest(BaseModel):
    """내보낼 표. 행이 비어 있으면 제목 줄만 있는 빈 서식이 된다.

    값을 ``Any`` 로 받는 이유는 일괄 등록(`PostalBulkRow`)과 같다. 그리드는
    아직 검증되지 않은 값을 담고 있고, **검증 전에도 파일로 뽑을 수 있어야**
    한다. 형식이 틀렸다고 내보내기를 막으면 「고치려고 Excel 로 꺼내는」
    가장 흔한 사용법이 막힌다.
    """

    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=200)

    @field_validator("rows")
    @classmethod
    def _limit_cells(cls, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for row in rows:
            if len(row) > 64:
                raise ValueError("1行の列が多すぎます。")
        return rows


class PostalSheetImportSummary(BaseModel):
    """무엇을 어떻게 읽었는지. 화면이 그대로 사람에게 보여 준다."""

    file_name: str
    kind: Literal["CSV", "XLSX"]
    encoding: str = ""      # CSV 만
    sheet_name: str = ""    # Excel 만
    header_mode: Literal["HEADER", "POSITIONAL"]
    total_rows: int
    blank_rows: int
    matched_columns: int
    ignored_columns: list[str] = []
    warnings: list[str] = []


class PostalSheetImportResult(BaseModel):
    rows: list[dict[str, str]]
    summary: PostalSheetImportSummary


class PostalSheetImportResponse(BaseModel):
    success: bool = True
    data: PostalSheetImportResult


# ==========================================================================
# A-20 / A-21 회장
# ==========================================================================


class ScheduleRow(BaseModel):
    """회장이 여는 하루 — 관리 화면용.

    회장 목록·상세가 「이 회장이 언제 여는가」를 답하려면 이 목록이
    필요하다. 예전에는 회장 한 행에 개최일 한 칸이었다.
    """

    id: int
    hospital_id: int
    event_date: date
    weekday: str
    booking_close_date: date | None = None
    open_time: time | None = None
    reception_end_time: time | None = None
    is_visible: bool = True
    note: str = ""

    slot_count: int = 0
    capacity: int = 0
    reserved: int = 0
    remaining: int = 0

    is_booking_open: bool = False
    is_past: bool = False

    # 휴진 표시용. 달력이 **다른 회장**의 칸을 그릴 때도 이 값을 본다.
    # 없으면 회장을 바꾸는 순간 휴진 표시가 사라진다.
    closed_slots: int = 0
    is_all_closed: bool = False


class HospitalRow(BaseModel):
    id: int
    code: str
    name: str

    # 회장명 읽기(히라가나). 관리 화면이 「さんぷる」로 サンプル会館 A 를
    # 찾는 축이다. 예전에는 이 값을 목록에 싣지 않아, 화면(core.js)이 회장
    # 20곳의 읽기를 스스로 들고 있었다. 그 사본은 담당자가 표에서 후리가나를
    # 고쳐도 바뀌지 않아, 「고쳤는데 검색이 그대로」인 상태가 계속됐다.
    name_kana: str = ""

    area: str
    city: str
    region: str             # 표시용 — 地域+区市町村
    postal_code: str
    address: str
    tel: str                # 회장별 예외 번호. 비어 있으면 공통 문의처를 쓴다
    contact_tel: str        # 실제로 안내되는 번호 (tel 또는 CONTACT_TEL)
    transit_info: str
    access_minutes: str
    access_info: str        # 위 둘을 이어 붙인 표시용 한 줄

    # 이 회장이 여는 날들. 지난 회차도 포함한다 — 관리 화면은 끝난 회차의
    # 실적도 봐야 한다. 이용자 화면(`schemas/hospital.py`)과 다른 점이다.
    schedules: list[ScheduleRow] = []
    schedule_count: int = 0
    upcoming_schedule_count: int = 0

    # 아래 넷은 **대표 회차**(가장 이른 접수 중인 회차, 없으면 마지막 회차)의
    # 값이다. 목록 한 줄에 날짜 하나만 찍는 자리를 위해 남겨 둔다.
    event_date: date | None = None
    booking_close_date: date | None = None
    open_time: time | None = None
    reception_end_time: time | None = None

    has_parking: bool = False
    latitude: float | None = None
    longitude: float | None = None
    is_visible: bool
    sort_order: int
    slot_days: int          # 슬롯이 만들어져 있는 날짜 수
    slot_count: int         # 슬롯 개수
    total_capacity: int     # 그 회장의 총 정원
    upcoming_reserved: int  # 앞으로의 예약 건수
    is_booking_open: bool   # 오늘 웹에서 접수를 받는 회차가 있는가


class HospitalListResponse(BaseModel):
    success: bool = True
    data: list[HospitalRow]


class ScheduleInput(BaseModel):
    """회장 상세 화면에서 편집하는 개최 회차 한 줄.

    `id` 가 있으면 그 회차를 고치고, 없으면 새로 만든다. 저장 요청에
    없는 회차는 지운다 — 이 목록이 그 회장 회차의 전부다.
    """

    id: int | None = None
    event_date: date
    booking_close_date: date | None = None
    open_time: time | None = None
    reception_end_time: time | None = None
    is_visible: bool = True
    note: str = Field("", max_length=200)


class HospitalSaveRequest(BaseModel):
    code: str = Field(..., max_length=20)
    name: str = Field(..., max_length=120)
    area: str = Field("", max_length=40)
    city: str = Field("", max_length=60)
    postal_code: str = Field("", max_length=10)
    address: str = Field("", max_length=255)
    tel: str = Field("", max_length=30)
    transit_info: str = Field("", max_length=200)
    access_minutes: str = Field("", max_length=40)
    has_parking: bool = False
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    is_visible: bool = True
    sort_order: int = 0

    # 개최 회차. `None` 은 「손대지 않음」이고 `[]` 는 「전부 지움」이다.
    # 둘을 같게 두면, 회차 편집을 지원하지 않는 옛 화면이 회장 이름만
    # 고쳐 저장하는 것만으로 개최일이 전부 사라진다.
    schedules: list[ScheduleInput] | None = None

    @field_validator("code", "name")
    @classmethod
    def _required(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("必須項目です。")
        return v

    @field_validator("schedules")
    @classmethod
    def _unique_dates(
        cls, value: list[ScheduleInput] | None
    ) -> list[ScheduleInput] | None:
        if value is None:
            return value
        seen: set[date] = set()
        for item in value:
            if item.event_date in seen:
                raise ValueError(
                    f"開催日 {item.event_date.isoformat()} が重複しています。"
                )
            seen.add(item.event_date)
        return value

    @property
    def region(self) -> str:
        """표시용 지역 한 줄. 저장 시점에 만들어 둔다."""
        return f"{self.area}{self.city}"


# --------------------------------------------------------------------------
# A-24 회장 일괄 관리 (스프레드시트)
# --------------------------------------------------------------------------
# 우편 접수 일괄 입력과 같은 방식이다. 셀 값을 ``Any`` 로 받는 이유도 같다 —
# 형식이 틀린 셀을 요청 입구에서 거절하면 **어느 행의 어느 칸이 잘못됐는지**
# 표에 표시할 수 없다. 검증은 `admin_master_service` 에서 전 행을 모아 한다.


class HospitalBulkRow(BaseModel):
    model_config = {"extra": "allow"}

    row_no: Any = None
    id: Any = None          # 기존 회장이면 그 id. 비어 있으면 코드로 찾는다
    schedule_id: Any = None  # 기존 회차면 그 id. 비어 있으면 코드+개최일로 찾는다

    code: Any = ""
    name: Any = ""
    area: Any = ""
    city: Any = ""
    postal_code: Any = ""
    address: Any = ""
    tel: Any = ""
    transit_info: Any = ""
    access_minutes: Any = ""
    event_date: Any = ""
    booking_close_date: Any = ""
    open_time: Any = ""
    reception_end_time: Any = ""
    has_parking: Any = ""
    latitude: Any = ""
    longitude: Any = ""
    is_visible: Any = ""
    sort_order: Any = ""


class HospitalBulkRequest(BaseModel):
    rows: list[HospitalBulkRow] = Field(..., min_length=1, max_length=200)


class HospitalBulkFieldError(BaseModel):
    row_no: int
    field: str
    message: str


class HospitalBulkError(BaseModel):
    code: Literal["BULK_VALIDATION_FAILED"] = "BULK_VALIDATION_FAILED"
    message: str = "入力内容をご確認ください。"


class HospitalBulkErrorResponse(BaseModel):
    success: Literal[False] = False
    error: HospitalBulkError = Field(default_factory=HospitalBulkError)
    errors: list[HospitalBulkFieldError]


class HospitalBulkRowResult(BaseModel):
    row_no: int
    id: int                        # 회장 id
    schedule_id: int | None = None  # 이 행이 만든/고친 회차
    code: str
    name: str
    event_date: date | None = None
    action: Literal["CREATED", "UPDATED", "UNCHANGED"]
    changed_fields: list[str] = []


class HospitalBulkResult(BaseModel):
    created_count: int
    updated_count: int
    unchanged_count: int
    rows: list[HospitalBulkRowResult]

    # 저장은 됐지만 사람이 봐 두는 편이 좋은 것. 오류(`errors`)와 나눠 둔다.
    # 「이상하지만 틀리지는 않은 값」을 오류로 막으면, 담당자는 표를 열어
    # 그대로 저장하는 것조차 못 하게 된다 — 그 값을 넣은 것이 임포터일 때가
    # 특히 그렇다. 반대로 조용히 넘기면 아무도 눈치채지 못한다.
    warnings: list[HospitalBulkFieldError] = []


class HospitalBulkResponse(BaseModel):
    success: bool = True
    data: HospitalBulkResult


class HospitalSheetExportRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=200)

    @field_validator("rows")
    @classmethod
    def _limit_cells(cls, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for row in rows:
            if len(row) > 64:
                raise ValueError("1行の列が多すぎます。")
        return rows


class HospitalSheetImportResult(BaseModel):
    rows: list[dict[str, str]]
    summary: PostalSheetImportSummary


class HospitalSheetImportResponse(BaseModel):
    success: bool = True
    data: HospitalSheetImportResult


# ==========================================================================
# A-22 정원 관리
# ==========================================================================


class CapacitySlot(BaseModel):
    slot_id: int
    start_time: str
    end_time: str
    time_label: str
    period: str
    capacity: int
    reserved: int
    remaining: int
    is_closed: bool


class CapacityDay(BaseModel):
    date: date
    weekday: str
    schedule_id: int | None = None
    capacity: int
    reserved: int
    remaining: int
    closed_slots: int
    slot_count: int
    is_all_closed: bool


class CapacityMonth(BaseModel):
    hospital_id: int
    hospital_name: str
    month: str                     # YYYY-MM
    days: list[CapacityDay]
    selected_date: date | None = None
    selected_schedule_id: int | None = None
    slots: list[CapacitySlot] = []

    # 이 회장의 전 회차. 달력을 「이 회장이 여는 날」로 곧장 옮기기 위한
    # 목록이다. 회차가 여러 달에 걸쳐 있으면 월을 넘겨 가며 찾아야 하는데,
    # 스무 곳 × 여러 회차에서 그것은 사람이 할 일이 아니다.
    schedules: list[ScheduleRow] = []


class CapacityResponse(BaseModel):
    success: bool = True
    data: CapacityMonth


class SlotUpdateItem(BaseModel):
    slot_id: int
    capacity: int | None = None
    is_closed: bool | None = None


class SlotUpdateRequest(BaseModel):
    """정원 일괄 변경.

    날짜를 여러 개 골라 한 번에 조정할 수 있어야 한다.
    20개 회장 × 365일 × 12슬롯을 하나씩 만지는 것은 불가능하다 (M-5).
    """

    items: list[SlotUpdateItem] = Field(default_factory=list)

    # 날짜 단위 일괄 조작
    dates: list[date] = Field(default_factory=list)
    delta: int | None = Field(None, description="全スロットの定員増減 (+3 / -2)")
    set_closed: bool | None = Field(None, description="全スロットの締切/解除")


class ReservationImpact(BaseModel):
    """휴진으로 닫는 날짜에 이미 들어와 있는 예약.

    이메일이 없는 사람은 전화 말고 닿을 길이 없어 따로 센다. 먼저 걸어야
    하는 사람이 몇 명인지가 담당자에게 가장 급한 숫자다.
    """
    total: int = 0
    with_email: int = 0
    without_email: int = 0


class SlotUpdateResult(BaseModel):
    updated: int
    blocked: list[str] = []   # 예약 수보다 낮은 정원 등 거부된 항목
    message: str
    impact: ReservationImpact | None = None   # 휴진으로 닫았을 때만 채운다


class SlotUpdateResponse(BaseModel):
    success: bool = True
    data: SlotUpdateResult


class ReservationImpactResponse(BaseModel):
    success: bool = True
    data: ReservationImpact


# ==========================================================================
# A-30 옵션 검사
# ==========================================================================


class ExamOptionRow(BaseModel):
    id: int
    code: str
    name: str
    description: str
    note: str
    target_gender: str
    target_gender_label: str
    target_age_min: int
    target_age_max: int
    is_active: bool
    sort_order: int
    used_count: int   # 이 옵션을 신청한 예약 수


class ExamOptionListResponse(BaseModel):
    success: bool = True
    data: list[ExamOptionRow]


class ExamOptionSaveRequest(BaseModel):
    code: str = Field(..., max_length=20)
    name: str = Field(..., max_length=120)
    description: str = ""
    note: str = Field("", max_length=255)
    target_gender: Literal["M", "F", "ALL"] = "ALL"
    target_age_min: int = Field(40, ge=0, le=120)
    target_age_max: int = Field(74, ge=0, le=120)
    is_active: bool = True
    sort_order: int = 0

    @field_validator("code", "name")
    @classmethod
    def _required(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("必須項目です。")
        return v

    @field_validator("target_age_max")
    @classmethod
    def _age_order(cls, v: int, info) -> int:
        age_min = info.data.get("target_age_min")
        if age_min is not None and v < age_min:
            raise ValueError("最大年齢は最小年齢より大きくする必要があります。")
        return v


# ==========================================================================
# A-40 메일 템플릿
# ==========================================================================


class MailTemplateRow(BaseModel):
    id: int
    template_key: str
    label: str
    timing: str
    subject: str
    body: str
    updated_by: str
    updated_at: datetime


class MailTemplateListResponse(BaseModel):
    success: bool = True
    data: dict[str, Any]   # { templates: [...], variables: [...] }


class MailTemplateSaveRequest(BaseModel):
    subject: str = Field(..., max_length=255)
    body: str

    @field_validator("subject", "body")
    @classmethod
    def _required(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("空欄にすることはできません。")
        return v


class MailTemplatePreview(BaseModel):
    subject: str
    body: str
    sample_reservation_no: str = ""


class MailTemplatePreviewResponse(BaseModel):
    success: bool = True
    data: MailTemplatePreview


class MailLogRow(BaseModel):
    id: int
    reservation_id: int | None
    reservation_no: str
    template_key: str
    template_label: str
    to_email: str
    subject: str
    status: str
    status_label: str
    error_message: str
    sent_at: datetime


class MailLogResponse(BaseModel):
    success: bool = True
    data: Page[MailLogRow]


# ==========================================================================
# A-50 계정
# ==========================================================================


class AccountRow(BaseModel):
    id: int
    login_id: str
    name: str
    email: str
    role: str
    role_label: str
    level: int
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class AccountListResponse(BaseModel):
    success: bool = True
    data: list[AccountRow]


LOGIN_ID_PATTERN = re.compile(r"[A-Za-z0-9._@-]{3,60}")


class AccountCreateRequest(BaseModel):
    login_id: str = Field(..., max_length=60)
    name: str = Field(..., max_length=120)
    email: str = Field("", max_length=255)
    # `SYSTEM_ADMIN` 이 남아 있는 것은 **기존 L3 계정을 수정할 때**
    # 자기 권한을 그대로 보내야 하기 때문이다. 신규 생성·승격은
    # `admin_auth_service._reject_system_admin_role` 에서 막는다.
    role: Literal["SYSTEM_ADMIN", "BUSINESS_ADMIN", "STAFF"] = "STAFF"
    password: str = Field(..., min_length=8, max_length=200)
    is_active: bool = True

    @field_validator("login_id", "name")
    @classmethod
    def _required(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("必須項目です。")
        return v

    @field_validator("login_id")
    @classmethod
    def _check_login_id(cls, v: str) -> str:
        # 로그인 ID 는 한 번 만들면 바꿀 수 없다. 공백이나 전각 글자가 섞이면
        # 로그인할 때마다 IME 상태에 따라 맞기도 틀리기도 해, 본인도 못 들어간다.
        if not LOGIN_ID_PATTERN.fullmatch(v):
            raise ValueError(
                "ログインIDは半角英数字と記号「. _ @ -」で3～60文字にしてください。"
            )
        return v

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        # 스태프가 대신 입력하는 값이라 오타를 본인이 확인해 줄 수 없다.
        # 형식 검증은 이용자 화면과 같은 기준으로 건다. (core/email_utils.py)
        try:
            return normalize_email(v)
        except EmailInvalid as exc:
            raise ValueError(str(exc)) from exc


class AccountUpdateRequest(BaseModel):
    name: str = Field(..., max_length=120)
    email: str = Field("", max_length=255)
    # `SYSTEM_ADMIN` 이 남아 있는 것은 **기존 L3 계정을 수정할 때**
    # 자기 권한을 그대로 보내야 하기 때문이다. 신규 생성·승격은
    # `admin_auth_service._reject_system_admin_role` 에서 막는다.
    role: Literal["SYSTEM_ADMIN", "BUSINESS_ADMIN", "STAFF"]
    is_active: bool = True
    # 비워 두면 비밀번호를 바꾸지 않는다
    password: str = Field("", max_length=200)


# ==========================================================================
# A-60 조작 로그
# ==========================================================================

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        # 스태프가 대신 입력하는 값이라 오타를 본인이 확인해 줄 수 없다.
        # 형식 검증은 이용자 화면과 같은 기준으로 건다. (core/email_utils.py)
        try:
            return normalize_email(v)
        except EmailInvalid as exc:
            raise ValueError(str(exc)) from exc


class AuditLogRow(BaseModel):
    id: int
    admin_login_id: str
    admin_name: str
    action: str
    action_label: str
    target_type: str
    target_id: int | None
    target_label: str
    before_json: Any = None
    after_json: Any = None
    ip_address: str
    created_at: datetime


class AuditLogResponse(BaseModel):
    success: bool = True
    data: Page[AuditLogRow]
