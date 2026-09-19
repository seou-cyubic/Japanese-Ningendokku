"""검증 스크립트의 전제 조건.

`smoke_test` 와 `reservation_api_test` 는 명부의 몇 분(田中 太郎 등)을 **「예약이 없는
사람」**으로 쓴다. 누군가 화면에서 그분으로 예약을 한 번 넣으면, 그 뒤로는 두 스크립트가
원인을 말하지 않고 수십 줄씩 실패했다.

남의 예약을 스크립트가 지우지는 않는다(개발 DB 라도 사람이 넣은 데이터다).
대신 **처음에 멈추고 무엇을 하면 되는지** 알린다.
"""

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.reservation import Reservation


# 검증 스크립트가 「예약이 없는 사람」으로 쓰는 명부 대상자. (성, 이름, 생년월일)
UNRESERVED_TEST_PEOPLE = (
    ("田中", "太郎", "1970-05-12"),
    ("高橋", "美咲", "1982-07-08"),
    ("渡辺", "由美", "1975-12-15"),
)


def active_reservations_of_test_person(people=UNRESERVED_TEST_PEOPLE) -> list[str]:
    """그분들의 취소되지 않은 예약 (「이름 예약번호」). 비어 있어야 검증을 돌릴 수 있다."""
    from datetime import date

    db = SessionLocal()
    try:
        found: list[str] = []
        for last, first, birth in people:
            for number in db.execute(
                select(Reservation.reservation_no).where(
                    Reservation.last_name == last,
                    Reservation.first_name == first,
                    Reservation.birth_date == date.fromisoformat(birth),
                    Reservation.status != "CANCELLED",
                )
            ).scalars():
                found.append(f"{last} {first} {number}")
        return found
    finally:
        db.close()


def explain_blocked(numbers: list[str]) -> None:
    print("[中止] 検証用の受診対象者に有効な予約があります: " + ", ".join(numbers))
    print("       この検証はその方々を「予約なし」として使います。")
    print("       管理画面でその予約をキャンセルするか、")
    print("       python -m scripts.setup_db --reset で DB を作り直してから再実行してください。")
