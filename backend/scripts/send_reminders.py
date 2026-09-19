"""검진 전날 리마인드 메일 발송 (plan.md BR-11 / §11.6).

    python -m scripts.send_reminders          # 내일 검진자에게 발송
    python -m scripts.send_reminders --date 2026-08-11
    python -m scripts.send_reminders --dry    # 대상만 확인

운영에서는 **매일 12:00** 에 실행한다 (Windows 작업 스케줄러 또는 cron).
발송 결과는 `mail_logs` 에 남고, 실패 건은 관리 화면 대시보드에 뜬다 (M-12).
"""

import scripts._console  # noqa: F401  (콘솔 UTF-8 보정)
import sys
from datetime import date, timedelta

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.reservation import Reservation
from app.services import mail_service


def _target_date() -> date:
    if "--date" in sys.argv:
        index = sys.argv.index("--date")
        if index + 1 < len(sys.argv):
            return date.fromisoformat(sys.argv[index + 1])
    return date.today() + timedelta(days=1)


def main() -> int:
    dry = "--dry" in sys.argv
    target = _target_date()

    db = SessionLocal()
    try:
        rows = db.execute(
            select(Reservation)
            .where(
                Reservation.slot_date == target,
                Reservation.status == "CONFIRMED",
                Reservation.email != "",
            )
            .order_by(Reservation.start_time)
        ).scalars().unique().all()

        print("=" * 66)
        print(f" 受診前日リマインド — 対象日 {target.isoformat()}")
        print("=" * 66)
        print(f" 対象 : {len(rows)}件 (確定済み・メールアドレス登録済みの予約のみ)")

        if dry:
            for r in rows:
                print(f"   {r.reservation_no}  {r.full_name:<10} {r.time_label}  {r.email}")
            print(" (--dry のため送信していません)")
            return 0

        success = failed = skipped = 0
        for reservation in rows:
            log = mail_service.send_reminder(db, reservation)
            if log.status == "SUCCESS":
                success += 1
            elif log.status == "FAILED":
                failed += 1
                print(f"   [失敗] {reservation.reservation_no} — {log.error_message}")
            else:
                skipped += 1

        db.commit()

        print(f" 送信 : 成功 {success} / 失敗 {failed} / 保留 {skipped}")
        if skipped:
            print("   ※ 保留は API キーが未設定のため、本文だけを記録した件です。")
            print("     .env の RESEND_API_KEY を設定すると実際に送信されます。")
        return 1 if failed else 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
