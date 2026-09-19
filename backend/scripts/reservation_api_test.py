"""예약 확정 · 관리 화면 API 통합 검증.

    python -m uvicorn app.main:app --reload      # 다른 창에서 서버 기동
    python -m scripts.reservation_api_test
    python -m scripts.reservation_api_test --base http://127.0.0.1:8010

무엇을 확인하는가
----------------
    ① 본인 확인 → 예약 확정 → 예약번호 발행
    ② 같은 사람이 다시 예약 → 중복 거절 (BR-03)
    ③ 본인 확인 없이 예약 → 거절
    ④ 정원이 0인 슬롯에 예약 → 만석 거절 (BR-07)
    ⑤ 관리자 로그인 · 권한 3단계 접근 제어 (L1/L2/L3)
    ⑥ 예약 검색 · 상세 · 수정 · 취소 → 정원 반환
    ⑦ 우편 접수 (제1희망 만석 → 제2희망 자동 이동)
    ⑧ 정원 감원 하한 (예약 수 미만으로 내릴 수 없음)
    ⑨ 기간이 지난 예약의 자동 삭제
"""

import scripts._console  # noqa: F401  (콘솔 UTF-8 보정)
import http.cookiejar
import json
import sys
import urllib.error
import urllib.request
from urllib.parse import quote
from datetime import date, datetime, timedelta

from sqlalchemy import or_, select

from app.core import reservation_no as res_no
from app.core.database import SessionLocal
from app.core import time_grid
from app.models.hospital import Hospital, HospitalSchedule
from app.services import slot_grid_service as grid
from app.models.reservation import Reservation

PASS = "  [OK]  "
FAIL = "  [FAIL]"

BASE = "http://127.0.0.1:8000"

failures = 0


def _base() -> str:
    if "--base" in sys.argv:
        index = sys.argv.index("--base")
        if index + 1 < len(sys.argv):
            return sys.argv[index + 1].rstrip("/")
    return BASE


class Client:
    """쿠키를 유지하는 최소 HTTP 클라이언트. (관리자 세션 확인용)"""

    def __init__(self, base: str) -> None:
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )

    def call(self, method: str, path: str, payload=None) -> tuple[int, dict]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with self.opener.open(request, timeout=15) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            try:
                return exc.code, json.loads(body)
            except json.JSONDecodeError:
                return exc.code, {"raw": body}


def check(title: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"{PASS if ok else FAIL} {title}")
    if detail:
        print(f"         {detail}")
    if not ok:
        failures += 1


CARD = {"insurer_no": "0000", "insurance_symbol": "ABCD", "insurance_no": "0000"}

# 우편 접수 검증은 명부에 없는 사람을 쓴다.
# 이 스크립트를 두 번 연속 돌려도 중복 예약(BR-03)에 걸리지 않도록,
# 실행할 때마다 다른 이름·전화번호를 만든다. 검증이 실행 순서에 기대면
# 「어제는 됐는데 오늘은 안 된다」가 되어 아무것도 증명하지 못한다.
_RUN_TAG = datetime.now().strftime("%m%d%H%M%S")


TEST_LAST_NAME_PREFIX = "検証"


def unique_person(suffix: str) -> dict:
    tag = f"{_RUN_TAG}{suffix}"
    return {
        "last_name": f"{TEST_LAST_NAME_PREFIX}{suffix}",
        "first_name": f"太郎{suffix}",
        "last_name_kana": "ケンショウ",
        "first_name_kana": "タロウ",
        "gender": "M",
        "birth_date": "1968-03-15",
        "tel_mobile": f"090-{tag[:4]}-{tag[4:8]}",
    }


