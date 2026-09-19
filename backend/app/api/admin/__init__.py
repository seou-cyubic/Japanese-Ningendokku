"""관리 화면 API (plan.md §10.2).

라우터를 한곳에 모아 `/api/v1/admin` 아래에 붙인다.
권한 검사는 각 라우터의 의존성에서 한다 (core/deps.py).
"""

from fastapi import APIRouter

from app.api.admin import (
    accounts,
    audit_logs,
    auth,
    bulk,
    dashboard,
    exam_options,
    hospitals,
    mail_templates,
    reservations,
    system,
)

router = APIRouter(prefix="/admin")

router.include_router(auth.router)
router.include_router(dashboard.router)
router.include_router(reservations.router)
router.include_router(hospitals.router)
# 회장 정보 · 정원 일괄 관리. 「한 표에 전부」였던 것을 둘로 나눈 자리다.
router.include_router(bulk.router)
router.include_router(exam_options.router)
router.include_router(mail_templates.router)
router.include_router(accounts.router)
router.include_router(audit_logs.router)
# 우편번호 데이터 상태. 「주소 찾기가 안 된다」의 원인이 여기서만 보인다.
router.include_router(system.router)
