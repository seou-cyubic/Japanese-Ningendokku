"""회장 마스터 Excel · CSV 를 MySQL 로 임포트한다.

    python -m scripts.import_hospitals            # 갱신 (기존 슬롯 덮어쓰기)
    python -m scripts.import_hospitals --reset    # 회장·회차·슬롯 전체 삭제 후 재적재
    python -m scripts.import_hospitals --file data/hospitals/test_data.csv
    python -m scripts.import_hospitals --reset --shift-to-future   # 샘플 날짜를 앞으로 민다

읽는 위치 : data/hospitals/*.xlsx  (파일 1개, 시트 1장)
            `--file` 로는 .csv 도 읽는다.

한 행이 **개최 회차** 하나다
----------------------------
예전에는 「한 행 = 会場 하나」였다. 회장이 하루만 연다는 전제가 스키마에
박혀 있었기 때문이다.

지금은 다르다. **같은 会場番号 를 가진 행이 여러 列 있으면, 그 회장이
여러 날 연다는 뜻이다.** 시민회관을 7월에 한 번, 10월에 한 번 빌리는
것이 실제 운영이다.

    会場番号  開催日        →  결과
    ----------------------------------------------------------
    T01      2026-09-15       Hospital(T01) + Schedule(09-15)
    T01      2026-10-20                     + Schedule(10-20)
    T01      2026-11-17                     + Schedule(11-17)

장소 정보(주소·좌표·교통편)는 **첫 행에서만 읽는다.** 같은 회장의 행끼리
값이 다르면 첫 행을 채택하고 경고로 남긴다. 어느 쪽이 맞는지는 시트를
만든 사람만 알기 때문에, 조용히 마지막 값으로 덮어쓰지 않는다.

시간표는 열 이름에서 읽는다
---------------------------
`9:30～10:00` 처럼 **시각 범위로 된 열 이름**을 전부 슬롯으로 본다.
값이 있는 칸만 그 회차의 슬롯이 된다. 회차마다 여는 시간이 달라도
(오전만 여는 날, 10시에 시작하는 날) 그대로 반영된다.

값은 **정원**이며 예약 실적 열은 없다. 신규 적재이므로 예약 수는 0이다.
"""

import scripts._console  # noqa: F401  (콘솔 UTF-8 보정)
import csv
import io
import re
import sys
import unicodedata
from collections import OrderedDict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select

from app.core import db_setup
from app.core.config import PROJECT_DIR
from app.core.database import SessionLocal
from app.models.hospital import (  # noqa: F401
    Hospital,
    HospitalSchedule,
    ReservationCount,
)
from app.models.reservation import Reservation
from app.models.target_person import TargetPerson  # noqa: F401
from app.core import time_grid
from app.services import hospital_sheet_service
from app.services import slot_grid_service as grid

SHEET_DIR = PROJECT_DIR / "data" / "hospitals"

# --------------------------------------------------------------------------
# 열 이름 → 우리 필드
# --------------------------------------------------------------------------
# 표기 흔들림(전각·공백·괄호)을 흡수한 뒤 맞춘다. 원본을 담당자가 다시
# 내려받아 열 이름이 한 글자 달라져도 여기 한 줄만 늘리면 된다.
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "venue_no": ("会場番号", "会場no", "id"),
    "area": ("地域", "都道府県"),
    "city": ("区・市町村", "区市町村", "市町村"),
    "name": ("会場名", "会場"),
    # 원본 마스터에는 아직 없는 열이다. 담당자가 읽기 열을 붙여 주면 그대로
    # 받는다. 없으면 기존 값을 지키기만 한다 (`upsert_hospital` 참조).
    "name_kana": ("会場名カナ", "フリガナ", "ふりがな", "よみがな", "フリガナ"),
    "address": ("住所",),
    "open_time": ("開始時刻", "開始時間"),
    "reception_end_time": ("受付終了", "受付終了時刻"),
    "parking": ("駐車場",),
    "latitude": ("緯度",),
    "longitude": ("経度",),
    "transit_info": ("交通情報", "交通"),
    "access_minutes": ("アクセス時間", "アクセス"),
    "event_date": ("開催日",),
    "booking_close_date": ("予約終了", "予約締切"),
    "total": ("計", "合計"),
}

