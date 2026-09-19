"""우편 접수 일괄 입력 표의 파일 입출력 검증 (CSV · Excel).

    python -m scripts.postal_sheet_test

**DB 도 서버도 필요하지 않다.** `postal_sheet_service` 는 순수 변환 계층이므로
파일 왕복만으로 전부 확인할 수 있다. 그래서 스키마를 고친 직후, 서버를 띄우기
전에 바로 돌려 볼 수 있다.

무엇을 지키려는 시험인가

  · **왕복 안정성** — 내보낸 파일을 다시 가져오면 값이 그대로여야 한다.
    한 칸이라도 달라지면 「Excel 로 꺼내서 고치고 되돌리기」가 성립하지 않는다.
  · **Excel 이 값을 바꾸는 것** — 날짜 셀·숫자 셀·수식으로 보이는 문자열은
    Excel 을 거치면 모습이 바뀐다. 그 셋을 실제로 만들어 확인한다.
  · **거절해야 하는 것** — 서식을 추측해서 열을 잘못 붙이면 성과 이름이,
    우편번호와 전화번호가 뒤바뀐 예약이 조용히 만들어진다. 애매하면 거절한다.
"""

import scripts._console  # noqa: F401  (콘솔 UTF-8 보정)
import io
import sys
from datetime import date, datetime, time

from app.services import postal_sheet_service as sheet
from app.services.postal_sheet_service import PostalSheetError
from app.services.sheet_io import BOOL_TRUE_TEXT

PASS = "  [OK]  "
FAIL = "  [FAIL]"

_failures = 0


def check(title: str, ok: bool, detail: object = "") -> None:
    global _failures
    print(f"{PASS if ok else FAIL} {title}")
    if not ok:
        _failures += 1
        if detail != "":
            print(f"         {detail}")


def section(title: str) -> None:
    print("-" * 66)
    print(f" {title}")
    print("-" * 66)


def row(**values: str) -> dict[str, str]:
    """열 키로 한 행을 만든다. 적지 않은 열은 빈 칸."""
    base = sheet.empty_row()
    base.update(values)
    return base


# ==========================================================================
# 시험 데이터
# ==========================================================================

ROWS = [
    row(
        last_name="田中", first_name="太郎",
        last_name_kana="タナカ", first_name_kana="タロウ",
        gender="M", birth_date="1970-04-02",
        insurer_no="0000", insurance_symbol="ABCD", insurance_no="0001",
        postal_code="101-0021", address="東京都千代田区外神田",
        address_detail="1-2-3", building="みらいビル 5F",
        tel_mobile="090-1234-5678", email="tanaka@example.jp",
        wish1_hospital="H001", wish1_date="2026-08-12", wish1_time="09:00",
        wish2_hospital="サンプル中央病院", wish2_date="2026-08-13", wish2_time="10:30",
        option_codes="OPT01;OPT03", memo="글씨 판독 어려움",
    ),
    row(
        last_name="佐藤", first_name="花子", gender="여", birth_date="1965-11-30",
        wish1_hospital="H002", wish1_date="2026-09-01", wish1_time="14:00",
        allow_defect="예", memo='쉼표, 따옴표" 섞임',
    ),
    row(
        # Excel 이 수식으로 실행해 버릴 수 있는 값. 그대로 살아 돌아와야 한다.
        last_name="=SUM(A1)", first_name="太郎", gender="M", birth_date="1980-01-01",
        wish1_hospital="H003", wish1_date="2026-10-01", wish1_time="09:30",
    ),
]


def diff(left: list[dict[str, str]], right: list[dict[str, str]]) -> list[tuple]:
    if len(left) != len(right):
        return [("행 수", len(left), len(right))]
    return [
        (index + 1, key, left[index][key], right[index][key])
        for index in range(len(left))
        for key in sheet.COLUMN_KEYS
        if left[index][key] != right[index][key]
    ]


