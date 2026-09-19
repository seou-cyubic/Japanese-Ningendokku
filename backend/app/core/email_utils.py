"""이메일 주소 검증.

무엇으로 검증하는가
--------------------
`email-validator` 를 쓴다. Pydantic 의 `EmailStr` 이 내부에서 쓰는 바로 그
라이브러리이며, 파이썬 진영에서 사실상 표준으로 쓰인다.
정규식을 직접 짜지 않는 이유는, 이메일 주소의 문법(RFC 5322)이 정규식으로
정확히 표현하기에는 너무 복잡해서 **직접 짜면 반드시 틀리기 때문**이다.
흔한 실수는 두 방향 모두로 난다.

    · 너무 느슨해서 `a@b` 같은 값을 통과시킨다
    · 너무 빡빡해서 `taro+kenshin@example.co.jp` 같은 정상 주소를 막는다

이 라이브러리는 다음을 함께 처리한다.

    · 문법 검사 (로컬부·도메인부·따옴표·길이 제한)
    · 유니코드 도메인의 IDNA 변환 (`日本.jp` → `xn--wgv71a.jp`)
    · 도메인을 소문자로 통일한 **정규화된 주소** 반환

DNS 조회는 하지 않는다
----------------------
`check_deliverability=False` 로 끈다. 켜면 예약 접수 도중에 DNS 를 물어보게 되고,
그 응답이 늦으면 **예약 화면이 그만큼 멈춘다.** 남의 인프라 사정으로 우리 예약이
느려지는 것을 받아들일 수 없다. 실제 도달 여부는 확인 메일 발송 결과
(`mail_logs`)로 판단한다.

오타 도메인은 막지 않는다
-------------------------
`gmail.co` 처럼 실제로 존재하는 도메인은 문법상 정상이다. 막을 근거가 없다.
대신 화면에서 「혹시 gmail.com 아니십니까?」로 되묻는다.
(frontend/assets/js/apply.js) 막는 것과 되묻는 것은 다르다.
"""

from email_validator import EmailNotValidError, validate_email

# 이용자에게 보여 줄 문구. 라이브러리의 영어 메시지를 그대로 내보내지 않는다.
# 고령 이용자 대상이므로 「무엇이 잘못됐는지」보다 「어떻게 적으면 되는지」를 적는다.
MSG_INVALID = (
    "メールアドレスの形式が正しくありません。"
    "「お名前@ドメイン」の形式で入力してください。(例: taro@example.jp)"
)
MSG_NO_AT = (
    "メールアドレスに「@」がありません。"
    "「お名前@ドメイン」の形式で入力してください。(例: taro@example.jp)"
)
MSG_TOO_LONG = "メールアドレスが長すぎます。もう一度ご確認ください。"

MAX_LENGTH = 255


class EmailInvalid(ValueError):
    """이용자에게 그대로 보여 줄 수 있는 이메일 오류."""


def normalize_email(value: str | None) -> str:
    """이메일 주소를 검증하고 정규화한 값을 돌려준다.

    빈 값은 그대로 빈 문자열로 돌려준다. 이 시스템에서 이메일은 임의 항목이다.
    (plan.md BR-05 — 필수는 전화번호이며, 메일은 있으면 확인 메일을 보낸다)

    >>> normalize_email("")
    ''
    >>> normalize_email("  Taro@Example.JP  ")
    'Taro@example.jp'
    >>> normalize_email("taro+kenshin@example.co.jp")
    'taro+kenshin@example.co.jp'
    """
    value = (value or "").strip()
    if not value:
        return ""

    if len(value) > MAX_LENGTH:
        raise EmailInvalid(MSG_TOO_LONG)

    if "@" not in value:
        raise EmailInvalid(MSG_NO_AT)

    try:
        result = validate_email(value, check_deliverability=False)
    except EmailNotValidError as exc:
        raise EmailInvalid(MSG_INVALID) from exc

    # 도메인은 소문자로, 유니코드 도메인은 퓨니코드로 통일된 값이다.
    # 로컬부(@ 앞)는 대소문자를 구별하는 서버가 있으므로 손대지 않는다.
    return result.normalized
