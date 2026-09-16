"""add payslip_items au_statutory_deductions_total column

Revision ID: f1b78410d568
Revises: 17cdc71d4d8e
Create Date: 2026-09-16

Australia 2026-27 statutory build (ZP-TAX-AU-2026-27-001), child support/
garnishee Phase 5 — a real employee deduction, summed into
total_employee_deductions/net_pay. See
models.PayslipItem.au_statutory_deductions_total's own docstring.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1b78410d568'
down_revision: Union[str, Sequence[str], None] = '17cdc71d4d8e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payslip_items', sa.Column('au_statutory_deductions_total', sa.Numeric(12, 2), server_default='0'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payslip_items', 'au_statutory_deductions_total')
