"""회장 정보 · 정원 일괄 관리 (A-24 분리).

두 표가 하는 일
---------------
    회장 정보 일괄 관리   한 행 = 회장 하나.   장소 정보만.
    정원 일괄 관리        한 행 = 회차 하나.   날짜와 시간대 정원만.

나눈 이유는 `app/schemas/bulk.py` 의 도입부에 적어 두었다. 요지는
**정원을 고치러 온 사람에게 주소 칸을 보이지 않는 것**과,
**같은 회장의 주소가 한 번만 적히게 두는 것**이다.

두 표 모두 지키는 규칙
----------------------
    · 전 행을 먼저 검증하고, **한 셀이라도 틀리면 한 건도 저장하지 않는다.**
      절반만 반영된 마스터는 반영되지 않은 마스터보다 나쁘다 —
      무엇이 들어갔는지 아무도 모르는 상태가 된다.
    · **표에 없는 것은 지우지 않는다.** 표는 「이번에 손댄 것」이지
      「전체 목록」이 아니다. 지우는 것은 회장 관리 화면에서만 한다.
    · 오류와 경고를 나눈다. 「이상하지만 틀리지는 않은 값」을 오류로 막으면
      담당자는 표를 열어 그대로 저장하는 것조차 못 하게 된다.
"""

import re
import unicodedata
from datetime import date, time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import time_grid
from app.models.admin import AdminUser
from app.models.hospital import Hospital, HospitalSchedule
from app.models.reservation import Reservation
from app.schemas.bulk import (
    BulkFieldChange,
    BulkFieldError,
    CapacityBulkRequest,
    CapacityBulkResult,
    CapacityBulkRowResult,
    CapacityGridData,
    ExamOptionBulkRequest,
    ExamOptionBulkResult,
    ExamOptionBulkRowResult,
    ExamOptionGridData,
    GridChoice,
    GridColumn,
    VenueBulkRequest,
    VenueBulkResult,
    VenueBulkRowResult,
    VenueGridData,
)
from app.services import admin_master_service
from app.services import audit_service
from app.services import slot_grid_service as grid
from app.services.hospital_sheet_service import normalize_code


class BulkValidationError(Exception):
    """전 행을 검사한 뒤 돌려주는 셀 단위 오류."""

    def __init__(self, errors: list[BulkFieldError]) -> None:
        super().__init__("入力内容をご確認ください。")
        self.errors = errors


class BulkDataError(Exception):
    """행 단위가 아닌, 요청 전체를 받을 수 없는 이유."""


# --------------------------------------------------------------------------
# 셀 읽기
# --------------------------------------------------------------------------
# 표에서 참/거짓으로 읽는 값. 원본 마스터의 ○ × 를 그대로 받는다.

# 「예 / 아니오 / 표시 / 공개」 는 한국어 시절에 내보낸 표를 위해 남긴다.
# 담당자 손에 있는 파일은 화면 문구를 일본어로 바꾼다고 같이 바뀌지 않는다.
_TRUE_TEXTS = frozenset(
    {"はい", "y", "yes", "true", "1", "o", "○", "◯", "有", "あり", "表示", "公開",
     "예", "표시", "공개"}
)
_FALSE_TEXTS = frozenset(
    {"いいえ", "n", "no", "false", "0", "x", "×", "✕", "無", "なし", "非表示", "非公開",
     "아니오", "비표시", "비공개"}
)


def _cell(value: Any) -> str:
    if value is None or value is False:
        return ""
    if value is True:
        return "はい"
    return re.sub(r"[\s ]+", " ", str(value)).strip()


def _parse_date(text: str) -> date | None:
    normalized = unicodedata.normalize("NFKC", text).replace(".", "-").replace("/", "-")
    normalized = re.sub(r"\s+.*$", "", normalized)  # 「2026-07-17 00:00:00」의 뒤를 자른다
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None


def _parse_time(text: str) -> time | None:
    normalized = unicodedata.normalize("NFKC", text)
    matched = re.match(r"^(\d{1,2}):(\d{2})", normalized)
    if not matched:
        return None
    hour, minute = int(matched.group(1)), int(matched.group(2))
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def _parse_int(text: str) -> int | None:
    normalized = unicodedata.normalize("NFKC", text).strip()
    return int(normalized) if re.fullmatch(r"-?\d+", normalized) else None


def _bool_text(value: bool) -> str:
    return "はい" if value else "いいえ"


def _change_text(value: Any) -> str:
    """전/후 값을 사람이 읽을 한 줄로.

    비어 있는 것을 빈 문자열로 두면 「무엇에서 무엇으로」가 「 → 서울」처럼
    읽힌다. 값이 없었다는 사실이 보여야 한다.
    """
    if value is None or value == "":
        return "（なし）"
    if isinstance(value, bool):
        return _bool_text(value)
    return str(value)


def _changes_of(
    before: dict[str, Any],
    after: dict[str, Any],
    changed: list[str],
    columns: tuple[GridColumn, ...] | list[GridColumn],
) -> list[BulkFieldChange]:
    """바뀐 칸을 「무엇에서 무엇으로」 목록으로.

    저장 **전에** 보여 주기 위한 것이다. 필드 이름만 알려 주면
    「주소가 바뀝니다」까지는 알아도 무엇으로 바뀌는지는 모른다.

    새로 만드는 행(`before` 가 빈 경우)에는 목록을 만들지 않는다. 전부
    「(없음) → 값」이라 읽을 것이 없고, 화면도 「새로 등록됩니다」 한 줄로
    보여 준다. 200행을 넣을 때 이 목록이 응답의 대부분을 차지한다.
    """
    if not before:
        return []

    labels = {column.key: column.label for column in columns}
    result: list[BulkFieldChange] = []
    for field in changed:
        if field == "cells":
            # cells は dict(時間帯ラベル → 定員) なので、
            # 変更のあったスロットだけを個別の行として展開する。
            b_cells = before.get("cells") or {}
            a_cells = after.get("cells") or {}
            all_keys = sorted(set(b_cells) | set(a_cells))
            for slot_key in all_keys:
                bv = b_cells.get(slot_key)
                av = a_cells.get(slot_key)
                if bv == av:
                    continue
                b_str = f"{bv}名" if bv is not None else "受付枠なし"
                a_str = f"{av}名" if av is not None else "受付枠なし"
                if isinstance(bv, (int, float)) and isinstance(av, (int, float)):
                    d = av - bv
                    if d > 0:
                        a_str += f" (+{d}名増加)"
                    elif d < 0:
                        a_str += f" ({abs(d)}名減少)"
                elif bv is None and av is not None:
                    a_str += " (新規受付)"
                elif bv is not None and av is None:
                    a_str += " (受付停止)"

                result.append(BulkFieldChange(
                    field="cells",
                    label=f"{slot_key}枠",
                    before=b_str,
                    after=a_str,
                ))
            continue
        result.append(BulkFieldChange(
            field=field,
            label=labels.get(field, field),
            before=_change_text(before.get(field)),
            after=_change_text(after.get(field)),
        ))
    return result


def _format_bulk_label(title: str, count: int, unit: str, created: int, updated: int) -> str:
    """일괄 저장 요약 라벨에서 0건 항목을 배제하고 직관적으로 만든다."""
    if created == 0 and updated == 0:
        return f"{title} {count}{unit}（変更なし）"
    parts = []
    if created > 0:
        parts.append(f"新規 {created}件")
    if updated > 0:
        parts.append(f"修正 {updated}件")
    return f"{title} {count}{unit}（{'・'.join(parts)}）"


