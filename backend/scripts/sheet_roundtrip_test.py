"""표 ↔ 파일 왕복 검증 — 회장 · 정원 · 옵션 검사.

    python -m scripts.sheet_roundtrip_test

**서버도 DB 도 필요 없다.** 열 정의와 변환 규칙만 본다.

무엇을 지키려는 검사인가
------------------------
세 표가 전부 `sheet_io.SheetFormat` 위에 있고, 열 정의는 그리드
(`admin_bulk_service`)에서 **파생**된다. 그래서 열을 하나 늘리면 화면·시트가
함께 늘어나야 하는데, 파생이 끊기면 「화면에는 있는데 내보내면 빠지는 칸」이
생긴다. 그것은 담당자가 파일로 왕복하는 동안 **조용히 값이 사라지는** 형태로
나타나므로, 사고가 난 뒤에야 알게 된다.

특히 보는 것
------------
    · 그리드 열과 시트 열이 **같은 순서로 같은 집합**인가
    · 내보낸 것을 다시 가져오면 **한 글자도 달라지지 않는가** (CSV · Excel)
    · 우편번호 `0040051` 의 앞자리 0 이 살아남는가
    · 좌표 `35.6584491` 이 유효숫자에서 잘리지 않는가
    · 성별 코드 `F` 가 파일에서는 「女性のみ」이고 돌아올 때 다시 `F` 가 되는가
    · 열 **순서를 바꿔 만든 파일**도 제목 줄을 보고 제자리에 들어가는가
    · 수식으로 시작하는 셀(`=1+1`)이 Excel 에서 수식이 되지 않는가
"""

import scripts._console  # noqa: F401  (콘솔 UTF-8 보정)

import sys
from datetime import datetime

from app.core import time_grid
from app.services import (
    admin_bulk_service,
    capacity_sheet_service,
    exam_option_sheet_service,
    venue_sheet_service,
)

PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}")
    if detail:
        print(f"         {detail}")


def roundtrip(service, rows, kind):
    """내보낸 뒤 다시 가져온다. → (되돌아온 행들, 요약)"""
    normalized = service.normalize_export_rows(rows)
    blob = service.build_xlsx(normalized) if kind == "xlsx" else service.build_csv(normalized)
    result = service.parse_upload(f"t.{kind}", blob)
    return normalized, result


def compare(normalized, result, ignore=()):
    """왕복 전후로 달라진 칸을 찾는다."""
    if len(normalized) != len(result.rows):
        return [f"행 수가 다르다 {len(normalized)} → {len(result.rows)}"]

    bad = []
    for i, (before, after) in enumerate(zip(normalized, result.rows), start=1):
        for key, value in before.items():
            if key in ignore:
                continue
            if value != after.get(key, ""):
                bad.append(f"{i}행 {key}: {value!r} → {after.get(key)!r}")
    return bad


# --------------------------------------------------------------------------
# ① 그리드 열 == 시트 열
# --------------------------------------------------------------------------


def test_columns_match() -> None:
    print("\n① 그리드 열과 파일 열이 어긋나지 않는가")
    print("-" * 70)

    grid_keys = [c.key for c in admin_bulk_service.VENUE_COLUMNS]
    sheet_keys = [c.key for c in venue_sheet_service.SHEET_COLUMNS]
    check("회장 — 열 집합과 순서가 같다", grid_keys == sheet_keys,
          f"그리드 {len(grid_keys)}열 · 시트 {len(sheet_keys)}열")

    grid_keys = [c.key for c in admin_bulk_service.EXAM_OPTION_COLUMNS]
    sheet_keys = [c.key for c in exam_option_sheet_service.SHEET_COLUMNS]
    check("옵션 검사 — 열 집합과 순서가 같다", grid_keys == sheet_keys,
          f"그리드 {len(grid_keys)}열 · 시트 {len(sheet_keys)}열")

    # 정원 표는 회장 열이 읽기 전용이라 그리드에만 있는 열이 있다.
    # 반대로 **시간대 열은 격자에서 나오므로 반드시 전부 있어야 한다.**
    sheet_keys = {c.key for c in capacity_sheet_service.SHEET_COLUMNS}
    missing = [k for k in time_grid.SHEET_KEYS if k not in sheet_keys]
    check("정원 — 격자의 시간대 열이 파일에 전부 있다", not missing,
          f"격자 {len(time_grid.SHEET_KEYS)}칸 / 빠진 칸 {missing or '없음'}")


