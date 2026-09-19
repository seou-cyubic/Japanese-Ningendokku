"""우편번호 적재 판정 검증.

    python -m scripts.postal_import_test

**서버도 인터넷도 필요 없다.** 원본 파싱과 「적재됐는가」 판정만 본다.
(DB 는 건수를 세는 데만 쓰며, 아무것도 고치지 않는다.)

무엇을 지키려는 검사인가
------------------------
「주소 찾기」가 이 데이터 위에서 돈다. 없으면 검색이 **조용히 0건**을
돌려주고, 화면에도 로그에도 원인이 남지 않는다. 서버가 뜰 때 그것을
알아채도록 판정을 넣었는데, 그 판정이 틀리면 두 방향으로 나빠진다.

    · 너무 느슨하면 — 반쪽만 들어간 데이터를 「있다」고 보고 그대로 돈다
    · 너무 빡빡하면 — 멀쩡한 데이터를 매번 다시 내려받는다

특히 보는 것
------------
    · 12만 건 중 3만 건만 들어간 상태를 「없음」으로 보는가 (임계값)
    · 원본의 「사람이 읽으라고 넣은 말」을 걷어내는가
    · **카나 칸이 반각**인 utf 판에서도 그것이 걷혀 나가는가
    · 정역의 괄호만 떼고 정역 이름 자체는 남기는가
"""

import scripts._console  # noqa: F401  (콘솔 UTF-8 보정)

import sys

from app.core.config import settings
from app.services import postal_import_service as importer

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


# 실제 KEN_ALL(utf 판)에서 그대로 가져온 모양. **카나 칸이 반각**이다.
SAMPLE = (
    '13101,"100  ","1000014","ﾄｳｷｮｳﾄ","ﾁﾖﾀﾞｸ","ﾅｶﾞﾀﾁｮｳ",'
    '"東京都","千代田区","永田町",0,0,1,0,0,0\n'
    '13101,"100  ","1000000","ﾄｳｷｮｳﾄ","ﾁﾖﾀﾞｸ","ｲｶﾆｹｲｻｲｶﾞﾅｲﾊﾞｱｲ",'
    '"東京都","千代田区","以下に掲載がない場合",0,0,0,0,0,0\n'
    '13103,"105  ","1050011","ﾄｳｷｮｳﾄ","ﾐﾅﾄｸ","ｼﾊﾞｺｳｴﾝ(1-3ﾁｮｳﾒ)",'
    '"東京都","港区","芝公園（１〜３丁目）",1,0,1,0,0,0\n'
    # 같은 값이 두 번 — 괄호를 떼면 중복이 된다
    '13103,"105  ","1050011","ﾄｳｷｮｳﾄ","ﾐﾅﾄｸ","ｼﾊﾞｺｳｴﾝ(4ﾁｮｳﾒ)",'
    '"東京都","港区","芝公園（４丁目）",1,0,1,0,0,0\n'
    # 우편번호가 7자리가 아닌 줄 — 버려야 한다
    '13101,"100  ","100","ﾄｳｷｮｳﾄ","ﾁﾖﾀﾞｸ","ﾃｽﾄ","東京都","千代田区","テスト",0,0,0,0,0,0\n'
)


def test_parse() -> None:
    print("\n① 원본 읽기")
    print("-" * 70)

    rows = importer.parse(SAMPLE)
    by_zip = {r["zipcode"]: r for r in rows}

    check("7자리가 아닌 우편번호는 버린다", "100" not in by_zip,
          f"읽은 건수 {len(rows)}")

    check("괄호를 뗀 뒤 같아진 두 줄을 하나로 합친다",
          len([r for r in rows if r["zipcode"] == "1050011"]) == 1,
          "芝公園（１〜３丁目） 와 （４丁目） → 芝公園")

    row = by_zip.get("1000000")
    check("「以下に掲載がない場合」은 정역을 비운다",
          row is not None and row["town"] == "",
          f"→ 町域={row['town']!r} · 전체={row['search_text']}" if row else "행이 없다")

    # 예전에는 전각 카나만 보고 있어, 한자 쪽은 지워지는데 카나 쪽에는
    # 그대로 남았다. 카나로 검색하면 「以下に掲載がない場合」이 걸렸다.
    check("카나 칸(반각)에서도 그 말이 걷혀 나간다",
          row is not None and "ｲｶﾆｹｲｻｲ" not in row["search_kana"],
          f"→ {row['search_kana']!r}" if row else "")

    row = by_zip.get("1050011")
    check("정역의 괄호만 떼고 이름은 남긴다",
          row is not None and row["town"] == "芝公園",
          f"→ {row['town']!r}" if row else "")

    # 예전 식은 괄호 **앞의 카나까지** 먹어 정역 읽기가 통째로 사라졌다.
    check("카나 쪽에서도 괄호 앞의 이름이 살아남는다",
          row is not None and row["search_kana"].endswith("ｼﾊﾞｺｳｴﾝ"),
          f"→ {row['search_kana']!r}" if row else "")

    row = by_zip.get("1000014")
    check("보통 행은 그대로 들어간다",
          row is not None and row["search_text"] == "東京都千代田区永田町",
          f"→ {row['search_text']}" if row else "")


