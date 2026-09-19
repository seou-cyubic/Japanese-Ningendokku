"""애플리케이션 설정.

.env 파일 또는 환경 변수에서 값을 읽는다.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

# 저장소에 그대로 적혀 있는 개발용 서명 키. 이 값을 쓰는 서버는 누구나
# 관리자 세션 쿠키를 위조할 수 있다 — 운영 모드에서는 기동을 거부한다.
DEFAULT_SECRET_KEY = "dev-only-secret-change-me"

# README §4 가 공개하는 개발용 계정. 운영 모드에서 그대로 남아 있으면
# 기동 로그에 경고를 남긴다(막지는 않는다 — DB 를 못 읽는 상황에서
# 서버가 아예 못 뜨는 쪽이 더 위험하다).
DEFAULT_ADMIN_PASSWORDS = {
    "admin": "admin1234",
    "manager": "manager1234",
    "staff": "staff1234",
}

# backend/ 디렉터리 (app/core/config.py 기준 2단계 위)
BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent
FRONTEND_DIR = PROJECT_DIR / "frontend"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- MySQL -----------------------------------------------------------
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_NAME: str = "kenshin_reservation"
    # 기동할 때 DB 생성 · 마이그레이션 · 필수 초기 데이터(계정 · 메일 문구)를 맞춘다.
    # 스키마 변경을 배포 절차에서 따로 돌리는 운영이라면 false 로 두고
    # `python -m scripts.setup_db` 를 직접 실행한다.
    DB_AUTO_MIGRATE: bool = True

    # --- 애플리케이션 ----------------------------------------------------
    # 「운영으로 돌리는 중인가」. production 이면 기본 서명 키·기본 비밀번호로는
    # 뜨지 않는다(app/main.py `_check_secrets`). 로컬 개발은 기본값 그대로 둔다.
    ENV: str = "development"
    SECRET_KEY: str = DEFAULT_SECRET_KEY
    VERIFY_TOKEN_TTL: int = 1800  # 30분

    # 관리자 세션 유효 시간(초). 기본 8시간 — 하루 근무를 한 번의 로그인으로 덮는다.
    ADMIN_SESSION_TTL: int = 28800
    # HTTPS 전용 쿠키. 로컬 개발(http)에서는 False 여야 쿠키가 저장된다.
    ADMIN_COOKIE_SECURE: bool = False

    # --- 예약 만료 정리 --------------------------------------------------
    # 검진 시각이 지난 예약은 자동으로 삭제한다.
    # 「09:00 예약을 10:00 에 삭제」 = 슬롯 시작 시각 + 유예 60분.
    RESERVATION_EXPIRE_GRACE_MINUTES: int = 60
    # 정리 작업 실행 주기(분). 0 이면 자동 실행하지 않는다(수동 스크립트만).
    RESERVATION_PURGE_INTERVAL_MINUTES: int = 10

    # --- 우편번호(주소) 데이터 -------------------------------------------
    # 「주소 찾기」(U-14)가 이 데이터 위에서 돈다. 없으면 검색이 조용히
    # 0건을 돌려주므로, 기동할 때 확인하고 없으면 채운다.
    #
    # 자동 적재는 백그라운드로 돌아 기동을 막지 않는다. 인터넷이 없는
    # 환경에서는 false 로 두고 POSTAL_SOURCE_FILE 을 쓰거나, 스크립트로
    # 직접 넣으면 된다.
    POSTAL_AUTO_IMPORT: bool = True
    # 이 수 미만이면 「온전하지 않음」으로 본다. 전체가 12만 건 남짓이다.
    # 0건이 아니라 임계값으로 보는 이유 : 적재 도중에 죽으면 3만 건쯤
    # 들어간 상태로 남는데, 0건이 아니라는 이유로 「있다」고 판정하면
    # 그 반쪽짜리 데이터로 계속 돈다.
    POSTAL_MIN_ROWS: int = 100000
    # 비우면 일본우편에서 내려받는다. 오프라인 설치용으로 파일 경로를 준다.
    POSTAL_SOURCE_FILE: str = ""

    # --- 메일 발신 (plan.md 미확정 E) ------------------------------------
    # RESEND_API_KEY 가 비어 있으면 실제 발송을 하지 않고 mail_logs 에만 기록한다.
    # 발신 인프라가 정해지기 전에도 「무엇이 언제 나갔어야 하는지」는 남는다.
    RESEND_API_KEY: str = ""
    MAIL_FROM: str = "kenshin@example.jp"
    MAIL_FROM_NAME: str = "医療法人 Sample Group 健康診断予約センター"

    # --- 접속 IP 판정 -----------------------------------------------------
    # 리버스 프록시(Nginx 등) 뒤에 둘 때만 true.
    #
    # X-Forwarded-For 는 누구나 마음대로 적어 보낼 수 있는 헤더다.
    # 프록시 없이 true 로 두면 예약 조회(U-20)의 시도 횟수 제한을
    # 헤더 값만 바꿔 가며 무한히 우회할 수 있다. 기본값은 반드시 false.
    TRUST_PROXY_HEADER: bool = False

    # --- 문의처 ----------------------------------------------------------
    CONTACT_TEL: str = "03-1234-5678"
    CONTACT_EMAIL: str = "kenshin@example.jp"
    CONTACT_HOURS: str = "平日 9:00～17:00（土日・祝日を除く）"

    # --- 프론트엔드 --------------------------------------------------------
    FRONTEND_URL: str = "http://127.0.0.1:8000"

    @property
    def database_url(self) -> URL:
        """SQLAlchemy 접속 URL (DB 지정).

        문자열로 이어 붙이지 않고 `URL.create` 로 만든다. 비밀번호에 `@`·`/`·
        `#`·`:` 가 들어 있으면 이어 붙인 문자열은 **다른 호스트·DB 로 읽힌다.**
        「비밀번호만 바꿨는데 접속이 안 된다」가 되므로 이스케이프를 맡긴다.
        """
        return self._url(self.DB_NAME)

    @property
    def server_url(self) -> URL:
        """DB 를 지정하지 않은 서버 접속 URL (DB 생성용)."""
        # `URL.set(database=None)` 은 None 을 「바꾸지 않음」으로 읽는다. 새로 만든다.
        return self._url(None)

    def _url(self, database: str | None) -> URL:
        return URL.create(
            "mysql+pymysql",
            username=self.DB_USER,
            password=self.DB_PASSWORD,
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=database,
            query={"charset": "utf8mb4"},
        )

    # --- 안전장치 --------------------------------------------------------
    @property
    def is_production(self) -> bool:
        """운영 모드인가.

        `ENV=production` 을 명시했거나, HTTPS 전용 쿠키를 켠 경우로 본다.
        후자를 함께 보는 이유는 「.env 를 새로 쓰면서 ENV 만 빠뜨렸다」가
        가장 흔한 실수이기 때문이다 — 그 경우에도 안전장치가 걸린다.
        """
        return (
            self.ENV.strip().lower() in ("production", "prod")
            or self.ADMIN_COOKIE_SECURE
        )

    @property
    def uses_default_secret_key(self) -> bool:
        return self.SECRET_KEY == DEFAULT_SECRET_KEY


settings = Settings()
