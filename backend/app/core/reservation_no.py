"""예약번호 생성 규칙 (plan.md §11.5).

    형식 : 영문 대문자 · 영문 소문자 · 숫자를 섞은 **완전 무작위 12자**
           예) `aK9mQ2xR7bTz`

문자셋은 62자(대문자 26 + 소문자 26 + 숫자 10)이며, 어떤 문자도 빼지 않는다.
자리마다 62가지가 그대로 살아 있어야 12자리가 제 값(62^12 ≈ 3.2 × 10^21)을 한다.

왜 무작위인가
--------------
예약번호는 「예약 조회」의 열쇠다. 번호에 규칙성이 있으면 자기 번호 하나로
남의 번호를 만들어 낼 수 있고, 그대로 타인 예약 열람 경로가 된다.
그래서 연도·회장·순번 같은 의미를 일절 담지 않는다.

`random` 이 아니라 `secrets` 를 쓰는 이유
------------------------------------------
`random` 은 내부 상태를 알면 다음 값을 계산할 수 있는 의사난수다.
예약번호는 추측되면 안 되는 값이므로 암호학적 난수(`secrets`)로 만든다.

대소문자는 **모든 상황에서 구별한다**
--------------------------------------
`aK9mQ2xR7bTz` 와 `AK9MQ2XR7BTZ` 는 서로 다른 번호다.
이것을 지키려면 대조가 일어나는 모든 지점이 같은 기준이어야 한다.

  · **DB 컬럼** — `reservations.reservation_no` 에 `utf8mb4_bin` 을 지정한다.
    테이블 기본값(`utf8mb4_general_ci`)을 그대로 두면 `=`·`LIKE`·`UNIQUE`
    판정이 전부 대소문자를 뭉개 버린다. (models/reservation.py)
  · **발행** — 중복 확인도 같은 컬럼을 보므로 자동으로 대소문자를 구별한다.
    `aB…` 와 `Ab…` 는 서로 다른 번호이며 둘 다 존재할 수 있다.
    (services/reservation_service.py)
  · **화면** — 코드 어디에서도 `upper()`·`lower()` 를 씌우지 않는다.
    한 곳에서만 뭉개면 그 지점만 다른 답을 내놓는다.
  · **이용자 안내** — 「대문자와 소문자를 구별합니다」를 예약번호 옆에 적는다.
    구별한다는 사실을 모르면 그것이 그대로 「조회가 안 된다」는 문의가 된다.

그래서 62^12 ≈ 3.2 × 10^21 가지가 값을 깎이지 않고 그대로 유지된다.

단 하나의 예외 — **관리자 화면의 검색**
----------------------------------------
창구 담당자는 전화로 번호를 듣는다. 대소문자는 들리지 않고, 0과 O, 1과 l과 I
도 가려지지 않으며, 한 손으로 치면 전부 소문자다. 그래서 관리자 검색은
`fold_for_search()` 로 양쪽을 뭉개서 견준다. 뭉개도 36^12 에 가까운 공간이
남아 2만 건에서 겹칠 일은 사실상 없고, 겹치면 결과 화면이 둘 다 보여 준다.
이용자 화면의 「예약 조회」는 그대로 엄격하다 — 거기는 열쇠다.
"""

import secrets
import string

ALPHABET = string.ascii_uppercase + string.ascii_lowercase + string.digits  # 62자
LENGTH = 12

# 예약번호 컬럼에 지정할 콜레이션. 바이트 단위 비교라 대소문자를 구별한다.
# 값이 ASCII 영숫자뿐이므로 `utf8mb4_bin` 으로 충분하다.
DB_COLLATION = "utf8mb4_bin"

# 전화로 들으면 가려지지 않는 글자. 관리자 검색에서만 같은 것으로 본다.
# (소문자로 내린 뒤 적용한다)
SEARCH_FOLD = (("o", "0"), ("l", "1"), ("i", "1"))


def fold_for_search(value: str) -> str:
    """관리자 검색용으로 뭉갠다 — 소문자로, 그리고 O→0 · l/I→1.

    >>> fold_for_search("PlI81PsAERCX")
    'p1181psaercx'
    >>> fold_for_search("pli81psaercx") == fold_for_search("PlI81PsAERCX")
    True
    >>> fold_for_search("QAzdhwjBEUk2")
    'qazdhwjbeuk2'
    """
    out = (value or "").lower()
    for src, dst in SEARCH_FOLD:
        out = out.replace(src, dst)
    return out


def generate() -> str:
    """무작위 예약번호 한 개를 만든다.

    중복 확인은 하지 않는다. DB 를 아는 것은 이 모듈의 일이 아니다.
    발행은 `services.reservation_service.issue_reservation_no()` 가 맡는다.

    >>> value = generate()
    >>> len(value)
    12
    >>> all(c in ALPHABET for c in value)
    True
    """
    return "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))


def is_valid(value: str) -> bool:
    """예약번호로 쓸 수 있는 모양인지 확인한다.

    조회 화면에서 「번호를 잘못 입력했습니다」를 DB 조회 전에 돌려주는 데 쓴다.

    >>> is_valid("aK9mQ2xR7bTz")
    True
    >>> is_valid("aK9mQ2xR7bT")
    False
    >>> is_valid("aK9mQ2xR7bT-")
    False
    """
    return len(value) == LENGTH and all(c in ALPHABET for c in value)