def test_town_cleaners() -> None:
    print("\n② 「사람이 읽으라고 넣은 말」 걷어내기")
    print("-" * 70)

    cases_kanji = [
        ("以下に掲載がない場合", ""),
        ("○○の次に番地がくる場合", ""),
        ("一円", ""),
        ("芝公園（１〜３丁目）", "芝公園"),
        ("永田町", "永田町"),
    ]
    for text, want in cases_kanji:
        got = importer.clean_town(text)
        check(f"한자 「{text}」 → {want!r}", got == want, f"→ {got!r}")

    cases_kana = [
        ("ｲｶﾆｹｲｻｲｶﾞﾅｲﾊﾞｱｲ", ""),
        ("イカニケイサイガナイバアイ", ""),
        ("ｲﾁｴﾝ", ""),
        # 「一円寺」처럼 一円 으로 시작하는 진짜 지명은 남아야 한다
        ("ｲﾁｴﾝｼﾞ", "ｲﾁｴﾝｼﾞ"),
        ("ｼﾊﾞｺｳｴﾝ(1-3ﾁｮｳﾒ)", "ｼﾊﾞｺｳｴﾝ"),
        ("ﾅｶﾞﾀﾁｮｳ", "ﾅｶﾞﾀﾁｮｳ"),
    ]
    for text, want in cases_kana:
        got = importer.clean_town_kana(text)
        check(f"카나 「{text}」 → {want!r}", got == want, f"→ {got!r}")


def test_loaded_judgement() -> None:
    print("\n③ 「적재됐는가」 판정")
    print("-" * 70)
    print("  0건이 아니라 임계값으로 본다. 적재 도중에 죽으면 3만 건쯤")
    print("  들어간 상태로 남는데, 그것을 「있다」고 보면 반쪽짜리로 계속 돈다.")
    print()

    class FakeDB:
        def __init__(self, count):
            self._count = count

        def execute(self, *_args, **_kwargs):
            outer = self

            class R:
                def scalar(self):
                    return outer._count
            return R()

    minimum = settings.POSTAL_MIN_ROWS
    for count, want in ((0, False), (30_000, False),
                        (minimum - 1, False), (minimum, True), (124_147, True)):
        got = importer.is_loaded(FakeDB(count), minimum)
        check(f"{count:>7,}건 → {'쓸 수 있다' if want else '온전하지 않다'}",
              got == want, f"기준 {minimum:,}건")


def test_status_shape() -> None:
    print("\n④ 관리 화면이 읽는 상태의 모양")
    print("-" * 70)

    keys = set(importer.ImportState().as_dict())
    want = {"state", "count", "total", "message", "started_at", "finished_at"}
    check("상태 응답에 필요한 칸이 전부 있다", want <= keys,
          f"빠진 칸 {want - keys or '없음'}")

    states = {importer.MISSING, importer.RUNNING, importer.READY,
              importer.FAILED, importer.DISABLED}
    check("상태 값이 다섯 가지로 갈린다", len(states) == 5,
          " · ".join(sorted(states)))


def main() -> int:
    print("=" * 70)
    print(" 우편번호 적재 판정 검증")
    print("=" * 70)

    test_parse()
    test_town_cleaners()
    test_loaded_judgement()
    test_status_shape()

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
