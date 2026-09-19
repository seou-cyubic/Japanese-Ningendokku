"""콘솔 출력 인코딩 보정.

Windows 한국어 환경의 기본 콘솔 코드페이지는 cp949 라서,
스크립트가 출력하는 일본어 성명이나 `—`(em dash) 에서 그대로 죽는다.

    UnicodeEncodeError: 'cp949' codec can't encode character '\\u2014'

스크립트를 실행할 때마다 `set PYTHONIOENCODING=utf-8` 을 치게 만들지 않으려고
표준 출력만 UTF-8 로 다시 연다. 실패해도 무시한다 — 출력 인코딩 때문에
DB 작업이 막히면 안 된다.

    import scripts._console  # noqa: F401
"""

import sys

for _stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(_stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
