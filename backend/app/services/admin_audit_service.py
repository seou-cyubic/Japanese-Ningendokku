"""관리 화면 — 조작 로그 조회 (A-60).

L3(시스템 관리자) 전용. 여기서 답할 수 있어야 하는 질문은 하나다.
**「이 예약, 누가 언제 이렇게 만들었나?」**
"""

from datetime import date, datetime, time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.admin import AuditLog
from app.schemas.admin import AuditLogRow, Page
from app.services.audit_service import ACTION_LABELS, action_label


def list_logs(
    db: Session,
    *,
    keyword: str = "",
    action: str = "",
    admin_user_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    log_id_from: int | None = None,
    log_id_to: int | None = None,
    page: int = 1,
    size: int = 40,
) -> Page[AuditLogRow]:
    stmt = select(AuditLog)

    if keyword:
        like = f"%{keyword.strip()}%"
        stmt = stmt.where(
            AuditLog.target_label.like(like)
            | AuditLog.admin_login_id.like(like)
            | AuditLog.admin_name.like(like)
        )
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if admin_user_id:
        stmt = stmt.where(AuditLog.admin_user_id == admin_user_id)
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        stmt = stmt.where(AuditLog.created_at <= datetime.combine(date_to, time.max))
    if log_id_from is not None:
        stmt = stmt.where(AuditLog.id >= log_id_from)
    if log_id_to is not None:
        stmt = stmt.where(AuditLog.id <= log_id_to)

    total = int(
        db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    )

    page = max(1, page)
    size = min(max(1, size), 200)

    rows = db.execute(
        stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).scalars().all()

    return Page[AuditLogRow](
        items=[
            AuditLogRow(
                id=log.id,
                admin_login_id=log.admin_login_id,
                admin_name=log.admin_name,
                action=log.action,
                action_label=action_label(log.action),
                target_type=log.target_type,
                target_id=log.target_id,
                target_label=_clean_target_label(log.target_label, log.after_json, log.action),
                before_json=log.before_json,
                after_json=log.after_json,
                ip_address=log.ip_address,
                created_at=log.created_at,
            )
            for log in rows
        ],
        total=total,
        page=page,
        size=size,
    )


def action_choices() -> list[dict]:
    """필터의 조작 종류 선택지."""
    return [{"value": key, "label": label} for key, label in ACTION_LABELS.items()]


