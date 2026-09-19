"""옵션 검사 조회 스키마 (U-14 정보 입력).

이용자에게는 「본인이 신청할 수 있는 옵션」만 내려보낸다.
신청할 수 없는 검사를 흐리게라도 보여 주면 「왜 안 되냐」는 문의가 늘어난다.
(plan.md BR-13 / 문의 감소가 이 프로젝트의 핵심 목표)
"""

from pydantic import BaseModel


class ExamOptionItem(BaseModel):
    """이용자 화면에 표시할 옵션 검사 1건."""

    id: int
    code: str
    name: str
    description: str
    note: str


class ExamOptionListData(BaseModel):
    # 어떤 조건으로 걸렀는지 함께 내려보낸다.
    # 화면에서 「1975년생 여성에게 신청 가능한 검사」처럼 근거를 밝히면
    # 「내가 받던 검사가 왜 없냐」는 문의를 미리 막을 수 있다.
    gender: str
    gender_label: str
    age: int
    options: list[ExamOptionItem]


class ExamOptionListResponse(BaseModel):
    success: bool = True
    data: ExamOptionListData