# --------------------------------------------------------------------------
# ② 왕복
# --------------------------------------------------------------------------


VENUE_ROW = {
    "code": "V01",
    "name": "サンプル会館 B",
    "name_kana": "さんぷるかいかん びー",
    "is_visible": "예",
    "sort_order": "1",
    "tel": "03-0000-0000",
    "area": "東京都",
    "city": "墨田区",
    # 앞자리 0 — Excel 이 숫자로 읽으면 `12345` 가 된다
    "postal_code": "0012345",
    "address": "押上1丁目1-2",
    "transit_info": "とうきょうスカイツリー駅から徒歩1分",
    "access_minutes": "徒歩1分",
    "has_parking": "예",
    # 유효숫자 — `:g` 로 찍으면 35.7101 로 잘려 위치가 옮겨간다
    "latitude": "35.7100543",
    "longitude": "139.8107141",
}


def test_venue_roundtrip() -> None:
    print("\n② 회장 표 — 내보낸 뒤 다시 가져온다")
    print("-" * 70)

    for kind in ("csv", "xlsx"):
        normalized, result = roundtrip(venue_sheet_service, [VENUE_ROW], kind)
        bad = compare(normalized, result)
        check(f"{kind.upper()} 왕복에서 한 칸도 달라지지 않는다", not bad,
              "; ".join(bad) if bad else f"{len(normalized)}행 · 열 {result.matched_columns}개 연결")

        row = result.rows[0]
        check(f"{kind.upper()} 우편번호의 앞자리 0 이 살아남는다",
              row["postal_code"] == "0012345", f"→ {row['postal_code']!r}")
        check(f"{kind.upper()} 좌표가 유효숫자에서 잘리지 않는다",
              row["latitude"] == "35.7100543", f"→ {row['latitude']!r}")


def test_capacity_roundtrip() -> None:
    print("\n③ 정원 표 — 내보낸 뒤 다시 가져온다")
    print("-" * 70)

    row = {
        "hospital_code": "V01",
        "hospital_name": "サンプル会館 A",
        "event_date": "2026-09-15",
        "booking_close_date": "2026-09-01",
        "open_time": "09:30",
        "reception_end_time": "16:00",
        "note": "오전만 개최",
        "is_visible": "예",
    }
    # 격자의 앞 절반만 채운다 — 「오전만 여는 날」
    for i in list(time_grid.indexes())[:6]:
        row[time_grid.sheet_key(i)] = str(20 + i)

    for kind in ("csv", "xlsx"):
        normalized, result = roundtrip(capacity_sheet_service, [row], kind)
        bad = compare(normalized, result)
        check(f"{kind.upper()} 왕복에서 한 칸도 달라지지 않는다", not bad,
              "; ".join(bad) if bad else f"열 {result.matched_columns}개 연결")

        back = result.rows[0]
        check(f"{kind.upper()} 날짜가 지역 표기로 바뀌지 않는다",
              back["event_date"] == "2026-09-15", f"→ {back['event_date']!r}")
        check(f"{kind.upper()} 시각이 문자열로 남는다",
              back["open_time"] == "09:30", f"→ {back['open_time']!r}")
        # 빈 칸은 「그 시간대를 열지 않음」이다. 0 으로 바뀌면 뜻이 달라진다.
        late = time_grid.sheet_key(list(time_grid.indexes())[-1])
        check(f"{kind.upper()} 빈 시간대가 0 으로 바뀌지 않는다",
              back.get(late, "") == "", f"{late} → {back.get(late)!r}")


