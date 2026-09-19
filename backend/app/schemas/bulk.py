"""회장 정보 · 정원 일괄 관리 표의 스키마 (A-24 분리).

왜 표를 둘로 나눴는가
---------------------
예전에는 원본 CSV 모양 그대로 한 표에서 전부 다뤘다. 한 행이 개최 회차
하나였고, 그 행에 회장 코드·이름·주소·좌표까지 함께 실려 있었다.

두 가지가 문제였다.

    ① 「회장 A 의 8/28·8/29·8/30 정원을 본다」에 주소와 좌표가 딸려 온다.
       정원을 고치러 온 사람에게 필요 없는 열이 스무 개 붙어 있다.

    ② 회장 A 가 세 행이면 주소도 세 벌이다. 한 행의 위도만 잘못 고치면
       같은 회장의 행끼리 값이 어긋난다. 코드로 막을 수는 있지만,
       **애초에 한 번만 적히게 두는 편이 낫다.**

그래서 표를 둘로 나눈다.

    회장 정보 일괄 관리   한 행 = 회장 하나.   장소 정보만.
    정원 일괄 관리        한 행 = 회차 하나.   날짜와 시간대 정원만.

원본 CSV 는 여전히 한 장이므로, 그것을 넣는 화면(마스터 파일 가져오기)은
따로 남는다. 가져오기는 **넣을 때 한 번**이고, 두 표는 **그 뒤로 계속**이다.
"""

from datetime import date, time
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


# ==========================================================================
# 공통
# ==========================================================================


class BulkFieldError(BaseModel):
    """어느 행 어느 칸이 왜 틀렸는가. 화면이 그 셀을 붉게 칠한다."""

    row_no: int
    field: str
    message: str


class BulkFieldChange(BaseModel):
    """한 칸이 무엇에서 무엇으로 바뀌는가.

    저장 **전에** 보여 주기 위한 것이다. 예전에는 「21곳을 검사합니다」만
    말하고, 몇 곳이 새로 생기고 몇 곳이 덮어써지는지는 저장한 뒤에야 알 수
    있었다. 덮어쓰기가 걱정되어 파일을 올리는 사람에게 그 순서는 거꾸로다.

    저장 후 응답에도 담는다. 무엇이 들어갔는지 되짚을 수 있어야 한다.
    """

    field: str
    label: str = ""
    before: str = ""
    after: str = ""


class BulkError(BaseModel):
    code: Literal["BULK_VALIDATION_FAILED"] = "BULK_VALIDATION_FAILED"
    message: str = "入力内容をご確認ください。"


class BulkErrorResponse(BaseModel):
    success: Literal[False] = False
    error: BulkError = Field(default_factory=BulkError)
    errors: list[BulkFieldError]


# ==========================================================================
# 회장 정보 일괄 관리
# ==========================================================================


class VenueBulkRow(BaseModel):
    """표의 한 행 = 회장 하나.

    셀 값을 `Any` 로 받는 이유는 우편 일괄 입력과 같다 — 형식이 틀린 셀을
    요청 입구에서 거절하면 **어느 행의 어느 칸이 잘못됐는지** 표에 표시할
    수 없다. 검증은 서비스에서 전 행을 모아 한 번에 한다.
    """

    model_config = {"extra": "allow"}

    row_no: Any = None
    id: Any = None          # 기존 회장이면 그 id. 비어 있으면 코드로 찾는다

    code: Any = ""
    name: Any = ""
    name_kana: Any = ""     # 회장명 요미가나 (히라가나 검색용)
    area: Any = ""
    city: Any = ""
    postal_code: Any = ""
    address: Any = ""
    transit_info: Any = ""
    access_minutes: Any = ""
    tel: Any = ""
    has_parking: Any = ""
    latitude: Any = ""
    longitude: Any = ""
    is_visible: Any = ""
    sort_order: Any = ""


class VenueBulkRequest(BaseModel):
    rows: list[VenueBulkRow] = Field(..., min_length=1, max_length=200)


class VenueBulkRowResult(BaseModel):
    row_no: int
    id: int
    code: str
    name: str
    action: Literal["CREATED", "UPDATED", "UNCHANGED"]
    changed_fields: list[str] = []
    # 어느 칸이 무엇에서 무엇으로 바뀌는가. 저장 전 미리보기가 이것을 읽는다.
    changes: list[BulkFieldChange] = []