# ==========================================================================
# ① 회장 정보 일괄 관리
# ==========================================================================

# 열 순서 = 행을 알아보는 것 → 자주 손대는 것 → 거의 안 바뀌는 것
# --------------------------------------------------------------------------
# 맨 왼쪽은 **회장 코드와 회장명**이다. 자주 바뀌어서가 아니라 **행을 구별하기
# 위해서**다. 표를 가로로 밀어도 「지금 보고 있는 것이 어느 회장인가」를 잃지
# 않아야 한다.
#
# 코드가 회장명보다 앞이다. 정원 표(`capacity_columns()`)도 회장 코드로 시작하며,
# 담당자는 두 표를 나란히 놓고 같은 회장을 찾는다. 두 표의 첫 칸이 다르면
# 눈이 매번 다른 자리에서 시작한다. 예전에는 코드를 오른쪽 끝에 두었는데,
# 「이 회장의 코드가 뭐였지」를 볼 때마다 표를 끝까지 밀어야 했다.
#
# 그 다음이 실제로 손대는 칸들이다 — 예약 화면 표시, 순서. 담당자가 이 표에서
# 하는 일의 대부분이 그 둘이다.
#
# **후리가나는 오른쪽 끝에 남긴다.** 한 번 넣으면 바뀌지 않는 검색용 읽기이고,
# 사람이 매일 읽는 값이 아니다. 회장명 옆에 있으면 정작 읽어야 할 자리를 뺏는다.
#
# ※ 열 순서를 바꾸면 **Ctrl+V 붙여넣기의 칸 대응이 달라진다.**
#    파일 「가져오기」는 제목 줄을 보고 맞추므로 영향이 없다
#    (`venue_sheet_service`). 옛 순서로 만들어 둔 파일은 붙여넣지 말고
#    가져오기를 쓰도록 화면에서 안내한다.
VENUE_COLUMNS: tuple[GridColumn, ...] = (
    # 행을 알아보는 칸. 코드가 먼저다 — 회장을 특정하는 열쇠이고,
    # 정원 표(capacity_sheet_service)도 회장 코드가 첫 열이다. 두 표를
    # 나란히 놓고 보는 일이 잦으므로 같은 자리에서 시작하게 둔다.
    GridColumn(key="code", label="会場コード", width=96, group="会場"),
    GridColumn(key="name", label="会場名", width=230, group="会場"),
    GridColumn(key="is_visible", label="予約画面表示", width=112, kind="bool", group="表示"),
    GridColumn(key="sort_order", label="順序", width=72, kind="number", group="表示"),
    GridColumn(key="tel", label="電話（例外）", width=130, group="表示"),
    GridColumn(key="area", label="地域", width=110, group="所在地"),
    GridColumn(key="city", label="区・市町村", width=120, group="所在地"),
    GridColumn(key="postal_code", label="郵便番号", width=100, group="所在地"),
    GridColumn(key="address", label="住所", width=280, group="所在地"),
    GridColumn(key="transit_info", label="交通情報", width=260, group="所在地"),
    GridColumn(key="access_minutes", label="所要時間", width=96, group="所在地"),
    GridColumn(key="has_parking", label="駐車場", width=80, kind="bool", group="施設"),
    GridColumn(key="latitude", label="緯度", width=110, kind="number", group="施設"),
    GridColumn(key="longitude", label="経度", width=110, kind="number", group="施設"),
    # 한자·가타카나 회장명을 히라가나로 찾기 위한 읽기.
    # 예전에는 화면 파일에 20곳을 박아 두었다 (hospitals.js 의 READINGS).
    #
    # 그룹은 **연속한 열끼리** 묶인다 (frontend grid.js). 코드를 맨 앞으로
    # 옮기면서 「코드 · 읽기」를 그대로 두면 머리글이 두 조각으로 갈라지므로
    # 남은 쪽의 이름을 바꾼다.
    GridColumn(key="name_kana", label="フリガナ", width=200, group="読み"),
)

# 길이 제한만 보는 칸. (필드, 최대 길이, 사람이 읽는 이름)
_VENUE_TEXT_LIMITS = (
    ("name_kana", 200, "フリガナ"),
    ("area", 40, "地域"),
    ("city", 60, "区・市町村"),
    ("postal_code", 10, "郵便番号"),
    ("address", 255, "住所"),
    ("transit_info", 200, "交通情報"),
    ("access_minutes", 40, "所要時間"),
    ("tel", 30, "電話"),
)

_VENUE_FIELDS = [
    "code", "name", "name_kana", "area", "city", "postal_code", "address",
    "tel", "transit_info", "access_minutes", "has_parking",
    "latitude", "longitude", "is_visible", "sort_order",
]


def venue_grid(db: Session) -> VenueGridData:
    """지금 등록된 회장을 표의 행으로. **한 회장에 한 행.**"""
    rows: list[dict[str, Any]] = []

    hospitals = db.execute(
        select(Hospital).order_by(Hospital.sort_order, Hospital.id)
    ).scalars().all()

    # 앞으로의 예약 건수를 회장별로 한 번에 센다. 행마다 세면 회장 수만큼
    # 질의가 나간다(N+1). 이 값은 「이 회장을 지울 수 있는가」의 근거다.
    today = date.today()
    reserved_counts = dict(
        db.execute(
            select(Reservation.hospital_id, func.count())
            .where(
                Reservation.slot_date >= today,
                Reservation.status != "CANCELLED",
            )
            .group_by(Reservation.hospital_id)
        ).all()
    )

    for h in hospitals:
        upcoming = [s for s in h.schedules if not s.is_past]
        # 「접수 중」인 회차가 하나라도 있는가. 화면의 접수 상태 필터가 이 값으로
        # 거른다. 회차를 화면에서 다시 훑게 하면 같은 판정이 두 곳에 생긴다.
        #
        # 판정은 모델이 한다 (`is_open_for_booking`) — 접수 마감일을 어떻게
        # 보는지는 이용자 화면도 같은 함수를 쓴다.
        booking_open = any(s.is_open_for_booking(today) for s in upcoming)
        rows.append({
            "id": str(h.id),
            "code": h.code,
            "name": h.name,
            "name_kana": h.name_kana or "",
            "area": h.area,
            "city": h.city,
            "postal_code": h.postal_code,
            "address": h.address,
            "transit_info": h.transit_info,
            "access_minutes": h.access_minutes,
            "has_parking": _bool_text(h.has_parking),
            # `:g` 를 쓰면 유효숫자 6자리로 잘려 35.6584491 이 35.6584 가 된다.
            # 표를 열었다 그대로 저장하는 것만으로 좌표가 200m 옮겨간다.
            # repr 은 다시 읽으면 같은 값이 되는 가장 짧은 표기를 준다.
            "latitude": "" if h.latitude is None else repr(h.latitude),
            "longitude": "" if h.longitude is None else repr(h.longitude),
            "tel": h.tel,
            "is_visible": _bool_text(h.is_visible),
            "sort_order": str(h.sort_order),
            # 읽기 전용 참고 값. 이 표에서 고칠 수는 없지만, **일정이 있는지
            # 없는지는 알아야** 한다 — 회차가 0인 회장은 이용자 화면에 없다.
            "_schedule_count": len(h.schedules),
            "_upcoming_count": len(upcoming),
            # 접수 상태 필터와 「접수 마감」 표시가 쓴다.
            "_is_booking_open": booking_open,
            # 앞으로의 예약 건수. 회장을 지울 수 있는지가 여기서 갈린다.
            "_upcoming_reserved": int(reserved_counts.get(h.id, 0)),
        })

    return VenueGridData(columns=list(VENUE_COLUMNS), rows=rows)


