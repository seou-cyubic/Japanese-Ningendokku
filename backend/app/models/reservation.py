"""예약 모델 (plan.md §9.6 / §9.7 / §9.8).

예약은 **물리 삭제하지 않는다.** 취소는 `status` 변경으로만 처리한다.
스태프가 실수로 지운 것인지 추적할 수 없으면 문의에 답할 수 없기 때문이다.
(자체 피드백 M-8)

성명은 U-11 본인 확인과 같은 방식으로 성·이름을 분리해 보관한다.
명부(`target_persons`)를 참조하지만 값 자체도 복사해 둔다.
명부가 갱신되어도 「예약 당시에 무엇으로 접수했는가」가 남아야 하기 때문이다.
"""

from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core import reservation_no as res_no
from app.core.database import Base

# 이 모델이 참조하는 테이블·클래스를 **실제로** import 한다.
# 문자열 이름("Hospital")만 적어 두면, 그 클래스를 아직 불러오지 않은
# 스크립트에서 매퍼 설정이 실패한다. 아래 네 모듈은 reservation 을
# 되돌아 참조하지 않으므로 순환 import 가 생기지 않는다.
from app.models.admin import AdminUser  # noqa: F401
from app.models.exam_option import ExamOption  # noqa: F401
from app.models.hospital import Hospital, HospitalSchedule
from app.models.target_person import TargetPerson  # noqa: F401

# 예약 상태 (plan.md §9.6)
#   CONFIRMED : 확정.  웹 예약은 접수 즉시 이 상태가 된다 (BR-04)
#   PENDING   : 임시.  우편 접수 중 불비가 있어 스태프 확인을 기다리는 상태
#   CANCELLED : 취소.  정원은 취소 시점에 즉시 반환된다 (BR-10)
RESERVATION_STATUSES = ("CONFIRMED", "PENDING", "CANCELLED")

# 취소의 종류 (cancel_type). 빈 값은 구분 이전의 취소다.
CANCEL_TYPES = ("ADVANCE", "SAME_DAY")
CANCEL_TYPE_LABELS = {
    "ADVANCE": "事前キャンセル",
    "SAME_DAY": "当日キャンセル",
}

# 접수 경로
#   WEB    : 이용자가 스스로 웹에서 접수
#   POSTAL : 우편 신청서를 스태프가 관리 화면에서 대리 등록 (A-13)
RESERVATION_CHANNELS = ("WEB", "POSTAL")


