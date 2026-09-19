"""회장 일괄 관리 표의 파일 입출력 — 그리드 ↔ CSV / Excel (A-24).

회장 마스터는 원래 Excel 로 온다
--------------------------------
`data/hospitals/*.xlsx` 의 「会場マスター」가 그것이다. 담당자는 그 파일을
Excel 에서 만들고 고친다. 그런데 관리 화면에서 고치려면 회장 하나마다
모달을 열고 20번 저장해야 했다. **손에 익은 도구와 화면이 어긋나 있었다.**

그래서 우편 접수 일괄 입력(A-13)과 같은 표를 회장 마스터에도 둔다.
지금 등록된 20곳이 표에 그대로 떠 있고, 셀을 고쳐 한 번에 저장한다.
Excel 로 꺼내 고친 뒤 다시 올리는 길도 같다.

원본 마스터를 그대로 올릴 수 있다
--------------------------------
열 별칭에 원본의 일본어 열 이름(`会場名`·`開催日`·`予約終了` …)을 넣어 두었다.
담당자가 받은 파일을 손대지 않고 「가져오기」에 올리면 그대로 표에 붙는다.
`scripts/import_hospitals` 를 서버에서 돌리지 않아도 되는 길이 생긴다.

한 행이 개최 회차 하나다
------------------------
회장 1곳이 여러 날 열기 때문에, **같은 회장 코드가 여러 행에 나온다.**
행을 특정하는 것은 코드가 아니라 「코드 + 개최일」 쌍이다.

    회장 코드  개최일        →  뜻
    ------------------------------------------------
    T01       2026-09-15       T01 이 9/15 에 연다
    T01       2026-10-20       T01 이 10/20 에도 연다

장소 칸(회장명·주소·좌표·교통편)은 같은 회장의 행에서 **전부 같아야 한다.**
한 행만 고치면 저장할 때 「몇 행과 다르다」고 짚어 준다. 조용히 한쪽을
채택하면, 표의 줄 순서를 바꾸는 것만으로 주소가 바뀌기 때문이다.
화면의 「같은 회장에 채우기」 버튼이 나머지 행을 맞춰 준다.
"""

import re
import unicodedata
from datetime import datetime
from typing import Any

from app.services.sheet_io import (
    BOOL_TRUE_TEXT,
    MAX_SHEET_ROWS,
    SheetColumn,
    SheetError,
    SheetFormat,
    SheetImport,
)

HospitalSheetError = SheetError

SHEET_NAME = "会場マスター"

# 「9:30～10:00」 형태의 열 이름 또는 「計」, 「合計」.
SLOT_HEADER = re.compile(r"^(\d{1,2}):(\d{2})[~～－\-](\d{1,2}):(\d{2})$|^(計|合計)$")