def _validate_venue_row(
    row,
    row_no: int,
    *,
    by_id: dict[int, Hospital],
    by_code: dict[str, Hospital],
    seen_codes: dict[str, int],
    errors: list[BulkFieldError],
) -> tuple[Hospital | None, dict[str, Any]] | None:
    def add(field: str, message: str) -> None:
        errors.append(BulkFieldError(row_no=row_no, field=field, message=message))

    before = len(errors)
    values: dict[str, Any] = {}

    # --- 코드 : 회장을 특정하는 열쇠 --------------------------------------
    # 이 표에서는 **코드가 겹칠 수 없다.** 한 회장에 한 행이기 때문이다.
    # (정원 표에서는 같은 코드가 여러 번 나오는 것이 정상이다.)
    code = normalize_code(_cell(row.code))
    if not code:
        add("code", "会場コードは必須です。")
    elif len(code) > 20:
        add("code", "会場コードは20文字以内で入力してください。")
    else:
        duplicate_at = seen_codes.get(code.casefold())
        if duplicate_at is not None:
            add("code", f"{duplicate_at}行目と会場コードが同じです。"
                        "この表では1会場につき1行です。")
        else:
            seen_codes[code.casefold()] = row_no
    values["code"] = code

    name = _cell(row.name)
    if not name:
        add("name", "会場名は必須です。")
    elif len(name) > 120:
        add("name", "会場名は120文字以内で入力してください。")
    values["name"] = name

    # --- 어느 회장을 고치는가 ---------------------------------------------
    # id 가 오면 그것이 우선이다. 코드를 고치는 수정(오타 정정)이 코드로만
    # 찾으면 「새 회장 등록」이 되어 버린다.
    hospital: Hospital | None = None
    raw_id = _cell(row.id)
    if raw_id:
        if not raw_id.isdigit() or int(raw_id) not in by_id:
            add("code", "この行が示す会場が見つかりません。画面を更新してください。")
        else:
            hospital = by_id[int(raw_id)]
    elif code:
        hospital = by_code.get(code.casefold())

    if code:
        owner = by_code.get(code.casefold())
        if owner is not None and hospital is not None and owner.id != hospital.id:
            add("code", f"会場コード「{code}」は {owner.name} が使用しています。")

    for field, limit, label in _VENUE_TEXT_LIMITS:
        text = _cell(getattr(row, field))
        if len(text) > limit:
            add(field, f"{label} は {limit}文字以内で入力してください。")
        values[field] = text

    # 표시용 지역 한 줄은 두 칸에서 만든다. 사람이 따로 적지 않는다.
    values["region"] = f"{values['area']}{values['city']}"

    for field, label, default in (
        ("has_parking", "駐車場", False),
        ("is_visible", "予約画面表示", True),
    ):
        text = _cell(getattr(row, field)).casefold()
        if not text:
            values[field] = default
        elif text in _TRUE_TEXTS:
            values[field] = True
        elif text in _FALSE_TEXTS:
            values[field] = False
        else:
            add(field, f"{label} は「はい」または「いいえ」で入力してください。")
            values[field] = default

    for field, label, low, high in (
        ("latitude", "緯度", -90.0, 90.0),
        ("longitude", "経度", -180.0, 180.0),
    ):
        text = _cell(getattr(row, field))
        if not text:
            values[field] = None
            continue
        try:
            number = float(unicodedata.normalize("NFKC", text))
        except ValueError:
            add(field, f"{label} は数値で入力してください。(例: 35.6584491)")
            values[field] = None
            continue
        if not low <= number <= high:
            add(field, f"{label} は {low} ~ {high} の間である必要があります。")
        values[field] = number

    order_text = _cell(row.sort_order)
    if not order_text:
        values["sort_order"] = row_no
    else:
        parsed = _parse_int(order_text)
        if parsed is None:
            add("sort_order", "並び順は整数で入力してください。")
            values["sort_order"] = row_no
        else:
            values["sort_order"] = parsed

    if len(errors) > before:
        return None
    return hospital, values


def save_venues(
    db: Session,
    payload: VenueBulkRequest,
    *,
    admin: AdminUser,
    ip_address: str,
    dry_run: bool = False,
) -> VenueBulkResult:
    """회장 정보 표를 마스터에 반영한다. **개최 회차는 손대지 않는다.**

    `dry_run=True` 면 **아무것도 저장하지 않고** 무엇이 바뀔지만 세어
    돌려준다. 저장 전에 「신규 몇 곳 · 덮어쓰기 몇 곳 · 손대지 않는 몇 곳」과
    칸별 전/후를 보여 주기 위한 경로다.
    """
    hospitals = db.execute(select(Hospital)).scalars().all()
    by_id = {h.id: h for h in hospitals}
    by_code = {h.code.casefold(): h for h in hospitals}

    # 이 저장에서 나오는 모든 로그를 하나로 묶는 열쇠. 「아까 그 저장」을
    # 나중에 통째로 가리킬 수 있어야 되돌릴 수 있다.
    batch_id = audit_service.new_batch_id()

    errors: list[BulkFieldError] = []
    warnings: list[BulkFieldError] = []
    seen_codes: dict[str, int] = {}
    drafts: list[tuple[int, Hospital | None, dict[str, Any]]] = []

    for index, row in enumerate(payload.rows, start=1):
        row_no = int(row.row_no) if str(row.row_no or "").isdigit() else index
        parsed = _validate_venue_row(
            row, row_no,
            by_id=by_id, by_code=by_code, seen_codes=seen_codes, errors=errors,
        )
        if parsed is not None:
            drafts.append((row_no, parsed[0], parsed[1]))

    if errors:
        raise BulkValidationError(errors)

    results: list[VenueBulkRowResult] = []
    created = updated = unchanged = 0

    for row_no, hospital, values in drafts:
        is_new = hospital is None
        if is_new:
            hospital = Hospital()
            db.add(hospital)
            before: dict[str, Any] = {}
        else:
            before = audit_service.snapshot(hospital, _VENUE_FIELDS)

        for field in _VENUE_FIELDS:
            setattr(hospital, field, values[field])
        hospital.region = values["region"]

        db.flush()
        after = audit_service.snapshot(hospital, _VENUE_FIELDS)
        changed = [f for f in _VENUE_FIELDS if before.get(f) != after.get(f)]

        if is_new:
            created += 1
            action = "CREATED"
        elif changed:
            updated += 1
            action = "UPDATED"
        else:
            unchanged += 1
            action = "UNCHANGED"

        # 좌표가 비면 이용자 화면의 지도가 주소 검색으로 떨어진다. 막지는
        # 않는다 — 새로 등록하는 중에는 아직 모를 수 있다.
        if values["latitude"] is None or values["longitude"] is None:
            warnings.append(BulkFieldError(
                row_no=row_no, field="latitude",
                message="座標が空のため、地図は住所検索で表示されます。",
            ))

        if action != "UNCHANGED" and not dry_run:
            audit_service.write_log(
                db,
                admin=admin,
                action="HOSPITAL_CREATE" if is_new else "HOSPITAL_UPDATE",
                target_type="hospital",
                target_id=hospital.id,
                target_label=f"{hospital.code} {hospital.name}",
                before=before or None,
                after=audit_service.diff(before, after) if before else after,
                ip_address=ip_address,
                batch_id=batch_id,
            )

        results.append(VenueBulkRowResult(
            row_no=row_no, id=hospital.id, code=hospital.code,
            name=hospital.name, action=action, changed_fields=changed,
            changes=_changes_of(before, after, changed, VENUE_COLUMNS),
        ))

    # 이 표에 아예 없는 회장은 몇 곳인가. 「표에 없는 것은 지우지 않는다」는
    # 규약을 **숫자로** 보여 주기 위한 값이다. 말로만 적어 두면, 덮어쓰기가
    # 걱정되어 파일을 올리는 사람에게는 근거가 없다.
    touched_ids = {h.id for _, h, _ in drafts if h is not None}
    untouched = len([h for h in hospitals if h.id not in touched_ids])

    if dry_run:
        # 무엇이 바뀔지만 세고 되돌린다. flush 로 만들어진 신규 행도 함께 사라진다.
        db.rollback()
    else:
        audit_service.write_log(
            db,
            admin=admin,
            action="HOSPITAL_BULK_SAVE",
            target_type="hospital",
            target_label=_format_bulk_label("会場管理", len(drafts), "件", created, updated),
            after={"created": created, "updated": updated, "unchanged": unchanged},
            ip_address=ip_address,
            batch_id=batch_id,
        )
        db.commit()

    return VenueBulkResult(
        created_count=created, updated_count=updated, unchanged_count=unchanged,
        untouched_count=untouched, rows=results, warnings=warnings,
    )


