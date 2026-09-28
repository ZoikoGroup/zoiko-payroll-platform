"""add payslip_items.sgp_calculation_trace

Revision ID: d4e8f2a6b9c1
Revises: c3d9e1f4a7b2
Create Date: 2026-09-23

Singapore calculation trace persistence (ZP-SG-ENG-001, approved D-B) —
one nullable JSON column on payslip_items, the same country-scoped
precedent as au_calculation_trace. Additive only; every existing row keeps
NULL. Idempotent (inspector-guarded), same shape as c3d9e1f4a7b2.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e8f2a6b9c1'
down_revision: Union[str, Sequence[str], None] = 'c3d9e1f4a7b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns() -> set:
    return {col["name"] for col in sa.inspect(op.get_bind()).get_columns("payslip_items")}


def upgrade() -> None:
    """Upgrade schema."""
    if "sgp_calculation_trace" not in _existing_columns():
        op.add_column('payslip_items', sa.Column('sgp_calculation_trace', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    if "sgp_calculation_trace" in _existing_columns():
        op.drop_column('payslip_items', 'sgp_calculation_trace')
