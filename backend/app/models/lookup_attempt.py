"""예약 조회 시도 기록 (U-20 의 추측 방지).

예약번호는 무작위 12자이고 그 자체가 열쇠다. 따라서 유일한 공격 경로는
**찍어서 두드려 보는 것**이며, 아무리 넓은 공간이라도 무제한으로 두드릴 수
있게 두지 않는다. (plan.md §13.2)

왜 메모리가 아니라 표에 두는가
------------------------------
프로세스 메모리에 두면 두 가지가 깨진다.

  · 워커를 여러 개 띄우면 워커마다 따로 세므로 한도가 워커 수만큼 늘어난다
  · 서버를 다시 띄우면 기록이 사라져, 재시작을 반복하면 무제한이 된다

표에 두면 둘 다 없어지고, 검증 스크립트가 상태를 지울 수 있어
「몇 번째 실행인지에 따라 결과가 달라지는」 검증도 피할 수 있다.

성공한 조회는 세지 않는다. 자기 예약을 여러 번 확인하는 것은 정상이다.
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LookupAttempt(Base):
    """IP 하나당 한 행. 실패가 쌓이면 잠시 막는다."""

    __tablename__ = "lookup_attempts"

    # IPv6 까지 담을 수 있는 길이. 프록시 뒤라면 실제 이용자의 주소가 들어간다.
    ip_address: Mapped[str] = mapped_column(String(64), primary_key=True)

    fail_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 현재 세는 구간이 시작된 시각. 구간을 넘기면 0부터 다시 센다.
    window_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # 이 시각까지는 조회를 받지 않는다.
    #
    # **막혀 있지 않으면 NULL 이다.** 「막히지 않음」을 현재 시각으로 표현하면
    # 안 된다. MySQL 의 DATETIME 은 소수점 이하를 **반올림**하므로,
    # 12:00:00.7 을 넣으면 12:00:01 로 저장되어 0.3초 동안 미래가 된다.
    # 그 사이에 들어온 다음 요청이 이유 없이 막힌다.
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<LookupAttempt {self.ip_address} fail={self.fail_count}>"