# ==========================================================================
# ② 정원 일괄 관리
# ==========================================================================


def capacity_snapshot(schedule: HospitalSchedule) -> dict[str, int | None]:
    """회차의 시간대 정원 16칸을 조작 로그에 남길 모양으로.

    `{"09:00~09:30": 22, "09:30~10:00": None, …}`
    `None` 은 「그 시간대를 열지 않음」이며 0 과 다르다 — 되돌릴 때 이 둘을
    구별하지 못하면 닫혀 있던 칸이 만석으로 되살아난다.
    """
    return {
        time_grid.sheet_key(index): schedule.capacity_at(index)
        for index in time_grid.indexes()
    }


def capacity_columns() -> list[GridColumn]:
    """열 정의를 서버가 만든다.

    시간대 열이 **격자에서 나오기** 때문이다. 화면에 16칸을 적어 두면
    격자를 넓힐 때 두 곳을 고쳐야 하고, 반드시 한 곳을 잊는다.
    """
    columns = [
        GridColumn(key="hospital_code", label="会場コード", width=96,
                   readonly=True, group="会場"),
        GridColumn(key="hospital_name", label="会場名", width=200,
                   readonly=True, group="会場"),
        GridColumn(key="event_date", label="開催日", width=118, kind="date",
                   group="開催回"),
        GridColumn(key="booking_close_date", label="受付締切日", width=118,
                   kind="date", group="開催回"),
        GridColumn(key="open_time", label="開始", width=84, kind="time",
                   group="開催回"),
        GridColumn(key="reception_end_time", label="受付終了", width=96,
                   kind="time", group="開催回"),
        GridColumn(key="note", label="開催回メモ", width=160, group="開催回"),
        GridColumn(key="is_visible", label="表示", width=76, kind="bool",
                   group="開催回"),
    ]
    columns.extend(
        GridColumn(
            key=time_grid.sheet_key(index),
            label=time_grid.label(index),
            width=96,
            kind="capacity",
            group="時間帯別定員",
        )
        for index in time_grid.indexes()
    )
    return columns


def capacity_grid(db: Session, hospital_id: int | None = None) -> CapacityGridData:
    """개최 회차를 표의 행으로. **한 회차에 한 행.**

    `hospital_id` 를 주면 그 회장의 회차만. 「회장 A 의 8/28·8/29·8/30
    정원을 본다」가 이 화면이 답해야 하는 첫 질문이다.
    """
    stmt = (
        select(HospitalSchedule, Hospital)
        .join(Hospital, Hospital.id == HospitalSchedule.hospital_id)
        .order_by(Hospital.sort_order, Hospital.id, HospitalSchedule.event_date)
    )
    if hospital_id is not None:
        stmt = stmt.where(HospitalSchedule.hospital_id == hospital_id)

    rows: list[dict[str, Any]] = []
    reserved: dict[str, dict[str, int]] = {}
    closed: dict[str, list[str]] = {}

    for schedule, hospital in db.execute(stmt).all():
        key = str(schedule.id)
        row: dict[str, Any] = {
            "schedule_id": key,
            "hospital_id": str(hospital.id),
            "hospital_code": hospital.code,
            "hospital_name": hospital.name,
            "event_date": schedule.event_date.isoformat(),
            "booking_close_date": (
                schedule.booking_close_date.isoformat()
                if schedule.booking_close_date else ""
            ),
            "open_time": (
                schedule.open_time.strftime("%H:%M") if schedule.open_time else ""
            ),
            "reception_end_time": (
                schedule.reception_end_time.strftime("%H:%M")
                if schedule.reception_end_time else ""
            ),
            "note": schedule.note,
            "is_visible": _bool_text(schedule.is_visible),
        }

        counts = schedule.counts
        cell_reserved: dict[str, int] = {}
        cell_closed: list[str] = []

        for index in time_grid.indexes():
            cell = time_grid.sheet_key(index)
            capacity = schedule.capacity_at(index)
            row[cell] = "" if capacity is None else str(capacity)

            taken = counts.reserved_at(index) if counts else 0
            if taken:
                cell_reserved[cell] = taken
            if schedule.is_closed_at(index):
                cell_closed.append(cell)

        rows.append(row)
        if cell_reserved:
            reserved[key] = cell_reserved
        if cell_closed:
            closed[key] = cell_closed

    hospitals = [
        {
            "id": h.id,
            "code": h.code,
            "name": h.name,
            "region": h.region,
            "schedule_count": len(h.schedules),
        }
        for h in db.execute(
            select(Hospital).order_by(Hospital.sort_order, Hospital.id)
        ).scalars()
    ]

    return CapacityGridData(
        columns=capacity_columns(),
        rows=rows,
        reserved=reserved,
        closed=closed,
        hospitals=hospitals,
    )


