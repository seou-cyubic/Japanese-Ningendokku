"""정규화가 실제로 이뤄졌는지 DB 를 열어 확인한다.

    python -m scripts.verify_normalization
    python -m scripts.verify_normalization --file data/hospitals/test_data.csv

`--file` 을 주면 그 시트를 **정답지로 삼아** DB 와 대조한다. 주지 않으면
구조만 본다(중복 회차·빠진 예약 수 행 등).

왜 임포터의 출력만으로는 부족한가
---------------------------------
임포터는 자기가 무엇을 넣었다고 **말할** 뿐이다. 넣었다고 말한 것과
DB 에 실제로 들어간 것이 같은지는 다른 질문이다. 특히 이번처럼 한 행이
여러 테이블로 나뉘는 변경에서는, 회차는 만들어졌는데 시간표가 엉뚱한
회차에 붙는 식의 어긋남이 조용히 생긴다.

무엇을 보는가
-------------
    구조   중복 회차 / 빠진 예약 수 행 / 열지 않는 칸의 마감 표시
    내용   시트의 (회장, 개최일, 시간대, 정원) 이 DB 에 그대로 있는가
    멱등   같은 시트를 두 번 넣어도 회차·시간대 수가 늘지 않는가 (호출자가 확인)

예약 수의 정합성은 `verify_capacity_grid` 가 본다. 이 스크립트는
**시트에서 들어온 것**이 제대로 들어갔는지만 답한다.
"""

import scripts._console  # noqa: F401  (콘솔 UTF-8 보정)
import sys
from datetime import date

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.core import time_grid
from app.models.hospital import Hospital, HospitalSchedule
from app.services import slot_grid_service as grid
from scripts import import_hospitals as importer


class Report:
    """확인 결과. 실패가 하나라도 있으면 종료 코드가 1 이 된다."""

    def __init__(self) -> None:
        self.checks = 0
        self.failures: list[str] = []

    def ok(self, label: str) -> None:
        self.checks += 1
        print(f"   [OK]   {label}")

    def fail(self, label: str, detail: str = "") -> None:
        self.checks += 1
        self.failures.append(f"{label}{' — ' + detail if detail else ''}")
        print(f"   [FAIL] {label}")
        if detail:
            print(f"          {detail}")

    def check(self, condition: bool, label: str, detail: str = "") -> None:
        self.ok(label) if condition else self.fail(label, detail)


# --------------------------------------------------------------------------
# 구조 검사 — 시트 없이도 항상 참이어야 하는 것
# --------------------------------------------------------------------------


def check_structure(db, report: Report) -> None:
    print("\n 구조")

    # 시간표가 회차 행의 그리드가 되면서 「고아 슬롯」이라는 상태 자체가
    # 사라졌다. 칸은 회차 행의 칼럼이라 회차 없이 존재할 수 없다.
    # 대신 그리드가 스스로 모순되지 않는지 본다.

    schedules = db.execute(select(HospitalSchedule)).scalars().all()

    duplicates = db.execute(
        select(HospitalSchedule.hospital_id, HospitalSchedule.event_date, func.count())
        .group_by(HospitalSchedule.hospital_id, HospitalSchedule.event_date)
        .having(func.count() > 1)
    ).all()
    report.check(
        not duplicates,
        "같은 회장에 같은 개최일이 두 번 있지 않다",
        f"중복 {len(duplicates)}쌍",
    )

    no_counts = [s for s in schedules if s.counts is None]
    report.check(
        not no_counts,
        "모든 회차에 예약 수 행이 있다",
        f"없는 회차 {len(no_counts)}건",
    )

    # 열지 않는 칸(정원 NULL)에 마감 비트가 서 있으면, 화면에서 사라진
    # 시간대가 「마감」으로 되살아난다.
    stray: list[str] = []
    for schedule in schedules:
        for index in time_grid.closed_indexes(schedule.closed_mask):
            if schedule.capacity_at(index) is None:
                stray.append(f"{schedule.event_date} {time_grid.label(index)}")
    report.check(
        not stray,
        "열지 않는 시간대에 마감 표시가 남아 있지 않다",
        " / ".join(stray[:5]),
    )

    no_schedule = db.execute(
        select(func.count())
        .select_from(Hospital)
        .outerjoin(HospitalSchedule, HospitalSchedule.hospital_id == Hospital.id)
        .where(HospitalSchedule.id.is_(None))
    ).scalar() or 0
    if no_schedule:
        # 실패는 아니다. 일정이 아직 안 정해진 회장은 정상적으로 있을 수 있다.
        print(f"   [i]    개최 회차가 없는 회장 {no_schedule}곳 "
              f"(이용자 화면에는 나오지 않는다)")


# --------------------------------------------------------------------------
# 내용 검사 — 시트를 정답지로
# --------------------------------------------------------------------------