# --------------------------------------------------------------------------
# 열 정의
# --------------------------------------------------------------------------
# 화면(`bulk-hospitals.js`)과 주고받는 값은 열 라벨이 아니라 **열 키**다.
# aliases 에는 원본 마스터의 일본어 열 이름을 넣어 두어, 담당자가 받은
# 파일을 고치지 않고 그대로 올릴 수 있게 한다.
SHEET_COLUMNS: tuple[SheetColumn, ...] = (
    SheetColumn("code", "会場コード", 12, zero_sensitive=True,
                aliases=("コード", "会場番号", "会場no", "venueno", "id")),
    SheetColumn("name", "会場名", 30, aliases=("会場名", "会場", "hospitalname")),
    SheetColumn("area", "地域", 14, aliases=("地域", "都道府県", "所管")),
    SheetColumn("city", "区・市町村", 16, aliases=("市区町村", "市区郡", "市町村", "区市町村")),
    SheetColumn("postal_code", "郵便番号", 12, zero_sensitive=True,
                aliases=("郵便番号", "zip", "zipcode")),
    SheetColumn("address", "住所", 36, aliases=("住所",)),
    SheetColumn("transit_info", "交通情報", 34, aliases=("交通情報", "交通", "最寄り駅")),
    SheetColumn("access_minutes", "所要時間", 14, aliases=("アクセス時間", "アクセス", "徒歩")),
    SheetColumn("event_date", "開催日", 14, kind="date", aliases=("開催日", "受診日", "eventdate")),
    SheetColumn("booking_close_date", "受付締切日", 14, kind="date",
                aliases=("予約終了", "予約締切", "締切日", "bookingclosedate")),
    SheetColumn("open_time", "開始時刻", 12, kind="time", aliases=("開始時刻", "開始時間", "opentime")),
    SheetColumn("reception_end_time", "受付終了時刻", 14, kind="time",
                aliases=("受付終了", "受付終了時刻", "receptionendtime")),
    SheetColumn("schedule_note", "開催回メモ", 20,
                aliases=("備考", "メモ", "note", "schedulenote")),
    SheetColumn("has_parking", "駐車場", 10, kind="bool", aliases=("駐車場", "parking")),
    SheetColumn("latitude", "緯度", 12, kind="number", aliases=("緯度", "lat")),
    SheetColumn("longitude", "経度", 12, kind="number", aliases=("経度", "lng", "lon")),
    SheetColumn("tel", "電話（例外）", 16, zero_sensitive=True,
                aliases=("電話", "電話番号", "tel")),
    SheetColumn("is_visible", "予約画面表示", 14, kind="bool",
                aliases=("表示", "公開", "isvisible")),
    SheetColumn("sort_order", "並び順", 12, kind="number", aliases=("順序", "ソート", "sortorder")),
)

COLUMN_KEYS: tuple[str, ...] = tuple(column.key for column in SHEET_COLUMNS)

_GUIDE_LINES: tuple[tuple[str, str], ...] = (
    ("1行 = 開催回1つ",
     "1つの会場で複数日開催する場合、その分行数が増えます。同じ会場コードが複数回出現しても問題ありません。"),
    ("会場コード", "必須。このコードで既存の会場を探します。ないコードなら新しい会場として登録します。コードは重複してもかまいません。"),
    ("開催日", "開催回を特定する欄です。「会場コード + 開催日」が同じ行が2回あると保存しません。空欄にしておくと会場のみ登録し、開催回は作成しません。"),
    ("会場名・住所・座標・交通手段",
     "場所情報です。同じ会場の行ではすべて同じでなければなりません。1行だけ直すと「何行目と違う」とお知らせします。"),
    ("地域・区・市町村", "2つを繋ぎ合わせた値が利用者画面の地域表示になります（例: 東京都港区）。絞り込みの軸は地域です。"),
    ("受付締切日", "YYYY-MM-DD. この日が過ぎるとその **開催回**が利用者画面から外れます。同じ会場の別の日付はそのまま残ります。"),
    ("開始時刻・受付終了時刻", "HH:MM (例: 09:30)。開催回ごとに異なる場合があります — 午前のみ開催する日があります。"),
    ("開催回メモ", "「午前のみ開催」のようにその日のみに該当するメモです。空欄でもかまいません。"),
    ("駐車場・予約画面表示", f"「{BOOL_TRUE_TEXT}」/「いいえ」。 ○ × もそのまま読み込みます。"),
    ("緯度・経度", "10進数（例: 35.6584491）。空欄でもかまいません。"),
    ("電話（例外）", "空欄にしておくと共通のお問い合わせ先（.env の CONTACT_TEL）を案内します。この会場だけ別の番号を使用する場合のみ入力してください。"),
    ("時間帯別定員",
     "「9:30~10:00」のような列を付けるとその開催回のタイムテーブルになります。予約が入ったスロットは予約数より下には減りません。"),
    ("削除", "表にない会場・開催回は削除しません。削除は会場管理画面からのみ行います。"),
    ("空行", "すべて空欄の行は無視します。途中に空行があっても問題ありません。"),
    ("行数", f"一度に取り込めるデータ行は最大 {MAX_SHEET_ROWS}行です。"),
)