def _validate_capacity_row(
    row,
    row_no: int,
    *,
    hospitals_by_code: dict[str, Hospital],
    schedules_by_id: dict[int, HospitalSchedule],
    seen: dict[tuple[str, date], int],
    errors: list[BulkFieldError],
    warnings: list[BulkFieldError],
) -> dict[str, Any] | None:
    def add(field: str, message: str) -> None:
        errors.append(BulkFieldError(row_no=row_no, field=field, message=message))

    def warn(field: str, message: str) -> None:
        warnings.append(BulkFieldError(row_no=row_no, field=field, message=message))

    before = len(errors)
    values: dict[str, Any] = {}

    # --- 어느 회장의 회차인가 ---------------------------------------------
    code = normalize_code(_cell(row.hospital_code))
    hospital = hospitals_by_code.get(code.casefold()) if code else None
    if not code:
        add("hospital_code", "会場コードは必須です。")
    elif hospital is None:
        add("hospital_code",
            f"「{code}」の会場が存在しません。先に「会場情報管理」から登録してください。")
    values["hospital"] = hospital

    # --- 개최일 : 회차를 특정하는 칸 --------------------------------------
    event_text = _cell(row.event_date)
    event_date = _parse_date(event_text) if event_text else None
    if not event_text:
        add("event_date", "開催日は必須です。")
    elif event_date is None:
        add("event_date", "開催日はYYYY-MM-DD形式で入力してください。(例: 2026-07-17)")
    values["event_date"] = event_date

    if code and event_date is not None:
        key = (code.casefold(), event_date)
        duplicate_at = seen.get(key)
        if duplicate_at is not None:
            add("event_date",
                f"{duplicate_at}行目と会場・開催日が同じです。"
                "同一会場で同日に複数回開催することはできません。")
        else:
            seen[key] = row_no

    close_text = _cell(row.booking_close_date)
    close_date = _parse_date(close_text) if close_text else None
    if close_text and close_date is None:
        add("booking_close_date", "受付締切日はYYYY-MM-DD形式で入力してください。")
    if event_date and close_date and close_date > event_date:
        # 막지 않는다. 개최일이 지나면 어차피 접수가 닫히므로 효력이 없을
        # 뿐 데이터를 망가뜨리지 않는다. 임포터도 경고만 하고 저장한다.
        warn("booking_close_date",
             "受付締切日が開催日より後になっています。開催日を過ぎれば受付は"
             "どのみち閉じるため、この値は効きません。")
    values["booking_close_date"] = close_date

    for field, label in (("open_time", "開始時刻"),
                         ("reception_end_time", "受付終了時刻")):
        text = _cell(getattr(row, field))
        if not text:
            values[field] = None
            continue
        parsed = _parse_time(text)
        if parsed is None:
            add(field, f"{label} はHH:MM形式で入力してください。(例: 09:30)")
        values[field] = parsed

    start, end = values.get("open_time"), values.get("reception_end_time")
    if start and end and end <= start:
        add("reception_end_time", "受付終了時刻が開始時刻以前になっています。")

    values["note"] = _cell(row.note)[:200]

    visible_text = _cell(row.is_visible).casefold()
    if not visible_text:
        values["is_visible"] = True
    elif visible_text in _TRUE_TEXTS:
        values["is_visible"] = True
    elif visible_text in _FALSE_TEXTS:
        values["is_visible"] = False
    else:
        add("is_visible", "表示は「はい」または「いいえ」で入力してください。")
        values["is_visible"] = True

    # --- 어느 회차를 고치는가 ---------------------------------------------
    schedule: HospitalSchedule | None = None
    raw_id = _cell(row.schedule_id)
    if raw_id:
        if not raw_id.isdigit() or int(raw_id) not in schedules_by_id:
            add("event_date", "この行が示す開催回が見つかりません。画面を更新してください。")
        else:
            schedule = schedules_by_id[int(raw_id)]
    elif hospital is not None and event_date is not None:
        schedule = next(
            (s for s in hospital.schedules if s.event_date == event_date), None
        )
    values["schedule"] = schedule

    # --- 시간대 정원 ------------------------------------------------------
    # 빈 칸은 「그 시간대를 열지 않음」이다. 0 과 다르다 — 0 은 자리는
    # 있으나 정원이 없다는 뜻이고, 그렇게 적으면 화면에 만석으로 뜬다.
    cells: dict[int, int | None] = {}
    extra = row.model_dump(exclude_unset=True)
    for key, raw in extra.items():
        index = time_grid.index_of_sheet_key(key)
        if index is None:
            continue
        text = _cell(raw)
        if not text:
            cells[index] = None
            continue
        parsed = _parse_int(text)
        if parsed is None:
            add(key, "定員は整数で入力してください。(例: 15)")
            continue
        if parsed < 0:
            add(key, "定員は0以上でなければなりません。空欄は「この時間帯を開設しない」です。")
            continue

        # 이 화면은 정원을 다루는 전용 화면이다. 예약 수 아래로 내리려는
        # 시도를 조용히 올려 붙이지 않고 **그 셀에 이유를 적어 돌려준다.**
        if schedule is not None:
            taken = schedule.counts.reserved_at(index) if schedule.counts else 0
            if parsed < taken:
                add(key, f"既に {taken}名の予約があるため、{parsed}名に減らすことはできません。")
                continue
        cells[index] = parsed

    if schedule is None and not any(v for v in cells.values()):
        warn("event_date", "時間帯の定員が空のため、利用者画面にこの日付は表示されません。")

    values["cells"] = cells

    if len(errors) > before:
        return None
    values["row_no"] = row_no
    return values


