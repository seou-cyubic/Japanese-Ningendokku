"""예약 테스트 데이터 투입.

    python -m scripts.seed_reservations          # 없으면 만든다
    python -m scripts.seed_reservations --reset  # 기존 예약을 전부 지우고 다시 만든다

선행 조건
--------
    python -m scripts.init_db
    python -m scripts.import_hospitals

무엇을 만드는가
--------------
① **명부 대상자 3명의 예약** — 본인 확인이 「이미 예약 있음」으로 판정되어야
   하는 사람들이다. 예전에는 명부에 플래그로 적어 두었으나, 이제 예약 유무는
   예약 테이블만이 답하므로 실제 예약을 만들어야 한다.

② **관리 화면 확인용 예약 약 60건** — 확정 · 임시(불비) · 취소가 섞여 있고,
   웹과 우편이 섞여 있으며, 연락 이력이 쌓인 건도 있다.
   예약이 하나도 없는 관리 화면은 아무것도 검증할 수 없다.

슬롯의 `reserved_count` 에 대하여
--------------------------------
CSV 로 들어온 `reserved_count` 는 「이 시스템 이전부터 잡혀 있던 예약」으로
본다. 여기서 만드는 예약은 그 위에 1씩 더한다. 그래야 취소 시 정원이
정상적으로 되돌아가는 흐름을 그대로 확인할 수 있다.
"""

import scripts._console  # noqa: F401  (콘솔 UTF-8 보정)
import random
import sys
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select

from app.core import time_grid
from app.core.dates import fiscal_year
from app.core.database import SessionLocal
from app.models.admin import AdminUser
from app.models.exam_option import ExamOption
from app.models.hospital import Hospital, HospitalSchedule, ReservationCount
from app.models.reservation import (
    ContactHistory,
    Reservation,
    ReservationOption,
)
from app.models.target_person import TargetPerson
from app.services import mail_service
from app.services import slot_grid_service as grid
from app.services.slot_grid_service import SlotView
from app.services.reservation_service import issue_reservation_no

random.seed(20260806)

# 명부에서 「이미 예약 있음」이 되어야 하는 사람 (성, 이름, 성 후리가나)
PRE_RESERVED = [
    ("佐藤", "花子", "サトウ"),
    ("伊藤", "健二", "イトウ"),
    ("中田", "健", "ナカダ"),   # ナカタ 씨는 미예약이어야 한다
]

# 관리 화면 확인용 가상 신청자 (명부에 없는 사람 = 우편 접수로 들어온 사람 포함)
FAKE_PEOPLE = [
    ("小林", "誠",   "コバヤシ", "マコト",   "M", date(1961, 3, 14)),
    ("加藤", "洋子", "カトウ",   "ヨウコ",   "F", date(1957, 8, 22)),
    ("吉田", "健一", "ヨシダ",   "ケンイチ", "M", date(1972, 11, 5)),
    ("山田", "光子", "ヤマダ",   "ミツコ",   "F", date(1964, 1, 30)),
    ("佐々木", "隆", "ササキ",   "タカシ",   "M", date(1955, 6, 18)),
    ("松本", "真理", "マツモト", "マリ",     "F", date(1979, 9, 9)),
    ("井上", "義男", "イノウエ", "ヨシオ",   "M", date(1951, 12, 2)),
    ("木村", "久美", "キムラ",   "クミ",     "F", date(1968, 4, 27)),
    ("清水", "剛",   "シミズ",   "ツヨシ",   "M", date(1974, 7, 11)),
    ("斎藤", "節子", "サイトウ", "セツコ",   "F", date(1953, 2, 6)),
    ("林",   "浩二", "ハヤシ",   "コウジ",   "M", date(1966, 10, 19)),
    ("森",   "陽子", "モリ",     "ヨウコ",   "F", date(1981, 5, 25)),
    ("池田", "秀夫", "イケダ",   "ヒデオ",   "M", date(1958, 3, 8)),
    ("橋本", "麻衣", "ハシモト", "マイ",     "F", date(1985, 12, 21)),
    ("石川", "康弘", "イシカワ", "ヤスヒロ", "M", date(1963, 8, 3)),
]

ADDRESSES = [
    ("101-0021", "東京都千代田区外神田", "1-2-3", ""),
    ("160-0022", "東京都新宿区新宿", "3-15-7", "新宿マンション302"),
    ("150-0031", "東京都渋谷区桜丘町", "12-4", ""),
    ("113-0033", "東京都文京区本郷", "5-24-6", "本郷ハイツ101"),
    ("130-0013", "東京都墨田区錦糸", "2-3-11", ""),
    ("140-0002", "東京都品川区東品川", "4-12-8", "シーサイドレジデンス705"),
    ("174-0071", "東京都板橋区常盤台", "1-22-9", ""),
    ("116-0012", "東京都荒川区東尾久", "5-8-13", ""),
]