FORMAT = SheetFormat(
    columns=SHEET_COLUMNS,
    sheet_name=SHEET_NAME,
    file_prefix="会場マスター_一括管理",
    guide_lines=_GUIDE_LINES,
    dynamic_column_pattern=SLOT_HEADER,
)


def normalize_code(value: str) -> str:
    """회장 코드를 하나의 표기로 맞춘다. 번호만 있으면 `V01` 형태로.

    원본 마스터의 `会場番号` 는 `1`, `2` … 처럼 번호뿐이다. 그대로 두면
    `scripts/import_hospitals` 가 넣은 `V01` 과 **다른 코드**가 되어, 받은
    마스터를 그대로 올리는 순간 같은 회장이 20곳 더 생긴다. 담당자가 가장
    먼저 할 법한 일이 그것이므로 여기서 맞춰 둔다.

    이미 문자가 섞인 코드는 손대지 않는다.

    >>> normalize_code("1")
    'V01'
    >>> normalize_code("V07")
    'V07'
    >>> normalize_code("")
    ''
    """
    text = unicodedata.normalize("NFKC", (value or "").strip())
    if not text:
        return ""
    if re.fullmatch(r"\d{1,3}", text):
        return f"V{int(text):02d}"
    return text


def _normalize_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    for row in rows:
        if "code" in row:
            row["code"] = normalize_code(row["code"])
            
        # 시간대 키를 HH:MM~HH:MM 형식으로 정규화 (예: 9:30~10:00 -> 09:30~10:00)
        keys = list(row.keys())
        for key in keys:
            matched = SLOT_HEADER.match(key)
            if matched and matched.group(1):
                norm_key = f"{int(matched.group(1)):02d}:{int(matched.group(2)):02d}～{int(matched.group(3)):02d}:{int(matched.group(4)):02d}"
                if norm_key != key:
                    row[norm_key] = row.pop(key)
    return rows


def empty_row() -> dict[str, str]:
    return FORMAT.empty_row()


def normalize_export_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """会場マスター表を書き出し用に整える。時間帯の定員列も一緒に載せる。

    `FORMAT.normalize_export_rows` は**空行を捨てる**ので、その戻り値を
    元の `rows` と同じ番号で引くことはできない。以前はそうしていたため、
    前の行が空だと `IndexError` で 500 になり、落ちない組み合わせでは
    定員が別の会場の行に付くという、より気付きにくい壊れ方をしていた。
    そこで、空行を捨てる判定と時間帯列の取り込みを**同じ一巡**で行う。
    """
    cleaned: list[dict[str, str]] = []
    for raw in rows:
        row = {key: FORMAT.export_text(raw.get(key)) for key in FORMAT.keys}
        for key, value in raw.items():
            if SLOT_HEADER.match(key) and value is not None and value != "":
                row[key] = str(value)
        # 定義済みの列も時間帯列もすべて空なら、その行は書き出さない。
        if any(row.values()):
            cleaned.append(row)
    return cleaned


def build_csv(rows: list[dict[str, str]]) -> bytes:
    return FORMAT.build_csv(rows)


def build_xlsx(rows: list[dict[str, str]]) -> bytes:
    return FORMAT.build_xlsx(rows)


def parse_upload(file_name: str, raw: bytes) -> SheetImport:
    result = FORMAT.parse_upload(file_name, raw)
    # 표에 올리기 **전에** 코드 표기를 맞춘다. 저장할 때 조용히 바꾸면
    # 사람이 화면에서 본 값과 저장된 값이 달라진다.
    _normalize_rows(result.rows)
    return result


def export_file_name(kind: str, moment: datetime) -> str:
    return FORMAT.export_file_name(kind, moment)
