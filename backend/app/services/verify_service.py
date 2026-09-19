"""본인 확인 · 검진 대상자 판별 업무 로직.

판정 흐름
    1) 「생년월일 + 보험자 번호 + 기호 + 번호」로 명부 후보를 좁힌다
    2) 후보 중 한자 성명이 일치하는 사람을 추린다
    3) 그중 후리가나까지 일치하는 사람을 찾는다
    4) 확정된 대상자의 `id` 로 **예약 테이블을 조회**해 예약 유무를 판정한다
    5) 결과에 따라 분기한다

예약 유무를 명부에 적어 두지 않는 이유
------------------------------------
「예약했는가」는 예약 테이블만이 안다. 명부에 플래그로 복사해 두면
취소·자동 삭제 때 한쪽만 갱신되어 어긋나고, 어긋난 순간
「예약이 있다는데 내역이 없다」는 문의가 된다.
그래서 대상자를 확정한 뒤 `reservations.target_person_id` 를 조회한다.

        한자 불일치            → NOT_ELIGIBLE     (검진 대상자 아님, 문의처 안내)
        한자 O · 후리가나 X     → KANA_MISMATCH    (읽는 법 확인 안내)
        성명 O · 성별 X        → GENDER_MISMATCH  (성별 확인 안내)
        완전 일치 2명 이상      → AMBIGUOUS        (명부 이상, 담당자 확인)
        완전 일치 + 예약 있음    → ALREADY_RESERVED
        완전 일치 + 미예약      → ELIGIBLE

대조 키에 포함하지 않는 항목
--------------------------
  · 미들네임 — 외국인 전용 임의 항목이며 명부에는 대부분 공란이다.
                대조에 넣으면 입력한 사람이 오히려 튕긴다.

후리가나를 대조 키에 포함하는 이유
--------------------------------
일본어는 같은 한자라도 읽는 법이 다르면 다른 사람이다.
  中田 健 → ナカタ ケン / ナカダ ケン
  東海林  → ショウジ / トウカイリン
  新谷    → シンタニ / ニイヤ

한자만으로 대조하면 동성동명·동일 생년월일인 두 사람을 구별하지 못하고
후보 중 아무나 한 명을 조용히 반환한다. 그 결과 다른 사람의 예약 상태를
보여 주거나, 다른 사람 이름으로 예약이 확정된다.

「명부에 있는데 튕겨서 전화 한 통」보다 「다른 사람으로 확정」이 훨씬 나쁘다.
의료 정보를 다루는 시스템에서 오식별은 조용히 일어나기 때문에 더 위험하다.
따라서 후리가나는 대조 키에 포함하고, 대신 불일치 시 「대상자 아님」이라는
막다른 안내 대신 「읽는 법을 확인해 주세요」라는 구체적 안내를 돌려준다.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import issue_verify_token
from app.core.text_utils import normalize_kana, normalize_name
from app.models.reservation import Reservation
from app.models.target_person import TargetPerson
from app.schemas.verify import (
    ContactInfo,
    VerifiedPerson,
    VerifyRequest,
    VerifyResponseData,
    VerifyStatus,
)

# --------------------------------------------------------------------------
# 이용자 안내 문구
# 고령 이용자 대상이므로 「무엇이 잘못됐는지」보다 「이제 무엇을 하면 되는지」를
# 알려준다. (plan.md 자체 피드백 P-7)
# --------------------------------------------------------------------------

TITLE_ELIGIBLE = "本人確認が完了しました"
MSG_ELIGIBLE = "本人確認が完了しました。続けて予約を進めてください。"

# 이미 예약이 있는 경우.
#
# **예약번호도 예약 내용도 여기서 보여 주지 않는다.**
# 이 화면에 넣는 값(성명·후리가나·성별·생년월일·보험증)은 가족이나 동거인이라면
# 알 수 있는 정보다. 그것만으로 예약번호가 나오면, 예약번호 하나로 열리는
# 예약 조회(U-20)가 통째로 열리는 셈이 된다.
#
# 대신 「무엇을 하면 되는지」를 평소보다 자세히 적는다. 여기서 막힌 이용자는
# 화면에서 더 할 수 있는 일이 없으므로, 안내가 부족하면 그대로 전화가 된다.
TITLE_ALREADY_RESERVED = "既に予約内容があります"
MSG_ALREADY_RESERVED = (
    "入力された方は今年度すでに予約を受付済みです。"
    "健康診断は1年に1回のみお申し込みいただけるため、新しく予約することはできません。"
)
HINTS_ALREADY_RESERVED = [
    "予約内容（会場・日時）は予約時にご案内した予約番号でご確認いただけます",
    "予約番号は予約完了画面と確認メールに記載されています",
    "予約番号をお忘れの場合や予約の変更・キャンセルをご希望の場合は、下記連絡先までお電話ください",
    "お電話の際にお名前と生年月日をお伝えいただければ、担当者がお調べいたします",
]

TITLE_NOT_ELIGIBLE = "健診対象者を確認できません"
MSG_NOT_ELIGIBLE = (
    "入力された情報では今年度の健康診断対象者を確認できません。"
    "下記の連絡先にお問い合わせいただければ、担当者が確認いたします。"
)
HINTS_NOT_ELIGIBLE = [
    "お名前や生年月日を誤って入力されている可能性があります",
    "健康保険証の番号をもう一度ご確認ください",
    "今年度の健診対象者名簿に含まれていない可能性があります",
]

# 한자 성명은 맞았으나 후리가나가 다른 경우.
# 「대상자가 아니다」라고 하면 이용자가 포기하거나 전화를 건다.
# 무엇을 고치면 되는지 콕 집어 알려 준다.
TITLE_KANA_MISMATCH = "フリガナをもう一度ご確認ください"
MSG_KANA_MISMATCH = (
    "お名前（漢字）は確認できましたが、フリガナが登録内容と異なります。"
    "健康保険証に記載されている読み方の通りに入力してください。"
)
HINTS_KANA_MISMATCH = [
    "同じ漢字でも読み方が異なると別の方として処理されます",
    "例えば「中田」は ナカタ と ナカダ で異なります",
    "濁点（゛）や小さい文字（ッ ャ ュ ョ）が正しいかご確認ください",
]

# 성명·후리가나는 맞으나 성별이 다른 경우.
TITLE_GENDER_MISMATCH = "性別をもう一度ご確認ください"
MSG_GENDER_MISMATCH = (
    "お名前は確認できましたが、選択された性別が登録内容と異なります。"
    "健康保険証に記載されている通りに選択してください。"
)
HINTS_GENDER_MISMATCH = [
    "健康保険証に記載されている性別（戸籍上の性別）を選択してください",
    "登録内容が誤っている場合は下記の連絡先までお問い合わせください",
]

# 완전히 같은 정보의 대상자가 2명 이상인 경우. 명부 데이터 이상이다.
# 임의로 한 명을 고르면 다른 사람의 예약이 되므로 반드시 사람이 개입해야 한다.
TITLE_AMBIGUOUS = "本人確認に担当者の確認が必要です"
MSG_AMBIGUOUS = (
    "入力された情報と一致する対象者様が複数名いらっしゃるため、"
    "自動で確認できません。下記の連絡先までお問い合わせください。"
)
HINTS_AMBIGUOUS = [
    "担当者が直接確認の上、予約をお手伝いいたします",
    "お電話の際にお名前・生年月日・健康保険証をご準備ください",
]


def _contact_info() -> ContactInfo:
    return ContactInfo(
        tel=settings.CONTACT_TEL,
        email=settings.CONTACT_EMAIL,
        hours=settings.CONTACT_HOURS,
    )


def _to_verified_person(person: TargetPerson) -> VerifiedPerson:
    return VerifiedPerson(
        last_name=person.last_name,
        first_name=person.first_name,
        last_name_kana=person.last_name_kana,
        first_name_kana=person.first_name_kana,
        full_name=person.full_name,
        full_name_kana=person.full_name_kana,
        middle_name=person.middle_name,
        middle_name_kana=person.middle_name_kana,
        gender=person.gender,
        gender_label=person.gender_label,
        birth_date=person.birth_date,
        insurance_card_no=person.insurance_card_no,
    )


# --------------------------------------------------------------------------
# 대조
# --------------------------------------------------------------------------


def _load_candidates(db: Session, payload: VerifyRequest) -> list[TargetPerson]:
    """인덱스가 걸린 항목(생년월일 + 보험증)으로 후보를 좁힌다."""
    stmt = select(TargetPerson).where(
        TargetPerson.birth_date == payload.birth_date,
        TargetPerson.insurer_no == payload.insurer_no,
        TargetPerson.insurance_symbol == payload.insurance_symbol,
        TargetPerson.insurance_no == payload.insurance_no,
    )
    return list(db.execute(stmt).scalars().all())


def match_kanji(candidates: list[TargetPerson], payload: VerifyRequest) -> list[TargetPerson]:
    """한자 성명이 일치하는 후보를 추린다.

    전각/반각 공백 등 표기 흔들림은 정규화로 흡수한다.
    후보는 이미 「생년월일 + 보험증」으로 한 자릿수까지 좁혀져 있으므로,
    정규화 값을 별도 컬럼에 저장하지 않고 이 자리에서 계산해도 부담이 없다.
    """
    target_last = normalize_name(payload.last_name)
    target_first = normalize_name(payload.first_name)

    return [
        p
        for p in candidates
        if normalize_name(p.last_name) == target_last
        and normalize_name(p.first_name) == target_first
    ]


def match_kana(candidates: list[TargetPerson], payload: VerifyRequest) -> list[TargetPerson]:
    """후리가나까지 일치하는 후보를 추린다.

    ※ 탁점(ダ↔タ)과 작은 글자(ッ↔ツ)는 정규화하지 않는다.
       이들은 표기 흔들림이 아니라 서로 다른 이름을 가르는 정보이기 때문이다.
       반각→전각, 히라가나→가타카나만 통일한다.
    """
    target_last = normalize_kana(payload.last_name_kana)
    target_first = normalize_kana(payload.first_name_kana)

    return [
        p
        for p in candidates
        if normalize_kana(p.last_name_kana) == target_last
        and normalize_kana(p.first_name_kana) == target_first
    ]


def find_active_reservation(db: Session, target_person_id: int) -> Reservation | None:
    """대상자 ID 로 유효한 예약을 찾는다.

    「유효」 = 취소되지 않은 예약. 검진일이 지난 예약은 자동 정리로 이미
    삭제되어 있으므로(services/purge_service.py) 별도 날짜 조건이 필요 없다.

    2건 이상이 나오는 것은 중복 예약 방지(BR-03)가 뚫린 상태이므로,
    가장 이른 검진일 1건을 대표로 돌려주되 그 자체가 조사 대상이다.
    """
    stmt = (
        select(Reservation)
        .where(
            Reservation.target_person_id == target_person_id,
            Reservation.status != "CANCELLED",
        )
        .order_by(Reservation.slot_date, Reservation.start_time)
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def verify_identity(db: Session, payload: VerifyRequest) -> VerifyResponseData:
    """본인 확인을 수행하고 결과를 반환한다."""
    candidates = _load_candidates(db, payload)
    kanji_matched = match_kanji(candidates, payload)

    # --- 한자 성명 자체가 없음 → 검진 대상자가 아님 ----------------------
    if not kanji_matched:
        return VerifyResponseData(
            status=VerifyStatus.NOT_ELIGIBLE,
            title=TITLE_NOT_ELIGIBLE,
            message=MSG_NOT_ELIGIBLE,
            hints=HINTS_NOT_ELIGIBLE,
            contact=_contact_info(),
        )

    kana_matched = match_kana(kanji_matched, payload)

    # --- 한자는 맞으나 읽는 법이 다름 → 후리가나 확인 안내 ---------------
    if not kana_matched:
        return VerifyResponseData(
            status=VerifyStatus.KANA_MISMATCH,
            title=TITLE_KANA_MISMATCH,
            message=MSG_KANA_MISMATCH,
            hints=HINTS_KANA_MISMATCH,
            contact=_contact_info(),
        )

    # --- 성명은 맞으나 성별이 다름 → 성별 확인 안내 ----------------------
    # 성별도 명부와 대조한다. 값이 두 개뿐이라 식별력은 약하지만,
    # 입력 착오를 잡아 주고 「어느 칸을 고치면 되는지」를 알려 줄 수 있다.
    exact_matched = [p for p in kana_matched if p.gender == payload.gender]
    if not exact_matched:
        return VerifyResponseData(
            status=VerifyStatus.GENDER_MISMATCH,
            title=TITLE_GENDER_MISMATCH,
            message=MSG_GENDER_MISMATCH,
            hints=HINTS_GENDER_MISMATCH,
            contact=_contact_info(),
        )

    # --- 완전 일치가 2명 이상 → 자동 판정 불가, 담당자 확인 --------------
    # 임의로 한 명을 고르면 다른 사람의 예약이 된다. 절대 추측하지 않는다.
    if len(exact_matched) > 1:
        return VerifyResponseData(
            status=VerifyStatus.AMBIGUOUS,
            title=TITLE_AMBIGUOUS,
            message=MSG_AMBIGUOUS,
            hints=HINTS_AMBIGUOUS,
            contact=_contact_info(),
        )

    person = exact_matched[0]

    # --- 이미 예약이 존재함 ----------------------------------------------
    # 명부의 플래그가 아니라 예약 테이블을 직접 본다.
    # 취소되거나 검진일이 지나 삭제된 예약은 여기서 자연히 제외된다.
    existing = find_active_reservation(db, person.id)
    if existing is not None:
        # 예약번호도, 예약 내용도, 확인된 신원도 돌려주지 않는다.
        # 이 화면의 입력값(성명·생년월일·보험증)은 **가족이나 동거인이라면
        # 알 수 있는 정보**다. 그것만으로 예약번호가 나오면, 예약번호를 열쇠로
        # 삼는 예약 조회(U-20)가 통째로 열린다.
        # 여기서는 「예약이 있다」는 사실과 문의 방법만 알린다.
        return VerifyResponseData(
            status=VerifyStatus.ALREADY_RESERVED,
            title=TITLE_ALREADY_RESERVED,
            message=MSG_ALREADY_RESERVED,
            hints=HINTS_ALREADY_RESERVED,
            contact=_contact_info(),
        )

    # --- 예약 진행 가능 ---------------------------------------------------
    return VerifyResponseData(
        status=VerifyStatus.ELIGIBLE,
        title=TITLE_ELIGIBLE,
        message=MSG_ELIGIBLE,
        person=_to_verified_person(person),
        verify_token=issue_verify_token(person.id),
    )