def save_capacity(
    db: Session,
    payload: CapacityBulkRequest,
    *,
    admin: AdminUser,
    ip_address: str,
    dry_run: bool = False,
) -> CapacityBulkResult:
    """정원 표를 마스터에 반영한다. **회장 정보는 손대지 않는다.**

    `dry_run=True` 면 **아무것도 저장하지 않고** 무엇이 바뀔지만 세어
    돌려준다. 특히 **정원이 사라지는 칸**을 저장 전에 알리기 위한 경로다 —
    시간대 열이 빠진 파일을 올리면 그 칸이 「열지 않음」이 되는데, 예전에는
    그 사실이 저장한 뒤에야 드러났다.
    """
    hospitals = db.execute(select(Hospital)).scalars().all()
    hospitals_by_code = {h.code.casefold(): h for h in hospitals}
    schedules_by_id = {
        s.id: s for s in db.execute(select(HospitalSchedule)).scalars()
    }

    batch_id = audit_service.new_batch_id()

    errors: list[BulkFieldError] = []
    warnings: list[BulkFieldError] = []
    seen: dict[tuple[str, date], int] = {}
    drafts: list[dict[str, Any]] = []

    for index, row in enumerate(payload.rows, start=1):
        row_no = int(row.row_no) if str(row.row_no or "").isdigit() else index
        parsed = _validate_capacity_row(
            row, row_no,
            hospitals_by_code=hospitals_by_code,
            schedules_by_id=schedules_by_id,
            seen=seen, errors=errors, warnings=warnings,
        )
        if parsed is not None:
            drafts.append(parsed)

    if errors:
        raise BulkValidationError(errors)

    _SCHEDULE_FIELDS = [
        "event_date", "booking_close_date", "open_time",
        "reception_end_time", "note", "is_visible",
    ]

    results: list[CapacityBulkRowResult] = []
    created = updated = unchanged = 0

    for draft in drafts:
        hospital: Hospital = draft["hospital"]
        schedule: HospitalSchedule | None = draft["schedule"]
        is_new = schedule is None

        if is_new:
            schedule = HospitalSchedule(
                hospital_id=hospital.id, event_date=draft["event_date"]
            )
            db.add(schedule)
            db.flush()
            before: dict[str, Any] = {}
        else:
            before = audit_service.snapshot(schedule, _SCHEDULE_FIELDS)
            # 시간대 정원도 함께 남긴다. 회차의 날짜·메모만 남기면
            # 되돌리기가 **정원 숫자를 그대로 두는** 반쪽짜리가 된다.
            before["cells"] = capacity_snapshot(schedule)

        # 예약이 걸린 회차의 개최일이 바뀌면 옮기지 않고 **둘로 나눈다.**
        # 옛 날짜는 휴진으로 남고, 새 날짜가 새 회차로 열린다.
        # 왜 그런지는 admin_master_service.close_moved_schedule 에 적어 두었다.
        if not is_new and schedule.event_date != draft["event_date"]:
            stale = schedule
            stale_before = audit_service.snapshot(stale, _SCHEDULE_FIELDS)
            stale_before["cells"] = capacity_snapshot(stale)

            held = admin_master_service.close_moved_schedule(db, stale)
            if held:
                if not dry_run:
                    stale_after = audit_service.snapshot(stale, _SCHEDULE_FIELDS)
                    stale_after["cells"] = capacity_snapshot(stale)
                    audit_service.write_log(
                        db,
                        admin=admin,
                        action="HOSPITAL_SCHEDULE_SAVE",
                        target_type="hospital_schedule",
                        target_id=stale.id,
                        target_label=(
                            f"{hospital.code} {hospital.name} "
                            f"{stale.event_date.isoformat()} 休診 "
                            f"(開催日を {draft['event_date'].isoformat()} に移動)"
                        ),
                        before=stale_before,
                        after=audit_service.diff(stale_before, stale_after),
                        ip_address=ip_address,
                        batch_id=batch_id,
                    )

                warnings.append(BulkFieldError(
                    row_no=draft["row_no"],
                    field="event_date",
                    message=(
                        f"{stale.event_date.isoformat()} に予約が {held}件あるため、"
                        f"日付を移動せずに分割しました。この日は休診となり、"
                        f"{draft['event_date'].isoformat()} が新しく開きます。"
                        "予約検索の「休診日」フィルターからお一人ずつ移動してください。"
                    ),
                ))

                schedule = HospitalSchedule(
                    hospital_id=hospital.id, event_date=draft["event_date"]
                )
                db.add(schedule)
                db.flush()
                is_new = True
                before = {}

        schedule.hospital_id = hospital.id
        for field in _SCHEDULE_FIELDS:
            setattr(schedule, field, draft[field])

        counts = grid.counts_of(db, schedule)

        cells_changed = False
        for index in time_grid.indexes():
            wanted = draft["cells"].get(index)
            current = schedule.capacity_at(index)
            if wanted == current:
                continue

            if wanted is None and counts.reserved_at(index) > 0:
                # 예약이 걸린 칸은 비우지 않는다. 비우면 그 예약이 몇 시였는지
                # 화면이 답할 수 없게 된다.
                warnings.append(BulkFieldError(
                    row_no=draft["row_no"],
                    field=time_grid.sheet_key(index),
                    message=(
                        f"予約が {counts.reserved_at(index)}件あるため、この時間帯を"
                        "空にしませんでした。"
                    ),
                ))
                continue

            # 정원이 **사라지는** 칸은 따로 알린다.
            #
            # 시간대 열이 빠진 파일(오전 열만 잘라 온 파일 등)을 올리면 그
            # 칸이 「열지 않음」이 된다. 값이 바뀌는 것과 자리가 없어지는 것은
            # 뜻이 다른데, 예전에는 둘 다 조용히 지나갔다. 되돌리려면 원래
            # 정원이 얼마였는지 알아야 하므로 그 숫자를 문장에 담는다.
            if wanted is None and current is not None:
                warnings.append(BulkFieldError(
                    row_no=draft["row_no"],
                    field=time_grid.sheet_key(index),
                    message=(
                        f"{hospital.code} {schedule.event_date.isoformat()} "
                        f"{time_grid.label(index)} — 定員 {current} がなくなり、"
                        "「この時間帯は受付なし」になります。"
                    ),
                ))

            schedule.set_capacity_at(index, wanted)
            if wanted is None:
                schedule.set_closed_at(index, False)
            cells_changed = True

        db.flush()
        after = audit_service.snapshot(schedule, _SCHEDULE_FIELDS)
        after["cells"] = capacity_snapshot(schedule)
        changed = [f for f in _SCHEDULE_FIELDS if before.get(f) != after.get(f)]
        if cells_changed:
            changed.append("cells")

        if is_new:
            created += 1
            action = "CREATED"
        elif changed:
            updated += 1
            action = "UPDATED"
        else:
            unchanged += 1
            action = "UNCHANGED"

        if action != "UNCHANGED" and not dry_run:
            audit_service.write_log(
                db,
                admin=admin,
                action="HOSPITAL_SCHEDULE_SAVE",
                target_type="hospital_schedule",
                target_id=schedule.id,
                target_label=(
                    f"{hospital.code} {hospital.name} "
                    f"{schedule.event_date.isoformat()}"
                ),
                before=before or None,
                after=audit_service.diff(before, after) if before else after,
                ip_address=ip_address,
                batch_id=batch_id,
            )

        totals = grid.totals_of(schedule)
        results.append(CapacityBulkRowResult(
            row_no=draft["row_no"],
            schedule_id=schedule.id,
            hospital_id=hospital.id,
            hospital_code=hospital.code,
            hospital_name=hospital.name,
            event_date=schedule.event_date,
            action=action,
            changed_fields=changed,
            changes=_changes_of(before, after, changed, capacity_columns()),
            total_capacity=totals.capacity,
            total_reserved=totals.reserved,
        ))

    # 이 표에 아예 없는 회차는 몇 건인가. 「표에 없는 것은 지우지 않는다」를
    # 숫자로 보여 준다.
    touched_ids = {
        d["schedule"].id for d in drafts if d.get("schedule") is not None
    }
    untouched = len([s for s in schedules_by_id.values() if s.id not in touched_ids])

    if dry_run:
        db.rollback()
    else:
        audit_service.write_log(
            db,
            admin=admin,
            action="SLOT_BULK_UPDATE",
            target_type="hospital_schedule",
            target_label=_format_bulk_label("定員管理", len(drafts), "開催回", created, updated),
            after={"created": created, "updated": updated, "unchanged": unchanged},
            ip_address=ip_address,
            batch_id=batch_id,
        )
        db.commit()

    return CapacityBulkResult(
        created_count=created, updated_count=updated, unchanged_count=unchanged,
        untouched_count=untouched, rows=results, warnings=warnings,
    )


def set_cell_closed(
    db: Session,
    schedule_id: int,
    cell: str,
    closed: bool,
    *,
    admin: AdminUser,
    ip_address: str,
) -> dict[str, Any]:
    """시간대 한 칸을 마감하거나 푼다.

    정원과 별개의 상태이므로 저장 경로도 나눠 둔다. 표에서 셀을 우클릭해
    바로 바꾸는 조작이며, 값이 아니라 **상태**를 바꾸는 일이다.
    """
    schedule = db.get(HospitalSchedule, schedule_id)
    if schedule is None:
        raise BulkDataError("開催回が見つかりません。")

    index = time_grid.index_of_sheet_key(cell)
    if index is None:
        raise BulkDataError(f"「{cell}」は時間割に存在しない時間帯です。")
    if schedule.capacity_at(index) is None:
        raise BulkDataError("この時間帯は受付なしのため、締切を設定できません。")

    schedule.set_closed_at(index, closed)

    audit_service.write_log(
        db,
        admin=admin,
        action="SLOT_UPDATE",
        target_type="hospital_schedule",
        target_id=schedule.id,
        target_label=f"{schedule.event_date.isoformat()} {time_grid.label(index)}",
        after={"closed": closed},
        ip_address=ip_address,
    )
    db.commit()

    view = grid.view_at(schedule, index)
    return {
        "schedule_id": schedule.id,
        "cell": cell,
        "is_closed": closed,
        "capacity": view.capacity if view else 0,
        "reserved": view.reserved_count if view else 0,
        "remaining": view.remaining if view else 0,
    }


