"""관리 화면 — 메일 템플릿 편집 · 발송 이력 (A-40).

L3(시스템 관리자) 전용이다.
「확인 메일 문구를 바꾸려면 매번 개발자를 불러야 한다」를 없애기 위한 화면이며
(자체 피드백 M-11), 치환 변수 목록을 화면에 명시한다.
"""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.admin import AdminUser
from app.models.mail import (
    TEMPLATE_KEYS,
    TEMPLATE_LABELS,
    MailLog,
    MailTemplate,
)
from app.models.reservation import Reservation
from app.schemas.admin import (
    MailLogRow,
    MailTemplatePreview,
    MailTemplateRow,
    MailTemplateSaveRequest,
    Page,
)
from app.services import audit_service, mail_service


class MailTemplateError(Exception):
    pass


def _to_row(t: MailTemplate) -> MailTemplateRow:
    return MailTemplateRow(
        id=t.id,
        template_key=t.template_key,
        label=t.label,
        timing=t.timing,
        subject=t.subject,
        body=t.body,
        updated_by=t.updated_by,
        updated_at=t.updated_at,
    )


def list_templates(db: Session) -> dict:
    # 없으면 기본값으로 만들어 둔다. 빈 화면을 보여 주지 않는다.
    templates = [mail_service.get_template(db, key) for key in TEMPLATE_KEYS]
    db.commit()

    return {
        "templates": [_to_row(t) for t in templates],
        "variables": mail_service.TEMPLATE_VARIABLES,
    }


def save_template(
    db: Session,
    template_key: str,
    payload: MailTemplateSaveRequest,
    *,
    admin: AdminUser,
    ip_address: str,
) -> MailTemplateRow:
    if template_key not in TEMPLATE_KEYS:
        raise MailTemplateError("不明なメール種別です。")

    # 모르는 변수는 치환되지 않고 `{{…}}` 글자 그대로 이용자에게 나간다.
    # 오타(「{{お名前 }}」가 아니라 「{{お名}}」 등)를 저장 단계에서 막는다.
    unknown = mail_service.unknown_variables(payload.subject, payload.body)
    if unknown:
        raise MailTemplateError(
            "使用できない置換変数があります: " + "、".join(unknown)
            + "。画面右の「置換変数」一覧にある名前をご使用ください。"
        )

    template = mail_service.get_template(db, template_key)
    before = audit_service.snapshot(template, ["subject", "body"])

    template.subject = payload.subject
    template.body = payload.body
    template.updated_by = admin.name

    db.flush()

    diff_payload = {}
    if before["subject"] != payload.subject:
        diff_payload["subject"] = {"before": before["subject"], "after": payload.subject}
    if before["body"] != payload.body:
        diff_payload["body_diff"] = audit_service.text_diff(before["body"], payload.body)

    audit_service.write_log(
        db,
        admin=admin,
        action="MAIL_TEMPLATE_UPDATE",
        target_type="mail_template",
        target_id=template.id,
        target_label=TEMPLATE_LABELS.get(template_key, template_key),
        before=None,  # diff를 직접 만들었으므로 before를 생략
        after=diff_payload,
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(template)
    return _to_row(template)


def preview_extra(sample: Reservation) -> dict[str, str]:
    """미리 보기에서만 쓰는 견본 값.

    「검진일 변경 안내」의 `{{변경전검진일}}` 은 예약 한 건에서 끌어낼 수 없다.
    실제 발송 때는 일시를 바꾸기 직전에 붙잡아 둔 값을 넘기지만, 미리 보기에는
    그런 값이 없어 기본값인 「-」 가 그대로 나온다.

    그러면 화면에서 이렇게 보인다.

        변경 전   -  -
        변경 후   2026년 9월 17일 (목) 14:00~14:30

    담당자가 정작 확인해야 할 「변경 전 → 변경 후」 두 줄이 반쪽만 나와,
    줄이 나란히 서는지·자리가 맞는지를 볼 수 없다. 문구를 고치라고 만든
    화면인데 고칠 대상이 안 보이는 셈이다.

    그래서 견본을 넣는다. **「변경 후」는 그 예약의 진짜 일시를 그대로 쓰고,**
    **「변경 전」만 일주일 앞선 날로 지어낸다.** 예약이 실제로 새 날짜에 있는
    것이 사실이므로, 지어내는 쪽은 사라진 옛 날짜뿐이다.

    화면에는 「미리 보기용 견본 값」이라고 적어 둔다.
    """
    before = sample.slot_date - timedelta(days=7)
    return {
        "変更前受診日": mail_service.format_date_ja(before),
        "変更前受診時刻": sample.time_label,
    }


def preview(
    db: Session,
    template_key: str,
    payload: MailTemplateSaveRequest | None = None,
) -> MailTemplatePreview:
    """실제 예약 1건을 넣어 치환 결과를 보여 준다.

    저장하기 전의 편집 중인 내용으로 미리 볼 수 있어야 한다.
    저장하고 나서야 결과를 알 수 있으면 이용자에게 잘못된 메일이 나간다.
    """
    sample = db.execute(
        select(Reservation)
        .where(Reservation.status != "CANCELLED")
        .order_by(Reservation.created_at.desc())
        .limit(1)
    ).scalars().first()

    if sample is None:
        return MailTemplatePreview(
            subject="",
            body="プレビューに使用できる予約がまだありません。"
            "予約が1件でも受付されると実際の値でご確認いただけます。",
        )

    context = mail_service.build_context(sample, preview_extra(sample))

    if payload is not None:
        subject, body = payload.subject, payload.body
    else:
        template = mail_service.get_template(db, template_key)
        db.commit()
        subject, body = template.subject, template.body

    return MailTemplatePreview(
        subject=mail_service.render(subject, context),
        body=mail_service.render(body, context),
        sample_reservation_no=sample.reservation_no,
    )


def list_logs(
    db: Session,
    *,
    status: str = "",
    keyword: str = "",
    page: int = 1,
    size: int = 30,
) -> Page[MailLogRow]:
    stmt = select(MailLog)

    if status:
        stmt = stmt.where(MailLog.status == status)
    if keyword:
        like = f"%{keyword.strip()}%"
        stmt = stmt.where(
            MailLog.reservation_no.like(like) | MailLog.to_email.like(like)
        )

    total = int(
        db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    )

    page = max(1, page)
    size = min(max(1, size), 200)

    rows = db.execute(
        stmt.order_by(MailLog.sent_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).scalars().all()

    return Page[MailLogRow](
        items=[
            MailLogRow(
                id=m.id,
                reservation_id=m.reservation_id,
                reservation_no=m.reservation_no,
                template_key=m.template_key,
                template_label=TEMPLATE_LABELS.get(m.template_key, m.template_key),
                to_email=m.to_email,
                subject=m.subject,
                status=m.status,
                status_label=m.status_label,
                error_message=m.error_message,
                sent_at=m.sent_at,
            )
            for m in rows
        ],
        total=total,
        page=page,
        size=size,
    )
