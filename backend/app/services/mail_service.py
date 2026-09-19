"""메일 렌더링 · 발송 (plan.md BR-11 / §9.10).

보내는 메일은 두 종류뿐이다.

    RESERVE_COMPLETE  예약 확정 직후
    REMINDER          검진 전날 12:00

본문은 DB(`mail_templates`)에 있고 관리 화면(A-40)에서 편집한다.
치환 변수는 `{{예약번호}}` 형태이며, 화면에 목록을 표시한다.

발신 인프라는 Resend API를 사용한다.
`RESEND_API_KEY` 가 비어 있으면 **실제 발송 없이 `mail_logs` 에만 기록**한다.
그래야 인프라가 정해지기 전에도 「무엇이 언제 나갔어야 하는가」가 남고,
설정을 채우는 순간 코드 수정 없이 실제 발송으로 바뀐다.
"""

import re
import resend

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.mail import (
    TEMPLATE_LOOKUP_LINK,
    TEMPLATE_REMINDER,
    TEMPLATE_RESERVE_CHANGE,
    TEMPLATE_RESERVE_CHANGE_BY_CLINIC,
    TEMPLATE_RESERVE_COMPLETE,
    TEMPLATE_SCHEDULE_CHANGED,
    MailLog,
    MailTemplate,
)
from app.models.reservation import Reservation

WEEKDAY_JA = ["月", "火", "水", "木", "金", "土", "日"]

# 화면(A-40)에 안내할 치환 변수 목록.
# 여기에 없는 변수를 본문에 써 두면 치환되지 않고 그대로 나간다.
TEMPLATE_VARIABLES: list[dict[str, str]] = [
    {"name": "{{お名前}}", "desc": "申込者のお名前 (例: 田中 太郎)"},
    {"name": "{{フリガナ}}", "desc": "申込者のフリガナ (例: タナカ タロウ)"},
    {"name": "{{予約番号}}", "desc": "予約番号 — 英数字12桁 (例: aK9mQ2xR7bTz)"},
    {"name": "{{会場名}}", "desc": "受診会場名"},
    {"name": "{{会場住所}}", "desc": "受診会場の住所"},
    {"name": "{{会場電話}}", "desc": "変更・キャンセルのお問い合わせ先電話番号 (会場固有の番号がない場合は予約センター)"},
    {"name": "{{アクセス}}", "desc": "会場へのアクセス案内"},
    {"name": "{{受診日}}", "desc": "受診日 (例: 2026年8月10日 (月))"},
    {"name": "{{受診時刻}}", "desc": "健診時間帯 (例: 10:00～10:30)"},
    {"name": "{{オプション検査}}", "desc": "申し込んだオプション検査一覧。ない場合は「なし」"},
    {"name": "{{確認リンク}}", "desc": "予約内容を照会できるショートカットリンク"},
    {"name": "{{問い合わせ電話}}", "desc": "Sample Groupのお問い合わせ電話番号"},
    {"name": "{{問い合わせメール}}", "desc": "Sample Groupのお問い合わせメールアドレス"},
    {"name": "{{問い合わせ時間}}", "desc": "Sample Groupのお問い合わせ受付時間"},
    # 아래 둘은 「검진일 변경 안내」에서만 값이 채워진다. 다른 문구에 쓰면
    # 바꿀 것이 없으므로 「-」 로 나간다.
    {"name": "{{変更前受診日}}", "desc": "変更前の受診日 — 変更案内メール専用"},
    {"name": "{{変更前受診時刻}}", "desc": "変更前の健診時間帯 — 変更案内メール専用"},
]

_PLACEHOLDER = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")