def list_batches(db: Session, *, limit: int = 30) -> list[dict]:
    """되돌릴 수 있는 일괄 저장 목록. 한 줄이 「저장을 한 번 누른 것」이다.

    로그 목록에서는 회장 21곳이 21줄로 나란히 보일 뿐이라, 어디부터
    어디까지가 한 번의 조작이었는지 알 수 없다. 그 경계를 `batch_id` 로
    묶어 「무슨 저장이었나」를 한 줄로 보여 준다.

    요약 로그(`*_BULK_SAVE`)가 그 저장의 제목이고, 같은 batch 의 나머지
    로그 수가 그 저장이 건드린 건수다.
    """
    from app.services.admin_revert_service import REVERTABLE, SUMMARY_ACTIONS

    # 요약 로그를 최근 순으로. 이것이 일괄 저장 하나를 대표한다.
    summaries = db.execute(
        select(AuditLog)
        .where(
            AuditLog.action.in_(tuple(SUMMARY_ACTIONS)),
            AuditLog.batch_id != "",
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
    ).scalars().all()

    if not summaries:
        return []

    batch_ids = [s.batch_id for s in summaries]

    # 각 batch 가 건드린 행 수. 한 번에 세어 N+1 을 피한다.
    counts = dict(
        db.execute(
            select(AuditLog.batch_id, func.count())
            .where(
                AuditLog.batch_id.in_(batch_ids),
                AuditLog.action.in_(tuple(REVERTABLE)),
            )
            .group_by(AuditLog.batch_id)
        ).all()
    )

    # 이미 되돌린 저장. 되돌리기 로그의 `after_json.batch_id` 가 원래 batch 를 가리킨다.
    #
    # 라벨(target_label)에서 찾지 않는다. 라벨은 사람이 읽는 문구라 형식이
    # 바뀌는데, 예전에 라벨에서 batch_id 앞자리를 찾다가 문구가 바뀐 뒤로
    # 되돌린 저장도 늘 「元に戻す」로 남았다.
    reverted = {
        str((row.after_json or {}).get("batch_id", ""))
        for row in db.execute(
            select(AuditLog).where(AuditLog.action == "BATCH_REVERT")
        ).scalars()
    }
    reverted.discard("")

    out = []
    for log in summaries:
        out.append({
            "batch_id": log.batch_id,
            "action": log.action,
            "action_label": action_label(log.action),
            "title": _clean_target_label(log.target_label, log.after_json, log.action),
            "admin_name": log.admin_name,
            "admin_login_id": log.admin_login_id,
            "created_at": log.created_at,
            "row_count": int(counts.get(log.batch_id, 0)),
            "is_reverted": log.batch_id in reverted,
        })
    return out


TARGET_TYPE_LABELS: dict[str, str] = {
    "reservation": "予約",
    "hospital": "会場",
    "hospital_schedule": "会場日程・定員",
    "schedule": "会場日程・定員",
    "admin_user": "管理者アカウント",
    "exam_option": "オプション検査",
    "mail_template": "メールテンプレート",
    "postal_code": "郵便番号",
    "batch": "一括処理",
    "sheet": "シート",
    "contact": "連絡履歴",
    "slot": "時間帯枠",
}

FIELD_LABELS: dict[str, str] = {
    # 予約・受診者情報
    "id": "識別番号",
    "reservation_no": "予約番号",
    "slot_id": "時間帯識別番号",
    "schedule_id": "日程識別番号",
    "hospital_id": "会場識別番号",
    "slot_date": "受診日",
    "time_label": "受診日時",
    "start_time": "開始時刻",
    "end_time": "終了時刻",
    "channel": "受付経路",
    "status": "ステータス",
    "admin_notes": "管理者メモ",
    "option_names": "オプション検査",
    "hospital": "会場",
    "time": "健診時間",
    "choice": "希望順位",
    "defect": "不備理由",
    "cancel_reason": "キャンセル理由",
    "memo": "メモ",
    "has_defect": "不備有無",
    "defect_note": "不備理由",
    "fiscal_year": "会計年度",
    "created_by_admin_id": "作成管理者ID",
    "cancelled_at": "キャンセル日時",
    "target_person_id": "対象者識別番号",
    "last_name": "姓",
    "first_name": "名",
    "middle_name": "ミドルネーム",
    "last_name_kana": "姓（カナ）",
    "first_name_kana": "名（カナ）",
    "middle_name_kana": "ミドルネーム（カナ）",
    "gender": "性別",
    "birth_date": "生年月日",
    "insurer_no": "保険者番号",
    "insurance_symbol": "保険証記号",
    "insurance_no": "保険証番号",
    "postal_code": "郵便番号",
    "address": "住所",
    "address_detail": "番地",
    "building": "建物名",
    "tel_mobile": "携帯電話",
    "tel_home": "固定電話",
    "email": "メールアドレス",

    # 会場・日程情報
    "code": "会場コード",
    "name": "会場名",
    "name_kana": "会場名（フリガナ）",
    "area": "地域",
    "city": "市区町村",
    "transit_info": "交通情報",
    "access_minutes": "所要時間",
    "event_date": "開催日",
    "booking_close_date": "予約締切日",
    "open_time": "開始時刻",
    "reception_end_time": "受付終了時刻",
    "has_parking": "駐車場の有無",
    "latitude": "緯度",
    "longitude": "経度",
    "tel": "電話番号",
    "is_visible": "予約画面表示",
    "schedules": "開催日程",
    "sort_order": "並び順",
    "closed": "休診状態",
    "is_closed": "休診の有無",

    # オプション検査
    "option_type": "オプション種別",
    "price": "料金",
    "description": "オプション説明",
    "note": "注意事項",
    "target_gender": "対象性別",
    "target_age_min": "最小対象年齢",
    "target_age_max": "最大対象年齢",

    # 連絡履歴
    "method": "連絡方法",
    "result": "連絡結果",
    "count": "連絡回数",

    # ファイル・一括処理
    "rows": "データ行数",
    "format": "ファイル形式",
    "kind": "データ種別",
    "header_mode": "ヘッダー行の有無",
    "encoding": "文字コード",
    "sheet": "シート名",
    "batch_id": "一括処理ID",

    # 管理者アカウント
    "login_id": "ログインID",
    "admin_login_id": "管理者ID",
    "admin_name": "管理者名",
    "role": "権限",
    "is_active": "有効状態",

    # メール
    "template": "メール種別",
    "subject": "件名",
    "body_diff": "本文の変更内容",

    # 定員・枠
    "cells": "時間帯別定員",
    "dates": "対象日",
    "delta": "定員の増減",
    "updated": "更新件数",
    "updated_slots": "変更された時間帯枠",
    "blocked": "ブロック件数",
    "set_closed": "受付停止の有無",

    # 処理件数・その他
    "created": "新規登録件数",
    "unchanged": "変更なし件数",
    "deleted": "削除件数",
    "skipped": "スキップ件数",
    "reverted": "元に戻した件数",
    "items": "変更対象詳細",
    "cutoff": "削除基準日時",
    "grace_minutes": "猶予時間（分）",
    "deleted_reservations": "削除された予約一覧",
    "changed": "変更項目",
}

VALUE_LABELS: dict[str, str] = {
    # 予約ステータス
    "CONFIRMED": "確定",
    "PENDING": "不備（仮受付）",
    "PENDING_DEFECT": "不備（仮受付）",
    "CANCELLED": "キャンセル",
    "COMPLETED": "受診完了",

    # 対象性別
    "ALL": "全員対象",

    # 受付経路
    "WEB": "Web予約",
    "POSTAL": "郵送受付",
    "PHONE": "電話",
    "EMAIL": "メール",
    "MAIL": "郵送",

    # 性別
    "M": "男性",
    "F": "女性",

    # 管理者権限
    "SYSTEM_ADMIN": "システム管理者",
    "BUSINESS_ADMIN": "業務管理者",
    "STAFF": "一般スタッフ",

    # 連絡結果
    "CONNECTED": "応答",
    "NO_ANSWER": "不在",
    "LEFT_MESSAGE": "伝言残し",
    "CALLBACK_REQUESTED": "折り返し希望",

    # メールテンプレート種別
    "RESERVE_COMPLETE": "予約確定案内メール",
    "REMINDER": "リマインダーメール",
    "confirmation": "予約確認メール",
    "cancellation": "キャンセル案内メール",
    "reminder": "リマインダーメール",

    # シート名
    "capacity": "定員カレンダー",
    "hospital": "会場マスター",
    "exam_option": "オプション検査マスター",
    "postal_code": "郵便番号",

    # 操作・処理結果
    "SUCCESS": "成功",
    "FAILED": "失敗",
    "RESTORE": "元に戻す",
    "DELETE": "削除",
    "UPSERT": "追加・更新",
}


def _format_value(k: str, val) -> str:
    """단일 값을 사람이 읽기 쉬운 문자열로 변환한다."""
    if val is None or val == "":
        return "なし"
    if val is True:
        if k in ("is_closed", "closed", "set_closed"):
            return "休診（受付停止）"
        if k == "has_parking":
            return "あり"
        if k == "is_visible":
            return "表示"
        if k == "is_active":
            return "有効"
        if k == "has_defect":
            return "あり"
        return "はい"
    if val is False:
        if k in ("is_closed", "closed", "set_closed"):
            return "通常受付"
        if k == "has_parking":
            return "なし"
        if k == "is_visible":
            return "非表示"
        if k == "is_active":
            return "無効"
        if k == "has_defect":
            return "なし"
        return "いいえ"
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        if k in ("price",):
            return f"{int(val):,}円"
        if k in ("delta",):
            sign = "+" if val > 0 else ""
            return f"{sign}{val}名"
        if k in ("updated", "created", "unchanged", "deleted", "skipped", "reverted", "blocked"):
            return f"{val}件"
        if k in ("access_minutes", "grace_minutes"):
            return f"{val}分"
        return str(val)
    if isinstance(val, str):
        if val in VALUE_LABELS:
            return VALUE_LABELS[val]
        # 시각 초 단위 절삭: "15:00:00" -> "15:00"
        if len(val) == 8 and val[2] == ":" and val[5] == ":" and val[:2].isdigit() and val[3:5].isdigit() and val[6:].isdigit():
            return val[:5]
        return val
    return str(val)


def _format_cells(val) -> str:
    """cells(時間帯別定員) 데이터를 사람이 읽기 쉬운 문자열로 변환한다."""
    if not val:
        return "設定なし"
    if isinstance(val, dict):
        if "before" in val and "after" in val:
            vb = val.get("before") or {}
            va = val.get("after") or {}
            all_slots = sorted(set(list(vb.keys()) + list(va.keys())))
            changes = []
            for s in all_slots:
                b = vb.get(s)
                a = va.get(s)
                if b != a:
                    b_str = f"{b}名" if b is not None else "受付枠なし"
                    a_str = f"{a}名" if a is not None else "受付枠なし"
                    note = ""
                    if isinstance(b, (int, float)) and isinstance(a, (int, float)):
                        d = a - b
                        if d > 0:
                            note = f"（+{d}名増加）"
                        elif d < 0:
                            note = f"（{abs(d)}名減少）"
                    elif b is None and a is not None:
                        note = "（新規受付）"
                    elif b is not None and a is None:
                        note = "（受付停止）"
                    changes.append(f"{s}枠: {b_str} → {a_str}" + (f" {note}" if note else ""))
            return ", ".join(changes) if changes else "変更なし"

        items = []
        for slot_time, slot_val in val.items():
            if isinstance(slot_val, dict) and ("before" in slot_val or "after" in slot_val):
                b = slot_val.get("before")
                a = slot_val.get("after")
                b_str = f"{b}名" if b is not None else "受付枠なし"
                a_str = f"{a}名" if a is not None else "受付枠なし"
                note = ""
                if isinstance(b, (int, float)) and isinstance(a, (int, float)):
                    d = a - b
                    if d > 0:
                        note = f"（+{d}名増加）"
                    elif d < 0:
                        note = f"（{abs(d)}名減少）"
                elif b is None and a is not None:
                    note = "（新規受付）"
                elif b is not None and a is None:
                    note = "（受付停止）"
                items.append(f"{slot_time}枠: {b_str} → {a_str}" + (f" {note}" if note else ""))
            elif slot_val is not None:
                items.append(f"{slot_time}枠: {slot_val}名")
        return ", ".join(items) if items else "変更なし"

    return str(val)


def _format_revert_items(items: list) -> str:
    """BATCH_REVERT 의 items 목록을 사람이 읽기 쉬운 설명으로 변환한다."""
    out = []
    for it in items:
        if isinstance(it, dict):
            target = it.get("target_label") or it.get("target_type") or ""
            act = it.get("action_label") or action_label(it.get("action", ""))
            changes = it.get("changes") or []
            chg_parts = []
            for c in changes:
                if isinstance(c, dict):
                    f = FIELD_LABELS.get(c.get("field", ""), c.get("label") or c.get("field", ""))
                    f = FIELD_LABELS.get(f, f)
                    b_val = _format_value(c.get("field", ""), c.get("before", ""))
                    a_val = _format_value(c.get("field", ""), c.get("after", ""))
                    chg_parts.append(f"{f}: {b_val} → {a_val}")
            chg_str = f" [{', '.join(chg_parts)}]" if chg_parts else ""
            out.append(f"{target}【{act}】{chg_str}")
        else:
            out.append(str(it))
    return "; ".join(out)


def _clean_target_label(
    label: str | None,
    after: dict | None = None,
    action: str = "",
    target_type: str = "",
) -> str:
    """화면의 formatTargetLabel 및 cleanBulkLabelText 와 100% 동일하게 대상 상세를 정돈한다."""
    if not label or label == "—":
        return "—"
    import re

    # 1) 예약 관련: "aGCeHrgfuHsx 田中 太郎" -> "予約番号: aGCeHrgfuHsx, 受診者: 田中 太郎"
    if (target_type == "reservation" or action.startswith("RESERVATION_")) and action != "RESERVATION_PURGE":
        # 메일 재발송: "aGCeHrgfuHsx → user@email.com"
        if action == "MAIL_RESEND" and "→" in label:
            parts = label.split("→", 1)
            return f"予約番号: {parts[0].strip()} → {parts[1].strip()}"
        # 우편 일괄: "郵送一括入力表 15行 (CSV)"
        if "郵送一括" in label:
            return label
        # 일반 예약: "aGCeHrgfuHsx 田中 太郎"
        first_space = label.find(" ")
        if first_space != -1:
            res_no = label[:first_space].strip()
            name = label[first_space + 1:].strip()
            return f"予約番号: {res_no}, 受診者: {name}"

    # 2) 회장 관련: "V01 サンプル会館 A" -> "会場: サンプル会館 A (V01)"
    if target_type == "hospital" and not any(k in label for k in ("管理", "一括", "表", "（")):
        h_space = label.find(" ")
        if h_space != -1:
            code = label[:h_space].strip()
            name = label[h_space + 1:].strip()
            return f"会場: {name} ({code})"

    # 3) 옵션 관련: "OTP11 胃カメラ" -> "オプション: 胃カメラ (OTP11)"
    if target_type == "exam_option" and not any(k in label for k in ("管理", "一括", "表", "（")):
        o_space = label.find(" ")
        if o_space != -1:
            code = label[:o_space].strip()
            name = label[o_space + 1:].strip()
            return f"オプション: {name} ({code})"

    # 4) 관리자 계정: "admin" -> "管理者アカウント: admin"
    if target_type == "admin_user" or action in ("ADMIN_LOGIN", "ADMIN_LOGIN_FAILED", "ADMIN_LOGOUT"):
        if not label.startswith("管理者アカウント:"):
            return f"管理者アカウント: {label}"

    # 5) 일괄 저장 되돌리기: "一括保存を元に戻す [1243e1cdef32] — 元に戻す 1件・削除 0件・スキップ 0件" -> "対象: 会場名"
    if action == "BATCH_REVERT" or "一括保存を元に戻す" in label:
        after_obj = after or {}
        items = after_obj.get("items") or []
        valid_targets = []
        for i in items:
            if isinstance(i, dict) and i.get("plan") != "SKIP" and i.get("target_label"):
                valid_targets.append(i.get("target_label"))
        valid_targets = list(dict.fromkeys(valid_targets))
        if len(valid_targets) == 1:
            return f"対象: {valid_targets[0]}"
        elif len(valid_targets) > 1:
            return f"対象: {valid_targets[0]} 他 {len(valid_targets) - 1}件"

        clean = re.sub(r"\s*\[[0-9a-fA-F]+\]\s*", " ", label)
        clean = re.sub(r"—\s*.*$", "", clean).strip()
        return clean or "一括保存を元に戻す"

    # 6) 기간 경과 예약 자동 삭제:
    if action == "RESERVATION_PURGE":
        return "期間経過予約の自動整理"

    # 7) 일괄 저장: "(新規 0 ・ 修正 1 ・ 変更なし 19)" 형태 정돈
    m = re.search(
        r"^(.*?)\s*[\(（](?:新規\s*(\d+)\s*件?[・,\s]*)(?:(?:修正|更新)\s*(\d+)\s*件?[・,\s]*)(?:変更なし\s*(\d+)\s*件?)?[\)）]$",
        label.strip(),
    )
    if m:
        base = m.group(1).strip()
        c = int(m.group(2) or 0)
        u = int(m.group(3) or 0)
        parts = []
        if c > 0:
            parts.append(f"新規 {c}件")
        if u > 0:
            parts.append(f"修正 {u}件")
        joined = "・".join(parts)
        return f"{base}（変更なし）" if not parts else f"{base}（{joined}）"
    return label


_clean_bulk_label = _clean_target_label


def _format_plain_dict(val: dict, target_type: str = "", exclude: set[str] | None = None) -> str:
    """단순 딕셔너리를 사람이 읽기 좋은 일본어 key-value 텍스트로 변환한다."""
    if not val:
        return "なし"
    exclude_keys = exclude or set()
    items = []
    for k, v in val.items():
        if k in exclude_keys or k == "data":
            continue
        # 0건인 카운트 항목 생략
        if k in ("created", "updated", "unchanged", "deleted", "skipped", "reverted", "blocked") and v == 0:
            continue
        if target_type == "exam_option":
            if k == "code":
                k_label = "オプションコード"
            elif k == "name":
                k_label = "オプション名"
            else:
                k_label = FIELD_LABELS.get(k, k)
        elif target_type == "hospital":
            if k == "code":
                k_label = "会場コード"
            elif k == "name":
                k_label = "会場名"
            else:
                k_label = FIELD_LABELS.get(k, k)
        else:
            k_label = FIELD_LABELS.get(k, k)

        if k == "cells":
            items.append(f"{k_label}: {_format_cells(v)}")
        else:
            items.append(f"{k_label}: {_format_value(k, v)}")
    return " | ".join(items) if items else "なし"


def _format_diff_cols_for_csv(log: AuditLog) -> tuple[str, str]:
    """조작 로그의 변경 전(before)과 변경 후(after) 내용을
    화면의 미리보기 및 상세 비교 테이블과 100% 동일한 자연어로 생성한다.
    """
    action = log.action or ""
    after = log.after_json
    before = log.before_json
    target_type = log.target_type or ""

    # 1) 우편 접수 등록: RESERVATION_CREATE_POSTAL
    if action == "RESERVATION_CREATE_POSTAL" and isinstance(after, dict):
        parts = []
        if after.get("hospital"):
            parts.append(str(after["hospital"]))
        if after.get("time"):
            parts.append(str(after["time"]))
        if after.get("choice"):
            parts.append(f"第{after['choice']}希望割当")
        if after.get("status") == "PENDING_DEFECT" and after.get("defect"):
            parts.append(f"不備 ({after['defect']})")
        return "なし", " · ".join(parts) if parts else "郵送受付登録完了"

    # 2) Web 예약 접수: RESERVATION_CREATE_WEB
    if action == "RESERVATION_CREATE_WEB" and isinstance(after, dict):
        parts = []
        if after.get("hospital"):
            parts.append(f"会場: {after['hospital']}")
        if after.get("slot_date"):
            parts.append(f"受診日: {after['slot_date']}")
        if after.get("time"):
            parts.append(f"健診時間: {after['time']}")
        return "なし", " | ".join(parts) if parts else "Web予約受付完了"

    # 3) 예약 취소: RESERVATION_CANCEL
    if action == "RESERVATION_CANCEL" and isinstance(after, dict):
        b_stat = "確定"
        if isinstance(after.get("status"), dict) and "before" in after["status"]:
            b_stat = _format_value("status", after["status"]["before"])
        reason = ""
        if isinstance(after.get("cancel_reason"), dict):
            reason = str(after["cancel_reason"].get("after") or "")
        elif after.get("cancel_reason"):
            reason = str(after["cancel_reason"])
        after_text = "ステータス: キャンセル" + (f" (理由: {reason})" if reason else "")
        return f"ステータス: {b_stat}", after_text

    # 4) 연락 이력 추가: CONTACT_ADD
    if action == "CONTACT_ADD" and isinstance(after, dict):
        method = _format_value("method", after.get("method", ""))
        result = _format_value("result", after.get("result", ""))
        count = after.get("count")
        after_text = f"{method}連絡 → {result}" + (f" ({count}回目)" if count else "")
        return "なし", after_text

    # 5) 우편 일괄 가져오기/내보내기
    if action == "POSTAL_BULK_IMPORT" and isinstance(after, dict):
        kind = str(after.get("kind") or "CSV").upper()
        rows = after.get("rows", 0)
        return "なし", f"郵送受付ファイル取り込み ({kind}) · {rows}件"

    if action == "POSTAL_BULK_EXPORT" and isinstance(after, dict):
        fmt = str(after.get("format") or "CSV").upper()
        rows = after.get("rows", 0)
        return "なし", f"郵送受付ファイル書き出し ({fmt}) · {rows}件"

    # 6) 시트 일괄 가져오기/내보내기 (BULK_SHEET_*, HOSPITAL_BULK_*)
    if action in ("BULK_SHEET_IMPORT", "HOSPITAL_BULK_IMPORT") and isinstance(after, dict):
        sheet_key = after.get("sheet", "")
        sheet_name = VALUE_LABELS.get(sheet_key, sheet_key) or ("会場マスター" if action == "HOSPITAL_BULK_IMPORT" else "シート")
        kind = str(after.get("kind") or "CSV").upper()
        data = after.get("data")
        rows = after.get("rows", len(data) if isinstance(data, list) else 0)
        return "なし", f"{sheet_name} ファイル取り込み ({kind}) · {rows}件"

    if action in ("BULK_SHEET_EXPORT", "HOSPITAL_BULK_EXPORT") and isinstance(after, dict):
        sheet_key = after.get("sheet", "")
        sheet_name = VALUE_LABELS.get(sheet_key, sheet_key) or ("会場マスター" if action == "HOSPITAL_BULK_EXPORT" else "シート")
        fmt = str(after.get("format") or "CSV").upper()
        data = after.get("data")
        rows = after.get("rows", len(data) if isinstance(data, list) else 0)
        return "なし", f"{sheet_name} ファイル書き出し ({fmt}) · {rows}件"

    # 7) 메일 관련
    if action == "MAIL_TEMPLATE_UPDATE" and isinstance(after, dict):
        m_parts = []
        if after.get("subject"):
            m_parts.append("件名変更")
        if after.get("body_diff"):
            m_parts.append("本文変更")
        return "なし", " · ".join(m_parts) if m_parts else "変更なし"

    if action == "MAIL_RESEND" and isinstance(after, dict):
        template = _format_value("template", after.get("template", ""))
        status = _format_value("status", after.get("status", "SUCCESS"))
        return "なし", f"{template} 送信{status}"

    # 8) 일괄 저장 (会場/定員/オプション)
    if action in ("HOSPITAL_BULK_SAVE", "SLOT_BULK_UPDATE", "EXAM_OPTION_BULK_SAVE") and isinstance(after, dict):
        c = after.get("created", 0) or 0
        u = after.get("updated", 0) or 0
        parts = []
        if c > 0:
            parts.append(f"新規 {c}件")
        if u > 0:
            parts.append(f"更新 {u}件")
        return "なし", " ・ ".join(parts) if parts else "変更なし"

    # 9) 정원 변경 (SLOT_UPDATE)
    if action == "SLOT_UPDATE" and isinstance(after, dict):
        parts = []
        delta = after.get("delta")
        if delta is not None and delta != "":
            d = int(delta)
            parts.append(f"定員 +{d}名増加" if d > 0 else f"定員 {d}名減少")
        if after.get("closed") is True or after.get("set_closed") is True:
            parts.append("受付停止（締切）")
        elif after.get("closed") is False or after.get("set_closed") is False:
            parts.append("通常受付（再開）")
        if after.get("updated") is not None:
            slots = after.get("updated_slots") or []
            if len(slots) == 1:
                parts.append(f"1件変更 ({slots[0]})")
            elif len(slots) > 1:
                parts.append(f"{after['updated']}件変更 ({slots[0]} 他 {len(slots)-1}件)")
            else:
                parts.append(f"{after['updated']}件変更")
        return "なし", " · ".join(parts) if parts else "定員設定変更"

    # 10) 기간 경과 예약 자동 삭제 (RESERVATION_PURGE)
    if action == "RESERVATION_PURGE" and isinstance(after, dict):
        grace = after.get("grace_minutes", 60)
        deleted = after.get("deleted", 0)
        return "なし", f"受診時刻から {grace}分が経過した過去の予約 {deleted}件を自動整理（削除）"

    # 11) 관리자 로그인 / 실패 / 로그아웃
    if action == "ADMIN_LOGIN":
        return "なし", "ログイン成功"
    if action == "ADMIN_LOGIN_FAILED":
        return "なし", "ログイン失敗（パスワード相違など）"
    if action == "ADMIN_LOGOUT":
        return "なし", "ログアウト"
    if action == "ACCOUNT_PASSWORD_RESET":
        return "なし", "パスワード再設定完了"

    # 12) 일괄 저장 되돌리기 (BATCH_REVERT)
    if action == "BATCH_REVERT" and isinstance(after, dict):
        rev = after.get("reverted", 0) or 0
        dlt = after.get("deleted", 0) or 0
        skp = after.get("skipped", 0) or 0
        total = rev + dlt
        chg_fields = []
        for item in after.get("items") or []:
            if isinstance(item, dict) and item.get("plan") != "SKIP":
                for chg in item.get("changes") or []:
                    f = FIELD_LABELS.get(chg.get("field", ""), chg.get("label") or chg.get("field", ""))
                    if f and f not in chg_fields:
                        chg_fields.append(f)
        field_summary = f" ({', '.join(chg_fields[:2])}{' 他' if len(chg_fields) > 2 else ''})" if chg_fields else ""
        after_text = f"{total}件変更を元に戻す{field_summary}" if total > 0 else "変更なし"
        if skp > 0:
            after_text += f" · スキップ {skp}件"
        if after.get("items"):
            after_text += f" [{_format_revert_items(after['items'])}]"
        return "なし", after_text

    # 13) Diff 형식 판정: after_json 에 {before, after} 쌍이 포함되어 있는 경우
    # (RESERVATION_UPDATE, HOSPITAL_UPDATE, EXAM_OPTION_UPDATE, HOSPITAL_SCHEDULE_SAVE, ACCOUNT_UPDATE 등)
    if isinstance(after, dict):
        has_diff = any(
            isinstance(v, dict) and ("before" in v and "after" in v)
            for k, v in after.items()
        ) or (
            "cells" in after and isinstance(after["cells"], dict)
        )

        if has_diff:
            before_parts = []
            after_parts = []

            for k, v in after.items():
                if k == "slot_id" and "time_label" in after:
                    continue
                if target_type == "exam_option":
                    if k == "code":
                        k_label = "オプションコード"
                    elif k == "name":
                        k_label = "オプション名"
                    else:
                        k_label = FIELD_LABELS.get(k, k)
                elif target_type == "hospital":
                    if k == "code":
                        k_label = "会場コード"
                    elif k == "name":
                        k_label = "会場名"
                    else:
                        k_label = FIELD_LABELS.get(k, k)
                else:
                    k_label = FIELD_LABELS.get(k, k)

                if k == "cells":
                    c_before = {}
                    c_after = {}
                    if isinstance(v, dict) and "before" in v and "after" in v:
                        vb = v.get("before") or {}
                        va = v.get("after") or {}
                        c_before = vb if isinstance(vb, dict) else {}
                        c_after = va if isinstance(va, dict) else {}
                    elif isinstance(v, dict):
                        for sk, sv in v.items():
                            if isinstance(sv, dict) and ("before" in sv or "after" in sv):
                                c_before[sk] = sv.get("before")
                                c_after[sk] = sv.get("after")

                    all_slots = sorted(set(list(c_before.keys()) + list(c_after.keys())))
                    b_slot_changes = []
                    a_slot_changes = []
                    for s in all_slots:
                        sb = c_before.get(s)
                        sa = c_after.get(s)
                        if sb != sa:
                            b_str = f"{sb}名" if sb is not None else "受付枠なし"
                            a_str = f"{sa}名" if sa is not None else "受付枠なし"
                            note = ""
                            if isinstance(sb, (int, float)) and isinstance(sa, (int, float)):
                                d = sa - sb
                                if d > 0:
                                    note = f"（+{d}名増加）"
                                elif d < 0:
                                    note = f"（{abs(d)}名減少）"
                            elif sb is None and sa is not None:
                                note = "（新規受付）"
                            elif sb is not None and sa is None:
                                note = "（受付停止）"
                            b_slot_changes.append(f"{s}枠: {b_str}")
                            a_slot_changes.append(f"{s}枠: {a_str}" + (f" {note}" if note else ""))

                    if b_slot_changes:
                        before_parts.append(f"{k_label}: {', '.join(b_slot_changes)}")
                    if a_slot_changes:
                        after_parts.append(f"{k_label}: {', '.join(a_slot_changes)}")

                elif isinstance(v, dict) and "before" in v and "after" in v:
                    vb = v.get("before")
                    va = v.get("after")
                    vb_str = _format_value(k, vb)
                    va_str = _format_value(k, va)
                    if vb_str != va_str:
                        before_parts.append(f"{k_label}: {vb_str}")
                        after_parts.append(f"{k_label}: {va_str}")
                else:
                    after_parts.append(f"{k_label}: {_format_value(k, v)}")

            before_col = " | ".join(before_parts) if before_parts else "なし"
            after_col = " | ".join(after_parts) if after_parts else "変更なし"
            return before_col, after_col

    # 14) 단순 생성/등록 (HOSPITAL_CREATE, EXAM_OPTION_CREATE, ACCOUNT_CREATE 등)
    if isinstance(after, dict) and not before:
        after_text = _format_plain_dict(after, target_type=target_type, exclude={"id", "slot_id", "schedule_id", "sort_order", "created_at", "updated_at"})
        return "なし", after_text

    # 15) 삭제 (HOSPITAL_DELETE, EXAM_OPTION_DELETE 등)
    if isinstance(before, dict) and not after:
        before_text = _format_plain_dict(before, target_type=target_type, exclude={"id", "created_at", "updated_at"})
        return before_text, action_label(action)

    # 16) 기본 fallback
    return _format_json_field(before), _format_json_field(after)


def _format_json_field(val) -> str:
    """AuditLog 의 before_json / after_json 을 일반인이 바로 읽을 수 있는 일본어 텍스트로 변환한다."""
    if val is None or val == {} or val == []:
        return "なし"
    if isinstance(val, dict):
        # BATCH_REVERT 의 after_json 인 경우 간결하게 대상과 건수만 표시
        if "items" in val and ("reverted" in val or "deleted" in val):
            revert_parts = []
            rev = val.get("reverted", 0)
            dlt = val.get("deleted", 0)
            skp = val.get("skipped", 0)
            total = rev + dlt
            if total > 0:
                revert_parts.append(f"{total}件変更を元に戻す")
                if dlt > 0:
                    revert_parts.append(f"（うち削除 {dlt}件）")
            elif skp > 0:
                revert_parts.append("変更なし")
            if skp > 0:
                revert_parts.append(f"スキップ: {skp}件")
            if val.get("items"):
                revert_parts.append(f"対象詳細: {_format_revert_items(val['items'])}")
            return " | ".join(revert_parts)

        if "batch_id" in val and "reverted" in val and "items" not in val:
            rev = val.get("reverted", 0)
            return f"{rev}件変更を元に戻す" if rev > 0 else "変更なし"

        # 会場・定員・オプション等の各一括保存（created, updated, unchanged）の結果を簡潔に表現
        if (
            set(val.keys()).issubset({"created", "updated", "unchanged", "untouched"})
            and ("created" in val or "updated" in val or "unchanged" in val)
        ):
            c = val.get("created", 0) or 0
            u = val.get("updated", 0) or 0
            parts = []
            if c > 0:
                parts.append(f"新規 {c}件")
            if u > 0:
                parts.append(f"更新 {u}件")
            return " ・ ".join(parts) if parts else "変更なし"

        items = []
        for k, v in val.items():
            # 0건인 카운트 항목은 불필요한 노이즈이므로 생략
            if k in ("created", "updated", "unchanged", "deleted", "skipped", "reverted", "blocked") and v == 0:
                continue
            k_label = FIELD_LABELS.get(k, k)
            if k == "cells":
                items.append(f"{k_label}: {_format_cells(v)}")
            elif k == "items" and isinstance(v, list):
                items.append(f"{k_label}: {_format_revert_items(v)}")
            elif isinstance(v, dict):
                if "before" in v and "after" in v:
                    vb_str = _format_value(k, v.get("before"))
                    va_str = _format_value(k, v.get("after"))
                    if vb_str == va_str:
                        items.append(f"{k_label}: {va_str}")
                    else:
                        items.append(f"{k_label}: {vb_str} → {va_str}")
                else:
                    sub_parts = []
                    for sk, sv in v.items():
                        sk_label = FIELD_LABELS.get(sk, sk)
                        sub_parts.append(f"{sk_label}: {_format_value(sk, sv)}")
                    items.append(f"{k_label}: {{{', '.join(sub_parts)}}}")
            elif isinstance(v, list):
                if not v:
                    items.append(f"{k_label}: なし")
                elif all(isinstance(item, (str, int, float)) for item in v):
                    formatted_items = [_format_value(k, item) for item in v]
                    items.append(f"{k_label}: {', '.join(formatted_items)}")
                else:
                    import json
                    items.append(f"{k_label}: {json.dumps(v, ensure_ascii=False)}")
            else:
                items.append(f"{k_label}: {_format_value(k, v)}")
        return " | ".join(items) if items else "なし"

    if isinstance(val, list):
        if not val:
            return "なし"
        if all(isinstance(item, (str, int, float)) for item in val):
            return ", ".join(str(item) for item in val)
        import json
        return json.dumps(val, ensure_ascii=False)

    return str(val)


def export_file(
    db: Session,
    *,
    keyword: str = "",
    action: str = "",
    admin_user_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    log_id_from: int | None = None,
    log_id_to: int | None = None,
    fmt: str = "csv",
) -> tuple[str, bytes, str]:
    import csv
    import io

    stmt = select(AuditLog)

    if keyword:
        like = f"%{keyword.strip()}%"
        stmt = stmt.where(
            AuditLog.target_label.like(like)
            | AuditLog.admin_login_id.like(like)
            | AuditLog.admin_name.like(like)
        )
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if admin_user_id:
        stmt = stmt.where(AuditLog.admin_user_id == admin_user_id)
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        stmt = stmt.where(AuditLog.created_at <= datetime.combine(date_to, time.max))
    if log_id_from is not None:
        stmt = stmt.where(AuditLog.id >= log_id_from)
    if log_id_to is not None:
        stmt = stmt.where(AuditLog.id <= log_id_to)

    rows = db.execute(
        stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(10000)
    ).scalars().all()

    headers = [
        "ログID", "発生日時", "担当者アカウント", "担当者氏名",
        "操作種別", "対象区分", "対象ID", "対象詳細",
        "変更前内容", "変更後内容", "IPアドレス"
    ]
    data_rows = []
    for log in rows:
        admin_acc = log.admin_login_id or "システム（自動）"
        if admin_acc == "SYSTEM":
            admin_acc = "システム（自動）"
        target_detail = _clean_target_label(
            log.target_label or "",
            log.after_json,
            log.action,
            log.target_type or "",
        )
        before_str, after_str = _format_diff_cols_for_csv(log)
        data_rows.append([
            log.id,
            log.created_at.strftime("%Y-%m-%d %H:%M:%S") if log.created_at else "",
            admin_acc,
            log.admin_name or "システム",
            action_label(log.action),
            TARGET_TYPE_LABELS.get(log.target_type, log.target_type or ""),
            log.target_id or "",
            target_detail,
            before_str,
            after_str,
            log.ip_address or "",
        ])

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    if fmt == "xlsx":
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Alignment, Font, PatternFill
            from openpyxl.utils import get_column_letter

            wb = Workbook()
            ws = wb.active
            ws.title = "操作ログ"

            header_font = Font(bold=True, color="FF0F172A")
            header_fill = PatternFill("solid", fgColor="FFE2E8F0")
            header_align = Alignment(vertical="center", horizontal="left")

            ws.append(headers)
            for col_idx in range(1, len(headers) + 1):
                cell = ws.cell(row=1, column=col_idx)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = header_align

            for r_idx, row_data in enumerate(data_rows, start=2):
                for c_idx, val in enumerate(row_data, start=1):
                    cell = ws.cell(row=r_idx, column=c_idx)
                    cell.value = val

            ws.freeze_panes = "A2"
            max_col = get_column_letter(len(headers))
            max_row = max(1, len(data_rows) + 1)
            # 엑셀 헤더에 자동 필터 드롭다운 화살표(AutoFilter)를 활성화
            ws.auto_filter.ref = f"A1:{max_col}{max_row}"

            # 열 너비 자동 맞춤
            col_widths = [12, 20, 16, 16, 22, 14, 12, 30, 40, 40, 16]
            for col_idx, w in enumerate(col_widths, start=1):
                ws.column_dimensions[get_column_letter(col_idx)].width = w

            stream = io.BytesIO()
            wb.save(stream)
            filename = f"audit_logs_export_{ts}.xlsx"
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            return filename, stream.getvalue(), media_type
        except ImportError:
            pass

    output = io.StringIO()
    # BOM 은 여기서 붙이지 않는다 — 아래 encode("utf-8-sig") 가 이미 붙인다.
    # 두 번 붙이면 Excel 첫 칸 머리글에 보이지 않는 글자가 섞여
    # 그 파일을 다시 가져올 때 열 이름이 어긋난다.
    writer = csv.writer(output)
    # CSV 는 색·굵기가 없으므로 머리글을 【】로 감싸 데이터 줄과 구분한다.
    writer.writerow([f"【{h}】" for h in headers])
    for r in data_rows:
        writer.writerow(r)

    filename = f"audit_logs_export_{ts}.csv"
    media_type = "text/csv; charset=utf-8-sig"
    return filename, output.getvalue().encode("utf-8-sig"), media_type
