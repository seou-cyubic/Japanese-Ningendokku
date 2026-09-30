"""site_sessions — 이용자 화면 로그인 세션을 서버에 둔다.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-28

0002 에서는 로그인 여부를 서명 쿠키에만 담아, 서버를 다시 켜도 로그인이
살아 있었다. 세션을 이 표에 두고 서버가 뜰 때 비운다
(`app/models/site_user.py` 의 SiteSession 참조).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_general_ci",
}


def upgrade() -> None:
    # Alembic 도입 전 DB 를 받아들이는 경로(`db_setup.adopt_legacy_schema`)는
    # 모델의 표를 전부 만든 뒤 0001 도장을 찍는다. 그때는 이미 있다.
    if 'site_sessions' in sa.inspect(op.get_bind()).get_table_names():
        return

    op.create_table('site_sessions',
    sa.Column('token_hash', sa.String(length=64), nullable=False, comment='쿠키 토큰의 SHA-256 (원문은 두지 않는다)'),
    sa.Column('site_user_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['site_user_id'], ['site_users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('token_hash'),
    comment='利用者画面ログインセッション (サーバー起動時に全削除)',
    **TABLE_OPTS,
    )
    op.create_index('ix_site_sessions_user', 'site_sessions', ['site_user_id'], unique=False)
    op.create_index('ix_site_sessions_expires', 'site_sessions', ['expires_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_site_sessions_expires', table_name='site_sessions')
    op.drop_index('ix_site_sessions_user', table_name='site_sessions')
    op.drop_table('site_sessions')