def main() -> int:
    print("=" * 66)
    print(" 우편 접수 일괄 입력 — 표 파일 입출력 검증")
    print("=" * 66)

    section("① 열 정의")
    labels = [column.label for column in sheet.SHEET_COLUMNS]
    keys = [column.key for column in sheet.SHEET_COLUMNS]
    check("열 키가 유일하다", len(set(keys)) == len(keys))
    check(
        "제목 줄 이름이 유일하다 (겹치면 가져올 때 열을 못 가른다)",
        len(set(labels)) == len(labels),
        [label for label in labels if labels.count(label) > 1],
    )
    check(
        "모든 라벨·별칭이 제 열로 되돌아온다",
        all(
            sheet._ALIAS_TO_KEY.get(sheet._normalize_header(column.label)) == column.key
            for column in sheet.SHEET_COLUMNS
        ),
    )

    rows = sheet.normalize_export_rows(ROWS + [sheet.empty_row()])
    check("완전히 빈 행은 내보내지 않는다", len(rows) == len(ROWS), len(rows))

    section("② CSV 왕복")
    csv_bytes = sheet.build_csv(rows)
    check(
        "UTF-8 BOM 을 붙인다 (없으면 일본어 Excel 이 깨진 채로 연다)",
        csv_bytes[:3] == b"\xef\xbb\xbf",
    )
    check("수식으로 보이는 셀을 따옴표로 막는다", b"'=SUM" in csv_bytes)

    got = sheet.parse_upload("표.csv", csv_bytes)
    check("인코딩을 UTF-8 로 판정한다", got.encoding.startswith("UTF-8"), got.encoding)
    check("제목 줄을 찾는다", got.header_mode == "HEADER")
    check("열 30개가 모두 붙는다", got.matched_columns == len(sheet.SHEET_COLUMNS),
          got.matched_columns)
    check("값이 그대로 돌아온다", not diff(rows, got.rows), diff(rows, got.rows))

    twice = sheet.parse_upload("표.csv", sheet.build_csv(got.rows))
    check(
        "두 번 왕복해도 안정적이다 (따옴표가 쌓이지 않는다)",
        not diff(rows, twice.rows),
        diff(rows, twice.rows),
    )

    section("③ Excel 왕복")
    xlsx_bytes = sheet.build_xlsx(rows)
    check("xlsx 로 저장된다", xlsx_bytes[:4] == b"PK\x03\x04")
    got_x = sheet.parse_upload("표.xlsx", xlsx_bytes)
    check("데이터 시트를 고른다", got_x.sheet_name == sheet.SHEET_NAME, got_x.sheet_name)
    check("값이 그대로 돌아온다", not diff(rows, got_x.rows), diff(rows, got_x.rows))
    check("CSV 와 결과가 같다", got_x.rows == got.rows, diff(got.rows, got_x.rows))

    section("④ 빈 서식")
    empty_csv = sheet.build_csv([])
    check(
        "행이 없으면 제목 줄만 나온다",
        empty_csv.decode("utf-8-sig").strip().count("\n") == 0,
    )
    try:
        sheet.parse_upload("빈서식.xlsx", sheet.build_xlsx([]))
        check("내용이 없는 파일은 거절한다", False, "예외가 나지 않았다")
    except PostalSheetError as exc:
        check("내용이 없는 파일은 거절한다", "データ行がありません" in str(exc), exc)

    section("⑤ 회장이 쓰는 다른 서식 (CP932 · 일본어 열 이름 · 표 위 제목)")
    japanese = (
        "2026年度 郵便受付分\r\n"
        "姓,名,セイ,メイ,性別,生年月日,郵便番号,住所,番地,携帯電話,"
        "第1希望病院,第1希望日,第1希望時間,備考,担当者\r\n"
        "鈴木,一郎,スズキ,イチロウ,男,1958-03-04,1010021,東京都,1-1,09011112222,"
        "H001,2026-08-12,09:00,ビコウ,山田\r\n"
    ).encode("cp932")
    jp = sheet.parse_upload("受付分.csv", japanese)
    check("CP932 로 읽는다", "CP932" in jp.encoding, jp.encoding)
    check("표 위의 제목 줄을 건너뛴다", len(jp.rows) == 1, len(jp.rows))
    check(
        "일본어 열 이름을 알아본다",
        jp.rows[0]["last_name"] == "鈴木"
        and jp.rows[0]["birth_date"] == "1958-03-04"
        and jp.rows[0]["tel_mobile"] == "09011112222",
        jp.rows[0],
    )
    check("모르는 열은 넣지 않고 알려 준다", jp.ignored_columns == ["担当者"],
          jp.ignored_columns)
    check(
        "성별 표기를 여기서 고치지 않는다 (판정은 일괄 검증 한 곳에서)",
        jp.rows[0]["gender"] == "男",
        jp.rows[0]["gender"],
    )

    section("⑥ Excel 이 값을 바꿔 놓는 셀")
    from openpyxl import Workbook

    book = Workbook()
    worksheet = book.active
    worksheet.append([column.label for column in sheet.SHEET_COLUMNS])
    at = {key: index for index, key in enumerate(sheet.COLUMN_KEYS)}
    cells: list[object] = [""] * len(sheet.SHEET_COLUMNS)
    cells[at["last_name"]] = "高橋"
    cells[at["first_name"]] = "次郎"
    cells[at["gender"]] = "M"
    cells[at["birth_date"]] = date(1972, 1, 15)              # 날짜 셀
    cells[at["postal_code"]] = 1010021                        # 숫자 셀
    cells[at["tel_mobile"]] = 9012345678                      # 앞자리 0 소실
    cells[at["wish1_hospital"]] = "H001"
    cells[at["wish1_date"]] = datetime(2026, 8, 12, 0, 0)     # 일시 셀
    cells[at["wish1_time"]] = time(9, 0)                      # 시각 셀
    cells[at["option_codes"]] = "OPT01\nOPT02"                # 셀 안 줄바꿈
    cells[at["allow_defect"]] = True                          # 참/거짓 셀
    worksheet.append(cells)
    stream = io.BytesIO()
    book.save(stream)

    typed = sheet.parse_upload("입력중.xlsx", stream.getvalue())
    got_row = typed.rows[0]
    check("날짜 셀 → YYYY-MM-DD", got_row["birth_date"] == "1972-01-15",
          got_row["birth_date"])
    check("일시 셀 → 날짜만", got_row["wish1_date"] == "2026-08-12",
          got_row["wish1_date"])
    check("시각 셀 → HH:MM", got_row["wish1_time"] == "09:00", got_row["wish1_time"])
    check("숫자 셀에 소수점이 붙지 않는다", got_row["postal_code"] == "1010021",
          got_row["postal_code"])
    check(f"참/거짓 셀 → 「{BOOL_TRUE_TEXT}」",
          got_row["allow_defect"] == BOOL_TRUE_TEXT,
          got_row["allow_defect"])
    check("옵션 칸의 줄바꿈은 세미콜론으로", got_row["option_codes"] == "OPT01;OPT02",
          got_row["option_codes"])
    check(
        "앞자리 0 이 사라졌을 수 있다고 경고한다",
        any("先頭の「0」" in warning for warning in typed.warnings),
        typed.warnings,
    )

    section("⑦ 거절해야 하는 것")
    cases = [
        (".xls (구형 Excel)", "명부.xls", b"\xd0\xcf\x11\xe0abcd", "xlsx"),
        ("CSV·Excel 이 아닌 파일", "신청서.pdf", b"%PDF-1.4 ...", "CSV"),
        ("빈 파일", "빈파일.csv", b"", "空です"),
        (
            "제목 줄이 없고 열 수도 다르다",
            "엉뚱한서식.csv",
            "田中,太郎,M\r\n佐藤,花子,F\r\n".encode(),
            "ヘッダー行",
        ),
        (
            "상한을 넘는 행 수",
            "너무많음.csv",
            (
                ",".join(column.label for column in sheet.SHEET_COLUMNS)
                + "\r\n"
                + "\r\n".join(
                    f"성{index}" + "," * (len(sheet.SHEET_COLUMNS) - 1)
                    for index in range(sheet.MAX_SHEET_ROWS + 1)
                )
            ).encode("utf-8-sig"),
            str(sheet.MAX_SHEET_ROWS),
        ),
        (
            "상한을 넘는 파일 크기",
            "큰파일.csv",
            b"a" * (sheet.MAX_UPLOAD_BYTES + 1),
            "大きすぎます",
        ),
    ]
    for title, file_name, content, expected in cases:
        try:
            sheet.parse_upload(file_name, content)
            check(title, False, "거절하지 않았다")
        except PostalSheetError as exc:
            check(title, expected in str(exc), f"메시지={exc}")

    positional = (
        "\r\n".join(
            ",".join(
                {0: f"성{index}", 1: "이름", 6: "M", 7: "1990-01-01"}.get(column, "")
                for column in range(len(sheet.SHEET_COLUMNS))
            )
            for index in range(2)
        )
        + "\r\n"
    ).encode("utf-8-sig")
    try:
        result = sheet.parse_upload("서식그대로.csv", positional)
        check(
            "제목 줄이 없어도 열 수가 정확히 같으면 순서대로 받는다",
            result.header_mode == "POSITIONAL" and len(result.rows) == 2,
            (result.header_mode, len(result.rows)),
        )
    except PostalSheetError as exc:
        check("제목 줄이 없어도 열 수가 정확히 같으면 순서대로 받는다", False, exc)

    print("=" * 66)
    if _failures:
        print(f" 결과: {_failures}건 실패")
    else:
        print(" 결과: 전부 통과")
    print("=" * 66)
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())
