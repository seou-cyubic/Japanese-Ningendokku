"""문자열 정규화 유틸리티.

일본어 성명은 입력 방식에 따라 표기가 흔들린다.
  · 전각 공백(U+3000) / 반각 공백이 섞인다
  · 전각 영숫자(ＡＢＣＤ)와 반각 영숫자(ABCD)가 섞인다
  · 후리가나에 반각 가타카나(ﾀﾅｶ)나 히라가나(たなか)가 들어온다

이 흔들림 때문에 「명부에 있는 사람」이 「대상자가 아님」으로 판정되면
그대로 문의 전화로 이어진다. (plan.md 자체 피드백 P-7)
따라서 대조 전에 반드시 정규화한다.
"""

import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")

# 히라가나 → 가타카나 변환 범위 (ぁ U+3041 ~ ゖ U+3096)
_HIRAGANA_START = 0x3041
_HIRAGANA_END = 0x3096
_KANA_OFFSET = 0x60  # ぁ(U+3041) + 0x60 = ァ(U+30A1)

# 전각 가타카나로 허용하는 문자
#   U+30A1~U+30FA : ァ ~ ヺ
#   U+30FB        : ・  (외국인 성명의 중점)
#   U+30FC        : ー  (장음 부호)
#   U+30FD~U+30FE : ヽヾ (반복 기호)
_FULLWIDTH_KATAKANA_ONLY = re.compile(r"^[ァ-ヺ・-ヾ]+$")


def normalize_name(value: str | None) -> str:
    """성명(한자) 대조용 정규화.

    NFKC 정규화(전각→반각 통일) 후 모든 공백을 제거한다.

    >>> normalize_name("田中　太郎")
    '田中太郎'
    >>> normalize_name(" 田中 太郎 ")
    '田中太郎'
    """
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", value)
    return _WHITESPACE.sub("", normalized)


def normalize_kana(value: str | None) -> str:
    """후리가나를 전각 가타카나로 정규화한다.

    1) NFKC 정규화 → 반각 가타카나가 전각으로 바뀐다 (ﾀﾅｶ → タナカ, ﾀﾞ → ダ)
    2) 공백 제거
    3) 히라가나를 가타카나로 변환 (たなか → タナカ)

    고령 이용자에게 「전각 가타카나로 다시 입력하세요」라고 되돌려 보내는 대신
    시스템이 알아서 맞춰 주는 편이 문의를 줄인다.

    >>> normalize_kana("ﾀﾅｶ")
    'タナカ'
    >>> normalize_kana("たなか")
    'タナカ'
    >>> normalize_kana("タナカ")
    'タナカ'
    """
    if not value:
        return ""

    normalized = unicodedata.normalize("NFKC", value)
    normalized = _WHITESPACE.sub("", normalized)

    return "".join(
        chr(ord(ch) + _KANA_OFFSET)
        if _HIRAGANA_START <= ord(ch) <= _HIRAGANA_END
        else ch
        for ch in normalized
    )


def is_fullwidth_katakana(value: str | None) -> bool:
    """전각 가타카나만으로 이루어져 있는지 검사한다.

    normalize_kana() 를 거친 값에 대해 사용한다.
    한자·히라가나·영숫자가 섞여 있으면 False.

    >>> is_fullwidth_katakana("タナカ")
    True
    >>> is_fullwidth_katakana("田中")
    False
    >>> is_fullwidth_katakana("tanaka")
    False
    """
    if not value:
        return False
    return bool(_FULLWIDTH_KATAKANA_ONLY.match(value))


def normalize_code(value: str | None) -> str:
    """보험증 번호 등 코드값 정규화.

    NFKC 정규화 후 공백을 제거하고 대문자로 통일한다.
    하이픈은 제거하지 않는다(항목별로 분리 입력받기 때문).

    >>> normalize_code(" abcd ")
    'ABCD'
    """
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", value)
    return _WHITESPACE.sub("", normalized).upper()


# ---------------------------------------------------------------------------
# 전화번호
# ---------------------------------------------------------------------------
#
# 우편 접수·관리 화면은 전화번호를 자유 입력으로 받는다. 담당자에 따라
# 「09012345678」처럼 하이픈 없이 적기도 하고 「090-1234-5678」로 적기도
# 해서, 목록에 두 표기가 섞여 읽기 어려웠다. 저장할 때 표기를 맞춘다.
#
# 다만 **자릿수만 보고 확실히 나눌 수 있는 것만** 나눈다. 일본의 시외국번은
# 지역에 따라 2~5자리로 길이가 다르고, 번호만으로는 어디까지가 국번인지
# 알 수 없다. 예를 들어 東京都大島町은 04992-X-XXXX 로 국번이 5자리인데, 이를
# 모르고 4자리로 끊으면 0499-2X-XXXX 라는 **틀린 표기**가 된다.
#
# 틀린 자리에 하이픈을 넣는 것은, 하이픈이 없는 것보다 나쁘다. 담당자가
# 번호를 잘못 읽을 수 있기 때문이다. 그래서 아래 표에 없는 번호는
# **적은 그대로 둔다.**

# 국번 길이가 번호만으로 정해지는 것들. (일본의 시외국번은 어떤 국번도
# 다른 국번의 앞부분이 되지 않도록 배정되어 있어, 아래 판정은 겹치지 않는다.)
_PHONE_PATTERNS: list[tuple[str, int, tuple[int, int, int]]] = [
    # (앞자리, 전체 자릿수, 끊는 위치)
    ("090", 11, (3, 4, 4)),   # 휴대전화
    ("080", 11, (3, 4, 4)),
    ("070", 11, (3, 4, 4)),
    ("050", 11, (3, 4, 4)),   # IP 전화
    ("0800", 11, (4, 3, 4)),  # 착신과금
    ("0120", 10, (4, 3, 3)),  # 프리다이얼
    ("0570", 10, (4, 3, 3)),  # 내비다이얼
    ("0990", 10, (4, 3, 3)),
    ("03", 10, (2, 4, 4)),    # 東京 23区 등
    ("06", 10, (2, 4, 4)),    # 大阪市 등
    ("011", 10, (3, 3, 4)),
    ("045", 10, (3, 3, 4)),
    ("052", 10, (3, 3, 4)),
]


def format_phone(value: str | None) -> str:
    """전화번호에 하이픈을 넣는다. 확실하지 않으면 적은 그대로 돌려준다.

    이미 하이픈이나 괄호가 들어 있으면 사람이 의도를 갖고 적은 것으로
    보고 손대지 않는다. 전각 숫자는 반각으로 맞춘다.
    """
    text = unicodedata.normalize("NFKC", (value or "")).strip()
    if not text:
        return ""

    # 사람이 이미 나눠 적었으면 그대로 둔다.
    if any(character in text for character in "-()（） "):
        return text

    if not text.isdigit():
        return text

    for prefix, length, cuts in _PHONE_PATTERNS:
        if len(text) == length and text.startswith(prefix):
            first, second, _third = cuts
            return "-".join(
                (text[:first], text[first:first + second], text[first + second:])
            )

    # 표에 없는 번호(시외국번 길이를 알 수 없음). 적은 그대로 둔다.
    return text