# 옛 변수 이름 → 지금 이름. DB 에 이미 저장된 문구를 위한 하위호환이다.
# (자세한 사정은 `build_context` 의 주석 참조)
LEGACY_VARIABLE_ALIASES: tuple[tuple[str, str], ...] = (
    # 「健診日」계열도 계속 받는다. 이용자 화면이 「受診日」로 통일되면서
    # 메일 변수 이름도 함께 바뀌었는데, 담당자가 A-40 에서 손댄 문구는
    # DB 에 옛 이름 그대로 남아 있기 때문이다.
    ("健診日", "受診日"),
    ("健診時刻", "受診時刻"),
    ("変更前健診日", "変更前受診日"),
    ("変更前健診時刻", "変更前受診時刻"),
    # 아래 한국어 이름은 **DB 저장 문안 하위호환용**이다. 새 문구에는 쓰지 않는다.
    ("성함", "お名前"),
    ("후리가나", "フリガナ"),
    ("예약번호", "予約番号"),
    ("회장명", "会場名"),
    ("회장주소", "会場住所"),
    ("회장전화", "会場電話"),
    ("가시는길", "アクセス"),
    ("검진일", "受診日"),
    ("검진시각", "受診時刻"),
    ("옵션검사", "オプション検査"),
    ("조회링크", "照会リンク"),
    ("문의전화", "問い合わせ電話"),
    ("문의메일", "問い合わせメール"),
    ("문의시간", "問い合わせ時間"),
    ("변경전검진일", "変更前受診日"),
    ("변경전검진시각", "変更前受診時刻"),
    ("병원명", "会場名"),
    ("병원주소", "会場住所"),
    ("병원전화", "会場電話"),
    # 「お」や「の」の有無だけが違う書き方も受ける。
    #
    # DB に入っている文面はこちらの書き方だった。画面の変数一覧は
    # 「問い合わせ電話」を案内しているのに、文面は「お問い合わせ電話」
    # だったため、置換されずに **{{お問い合わせ電話}} のまま受診者へ
    # 送信されていた**（予約完了・前日リマインド・日程変更の3種）。
    # 文面そのものは正しい名前に直したが、担当者が A-40 で編集した
    # 文面には古い書き方が残りうるので、ここでも受けておく。
    ("お問い合わせ電話", "問い合わせ電話"),
    ("お問い合わせメール", "問い合わせメール"),
    ("お問い合わせ時間", "問い合わせ時間"),
    ("受付時間", "問い合わせ時間"),
    ("変更前の受診日", "変更前受診日"),
    ("変更前の受診時刻", "変更前受診時刻"),
    # 画面のボタンは「メールで確認リンクを受け取る」、届くメールは
    # 「照会リンク」と、約束した言葉と届いた言葉が違っていた。
    # 利用者向けの言い方を「確認リンク」に寄せ、旧名も受ける。
    ("確認リンク", "照会リンク"),
)


def known_variable_names() -> set[str]:
    """문구에 써도 되는 치환 변수 이름 (중괄호 없이)."""
    names = {_PLACEHOLDER.fullmatch(v["name"]).group(1) for v in TEMPLATE_VARIABLES}
    names.update(old for old, _new in LEGACY_VARIABLE_ALIASES)
    return names


def unknown_variables(*texts: str) -> list[str]:
    """모르는 `{{변수}}`. 저장 전에 걸러, 글자 그대로 이용자에게 나가지 않게 한다."""
    known = known_variable_names()
    found: list[str] = []
    for text in texts:
        for match in _PLACEHOLDER.finditer(text or ""):
            name = match.group(1)
            if name not in known and match.group(0) not in found:
                found.append(match.group(0))
    return found


# ==========================================================================
# 기본 템플릿
#   DB 에 템플릿이 없을 때 투입되는 초기값이다.
#   변경·취소 절차 안내는 **반드시** 본문에 포함한다 (BR-10 / 자체 피드백 P-9).
# ==========================================================================

