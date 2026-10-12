"""widen tax_slabs filing_status to varchar 30

Revision ID: 518b8d4a5e46
Revises: 40efec6cf8b7
Create Date: 2026-09-17

Found via LIVE data entry of ZP-TAX-AU-2026-27-001's Schedule 8 STSL
family names — "STSL_CLAIMED_OR_FOREIGN" (24 chars) exceeded
payroll_tax_slabs.filing_status's VARCHAR(20) limit, causing a
StringDataRightTruncation error on insert. Never caught by pytest
(in-memory dataclass contexts never touch this column) — same
VARCHAR-limit bug class this project has hit before on CA/US builds.
Purely additive (widening, no data loss).

NOTE: two alembic heads exist (b33ef13051bb from a merged billing branch,
40efec6cf8b7 from the AU branch) — this migration chains on the AU
branch's own head, same as every prior AU migration. Head reconciliation
is a separate, cross-team decision.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '518b8d4a5e46'
down_revision: Union[str, Sequence[str], None] = '40efec6cf8b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('payroll_tax_slabs', 'filing_status', type_=sa.String(30), existing_type=sa.String(20))


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('payroll_tax_slabs', 'filing_status', type_=sa.String(20), existing_type=sa.String(30))
