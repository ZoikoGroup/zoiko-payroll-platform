"""add payslip_items employer_payroll_tax column

Revision ID: 17cdc71d4d8e
Revises: 226e01315a66
Create Date: 2026-09-16

Australia 2026-27 statutory build (ZP-TAX-AU-2026-27-001), state/
territory employer payroll tax Phase 4 — one column across all 8
jurisdictions (an employee has at most one work_state). See
models.PayslipItem.employer_payroll_tax's own docstring.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '17cdc71d4d8e'
down_revision: Union[str, Sequence[str], None] = '226e01315a66'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payslip_items', sa.Column('employer_payroll_tax', sa.Numeric(12, 2), server_default='0'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payslip_items', 'employer_payroll_tax')