DEFAULT_TEMPLATES: dict[str, dict[str, str]] = {
    # 예약 확정 직후. 자동.
    TEMPLATE_RESERVE_COMPLETE: {
        "subject": "【Sample Group】健康診断のご予約が確定しました（予約番号 {{予約番号}}）",
        "body": """{{お名前}} 様

健康診断のご予約が確定いたしました。
下記の内容をご確認のうえ、このメールは受診日まで保管してください。

──────────────────────────────
■ 予約番号　　{{予約番号}}
■ 受診日時　　{{受診日}} {{受診時刻}}
■ 受診会場　　{{会場名}}
■ 会場住所　　{{会場住所}}
■ アクセス　　{{アクセス}}
■ お問い合わせ　{{問い合わせ電話}}
■ オプション検査　{{オプション検査}}
──────────────────────────────

■ 当日お持ちいただくもの
  ・ 健康保険証
  ・ このメール（予約番号を確認できる画面または印刷したもの）
  ・ オプション検査をお申し込みの方は、ご案内した準備物

■ ご予約の変更・キャンセルについて
  変更・キャンセルは、このサイトではお受けできません。
  受診日の3日前までに、下記へお電話ください。

      {{問い合わせ電話}}　{{問い合わせ時間}}

■ お問い合わせ
  医療法人 Sample Group 健康診断予約センター
  電話 {{問い合わせ電話}} / メール {{問い合わせメール}}
  受付時間 {{問い合わせ時間}}

※ このメールは送信専用です。ご返信いただいてもお答えできません。""",
    },
    # 수진일 전날 12:00. 자동 (cron).
    TEMPLATE_REMINDER: {
        "subject": "【Sample Group】明日は健康診断の受診日です（予約番号 {{予約番号}}）",
        "body": """{{お名前}} 様

明日、健康診断のご予約が入っております。お忘れなくお越しください。

──────────────────────────────
■ 予約番号　　{{予約番号}}
■ 受診日時　　{{受診日}} {{受診時刻}}
■ 受診会場　　{{会場名}}
■ 会場住所　　{{会場住所}}
■ アクセス　　{{アクセス}}
■ お問い合わせ　{{問い合わせ電話}}
■ オプション検査　{{オプション検査}}
──────────────────────────────

■ 当日お持ちいただくもの
  ・ 健康保険証
  ・ このメール（予約番号を確認できる画面または印刷したもの）

■ お越しになれなくなった場合
  {{問い合わせ電話}} までお電話ください。

■ お問い合わせ
  医療法人 Sample Group 健康診断予約センター
  電話 {{問い合わせ電話}} / メール {{問い合わせメール}}
  受付時間 {{問い合わせ時間}}

※ このメールは送信専用です。ご返信いただいてもお答えできません。""",
    },
    # 일시를 옮긴 뒤 담당자가 보낸다.
    TEMPLATE_SCHEDULE_CHANGED: {
        "subject": "【Sample Group】健康診断 日程変更のお知らせ（予約番号 {{予約番号}}）",
        "body": """{{お名前}} 様

お電話でご案内いたしましたとおり、健康診断の日程が下記のとおり変更となりました。
このメールを確認用として保管してください。

──────────────────────────────
■ 予約番号　　{{予約番号}}

  変更前　　{{変更前受診日}} {{変更前受診時刻}}
  変更後　　{{受診日}} {{受診時刻}}

■ 受診会場　　{{会場名}}
■ 会場住所　　{{会場住所}}
■ アクセス　　{{アクセス}}
■ オプション検査　{{オプション検査}}
──────────────────────────────

■ 当日お持ちいただくもの
  ・ 健康保険証
  ・ このメール（予約番号を確認できる画面または印刷したもの）
  ・ オプション検査をお申し込みの方は、ご案内した準備物

■ 再度ご変更の場合
  受診日の3日前までに、下記の予約センターへお電話ください。

■ お問い合わせ
  医療法人 Sample Group 健康診断予約センター
  電話 {{問い合わせ電話}} / メール {{問い合わせメール}}
  受付時間 {{問い合わせ時間}}

※ このメールは送信専用です。ご返信いただいてもお答えできません。""",
    },
    # 이용자가 예약 내용을 바꿨을 때.
    TEMPLATE_RESERVE_CHANGE: {
        "subject": "【Sample Group】健康診断のご予約内容を変更いたしました（予約番号 {{予約番号}}）",
        "body": """{{お名前}} 様

健康診断のご予約内容を変更いたしました。
下記の内容をご確認のうえ、このメールは受診日まで保管してください。

──────────────────────────────
■ 予約番号　　　　　{{予約番号}}
■ 受診日時　　　　　{{受診日}} {{受診時刻}}
■ 受診会場　　　　　{{会場名}}
■ 会場住所　　　　　{{会場住所}}
■ アクセス　　　　　{{アクセス}}
■ オプション検査　　{{オプション検査}}
──────────────────────────────

■ 当日お持ちいただくもの
  ・ 健康保険証
  ・ このメール（予約番号を確認できる画面または印刷したもの）
  ・ オプション検査をお申し込みの方は、ご案内した事前のご準備

■ ご予約の変更・キャンセルについて
  ご予約の変更・キャンセルは、当サイトではお受けできません。
  受診日の3日前までに、下記の予約センターへお電話ください。

      {{問い合わせ電話}}　{{問い合わせ時間}}

■ お問い合わせ
  医療法人 Sample Group 健康診断予約センター
  電話 {{問い合わせ電話}} / メール {{問い合わせメール}}
  受付時間 {{問い合わせ時間}}

※ このメールは送信専用です。ご返信いただいてもお答えできません。""",
    },
    # 휴진으로 회장 사정이 바뀌었을 때.
    TEMPLATE_RESERVE_CHANGE_BY_CLINIC: {
        "subject": "【Sample Group】会場休診にともなう受診日変更のお知らせ（予約番号 {{予約番号}}）",
        "body": """{{お名前}} 様

このたび、ご予約いただいていた日は会場が休診となりましたため、
健康診断の受診日を下記のとおり変更させていただきました。
ご迷惑をおかけいたしますことを深くお詫び申し上げます。

下記の内容をご確認のうえ、このメールは受診日まで保管してください。

──────────────────────────────
■ 予約番号　　　　　{{予約番号}}
■ 受診日時　　　　　{{受診日}} {{受診時刻}}
■ 受診会場　　　　　{{会場名}}
■ 会場住所　　　　　{{会場住所}}
■ アクセス　　　　　{{アクセス}}
■ オプション検査　　{{オプション検査}}
──────────────────────────────

■ 変更後の日程でのご受診が難しい場合
  当サイトでの変更・キャンセルはお受けできません。
  お手数ですが、下記の予約センターへお早めにお電話ください。

      {{問い合わせ電話}}　{{問い合わせ時間}}

■ 当日お持ちいただくもの
  ・ 健康保険証
  ・ このメール（予約番号を確認できる画面または印刷したもの）
  ・ オプション検査をお申し込みの方は、ご案内した事前のご準備

■ お問い合わせ
  医療法人 Sample Group 健康診断予約センター
  電話 {{問い合わせ電話}} / メール {{問い合わせメール}}
  受付時間 {{問い合わせ時間}}

※ このメールは送信専用です。ご返信いただいてもお答えできません。""",
    },
    # 예약번호 조회 화면에서 요청했을 때.
    TEMPLATE_LOOKUP_LINK: {
        "subject": "【Sample Group】ご予約内容の確認リンクのご案内",
        "body": """{{お名前}} 様

ご依頼いただいた健康診断のご予約内容について、確認リンクをご案内いたします。
下記のリンクを開くと、ご予約の内容をご確認いただけます。

確認リンク: {{確認リンク}}

■ お問い合わせ
  医療法人 Sample Group 健康診断予約センター
  電話 {{問い合わせ電話}} / メール {{問い合わせメール}}
  受付時間 {{問い合わせ時間}}

※ このメールは送信専用です。ご返信いただいてもお答えできません。""",
    },
}


