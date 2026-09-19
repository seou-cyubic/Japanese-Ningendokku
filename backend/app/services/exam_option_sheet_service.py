"""옵션 검사 표의 파일 입출력 — 그리드 ↔ CSV / Excel.

열은 그리드(`admin_bulk_service.EXAM_OPTION_COLUMNS`)에서 만든다.
이유는 `venue_sheet_service` 와 같다 — 열 목록이 두 곳에 있으면 하나를 늘릴
때 반드시 한 곳을 잊고, 잊은 곳이 시트면 파일로 왕복하는 동안 값이 조용히
사라진다.

예전 CSV 와의 관계
------------------
예전에는 `admin_master_service.export_exam_options` / `import_exam_options` 가
csv 모듈을 직접 다뤘다. 그래서 `sheet_io` 가 이미 갖고 있던 것들을 못 받고
있었다 — 일본어 Excel 의 CP932, 한국어 Windows 의 CP949, 수식 인젝션 방어,
Excel 의 숫자 셀이 `1010021.0` 으로 넘어오는 문제, 제목 줄 자동 탐색.

그 두 함수는 이 모듈로 대체되었다.

타깃 성별은 「말」로 담는다
--------------------------
파일에는 `F` 가 아니라 `여성만` 이 적힌다. 담당자가 Excel 에서 읽고 고치는
파일이고, `F` 가 여성인지 거짓(false)인지 매번 헷갈리기 때문이다.
읽을 때는 둘 다 받는다 (`admin_bulk_service.parse_gender`).
"""

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

ExamOptionSheetError = SheetError

SHEET_NAME = "オプション検査"

_EXTRA: dict[str, dict] = {
    "code": {"zero_sensitive": True, "aliases": ("検査コード", "option_code", "optioncode")},
    "name": {"aliases": ("検査名", "オプション名", "検査名")},
    "is_active": {"aliases": ("有効", "使用可否", "アクティブ", "active", "予約画面に表示")},
    "sort_order": {"aliases": ("並び順", "並び順", "順序", "sortorder")},
    "target_gender": {"aliases": ("ターゲット性別", "性別", "対象性別", "gender")},
    "target_age_min": {"aliases": ("最小年齢", "最小年齢", "対象年齢下限", "agemin")},
    "target_age_max": {"aliases": ("最大年齢", "最大年齢", "対象年齢上限", "agemax")},
    "description": {"aliases": ("説明", "案内", "説明")},
    "note": {"aliases": ("準備事項", "準備事項", "注意事項", "備考")},
}

_KIND = {"bool": "bool", "number": "number", "date": "date", "time": "time"}


def _build_columns() -> tuple[SheetColumn, ...]:
    from app.services.admin_bulk_service import EXAM_OPTION_COLUMNS

    out: list[SheetColumn] = []
    for column in EXAM_OPTION_COLUMNS:
        extra = _EXTRA.get(column.key, {})
        out.append(
            SheetColumn(
                key=column.key,
                label=column.label,
                width=max(8, min(48, round(column.width / 7))),
                # enum 은 파일에서 그냥 글자다. 코드로 되돌리는 것은 저장할 때
                # `parse_gender` 가 한다 — 판정을 한 곳에 둔다.
                kind=_KIND.get(getattr(column, "kind", "text") or "text", "text"),
                aliases=tuple(extra.get("aliases", ())),
                zero_sensitive=bool(extra.get("zero_sensitive", False)),
            )
        )
    return tuple(out)


SHEET_COLUMNS = _build_columns()

_GUIDE_LINES: tuple[tuple[str, str], ...] = (
    ("1行 = オプション検査1つ", "同じコードが2回出た場合は保存しません。"),
    ("コード", "必須。このコードで既存の検査を探します。ないコードなら新しい検査として登録します。"),
    ("検査名", "必須。120文字以内。"),
    ("予約画面に表示",
     f"「{BOOL_TRUE_TEXT}」/「いいえ」。「いいえ」なら予約画面に表示されず、新しい申し込みを受け付けません。すでに申し込まれた予約はそのまま残ります。"),
    ("ターゲット性別",
     "「全員」・「男性のみ」・「女性のみ」。ALL/M/Fと書いても読み込みます。空欄なら「全員」です。"),
    ("最小・最大年齢",
     "満年齢です。条件に合わない方には利用者画面でこの検査が一切見えません — 薄く表示されることもありません。"),
    ("説明", "利用者画面にそのままお見せする案内文です。"),
    ("準備事項", "絶食などの注意事項です。255文字以内。"),
    ("費用", "ここに金額欄はありません。健診当日に会場で支払います。"),
    ("削除", "表にない検査は削除しません。削除は表の行メニューからのみ行います。"),
    ("空行", "すべて空行は無視します。"),
    ("行数", f"一度に取り込めるデータ行は最大 {MAX_SHEET_ROWS}件です。"),
)

FORMAT = SheetFormat(
    columns=SHEET_COLUMNS,
    sheet_name=SHEET_NAME,
    file_prefix="オプション検査_管理",
    guide_lines=_GUIDE_LINES,
)


def empty_row() -> dict[str, str]:
    return FORMAT.empty_row()


def normalize_export_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """내보낼 때 성별을 코드에서 말로 바꾼다.

    화면은 이미 말로 보내지만, 다른 곳에서 코드째로 넘어올 수 있다.
    파일에 `F` 가 찍히면 담당자가 그것을 고치다 틀린다.
    """
    from app.services.admin_bulk_service import GENDER_CHOICES

    labels = {value: label for value, label in GENDER_CHOICES}

    cleaned = FORMAT.normalize_export_rows(rows)
    for row in cleaned:
        gender = row.get("target_gender", "")
        if gender in labels:
            row["target_gender"] = labels[gender]
    return cleaned


def build_csv(rows: list[dict[str, str]]) -> bytes:
    return FORMAT.build_csv(rows)


def build_xlsx(rows: list[dict[str, str]]) -> bytes:
    return FORMAT.build_xlsx(rows)


def parse_upload(file_name: str, raw: bytes) -> SheetImport:
    """파일을 표로. 성별은 표에 올릴 때 **코드로** 되돌린다.

    화면의 표는 코드를 담고 말을 보여 준다. 여기서 코드로 맞춰 두지 않으면
    가져온 행만 셀 안에 날것의 글자가 남아, 「변경함」 판정이 어긋난다.
    """
    from app.services.admin_bulk_service import parse_gender

    result = FORMAT.parse_upload(file_name, raw)
    for row in result.rows:
        raw_gender = row.get("target_gender", "")
        if not raw_gender:
            continue
        parsed = parse_gender(raw_gender)
        # 알아볼 수 없는 값은 **그대로 둔다.** 조용히 「전체」로 바꾸면
        # 오타가 조건 완화로 둔갑한다. 저장할 때 그 셀을 짚어 준다.
        if parsed:
            row["target_gender"] = parsed
    return result


def export_file_name(kind: str, moment: datetime) -> str:
    return FORMAT.export_file_name(kind, moment)
