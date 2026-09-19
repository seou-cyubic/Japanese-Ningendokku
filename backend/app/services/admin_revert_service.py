"""일괄 저장 되돌리기.

표에서 「저장」을 한 번 누른 것을 통째로 되돌린다.

왜 필요한가
-----------
일괄 저장은 한 번에 수십 건을 바꾼다. 파일을 잘못 올렸거나 열이 하나 밀린
채로 저장했을 때, 지금까지는 **손으로 되돌리는 수밖에 없었다.** 조작 로그에
바뀐 값이 전부 남아 있는데도 화면에서 그것을 되짚을 길이 없었다.

무엇을 근거로 되돌리는가
------------------------
`audit_logs` 다. 일괄 저장은 로그마다 같은 `batch_id` 를 남기므로, 그 열쇠로
한 번의 저장에 딸린 로그를 전부 모을 수 있다.

수정 로그의 `after_json` 은 `audit_service.diff()` 가 만든 모양이다.

    {"address": {"before": "…", "after": "…"}, "tel": {…}}

되돌릴 값(`before`)과, **그 사이에 남이 고쳤는지 확인할 기준**(`after`)이
한 곳에 다 있다.

되돌리지 않는 경우 — 조용히 덮어쓰지 않는다
-------------------------------------------
되돌리기는 그 자체가 되돌릴 수 없는 조작이다. 그래서 조금이라도 어긋나면
**그 행을 건너뛰고 이유를 말한다.** 억지로 밀어붙이면 남의 수정이 흔적 없이
사라진다.

    · 그 뒤에 누군가 같은 칸을 고쳤다        → 건너뜀 (충돌)
    · 되돌리면 정원이 예약 수보다 낮아진다   → 건너뜀 (BR-09)
    · 새로 만든 것을 지우려는데 예약이 걸렸다 → 건너뜀
    · 대상이 이미 사라졌다                   → 건너뜀

기록을 지우지 않는다
--------------------
되돌리기는 **새 조작**으로 남는다(`BATCH_REVERT`). 원래 로그는 그대로 둔다.
「되돌렸다는 사실」도 나중에 설명해야 할 일이기 때문이다.
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import time_grid
from app.models.admin import AdminUser, AuditLog
from app.models.exam_option import ExamOption
from app.models.hospital import Hospital, HospitalSchedule
from app.models.reservation import Reservation, ReservationOption
from app.services import audit_service
from app.services import slot_grid_service as grid


class RevertError(Exception):
    """되돌릴 수 없는 이유. API 는 409 로 돌려준다."""


# 되돌릴 수 있는 조작. 여기 없는 것은 손대지 않는다 —
# 「무엇을 되돌리는지 아는 것만」 되돌린다.
REVERTABLE = {
    "HOSPITAL_CREATE": ("hospital", "CREATE"),
    "HOSPITAL_UPDATE": ("hospital", "UPDATE"),
    "HOSPITAL_SCHEDULE_SAVE": ("schedule", "UPSERT"),
    "EXAM_OPTION_CREATE": ("exam_option", "CREATE"),
    "EXAM_OPTION_UPDATE": ("exam_option", "UPDATE"),
}

# 일괄 저장 하나를 대표하는 요약 로그. 이것은 되돌릴 대상이 아니라
# 「무슨 저장이었나」를 사람에게 보여 주는 제목이다.
SUMMARY_ACTIONS = {"HOSPITAL_BULK_SAVE", "SLOT_BULK_UPDATE", "EXAM_OPTION_BULK_SAVE"}

_HOSPITAL_FIELDS = [
    "code", "name", "name_kana", "area", "city", "postal_code", "address",
    "tel", "transit_info", "access_minutes", "has_parking",
    "latitude", "longitude", "is_visible", "sort_order",
]
_SCHEDULE_FIELDS = [
    "event_date", "booking_close_date", "open_time",
    "reception_end_time", "note", "is_visible",
]
_OPTION_FIELDS = [
    "code", "name", "description", "note",
    "target_gender", "target_age_min", "target_age_max",
    "is_active", "sort_order",
]

FIELDS_OF = {
    "hospital": _HOSPITAL_FIELDS,
    "schedule": _SCHEDULE_FIELDS,
    "exam_option": _OPTION_FIELDS,
}

MODEL_OF = {
    "hospital": Hospital,
    "schedule": HospitalSchedule,
    "exam_option": ExamOption,
}

FIELD_LABELS: dict[str, str] = {
    # 会場
    "code": "会場コード",
    "name": "会場名",
    "name_kana": "フリガナ",
    "area": "地域",
    "city": "市区町村",
    "postal_code": "郵便番号",
    "address": "住所",
    "tel": "電話番号",
    "transit_info": "アクセス",
    "access_minutes": "所要時間（分）",
    "has_parking": "駐車場",
    "latitude": "緯度",
    "longitude": "経度",
    "is_visible": "予約画面表示",
    "sort_order": "並び順",

    # 日程
    "event_date": "開催日",
    "booking_close_date": "予約締切日",
    "open_time": "開始時刻",
    "reception_end_time": "受付終了時刻",
    "note": "注意事項",
    "schedules": "開催日程",

    # オプション
    "description": "説明",
    "target_gender": "対象性別",
    "target_age_min": "最小対象年齢",
    "target_age_max": "最大対象年齢",
    "is_active": "有効状態",
    "price": "料金",
    "option_type": "オプション種別",

    # 時間帯・定員
    "cells": "時間帯別定員",
    "closed": "休診状態",
    "is_closed": "休診の有無",
}


@dataclass
class RevertItem:
    """되돌리기 대상 한 건. 미리보기와 실행이 같은 구조를 쓴다."""

    log_id: int
    action: str
    target_type: str
    target_id: int | None
    target_label: str
    # RESTORE(값을 되돌린다) / DELETE(새로 만든 것을 지운다) / SKIP
    plan: str = "SKIP"
    reason: str = ""
    changes: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "log_id": self.log_id,
            "action": self.action,
            "action_label": audit_service.action_label(self.action),
            "target_type": self.target_type,
            "target_id": self.target_id,
            "target_label": self.target_label,
            "plan": self.plan,
            "reason": self.reason,
            "changes": self.changes,
        }


@dataclass
class RevertPlan:
    batch_id: str
    title: str = ""
    admin_name: str = ""
    created_at: str = ""
    items: list[RevertItem] = field(default_factory=list)

    @property
    def restorable(self) -> int:
        return len([i for i in self.items if i.plan in ("RESTORE", "DELETE")])

    @property
    def skipped(self) -> int:
        return len([i for i in self.items if i.plan == "SKIP"])

    def as_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "title": self.title,
            "admin_name": self.admin_name,
            "created_at": self.created_at,
            "restorable_count": self.restorable,
            "skipped_count": self.skipped,
            "items": [i.as_dict() for i in self.items],
        }


# --------------------------------------------------------------------------
# 계획 세우기
# --------------------------------------------------------------------------


def _same(left: Any, right: Any) -> bool:
    """조작 로그의 값(JSON)과 지금 DB 의 값을 견준다.

    로그는 JSON 이라 날짜·시각이 문자열(`"2026-09-15"`)로 들어 있고 DB 는
    `date` 객체다. 그대로 비교하면 **전부 다르다고 나와** 멀쩡한 되돌리기가
    모두 충돌로 막힌다.
    """
    if left is None and right is None:
        return True
    if isinstance(left, bool) or isinstance(right, bool):
        return bool(left) == bool(right)
    return audit_service._jsonable(left) == audit_service._jsonable(right)


def build_plan(db: Session, batch_id: str) -> RevertPlan:
    """이 일괄 저장을 되돌리면 무엇이 어떻게 되는지 미리 계산한다.

    아무것도 고치지 않는다. 화면이 이것을 그대로 보여 주고, 사람이
    확인한 뒤에 `revert` 를 부른다.
    """
    if not batch_id:
        raise RevertError("元に戻す保存が見つかりません。")

    logs = db.execute(
        select(AuditLog)
        .where(AuditLog.batch_id == batch_id)
        .order_by(AuditLog.id)
    ).scalars().all()

    if not logs:
        raise RevertError("元に戻す保存が見つかりません。すでに削除された記録の可能性があります。")

    plan = RevertPlan(batch_id=batch_id)
    plan.admin_name = logs[0].admin_name
    plan.created_at = logs[0].created_at.isoformat() if logs[0].created_at else ""

    # 이미 되돌린 저장인가. 되돌리기 로그가 그 batch 를 가리키고 있다.
    already = db.execute(
        select(AuditLog).where(
            AuditLog.action == "BATCH_REVERT",
            AuditLog.target_label.like(f"%{batch_id[:12]}%"),
        )
    ).scalars().first()
    if already is not None:
        raise RevertError(
            "すでに元に戻した保存です。"
            f"({already.created_at:%Y-%m-%d %H:%M} · {already.admin_name})"
        )

    for log in logs:
        if log.action in SUMMARY_ACTIONS:
            plan.title = log.target_label
            continue

        entry = REVERTABLE.get(log.action)
        if entry is None:
            continue

        target_type, mode = entry
        item = RevertItem(
            log_id=log.id,
            action=log.action,
            target_type=target_type,
            target_id=log.target_id,
            target_label=log.target_label,
        )
        plan.items.append(item)

        obj = db.get(MODEL_OF[target_type], log.target_id) if log.target_id else None
        if obj is None:
            item.reason = "対象がすでに削除されています。"
            continue

        # 새로 만든 것인가 (before 가 비어 있다) — 되돌리기는 「지우기」다.
        created = not log.before_json
        if mode == "CREATE" or (mode == "UPSERT" and created):
            _plan_delete(db, item, target_type, obj)
            continue

        _plan_restore(db, item, target_type, obj, log)

    return plan


def _plan_delete(db: Session, item: RevertItem, target_type: str, obj) -> None:
    """새로 만들어진 것을 지우는 계획. 걸린 것이 있으면 건너뛴다."""
    if target_type == "hospital":
        used = db.execute(
            select(Reservation).where(Reservation.hospital_id == obj.id).limit(1)
        ).scalars().first()
        if used is not None:
            item.reason = "この会場に予約が入っているため削除できません。"
            return
    elif target_type == "schedule":
        used = db.execute(
            select(Reservation).where(Reservation.schedule_id == obj.id).limit(1)
        ).scalars().first()
        if used is not None:
            item.reason = "この開催回に予約が入っているため削除できません。"
            return
    elif target_type == "exam_option":
        used = db.execute(
            select(ReservationOption)
            .where(ReservationOption.exam_option_id == obj.id).limit(1)
        ).scalars().first()
        if used is not None:
            item.reason = "この検査を申し込んだ予約があるため削除できません。"
            return

    item.plan = "DELETE"
    item.changes = [{"field": "", "label": "この保存で新しく作成されました",
                     "before": "", "after": "削除します"}]


def _plan_restore(
    db: Session, item: RevertItem, target_type: str, obj, log: AuditLog
) -> None:
    """값을 되돌리는 계획. 그 사이 남이 고친 칸이 있으면 건너뛴다."""
    diff = log.after_json or {}
    if not isinstance(diff, dict) or not diff:
        item.reason = "変更内容が記録されていません。"
        return

    fields = FIELDS_OF[target_type]
    changes: list[dict[str, Any]] = []
    conflicts: list[str] = []

    for key, value in diff.items():
        if not isinstance(value, dict) or "before" not in value:
            continue

        # 시간대 정원은 칸이 열여섯이라 따로 다룬다.
        if key == "cells":
            problem = _plan_cells(db, obj, value, changes)
            if problem:
                conflicts.append(problem)
            continue

        if key not in fields:
            continue

        current = getattr(obj, key, None)
        # 이 저장이 만든 값과 지금 값이 다르면, 그 사이에 누가 고친 것이다.
        if not _same(current, value.get("after")):
            conflicts.append(FIELD_LABELS.get(key, key))
            continue

        changes.append({
            "field": key,
            "label": FIELD_LABELS.get(key, key),
            "before": _text(value.get("after"), key=key),   # 지금 값
            "after": _text(value.get("before"), key=key),   # 되돌릴 값
        })

    if conflicts:
        item.reason = (
            "この保存の後に誰かが同じ項目を変更しました — "
            + ", ".join(conflicts[:4])
            + ("…" if len(conflicts) > 4 else "")
            + ". 上書きせずにスキップします。"
        )
        return

    if not changes:
        item.reason = "元に戻す対象がありません（すでに同じ値です）。"
        return

    item.plan = "RESTORE"
    item.changes = changes


def _plan_cells(db: Session, schedule, value: dict, changes: list) -> str:
    """시간대 정원 16칸의 되돌리기 계획. → 문제가 있으면 그 이유"""
    was = value.get("before") or {}
    now_logged = value.get("after") or {}
    counts = grid.counts_of(db, schedule)

    for index in time_grid.indexes():
        key = time_grid.sheet_key(index)
        if key not in was and key not in now_logged:
            continue

        current = schedule.capacity_at(index)
        # 이 저장이 만든 값과 지금이 다르면 그 사이에 누가 고친 것이다.
        if key in now_logged and not _same(current, now_logged.get(key)):
            return f"{key} 定員"

        target = was.get(key)
        if _same(current, target):
            continue

        # 되돌린 정원이 이미 들어온 예약보다 낮으면 좌석이 사라진다.
        taken = counts.reserved_at(index)
        if taken and (target is None or target < taken):
            return f"{key} (予約 {taken}件)"

        changes.append({
            "field": key,
            "label": f"{key}枠",
            "before": _text(current, key=key),
            "after": _text(target, key=key),
        })

    return ""


def _text(value: Any, key: str = "") -> str:
    if value is None or value == "":
        return "（なし）"
    if isinstance(value, bool):
        if key in ("is_closed", "closed"):
            return "休診（受付停止）" if value else "通常受付"
        if key == "has_parking":
            return "あり" if value else "なし"
        if key == "is_visible":
            return "表示" if value else "非表示"
        if key == "is_active":
            return "有効" if value else "無効"
        return "はい" if value else "いいえ"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if key == "price":
            return f"{int(value):,}円"
        if "～" in key:
            return f"{value}名"
    if str(value) == "M":
        return "男性"
    if str(value) == "F":
        return "女性"
    return str(value)


# --------------------------------------------------------------------------
# 실행
# --------------------------------------------------------------------------


def revert(
    db: Session, batch_id: str, *, admin: AdminUser, ip_address: str
) -> dict:
    """계획을 다시 세우고 그대로 실행한다.

    미리보기 때의 계획을 들고 있지 않고 **여기서 다시 계산한다.** 사람이
    확인창을 보고 있는 사이에 다른 스태프가 같은 값을 고쳤을 수 있고,
    그때는 되돌리지 않는 것이 맞다.
    """
    plan = build_plan(db, batch_id)

    if not plan.restorable:
        raise RevertError(
            "元に戻せる対象がありません。"
            + (plan.items[0].reason if plan.items else "")
        )

    reverted = deleted = 0
    revert_batch = audit_service.new_batch_id()

    for item in plan.items:
        if item.plan == "SKIP":
            continue

        model = MODEL_OF[item.target_type]
        obj = db.get(model, item.target_id)
        if obj is None:
            continue

        log = db.get(AuditLog, item.log_id)
        before_snapshot = audit_service.snapshot(obj, FIELDS_OF[item.target_type])

        if item.plan == "DELETE":
            db.delete(obj)
            deleted += 1
            audit_service.write_log(
                db,
                admin=admin,
                action=f"{item.target_type.upper()}_DELETE"
                if item.target_type != "schedule" else "HOSPITAL_SCHEDULE_SAVE",
                target_type=item.target_type,
                target_id=item.target_id,
                target_label=f"{item.target_label} （元に戻して削除）",
                before=before_snapshot,
                ip_address=ip_address,
                batch_id=revert_batch,
            )
            continue

        # RESTORE — 로그에 적힌 「이전 값」으로 되돌린다.
        diff = (log.after_json or {}) if log else {}
        fields = FIELDS_OF[item.target_type]

        for key, value in diff.items():
            if not isinstance(value, dict) or "before" not in value:
                continue
            if key == "cells":
                _restore_cells(obj, value.get("before") or {})
                continue
            if key not in fields:
                continue
            setattr(obj, key, _coerce(model, key, value.get("before")))

        db.flush()
        after_snapshot = audit_service.snapshot(obj, fields)
        reverted += 1

        audit_service.write_log(
            db,
            admin=admin,
            action="HOSPITAL_UPDATE" if item.target_type == "hospital"
            else ("EXAM_OPTION_UPDATE" if item.target_type == "exam_option"
                  else "HOSPITAL_SCHEDULE_SAVE"),
            target_type=item.target_type,
            target_id=obj.id,
            target_label=f"{item.target_label} （元に戻す）",
            before=before_snapshot,
            after=audit_service.diff(before_snapshot, after_snapshot),
            ip_address=ip_address,
            batch_id=revert_batch,
        )

    total_changed = reverted + deleted
    targets = [i.target_label for i in plan.items if i.plan in ("RESTORE", "DELETE")]
    target_summary = targets[0] if len(targets) == 1 else (f"{targets[0]} 他{len(targets)-1}件" if len(targets) > 1 else "")
    prefix = f"{target_summary} " if target_summary else ""
    target_label_text = f"{prefix}一括保存を元に戻す ({total_changed}件変更)"

    # 되돌렸다는 사실 자체를 남긴다. 원래 로그는 지우지 않는다.
    audit_service.write_log(
        db,
        admin=admin,
        action="BATCH_REVERT",
        target_type="batch",
        target_label=target_label_text,
        after={
            "batch_id": batch_id,
            "reverted": reverted,
            "deleted": deleted,
            "skipped": plan.skipped,
            "items": [i.as_dict() for i in plan.items],
        },
        ip_address=ip_address,
        batch_id=revert_batch,
    )
    db.commit()

    return {
        "batch_id": batch_id,
        "reverted_count": reverted,
        "deleted_count": deleted,
        "skipped_count": plan.skipped,
        "items": [i.as_dict() for i in plan.items],
    }


def _restore_cells(schedule, was: dict) -> None:
    for index in time_grid.indexes():
        key = time_grid.sheet_key(index)
        if key not in was:
            continue
        value = was[key]
        schedule.set_capacity_at(index, None if value is None else int(value))
        if value is None:
            schedule.set_closed_at(index, False)


def _coerce(model, key: str, value: Any) -> Any:
    """로그의 JSON 값을 모델이 받는 형으로 되돌린다.

    날짜·시각이 문자열로 남아 있다. 그대로 넣으면 저장할 때 터진다.
    """
    from datetime import date, time as time_cls

    if value is None:
        return None

    column = getattr(model, key, None)
    python_type = None
    try:
        python_type = column.type.python_type
    except Exception:  # noqa: BLE001 — 하이브리드 속성 등
        return value

    if python_type is date and isinstance(value, str):
        return date.fromisoformat(value[:10])
    if python_type is time_cls and isinstance(value, str):
        parts = value.split(":")
        return time_cls(int(parts[0]), int(parts[1]))
    return value
