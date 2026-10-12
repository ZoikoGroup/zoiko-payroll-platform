"""Add stripe fields

Revision ID: bb8ad4440e65
Revises: 737e7bfa2d77
Create Date: 2026-09-16 12:40:02.448444

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'bb8ad4440e65'
down_revision: Union[str, Sequence[str], None] = '737e7bfa2d77'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('billing_commercial_audit_events', sa.Column('stripe_event_id', sa.String(length=100), nullable=True))
    op.create_index(op.f('ix_billing_commercial_audit_events_stripe_event_id'), 'billing_commercial_audit_events', ['stripe_event_id'], unique=True)
    op.add_column('billing_plan_versions', sa.Column('stripe_price_id', sa.String(length=100), nullable=True))
    op.create_index(op.f('ix_billing_plan_versions_stripe_price_id'), 'billing_plan_versions', ['stripe_price_id'], unique=False)

def downgrade() -> None:
    op.drop_index(op.f('ix_billing_plan_versions_stripe_price_id'), table_name='billing_plan_versions')
    op.drop_column('billing_plan_versions', 'stripe_price_id')
    op.drop_index(op.f('ix_billing_commercial_audit_events_stripe_event_id'), table_name='billing_commercial_audit_events')
    op.drop_column('billing_commercial_audit_events', 'stripe_event_id')