def test_exam_option_roundtrip() -> None:
    print("\n④ 옵션 검사 표 — 코드와 말의 왕복")
    print("-" * 70)

    row = {
        "code": "MAMMO",
        "name": "유방암 맘모그래피",
        "is_active": "예",
        "sort_order": "3",
        "target_gender": "F",
        "target_age_min": "40",
        "target_age_max": "74",
        "description": "유방 X선 촬영입니다.",
        "note": "금식은 필요하지 않습니다.",
    }

    gender_labels = dict(admin_bulk_service.GENDER_CHOICES)
    normalized = exam_option_sheet_service.normalize_export_rows([row])
    check("파일에는 코드가 아니라 말이 적힌다",
          normalized[0]["target_gender"] == gender_labels["F"],
          f"F → {normalized[0]['target_gender']!r}")

    for kind in ("csv", "xlsx"):
        _, result = roundtrip(exam_option_sheet_service, [row], kind)
        back = result.rows[0]
        check(f"{kind.upper()} 가져오면 다시 코드가 된다",
              back["target_gender"] == "F", f"→ {back['target_gender']!r}")
        check(f"{kind.upper()} 나머지 칸이 그대로다",
              back["code"] == "MAMMO" and back["name"] == row["name"]
              and back["target_age_max"] == "74",
              f"{back['code']} / {back['name']} / {back['target_age_max']}")

    # 담당자가 손으로 적을 법한 표기도 받는다
    written_back = [(label, value) for value, label in
                    admin_bulk_service.GENDER_CHOICES]
    for text, want in written_back + [("F", "F"), ("男性", "M"),
                                      ("ALL", "ALL"), ("女性", "F"),
                                      ("全体", "ALL")]:
        check(f"「{text}」 를 {want} 로 읽는다",
              admin_bulk_service.parse_gender(text) == want,
              f"→ {admin_bulk_service.parse_gender(text)}")
    check("알 수 없는 표기는 조용히 통과시키지 않는다",
          admin_bulk_service.parse_gender("女性だけ") is None)


# --------------------------------------------------------------------------
# ⑤ 열 순서가 바뀐 파일
# --------------------------------------------------------------------------


def test_column_order_independent() -> None:
    print("\n⑤ 열 순서를 바꿔 만든 파일도 제자리에 들어간다")
    print("-" * 70)
    print("  화면의 열 순서를 바꿨을 때, 예전에 내보낸 파일을 그대로 다시")
    print("  가져올 수 있어야 한다. 가져오기는 순서가 아니라 제목 줄을 본다.")
    print()

    import csv
    import io

    columns = list(venue_sheet_service.SHEET_COLUMNS)
    reordered = list(reversed(columns))

    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([c.label for c in reordered])
    writer.writerow([VENUE_ROW.get(c.key, "") for c in reordered])
    blob = buffer.getvalue().encode("utf-8-sig")

    result = venue_sheet_service.parse_upload("reversed.csv", blob)
    row = result.rows[0]
    bad = [k for k, v in VENUE_ROW.items() if row.get(k, "") != v]

    check("열을 거꾸로 늘어놓은 파일도 값이 제 칸에 들어간다", not bad,
          "; ".join(f"{k}: {VENUE_ROW[k]!r} → {row.get(k)!r}" for k in bad)
          if bad else f"열 {result.matched_columns}개 연결 · {result.header_mode}")


def test_formula_guard() -> None:
    print("\n⑥ 수식으로 시작하는 값이 Excel 에서 수식이 되지 않는다")
    print("-" * 70)

    row = dict(VENUE_ROW)
    row["name"] = "=1+1"
    row["transit_info"] = "@SUM(A1:A9)"

    normalized = venue_sheet_service.normalize_export_rows([row])
    blob = venue_sheet_service.build_csv(normalized)
    text = blob.decode("utf-8-sig")

    check("CSV 에 그대로 `=` 로 시작하는 셀이 남지 않는다",
          ",=1+1" not in text and text.count("'=1+1") == 1,
          "앞에 따옴표를 붙여 무력화한다")

    back = venue_sheet_service.parse_upload("f.csv", blob)
    check("다시 가져오면 따옴표가 떨어져 원래 값이 된다",
          back.rows[0]["name"] == "=1+1", f"→ {back.rows[0]['name']!r}")


def test_file_names() -> None:
    print("\n⑦ 내려받는 파일 이름")
    print("-" * 70)
    moment = datetime(2026, 9, 15, 14, 32)
    for label, service in (("회장", venue_sheet_service),
                           ("정원", capacity_sheet_service),
                           ("옵션 검사", exam_option_sheet_service)):
        name = service.export_file_name("xlsx", moment)
        check(f"{label} — 날짜가 들어가 서로 덮어쓰지 않는다",
              "20260915" in name and name.endswith(".xlsx"), name)


def main() -> int:
    print("=" * 70)
    print(" 표 ↔ 파일 왕복 검증 (회장 · 정원 · 옵션 검사)")
    print("=" * 70)

    test_columns_match()
    test_venue_roundtrip()
    test_capacity_roundtrip()
    test_exam_option_roundtrip()
    test_column_order_independent()
    test_formula_guard()
    test_file_names()

    print()
    print("=" * 70)
    if FAIL:
        print(f" 결과: {PASS}/{PASS + FAIL} 통과, {FAIL}건 실패")
    else:
        print(f" 결과: 전부 통과 ({PASS}건)")
    print("=" * 70)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
