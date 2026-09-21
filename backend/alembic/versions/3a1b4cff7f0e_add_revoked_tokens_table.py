"""add revoked_tokens table

Revision ID: 3a1b4cff7f0e
Revises: 1dc04f15a9b7
Create Date: 2026-09-18 00:00:00.000000

Platform infrastructure fix plan, Tier 3: JWT revocation on logout.
Every access/refresh token now carries a `jti` claim (core/security.py);
this table records revoked ones so core/dependencies.py's get_current_user
can reject them before their own natural exp. auth/scheduler.py sweeps
rows whose expires_at has passed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '3a1b4cff7f0e'
down_revision: Union[str, Sequence[str], None] = '1dc04f15a9b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'revoked_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('jti', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_revoked_tokens_id'), 'revoked_tokens', ['id'], unique=False)
    op.create_index(op.f('ix_revoked_tokens_jti'), 'revoked_tokens', ['jti'], unique=True)


def downgrade() -> None:
    op.drop_table('revoked_tokens')