# ==========================================================================
# ③ 옵션 검사 일괄 관리
# ==========================================================================
#
# 회장·정원과 같은 표로 맞춘다. 예전에는 카드 목록 + 행마다 수정 모달이라,
# 검사 12건의 타깃 연령을 한 살씩 올리는 데 모달을 열두 번 열어야 했다.
# CSV 입출력도 따로 붙어 있어 「표에서 고치는 것」과 「파일로 고치는 것」이
# 다른 화면이었고, 검증 규칙이 두 벌이었다.

GENDER_CHOICES: tuple[tuple[str, str], ...] = (
    ("ALL", "全員"),
    ("M", "男性のみ"),
    ("F", "女性のみ"),
)

_GENDER_VALUES = {value for value, _ in GENDER_CHOICES}

# 사람이 칠 법한 표기를 코드로 되돌린다. 화면은 말을 보내지만, 파일에는
# 코드가 적혀 있을 수도 있고 담당자가 「男」이라고만 쓸 수도 있다.
#
# 화면·내보내기가 쓰는 라벨(`GENDER_CHOICES`)은 **아래에서 자동으로 합친다.**
# 예전에는 여기에 손으로 적어 두었다가 라벨만 「全体」→「全員」으로 바뀌면서
# 내보낸 파일을 그대로 가져오지 못했다. 라벨은 한 곳(`GENDER_CHOICES`)에만 적고,
# 여기에는 「손으로 칠 법한 그 밖의 표기」만 남긴다.
_GENDER_ALIASES: dict[str, str] = {
    "all": "ALL", "全体": "ALL", "共通": "ALL", "-": "ALL", "*": "ALL",
    "m": "M", "male": "M", "男": "M", "男性": "M",
    "f": "F", "female": "F", "女": "F", "女性": "F",
}

# 라벨 자체도 받아들인다(내보내기 → 가져오기 왕복이 깨지지 않도록).
_GENDER_ALIASES.update({
    label.casefold(): value
    for value, label in GENDER_CHOICES
    if label.casefold() not in _GENDER_ALIASES
})

# 안내 문구도 라벨에서 만든다. 라벨을 고치면 문구가 따라온다.
_GENDER_LABEL_LIST = "・".join(f"「{label}」" for _, label in GENDER_CHOICES)

# 나이의 상식적인 범위. 이 밖의 값은 오타로 본다.
_AGE_MIN, _AGE_MAX = 0, 120

EXAM_OPTION_COLUMNS: tuple[GridColumn, ...] = (
    GridColumn(key="code", label="コード", width=110, group="検査"),
    GridColumn(key="name", label="検査名", width=240, group="検査"),
    GridColumn(key="is_active", label="予約画面に表示", width=120, kind="bool", group="表示"),
    GridColumn(key="sort_order", label="表示順", width=72, kind="number", group="表示"),
    GridColumn(
        key="target_gender", label="対象性別", width=110, kind="enum",
        group="対象",
        choices=[GridChoice(value=v, label=l) for v, l in GENDER_CHOICES],
    ),
    GridColumn(key="target_age_min", label="最小年齢", width=92, kind="number", group="対象"),
    GridColumn(key="target_age_max", label="最大年齢", width=92, kind="number", group="対象"),
    GridColumn(key="description", label="説明", width=300, group="案内"),
    GridColumn(key="note", label="準備事項", width=260, group="案内"),
)

_OPTION_TEXT_LIMITS = (
    ("description", 2000, "説明"),
    ("note", 255, "準備事項"),
)

_OPTION_BULK_FIELDS = [
    "code", "name", "description", "note",
    "target_gender", "target_age_min", "target_age_max",
    "is_active", "sort_order",
]


def parse_gender(text: str) -> str | None:
    """사람이 친 성별 표기를 코드로. 모르면 None."""
    key = (text or "").strip().casefold()
    if not key:
        return None
    if key.upper() in _GENDER_VALUES:
        return key.upper()
    return _GENDER_ALIASES.get(key)


def exam_option_grid(db: Session) -> ExamOptionGridData:
    """지금 등록된 옵션 검사를 표의 행으로. **한 검사에 한 행.**"""
    from app.models.exam_option import ExamOption
    from app.models.reservation import ReservationOption

    # 신청 건수는 행마다 세지 않고 한 번에 센다.
    used = dict(
        db.execute(
            select(ReservationOption.exam_option_id, func.count())
            .group_by(ReservationOption.exam_option_id)
        ).all()
    )

    options = db.execute(
        select(ExamOption).order_by(ExamOption.sort_order, ExamOption.id)
    ).scalars().all()

    rows: list[dict[str, Any]] = []
    for o in options:
        rows.append({
            "id": str(o.id),
            "code": o.code,
            "name": o.name,
            "is_active": _bool_text(o.is_active),
            "sort_order": str(o.sort_order),
            "target_gender": o.target_gender,
            "target_age_min": str(o.target_age_min),
            "target_age_max": str(o.target_age_max),
            "description": o.description,
            "note": o.note,
            # 읽기 전용 참고 값. 이 표에서 고칠 수는 없지만, **지울 수 있는지**와
            # 「사용함을 끄면 무엇이 멈추는지」가 이 숫자에 달려 있다.
            "_used_count": int(used.get(o.id, 0)),
        })

    return ExamOptionGridData(columns=list(EXAM_OPTION_COLUMNS), rows=rows)


