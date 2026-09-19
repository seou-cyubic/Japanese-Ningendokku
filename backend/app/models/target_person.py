"""검진 대상자 명부 모델.

Sample Group 이 사전에 보유한 「이번 연도 건강검진 대상자」 명부다.
이 테이블에 존재하지 않는 사람은 검진 대상자가 아니므로 예약할 수 없다.
(plan.md BR-01 본인 확인 / BR-02 예약 대상 연령)

연령 조건(만 40~74세)은 이 명부를 생성하는 시점에 이미 적용된 것으로 간주한다.

성명은 일본 서식에 맞춰 성(姓)과 이름(名)을 분리해 보관하며,
후리가나도 성·이름 각각을 전각 가타카나로 보관한다.

이 테이블에는 **신원 정보만 둔다**
--------------------------------
예약 여부·예약번호 같은 「예약의 상태」는 이 테이블에 두지 않는다.
같은 사실이 두 곳에 적히면 반드시 어긋나며, 어긋난 순간
「예약이 있다고 나오는데 예약 내역이 없다」는 문의가 된다.

예약 여부는 언제나 `reservations` 테이블을 `target_person_id` 로 조회해서
판정한다. 이 테이블은 「누구인가」만 답하고, 「예약했는가」는 답하지 않는다.
(services/verify_service.py)
"""

from datetime import date

from sqlalchemy import Date, Enum, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TargetPerson(Base):
    __tablename__ = "target_persons"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # --- 성명 (한자) -----------------------------------------------------
    # 표기 흔들림(전각 공백 등)은 대조 시점에 normalize_name() 으로 흡수한다.
    # 정규화 값을 따로 저장하지 않는 이유는, 같은 정보를 두 벌 두면
    # 한쪽만 갱신되어 어긋날 수 있기 때문이다.
    last_name: Mapped[str] = mapped_column(
        String(60), nullable=False, comment="성 (한자) 예: 田中"
    )
    first_name: Mapped[str] = mapped_column(
        String(60), nullable=False, comment="이름 (한자) 예: 太郎"
    )

    # --- 후리가나 (전각 가타카나) ----------------------------------------
    last_name_kana: Mapped[str] = mapped_column(
        String(60), nullable=False, default="", comment="성 후리가나 (전각 가타카나) 예: タナカ"
    )
    first_name_kana: Mapped[str] = mapped_column(
        String(60), nullable=False, default="", comment="이름 후리가나 (전각 가타카나) 예: タロウ"
    )

    # --- 미들네임 (외국인 전용, 통상 공란) --------------------------------
    # ※ 미들네임 후리가나는 명부에 없는 경우가 많아 임의 항목으로 두고,
    #    표기와 읽기를 따로 보관한다.
    middle_name: Mapped[str] = mapped_column(
        String(120), nullable=False, default="", comment="미들네임 (표기)"
    )
    middle_name_kana: Mapped[str] = mapped_column(
        String(120), nullable=False, default="", comment="미들네임 후리가나 (전각 가타카나)"
    )

    # --- 기타 신원 -------------------------------------------------------
    gender: Mapped[str] = mapped_column(
        Enum("M", "F", name="gender_enum"),
        nullable=False,
        comment="성별 M=남성 F=여성",
    )
    birth_date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="생년월일 (서기)"
    )

    # --- 건강보험증 ------------------------------------------------------
    # 실물 카드 표기 순서에 맞춰 3개 항목으로 분리 보관한다.
    # 테스트 데이터는 전건 0000-ABCD-0000 이다.
    insurer_no: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="보험자 번호"
    )
    insurance_symbol: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="기호"
    )
    insurance_no: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="번호"
    )

    __table_args__ = (
        # 본인 확인 조회는 「생년월일 + 보험증 3항목」으로 후보를 좁힌 뒤
        # 성·이름을 정규화 비교한다. (services/verify_service.py)
        Index(
            "ix_target_lookup",
            "birth_date",
            "insurer_no",
            "insurance_symbol",
            "insurance_no",
        ),
        Index("ix_target_name", "last_name", "first_name"),
        {"comment": "健康診断対象者名簿（身元情報専用）"},
    )

    # ----------------------------------------------------------------------
    # 표시용 결합 속성
    # ----------------------------------------------------------------------

    @property
    def full_name(self) -> str:
        """성 + 이름. 예) 田中 太郎"""
        return f"{self.last_name} {self.first_name}"

    @property
    def full_name_kana(self) -> str:
        """성 후리가나 + 이름 후리가나. 예) タナカ タロウ"""
        return f"{self.last_name_kana} {self.first_name_kana}"

    @property
    def gender_label(self) -> str:
        return "男性" if self.gender == "M" else "女性"

    @property
    def insurance_card_no(self) -> str:
        """화면 표시용 결합 형식. 예) 0000-ABCD-0000"""
        return f"{self.insurer_no}-{self.insurance_symbol}-{self.insurance_no}"

    def __repr__(self) -> str:
        return f"<TargetPerson {self.id} {self.full_name} {self.birth_date}>"