class VenueBulkResult(BaseModel):
    created_count: int
    updated_count: int
    unchanged_count: int
    # 이 표에 아예 없어서 **손대지 않는** 기존 데이터의 수.
    # 「90~110 을 올리면 1~89 는 어떻게 되는가」에 숫자로 답하는 칸이다.
    untouched_count: int = 0
    rows: list[VenueBulkRowResult]
    warnings: list[BulkFieldError] = []


class VenueBulkResponse(BaseModel):
    success: bool = True
    data: VenueBulkResult


# ==========================================================================
# 정원 일괄 관리
# ==========================================================================


class CapacityBulkRow(BaseModel):
    """표의 한 행 = 개최 회차 하나.

    시간대 정원은 `09:30~10:00` 같은 **동적 열**로 들어온다. 열 이름과
    순서는 `app/core/time_grid.py` 가 정하며, 이 스키마는 그것을 알지
    못한 채 `extra="allow"` 로 받아 넘긴다. 격자가 넓어져도 여기는 그대로다.
    """

    model_config = {"extra": "allow"}

    row_no: Any = None
    schedule_id: Any = None     # 기존 회차면 그 id
    hospital_code: Any = ""     # 어느 회장의 회차인가 (필수)

    event_date: Any = ""
    booking_close_date: Any = ""
    open_time: Any = ""
    reception_end_time: Any = ""
    note: Any = ""
    is_visible: Any = ""


class CapacityBulkRequest(BaseModel):
    rows: list[CapacityBulkRow] = Field(..., min_length=1, max_length=400)


class CapacityBulkRowResult(BaseModel):
    row_no: int
    schedule_id: int
    hospital_id: int
    hospital_code: str
    hospital_name: str
    event_date: date
    action: Literal["CREATED", "UPDATED", "UNCHANGED"]
    changed_fields: list[str] = []
    # 어느 칸이 무엇에서 무엇으로 바뀌는가. 저장 전 미리보기가 이것을 읽는다.
    changes: list[BulkFieldChange] = []
    total_capacity: int = 0
    total_reserved: int = 0


class CapacityBulkResult(BaseModel):
    created_count: int
    updated_count: int
    unchanged_count: int
    # 이 표에 아예 없어서 **손대지 않는** 기존 데이터의 수.
    # 「90~110 을 올리면 1~89 는 어떻게 되는가」에 숫자로 답하는 칸이다.
    untouched_count: int = 0
    rows: list[CapacityBulkRowResult]
    warnings: list[BulkFieldError] = []


class CapacityBulkResponse(BaseModel):
    success: bool = True
    data: CapacityBulkResult


# ==========================================================================
# 표를 열 때 내려주는 것
# ==========================================================================


class GridColumn(BaseModel):
    """화면이 표의 열을 그릴 때 쓰는 정의.

    열 목록을 서버가 내려주는 이유는 **시간대 열이 격자에서 나오기**
    때문이다. 화면에 16칸을 적어 두면 격자를 넓힐 때 두 곳을 고쳐야 한다.
    """

    key: str
    label: str
    width: int = 120
    kind: Literal[
        "text", "date", "time", "number", "bool", "capacity", "enum"
    ] = "text"
    readonly: bool = False
    group: str = ""
    # `kind="enum"` 인 칸의 선택지. 저장하는 값은 `value`(코드)이고 표에
    # 보이는 것은 `label`(말)이다. `F` 가 여성인지 거짓인지 매번 헷갈리므로
    # 화면에서는 말로 보여 주고, 서버·파일·API 는 코드로 말한다.
    choices: list["GridChoice"] = []


class GridChoice(BaseModel):
    value: str
    label: str


GridColumn.model_rebuild()


class VenueGridData(BaseModel):
    columns: list[GridColumn]
    rows: list[dict[str, Any]]


class VenueGridResponse(BaseModel):
    success: bool = True
    data: VenueGridData


class CapacityGridData(BaseModel):
    columns: list[GridColumn]
    rows: list[dict[str, Any]]

    # 셀에 「3 / 22」를 적기 위한 읽기 전용 값. 정원과 나란한 자리에
    # 예약 수를 두면, **정원을 3 아래로 못 내리는 이유가 셀 안에 보인다.**
    reserved: dict[str, dict[str, int]] = {}
    # 마감된 칸. `{schedule_id: ["09:30~10:00", …]}`
    closed: dict[str, list[str]] = {}

    hospitals: list[dict[str, Any]] = []


class CapacityGridResponse(BaseModel):
    success: bool = True
    data: CapacityGridData


