"""조작 로그 기록 (plan.md §9.9 / 자체 피드백 M-8).

모든 관리자 조작은 예외 없이 여기를 거친다.
「누가 · 언제 · 무엇을 · 무엇에서 무엇으로」 네 가지가 남지 않으면
나중에 문의가 들어왔을 때 답할 수 없다.

`db.commit()` 은 하지 않는다. 조작과 로그는 **같은 트랜잭션**이어야 한다.
조작이 롤백되었는데 로그만 남으면 없었던 일이 기록으로 남는다.
"""

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.admin import AdminUser, AuditLog

# 조작 종류. 화면 필터에 그대로 쓰이므로 한국어 라벨을 함께 둔다.
ACTION_LABELS: dict[str, str] = {
    "ADMIN_LOGIN": "ログイン",
    "ADMIN_LOGIN_FAILED": "ログイン失敗",
    "ADMIN_LOGOUT": "ログアウト",
    "RESERVATION_CREATE_WEB": "Web予約受付",
    "RESERVATION_CREATE_POSTAL": "郵送受付登録",
    "POSTAL_BULK_EXPORT": "郵送一括シート書き出し",
    "POSTAL_BULK_IMPORT": "郵送一括シート取り込み",
    "RESERVATION_UPDATE": "予約修正",
    "RESERVATION_CANCEL": "予約キャンセル",
    "RESERVATION_RESTORE": "予約キャンセル取り消し",
    "RESERVATION_PURGE": "期間経過予約の自動削除",
    "CONTACT_ADD": "連絡履歴追加",
    "HOSPITAL_CREATE": "会場登録",
    "HOSPITAL_UPDATE": "会場修正",
    "HOSPITAL_DELETE": "会場削除",
    "HOSPITAL_SCHEDULE_SAVE": "会場日程保存",
    "HOSPITAL_SCHEDULE_DELETE": "開催回削除",
    "HOSPITAL_BULK_SAVE": "会場一括保存",
    "HOSPITAL_BULK_EXPORT": "会場マスター書き出し",
    "HOSPITAL_BULK_IMPORT": "会場マスター取り込み",
    "SLOT_UPDATE": "定員変更",
    "SLOT_BULK_UPDATE": "定員一括変更",
    "EXAM_OPTION_CREATE": "オプション検査登録",
    "EXAM_OPTION_UPDATE": "オプション検査修正",
    "EXAM_OPTION_DELETE": "オプション検査削除",
    "MAIL_TEMPLATE_UPDATE": "メールテンプレート修正",
    "MAIL_RESEND": "メール再送信",
    "ACCOUNT_CREATE": "アカウント登録",
    "ACCOUNT_UPDATE": "アカウント修正",
    "ACCOUNT_PASSWORD_RESET": "パスワード再設定",
    "EXAM_OPTION_BULK_SAVE": "オプション検査一括保存",
    "BULK_SHEET_EXPORT": "シート書き出し",
    "BULK_SHEET_IMPORT": "シート取り込み",
    "POSTAL_IMPORT": "郵便番号データ取り込み",
    # 되돌리기는 **새 조작**으로 남긴다. 기록을 지우지 않는다 —
    # 되돌렸다는 사실 자체가 남아야 나중에 설명할 수 있다.
    "BATCH_REVERT": "一括保存を元に戻す",
    "RECORD_RESTORE": "削除を元に戻す",
}


def action_label(action: str) -> str:
    return ACTION_LABELS.get(action, action)


def new_batch_id() -> str:
    """일괄 저장 하나를 가리키는 열쇠. 저장 시작 때 한 번 만든다."""
    return uuid.uuid4().hex


