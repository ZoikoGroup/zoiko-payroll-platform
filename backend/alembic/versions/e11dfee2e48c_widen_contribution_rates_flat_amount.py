"""widen contribution_rates flat_amount to numeric 14 2

Revision ID: e11dfee2e48c
Revises: 1aa5f3e80f3a
Create Date: 2026-09-17

Found via LIVE data entry of ZP-TAX-AU-2026-27-001's Northern Territory
payroll tax: the $100,000,000 high-rate group-wage threshold overflowed
payroll_contribution_rates.flat_amount's Numeric(10,2) capacity (max
99,999,999.99). Widened to Numeric(14,2), matching TaxSlab.min_amount/
max_amount's own precision for consistency. Purely additive, no data
loss. Never caught by pytest (in-memory contexts never round-trip
through the real DB column) — same bug class as the two VARCHAR fixes
moments earlier in this same session.

NOTE: two alembic heads exist (b33ef13051bb from a merged billing branch,
1aa5f3e80f3a from the AU branch) — this migration chains on the AU
branch's own head, same as every prior AU migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e11dfee2e48c'
down_revision: Union[str, Sequence[str], None] = '1aa5f3e80f3a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('payroll_contribution_rates', 'flat_amount', type_=sa.Numeric(14, 2), existing_type=sa.Numeric(10, 2))


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('payroll_contribution_rates', 'flat_amount', type_=sa.Numeric(10, 2), existing_type=sa.Numeric(14, 2))
