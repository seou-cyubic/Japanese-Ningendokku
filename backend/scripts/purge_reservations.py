"""검진 시각이 지난 예약을 삭제한다.

    python -m scripts.purge_reservations          # 삭제 실행
    python -m scripts.purge_reservations --dry    # 대상 件수만 확인

규칙 : 검진 시각 + 유예 시간(.env 의 RESERVATION_EXPIRE_GRACE_MINUTES, 기본 60分)

    예) 8월 7일 09:00 예약 → 8월 7일 10:00 에 삭제

평상시에는 FastAPI 가 뜰 때 함께 도는 백그라운드 태스크가 같은 일을 한다
(app/main.py). 이 스크립트는 서버를 띄우지 않고 정리하거나,
운영에서 cron 으로 돌리고 싶을 때 쓴다. 두 경로가 겹쳐 돌아도 문제없다.
"""

import scripts._console  # noqa: F401  (콘솔 UTF-8 보정)
import sys
from datetime import datetime

from app.core.config import settings
from app.core.database import SessionLocal
from app.services import purge_service


def main() -> int:
    dry = "--dry" in sys.argv
    now = datetime.now()
    cutoff = purge_service.expire_cutoff(now)

    db = SessionLocal()
    try:
        print("=" * 66)
        print(" 受診時刻を過ぎた予約の整理")
        print(f" 現在時刻 : {now:%Y-%m-%d %H:%M}")
        print(f" 猶予時間 : {settings.RESERVATION_EXPIRE_GRACE_MINUTES}分")
        print(f" 基準時刻 : {cutoff:%Y-%m-%d %H:%M} より前に開始した予約が対象")
        print("=" * 66)

        pending = purge_service.count_expired(db, now)
        print(f" 対象 : {pending}件")

        if dry:
            print(" (--dry のため削除していません)")
            return 0

        deleted = purge_service.purge_expired(db, now)
        print(f" 削除 : {deleted}件")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
