"""본인 확인(U-11) 동작 검증.

DB 초기화 후 실행하여 세 가지 판정 결과가 모두 올바른지 확인한다.

    python -m scripts.init_db
    python -m scripts.smoke_test

서버를 띄우지 않고 서비스 계층을 직접 호출하므로 DB 접속만 있으면 된다.
"""

import scripts._console  # noqa: F401  (콘솔 UTF-8 보정)
import sys
from datetime import date

from pydantic import ValidationError

from app.core.database import SessionLocal
from app.schemas.verify import VerifyRequest, VerifyStatus
from app.services.verify_service import verify_identity

PASS = "  [OK]  "
FAIL = "  [FAIL]"

CARD = dict(insurer_no="0000", insurance_symbol="ABCD", insurance_no="0000")

# (설명, 입력, 기대 결과)
CASES = [
    (
        "① 검진 대상자 · 미예약 → 예약 진행 가능",
        dict(last_name="田中", first_name="太郎",
             last_name_kana="タナカ", first_name_kana="タロウ",
             gender="M", birth_date=date(1970, 5, 12), **CARD),
        VerifyStatus.ELIGIBLE,
    ),
    (
        "② 검진 대상자 · 예약 있음 → 이미 예약 내용 있음",
        dict(last_name="佐藤", first_name="花子",
             last_name_kana="サトウ", first_name_kana="ハナコ",
             gender="F", birth_date=date(1958, 11, 3), **CARD),
        VerifyStatus.ALREADY_RESERVED,
    ),
    (
        "③ 명부에 없는 사람 → 검진 대상자 아님",
        dict(last_name="木村", first_name="拓也",
             last_name_kana="キムラ", first_name_kana="タクヤ",
             gender="M", birth_date=date(1972, 3, 3), **CARD),
        VerifyStatus.NOT_ELIGIBLE,
    ),
    (
        "④ 성은 맞으나 이름 불일치 → 검진 대상자 아님",
        dict(last_name="田中", first_name="次郎",
             last_name_kana="タナカ", first_name_kana="ジロウ",
             gender="M", birth_date=date(1970, 5, 12), **CARD),
        VerifyStatus.NOT_ELIGIBLE,
    ),
    (
        "⑤ 생년월일 불일치 → 검진 대상자 아님",
        dict(last_name="田中", first_name="太郎",
             last_name_kana="タナカ", first_name_kana="タロウ",
             gender="M", birth_date=date(1970, 5, 13), **CARD),
        VerifyStatus.NOT_ELIGIBLE,
    ),
    (
        "⑥ 보험증 번호 불일치 → 검진 대상자 아님",
        dict(last_name="田中", first_name="太郎",
             last_name_kana="タナカ", first_name_kana="タロウ",
             gender="M", birth_date=date(1970, 5, 12),
             insurer_no="9999", insurance_symbol="ABCD", insurance_no="0000"),
        VerifyStatus.NOT_ELIGIBLE,
    ),
    (
        "⑦ 후리가나를 히라가나로 입력 → 가타카나로 자동 변환되어 통과",
        dict(last_name="田中", first_name="太郎",
             last_name_kana="たなか", first_name_kana="たろう",
             gender="M", birth_date=date(1970, 5, 12), **CARD),
        VerifyStatus.ELIGIBLE,
    ),
    (
        "⑧ 후리가나를 반각 가타카나로 입력 → 전각으로 자동 변환되어 통과",
        dict(last_name="鈴木", first_name="一郎",
             last_name_kana="ｽｽﾞｷ", first_name_kana="ｲﾁﾛｳ",
             gender="M", birth_date=date(1965, 2, 20), **CARD),
        VerifyStatus.ELIGIBLE,
    ),
    (
        "⑨ 한자 성명에 공백 섞임 → 정규화되어 통과",
        dict(last_name=" 高橋 ", first_name="　美咲　",
             last_name_kana="タカハシ", first_name_kana="ミサキ",
             gender="F", birth_date=date(1982, 7, 8), **CARD),
        VerifyStatus.ELIGIBLE,
    ),
    (
        "⑩ 기호 소문자 입력 → 정규화되어 통과",
        dict(last_name="渡辺", first_name="由美",
             last_name_kana="ワタナベ", first_name_kana="ユミ",
             gender="F", birth_date=date(1975, 12, 15),
             insurer_no="0000", insurance_symbol="abcd", insurance_no="0000"),
        VerifyStatus.ELIGIBLE,
    ),

    # ------------------------------------------------------------------
    # 핵심 검증 — 동성동명(한자) · 동일 생년월일 · 동일 보험증이지만
    # 읽는 법이 다른 두 사람을 후리가나로 구별할 수 있는가
    # ------------------------------------------------------------------
    (
        "⑪ 中田 健 = ナカタ(미예약) → 예약 가능",
        dict(last_name="中田", first_name="健",
             last_name_kana="ナカタ", first_name_kana="ケン",
             gender="M", birth_date=date(1968, 6, 15), **CARD),
        VerifyStatus.ELIGIBLE,
    ),
    (
        "⑫ 中田 健 = ナカダ(예약있음) → 이미 예약 내용 있음",
        dict(last_name="中田", first_name="健",
             last_name_kana="ナカダ", first_name_kana="ケン",
             gender="M", birth_date=date(1968, 6, 15), **CARD),
        VerifyStatus.ALREADY_RESERVED,
    ),
    (
        "⑬ 中田 健 = ナカサ(명부에 없는 읽기) → 후리가나 확인 안내",
        dict(last_name="中田", first_name="健",
             last_name_kana="ナカサ", first_name_kana="ケン",
             gender="M", birth_date=date(1968, 6, 15), **CARD),
        VerifyStatus.KANA_MISMATCH,
    ),
    (
        "⑭ 한자는 맞으나 후리가나 오타 → 「대상자 아님」이 아니라 확인 안내",
        dict(last_name="田中", first_name="太郎",
             last_name_kana="タナカ", first_name_kana="ジロウ",
             gender="M", birth_date=date(1970, 5, 12), **CARD),
        VerifyStatus.KANA_MISMATCH,
    ),
    (
        "⑮ 탁점 차이는 다른 이름으로 취급 (スズキ ≠ ススキ)",
        dict(last_name="鈴木", first_name="一郎",
             last_name_kana="ススキ", first_name_kana="イチロウ",
             gender="M", birth_date=date(1965, 2, 20), **CARD),
        VerifyStatus.KANA_MISMATCH,
    ),

    # --- 성별 대조 -----------------------------------------------------
    (
        "⑯ 성명·후리가나는 맞으나 성별이 다름 → 성별 확인 안내",
        dict(last_name="田中", first_name="太郎",
             last_name_kana="タナカ", first_name_kana="タロウ",
             gender="F", birth_date=date(1970, 5, 12), **CARD),
        VerifyStatus.GENDER_MISMATCH,
    ),

    # --- 미들네임 (임의 항목이므로 대조에 영향을 주지 않아야 한다) -------
    (
        "⑰ 미들네임을 입력해도 대조에 영향 없음 → 정상 통과",
        dict(last_name="田中", first_name="太郎",
             last_name_kana="タナカ", first_name_kana="タロウ",
             middle_name="ウィリアム", middle_name_kana="ウィリアム",
             gender="M", birth_date=date(1970, 5, 12), **CARD),
        VerifyStatus.ELIGIBLE,
    ),
    (
        "⑱ 미들네임 후리가나를 히라가나로 → 자동 변환되어 통과",
        dict(last_name="田中", first_name="太郎",
             last_name_kana="タナカ", first_name_kana="タロウ",
             middle_name="William", middle_name_kana="うぃりあむ",
             gender="M", birth_date=date(1970, 5, 12), **CARD),
        VerifyStatus.ELIGIBLE,
    ),
]

