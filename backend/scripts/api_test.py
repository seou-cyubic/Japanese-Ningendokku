"""본인 확인 API 통합 검증 (HTTP 경유).

서버를 띄운 상태에서 실행한다.

    python -m uvicorn app.main:app --port 8000
    python -m scripts.api_test
"""

import scripts._console  # noqa: F401  (콘솔 UTF-8 보정)
import json
import sys
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8000/api/v1/reservations/verify"

CARD = {"insurer_no": "0000", "insurance_symbol": "ABCD", "insurance_no": "0000"}


def call(payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


CASES = [
    ("① 예약 가능 (田中 太郎)",
     {"last_name": "田中", "first_name": "太郎",
      "last_name_kana": "タナカ", "first_name_kana": "タロウ",
      "gender": "M", "birth_date": "1970-05-12", **CARD}),

    ("② 이미 예약 (佐藤 花子)",
     {"last_name": "佐藤", "first_name": "花子",
      "last_name_kana": "サトウ", "first_name_kana": "ハナコ",
      "gender": "F", "birth_date": "1958-11-03", **CARD}),

    ("③ 대상자 아님 (木村 拓也)",
     {"last_name": "木村", "first_name": "拓也",
      "last_name_kana": "キムラ", "first_name_kana": "タクヤ",
      "gender": "M", "birth_date": "1972-03-03", **CARD}),

    ("④ 후리가나 히라가나 입력 → 자동 변환 후 통과",
     {"last_name": "田中", "first_name": "太郎",
      "last_name_kana": "たなか", "first_name_kana": "たろう",
      "gender": "M", "birth_date": "1970-05-12", **CARD}),

    ("⑤ 후리가나 반각 가타카나 입력 → 자동 변환 후 통과",
     {"last_name": "鈴木", "first_name": "一郎",
      "last_name_kana": "ｽｽﾞｷ", "first_name_kana": "ｲﾁﾛｳ",
      "gender": "M", "birth_date": "1965-02-20", **CARD}),

    # --- 동성동명(한자)·동일 생년월일·동일 보험증, 읽는 법만 다른 두 사람 ---
    ("⑥ 中田 健 = ナカタ ケン → 예약 가능",
     {"last_name": "中田", "first_name": "健",
      "last_name_kana": "ナカタ", "first_name_kana": "ケン",
      "gender": "M", "birth_date": "1968-06-15", **CARD}),

    ("⑦ 中田 健 = ナカダ ケン → 이미 예약 있음 (다른 사람)",
     {"last_name": "中田", "first_name": "健",
      "last_name_kana": "ナカダ", "first_name_kana": "ケン",
      "gender": "M", "birth_date": "1968-06-15", **CARD}),

    ("⑧ 中田 健 = ナカサ ケン → 후리가나 확인 안내",
     {"last_name": "中田", "first_name": "健",
      "last_name_kana": "ナカサ", "first_name_kana": "ケン",
      "gender": "M", "birth_date": "1968-06-15", **CARD}),

    ("⑨ 입력 검증 — 후리가나에 한자",
     {"last_name": "田中", "first_name": "太郎",
      "last_name_kana": "田中", "first_name_kana": "タロウ",
      "gender": "M", "birth_date": "1970-05-12", **CARD}),

    ("⑦ 입력 검증 — 후리가나에 영문",
     {"last_name": "田中", "first_name": "太郎",
      "last_name_kana": "タナカ", "first_name_kana": "Taro",
      "gender": "M", "birth_date": "1970-05-12", **CARD}),

    ("⑧ 입력 검증 — 성(한자) 누락",
     {"last_name": "", "first_name": "太郎",
      "last_name_kana": "タナカ", "first_name_kana": "タロウ",
      "gender": "M", "birth_date": "1970-05-12", **CARD}),

    ("⑨ 입력 검증 — 미래 생년월일",
     {"last_name": "田中", "first_name": "太郎",
      "last_name_kana": "タナカ", "first_name_kana": "タロウ",
      "gender": "M", "birth_date": "2099-01-01", **CARD}),
]


def main() -> int:
    for title, payload in CASES:
        status, body = call(payload)
        print(f"--- {title}   [HTTP {status}]")

        if not body.get("success"):
            err = body.get("error", {})
            print(f"    코드    : {err.get('code')}")
            print(f"    메시지  : {err.get('message')}")
            for f in body.get("fields", []):
                print(f"    필드    : {f['name']} → {f['message']}")
            print()
            continue

        d = body["data"]
        print(f"    status  : {d['status']}")
        print(f"    제목    : {d['title']}")
        print(f"    message : {d['message']}")
        for h in d.get("hints", []):
            print(f"      · {h}")
        if d.get("reservation_no"):
            print(f"    예약번호: {d['reservation_no']}")
        if d.get("person"):
            p = d["person"]
            print(f"    성명    : {p['last_name']} {p['first_name']}"
                  f"  (성={p['last_name']} / 이름={p['first_name']})")
            print(f"    후리가나: {p['last_name_kana']} {p['first_name_kana']}"
                  f"  (성={p['last_name_kana']} / 이름={p['first_name_kana']})")
            print(f"    기타    : {p['gender']} / {p['birth_date']} / {p['insurance_card_no']}")
            print(f"    미들네임: {'(공란)' if p['middle_name'] == '' else p['middle_name']}")
        if d.get("contact"):
            c = d["contact"]
            print(f"    문의처  : {c['tel']} / {c['email']}")
            print(f"    응대시간: {c['hours']}")
        if d.get("verify_token"):
            print(f"    토큰    : {d['verify_token'][:40]}...")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