# 별칭 → (필드, 우선순위). 우선순위는 위 표에 적은 순서이며 **작을수록 세다.**
#
# 한 필드에 여러 열이 붙을 수 있다는 것이 문제다. 예를 들어 `venue_no` 는
# 「会場番号」와 「ID」 둘 다 받는데, 원본 마스터에는 **그 두 열이 나란히
# 있다.** 먼저 만난 열을 쓰면 왼쪽에 있는 「ID」가 이기고, 그것은 회장
# 번호가 아니라 줄 번호다. 개최 회차가 여럿인 시트에서는 줄마다 값이
# 달라서, 같은 회장의 세 회차가 서로 다른 회장 세 곳이 되어 버린다.
#
# 원본 파일에서는 ID 와 会場番号 가 우연히 같은 값(1..20)이라 이 어긋남이
# 드러나지 않았다. 별칭 표의 순서를 우선순위로 삼아 「会場番号」가 이기게 한다.
_ALIAS_TO_FIELD: dict[str, tuple[str, int]] = {
    alias: (field, rank)
    for field, aliases in COLUMN_ALIASES.items()
    for rank, alias in enumerate(aliases)
}

# 「9:30～10:00」 형태의 열 이름. 물결표는 전각(～)·반각(~) 둘 다 온다.
SLOT_HEADER = re.compile(r"^(\d{1,2}):(\d{2})[~～－\-](\d{1,2}):(\d{2})$")

# 회장(장소)에 속하는 칸. 같은 회장의 행끼리 이 값이 다르면 경고한다.
# 개최일·마감일·개시 시각은 **회차마다 달라도 정상**이므로 여기 없다.
VENUE_FIELDS: tuple[tuple[str, str], ...] = (
    ("name", "会場名"),
    ("area", "地域"),
    ("city", "区・市町村"),
    ("address", "住所"),
    ("transit_info", "交通情報"),
    ("access_minutes", "アクセス時間"),
    ("parking", "駐車場"),
    ("latitude", "緯度"),
    ("longitude", "経度"),
)