class Reservation(Base):
    """확정된 예약 1건."""

    __tablename__ = "reservations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # 무작위 12자(영문 대소문자 + 숫자).
    #
    # 이 컬럼만 테이블 기본 콜레이션(utf8mb4_general_ci — 대소문자 구별 없음)을
    # 쓰지 않고 `utf8mb4_bin` 을 지정한다. 예약번호는 **대소문자를 구별**해야
    # 하기 때문이다. (core/reservation_no.py)
    #
    # 콜레이션은 컬럼에 붙어 있으므로 조회·`LIKE`·`UNIQUE` 판정이 전부
    # 같은 기준(대소문자 구별)으로 동작한다. 어느 한 곳에서 `upper()` 를
    # 씌우는 식으로 흉내 내면 나머지 한쪽과 어긋나므로 그렇게 하지 않는다.
    reservation_no: Mapped[str] = mapped_column(
        String(res_no.LENGTH, collation=res_no.DB_COLLATION),
        nullable=False,
        unique=True,
        comment="자동 생성 예약번호 — 무작위 12자 · 대소문자 구별 (core/reservation_no.py)",
    )

    # --- 예약 대상 -------------------------------------------------------
    # 시간표가 행(`slots`)에서 그리드(`hospital_schedules.cap_*`)로 바뀌면서
    # 가리킬 슬롯 행이 없어졌다. 대신 **회차 + 시각**이 그 자리를 대신한다.
    #
    # `RESTRICT` 는 그대로 둔다. 예전에 「예약이 걸린 슬롯을 지울 수 없다」를
    # DB 가 보장하던 것이 이제 **「예약이 걸린 회차를 지울 수 없다」** 가 된다.
    # 보호 단위가 한 층 올라갔을 뿐, 지키는 것은 같다.
    schedule_id: Mapped[int] = mapped_column(
        ForeignKey("hospital_schedules.id", ondelete="RESTRICT"), nullable=False
    )
    # hospital_id · slot_date · start_time 은 회차를 따라가면 알 수 있지만,
    # 관리자 검색이 「회장 + 기간」으로 이루어지므로 비정규화해 둔다.
    hospital_id: Mapped[int] = mapped_column(
        ForeignKey("hospitals.id", ondelete="RESTRICT"), nullable=False
    )
    slot_date: Mapped[date] = mapped_column(Date, nullable=False, comment="검진일")
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    channel: Mapped[str] = mapped_column(
        Enum(*RESERVATION_CHANNELS, name="reservation_channel_enum"),
        nullable=False,
        default="WEB",
    )
    status: Mapped[str] = mapped_column(
        Enum(*RESERVATION_STATUSES, name="reservation_status_enum"),
        nullable=False,
        default="CONFIRMED",
    )

    # --- 신청자 (본인 확인 결과를 복사해 둔다) ----------------------------
    target_person_id: Mapped[int | None] = mapped_column(
        ForeignKey("target_persons.id", ondelete="SET NULL"),
        nullable=True,
        comment="검진 대상자 명부 연결. 우편 접수는 비어 있을 수 있다",
    )

    last_name: Mapped[str] = mapped_column(String(60), nullable=False)
    first_name: Mapped[str] = mapped_column(String(60), nullable=False)
    last_name_kana: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    first_name_kana: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    middle_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    middle_name_kana: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    gender: Mapped[str] = mapped_column(
        Enum("M", "F", name="reservation_gender_enum"), nullable=False
    )
    birth_date: Mapped[date] = mapped_column(Date, nullable=False, comment="서기 표기")

    insurer_no: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    insurance_symbol: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    insurance_no: Mapped[str] = mapped_column(String(30), nullable=False, default="")

    # --- 주소 · 연락처 (BR-05) --------------------------------------------
    postal_code: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    address: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    address_detail: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    building: Mapped[str] = mapped_column(
        String(255), nullable=False, default="", comment="아파트·맨션명 [임의]"
    )

    tel_mobile: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    tel_home: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    email: Mapped[str] = mapped_column(
        String(255), nullable=False, default="", comment="[임의] 미입력이면 메일을 보내지 않는다"
    )

    # --- 관리 정보 --------------------------------------------------------
    fiscal_year: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="중복 판정용 회계연도 (4/1 기준)"
    )
    memo: Mapped[str] = mapped_column(
        Text, nullable=False, default="", comment="스태프 메모 (이용자에게 보이지 않음)"
    )
    has_defect: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="불비 여부. 우편 접수에서 항목이 빠진 채 임시 등록된 경우 True",
    )
    defect_note: Mapped[str] = mapped_column(
        String(255), nullable=False, default="", comment="무엇이 빠졌는지"
    )

    created_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
        comment="우편 접수를 대리 등록한 스태프",
    )

    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 취소의 종류. 통계에서 둘을 따로 세야 하므로 나눈다.
    #   ADVANCE  事前キャンセル — 본인이 전화로 미리 알려 온 취소
    #   SAME_DAY 当日キャンセル — 연락이 닿지 않는 등 당일에 확인된 취소
    # 빈 문자열은 이 구분이 생기기 전에 취소된 예약이다. 「キャンセル」로만 보인다.
    cancel_type: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    cancel_reason: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # --- 관계 -------------------------------------------------------------
    hospital: Mapped[Hospital] = relationship(Hospital, lazy="joined")
    # 예전에는 `slot` 이었다. 시간표가 그리드가 되면서 가리킬 슬롯 행이
    # 없어졌고, 그 자리를 회차가 받았다. 그 날의 몇 시인지는 이 행이 가진
    # `start_time` 이 답한다.
    schedule: Mapped["HospitalSchedule"] = relationship(
        "HospitalSchedule", lazy="joined"
    )
    options: Mapped[list["ReservationOption"]] = relationship(
        back_populates="reservation",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    contacts: Mapped[list["ContactHistory"]] = relationship(
        back_populates="reservation",
        cascade="all, delete-orphan",
        order_by="ContactHistory.contacted_at",
        lazy="selectin",
    )

    __table_args__ = (
        # 중복 예약 판정 (BR-03) : 성명 + 생년월일 + 전화번호 / 당해 연도
        Index("ix_res_dup", "fiscal_year", "birth_date", "last_name", "first_name"),
        Index("ix_res_status", "fiscal_year", "status"),
        Index("ix_res_schedule", "hospital_id", "slot_date"),
        Index("ix_res_created", "created_at"),
        {"comment": "健康診断予約"},
    )

    # ----------------------------------------------------------------------
    # 표시용 파생 값
    # ----------------------------------------------------------------------

    @property
    def full_name(self) -> str:
        return f"{self.last_name} {self.first_name}"

    @property
    def full_name_kana(self) -> str:
        return f"{self.last_name_kana} {self.first_name_kana}".strip()

    @property
    def gender_label(self) -> str:
        return "男性" if self.gender == "M" else "女性"

    @property
    def time_label(self) -> str:
        # 波ダッシュは全角チルダ（U+FF5E）。core/time_grid.label() と同じ表記に
        # そろえる。同じ「09:30～10:00」を作る場所が二つあり、片方だけ直すと
        # 画面によって記号が変わる。
        return f"{self.start_time.strftime('%H:%M')}～{self.end_time.strftime('%H:%M')}"

    @property
    def tel_primary(self) -> str:
        """연락처 1순위. 휴대전화가 있으면 그쪽이다."""
        return self.tel_mobile or self.tel_home

    @property
    def full_address(self) -> str:
        parts = [self.address, self.address_detail, self.building]
        return " ".join(p for p in parts if p)

    @property
    def insurance_card_no(self) -> str:
        return f"{self.insurer_no}-{self.insurance_symbol}-{self.insurance_no}"

    @property
    def contact_count(self) -> int:
        """연락 횟수. 3회에 도달하면 취소 대상이다 (BR-06 / M-3)."""
        return len(self.contacts)

    @property
    def contact_connected(self) -> bool:
        """한 번이라도 통화가 됐는가.

        횟수만으로는 「세 번 다 부재중」과 「통화 후 유지」를 가릴 수 없다.
        취소 대상은 3회 **미연결**이므로, 담당자가 봐야 하는 것은 횟수가
        아니라 닿았는지다.
        """
        return any(c.result == "CONNECTED" for c in self.contacts)

    @property
    def option_names(self) -> str:
        return ", ".join(sorted(opt.option_name for opt in self.options)) if self.options else "選択なし"

    def __repr__(self) -> str:
        return f"<Reservation {self.reservation_no} {self.full_name} {self.status}>"


class ReservationOption(Base):
    """예약 ↔ 옵션 검사 (N:M).

    옵션명을 함께 복사해 둔다. 마스터에서 옵션이 삭제·개명되어도
    「그때 무엇을 신청했는가」는 남아야 한다.
    """

    __tablename__ = "reservation_options"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    reservation_id: Mapped[int] = mapped_column(
        ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False
    )
    exam_option_id: Mapped[int | None] = mapped_column(
        ForeignKey("exam_options.id", ondelete="SET NULL"), nullable=True
    )
    option_code: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    option_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    reservation: Mapped[Reservation] = relationship(back_populates="options")

    __table_args__ = (
        UniqueConstraint("reservation_id", "exam_option_id", name="uq_res_option"),
        {"comment": "予約別オプション検査"},
    )

    def __repr__(self) -> str:
        return f"<ReservationOption {self.reservation_id} {self.option_code}>"


class ContactHistory(Base):
    """연락 이력 (plan.md §9.8 / 자체 피드백 M-3).

    우편 접수의 불비를 확인하려고 건 전화·메일을 누적한다.
    「몇 번째 연락인지 기억이 안 난다」를 없애기 위한 테이블이며,
    3회에 도달하면 예약을 취소할 수 있다 (BR-06).
    """

    __tablename__ = "contact_histories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    reservation_id: Mapped[int] = mapped_column(
        ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False
    )
    contacted_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    admin_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True
    )
    admin_name: Mapped[str] = mapped_column(
        String(120), nullable=False, default="", comment="담당자명 (계정이 지워져도 남는다)"
    )

    method: Mapped[str] = mapped_column(
        Enum("TEL", "MAIL", name="contact_method_enum"), nullable=False, default="TEL"
    )
    result: Mapped[str] = mapped_column(
        Enum("CONNECTED", "NO_ANSWER", name="contact_result_enum"),
        nullable=False,
        default="NO_ANSWER",
    )
    memo: Mapped[str] = mapped_column(
        Text, nullable=False, default="", comment="무엇을 확인·수정했는지"
    )

    reservation: Mapped[Reservation] = relationship(back_populates="contacts")

    __table_args__ = (
        Index("ix_contact_reservation", "reservation_id", "contacted_at"),
        {"comment": "不備確認連絡履歴"},
    )

    @property
    def method_label(self) -> str:
        return "電話" if self.method == "TEL" else "メール"

    @property
    def result_label(self) -> str:
        return "応答あり" if self.result == "CONNECTED" else "応答なし"

    def __repr__(self) -> str:
        return f"<ContactHistory r={self.reservation_id} {self.method} {self.result}>"
