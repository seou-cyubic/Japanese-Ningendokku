"""관리 화면 API — 시스템 데이터 상태.

지금은 우편번호(주소) 데이터 하나를 다룬다.

왜 화면에 내는가
----------------
「주소 찾기」가 이 데이터 위에서 돈다. 없으면 이용자 화면의 검색이 아무것도
찾지 못하는데, 그 사실이 **서버 로그에만** 남는다. 담당자는 서버 콘솔을 볼
수 없으므로, 문의가 들어오기 전까지 아무도 모른다.

기동할 때 자동으로 채우게 해 두었지만(`main.py` 의 `lifespan`), 인터넷이
막힌 환경이나 일본우편이 배포 형식을 바꾼 경우에는 실패한다. 그때
**무엇이 어떻게 안 되고 있는지**와 **다시 시도하는 버튼**이 필요하다.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.core.deps import client_ip, require_staff, require_system_admin
from app.models.admin import AdminUser
from app.services import audit_service, postal_import_service

logger = logging.getLogger("kenshin")

# 읽기는 L1 부터. 「주소 검색이 안 된다」는 문의를 가장 먼저 받는 사람이
# 스태프인데, 그가 원인을 볼 수 없으면 그대로 위로 올라올 뿐이다.
# 다시 적재하는 것은 L3 만 (개별 엔드포인트에서 다시 건다).
router = APIRouter(
    prefix="/system",
    tags=["管理 - システムデータ"],
    dependencies=[Depends(require_staff)],
)


@router.get(
    "/postal-status",
    summary="郵便番号データステータス",
    description=(
        "取り込み件数とステータス(`READY`/`RUNNING`/`MISSING`/`FAILED`/`DISABLED`)を返す。\n\n"
        "`MISSING`・`FAILED` だと利用者画面の「住所検索」が動作しない。 "
        "L1 スタッフも閲覧できるようにした — 「住所検索ができない」という問い合わせを"
        "最初に受ける人だからである。"
    ),
)
def postal_status(db: Session = Depends(get_db)) -> dict:
    data = postal_import_service.status(db)
    data["minimum"] = settings.POSTAL_MIN_ROWS
    data["auto_import"] = settings.POSTAL_AUTO_IMPORT
    data["source"] = settings.POSTAL_SOURCE_FILE or postal_import_service.KEN_ALL_URL
    return {"success": True, "data": data}


@router.post(
    "/postal-import",
    summary="郵便番号データの再取り込み",
    description=(
        "日本郵便から再ダウンロードして全件入れ替える。 **1～2分かかり、"
        "バックグラウンドで動作する** — レスポンスはすぐに返る。進捗状況は "
        "`GET /system/postal-status` で確認する。\n\n"
        "何度実行しても結果は同じ（冪等）。日本郵便が毎月更新するため"
        "半年に1回程度押しておけばよい。\n\n"
        "すでに取り込み中の場合は409で拒否する。"
    ),
    dependencies=[Depends(require_system_admin)],
)
async def postal_import(
    request: Request,
    admin: AdminUser = Depends(require_system_admin),
) -> dict:
    if postal_import_service.STATE.state == postal_import_service.RUNNING:
        raise HTTPException(
            status_code=409,
            detail="すでに取り込み中です。完了するまでお待ちください。",
        )

    ip_address = client_ip(request)

    db = SessionLocal()
    try:
        audit_service.write_log(
            db,
            admin=admin,
            action="POSTAL_IMPORT",
            target_type="system",
            target_label="郵便番号データの再取り込み",
            after={"source": settings.POSTAL_SOURCE_FILE or "japanpost"},
            ip_address=ip_address,
        )
        db.commit()
    finally:
        db.close()

    # 요청을 붙잡아 두지 않는다. 프록시의 타임아웃이 먼저 끊으면 담당자에게는
    # 「실패」로 보이는데, 실제로는 뒤에서 계속 돌고 있다.
    asyncio.create_task(_run_import())

    return {
        "success": True,
        "data": postal_import_service.STATE.as_dict(),
        "message": "取り込みを開始しました。1～2分後にステータスを確認してください。",
    }


async def _run_import() -> None:
    try:
        await asyncio.to_thread(
            postal_import_service.run_startup_import,
            SessionLocal,
            auto=True,           # 손으로 누른 것이므로 설정과 무관하게 적재한다
            minimum=10**9,       # 이미 있어도 다시 넣는다 (갱신이 목적)
            source=settings.POSTAL_SOURCE_FILE,
        )
    except Exception:  # noqa: BLE001
        logger.exception("郵便番号の手動再取り込みに失敗しました。")