# (사유, 취소의 종류). 종류를 비워 두면 「구분 이전의 옛 취소」로 보여,
# 새로 설치한 화면에서부터 대시보드에 「キャンセル（種類なし）」가 뜬다.
CANCEL_REASONS = [
    ("本人電話連絡 — 受診日に予定が入ったため", "ADVANCE"),
    ("本人電話連絡 — 他会場への変更希望", "ADVANCE"),
    ("3回連絡後、連絡がつかないためキャンセル (BR-06)", "SAME_DAY"),
]

CONTACT_MEMOS = [
    "保険者番号が未入力のため確認。本人が健康保険証を探しているとのことで、再度掛け直す予定",
    "不在。留守番電話に接続",
    "住所の番地未入力分を確認して補完",
]


def _pick_slot(db, hospital: Hospital, after: date) -> SlotView | None:
    """빈자리가 있는 시간대 하나를 고른다."""
    schedules = db.execute(
        select(HospitalSchedule)
        .where(
            HospitalSchedule.hospital_id == hospital.id,
            HospitalSchedule.event_date >= after,
        )
        .order_by(HospitalSchedule.event_date)
    ).scalars().all()

    available = [
        view
        for schedule in schedules
        for view in grid.views_of(schedule)
        if view.is_available
    ]
    return random.choice(available) if available else None


def _fill_common(reservation: Reservation) -> None:
    postal, address, detail, building = random.choice(ADDRESSES)
    reservation.postal_code = postal
    reservation.address = address
    reservation.address_detail = detail
    reservation.building = building
    reservation.tel_mobile = (
        f"090-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}"
    )
    if random.random() < 0.3:
        reservation.tel_home = f"03-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}"
    if random.random() < 0.65:
        reservation.email = f"user{random.randint(100, 999)}@example.jp"


def _attach_random_options(db, reservation: Reservation, options: list[ExamOption]) -> None:
    from app.core.dates import age_on

    age = age_on(reservation.birth_date, reservation.slot_date)
    eligible = [o for o in options if o.matches(reservation.gender, age)]
    if not eligible:
        return

    for option in random.sample(eligible, k=min(len(eligible), random.randint(0, 2))):
        db.add(
            ReservationOption(
                reservation_id=reservation.id,
                exam_option_id=option.id,
                option_code=option.code,
                option_name=option.name,
            )
        )


def reset_reservations(db) -> None:
    """기존 예약을 지우고 예약 수를 0 으로 되돌린다.

    한 건씩 빼는 대신 통째로 0 으로 만든다. 예약을 전부 지우는 자리에서는
    「0 이 정답」이 자명하고, 한 건씩 빼다 하나라도 어긋나면 그 뒤로
    남은 좌석이 계속 틀린다.
    """
    reservations = db.execute(select(Reservation)).scalars().unique().all()

    for counts in db.execute(select(ReservationCount)).scalars():
        for index in time_grid.indexes():
            counts.set_reserved_at(index, 0)

    db.execute(delete(ContactHistory))
    db.execute(delete(ReservationOption))
    db.execute(delete(Reservation))
    db.commit()
    print(f"      既存の予約 {len(reservations)}件を削除 (--reset)")


