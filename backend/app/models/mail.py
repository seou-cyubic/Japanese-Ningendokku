"""메일 템플릿 · 발송 이력 모델 (plan.md §9.10 / BR-11).

보내는 메일은 두 종류뿐이다 (Q44 비고: 과도한 통지 금지).

    RESERVE_COMPLETE  예약 완료 직후
    REMINDER          검진 전날 12:00

본문을 코드에 넣지 않고 DB 에 두는 이유는, 문구를 바꿀 때마다
개발자를 부르지 않기 위해서다 (자체 피드백 M-11).
치환 변수는 `{{예약번호}}` 형태이며 A-40 화면에 목록을 표시한다.
"""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core import reservation_no as res_no
from app.core.database import Base

# mail_logs 가 reservations 를 FK 로 참조한다.
# 테이블이 메타데이터에 먼저 등록되어 있어야 FK 가 해석되므로 실제로 import 한다.
from app.models.reservation import Reservation  # noqa: F401

TEMPLATE_RESERVE_COMPLETE = "RESERVE_COMPLETE"
TEMPLATE_RESERVE_CHANGE = "RESERVE_CHANGE"
TEMPLATE_RESERVE_CHANGE_BY_CLINIC = "RESERVE_CHANGE_CLINIC"
TEMPLATE_REMINDER = "REMINDER"
TEMPLATE_LOOKUP_LINK = "LOOKUP_LINK"
TEMPLATE_SCHEDULE_CHANGED = "SCHEDULE_CHANGED"

TEMPLATE_KEYS = (
    TEMPLATE_RESERVE_COMPLETE,
    TEMPLATE_RESERVE_CHANGE,
    TEMPLATE_RESERVE_CHANGE_BY_CLINIC,
    TEMPLATE_REMINDER,
    TEMPLATE_LOOKUP_LINK,
    TEMPLATE_SCHEDULE_CHANGED,
)

TEMPLATE_LABELS: dict[str, str] = {
    TEMPLATE_RESERVE_COMPLETE: "予約完了案内メール",
    TEMPLATE_RESERVE_CHANGE: "予約変更案内メール",
    TEMPLATE_RESERVE_CHANGE_BY_CLINIC: "休診による変更案内メール",
    TEMPLATE_REMINDER: "受診日前日リマインドメール",
    TEMPLATE_LOOKUP_LINK: "予約内容の確認リンク案内メール",
    TEMPLATE_SCHEDULE_CHANGED: "受診日変更案内メール",
}

TEMPLATE_TIMINGS: dict[str, str] = {
    TEMPLATE_RESERVE_COMPLETE: "予約確定直後に自動送信",
    TEMPLATE_RESERVE_CHANGE: "予約内容変更直後に自動送信",
    TEMPLATE_RESERVE_CHANGE_BY_CLINIC: "休診による日程変更時に送信",
    TEMPLATE_REMINDER: "受診日前日12:00に自動送信",
    TEMPLATE_LOOKUP_LINK: "予約番号照会画面での送信リクエスト時",
    # 자동이 아니다. 전화로 새 날짜를 합의한 뒤 화면에서 일시를 옮기고,
    # 그때 뜨는 「보낼까요」에 담당자가 답해 보낸다.
    TEMPLATE_SCHEDULE_CHANGED: "日時変更後に担当者が送信 （電話案内後の確認用）",
}


class MailTemplate(Base):
    """메일 본문 템플릿. L3(시스템 관리자)만 편집할 수 있다."""

    __tablename__ = "mail_templates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    template_key: Mapped[str] = mapped_column(
        Enum(*TEMPLATE_KEYS, name="mail_template_key_enum"),
        nullable=False,
        unique=True,
    )
    subject: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")

    updated_by: Mapped[str] = mapped_column(
        String(120), nullable=False, default="", comment="마지막으로 고친 담당자"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = ({"comment": "メール本文テンプレート"},)

    @property
    def label(self) -> str:
        return TEMPLATE_LABELS.get(self.template_key, self.template_key)

    @property
    def timing(self) -> str:
        return TEMPLATE_TIMINGS.get(self.template_key, "")

    def __repr__(self) -> str:
        return f"<MailTemplate {self.template_key}>"


class MailLog(Base):
    """메일 발송 이력.

    「리마인드가 정말 나갔는지 확인할 수 없다」를 없애기 위한 테이블이다.
    실패 건은 관리자 대시보드에 노출해 수동 대응하게 한다 (자체 피드백 M-12).
    """

    __tablename__ = "mail_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    reservation_id: Mapped[int | None] = mapped_column(
        ForeignKey("reservations.id", ondelete="SET NULL"), nullable=True
    )
    # 예약이 지워진 뒤에도 「어느 예약에 보낸 메일인가」를 알 수 있게 남기는 사본.
    # 이 컬럼도 메일 이력 검색(A-40)의 대상이므로 예약 테이블과 **같은 콜레이션**을
    # 쓴다. 한쪽만 대소문자를 뭉개면 같은 번호로 찾았는데 결과가 달라진다.
    reservation_no: Mapped[str] = mapped_column(
        String(res_no.LENGTH, collation=res_no.DB_COLLATION),
        nullable=False,
        default="",
    )

    template_key: Mapped[str] = mapped_column(String(30), nullable=False)
    to_email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    subject: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    body: Mapped[str] = mapped_column(
        Text, nullable=False, default="", comment="실제로 보낸 본문 (치환 완료 상태)"
    )

    # SKIPPED : 이메일 미등록 등으로 애초에 보내지 않은 경우.
    #           실패와 구별해야 「왜 안 왔냐」는 문의에 정확히 답할 수 있다.
    status: Mapped[str] = mapped_column(
        Enum("SUCCESS", "FAILED", "SKIPPED", name="mail_log_status_enum"),
        nullable=False,
        default="SUCCESS",
    )
    error_message: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    sent_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_maillog_sent", "sent_at"),
        Index("ix_maillog_status", "status", "sent_at"),
        Index("ix_maillog_reservation", "reservation_id"),
        {"comment": "メール送信履歴"},
    )

    @property
    def status_label(self) -> str:
        return {"SUCCESS": "送信完了", "FAILED": "送信失敗", "SKIPPED": "送信なし"}.get(
            self.status, self.status
        )

    def __repr__(self) -> str:
        return f"<MailLog {self.template_key} {self.to_email} {self.status}>"
