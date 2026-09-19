"""우편 접수 일괄 입력 표의 파일 입출력 — 그리드 ↔ CSV / Excel (A-13).

그리드에 붙여 넣는 것만으로 끝나지 않는 경우가 있다.

  · Excel 로 1차 타이핑해 둔 것을 그대로 올리고 싶다
  · 200행을 다 채우지 못한 채 하루가 끝나면 파일로 들고 나가야 한다
  · 회장이 이미 쓰는 사내 서식을 그대로 받고 싶다

**열의 정의는 이 모듈 한 곳에만 둔다.** 화면(`bulk-postal.js`)과 주고받는 값은
열 라벨이 아니라 `last_name` 같은 **열 키**다. 라벨을 계약으로 삼으면
「제1희망 회장」의 표기를 다듬는 순간 어제 내보낸 파일을 못 읽게 된다.

파일을 읽고 쓰는 일 자체는 `sheet_io.SheetFormat` 이 한다. 제목 줄 인식,
CP932 판정, 수식 인젝션 방어 같은 것은 회장 일괄 관리(A-24)와 완전히 같아서
한 곳에 모아 두었다. 여기 남은 것은 **이 화면의 열이 무엇인가**뿐이다.

업무 규칙은 여기서 검증하지 않는다. 형식이 틀린 셀도 그대로 그리드에 올려
사람이 보고 고치게 한다. 판정은 `admin_reservation_service` 의 일괄 검증
한 곳에서만 한다.
"""

from datetime import datetime
from typing import Any

from app.services.sheet_io import (
    BOOL_TRUE_TEXT,
    HEADER_SCAN_ROWS,
    MAX_CELL_LENGTH,
    MAX_SHEET_ROWS,
    MAX_UPLOAD_BYTES,
    SheetColumn,
    SheetError,
    SheetFormat,
    SheetImport,
    normalize_header,
)

__all__ = [
    "PostalSheetError",
    "SheetImport",
    "SHEET_COLUMNS",
    "COLUMN_KEYS",
    "MAX_SHEET_ROWS",
    "MAX_UPLOAD_BYTES",
    "MAX_CELL_LENGTH",
    "HEADER_SCAN_ROWS",
    "SHEET_NAME",
    "empty_row",
    "normalize_export_rows",
    "build_csv",
    "build_xlsx",
    "parse_upload",
    "export_file_name",
]

# 이 모듈을 쓰는 쪽(API·테스트)이 잡던 예외 이름을 그대로 둔다.
PostalSheetError = SheetError

SHEET_NAME = "郵送受付"


# --------------------------------------------------------------------------
# 열 정의
# --------------------------------------------------------------------------
# label 은 **파일의 제목 줄에 쓰는 이름**이고 서로 겹치면 안 된다.
# 그리드의 열 이름은 그룹 머리(제1희망 …)가 따로 있어 「회장 코드/명」처럼
# 짧지만, 파일에는 그룹 머리가 없으므로 전부 풀어 쓴다.
#
# aliases 에는 회장이 실제로 쓸 만한 표기를 넣어 둔다. 여기에 한 줄
# 추가하는 것이 스태프에게 「열 이름을 고쳐서 다시 올려 주세요」라고
# 말하는 것보다 언제나 싸다.
SHEET_COLUMNS: tuple[SheetColumn, ...] = (
    SheetColumn("last_name", "姓", 12, aliases=("姓(漢字)", "姓", "氏名(姓)", "lastname")),
    SheetColumn("first_name", "名", 12, aliases=("名(漢字)", "名", "氏名(名)", "firstname")),
    SheetColumn("last_name_kana", "姓フリガナ", 16, aliases=("セイ", "フリガナ(姓)", "姓カナ")),
    SheetColumn("first_name_kana", "名フリガナ", 16, aliases=("メイ", "フリガナ(名)", "名カナ")),
    SheetColumn("middle_name", "ミドルネーム", 14, aliases=("ミドルネーム", "middlename")),
    SheetColumn("middle_name_kana", "ミドルネームカナ", 18, aliases=("ミドルネームカナ",)),
    SheetColumn("gender", "性別", 8, aliases=("性別", "sex")),
    SheetColumn("birth_date", "生年月日", 14, kind="date", aliases=("生年月日", "birthdate", "dob")),
    SheetColumn("insurer_no", "保険者番号", 14, zero_sensitive=True, aliases=("保険者番号", "insurerno")),
    SheetColumn("insurance_symbol", "保険証記号", 14, zero_sensitive=True, aliases=("記号", "保険証記号", "insurancesymbol")),
    SheetColumn("insurance_no", "保険証番号", 14, zero_sensitive=True, aliases=("保険証番号", "insuranceno")),
    SheetColumn("postal_code", "郵便番号", 12, zero_sensitive=True, aliases=("郵便番号", "zip", "zipcode", "postalcode")),
    SheetColumn("address", "住所", 34, aliases=("住所",)),
    SheetColumn("address_detail", "番地", 18, aliases=("番地", "addressdetail")),
    SheetColumn("building", "アパート・マンション名", 22, aliases=("建物名", "マンション名")),
    SheetColumn("tel_mobile", "携帯電話", 16, zero_sensitive=True, aliases=("携帯電話", "携帯", "mobile", "telmobile")),
    SheetColumn("tel_home", "固定電話", 16, zero_sensitive=True, aliases=("固定電話", "自宅電話", "telhome")),
    SheetColumn("email", "メールアドレス", 26, aliases=("メール", "メールアドレス", "mail")),
    SheetColumn("wish1_hospital", "第1希望会場", 22, aliases=("第1希望病院", "第1希望会場", "会場1", "wish1hospital")),
    SheetColumn("wish1_date", "第1希望受診日", 16, kind="date", aliases=("第1希望日", "受診日1", "wish1date")),
    SheetColumn("wish1_time", "第1希望開始時間", 16, kind="time", aliases=("第1希望時間", "時間1", "wish1time")),
    SheetColumn("wish2_hospital", "第2希望会場", 22, aliases=("第2希望病院", "第2希望会場", "会場2", "wish2hospital")),
    SheetColumn("wish2_date", "第2希望受診日", 16, kind="date", aliases=("第2希望日", "受診日2", "wish2date")),
    SheetColumn("wish2_time", "第2希望開始時間", 16, kind="time", aliases=("第2希望時間", "時間2", "wish2time")),
    SheetColumn("wish3_hospital", "第3希望会場", 22, aliases=("第3希望病院", "第3希望会場", "会場3", "wish3hospital")),
    SheetColumn("wish3_date", "第3希望受診日", 16, kind="date", aliases=("第3希望日", "受診日3", "wish3date")),
    SheetColumn("wish3_time", "第3希望開始時間", 16, kind="time", aliases=("第3希望時間", "時間3", "wish3time")),
    SheetColumn("option_codes", "オプションコード", 20, multi=True, aliases=("オプション", "optioncodes", "options")),
    SheetColumn("allow_defect", "不備許容", 10, kind="bool", aliases=("不備", "allowdefect")),
    SheetColumn("memo", "スタッフメモ", 30, aliases=("メモ", "備考")),
)