def clean_previous_runs(extra_numbers: list[str] | None = None) -> int:
    """이전 실행이 남긴 예약을 지운다.

    검증이 몇 번째 실행인지에 따라 결과가 달라지면 아무것도 증명하지 못한다.
    이 스크립트가 만든 예약(성이 「検証」로 시작)을 골라 지우고,
    그 예약이 잡고 있던 자리도 함께 되돌린다.

    조회 검증(㉛)은 명부의 田中 太郎 로 예약을 만든다. 성이 「検証」가 아니므로
    예약번호를 따로 넘겨 함께 지운다. 남겨 두면 다음 실행의 ①이
    「이미 예약이 있습니다」가 되어 처음부터 무너진다.
    """
    from sqlalchemy import delete, or_

    from app.models.reservation import ContactHistory, ReservationOption

    db = SessionLocal()
    try:
        conditions = [Reservation.last_name.like(f"{TEST_LAST_NAME_PREFIX}%")]
        if extra_numbers:
            conditions.append(
                Reservation.reservation_no.in_([n for n in extra_numbers if n])
            )

        rows = db.execute(
            select(Reservation).where(or_(*conditions))
        ).scalars().unique().all()

        for reservation in rows:
            # `SlotView` 는 읽기 전용이다. 예약 수를 되돌리는 것은 그리드가
            # 아니라 `reservation_counts` 의 일이므로 어댑터를 통해 내린다.
            index = time_grid.index_of(reservation.start_time)
            if index is not None and reservation.status != "CANCELLED":
                grid.reserved_delta(db, reservation.schedule_id, index, -1)

            db.execute(
                delete(ReservationOption).where(
                    ReservationOption.reservation_id == reservation.id
                )
            )
            db.execute(
                delete(ContactHistory).where(
                    ContactHistory.reservation_id == reservation.id
                )
            )
            db.delete(reservation)

        db.commit()
        return len(rows)
    finally:
        db.close()

def clean_lookup_attempts() -> int:
    """예약 조회 시도 제한 기록을 지운다. (services/lookup_service.reset)"""
    from app.services import lookup_service

    db = SessionLocal()
    try:
        return lookup_service.reset(db)
    finally:
        db.close()


APPLICANT = {
    "postal_code": "101-0021",
    "address": "東京都千代田区外神田",
    "address_detail": "1-2-3",
    "building": "테스트빌딩 501",
    "tel_mobile": "090-1111-2222",
    "tel_home": "",
    "email": "taro@example.jp",
}


def _bookable_slots():
    """웹에서 실제로 예약할 수 있는 슬롯 조건.

    날짜가 남아 있다고 예약할 수 있는 것이 아니다. 그 **회차의 접수 마감일**
    (予約終了) 이 지났으면 웹 접수는 거절된다. 검진일은 두 달 뒤인데 접수는
    이미 끝난 회차가 흔하므로(마감은 개최일 14일 전) 이 조건을 빼면 테스트가
    마감된 회차를 골라 BOOKING_CLOSED 를 맞는다.

    마감은 **회장이 아니라 회차**마다 다르다. 같은 회장이 9월과 12월에
    열면 9월분은 마감이고 12월분은 열려 있다.
    """
    return (
        select(HospitalSchedule)
        .join(Hospital, Hospital.id == HospitalSchedule.hospital_id)
        .where(
            HospitalSchedule.event_date > date.today(),
            Hospital.is_visible.is_(True),
            HospitalSchedule.is_visible.is_(True),
            or_(
                HospitalSchedule.booking_close_date.is_(None),
                HospitalSchedule.booking_close_date >= date.today(),
            ),
        )
    )


def find_open_slot(exclude_ids: set[int]) -> tuple[int, int, date, str]:
    """빈자리가 있는 시간대를 하나 찾는다."""
    db = SessionLocal()
    try:
        schedules = db.execute(
            _bookable_slots().order_by(HospitalSchedule.event_date).limit(200)
        ).scalars().all()

        for schedule in schedules:
            for view in grid.views_of(schedule):
                if view.is_available and view.id not in exclude_ids:
                    return view.id, view.hospital_id, view.slot_date, view.time_label
        raise RuntimeError("빈 시간대를 찾지 못했습니다.")
    finally:
        db.close()


def count_slots(hospital_id: int, target: date) -> int:
    """그 회장의 그 날 시간표가 몇 칸인가."""
    db = SessionLocal()
    try:
        return len(grid.slots_for_date(db, hospital_id, target))
    finally:
        db.close()


# 만석 시뮬레이션으로 손댄 칸. 시험이 끝나면 원래 값으로 되돌린다.
#
# 되돌리지 않으면 **검증 스크립트가 계속 실패한다.** 예약이 없는데 예약
# 수만 12로 적힌 칸이 남기 때문이다. 그리고 그 실패는 진짜 어긋남과
# 구별되지 않아, 얼마 지나지 않아 아무도 검증 결과를 보지 않게 된다.
_FILLED_CELL: tuple[int, int, int] | None = None


