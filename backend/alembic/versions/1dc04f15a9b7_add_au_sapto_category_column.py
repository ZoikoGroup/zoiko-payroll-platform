"""add au sapto category column

Revision ID: 1dc04f15a9b7
Revises: 02d251c47245
Create Date: 2026-09-17

Australia 2026-27 statutory build (ZP-TAX-AU-2026-27-001), §5 step 4
Phase 10 — payroll_employees.au_sapto_category, a self-declared seniors/
pensioners category ("SINGLE" | "COUPLE" | "ILLNESS_SEPARATED_COUPLE")
driving the SAPTO tax offset. See models.PayrollEmployee's own
docstring; only "SINGLE" resolves to a real offset today.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1dc04f15a9b7'
down_revision: Union[str, Sequence[str], None] = '02d251c47245'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payroll_employees', sa.Column('au_sapto_category', sa.String(length=30), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_employees', 'au_sapto_category')
