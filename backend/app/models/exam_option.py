"""옵션 검사 모델.

plan.md §9.7 / BR-13

기본 검진에 부가하는 추가 검사다. 코스별 옵션 구성은 없고(BR-13),
연령·성별 타깃 조건만 가진다. 조건에 맞지 않는 검사는 이용자 화면의
선택지에 아예 나타나지 않는다.

    예: 자궁경부암 검사 → 성별 F, 만 40~74세인 경우에만 폼에 노출

옵션별 정원 상한은 없다(BR-13). 비용은 당일 회장에서 결제하므로
금액 항목도 두지 않는다(§4.2 결제 기능 제외).
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ExamOption(Base):
    """옵션 검사 마스터. 관리화면에서 등록·수정·삭제·타깃 설정한다."""

    __tablename__ = "exam_options"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    code: Mapped[str] = mapped_column(
        String(20), nullable=False, unique=True, comment="옵션 검사 코드"
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False, comment="검사명")
    description: Mapped[str] = mapped_column(
        Text, nullable=False, default="", comment="이용자 화면에 보여 줄 설명"
    )
    note: Mapped[str] = mapped_column(
        String(255), nullable=False, default="", comment="주의 사항 (금식 등)"
    )

    # --- 타깃 조건 (BR-13) ------------------------------------------------
    target_gender: Mapped[str] = mapped_column(
        String(3), nullable=False, default="ALL", comment="M / F / ALL"
    )
    target_age_min: Mapped[int] = mapped_column(
        Integer, nullable=False, default=40, comment="타깃 최소 연령 (만)"
    )
    target_age_max: Mapped[int] = mapped_column(
        Integer, nullable=False, default=74, comment="타깃 최대 연령 (만)"
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = ({"comment": "オプション検査マスタ (年齢・性別対象条件を含む)"},)

    def matches(self, gender: str, age: int) -> bool:
        """이 옵션을 해당 이용자에게 보여 줄지 판정한다."""
        if not self.is_active:
            return False
        if self.target_gender != "ALL" and self.target_gender != gender:
            return False
        return self.target_age_min <= age <= self.target_age_max

    def __repr__(self) -> str:
        return f"<ExamOption {self.code} {self.name}>"