COLUMN_KEYS: tuple[str, ...] = tuple(column.key for column in SHEET_COLUMNS)

_GUIDE_LINES: tuple[tuple[str, str], ...] = (
    ("姓・名", "必須です。漢字表記をそのまま入力してください。"),
    ("性別", "M またはF。男/女、男性/女性もそのまま読み取ります。"),
    ("生年月日", "YYYY-MM-DD (例: 1970-04-02)。YYYY/MM/DDも読み取ります。"),
    ("第N希望会場", "会場コードまたは正確な会場名。同名が複数ある場合はコードで入力してください。"),
    ("第N希望受診日", "YYYY-MM-DD. 第1希望は必須、第2・第3希望は空欄でも構いません。"),
    ("第N希望開始時間", "HH:MM (例: 09:30)。予約枠の開始時間と完全に一致している必要があります。"),
    ("オプションコード", "複数はセミコロンで区切ります（例: OP01;OP03）。"),
    ("不備許容", f"「{BOOL_TRUE_TEXT}」を入力すると、必須項目が空欄でも仮受付（PENDING）として登録します。"),
    ("空行", "すべて空欄の行は無視します。途中に空行があっても問題ありません。"),
    ("行数", f"一度に取り込めるデータ行は最大 {MAX_SHEET_ROWS}行です。"),
)

FORMAT = SheetFormat(
    columns=SHEET_COLUMNS,
    sheet_name=SHEET_NAME,
    file_prefix="郵送受付_一括入力",
    guide_lines=_GUIDE_LINES,
)

# 제목 줄 대조표. 열 이름이 겹치지 않는지 검사하는 쪽(`scripts/postal_sheet_test`)이
# 들여다본다. 대조 자체는 `FORMAT` 이 한다.
_normalize_header = normalize_header
_ALIAS_TO_KEY: dict[str, str] = dict(FORMAT.alias_to_key)


# --------------------------------------------------------------------------
# 공개 API — 이 화면이 부르던 이름을 그대로 유지한다
# --------------------------------------------------------------------------


def empty_row() -> dict[str, str]:
    return FORMAT.empty_row()


def normalize_export_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    return FORMAT.normalize_export_rows(rows)


def build_csv(rows: list[dict[str, str]]) -> bytes:
    return FORMAT.build_csv(rows)


def build_xlsx(rows: list[dict[str, str]]) -> bytes:
    return FORMAT.build_xlsx(rows)


def parse_upload(file_name: str, raw: bytes) -> SheetImport:
    return FORMAT.parse_upload(file_name, raw)


def export_file_name(kind: str, moment: datetime) -> str:
    return FORMAT.export_file_name(kind, moment)
