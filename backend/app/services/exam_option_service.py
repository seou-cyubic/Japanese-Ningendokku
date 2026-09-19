"""옵션 검사 조회 업무 로직 (U-14).

이용자의 성별·연령으로 걸러 신청 가능한 옵션만 돌려준다. (BR-13)
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.exam_option import ExamOption
from app.schemas.exam_option import ExamOptionItem, ExamOptionListData

GENDER_LABEL = {"M": "男性", "F": "女性"}


def calc_age(birth_date: date, today: date) -> int:
    """만 나이. 생일이 지나지 않았으면 1을 뺀다."""
    age = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


def list_for_person(
    db: Session,
    gender: str,
    birth_date: date,
    today: date,
) -> ExamOptionListData:
    """해당 이용자가 신청할 수 있는 옵션 검사 목록.

    타깃 조건 판정은 DB 쿼리가 아니라 모델의 `matches()` 에 맡긴다.
    조건이 늘어나도(예: 특정 회장 한정) 판정 규칙이 한 곳에만 있게 된다.
    """
    age = calc_age(birth_date, today)

    stmt = (
        select(ExamOption)
        .where(ExamOption.is_active.is_(True))
        .order_by(ExamOption.sort_order, ExamOption.id)
    )

    options = [
        ExamOptionItem(
            id=o.id,
            code=o.code,
            name=o.name,
            description=o.description,
            note=o.note,
        )
        for o in db.execute(stmt).scalars()
        if o.matches(gender, age)
    ]

    return ExamOptionListData(
        gender=gender,
        gender_label=GENDER_LABEL.get(gender, ""),
        age=age,
        options=options,
    )
