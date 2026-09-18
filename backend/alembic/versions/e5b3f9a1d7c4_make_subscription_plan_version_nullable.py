"""make billing_subscriptions.plan_version_id nullable

Revision ID: e5b3f9a1d7c4
Revises: d4f8a2c7e6b1
Create Date: 2026-09-18 00:00:03.000000

Part 12 — an ENTERPRISE_ORDER_FORM subscription has no plan version at
all, by design (limits come from EnterpriseOrderForm.negotiated_scale_limits
instead). Every other billing_authority still always sets a real
plan_version_id in practice; this only relaxes the column constraint.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5b3f9a1d7c4'
down_revision: Union[str, Sequence[str], None] = 'd4f8a2c7e6b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('billing_subscriptions', 'plan_version_id', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.alter_column('billing_subscriptions', 'plan_version_id', existing_type=sa.Integer(), nullable=False)
