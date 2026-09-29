"""create auth_email_events audit table

Revision ID: d4e5f6a7c8b9
Revises: a5f6e7d8c9b0
Create Date: 2026-09-23 00:00:00.000000

Records-of-truth for every auth-module email send (see modules/auth/models.py
AuthEmailEvent and modules/auth/service.py _dispatch_email_guarded). Purely
additive: one new table, nothing altered or dropped.

The live migrated database is skipped by app/database.py's create_all
bootstrap ("Existing tables detected — skipping schema creation."), so this
revision is what actually delivers the table to existing environments.

Table/column/constraint definitions mirror modules/auth/models.py exactly
(DateTime without tz, python-side default for outcome/created_at only — no
server_default). Written defensively, same convention as the billing layer:
the table — and each index that belongs to it — is created only when absent,
so a database already bootstrapped by create_all (migrations/create_all)
degrades this revision to a no-op instead of aborting.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7c8b9'
down_revision: Union[str, Sequence[str], None] = 'a5f6e7d8c9b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'auth_email_events' in inspector.get_table_names():
        return

    op.create_table(
        'auth_email_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('event_type', sa.String(length=80), nullable=False),
        sa.Column('template_id', sa.String(length=20), nullable=False),
        sa.Column('recipient_email', sa.String(length=200), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('organization_id', sa.Integer(), nullable=True),
        sa.Column('actor_user_id', sa.Integer(), nullable=True),
        sa.Column('idempotency_key', sa.String(length=220), nullable=False, unique=True),
        sa.Column('outcome', sa.String(length=24), nullable=False),
        sa.Column('provider_response', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )
    op.create_index(op.f('ix_auth_email_events_id'), 'auth_email_events', ['id'], unique=False)
    op.create_index(op.f('ix_auth_email_events_event_type'), 'auth_email_events', ['event_type'], unique=False)
    op.create_index(op.f('ix_auth_email_events_recipient_email'), 'auth_email_events', ['recipient_email'], unique=False)
    op.create_index(op.f('ix_auth_email_events_user_id'), 'auth_email_events', ['user_id'], unique=False)
    op.create_index(op.f('ix_auth_email_events_organization_id'), 'auth_email_events', ['organization_id'], unique=False)
    op.create_index(op.f('ix_auth_email_events_actor_user_id'), 'auth_email_events', ['actor_user_id'], unique=False)
    op.create_index(op.f('ix_auth_email_events_idempotency_key'), 'auth_email_events', ['idempotency_key'], unique=True)
    op.create_index(op.f('ix_auth_email_events_created_at'), 'auth_email_events', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'auth_email_events' not in inspector.get_table_names():
        return
    op.drop_index(op.f('ix_auth_email_events_created_at'), table_name='auth_email_events')
    op.drop_index(op.f('ix_auth_email_events_idempotency_key'), table_name='auth_email_events')
    op.drop_index(op.f('ix_auth_email_events_actor_user_id'), table_name='auth_email_events')
    op.drop_index(op.f('ix_auth_email_events_organization_id'), table_name='auth_email_events')
    op.drop_index(op.f('ix_auth_email_events_user_id'), table_name='auth_email_events')
    op.drop_index(op.f('ix_auth_email_events_recipient_email'), table_name='auth_email_events')
    op.drop_index(op.f('ix_auth_email_events_event_type'), table_name='auth_email_events')
    op.drop_index(op.f('ix_auth_email_events_id'), table_name='auth_email_events')
    op.drop_table('auth_email_events')