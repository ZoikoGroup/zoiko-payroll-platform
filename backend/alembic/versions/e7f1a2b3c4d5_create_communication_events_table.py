"""create communication_events audit table

Revision ID: e7f1a2b3c4d5
Revises: d4e5f6a7c8b9
Create Date: 2026-09-25 00:00:00.000000

Platform-wide record of truth for every outbound email (see
modules/communications/models.py CommunicationEvent and
modules/communications/service.py dispatch_email). Generalises
auth_email_events to every module. Purely additive: one new table, nothing
altered or dropped.

organization_id / recipient_user_id / actor_user_id are intentionally NOT
foreign keys — audit rows must outlive the tenant/user they describe.

Written defensively (same convention as d4e5f6a7c8b9): created only when
absent, so a database already bootstrapped by create_all degrades this
revision to a no-op instead of aborting.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7f1a2b3c4d5'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7c8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEXED = (
    'id', 'module', 'event_type', 'recipient_email', 'recipient_user_id',
    'organization_id', 'actor_user_id', 'created_at',
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'communication_events' in inspector.get_table_names():
        return

    op.create_table(
        'communication_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('module', sa.String(length=32), nullable=False),
        sa.Column('event_type', sa.String(length=80), nullable=False),
        sa.Column('template_id', sa.String(length=40), nullable=True),
        sa.Column('recipient_email', sa.String(length=200), nullable=False),
        sa.Column('recipient_user_id', sa.Integer(), nullable=True),
        sa.Column('organization_id', sa.Integer(), nullable=True),
        sa.Column('actor_user_id', sa.Integer(), nullable=True),
        sa.Column('idempotency_key', sa.String(length=255), nullable=True),
        sa.Column('outcome', sa.String(length=24), nullable=False),
        sa.Column('provider_response', sa.Text(), nullable=True),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    for column in _INDEXED:
        op.create_index(op.f(f'ix_communication_events_{column}'), 'communication_events', [column], unique=False)
    op.create_index(
        op.f('ix_communication_events_idempotency_key'), 'communication_events', ['idempotency_key'], unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'communication_events' not in inspector.get_table_names():
        return
    op.drop_index(op.f('ix_communication_events_idempotency_key'), table_name='communication_events')
    for column in reversed(_INDEXED):
        op.drop_index(op.f(f'ix_communication_events_{column}'), table_name='communication_events')
    op.drop_table('communication_events')
