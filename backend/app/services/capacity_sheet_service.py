"""정원 관리 표의 파일 입출력 — 그리드 ↔ CSV / Excel.

「정원 관리」 표(`admin_bulk_service.capacity_columns()`)를 그대로 파일로
내보내고, 파일을 그대로 표로 되돌린다. **한 행이 개최 회차 하나다.**

시간대 열은 격자에서 만든다
--------------------------
`09:30~10:00` … `16:30~17:00` 열을 여기에 적어 두지 않는다.
`app/core/time_grid.py` 가 격자를 아는 **유일한 곳**이고, 시트도 그것을
따른다. 격자를 넓히면 화면·표·파일이 함께 넓어진다.

회장은 읽기 전용이다
--------------------
회장 코드·회장명 열이 있지만 이 표에서 회장을 만들지는 못한다. 코드로
기존 회장을 **찾을 뿐**이고, 없는 코드면 그 행은 저장되지 않는다.
장소를 만드는 것은 「회장 관리」의 일이다.

회장명 열을 굳이 넣는 이유는, 코드만 있는 파일은 사람이 읽을 수 없기
때문이다. 내보낼 때는 채워 주고, 가져올 때는 참고만 하고 버린다.
"""

from datetime import datetime
from typing import Any

from app.core import time_grid
from app.services.hospital_sheet_service import normalize_code
from app.services.sheet_io import (
    BOOL_TRUE_TEXT,
    MAX_SHEET_ROWS,
    SheetColumn,
    SheetError,
    SheetFormat,
    SheetImport,
)

CapacitySheetError = SheetError

SHEET_NAME = "定員"

# 회차를 특정하는 칸 + 회차의 속성. 시간대 열은 아래에서 격자로 붙인다.
_FIXED_COLUMNS: tuple[SheetColumn, ...] = (
    SheetColumn("hospital_code", "会場コード", 12, zero_sensitive=True,
                aliases=("コード", "会場番号", "会場no", "venueno")),
    SheetColumn("hospital_name", "会場名", 26,
                aliases=("会場名", "会場", "hospitalname")),
    SheetColumn("event_date", "開催日", 14, kind="date",
                aliases=("開催日", "受診日", "eventdate")),
    SheetColumn("booking_close_date", "受付締切日", 14, kind="date",
                aliases=("予約終了", "予約締切", "締切日", "bookingclosedate")),
    SheetColumn("open_time", "開始", 10, kind="time",
                aliases=("開始時刻", "開始時間", "opentime")),
    SheetColumn("reception_end_time", "受付終了", 12, kind="time",
                aliases=("受付終了", "受付終了時刻", "receptionendtime")),
    SheetColumn("note", "開催回メモ", 20, aliases=("メモ", "備考")),
    SheetColumn("is_visible", "表示", 8, kind="bool",
                aliases=("公開", "表示有無")),
)


def _slot_columns() -> tuple[SheetColumn, ...]:
    out = []
    for index in time_grid.indexes():
        start, end = time_grid.TIME_GRID[index]
        s1 = f"{start.hour:02d}:{start.minute:02d}～{end.hour:02d}:{end.minute:02d}"
        s2 = f"{start.hour}:{start.minute:02d}～{end.hour:02d}:{end.minute:02d}"
        s3 = f"{start.hour:02d}:{start.minute:02d}~{end.hour:02d}:{end.minute:02d}"
        s4 = f"{start.hour}:{start.minute:02d}~{end.hour:02d}:{end.minute:02d}"
        out.append(
            SheetColumn(
                key=time_grid.sheet_key(index),
                label=time_grid.label(index),
                width=12,
                kind="number",
                aliases=(s1, s2, s3, s4),
            )
        )
    return tuple(out)


SHEET_COLUMNS: tuple[SheetColumn, ...] = _FIXED_COLUMNS + _slot_columns()

_GUIDE_LINES: tuple[tuple[str, str], ...] = (
    ("1行 = 開催回1つ",
     "1つの会場で複数日開催する場合、その分行数が増えます。同じ会場コードが複数回出現しても問題ありません。"),
    ("会場コード + 開催日",
     "この2つで開催回を特定します。同じ組み合わせが重複している場合は保存されません。"),
    ("存在しない会場コード",
     "この表では会場を作成しません。先に「会場管理」で会場を登録してください。"),
    ("会場名", "読みやすくするために入力されている項目です。取り込み時は会場コードのみを参照します。"),
    ("受付締切日",
     "YYYY-MM-DD. この日を過ぎると、その開催回は利用者画面に表示されなくなります。同じ会場の別日程はそのまま残ります。"),
    ("開始・受付終了", "HH:MM (例: 09:30)。開催回ごとに異なる場合があります — 午前のみ開催する日があります。"),
    ("表示", f"「{BOOL_TRUE_TEXT}」/「いいえ」。 ○ × もそのまま読み取ります。"),
    ("時間帯別定員",
     "その時間帯に受け入れ可能な人数です。 **空欄は「その時間帯の受付なし」であり、0とは異なります** — 0 は枠はあるものの満員という意味です。"),
    ("すでに入っている予約",
     "予約が入っている時間帯を、予約数未満の定員に減らすことはできません。該当するセルは予約数までしか下がりません。"),
    ("削除", "表にない開催回は削除しません。"),
    ("空行", "すべて空欄の行は無視します。途中に空行があっても問題ありません。"),
    ("行数", f"一度に取り込めるデータ行は最大 {MAX_SHEET_ROWS}行です。"),
)

FORMAT = SheetFormat(
    columns=SHEET_COLUMNS,
    sheet_name=SHEET_NAME,
    file_prefix="定員_管理",
    guide_lines=_GUIDE_LINES,
)


def empty_row() -> dict[str, str]:
    return FORMAT.empty_row()


def normalize_export_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    return FORMAT.normalize_export_rows(rows)


def build_csv(rows: list[dict[str, str]]) -> bytes:
    return FORMAT.build_csv(rows)


def build_xlsx(rows: list[dict[str, str]]) -> bytes:
    return FORMAT.build_xlsx(rows)


def parse_upload(file_name: str, raw: bytes) -> SheetImport:
    result = FORMAT.parse_upload(file_name, raw)
    for row in result.rows:
        if "hospital_code" in row:
            row["hospital_code"] = normalize_code(row["hospital_code"])
    return result


def export_file_name(kind: str, moment: datetime) -> str:
    return FORMAT.export_file_name(kind, moment)
