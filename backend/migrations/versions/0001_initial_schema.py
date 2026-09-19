"""initial schema — 전 테이블 생성.

Revision ID: 0001
Revises:
Create Date: 2026-09-17

이 리비전은 Alembic 도입 시점의 모델(`app/models`)을 그대로 얼린 것이다.
이후 모델을 바꾸면 이 파일을 고치지 말고 새 리비전을 만든다.

    python -m alembic revision --autogenerate -m "무엇을 바꾸는가"

테이블 옵션을 명시하는 이유
--------------------------
데이터베이스를 누가 어떻게 만들었는지에 따라 기본 문자셋이 다르다.
`CREATE DATABASE foo` 만 친 서버 기본값은 MySQL 8 에서 `utf8mb4_0900_ai_ci`,
오래된 서버나 호스팅에서는 `latin1` 인 경우도 있다. `latin1` 테이블에는
회장명·성명 같은 일본어가 들어가지 않는다. 그래서 DB 기본값에 기대지 않고
테이블마다 `utf8mb4` / `utf8mb4_general_ci` / `InnoDB`(외래키) 를 못 박는다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_general_ci",
}


def upgrade() -> None:
    op.create_table('admin_users',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('login_id', sa.String(length=60), nullable=False, comment='로그인 ID'),
    sa.Column('password_hash', sa.String(length=255), nullable=False, comment='bcrypt 해시. 평문은 어디에도 남기지 않는다'),
    sa.Column('name', sa.String(length=120), nullable=False, comment='담당자명'),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('role', sa.Enum('SYSTEM_ADMIN', 'BUSINESS_ADMIN', 'STAFF', name='admin_role_enum'), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False, comment='퇴직·휴직 시 False. 계정을 지우지 않는 것은 조작 로그를 살리기 위함'),
    sa.Column('last_login_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('login_id'),
    comment='管理画面ログインアカウント',
    **TABLE_OPTS,
    )
    op.create_table('exam_options',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('code', sa.String(length=20), nullable=False, comment='옵션 검사 코드'),
    sa.Column('name', sa.String(length=120), nullable=False, comment='검사명'),
    sa.Column('description', sa.Text(), nullable=False, comment='이용자 화면에 보여 줄 설명'),
    sa.Column('note', sa.String(length=255), nullable=False, comment='주의 사항 (금식 등)'),
    sa.Column('target_gender', sa.String(length=3), nullable=False, comment='M / F / ALL'),
    sa.Column('target_age_min', sa.Integer(), nullable=False, comment='타깃 최소 연령 (만)'),
    sa.Column('target_age_max', sa.Integer(), nullable=False, comment='타깃 최대 연령 (만)'),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code'),
    comment='オプション検査マスタ (年齢・性別対象条件を含む)',
    **TABLE_OPTS,
    )
    op.create_table('hospitals',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('code', sa.String(length=20), nullable=False, comment='회장 코드 (会場番号 연계 키)'),
    sa.Column('name', sa.String(length=120), nullable=False, comment='회장명'),
    sa.Column('name_kana', sa.String(length=200), nullable=False, comment='회장명 요미가나 (검색용)'),
    sa.Column('area', sa.String(length=40), nullable=False, comment='地域 (지역 필터의 축)'),
    sa.Column('city', sa.String(length=60), nullable=False, comment='区・市町村'),
    sa.Column('region', sa.String(length=100), nullable=False, comment='표시용 — 地域+区市町村'),
    sa.Column('postal_code', sa.String(length=10), nullable=False),
    sa.Column('address', sa.String(length=255), nullable=False),
    sa.Column('tel', sa.String(length=30), nullable=False, comment='비우면 공통 문의처를 사용'),
    sa.Column('transit_info', sa.String(length=200), nullable=False, comment='交通情報 — 최기역·출구'),
    sa.Column('access_minutes', sa.String(length=40), nullable=False, comment='アクセス時間 — 徒歩5分'),
    sa.Column('has_parking', sa.Boolean(), nullable=False, comment='駐車場 유무'),
    sa.Column('latitude', sa.Double(), nullable=True, comment='緯度'),
    sa.Column('longitude', sa.Double(), nullable=True, comment='経度'),
    sa.Column('is_visible', sa.Boolean(), nullable=False, comment='예약 화면 표시/비표시'),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code'),
    comment='受診会場マスター — 場所',
    **TABLE_OPTS,
    )
    op.create_index('ix_hospital_visible', 'hospitals', ['is_visible', 'sort_order'], unique=False)
    op.create_table('lookup_attempts',
    sa.Column('ip_address', sa.String(length=64), nullable=False),
    sa.Column('fail_count', sa.Integer(), nullable=False),
    sa.Column('window_start', sa.DateTime(), nullable=False),
    sa.Column('blocked_until', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('ip_address'),
    **TABLE_OPTS,
    )
    op.create_table('mail_templates',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('template_key', sa.Enum('RESERVE_COMPLETE', 'RESERVE_CHANGE', 'RESERVE_CHANGE_CLINIC', 'REMINDER', 'LOOKUP_LINK', 'SCHEDULE_CHANGED', name='mail_template_key_enum'), nullable=False),
    sa.Column('subject', sa.String(length=255), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('updated_by', sa.String(length=120), nullable=False, comment='마지막으로 고친 담당자'),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('template_key'),
    comment='メール本文テンプレート',
    **TABLE_OPTS,
    )
    op.create_table('postal_codes',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('zipcode', sa.String(length=7), nullable=False, comment='우편번호 7자리'),
    sa.Column('prefecture', sa.String(length=20), nullable=False, comment='도도부현'),
    sa.Column('city', sa.String(length=60), nullable=False, comment='시구정촌'),
    sa.Column('town', sa.String(length=120), nullable=False, comment='정역'),
    sa.Column('prefecture_kana', sa.String(length=40), nullable=False),
    sa.Column('city_kana', sa.String(length=120), nullable=False),
    sa.Column('town_kana', sa.String(length=200), nullable=False),
    sa.Column('search_text', sa.String(length=200), nullable=False, comment='검색용 — 도도부현+시구정촌+정역'),
    sa.Column('search_kana', sa.String(length=360), nullable=False, comment='검색용 — 위의 후리가나'),
    sa.PrimaryKeyConstraint('id'),
    comment='郵便番号 ↔ 住所 (日本郵便 KEN_ALL)',
    **TABLE_OPTS,
    )
    op.create_index('ix_postal_search', 'postal_codes', ['search_text'], unique=False)
    op.create_index('ix_postal_zipcode', 'postal_codes', ['zipcode'], unique=False)
    op.create_table('target_persons',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('last_name', sa.String(length=60), nullable=False, comment='성 (한자) 예: 田中'),
    sa.Column('first_name', sa.String(length=60), nullable=False, comment='이름 (한자) 예: 太郎'),
    sa.Column('last_name_kana', sa.String(length=60), nullable=False, comment='성 후리가나 (전각 가타카나) 예: タナカ'),
    sa.Column('first_name_kana', sa.String(length=60), nullable=False, comment='이름 후리가나 (전각 가타카나) 예: タロウ'),
    sa.Column('middle_name', sa.String(length=120), nullable=False, comment='미들네임 (표기)'),
    sa.Column('middle_name_kana', sa.String(length=120), nullable=False, comment='미들네임 후리가나 (전각 가타카나)'),
    sa.Column('gender', sa.Enum('M', 'F', name='gender_enum'), nullable=False, comment='성별 M=남성 F=여성'),
    sa.Column('birth_date', sa.Date(), nullable=False, comment='생년월일 (서기)'),
    sa.Column('insurer_no', sa.String(length=20), nullable=False, comment='보험자 번호'),
    sa.Column('insurance_symbol', sa.String(length=20), nullable=False, comment='기호'),
    sa.Column('insurance_no', sa.String(length=20), nullable=False, comment='번호'),
    sa.PrimaryKeyConstraint('id'),
    comment='健康診断対象者名簿（身元情報専用）',
    **TABLE_OPTS,
    )
    op.create_index('ix_target_lookup', 'target_persons', ['birth_date', 'insurer_no', 'insurance_symbol', 'insurance_no'], unique=False)
    op.create_index('ix_target_name', 'target_persons', ['last_name', 'first_name'], unique=False)
    op.create_table('audit_logs',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('admin_user_id', sa.Integer(), nullable=True),
    sa.Column('admin_login_id', sa.String(length=60), nullable=False, comment='계정이 지워져도 남는 조작자 표기'),
    sa.Column('admin_name', sa.String(length=120), nullable=False),
    sa.Column('action', sa.String(length=60), nullable=False, comment='예: RESERVATION_CANCEL'),
    sa.Column('target_type', sa.String(length=60), nullable=False),
    sa.Column('target_id', sa.Integer(), nullable=True),
    sa.Column('target_label', sa.String(length=255), nullable=False, comment='목록에서 바로 알아볼 표기'),
    sa.Column('before_json', sa.JSON(), nullable=True),
    sa.Column('after_json', sa.JSON(), nullable=True),
    sa.Column('batch_id', sa.String(length=40), nullable=False, comment='한 번의 일괄 저장을 묶는 열쇠'),
    sa.Column('ip_address', sa.String(length=45), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['admin_user_id'], ['admin_users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    comment='管理画面操作ログ',
    **TABLE_OPTS,
    )
    op.create_index('ix_audit_admin', 'audit_logs', ['admin_user_id', 'created_at'], unique=False)
    op.create_index('ix_audit_batch', 'audit_logs', ['batch_id'], unique=False)
    op.create_index('ix_audit_created', 'audit_logs', ['created_at'], unique=False)
    op.create_index('ix_audit_target', 'audit_logs', ['target_type', 'target_id'], unique=False)
    op.create_table('hospital_schedules',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('hospital_id', sa.Integer(), nullable=False),
    sa.Column('event_date', sa.Date(), nullable=False, comment='開催日'),
    sa.Column('booking_close_date', sa.Date(), nullable=True, comment='予約終了 — 이 날까지 접수'),
    sa.Column('open_time', sa.Time(), nullable=True, comment='開始時刻'),
    sa.Column('reception_end_time', sa.Time(), nullable=True, comment='受付終了'),
    sa.Column('is_visible', sa.Boolean(), nullable=False, comment='이 회차만 감출 때 사용'),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('note', sa.String(length=200), nullable=False, comment='회차 메모 (오전만 개최 등)'),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('cap_0900', sa.Integer(), nullable=True, comment='09:00～09:30 정원'),
    sa.Column('cap_0930', sa.Integer(), nullable=True, comment='09:30～10:00 정원'),
    sa.Column('cap_1000', sa.Integer(), nullable=True, comment='10:00～10:30 정원'),
    sa.Column('cap_1030', sa.Integer(), nullable=True, comment='10:30～11:00 정원'),
    sa.Column('cap_1100', sa.Integer(), nullable=True, comment='11:00～11:30 정원'),
    sa.Column('cap_1130', sa.Integer(), nullable=True, comment='11:30～12:00 정원'),
    sa.Column('cap_1200', sa.Integer(), nullable=True, comment='12:00～12:30 정원'),
    sa.Column('cap_1230', sa.Integer(), nullable=True, comment='12:30～13:00 정원'),
    sa.Column('cap_1300', sa.Integer(), nullable=True, comment='13:00～13:30 정원'),
    sa.Column('cap_1330', sa.Integer(), nullable=True, comment='13:30～14:00 정원'),
    sa.Column('cap_1400', sa.Integer(), nullable=True, comment='14:00～14:30 정원'),
    sa.Column('cap_1430', sa.Integer(), nullable=True, comment='14:30～15:00 정원'),
    sa.Column('cap_1500', sa.Integer(), nullable=True, comment='15:00～15:30 정원'),
    sa.Column('cap_1530', sa.Integer(), nullable=True, comment='15:30～16:00 정원'),
    sa.Column('cap_1600', sa.Integer(), nullable=True, comment='16:00～16:30 정원'),
    sa.Column('cap_1630', sa.Integer(), nullable=True, comment='16:30～17:00 정원'),
    sa.Column('closed_mask', sa.Integer(), nullable=False, comment='시간대 강제 마감 (16비트)'),
    sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('hospital_id', 'event_date', name='uq_schedule_unique'),
    comment='会場別開催回',
    **TABLE_OPTS,
    )
    op.create_index('ix_schedule_hospital', 'hospital_schedules', ['hospital_id', 'event_date'], unique=False)
    op.create_index('ix_schedule_open', 'hospital_schedules', ['event_date', 'booking_close_date'], unique=False)
    op.create_table('reservation_counts',
    sa.Column('schedule_id', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('res_0900', sa.Integer(), nullable=False, comment='09:00～09:30 예약 수'),
    sa.Column('res_0930', sa.Integer(), nullable=False, comment='09:30～10:00 예약 수'),
    sa.Column('res_1000', sa.Integer(), nullable=False, comment='10:00～10:30 예약 수'),
    sa.Column('res_1030', sa.Integer(), nullable=False, comment='10:30～11:00 예약 수'),
    sa.Column('res_1100', sa.Integer(), nullable=False, comment='11:00～11:30 예약 수'),
    sa.Column('res_1130', sa.Integer(), nullable=False, comment='11:30～12:00 예약 수'),
    sa.Column('res_1200', sa.Integer(), nullable=False, comment='12:00～12:30 예약 수'),
    sa.Column('res_1230', sa.Integer(), nullable=False, comment='12:30～13:00 예약 수'),
    sa.Column('res_1300', sa.Integer(), nullable=False, comment='13:00～13:30 예약 수'),
    sa.Column('res_1330', sa.Integer(), nullable=False, comment='13:30～14:00 예약 수'),
    sa.Column('res_1400', sa.Integer(), nullable=False, comment='14:00～14:30 예약 수'),
    sa.Column('res_1430', sa.Integer(), nullable=False, comment='14:30～15:00 예약 수'),
    sa.Column('res_1500', sa.Integer(), nullable=False, comment='15:00～15:30 예약 수'),
    sa.Column('res_1530', sa.Integer(), nullable=False, comment='15:30～16:00 예약 수'),
    sa.Column('res_1600', sa.Integer(), nullable=False, comment='16:00～16:30 예약 수'),
    sa.Column('res_1630', sa.Integer(), nullable=False, comment='16:30～17:00 예약 수'),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['schedule_id'], ['hospital_schedules.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('schedule_id'),
    comment='開催回別時間帯予約数 (reservations から派生)',
    **TABLE_OPTS,
    )
    op.create_table('reservations',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('reservation_no', sa.String(length=12, collation='utf8mb4_bin'), nullable=False, comment='자동 생성 예약번호 — 무작위 12자 · 대소문자 구별 (core/reservation_no.py)'),
    sa.Column('schedule_id', sa.Integer(), nullable=False),
    sa.Column('hospital_id', sa.Integer(), nullable=False),
    sa.Column('slot_date', sa.Date(), nullable=False, comment='검진일'),
    sa.Column('start_time', sa.Time(), nullable=False),
    sa.Column('end_time', sa.Time(), nullable=False),
    sa.Column('channel', sa.Enum('WEB', 'POSTAL', name='reservation_channel_enum'), nullable=False),
    sa.Column('status', sa.Enum('CONFIRMED', 'PENDING', 'CANCELLED', name='reservation_status_enum'), nullable=False),
    sa.Column('target_person_id', sa.Integer(), nullable=True, comment='검진 대상자 명부 연결. 우편 접수는 비어 있을 수 있다'),
    sa.Column('last_name', sa.String(length=60), nullable=False),
    sa.Column('first_name', sa.String(length=60), nullable=False),
    sa.Column('last_name_kana', sa.String(length=60), nullable=False),
    sa.Column('first_name_kana', sa.String(length=60), nullable=False),
    sa.Column('middle_name', sa.String(length=120), nullable=False),
    sa.Column('middle_name_kana', sa.String(length=120), nullable=False),
    sa.Column('gender', sa.Enum('M', 'F', name='reservation_gender_enum'), nullable=False),
    sa.Column('birth_date', sa.Date(), nullable=False, comment='서기 표기'),
    sa.Column('insurer_no', sa.String(length=30), nullable=False),
    sa.Column('insurance_symbol', sa.String(length=30), nullable=False),
    sa.Column('insurance_no', sa.String(length=30), nullable=False),
    sa.Column('postal_code', sa.String(length=10), nullable=False),
    sa.Column('address', sa.String(length=255), nullable=False),
    sa.Column('address_detail', sa.String(length=255), nullable=False),
    sa.Column('building', sa.String(length=255), nullable=False, comment='아파트·맨션명 [임의]'),
    sa.Column('tel_mobile', sa.String(length=30), nullable=False),
    sa.Column('tel_home', sa.String(length=30), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False, comment='[임의] 미입력이면 메일을 보내지 않는다'),
    sa.Column('fiscal_year', sa.Integer(), nullable=False, comment='중복 판정용 회계연도 (4/1 기준)'),
    sa.Column('memo', sa.Text(), nullable=False, comment='스태프 메모 (이용자에게 보이지 않음)'),
    sa.Column('has_defect', sa.Boolean(), nullable=False, comment='불비 여부. 우편 접수에서 항목이 빠진 채 임시 등록된 경우 True'),
    sa.Column('defect_note', sa.String(length=255), nullable=False, comment='무엇이 빠졌는지'),
    sa.Column('created_by_admin_id', sa.Integer(), nullable=True, comment='우편 접수를 대리 등록한 스태프'),
    sa.Column('cancelled_at', sa.DateTime(), nullable=True),
    sa.Column('cancel_type', sa.String(length=16), nullable=False),
    sa.Column('cancel_reason', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by_admin_id'], ['admin_users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['schedule_id'], ['hospital_schedules.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['target_person_id'], ['target_persons.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('reservation_no'),
    comment='健康診断予約',
    **TABLE_OPTS,
    )
    op.create_index('ix_res_created', 'reservations', ['created_at'], unique=False)
    op.create_index('ix_res_dup', 'reservations', ['fiscal_year', 'birth_date', 'last_name', 'first_name'], unique=False)
    op.create_index('ix_res_schedule', 'reservations', ['hospital_id', 'slot_date'], unique=False)
    op.create_index('ix_res_status', 'reservations', ['fiscal_year', 'status'], unique=False)
    op.create_table('contact_histories',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('reservation_id', sa.Integer(), nullable=False),
    sa.Column('contacted_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('admin_user_id', sa.Integer(), nullable=True),
    sa.Column('admin_name', sa.String(length=120), nullable=False, comment='담당자명 (계정이 지워져도 남는다)'),
    sa.Column('method', sa.Enum('TEL', 'MAIL', name='contact_method_enum'), nullable=False),
    sa.Column('result', sa.Enum('CONNECTED', 'NO_ANSWER', name='contact_result_enum'), nullable=False),
    sa.Column('memo', sa.Text(), nullable=False, comment='무엇을 확인·수정했는지'),
    sa.ForeignKeyConstraint(['admin_user_id'], ['admin_users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['reservation_id'], ['reservations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    comment='不備確認連絡履歴',
    **TABLE_OPTS,
    )
    op.create_index('ix_contact_reservation', 'contact_histories', ['reservation_id', 'contacted_at'], unique=False)
    op.create_table('mail_logs',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('reservation_id', sa.Integer(), nullable=True),
    sa.Column('reservation_no', sa.String(length=12, collation='utf8mb4_bin'), nullable=False),
    sa.Column('template_key', sa.String(length=30), nullable=False),
    sa.Column('to_email', sa.String(length=255), nullable=False),
    sa.Column('subject', sa.String(length=255), nullable=False),
    sa.Column('body', sa.Text(), nullable=False, comment='실제로 보낸 본문 (치환 완료 상태)'),
    sa.Column('status', sa.Enum('SUCCESS', 'FAILED', 'SKIPPED', name='mail_log_status_enum'), nullable=False),
    sa.Column('error_message', sa.String(length=255), nullable=False),
    sa.Column('sent_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['reservation_id'], ['reservations.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    comment='メール送信履歴',
    **TABLE_OPTS,
    )
    op.create_index('ix_maillog_reservation', 'mail_logs', ['reservation_id'], unique=False)
    op.create_index('ix_maillog_sent', 'mail_logs', ['sent_at'], unique=False)
    op.create_index('ix_maillog_status', 'mail_logs', ['status', 'sent_at'], unique=False)
    op.create_table('reservation_options',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('reservation_id', sa.Integer(), nullable=False),
    sa.Column('exam_option_id', sa.Integer(), nullable=True),
    sa.Column('option_code', sa.String(length=20), nullable=False),
    sa.Column('option_name', sa.String(length=120), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['exam_option_id'], ['exam_options.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['reservation_id'], ['reservations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('reservation_id', 'exam_option_id', name='uq_res_option'),
    comment='予約別オプション検査',
    **TABLE_OPTS,
    )


def downgrade() -> None:
    op.drop_table('reservation_options')
    op.drop_index('ix_maillog_status', table_name='mail_logs')
    op.drop_index('ix_maillog_sent', table_name='mail_logs')
    op.drop_index('ix_maillog_reservation', table_name='mail_logs')
    op.drop_table('mail_logs')
    op.drop_index('ix_contact_reservation', table_name='contact_histories')
    op.drop_table('contact_histories')
    op.drop_index('ix_res_status', table_name='reservations')
    op.drop_index('ix_res_schedule', table_name='reservations')
    op.drop_index('ix_res_dup', table_name='reservations')
    op.drop_index('ix_res_created', table_name='reservations')
    op.drop_table('reservations')
    op.drop_table('reservation_counts')
    op.drop_index('ix_schedule_open', table_name='hospital_schedules')
    op.drop_index('ix_schedule_hospital', table_name='hospital_schedules')
    op.drop_table('hospital_schedules')
    op.drop_index('ix_audit_target', table_name='audit_logs')
    op.drop_index('ix_audit_created', table_name='audit_logs')
    op.drop_index('ix_audit_batch', table_name='audit_logs')
    op.drop_index('ix_audit_admin', table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_index('ix_target_name', table_name='target_persons')
    op.drop_index('ix_target_lookup', table_name='target_persons')
    op.drop_table('target_persons')
    op.drop_index('ix_postal_zipcode', table_name='postal_codes')
    op.drop_index('ix_postal_search', table_name='postal_codes')
    op.drop_table('postal_codes')
    op.drop_table('mail_templates')
    op.drop_table('lookup_attempts')
    op.drop_index('ix_hospital_visible', table_name='hospitals')
    op.drop_table('hospitals')
    op.drop_table('exam_options')
    op.drop_table('admin_users')