def _validate_exam_option_row(
    row,
    row_no: int,
    *,
    by_id: dict,
    by_code: dict,
    seen_codes: dict[str, int],
    errors: list[BulkFieldError],
):
    def add(field: str, message: str) -> None:
        errors.append(BulkFieldError(row_no=row_no, field=field, message=message))

    before = len(errors)
    values: dict[str, Any] = {}

    # --- 코드 : 검사를 특정하는 열쇠 --------------------------------------
    code = _cell(row.code).strip()
    if not code:
        add("code", "コードは必須です。")
    elif len(code) > 20:
        add("code", "コードは20文字以内で入力してください。")
    else:
        duplicate_at = seen_codes.get(code.casefold())
        if duplicate_at is not None:
            add("code", f"{duplicate_at}行目とコードが重複しています。"
                        "この表では1検査につき1行です。")
        else:
            seen_codes[code.casefold()] = row_no
    values["code"] = code

    name = _cell(row.name)
    if not name:
        add("name", "検査名は必須です。")
    elif len(name) > 120:
        add("name", "検査名は120文字以内で入力してください。")
    values["name"] = name

    # --- 어느 검사를 고치는가 ---------------------------------------------
    # id 가 오면 그것이 우선이다. 코드를 고치는 수정(오타 정정)이 코드로만
    # 찾으면 「새 검사 등록」이 되어 버린다.
    option = None
    raw_id = _cell(row.id)
    if raw_id:
        if not raw_id.isdigit() or int(raw_id) not in by_id:
            add("code", "この行が示す検査が見つかりません。画面を更新してください。")
        else:
            option = by_id[int(raw_id)]
    elif code:
        option = by_code.get(code.casefold())

    if code:
        owner = by_code.get(code.casefold())
        if owner is not None and option is not None and owner.id != option.id:
            add("code", f"コード「{code}」は {owner.name} が使用しています。")

    for field, limit, label in _OPTION_TEXT_LIMITS:
        text = _cell(getattr(row, field))
        if len(text) > limit:
            add(field, f"{label} は {limit}文字以内で入力してください。")
        values[field] = text

    # --- 타깃 성별 ---------------------------------------------------------
    # 비우면 「전체」로 본다. 성별을 안 적었다는 것은 가리지 않겠다는 뜻이다.
    gender_text = _cell(row.target_gender)
    if not gender_text:
        values["target_gender"] = "ALL"
    else:
        parsed = parse_gender(gender_text)
        if parsed is None:
            add("target_gender",
                f"対象性別は{_GENDER_LABEL_LIST}の中から入力してください。")
            values["target_gender"] = "ALL"
        else:
            values["target_gender"] = parsed

    # --- 타깃 연령 ---------------------------------------------------------
    for field, label, default in (
        ("target_age_min", "最小年齢", 40),
        ("target_age_max", "最大年齢", 74),
    ):
        text = _cell(getattr(row, field))
        if not text:
            values[field] = default
            continue
        number = _parse_int(text)
        if number is None:
            add(field, f"{label} は数値で入力してください。")
            values[field] = default
        elif not (_AGE_MIN <= number <= _AGE_MAX):
            add(field, f"{label} は {_AGE_MIN}～{_AGE_MAX} の間で入力してください。")
            values[field] = default
        else:
            values[field] = number

    if values["target_age_min"] > values["target_age_max"]:
        add("target_age_max",
            "最大年齢が最小年齢より小さくなっています。このままでは誰にも表示されません。")

    # --- 사용함 -----------------------------------------------------------
    text = _cell(row.is_active).casefold()
    if not text:
        values["is_active"] = True
    elif text in _TRUE_TEXTS:
        values["is_active"] = True
    elif text in _FALSE_TEXTS:
        values["is_active"] = False
    else:
        add("is_active", "有効は「はい」または「いいえ」で入力してください。")
        values["is_active"] = True

    # --- 순서 -------------------------------------------------------------
    text = _cell(row.sort_order)
    if not text:
        values["sort_order"] = 0
    else:
        number = _parse_int(text)
        if number is None:
            add("sort_order", "表示順は数値で入力してください。")
            values["sort_order"] = 0
        else:
            values["sort_order"] = number

    if len(errors) != before:
        return None
    return option, values


def save_exam_options(
    db: Session,
    payload: ExamOptionBulkRequest,
    *,
    admin: AdminUser,
    ip_address: str,
    dry_run: bool = False,
) -> ExamOptionBulkResult:
    """옵션 검사 표를 마스터에 반영한다.

    **표에 없는 검사는 지우지 않는다.** 삭제는 행 메뉴에서만 하며, 신청된
    예약이 있으면 그쪽에서도 거절된다.
    """
    from app.models.exam_option import ExamOption

    options = db.execute(select(ExamOption)).scalars().all()
    by_id = {o.id: o for o in options}
    by_code = {o.code.casefold(): o for o in options}

    batch_id = audit_service.new_batch_id()

    errors: list[BulkFieldError] = []
    warnings: list[BulkFieldError] = []
    seen_codes: dict[str, int] = {}
    drafts: list[tuple[int, Any, dict[str, Any]]] = []

    for index, row in enumerate(payload.rows, start=1):
        row_no = int(row.row_no) if str(row.row_no or "").isdigit() else index
        parsed = _validate_exam_option_row(
            row, row_no,
            by_id=by_id, by_code=by_code, seen_codes=seen_codes, errors=errors,
        )
        if parsed is not None:
            drafts.append((row_no, parsed[0], parsed[1]))

    if errors:
        raise BulkValidationError(errors)

    results: list[ExamOptionBulkRowResult] = []
    created = updated = unchanged = 0

    for row_no, option, values in drafts:
        is_new = option is None
        if is_new:
            option = ExamOption()
            db.add(option)
            before: dict[str, Any] = {}
        else:
            before = audit_service.snapshot(option, _OPTION_BULK_FIELDS)

        for field in _OPTION_BULK_FIELDS:
            setattr(option, field, values[field])

        db.flush()
        after = audit_service.snapshot(option, _OPTION_BULK_FIELDS)
        changed = [f for f in _OPTION_BULK_FIELDS if before.get(f) != after.get(f)]

        if is_new:
            created += 1
            action = "CREATED"
        elif changed:
            updated += 1
            action = "UPDATED"
        else:
            unchanged += 1
            action = "UNCHANGED"

        # 타깃을 좁히면 이용자 화면의 선택지가 **즉시** 바뀐다 (BR-13).
        # 막지는 않는다 — 좁히는 것이 목적일 수 있다. 다만 조용히 넘기지도
        # 않는다. 「왜 신청이 안 되냐」는 문의가 여기서 나온다.
        if not is_new and ("target_gender" in changed
                           or "target_age_min" in changed
                           or "target_age_max" in changed):
            warnings.append(BulkFieldError(
                row_no=row_no, field="target_gender",
                message=(
                    f"{option.name} の対象条件が変更されました。"
                    "条件に合致しない方には利用者画面でこの検査が"
                    "一切表示されません。"
                ),
            ))

        if not is_new and "is_active" in changed and not option.is_active:
            warnings.append(BulkFieldError(
                row_no=row_no, field="is_active",
                message=f"{option.name} を無効にしました。新規申込を受け付けません。",
            ))

        if not dry_run and (is_new or changed):
            audit_service.write_log(
                db,
                admin=admin,
                action="EXAM_OPTION_CREATE" if is_new else "EXAM_OPTION_UPDATE",
                target_type="exam_option",
                target_id=option.id,
                target_label=f"{option.code} {option.name}",
                before=before or None,
                after=audit_service.diff(before, after) if before else after,
                ip_address=ip_address,
                batch_id=batch_id,
            )

        results.append(ExamOptionBulkRowResult(
            row_no=row_no, id=option.id, code=option.code, name=option.name,
            action=action, changed_fields=changed,
            changes=_changes_of(before, after, changed, EXAM_OPTION_COLUMNS),
        ))

    if dry_run:
        # 무엇이 바뀔지만 세고 되돌린다. 「저장하면 어떻게 되는가」를
        # 저장하기 전에 보여 주기 위한 경로다.
        db.rollback()
    else:
        audit_service.write_log(
            db,
            admin=admin,
            action="EXAM_OPTION_BULK_SAVE",
            target_type="exam_option",
            target_label=_format_bulk_label("オプション検査一括管理", len(drafts), "件", created, updated),
            after={"created": created, "updated": updated, "unchanged": unchanged},
            ip_address=ip_address,
            batch_id=batch_id,
        )
        db.commit()

    return ExamOptionBulkResult(
        created_count=created, updated_count=updated, unchanged_count=unchanged,
        rows=results, warnings=warnings,
    )
