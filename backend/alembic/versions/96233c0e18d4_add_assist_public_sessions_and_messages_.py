"""add assist public sessions and messages tables

Revision ID: 96233c0e18d4
Revises: dde9b427b6bf
Create Date: 2026-08-21 18:57:45.510405

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '96233c0e18d4'
down_revision: Union[str, Sequence[str], None] = 'dde9b427b6bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('assist_public_sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('locale', sa.String(length=20), nullable=False),
    sa.Column('message_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_assist_public_sessions_id'), 'assist_public_sessions', ['id'], unique=False)
    op.create_table('assist_public_messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.ForeignKeyConstraint(['session_id'], ['assist_public_sessions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_assist_public_messages_id'), 'assist_public_messages', ['id'], unique=False)
    op.create_index('ix_assist_public_messages_session', 'assist_public_messages', ['session_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_assist_public_messages_session_id'), 'assist_public_messages', ['session_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_assist_public_messages_session_id'), table_name='assist_public_messages')
    op.drop_index('ix_assist_public_messages_session', table_name='assist_public_messages')
    op.drop_index(op.f('ix_assist_public_messages_id'), table_name='assist_public_messages')
    op.drop_table('assist_public_messages')
    op.drop_index(op.f('ix_assist_public_sessions_id'), table_name='assist_public_sessions')
    op.drop_table('assist_public_sessions')