# 입력 형식 자체가 거부되어야 하는 케이스 (설명, 입력, 오류가 걸릴 필드)
INVALID_CASES = [
    (
        "⑪ 후리가나에 한자 입력 → 거부",
        dict(last_name="田中", first_name="太郎",
             last_name_kana="田中", first_name_kana="タロウ",
             gender="M", birth_date=date(1970, 5, 12), **CARD),
        "last_name_kana",
    ),
    (
        "⑫ 후리가나에 영문 입력 → 거부",
        dict(last_name="田中", first_name="太郎",
             last_name_kana="タナカ", first_name_kana="Taro",
             gender="M", birth_date=date(1970, 5, 12), **CARD),
        "first_name_kana",
    ),
    (
        "⑬ 성(한자) 누락 → 거부",
        dict(last_name="", first_name="太郎",
             last_name_kana="タナカ", first_name_kana="タロウ",
             gender="M", birth_date=date(1970, 5, 12), **CARD),
        "last_name",
    ),
    (
        "⑭ 미들네임 후리가나에 영문 입력 → 거부",
        dict(last_name="田中", first_name="太郎",
             last_name_kana="タナカ", first_name_kana="タロウ",
             middle_name="William", middle_name_kana="William",
             gender="M", birth_date=date(1970, 5, 12), **CARD),
        "middle_name_kana",
    ),
    (
        "⑮ 성별 미선택 → 거부",
        dict(last_name="田中", first_name="太郎",
             last_name_kana="タナカ", first_name_kana="タロウ",
             birth_date=date(1970, 5, 12), **CARD),
        "gender",
    ),
]


