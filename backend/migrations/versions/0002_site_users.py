"""site_users — 이용자 화면 입장 계정.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-28

이용자 화면에 처음 들어올 때 로그인을 거치게 하면서 생긴 표다.
관리 화면 계정(`admin_users`)과 섞지 않고 따로 둔다 (`app/models/site_user.py`).
초기 계정은 여기서 넣지 않는다 — 기동 시 `db_setup.seed_required` 가 표가
비어 있을 때만 넣는다. 마이그레이션에 넣으면 비밀번호 해시가 리비전 파일에
박제되고, 계정을 지운 뒤 다시 올려도 되살아나지 않는다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_general_ci",
}


def upgrade() -> None:
    # Alembic 도입 전 DB 를 받아들일 때(`db_setup.adopt_legacy_schema`)는 모델에
    # 있는 표를 전부 만든 뒤 0001 도장을 찍는다. 그 경로로 온 DB 에는 이 표가
    # 이미 있으므로 다시 만들지 않는다.
    if 'site_users' in sa.inspect(op.get_bind()).get_table_names():
        return

    op.create_table('site_users',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('login_id', sa.String(length=60), nullable=False, comment='로그인 ID'),
    sa.Column('password_hash', sa.String(length=255), nullable=False, comment='bcrypt 해시. 평문은 어디에도 남기지 않는다'),
    sa.Column('name', sa.String(length=120), nullable=False, comment='계정 설명 (누구에게 나눠 준 계정인가)'),
    sa.Column('is_active', sa.Boolean(), nullable=False, comment='False 면 로그인 · 기존 세션 모두 막힌다'),
    sa.Column('last_login_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('login_id'),
    comment='利用者画面ログインアカウント',
    **TABLE_OPTS,
    )


def downgrade() -> None:
    op.drop_table('site_users')