# ==========================================================================
# 옵션 검사 일괄 관리
# ==========================================================================
#
# 예전에는 카드 목록 + 행마다 모달이었다. 검사 12건의 타깃 연령을 한 살씩
# 올리는 데 모달을 열두 번 열어야 했고, CSV 입출력만 따로 붙어 있어
# 「표에서 고치는 것」과 「파일로 고치는 것」이 다른 화면이었다.
#
# 회장·정원과 같은 표로 맞춘다. 고치는 창구가 하나여야 검증 규칙이
# 갈라지지 않는다.


class ExamOptionBulkRow(BaseModel):
    """표의 한 행 = 옵션 검사 하나.

    셀 값을 `Any` 로 받는 이유는 다른 두 표와 같다 — 형식이 틀린 셀을 요청
    입구에서 거절하면 어느 행의 어느 칸이 잘못됐는지 표에 표시할 수 없다.
    """

    model_config = {"extra": "allow"}

    row_no: Any = None
    id: Any = None          # 기존 검사면 그 id. 비어 있으면 코드로 찾는다

    code: Any = ""
    name: Any = ""
    is_active: Any = ""
    sort_order: Any = ""
    target_gender: Any = ""
    target_age_min: Any = ""
    target_age_max: Any = ""
    description: Any = ""
    note: Any = ""


class ExamOptionBulkRequest(BaseModel):
    rows: list[ExamOptionBulkRow] = Field(..., min_length=1, max_length=200)


class ExamOptionBulkRowResult(BaseModel):
    row_no: int
    id: int
    code: str
    name: str
    action: Literal["CREATED", "UPDATED", "UNCHANGED"]
    changed_fields: list[str] = []
    # 어느 칸이 무엇에서 무엇으로 바뀌는가. 저장 전 미리보기가 이것을 읽는다.
    changes: list[BulkFieldChange] = []


class ExamOptionBulkResult(BaseModel):
    created_count: int
    updated_count: int
    unchanged_count: int
    # 이 표에 아예 없어서 **손대지 않는** 기존 데이터의 수.
    # 「90~110 을 올리면 1~89 는 어떻게 되는가」에 숫자로 답하는 칸이다.
    untouched_count: int = 0
    rows: list[ExamOptionBulkRowResult]
    warnings: list[BulkFieldError] = []


class ExamOptionBulkResponse(BaseModel):
    success: bool = True
    data: ExamOptionBulkResult


class ExamOptionGridData(BaseModel):
    columns: list[GridColumn]
    rows: list[dict[str, Any]]


class ExamOptionGridResponse(BaseModel):
    success: bool = True
    data: ExamOptionGridData


# ==========================================================================
# 파일 입출력 (표 공통)
# ==========================================================================
#
# 회장·정원·옵션 검사 세 표가 같은 모양으로 파일을 주고받는다. 표마다
# 스키마를 따로 두면 열 하나 늘릴 때마다 세 벌을 고치게 되고, 화면 쪽
# 공용 헬퍼(`grid-io.js`)도 표마다 분기해야 한다.
#
# 행은 `dict[str, Any]` 그대로 받는다. **어느 열이 있는지는 표마다 다르고,
# 정원 표는 시간대 열이 격자에서 나와** 스키마가 미리 알 수 없다.


class SheetExportRequest(BaseModel):
    """화면의 표를 그대로 파일로. 검증하지 않는다.

    형식이 틀린 값을 Excel 에서 고치려고 꺼내는 것이 이 요청의 가장 흔한
    쓰임이다. 여기서 거절하면 그 길이 막힌다.
    """

    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=400)

    @field_validator("rows")
    @classmethod
    def _limit_cells(cls, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # 정원 표는 고정 8열 + 시간대 16열이라 24열이다. 격자가 넓어질 것을
        # 감안해 넉넉히 두되, 무한정 받지는 않는다.
        for row in rows:
            if len(row) > 96:
                raise ValueError("1行の列が多すぎます。")
        return rows


class SheetImportSummary(BaseModel):
    """무엇을 어떻게 읽었는지. 화면이 그대로 사람에게 보여 준다.

    조용히 넘기면 오해가 남는다 — 제목 줄을 못 찾아 순서대로 넣었는지,
    모르는 열을 버렸는지, 빈 행을 몇 개 건너뛰었는지.
    """

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


class SheetImportResult(BaseModel):
    rows: list[dict[str, str]]
    summary: SheetImportSummary


class SheetImportResponse(BaseModel):
    success: bool = True
    data: SheetImportResult