def main() -> int:
    from scripts._preconditions import active_reservations_of_test_person, explain_blocked

    blocking = active_reservations_of_test_person()
    if blocking:
        explain_blocked(blocking)
        return 2

    db = SessionLocal()
    failures = 0

    print("=" * 66)
    print(" 본인 확인(U-11) 판정 검증")
    print("=" * 66)

    try:
        for title, payload, expected in CASES:
            request = VerifyRequest(**payload)
            result = verify_identity(db, request)
            ok = result.status == expected

            mark = PASS if ok else FAIL
            print(f"{mark} {title}")
            print(f"         기대={expected.value} / 실제={result.status.value}")

            if result.person:
                print(f"         대상자={result.person.full_name}"
                      f" ({result.person.full_name_kana})")
            if result.status == VerifyStatus.ALREADY_RESERVED:
                # 예약번호는 이 응답에 담기지 않는다. 담기면 그것이 결함이다.
                # (services/verify_service.py 의 ALREADY_RESERVED 분기)
                leaked = getattr(result, "reservation_no", None) or result.person
                print(f"         예약번호·신원 미노출={'실패' if leaked else '확인'}")
            if result.status == VerifyStatus.ELIGIBLE:
                print(f"         토큰 발급={'예' if result.verify_token else '아니오'}")
            if result.status in (
                VerifyStatus.NOT_ELIGIBLE,
                VerifyStatus.KANA_MISMATCH,
                VerifyStatus.GENDER_MISMATCH,
                VerifyStatus.AMBIGUOUS,
            ):
                print(f"         제목={result.title}")

            if not ok:
                failures += 1

        # --- 입력 형식 거부 검증 -----------------------------------------
        print("-" * 66)
        for title, payload, expected_field in INVALID_CASES:
            try:
                VerifyRequest(**payload)
                print(f"{FAIL} {title}")
                print("         기대=거부 / 실제=통과됨")
                failures += 1
            except ValidationError as e:
                fields = [str(err["loc"][-1]) for err in e.errors()]
                ok = expected_field in fields
                print(f"{PASS if ok else FAIL} {title}")
                msg = e.errors()[0]["msg"].removeprefix("Value error, ")
                print(f"         거부 필드={fields} / 메시지={msg}")
                if not ok:
                    failures += 1
    finally:
        db.close()

    print("=" * 66)
    total = len(CASES) + len(INVALID_CASES)
    if failures:
        print(f" 결과: {total - failures}/{total} 통과, {failures}건 실패")
    else:
        print(f" 결과: {total}/{total} 전부 통과")
    print("=" * 66)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