# ==========================================================================
# 템플릿 조회 · 치환
# ==========================================================================


def get_template(db: Session, template_key: str) -> MailTemplate:
    """템플릿을 가져온다. 없으면 기본값으로 만들어 둔다."""
    template = db.execute(
        select(MailTemplate).where(MailTemplate.template_key == template_key)
    ).scalar_one_or_none()

    if template is None:
        default = DEFAULT_TEMPLATES.get(template_key, {"subject": "", "body": ""})
        template = MailTemplate(
            template_key=template_key,
            subject=default["subject"],
            body=default["body"],
            updated_by="初期値",
        )
        db.add(template)
        db.flush()

    return template


def format_date_ja(value) -> str:
    """2026-08-10 → 2026年8月10日（月）"""
    return (
        f"{value.year}年{value.month}月{value.day}日"
        f"（{WEEKDAY_JA[value.weekday()]}）"
    )


def build_context(
    reservation: Reservation,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """치환 변수 값을 만든다."""
    hospital = reservation.hospital
    options = [o.option_name for o in reservation.options]

    context = {
        "お名前": reservation.full_name,
        "フリガナ": reservation.full_name_kana,
        "予約番号": reservation.reservation_no,
        "会場名": hospital.name if hospital else "",
        "会場住所": hospital.address if hospital else "",
        "会場電話": hospital.contact_tel if hospital else "",
        "アクセス": hospital.access_info if hospital else "",
        "受診日": format_date_ja(reservation.slot_date),
        "受診時刻": reservation.time_label,
        "オプション検査": " / ".join(options) if options else "なし",
        "照会リンク": f"{settings.FRONTEND_URL}/lookup.html?reservation_no={reservation.reservation_no}",
        "問い合わせ電話": settings.CONTACT_TEL,
        "問い合わせメール": settings.CONTACT_EMAIL,
        "問い合わせ時間": settings.CONTACT_HOURS,
    }

    # 예전 이름도 계속 받는다.
    #
    # 검진 장소를 「병원」에서 「회장」으로 부르기로 바꾸면서 변수 이름도 바꿨는데,
    # **DB 에 이미 저장된 문구는 예전 이름 그대로다.** 담당자가 손댄 문구라면
    # 더욱 그렇다. 새 이름만 받으면 그 문구들이 `{{병원명}}` 을 글자 그대로
    # 내보내게 되고, 그 메일은 이용자에게 그대로 간다.
    #
    # 화면의 변수 목록(`PLACEHOLDERS`)에는 새 이름만 싣는다. 예전 이름은
    # 「아직 동작하지만 권하지 않는」 것이지 새로 쓸 것이 아니다.
    for old, new in (("病院名", "会場名"), ("病院住所", "会場住所"), ("病院電話", "会場電話")):
        context[old] = context[new]

    # 변경 안내 전용 변수. 값이 없을 때 빈칸으로 두지 않는 이유는, 빈칸이면
    # 「변경 전    변경 후 10월 22일」 처럼 한쪽만 비어 나가서 받는 사람이
    # 무엇이 바뀌었는지 읽을 수 없기 때문이다.
    context.setdefault("変更前受診日", "-")
    context.setdefault("変更前受診時刻", "-")

    # 한국어 변수명도 계속 받는다.
    #
    # 화면 문구를 일본어로 바꾸면서 치환 변수 이름도 함께 바꿨는데,
    # **DB 에 이미 저장된 문구는 한국어 이름 그대로다.** 담당자가 A-40 에서
    # 손댄 문구라면 더욱 그렇다. 새 이름만 받으면 그 문구들이 `{{성함}}` 을
    # 글자 그대로 내보내게 되고, 그 메일은 이용자에게 그대로 간다.
    #
    # 화면의 변수 목록(`TEMPLATE_VARIABLES`)에는 새 이름만 싣는다. 예전 이름은
    # 「아직 동작하지만 권하지 않는」 것이지 새로 쓸 것이 아니다.
    for old, new in LEGACY_VARIABLE_ALIASES:
        context[old] = context[new]

    if extra:
        context.update(extra)

    return context


def render(text: str, context: dict[str, str]) -> str:
    """`{{변수}}` 를 값으로 바꾼다.

    모르는 변수는 지우지 않고 그대로 남긴다. 조용히 사라지면
    편집자가 오타를 알아채지 못한 채 그 상태로 메일이 나간다.
    """
    return _PLACEHOLDER.sub(
        lambda m: context.get(m.group(1), m.group(0)), text or ""
    )


def preview(db: Session, template_key: str, reservation: Reservation) -> tuple[str, str]:
    """편집 화면의 미리 보기용. 제목·본문을 치환해서 돌려준다."""
    template = get_template(db, template_key)
    context = build_context(reservation)
    return render(template.subject, context), render(template.body, context)


# ==========================================================================
# 발송
# ==========================================================================


def _resend_send(to_email: str, subject: str, body: str) -> None:
    """실제 Resend API 발송. 설정이 비어 있으면 이 함수는 호출되지 않는다."""
    resend.api_key = settings.RESEND_API_KEY
    resend.Emails.send({
        "from": f"{settings.MAIL_FROM_NAME} <{settings.MAIL_FROM}>",
        "to": [to_email],
        "subject": subject,
        "text": body,
    })


def send(
    db: Session,
    reservation: Reservation,
    template_key: str,
    extra: dict[str, str] | None = None,
) -> MailLog:
    """메일을 보내고 이력을 남긴다. (커밋하지 않는다)

    실패해도 예외를 밖으로 던지지 않는다. 메일이 안 나갔다고 해서
    이미 확정된 예약을 되돌리면 이용자는 영문도 모른 채 예약을 잃는다.
    실패는 `mail_logs` 에 남기고 대시보드에서 사람이 처리한다 (M-12).
    """
    template = get_template(db, template_key)
    context = build_context(reservation, extra)

    subject = render(template.subject, context)
    body = render(template.body, context)

    log = MailLog(
        reservation_id=reservation.id,
        reservation_no=reservation.reservation_no,
        template_key=template_key,
        to_email=reservation.email or "",
        subject=subject,
        body=body,
    )

    if not reservation.email:
        # 이메일 미입력은 실패가 아니다. 「왜 메일이 안 왔냐」는 문의에
        # 「등록된 주소가 없습니다」라고 정확히 답할 수 있어야 한다.
        log.status = "SKIPPED"
        log.error_message = "メールアドレスが登録されていません。"
    elif not settings.RESEND_API_KEY:
        log.status = "SKIPPED"
        log.error_message = "メール送信APIキーが設定されていません。（本文のみ記録）"
    else:
        try:
            _resend_send(reservation.email, subject, body)
            log.status = "SUCCESS"
        except Exception as exc:  # noqa: BLE001 — 발송 실패로 예약을 깨뜨리지 않는다
            error_str = str(exc)
            if "You can only send testing emails" in error_str:
                log.status = "SKIPPED"
                log.error_message = "テスト環境制限のため送信スキップ（" + error_str[:100] + "）"
            else:
                log.status = "FAILED"
                log.error_message = error_str[:255]

    db.add(log)
    return log


def send_reserve_complete(db: Session, reservation: Reservation) -> MailLog:
    return send(db, reservation, TEMPLATE_RESERVE_COMPLETE)


def send_reserve_change(db: Session, reservation: Reservation) -> MailLog:
    return send(db, reservation, TEMPLATE_RESERVE_CHANGE)


def send_reserve_change_by_clinic(db: Session, reservation: Reservation) -> MailLog:
    return send(db, reservation, TEMPLATE_RESERVE_CHANGE_BY_CLINIC)

def send_schedule_changed(
    db: Session,
    reservation: Reservation,
    before_date: str,
    before_time: str,
) -> MailLog:
    """검진 일시를 옮긴 뒤 보내는 안내.

    `reservation` 은 이미 **새 일시로 바뀐 뒤**다. 옛 일시는 바꾸기 직전에
    붙잡아 두었다가 여기로 넘겨야 한다 — 예약 객체에서는 더 꺼낼 수 없다.
    """
    return send(db, reservation, TEMPLATE_SCHEDULE_CHANGED, {
        "変更前受診日": before_date,
        "変更前受診時刻": before_time,
    })



def send_reminder(db: Session, reservation: Reservation) -> MailLog:
    return send(db, reservation, TEMPLATE_REMINDER)


def send_lookup_link(db: Session, reservation: Reservation) -> MailLog:
    return send(db, reservation, TEMPLATE_LOOKUP_LINK)