def main(argv: list[str] | None = None) -> int:
    reset = "--reset" in (sys.argv[1:] if argv is None else argv)
    db = SessionLocal()

    try:
        hospitals = db.execute(select(Hospital).order_by(Hospital.id)).scalars().all()
        if not hospitals:
            print("会場データがありません。先に python -m scripts.import_hospitals を実行してください。")
            return 1

        options = db.execute(select(ExamOption)).scalars().all()
        staff = db.execute(
            select(AdminUser).where(AdminUser.role == "STAFF")
        ).scalars().first()

        if reset:
            reset_reservations(db)

        existing = db.execute(select(Reservation).limit(1)).scalars().first()
        if existing is not None:
            print("すでに予約データがあります。作り直すには --reset を付けてください。")
            return 0

        # 오늘 이후의 슬롯에만 넣는다. 지난 날짜에 넣으면 자동 정리에 바로 지워진다.
        after = date.today()
        created = 0

        # ------------------------------------------------------------------
        # ① 명부 대상자의 예약 (본인 확인 = ALREADY_RESERVED)
        # ------------------------------------------------------------------
        for last, first, last_kana in PRE_RESERVED:
            person = None
            for candidate in db.execute(
                select(TargetPerson).where(
                    TargetPerson.last_name == last,
                    TargetPerson.first_name == first,
                )
            ).scalars():
                if candidate.last_name_kana == last_kana:
                    person = candidate
                    break

            if person is None:
                print(f"      ! 名簿に {last} {first} ({last_kana}) が見つかりませんでした")
                continue

            hospital = random.choice(hospitals)
            slot = _pick_slot(db, hospital, after)
            if slot is None:
                continue

            year = fiscal_year(slot.slot_date)
            reservation = Reservation(
                reservation_no=issue_reservation_no(db),
                schedule_id=slot.schedule_id,
                hospital_id=hospital.id,
                slot_date=slot.slot_date,
                start_time=slot.start_time,
                end_time=slot.end_time,
                channel="WEB",
                status="CONFIRMED",
                target_person_id=person.id,
                last_name=person.last_name,
                first_name=person.first_name,
                last_name_kana=person.last_name_kana,
                first_name_kana=person.first_name_kana,
                gender=person.gender,
                birth_date=person.birth_date,
                insurer_no=person.insurer_no,
                insurance_symbol=person.insurance_symbol,
                insurance_no=person.insurance_no,
                fiscal_year=year,
            )
            _fill_common(reservation)
            db.add(reservation)
            grid.reserved_delta(db, slot.schedule_id, slot.index, 1)
            db.flush()
            _attach_random_options(db, reservation, options)
            mail_service.send_reserve_complete(db, reservation)
            created += 1

        db.commit()
        print(f"      名簿の対象者の予約 {created}件を作成")

        # ------------------------------------------------------------------
        # ② 관리 화면 확인용 예약
        # ------------------------------------------------------------------
        bulk = 0
        cancelled = pending = 0

        for index in range(60):
            last, first, last_kana, first_kana, gender, birth = random.choice(FAKE_PEOPLE)
            hospital = random.choice(hospitals)
            slot = _pick_slot(db, hospital, after)
            if slot is None:
                continue

            year = fiscal_year(slot.slot_date)
            is_postal = random.random() < 0.35
            roll = random.random()

            if roll < 0.10:
                status, has_defect = "PENDING", True
            elif roll < 0.20:
                status, has_defect = "CANCELLED", False
            else:
                status, has_defect = "CONFIRMED", False

            reservation = Reservation(
                reservation_no=issue_reservation_no(db),
                schedule_id=slot.schedule_id,
                hospital_id=hospital.id,
                slot_date=slot.slot_date,
                start_time=slot.start_time,
                end_time=slot.end_time,
                channel="POSTAL" if is_postal else "WEB",
                status=status,
                last_name=last,
                first_name=first,
                last_name_kana=last_kana,
                first_name_kana=first_kana,
                gender=gender,
                birth_date=birth,
                insurer_no="0000",
                insurance_symbol="ABCD",
                insurance_no=f"{random.randint(1000, 9999)}",
                fiscal_year=year,
                created_by_admin_id=staff.id if (is_postal and staff) else None,
            )
            _fill_common(reservation)

            if has_defect:
                # 불비 = 필수 항목이 비어 있는 상태. 그 상태 그대로 재현한다.
                reservation.insurer_no = ""
                reservation.has_defect = True
                reservation.defect_note = "保険者番号"
                reservation.memo = "郵送申請書に保険者番号の記載なし"

            if status == "CANCELLED":
                reservation.cancelled_at = datetime.now() - timedelta(
                    days=random.randint(1, 10)
                )
                reservation.cancel_reason, reservation.cancel_type = random.choice(
                    CANCEL_REASONS
                )
                cancelled += 1
            else:
                # 취소된 예약은 자리를 차지하지 않는다
                grid.reserved_delta(db, slot.schedule_id, slot.index, 1)

            if status == "PENDING":
                pending += 1

            db.add(reservation)
            db.flush()
            _attach_random_options(db, reservation, options)

            # 불비 건에는 연락 이력을 쌓아 둔다 (M-3 화면 확인용)
            if has_defect and staff is not None:
                for n in range(random.randint(1, 3)):
                    db.add(
                        ContactHistory(
                            reservation_id=reservation.id,
                            contacted_at=datetime.now() - timedelta(days=3 - n),
                            admin_user_id=staff.id,
                            admin_name=staff.name,
                            method="TEL" if n < 2 else "MAIL",
                            result="NO_ANSWER" if n < 2 else "CONNECTED",
                            memo=CONTACT_MEMOS[n % len(CONTACT_MEMOS)],
                        )
                    )

            if status == "CONFIRMED":
                mail_service.send_reserve_complete(db, reservation)

            bulk += 1

            if index % 20 == 0:
                db.flush()

        db.commit()

        total = db.execute(select(Reservation)).scalars().unique().all()

        print(f"      管理画面用の予約 {bulk}件を作成"
              f" (仮受付 {pending} / キャンセル {cancelled})")
        print("-" * 70)
        print(f"合計 予約 {len(total)}件")
        print("\n管理画面で確認してください : http://127.0.0.1:8000/admin/\n")
        return 0

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
