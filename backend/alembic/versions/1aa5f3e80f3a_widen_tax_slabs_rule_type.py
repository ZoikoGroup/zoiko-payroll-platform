"""widen tax_slabs rule_type to varchar 30

Revision ID: 1aa5f3e80f3a
Revises: 518b8d4a5e46
Create Date: 2026-09-17

Found via LIVE data entry of ZP-TAX-AU-2026-27-001's §7 extra-pay-
calendar table — "AU_EXTRA_PAY_WITHHOLDING" (25 chars) exceeded
payroll_tax_slabs.rule_type's VARCHAR(20) limit, causing a
StringDataRightTruncation error on insert, same bug class as the
filing_status column widened in 518b8d4a5e46 moments earlier. Never
caught by pytest (in-memory dataclass contexts never touch this
column). Purely additive (widening, no data loss).

NOTE: two alembic heads exist (b33ef13051bb from a merged billing branch,
518b8d4a5e46 from the AU branch) — this migration chains on the AU
branch's own head, same as every prior AU migration. Head reconciliation
is a separate, cross-team decision.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1aa5f3e80f3a'
down_revision: Union[str, Sequence[str], None] = '518b8d4a5e46'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('payroll_tax_slabs', 'rule_type', type_=sa.String(30), existing_type=sa.String(20))


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('payroll_tax_slabs', 'rule_type', type_=sa.String(20), existing_type=sa.String(30))