def sheet_expectation(path) -> tuple[dict, list[str]]:
    """시트를 읽어 「DB 에 있어야 하는 것」을 만든다.

    임포터와 **같은 읽기 함수**를 쓴다. 여기서 따로 파서를 쓰면 두 파서가
    어긋났을 때 검증이 통과해 버린다.

    돌려주는 것은 {회장코드: {개최일: {시작시각: 정원}}} 과, 시트 자체가
    가진 문제(중복 행 등)의 설명이다.
    """
    rows, _columns = importer.read_sheet(path)
    groups = importer.group_by_venue(rows)

    expected: dict = {}
    notes: list[str] = []

    for code, venue_rows in groups.items():
        by_date: dict = {}
        for row in venue_rows:
            event_date = importer.parse_date(row.get("event_date"))
            if event_date is None:
                notes.append(f"{code} {row['_row_no']}행 — 開催日 없음 (건너뜀)")
                continue
            if event_date in by_date:
                notes.append(
                    f"{code} {row['_row_no']}행 — {event_date} 중복 (첫 행만 반영)"
                )
                continue
            by_date[event_date] = {
                start: capacity for start, _end, capacity, _label in row["_slots"]
            }
        expected[code] = by_date

    return expected, notes


def check_contents(db, path, report: Report) -> None:
    expected, notes = sheet_expectation(path)

    print(f"\n 내용 — 정답지 : {path.name}")
    for note in notes:
        print(f"   [i]    {note}")

    for code, by_date in expected.items():
        hospital = db.execute(
            select(Hospital).where(Hospital.code == code)
        ).scalar_one_or_none()
        if hospital is None:
            report.fail(f"{code} — 회장이 DB 에 없다")
            continue

        actual_dates = {s.event_date: s for s in hospital.schedules}
        report.check(
            set(actual_dates) == set(by_date),
            f"{code} {hospital.name} — 개최 회차 {len(by_date)}건",
            f"시트 {sorted(d.isoformat() for d in by_date)} / "
            f"DB {sorted(d.isoformat() for d in actual_dates)}",
        )

        for event_date, wanted in by_date.items():
            schedule = actual_dates.get(event_date)
            if schedule is None:
                continue

            actual = {
                view.start_time: view.capacity for view in grid.views_of(schedule)
            }
            report.check(
                actual == wanted,
                f"{code} {event_date} — 시간대 {len(wanted)}칸 / "
                f"정원 {sum(wanted.values())}",
                f"시트 {sorted((t.strftime('%H:%M'), c) for t, c in wanted.items())} / "
                f"DB {sorted((t.strftime('%H:%M'), c) for t, c in actual.items())}",
            )




# --------------------------------------------------------------------------
# 요약
# --------------------------------------------------------------------------


def print_summary(db) -> None:
    print("\n 지금 DB 에 들어 있는 것")
    today = date.today()

    hospitals = db.execute(
        select(Hospital).order_by(Hospital.sort_order, Hospital.id)
    ).scalars().all()

    for hospital in hospitals:
        open_count = sum(
            1 for s in hospital.schedules if s.is_open_for_booking(today)
        )
        print(f"\n   {hospital.code}  {hospital.name}  ({hospital.region})")
        print(f"         회차 {len(hospital.schedules)}건 · 접수 중 {open_count}건")
        for schedule in hospital.schedules:
            slots = grid.views_of(schedule)
            capacity = sum(s.capacity for s in slots)
            state = "접수중" if schedule.is_open_for_booking(today) else "마감  "
            times = (
                f"{min(s.start_time for s in slots).strftime('%H:%M')}"
                f"~{max(s.end_time for s in slots).strftime('%H:%M')}"
                if slots else "시간표 없음"
            )
            print(f"           {schedule.event_date}  {state}  "
                  f"시간대 {len(slots):>2}칸  정원 {capacity:>4}  {times}")


def main() -> int:
    argv = sys.argv[1:]
    path = None
    if "--file" in argv:
        index = argv.index("--file")
        if index + 1 >= len(argv):
            print(" --file 뒤에 경로를 적어 주세요.")
            return 1
        path = importer.find_sheet_file(argv[index + 1])

    report = Report()
    db = SessionLocal()
    try:
        print("=" * 78)
        print(" 정규화 검증")
        print("=" * 78)

        check_structure(db, report)
        if path is not None:
            check_contents(db, path, report)
        print_summary(db)

        print("\n" + "=" * 78)
        if report.failures:
            print(f" 확인 {report.checks}건 중 {len(report.failures)}건 실패")
            for line in report.failures:
                print(f"   · {line}")
            print("=" * 78)
            return 1

        print(f" 확인 {report.checks}건 전부 통과")
        print("=" * 78)
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