def normalize_header(value: Any) -> str:
    """열 이름을 대조용으로 다듬는다. 전각·공백·대소문자를 흡수한다."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"[\s　]+", "", text).casefold()


def parse_time(value: Any) -> time | None:
    if value is None or value == "":
        return None
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    if isinstance(value, datetime):
        return value.time().replace(second=0, microsecond=0)
    text = unicodedata.normalize("NFKC", str(value)).strip()
    matched = re.match(r"^(\d{1,2}):(\d{2})", text)
    if not matched:
        return None
    return time(int(matched.group(1)), int(matched.group(2)))


def parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = unicodedata.normalize("NFKC", str(value)).strip()
    text = re.sub(r"\s+.*$", "", text)  # 「2026-07-17 00:00:00」의 뒤를 자른다
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = unicodedata.normalize("NFKC", str(value)).strip()
    return int(text) if re.fullmatch(r"-?\d+", text) else None


def parse_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = unicodedata.normalize("NFKC", str(value)).strip()
    try:
        return float(text)
    except ValueError:
        return None


def parse_bool(value: Any) -> bool:
    """駐車場 칸. 원본은 ○ / ×."""
    if isinstance(value, bool):
        return value
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return text in {"○", "◯", "o", "有", "あり", "yes", "y", "true", "1", "예"}


def text_of(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return re.sub(r"[\r\n\t]+", " ", str(value)).strip()


def venue_code(value: Any, fallback: int) -> str:
    """会場番号 → 会場 코드.

    번호만 있는 값(1, 2, …)은 `V01` 형태로 만든다. 코드는 우편 일괄 입력에서
    스태프가 손으로 적는 값이므로, 「1」보다 「V01」쪽이 옆 칸의 숫자와
    헷갈리지 않는다. 이미 문자가 섞인 코드라면 그대로 쓴다.

    관리 화면의 会場 일괄 관리(A-24)도 **같은 함수**를 쓴다. 두 경로가 다른
    코드를 만들면, 같은 마스터를 한쪽으로 넣은 뒤 다른 쪽으로 올렸을 때
    같은 회장이 두 벌 생긴다.
    """
    text = text_of(value)
    return hospital_sheet_service.normalize_code(text) or f"V{fallback:02d}"


# --------------------------------------------------------------------------
# 시트 읽기
# --------------------------------------------------------------------------


def find_sheet_file(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            path = PROJECT_DIR / path
        if not path.exists():
            raise SystemExit(f" ファイルが見つかりません : {path}")
        return path

    candidates = sorted(
        p for p in SHEET_DIR.glob("*.xlsx") if not p.name.startswith("~$")
    )
    if not candidates:
        raise SystemExit(
            f" 会場マスターの Excel がありません。\n"
            f" {SHEET_DIR} に .xlsx ファイルを置いて実行し直してください。"
        )
    if len(candidates) > 1:
        names = "\n   ".join(p.name for p in candidates)
        raise SystemExit(
            f" .xlsx が複数あります。--file で 1 つを指定してください。\n   {names}"
        )
    return candidates[0]


def read_matrix(path: Path) -> list[list[Any]]:
    """파일을 2차원 배열로. `.csv` 와 `.xlsx` 를 같은 모양으로 돌려준다.

    CSV 를 함께 읽는 이유는 실험용 데이터 때문이다. 개최 회차가 여러 개인
    마스터를 손으로 만들어 보려면 Excel 을 열어야 했는데, 그러면 무엇을
    바꿨는지 diff 로 볼 수 없다.
    """
    suffix = path.suffix.casefold()

    if suffix == ".csv":
        # BOM 이 붙은 채로 저장된 파일이 흔하다(Excel 이 그렇게 내보낸다).
        # `utf-8-sig` 가 아니면 첫 열 이름이 `﻿ID` 가 되어 붙지 않는다.
        with io.open(path, encoding="utf-8-sig", newline="") as fp:
            return [list(row) for row in csv.reader(fp)]

    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            " openpyxl が必要です。pip install -r requirements.txt"
        ) from exc

    book = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    try:
        sheet = book[book.sheetnames[0]]
        return [list(cells) for cells in sheet.iter_rows(values_only=True)]
    finally:
        book.close()


def read_sheet(path: Path) -> tuple[list[dict[str, Any]], list[tuple[time, time, str]]]:
    """시트를 (행 목록, 슬롯 열 목록) 으로 읽는다.

    슬롯 열은 `(시작, 종료, 원본 열 이름)` 이며 시트에 적힌 순서를 지킨다.
    행에는 원본 줄 번호(`_row_no`)를 붙여 둔다 — 경고에 「몇 번째 줄」을
    적지 못하면, 회차가 여럿인 시트에서 어느 줄이 문제인지 찾을 수 없다.
    """
    matrix = read_matrix(path)
    if not matrix:
        raise SystemExit(" シートが空です。")

    header = matrix[0]
    field_at: dict[int, str] = {}
    # 어느 열이 어느 필드를 차지하고 있는지와, 그 열이 얼마나 센 별칭으로
    # 붙었는지. 더 센 별칭이 나오면 자리를 넘긴다.
    holder: dict[str, tuple[int, int]] = {}
    slot_at: dict[int, tuple[time, time, str]] = {}

    for index, raw in enumerate(header):
        label = normalize_header(raw)
        if not label:
            continue

        matched = SLOT_HEADER.match(label)
        if matched:
            start = time(int(matched.group(1)), int(matched.group(2)))
            end = time(int(matched.group(3)), int(matched.group(4)))
            slot_at[index] = (start, end, text_of(raw))
            continue

        found = _ALIAS_TO_FIELD.get(label)
        if not found:
            continue
        field, rank = found

        current = holder.get(field)
        if current is None:
            holder[field] = (index, rank)
            field_at[index] = field
        elif rank < current[1]:
            del field_at[current[0]]
            holder[field] = (index, rank)
            field_at[index] = field

    missing = {"name", "event_date"} - set(field_at.values())
    if missing:
        raise SystemExit(
            f" 必須の列が見つかりません : {', '.join(sorted(missing))}\n"
            f" 1 行目が見出し行になっているかご確認ください。"
        )
    if not slot_at:
        raise SystemExit(
            " 時間帯の列が見つかりません。「9:30～10:00」の形式の列名が必要です。"
        )

    rows: list[dict[str, Any]] = []
    for line_no, cells in enumerate(matrix[1:], start=2):
        if not any(text_of(cell) for cell in cells):
            continue

        row: dict[str, Any] = {"_slots": [], "_row_no": line_no}
        for index, field in field_at.items():
            row[field] = cells[index] if index < len(cells) else None
        for index, (start, end, label) in slot_at.items():
            capacity = parse_int(cells[index]) if index < len(cells) else None
            if capacity is not None and capacity > 0:
                row["_slots"].append((start, end, capacity, label))
        rows.append(row)

    slots = [slot_at[index] for index in sorted(slot_at)]
    return rows, slots


def group_by_venue(rows: list[dict[str, Any]]) -> "OrderedDict[str, list[dict]]":
    """같은 会場番号 의 행을 한 회장으로 모은다. 시트에 나온 순서를 지킨다.

    코드가 비어 있으면 그 **행 번호**로 대체 코드를 만든다. 옆줄과 묶어
    버리면 서로 다른 회장의 개최일이 한 회장에 붙는다.
    """
    groups: "OrderedDict[str, list[dict]]" = OrderedDict()
    for index, row in enumerate(rows, start=1):
        code = venue_code(row.get("venue_no"), index)
        groups.setdefault(code, []).append(row)
    return groups


# --------------------------------------------------------------------------
# 적재
# --------------------------------------------------------------------------


def upsert_hospital(
    db,
    code: str,
    rows: list[dict[str, Any]],
    order: int,
    kana_before: dict[str, str] | None = None,
) -> tuple[Hospital, list[str]]:
    """회장(장소) 1곳을 만들거나 갱신한다. 값은 **첫 행**에서 읽는다.

    `kana_before` 는 `--reset` 으로 지우기 **직전**의 코드 → フリガナ다.
    마스터 파일에는 읽기 열이 없으므로, 이것이 없으면 회기마다 담당자가
    표에 채워 넣은 フリガナ가 사라진다 (아래 참조).
    """
    notes: list[str] = []
    head = rows[0]

    # 같은 회장의 행끼리 장소 정보가 다르면 알린다. 첫 행을 채택한다 —
    # 마지막 행으로 덮어쓰면 시트의 줄 순서를 바꾸는 것만으로 주소가 바뀐다.
    for field, label in VENUE_FIELDS:
        first = text_of(head.get(field))
        for row in rows[1:]:
            other = text_of(row.get(field))
            if other != first:
                notes.append(
                    f"{row['_row_no']}行の「{label}」({other or '空欄'}) が "
                    f"{head['_row_no']}行({first or '空欄'}) と異なるため、"
                    f"{head['_row_no']}行の値を使用します"
                )

    area = text_of(head.get("area"))
    city = text_of(head.get("city"))

    hospital = db.execute(
        select(Hospital).where(Hospital.code == code)
    ).scalar_one_or_none()
    if hospital is None:
        hospital = Hospital(code=code)
        db.add(hospital)

    hospital.name = text_of(head.get("name"))

    # 후리가나(요미가나)는 원본 마스터에 **열 자체가 없다.** 그래서
    #
    #   ① 파일에 읽기 열이 있으면 그것이 이긴다 (담당자가 열을 붙일 수 있게)
    #   ② 없으면 지우기 직전의 값을 되돌린다 (--reset 재적재로 잃지 않게)
    #   ③ 둘 다 없으면 빈 채로 둔다 — 회장 관리 표가 「읽기 없음」으로 알린다
    #
    # 이 값이 비면 관리 화면의 빠른 검색에서 히라가나로 그 회장을 찾을 수
    # 없다. 이용자 화면에는 영향이 없다.
    file_kana = text_of(head.get("name_kana"))
    hospital.name_kana = (
        file_kana or (kana_before or {}).get(code) or hospital.name_kana or ""
    )

    hospital.area = area
    hospital.city = city
    # 표시용 한 줄. 「東京都」+「港区」→「東京都港区」
    hospital.region = f"{area}{city}"
    hospital.address = text_of(head.get("address"))
    hospital.transit_info = text_of(head.get("transit_info"))
    hospital.access_minutes = text_of(head.get("access_minutes"))
    hospital.has_parking = parse_bool(head.get("parking"))
    hospital.latitude = parse_float(head.get("latitude"))
    hospital.longitude = parse_float(head.get("longitude"))
    # 전화번호는 원본에 없다. 비워 두면 공통 문의처(.env CONTACT_TEL)를 쓴다.
    hospital.tel = ""
    hospital.postal_code = ""
    hospital.is_visible = True
    hospital.sort_order = order

    db.flush()
    return hospital, notes


def upsert_schedule(
    db, hospital: Hospital, row: dict[str, Any], order: int
) -> tuple[HospitalSchedule | None, list[str]]:
    """행 하나를 개최 회차로. 개최일이 없으면 회차를 만들지 않는다."""
    notes: list[str] = []
    event_date = parse_date(row.get("event_date"))
    if event_date is None:
        notes.append(f"{row['_row_no']}行 — 開催日 を読み取れないためスキップします")
        return None, notes

    close_date = parse_date(row.get("booking_close_date"))

    schedule = db.execute(
        select(HospitalSchedule).where(
            HospitalSchedule.hospital_id == hospital.id,
            HospitalSchedule.event_date == event_date,
        )
    ).scalar_one_or_none()
    if schedule is None:
        schedule = HospitalSchedule(hospital_id=hospital.id, event_date=event_date)
        db.add(schedule)

    schedule.booking_close_date = close_date
    schedule.open_time = parse_time(row.get("open_time"))
    schedule.reception_end_time = parse_time(row.get("reception_end_time"))
    schedule.is_visible = True
    schedule.sort_order = order

    if close_date is None:
        notes.append(f"{event_date} — 予約終了 が空のため、締切日なしで受け付けます")
    elif close_date > event_date:
        notes.append(f"{event_date} — 予約終了({close_date}) が 開催日 より後になっています")

    db.flush()
    return schedule, notes


def sync_slots(db, schedule: HospitalSchedule, row: dict[str, Any]) -> tuple[int, list[str]]:
    """한 회차의 정원 그리드를 시트에 맞춘다."""
    notes: list[str] = []
    label = schedule.event_date.isoformat()
    counts = grid.counts_of(db, schedule)

    wanted: set[int] = set()
    count = 0

    for start, _end, capacity, _column in row["_slots"]:
        index = time_grid.index_of(start)
        if index is None:
            notes.append(
                f"{label} {start.strftime('%H:%M')} は時間グリッドにない時刻のため"
                f"取り込めませんでした (app/core/time_grid.py 参照)"
            )
            continue

        wanted.add(index)
        reserved = counts.reserved_at(index)

        # 예약이 이미 들어간 칸의 정원을 예약 수 아래로 내리지 않는다.
        # 마스터를 다시 올렸다는 이유로 예약이 정원을 넘긴 상태가 되면
        # 남은 좌석 계산이 전부 어긋난다. (BR-09)
        if reserved > capacity:
            notes.append(
                f"{label} {time_grid.label(index)} はすでに {reserved}名の"
                f"予約が入っているため、定員を {capacity} に減らせませんでした"
            )
            schedule.set_capacity_at(index, reserved)
        else:
            schedule.set_capacity_at(index, capacity)
        count += 1

    for index in list(schedule.open_indexes()):
        if index in wanted:
            continue
        notes.extend(retire_slot(db, schedule, index, f"{label} {time_grid.label(index)}"))

    total = sum(item[2] for item in row["_slots"])
    declared = parse_int(row.get("total"))
    if declared is not None and declared != total:
        notes.append(f"{label} — 「計」({declared}) と時間帯の合計({total}) が一致しません")

    return count, notes


def retire_slot(db, schedule: HospitalSchedule, index: int, label: str) -> list[str]:
    """시트에서 사라진 시간대를 비운다. 예약이 얽혀 있으면 비우지 않는다."""
    counts = grid.counts_of(db, schedule)
    reserved = counts.reserved_at(index)

    if reserved > 0:
        return [f"{label} は予約 {reserved}件があるため残しました"]

    # 취소된 예약이 이 시간대를 가리키고 있으면, 비우는 대신 마감해 둔다.
    # 비워 버리면 그 예약 기록이 어느 시간대였는지 화면이 답할 수 없다.
    has_history = db.execute(
        select(func.count(Reservation.id)).where(
            Reservation.schedule_id == schedule.id,
            Reservation.start_time == time_grid.start_time(index),
        )
    ).scalar()

    if has_history:
        if schedule.capacity_at(index) != 0 or not schedule.is_closed_at(index):
            schedule.set_capacity_at(index, 0)
            schedule.set_closed_at(index, True)
        return [f"{label} はキャンセル済みの予約記録があるため、定員 0 で締め切りました"]

    schedule.set_capacity_at(index, None)
    schedule.set_closed_at(index, False)
    return []


def retire_schedule(db, schedule: HospitalSchedule) -> list[str]:
    """시트에서 사라진 회차를 정리한다.

    예약이 하나라도 얽혀 있으면 **회차를 지우지 않는다.** 회차가 사라지면
    그 날 예약한 사람들의 검진일이 어디서 왔는지 아무도 설명할 수 없다.
    (외래키가 `RESTRICT` 라 DB 도 막는다.) 대신 전 시간대를 마감하고
    회차를 감춰, 새 예약만 막는다.
    """
    label = schedule.event_date.isoformat()
    notes: list[str] = []
    keep = False

    for index in list(schedule.open_indexes()):
        slot_notes = retire_slot(
            db, schedule, index, f"{label} {time_grid.label(index)}"
        )
        if slot_notes:
            keep = True
            notes.extend(slot_notes)

    if keep:
        schedule.is_visible = False
        notes.append(f"{label} の開催回はシートから外れましたが、予約があるため非表示にしただけです")
    else:
        db.delete(schedule)
        notes.append(f"{label} の開催回はシートから外れたため削除しました")

    return notes


def import_venue(
    db, hospital: Hospital, rows: list[dict[str, Any]]
) -> tuple[int, int, int, list[str]]:
    """한 회장의 開催回 전부를 적재한다. → (開催回 수, 슬롯 수, 정원 합, 경고)

    **정리(reconcile)는 会場 단위로 한 번만 한다.** 행마다 「시트에 없는
    것 삭제」를 돌리면, 첫 행을 처리하는 순간 아직 읽지 않은 둘째 회차의
    슬롯이 「시트에 없는 것」으로 보여 지워진다.
    """
    notes: list[str] = []
    slot_total = 0
    capacity_total = 0
    seen: dict[date, int] = {}

    for order, row in enumerate(rows, start=1):
        event_date = parse_date(row.get("event_date"))
        if event_date is not None and event_date in seen:
            notes.append(
                f"{row['_row_no']}行 — 開催日 {event_date} が "
                f"{seen[event_date]}行と重複するためスキップします"
            )
            continue

        schedule, schedule_notes = upsert_schedule(db, hospital, row, order)
        notes.extend(schedule_notes)
        if schedule is None:
            continue

        seen[event_date] = row["_row_no"]
        added, slot_notes = sync_slots(db, schedule, row)
        notes.extend(slot_notes)
        slot_total += added
        # 건너뛴 행의 정원은 세지 않는다. 시트에 적힌 합계를 그대로 찍으면
        # 「정원 345」로 보이는데 DB 에는 253 만 들어가 있게 된다.
        capacity_total += sum(item[2] for item in row["_slots"])

    # 이 회장의 회차 중 이번 시트에 없는 것을 정리한다.
    for schedule in list(hospital.schedules):
        if schedule.event_date not in seen:
            notes.extend(retire_schedule(db, schedule))

    db.flush()
    return len(seen), slot_total, capacity_total, notes


# 샘플 날짜를 옮길 때, 가장 이른 개최일을 오늘로부터 며칠 뒤에 둘 것인가.
# 원본의 접수 마감은 개최일 14일 전이므로, 21일 뒤로 두면 **모든 회차가
# 적어도 1주일은 접수 중**으로 보인다.
SHIFT_LEAD_DAYS = 21


def shift_dates_to_future(rows: list[dict[str, Any]], today: date | None = None) -> int:
    """개최일·마감일을 같은 폭만큼 앞으로 민다. 옮긴 일수를 돌려준다.

    샘플 마스터는 날짜가 박힌 파일이다. 그대로 넣으면 몇 달 뒤 받은 사람의
    화면에는 **회장이 하나도 안 보인다**(지난 회차는 목록에서 빠진다).
    회차끼리의 간격·요일 차이는 그대로 두고 전체를 평행 이동한다.
    이미 충분히 미래라면 옮기지 않는다.
    """
    today = today or date.today()
    dates = [d for d in (parse_date(r.get("event_date")) for r in rows) if d]
    if not dates:
        return 0
    delta = (today + timedelta(days=SHIFT_LEAD_DAYS)) - min(dates)
    if delta.days <= 0:
        return 0
    for row in rows:
        for key in ("event_date", "booking_close_date"):
            value = parse_date(row.get(key))
            if value is not None:
                row[key] = value + delta
    return delta.days


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    reset = "--reset" in argv
    shift = "--shift-to-future" in argv
    explicit = None
    if "--file" in argv:
        index = argv.index("--file")
        if index + 1 >= len(argv):
            print(" --file の後にパスを指定してください。")
            return 1
        explicit = argv[index + 1]

    path = find_sheet_file(explicit)

    print("=" * 78)
    print(" 会場マスター → MySQL インポート")
    print(f" 読み込むファイル : {path.name}")
    print("=" * 78)

    rows, slot_columns = read_sheet(path)
    if shift:
        days = shift_dates_to_future(rows)
        if days:
            print(f" 開催日・予約終了を {days}日 後ろへずらしました (--shift-to-future)")
    groups = group_by_venue(rows)
    print(f" 会場 {len(groups)}件 / 開催回 {len(rows)}件 / "
          f"時間帯の列 {len(slot_columns)}列 "
          f"({slot_columns[0][2]} … {slot_columns[-1][2]})\n")

    db_setup.migrate()

    db = SessionLocal()
    try:
        # 지우기 **직전에** 회장 후리가나를 떠 둔다.
        # 마스터 파일에는 읽기 열이 없으므로, 그대로 지우면 담당자가 회장
        # 관리 표에서 채워 넣은 읽기가 회기마다 사라진다. 아무 오류도 나지
        # 않고 히라가나 검색만 조용히 죽는 종류의 손실이다.
        kana_before: dict[str, str] = {}
        if reset:
            kana_before = {
                row_code: kana
                for row_code, kana in db.execute(
                    select(Hospital.code, Hospital.name_kana)
                ).all()
                if kana
            }
            db.execute(delete(ReservationCount))
            db.execute(delete(HospitalSchedule))
            db.execute(delete(Hospital))
            db.commit()
            print(" 既存の会場・開催回・スロットを削除 (--reset)")
            if kana_before:
                print(f" 会場フリガナ {len(kana_before)}件は削除せず元に戻します")
            print()

        total_schedules = 0
        total_slots = 0
        warnings: list[str] = []

        for order, (code, venue_rows) in enumerate(groups.items(), start=1):
            hospital, venue_notes = upsert_hospital(
                db, code, venue_rows, order, kana_before
            )
            schedules, added, capacity, venue_slot_notes = import_venue(
                db, hospital, venue_rows
            )
            db.commit()
            db.refresh(hospital)

            total_schedules += schedules
            total_slots += added

            dates = ", ".join(d.isoformat() for d in hospital.event_dates) or "-"
            print(f"  {hospital.code}  {hospital.name[:20]:<22} "
                  f"{hospital.region[:12]:<14} "
                  f"開催回 {schedules}  時間帯 {added:>3}  定員 {capacity:>5}")
            print(f"        開催日 : {dates}")

            for note in venue_notes + venue_slot_notes:
                warnings.append(f"{hospital.code} {hospital.name} — {note}")

        print("-" * 78)
        print(f" 会場 {len(groups)}件 / 開催回 {total_schedules}件 / "
              f"時間帯 {total_slots}枠 取り込み完了")

        if warnings:
            print("\n 確認が必要な項目")
            for line in warnings:
                print(f"   · {line}")

        print("=" * 78)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