def make_full_slot() -> int:
    """정원을 다 채운 시간대를 하나 만든다. (만석 거절 확인용)

    가장 늦은 회차의 첫 칸을 쓴다. 다른 시험이 고른 시간대와 겹치면
    「만석이라 거절」과 「방금 다른 시험이 채웠다」를 구별할 수 없다.
    """
    global _FILLED_CELL
    db = SessionLocal()
    try:
        schedule = db.execute(
            _bookable_slots().order_by(HospitalSchedule.event_date.desc()).limit(1)
        ).scalars().one()
        counts = grid.counts_of(db, schedule)
        index = schedule.open_indexes()[0]
        _FILLED_CELL = (schedule.id, index, counts.reserved_at(index))
        counts.set_reserved_at(index, schedule.capacity_at(index) or 0)
        db.commit()
        return time_grid.slot_id(schedule.id, index)
    finally:
        db.close()


def restore_full_slot() -> None:
    """`make_full_slot` 이 채운 칸을 원래대로 되돌린다."""
    global _FILLED_CELL
    if _FILLED_CELL is None:
        return

    schedule_id, index, before = _FILLED_CELL
    db = SessionLocal()
    try:
        schedule = db.get(HospitalSchedule, schedule_id)
        if schedule is not None:
            grid.counts_of(db, schedule).set_reserved_at(index, before)
            db.commit()
    finally:
        db.close()
        _FILLED_CELL = None


def main() -> int:
    # 도중에 예외로 끝나도 만석 시뮬레이션으로 손댄 칸은 반드시 되돌린다.
    # 예전에는 마지막 줄에서만 되돌려, 검증이 중간에 죽으면 예약이 없는
    # 칸에 「정원만큼 예약됨」이 남아 이용자 화면에서 그 시간대가 사라졌다.
    try:
        return _run()
    finally:
        restore_full_slot()


