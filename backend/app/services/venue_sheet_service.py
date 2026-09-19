"""회장 관리 표의 파일 입출력 — 그리드 ↔ CSV / Excel.

「회장 관리」 표(`admin_bulk_service.VENUE_COLUMNS`)를 그대로 파일로 내보내고,
파일을 그대로 표로 되돌린다. **한 행이 회장 하나다** — 개최일·정원 열은 없다.
그것은 정원 표(`capacity_sheet_service`)의 일이다.

열은 그리드에서 만든다
----------------------
열 정의를 여기에 다시 적지 않는다. `VENUE_COLUMNS` 에서 파생시킨다.

화면·시트·검증이 각자 열 목록을 갖고 있으면, 열을 하나 늘릴 때 세 곳을
고쳐야 하고 반드시 한 곳을 잊는다. 잊은 곳이 시트면 「화면에는 있는데
내보내면 빠지는 칸」이 생기고, 그것은 담당자가 파일로 왕복하는 동안
**조용히 값이 사라지는** 형태로 나타난다.

그래서 순서까지 그리드를 따른다. 표에서 본 순서 그대로 Excel 이 열리고,
Excel 에서 만든 순서 그대로 표에 붙는다. 회장 코드가 첫 열인 것도, 후리가나가
오른쪽 끝에 있는 것도 화면과 같다.

가져오기는 제목 줄로 맞춘다
--------------------------
열 **순서**가 아니라 **제목**을 보고 붙인다. 그래서 화면의 열 순서를 바꿔도
예전에 내보낸 파일을 그대로 다시 가져올 수 있다. (Ctrl+V 붙여넣기만 순서에
의존한다 — 그쪽은 화면이 안내한다.)
"""

from datetime import datetime
from typing import Any

from app.services.hospital_sheet_service import normalize_code
from app.services.sheet_io import (
    BOOL_TRUE_TEXT,
    MAX_SHEET_ROWS,
    SheetColumn,
    SheetError,
    SheetFormat,
    SheetImport,
)

VenueSheetError = SheetError

SHEET_NAME = "会場"

# 열마다 덧붙일 것 — 원본 마스터의 일본어 열 이름과, 앞자리 0 이 날아가면
# 값이 달라지는 칸 표시. 그리드가 모르는(알 필요도 없는) 파일 쪽 사정이다.
_EXTRA: dict[str, dict] = {
    "code": {
        "zero_sensitive": True,
        "aliases": ("コード", "会場番号", "会場no", "venueno", "id"),
    },
    "name": {"aliases": ("会場名", "会場", "会場名", "hospitalname")},
    "name_kana": {
        "aliases": ("フリガナ", "読み仮名", "よみがな", "フリガナ", "会場名カナ", "namekana"),
    },
    "area": {"aliases": ("地域", "都道府県", "管轄")},
    "city": {"aliases": ("区・市町村", "市区町村", "市郡区", "市町村", "区市町村")},
    "postal_code": {"zero_sensitive": True, "aliases": ("郵便番号", "zip", "zipcode")},
    "address": {"aliases": ("住所",)},
    "transit_info": {"aliases": ("交通情報", "交通", "最寄駅")},
    "access_minutes": {"aliases": ("アクセス時間", "アクセス", "徒歩")},
    "tel": {"zero_sensitive": True, "aliases": ("電話番号", "電話", "tel", "telno")},
    "has_parking": {"aliases": ("駐車場", "駐車")},
    "latitude": {"aliases": ("緯度", "lat")},
    "longitude": {"aliases": ("経度", "lng", "lon")},
    "is_visible": {"aliases": ("表示", "公開", "表示有無")},
    "sort_order": {"aliases": ("順序", "並び順", "sortorder")},
}

# 그리드의 kind 와 시트의 kind 는 뜻이 같다. 그대로 옮긴다.
_KIND = {"bool": "bool", "number": "number", "date": "date", "time": "time"}


def _build_columns() -> tuple[SheetColumn, ...]:
    # 순환 참조를 피하려고 함수 안에서 읽는다
    # (admin_bulk_service 가 이 모듈을 쓰지는 않지만, 앞으로를 위해 한 방향으로 둔다).
    from app.services.admin_bulk_service import VENUE_COLUMNS

    out: list[SheetColumn] = []
    for column in VENUE_COLUMNS:
        extra = _EXTRA.get(column.key, {})
        out.append(
            SheetColumn(
                key=column.key,
                label=column.label,
                # 화면 폭(px)과 Excel 폭(문자 수)은 단위가 다르다. 대충 맞춘다.
                width=max(8, min(48, round(column.width / 7))),
                kind=_KIND.get(getattr(column, "kind", "text") or "text", "text"),
                aliases=tuple(extra.get("aliases", ())),
                zero_sensitive=bool(extra.get("zero_sensitive", False)),
            )
        )
    return tuple(out)


SHEET_COLUMNS = _build_columns()

_GUIDE_LINES: tuple[tuple[str, str], ...] = (
    ("1行 = 1会場",
     "同じ会場コードが2回出現した場合は保存しません。開催日と定員はこの表にはありません — 「定員管理」で行ってください。"),
    ("会場コード", "必須。このコードで既存の会場を検索します。存在しないコードの場合は新規会場として登録します。"),
    ("会場名", "必須。120文字以内。"),
    ("フリガナ",
     "会場名をひらがなで入力してください（例：さんぷるかいかん えー）。管理画面の検索で漢字が分からなくても検索できるようになります。空欄でも構いません。"),
    ("地域・区・市町村",
     "2つを繋ぎ合わせた値が利用者画面の地域表示になります（例: 東京都港区）。絞り込みの軸は地域です。"),
    ("予約画面表示",
     f"「{BOOL_TRUE_TEXT}」/「いいえ」。 ○ × もそのまま読み込みます。「いいえ」の場合は利用者画面から外れますが、既存の予約は残ります。"),
    ("並び順", "利用者画面の会場一覧の順序です。小さい数が上にきます。"),
    ("電話（例外）",
     "空欄にしておくと共通のお問い合わせ先（.env の CONTACT_TEL）を案内します。この会場だけ別の番号を使用する場合のみ入力してください。"),
    ("緯度・経度",
     "10進数（例：35.6584491）。空欄にすると利用者画面の地図が住所検索で表示され、位置が正確でない場合があります。"),
    ("削除", "表にない会場は削除しません。削除は会場管理画面の行メニューからのみ行います。"),
    ("空行", "すべて空欄の行は無視します。途中に空行があっても問題ありません。"),
    ("行数", f"一度に取り込めるデータ行は最大 {MAX_SHEET_ROWS}行です。"),
)

FORMAT = SheetFormat(
    columns=SHEET_COLUMNS,
    sheet_name=SHEET_NAME,
    file_prefix="会場_管理",
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
    # 표에 올리기 **전에** 코드 표기를 맞춘다 (`1` → `V01`). 저장할 때 조용히
    # 바꾸면 사람이 화면에서 본 값과 저장된 값이 달라진다.
    for row in result.rows:
        if "code" in row:
            row["code"] = normalize_code(row["code"])
    return result


def export_file_name(kind: str, moment: datetime) -> str:
    return FORMAT.export_file_name(kind, moment)