def _jsonable(value: Any) -> Any:
    """JSON 컬럼에 넣을 수 있는 형태로 낮춘다.

    date / datetime / time / Decimal 은 그대로 넣으면 직렬화에 실패한다.

    여기서 빠뜨린 형이 하나 있으면 **그 형을 쓰는 조작 전체가 500 이 된다.**
    로그를 남기지 못해 조작까지 롤백되기 때문이다(로그와 조작이 같은
    트랜잭션이므로). 회장에 개최일·개시 시각이 생겼을 때 실제로 그렇게 됐다.
    """
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    # time 은 초 단위 없이 HH:MM 만 남긴다
    if isinstance(value, time):
        return value.strftime("%H:%M")
    # datetime 은 date 의 하위형이므로 isinstance 한 번으로 함께 걸린다.
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def write_log(
    db: Session,
    *,
    admin: AdminUser | None,
    action: str,
    target_type: str = "",
    target_id: int | None = None,
    target_label: str = "",
    before: dict | None = None,
    after: dict | None = None,
    ip_address: str = "",
    batch_id: str = "",
) -> AuditLog:
    """조작 로그를 1건 남긴다. (커밋하지 않는다)

    `batch_id` 는 **한 번의 일괄 저장에서 나온 로그를 묶는** 열쇠다.
    표에서 저장을 한 번 누르면 회장 21곳이 각각 로그를 남기는데, 목록에서는
    21줄이 나란히 보일 뿐이라 어디까지가 한 조작이었는지 알 수 없었다.
    `new_batch_id()` 로 한 번 만들어 그 저장의 모든 로그에 같은 값을 준다.
    """
    log = AuditLog(
        admin_user_id=admin.id if admin else None,
        admin_login_id=admin.login_id if admin else "system",
        admin_name=admin.name if admin else "システム",
        action=action,
        target_type=target_type,
        target_id=target_id,
        target_label=target_label[:255],
        before_json=_jsonable(before) if before is not None else None,
        after_json=_jsonable(after) if after is not None else None,
        ip_address=ip_address[:45],
        batch_id=(batch_id or "")[:40],
    )
    db.add(log)
    return log


def write_system_log(
    db: Session,
    *,
    action: str,
    target_type: str = "",
    target_id: int | None = None,
    target_label: str = "",
    before: dict | None = None,
    after: dict | None = None,
) -> AuditLog:
    """사람이 아니라 시스템이 한 조작(배치·자동 정리)을 남긴다."""
    return write_log(
        db,
        admin=None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        target_label=target_label,
        before=before,
        after=after,
    )


def snapshot(obj: Any, fields: list[str]) -> dict:
    """모델 인스턴스에서 지정한 필드만 뽑아 변경 전/후 비교용 dict 를 만든다."""
    return {f: _jsonable(getattr(obj, f, None)) for f in fields}


def diff(before: dict, after: dict) -> dict:
    """실제로 바뀐 항목만 남긴다.

    전체를 그대로 남기면 조작 로그 목록에서 「무엇이 바뀌었는지」를
    사람이 눈으로 찾아야 한다.

    양쪽이 모두 dict인 값(예: cells)은 내부 키 단위로 비교해
    실제로 달라진 키만 남긴다. 16칸 전체를 쓰면 「어느 시간대가
    바뀌었는지」 사람이 눈으로 찾아야 한다.
    """
    changed = {}
    for key in after:
        bv = before.get(key)
        av = after.get(key)
        if bv == av:
            continue
        # 양쪽 모두 dict이면 내부 키 단위 diff
        if isinstance(bv, dict) and isinstance(av, dict):
            sub_before = {}
            sub_after = {}
            all_keys = set(bv) | set(av)
            for sk in all_keys:
                if bv.get(sk) != av.get(sk):
                    sub_before[sk] = bv.get(sk)
                    sub_after[sk] = av.get(sk)
            if sub_before or sub_after:
                changed[key] = {"before": sub_before, "after": sub_after}
        else:
            changed[key] = {"before": bv, "after": av}
    return changed


def text_diff(old_text: str, new_text: str) -> str:
    """긴 문자열의 변경 전후를 비교해 바뀐 부분(diff)만 읽기 쉬운 문자열로 반환한다."""
    import difflib

    old_lines = (old_text or "").splitlines()
    new_lines = (new_text or "").splitlines()
    diff_lines = list(
        difflib.unified_diff(old_lines, new_lines, n=1, lineterm="")
    )
    if not diff_lines:
        return ""

    result = []
    # 처음 두 줄(--- 변경 전, +++ 변경 후) 생략
    for line in diff_lines[2:]:
        if line.startswith("@@"):
            result.append("\n[変更箇所]")
        elif line.startswith("-"):
            result.append(f"削除: {line[1:]}")
        elif line.startswith("+"):
            result.append(f"追加: {line[1:]}")
        else:
            result.append(f"原文: {line[1:]}")

    return "\n".join(result).strip()


def list_admin_choices(db: Session) -> list[AdminUser]:
    """조작 로그 화면의 「담당자」 필터 선택지."""
    return list(
        db.execute(select(AdminUser).order_by(AdminUser.name)).scalars().all()
    )