def _run() -> int:
    base = _base()
    user = Client(base)

    print("=" * 70)
    print(f" 예약 확정 · 관리 화면 API 검증  ({base})")
    print("=" * 70)

    cleaned = clean_previous_runs()
    if cleaned:
        print(f" 이전 실행이 남긴 예약 {cleaned}건을 정리했습니다.")

    # 조회 검증(㉛)은 일부러 빗나간 번호로 두드린다. 그 기록이 남아 있으면
    # 다음 실행이 「시도가 너무 많습니다」로 막혀, 몇 번째 실행인지에 따라
    # 결과가 달라진다. 그런 검증은 아무것도 증명하지 못한다.
    cleared = clean_lookup_attempts()
    if cleared:
        print(f" 이전 실행이 남긴 조회 시도 기록 {cleared}건을 지웠습니다.")

    if cleaned or cleared:
        print("-" * 70)

    from scripts._preconditions import active_reservations_of_test_person, explain_blocked

    blocking = active_reservations_of_test_person()
    if blocking:
        explain_blocked(blocking)
        return 2

    # ======================================================================
    # ① 본인 확인 → 예약 확정
    # ======================================================================
    status, body = user.call(
        "POST",
        "/api/v1/reservations/verify",
        {
            "last_name": "田中", "first_name": "太郎",
            "last_name_kana": "タナカ", "first_name_kana": "タロウ",
            "gender": "M", "birth_date": "1970-05-12", **CARD,
        },
    )
    token = (body.get("data") or {}).get("verify_token")
    check(
        "① 본인 확인 통과 → 토큰 발급",
        status == 200 and body["data"]["status"] == "ELIGIBLE" and bool(token),
        f"status={body.get('data', {}).get('status')}",
    )

    slot_id, hospital_id, slot_date, time_label = find_open_slot(set())

    status, body = user.call(
        "POST",
        "/api/v1/reservations",
        {"verify_token": token, "slot_id": slot_id, "options": [], **APPLICANT},
    )
    reserved_no = (body.get("data") or {}).get("reservation_no", "")
    check(
        "② 예약 확정 → 예약번호 발행",
        status == 200 and len(reserved_no) == res_no.LENGTH,
        f"예약번호={reserved_no} / {slot_date} {time_label}",
    )

    # 예약번호 형식 — 영문 대소문자와 숫자만으로 이루어진 12자
    check(
        "③ 예약번호가 영숫자 12자 형식이다",
        res_no.is_valid(reserved_no),
        f"예약번호={reserved_no}",
    )

    # 정원이 실제로 1 줄었는지
    db = SessionLocal()
    try:
        slot = grid.find(db, slot_id)
        reservation = db.execute(
            select(Reservation).where(Reservation.reservation_no == reserved_no)
        ).scalars().one_or_none()
        check(
            "④ 예약 확정 시 슬롯의 예약 수가 증가",
            reservation is not None and slot.reserved_count > 0,
            f"슬롯 {slot.reserved_count}/{slot.capacity}",
        )
        reservation_id = reservation.id if reservation else 0
    finally:
        db.close()

    # ======================================================================
    # ⑤ 중복 예약 거절 (BR-03)
    # ======================================================================
    other_slot_id, _, _, _ = find_open_slot({slot_id})
    status, body = user.call(
        "POST",
        "/api/v1/reservations",
        {"verify_token": token, "slot_id": other_slot_id, "options": [], **APPLICANT},
    )
    check(
        "⑤ 같은 사람이 다시 예약 → 중복 거절",
        status == 409 and body["error"]["code"] == "DUPLICATE_RESERVATION",
        f"{status} {body.get('error', {}).get('message', '')[:40]}",
    )

    # ======================================================================
    # ⑥ 본인 확인 없이 예약
    # ======================================================================
    status, body = user.call(
        "POST",
        "/api/v1/reservations",
        {"verify_token": "위조된토큰", "slot_id": other_slot_id, "options": [], **APPLICANT},
    )
    check(
        "⑥ 위조 토큰으로 예약 → 거절",
        status == 409 and body["error"]["code"] == "VERIFY_REQUIRED",
        f"{status} {body.get('error', {}).get('code')}",
    )

    # ======================================================================
    # ⑦ 만석 슬롯
    # ======================================================================
    status, body = user.call(
        "POST",
        "/api/v1/reservations/verify",
        {
            "last_name": "鈴木", "first_name": "一郎",
            "last_name_kana": "スズキ", "first_name_kana": "イチロウ",
            "gender": "M", "birth_date": "1965-02-20", **CARD,
        },
    )
    token2 = body["data"]["verify_token"]

    full_slot_id = make_full_slot()
    status, body = user.call(
        "POST",
        "/api/v1/reservations",
        {
            "verify_token": token2, "slot_id": full_slot_id, "options": [],
            **{**APPLICANT, "tel_mobile": "090-3333-4444", "email": ""},
        },
    )
    check(
        "⑦ 만석 슬롯에 예약 → 거절",
        status == 409 and body["error"]["code"] == "SLOT_FULL",
        f"{status} {body.get('error', {}).get('code')}",
    )

    # 전화번호 둘 다 비면 422 (BR-05)
    status, body = user.call(
        "POST",
        "/api/v1/reservations",
        {
            "verify_token": token2, "slot_id": other_slot_id, "options": [],
            **{**APPLICANT, "tel_mobile": "", "tel_home": ""},
        },
    )
    check(
        "⑧ 전화번호를 둘 다 비우면 → 입력 오류(422)",
        status == 422,
        f"{status} {(body.get('fields') or [{}])[0].get('message', '')[:50]}",
    )

    # ======================================================================
    # ⑨ 관리자 권한 3단계
    # ======================================================================
    print("-" * 70)

    anon = Client(base)
    status, _ = anon.call("GET", "/api/v1/admin/dashboard")
    check("⑨ 로그인 없이 관리 API 호출 → 401", status == 401, f"{status}")

    staff = Client(base)
    status, body = staff.call(
        "POST", "/api/v1/admin/login", {"login_id": "staff", "password": "staff1234"}
    )
    check(
        "⑩ 일반 스태프(L1) 로그인",
        status == 200 and body["data"]["level"] == 1,
        f"{body.get('data', {}).get('name')} / {body.get('data', {}).get('role_label')}",
    )

    status, _ = staff.call("GET", "/api/v1/admin/dashboard")
    check("⑪ L1 → 대시보드 접근 가능", status == 200, f"{status}")

    status, body = staff.call("GET", "/api/v1/admin/hospitals")
    check("⑫ L1 → 회장 관리 접근 거부(403)", status == 403, f"{status}")

    status, body = staff.call("GET", "/api/v1/admin/accounts")
    check("⑬ L1 → 계정 관리 접근 거부(403)", status == 403, f"{status}")

    manager = Client(base)
    manager.call(
        "POST", "/api/v1/admin/login", {"login_id": "manager", "password": "manager1234"}
    )
    status, _ = manager.call("GET", "/api/v1/admin/hospitals")
    check("⑭ L2 → 회장 관리 접근 가능", status == 200, f"{status}")

    status, _ = manager.call("GET", "/api/v1/admin/audit-logs")
    check("⑮ L2 → 조작 로그 접근 거부(403)", status == 403, f"{status}")

    admin = Client(base)
    admin.call(
        "POST", "/api/v1/admin/login", {"login_id": "admin", "password": "admin1234"}
    )
    status, body = admin.call("GET", "/api/v1/admin/audit-logs")
    check(
        "⑯ L3 → 조작 로그 접근 가능",
        status == 200 and body["data"]["total"] > 0,
        f"로그 {body.get('data', {}).get('total')}건",
    )

    status, body = admin.call(
        "POST", "/api/v1/admin/login", {"login_id": "admin", "password": "틀린비밀번호"}
    )
    check("⑰ 잘못된 비밀번호 → 401", status == 401, f"{status}")

    # ======================================================================
    # ⑱ 예약 검색 · 상세 · 취소
    # ======================================================================
    print("-" * 70)

    status, body = staff.call(
        "GET", f"/api/v1/admin/reservations?keyword={reserved_no}"
    )
    check(
        "⑱ 예약번호로 검색",
        status == 200 and body["data"]["total"] == 1,
        f"{body.get('data', {}).get('total')}건",
    )

    # 관리자 검색은 대소문자를 **뭉개서** 찾는다. 창구 담당자는 번호를 전화로
    # 듣기 때문이다(core/reservation_no.py `fold_for_search`, README).
    # 대소문자를 엄격히 가르는 것은 이용자 「予約照会」 쪽이며, ㉛ 이 그것을 본다.
    swapped = reserved_no.swapcase()
    status, body = staff.call("GET", f"/api/v1/admin/reservations?keyword={swapped}")
    check(
        "⑱-2 관리자 검색은 대소문자를 뒤집은 예약번호로도 찾는다",
        status == 200 and body["data"]["total"] == 1,
        f"{swapped} → {body.get('data', {}).get('total')}건",
    )

    status, body = staff.call("GET", "/api/v1/admin/reservations?keyword=09011112222")
    check(
        "⑲ 하이픈 없는 전화번호로 검색",
        status == 200 and body["data"]["total"] >= 1,
        f"{body.get('data', {}).get('total')}건",
    )

    status, body = staff.call("GET", f"/api/v1/admin/reservations/{reservation_id}")
    check(
        "⑳ 예약 상세 — 자동 삭제 예정 시각 포함",
        status == 200 and bool(body["data"]["expires_at"]),
        f"검진 {body['data']['slot_date']} {body['data']['time_label']}"
        f" → 삭제 예정 {body['data']['expires_at']}",
    )

    status, body = staff.call(
        "POST",
        f"/api/v1/admin/reservations/{reservation_id}/contacts",
        {"method": "TEL", "result": "NO_ANSWER", "memo": "부재중"},
    )
    check(
        "㉑ 연락 이력 추가 → 누적 횟수 안내",
        status == 200 and body["data"]["contact_count"] == 1,
        body.get("message", ""),
    )

    db = SessionLocal()
    try:
        before_reserved = grid.find(db, slot_id).reserved_count
    finally:
        db.close()

    status, body = staff.call(
        "POST",
        f"/api/v1/admin/reservations/{reservation_id}/cancel",
        {"reason": "본인 전화 연락 — 테스트"},
    )
    db = SessionLocal()
    try:
        after_reserved = grid.find(db, slot_id).reserved_count
    finally:
        db.close()

    check(
        "㉒ 예약 취소 → 정원 즉시 반환",
        status == 200
        and body["data"]["status"] == "CANCELLED"
        and after_reserved == before_reserved - 1,
        f"{before_reserved} → {after_reserved} / {body.get('message', '')}",
    )

    # ======================================================================
    # ㉓ 우편 접수 — 제1희망 만석 시 제2희망으로
    # ======================================================================
    print("-" * 70)

    good_slot_id, good_hospital_id, good_date, good_label = find_open_slot({slot_id})

    status, body = staff.call(
        "POST",
        "/api/v1/admin/reservations/postal",
        {
            **unique_person("A"),
            "insurer_no": "0000", "insurance_symbol": "ABCD", "insurance_no": "0000",
            "postal_code": "116-0012", "address": "東京都荒川区東尾久",
            "address_detail": "5-8-13",
            "slot_ids": [full_slot_id, good_slot_id],
            "option_ids": [],
        },
    )
    check(
        "㉓ 우편 접수 — 제1희망 만석 → 제2희망으로 등록",
        status == 200 and body["data"]["used_choice"] == 2,
        f"{body.get('data', {}).get('message')} / 건너뜀 {len(body.get('data', {}).get('skipped', []))}건",
    )

    defective = {
        **unique_person("B"),
        "postal_code": "", "address": "", "address_detail": "",
        "slot_ids": [good_slot_id],
        "option_ids": [],
    }

    status, body = staff.call(
        "POST", "/api/v1/admin/reservations/postal", defective
    )
    check(
        "㉔ 우편 접수 — 필수 항목 누락 시 거절",
        # 화면 문구가 일본어로 바뀌었다. 예전 한국어 문구(「비어 있습니다」)를 찾으면
        # 거절이 제대로 되어도 늘 실패한다.
        status == 409 and "未入力" in body.get("error", {}).get("message", ""),
        body.get("error", {}).get("message", "")[:70],
    )

    status, body = staff.call(
        "POST",
        "/api/v1/admin/reservations/postal",
        {**defective, "allow_defect": True},
    )
    check(
        "㉕ 우편 접수 — 불비 허용 시 임시 접수(PENDING)로 등록",
        status == 200
        and body["data"]["status"] == "PENDING"
        and body["data"]["has_defect"],
        f"불비 항목 = {body.get('data', {}).get('defect_note')}",
    )

    # ======================================================================
    # ㉖ 정원 감원 하한 (M-6)
    # ======================================================================
    print("-" * 70)

    status, body = manager.call(
        "PUT",
        f"/api/v1/admin/hospitals/{good_hospital_id}/capacity",
        {"items": [{"slot_id": good_slot_id, "capacity": 0}]},
    )
    check(
        "㉖ 예약된 인원보다 낮은 정원 → 거부",
        status == 200 and body["data"]["updated"] == 0 and body["data"]["blocked"],
        (body.get("data", {}).get("blocked") or [""])[0][:70],
    )

    # 그 날 몇 개를 건드려야 맞는지는 **데이터에 물어본다.**
    # 회장마다 여는 시간이 달라 슬롯 수가 다르다(대개 8개). 예전처럼 12로
    # 못 박아 두면, 시간표가 바뀔 때마다 기능이 아니라 검증이 깨진다.
    slot_count = count_slots(good_hospital_id, good_date)

    status, body = manager.call(
        "PUT",
        f"/api/v1/admin/hospitals/{good_hospital_id}/capacity",
        {"dates": [good_date.isoformat()], "delta": 3},
    )
    check(
        "㉗ 날짜 단위 일괄 증원",
        status == 200 and body["data"]["updated"] == slot_count,
        f"{body.get('data', {}).get('message', '')} (그 날 슬롯 {slot_count}개)",
    )

    status, body = manager.call(
        "POST",
        f"/api/v1/admin/hospitals/{good_hospital_id}/holidays",
        {"dates": [good_date.isoformat()], "closed": True},
    )
    check(
        "㉘ 휴진일 설정 → 그 날 전 슬롯 마감",
        status == 200 and body["data"]["updated"] == slot_count,
        body.get("data", {}).get("message", "")[:70],
    )

    # 되돌린다 (다른 검증에 영향을 주지 않도록)
    manager.call(
        "POST",
        f"/api/v1/admin/hospitals/{good_hospital_id}/holidays",
        {"dates": [good_date.isoformat()], "closed": False},
    )

    # ======================================================================
    # ㉙ 기간이 지난 예약의 자동 삭제
    # ======================================================================
    print("-" * 70)

    db = SessionLocal()
    try:
        target = db.execute(
            select(Reservation).where(Reservation.reservation_no == reserved_no)
        ).scalars().one_or_none()

        if target is not None:
            # 검진 시각을 2시간 전으로 밀어 「기간이 지난 예약」을 만든다
            past = datetime.now() - timedelta(hours=2)
            target.slot_date = past.date()
            target.start_time = past.time().replace(microsecond=0)
            db.commit()

        from app.services import purge_service

        before = purge_service.count_expired(db)
        deleted = purge_service.purge_expired(db)
        remaining = db.execute(
            select(Reservation).where(Reservation.reservation_no == reserved_no)
        ).scalars().one_or_none()

        check(
            "㉙ 검진 시각 + 유예 시간이 지난 예약 → 자동 삭제",
            deleted >= 1 and remaining is None,
            f"대상 {before}건 / 삭제 {deleted}건 / {reserved_no} 잔존={remaining is not None}",
        )
    finally:
        db.close()

    status, body = admin.call("GET", "/api/v1/admin/audit-logs?action=RESERVATION_PURGE")
    check(
        "㉚ 자동 삭제 사실이 조작 로그에 남는다",
        status == 200 and body["data"]["total"] >= 1,
        f"{body.get('data', {}).get('total')}건 기록됨",
    )

    # ======================================================================
    # ㉛ 예약 조회 (U-20) — 예약번호만으로, 읽기 전용
    # ======================================================================
    print("-" * 70)

    # 앞서 취소했으므로 새 예약을 하나 만들어 조회 대상으로 쓴다.
    slot_id, hospital_id, slot_date, time_label = find_open_slot(set())
    status, body = user.call(
        "POST", "/api/v1/reservations/verify",
        {
            "last_name": "田中", "first_name": "太郎",
            "last_name_kana": "タナカ", "first_name_kana": "タロウ",
            "gender": "M", "birth_date": "1970-05-12", **CARD,
        },
    )
    token = (body.get("data") or {}).get("verify_token")

    lookup_no = ""
    if token:
        status, body = user.call(
            "POST", "/api/v1/reservations",
            {"verify_token": token, "slot_id": slot_id, "options": [], **APPLICANT},
        )
        lookup_no = (body.get("data") or {}).get("reservation_no", "")

    status, body = user.call("GET", f"/api/v1/lookup?reservation_no={lookup_no}")
    data = body.get("data") or {}
    check(
        "㉛ 예약번호로 조회 — 예약 상세를 돌려준다",
        status == 200 and data.get("reservation_no") == lookup_no,
        f"{data.get('full_name')} / {data.get('status_label')} / {data.get('hospital', {}).get('name')}",
    )

    # 조회 결과에 「고칠 수 있는 것」이 들어 있으면 안 된다.
    forbidden = {"verify_token", "token", "editable", "can_cancel", "target_person_id"}
    check(
        "㉛-2 조회 결과는 읽기 전용 — 수정용 필드가 없다",
        status == 200 and not (forbidden & set(data.keys())),
        f"필드 {len(data)}개 / 변경 안내 = {str(data.get('change_notice'))[:34]}…",
    )

    status, body = user.call(
        "GET", f"/api/v1/lookup?reservation_no={lookup_no.swapcase()}"
    )
    check(
        "㉛-3 대소문자를 뒤집은 예약번호로는 조회되지 않는다",
        status == 404,
        f"{lookup_no.swapcase()} → {status}",
    )

    status, body = user.call("GET", "/api/v1/lookup?reservation_no=short")
    err_a = (body.get("error") or {}).get("code")
    status2, body2 = user.call("GET", "/api/v1/lookup?reservation_no=ZZZZ99999999")
    err_b = (body2.get("error") or {}).get("code")
    check(
        "㉛-4 형식 오류와 없는 번호를 구별해 알려 주지 않는다",
        status == 404 and status2 == 404 and err_a == err_b,
        f"형식 오류={status}/{err_a}  없는 번호={status2}/{err_b}",
    )

    # 예약번호가 곧 열쇠이므로, 찍어서 두드리는 것이 유일한 공격 경로다.
    # 무제한으로 두드릴 수 있게 두지 않는다는 사실을 여기서 확인한다.
    from app.services import lookup_service

    clean_lookup_attempts()
    blocked_at = 0
    for attempt in range(1, lookup_service.FAIL_LIMIT + 3):
        st, _ = user.call("GET", f"/api/v1/lookup?reservation_no=ZZZZ9999{attempt:04d}")
        if st == 429:
            blocked_at = attempt
            break

    # 한도째 실패가 「막는다」를 켜고, 그 다음 요청부터 거절된다.
    # 그래서 429 는 한도 + 1 번째에 나온다.
    check(
        f"㉛-5 빗나간 조회가 쌓이면 막는다 (한도 {lookup_service.FAIL_LIMIT}회)",
        blocked_at == lookup_service.FAIL_LIMIT + 1,
        f"{blocked_at}회째 요청에서 429 (한도 {lookup_service.FAIL_LIMIT}회 실패 직후)",
    )

    # 막힌 동안에는 맞는 번호로도 열리지 않는다
    status, body = user.call("GET", f"/api/v1/lookup?reservation_no={lookup_no}")
    check(
        "㉛-6 막힌 동안에는 맞는 번호로도 조회되지 않는다",
        status == 429,
        f"{status}",
    )
    clean_lookup_attempts()

    status, body = user.call("GET", "/api/v1/lookup?reservation_no=ZZZZ99999999")
    check(
        "㉛-7 조회 실패 시 문의처를 함께 돌려준다",
        bool((body2.get("error") or {}).get("contact", {}).get("tel")),
        f"문의처={(body2.get('error') or {}).get('contact', {}).get('tel')}",
    )

    # ======================================================================
    # ㉜ 본인 확인은 예약번호를 알려 주지 않는다
    # ======================================================================
    print("-" * 70)

    status, body = user.call(
        "POST", "/api/v1/reservations/verify",
        {
            "last_name": "田中", "first_name": "太郎",
            "last_name_kana": "タナカ", "first_name_kana": "タロウ",
            "gender": "M", "birth_date": "1970-05-12", **CARD,
        },
    )
    data = body.get("data") or {}
    # 방금 예약했으므로 ALREADY_RESERVED 가 되어야 한다.
    check(
        "㉜ 이미 예약이 있으면 예약번호·신원을 돌려주지 않는다",
        status == 200
        and data.get("status") == "ALREADY_RESERVED"
        and not data.get("reservation_no")
        and not data.get("person")
        and len(data.get("hints") or []) >= 3,
        f"status={data.get('status')} / 안내 {len(data.get('hints') or [])}건 / "
        f"응답 본문에 예약번호 포함={lookup_no in str(body)}",
    )

    # ======================================================================
    # ㉝ 주소 검색 (U-14)
    # ======================================================================
    print("-" * 70)

    status, body = user.call("GET", "/api/v1/postal/search?keyword=1010021")
    items = ((body.get("data") or {}).get("items")) or []
    check(
        "㉝ 우편번호로 주소 검색",
        status == 200 and items and items[0]["address"] == "東京都千代田区外神田",
        f"{items[0]['zipcode']} {items[0]['address']}" if items else "결과 없음",
    )

    status, body = user.call(
        "GET", "/api/v1/postal/search?keyword=" + quote("千代田区外神田")
    )
    items = ((body.get("data") or {}).get("items")) or []
    check(
        "㉝-2 주소 일부로 검색",
        status == 200 and items and items[0]["zipcode"] == "1010021",
        f"{len(items)}건 / 선두 {items[0]['zipcode'] if items else '-'}",
    )

    status, body = user.call("GET", "/api/v1/postal/search?keyword=" + quote("あ"))
    check(
        "㉝-3 너무 짧은 검색어는 안내와 함께 거절",
        status == 422,
        f"{status} — {(body.get('error') or {}).get('message', '')[:32]}…",
    )

    # ======================================================================
    # ㉞ 이메일 형식 검증
    # ======================================================================
    print("-" * 70)

    status, body = user.call(
        "POST", "/api/v1/reservations",
        {"verify_token": "x", "slot_id": slot_id, "options": [],
         **{**APPLICANT, "email": "not-an-email"}},
    )
    fields = [f["name"] for f in (body.get("fields") or [])]
    check(
        "㉞ 형식이 틀린 이메일은 접수 전에 거절",
        status == 422 and "email" in fields,
        f"{status} / 거부 필드={fields}",
    )

    # 이 스크립트가 만든 예약을 남기지 않는다.
    # 남겨 두면 다음 실행이 「이미 예약된 분입니다」로 막히고,
    # 관리 화면에도 정체불명의 「検証」 씨가 쌓인다.
    # 조회 검증(㉛)이 만든 예약은 성이 「検証」가 아니므로 번호로 지정해 지운다.
    clean_previous_runs([lookup_no])
    clean_lookup_attempts()
    # 만석 시뮬레이션으로 손댄 칸도 되돌린다. 남겨 두면 예약이 없는데
    # 예약 수만 남아 검증 스크립트가 계속 실패한다.
    restore_full_slot()

    # ======================================================================
    print("=" * 70)
    if failures:
        print(f" 결과: {failures}건 실패")
    else:
        print(" 결과: 전부 통과")
    print("=" * 70)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
