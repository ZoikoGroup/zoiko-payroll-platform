"""add payroll_employees federal W-4 §3.4 fields

Revision ID: ffe310357ab2
Revises: 57409546258c
Create Date: 2026-09-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ffe310357ab2'
down_revision: Union[str, Sequence[str], None] = '57409546258c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payroll_employees', sa.Column('w4_allowances_claimed', sa.Integer(), nullable=True))
    op.add_column(
        'payroll_employees',
        sa.Column('is_nonresident_alien', sa.Boolean(), nullable=False, server_default='false'),
    )
    op.add_column('payroll_employees', sa.Column('w4_dependents_credit_annual', sa.Numeric(12, 2), nullable=True))
    op.add_column('payroll_employees', sa.Column('w4_other_income_annual', sa.Numeric(12, 2), nullable=True))
    op.add_column('payroll_employees', sa.Column('w4_extra_withholding_per_period', sa.Numeric(12, 2), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_employees', 'w4_extra_withholding_per_period')
    op.drop_column('payroll_employees', 'w4_other_income_annual')
    op.drop_column('payroll_employees', 'w4_dependents_credit_annual')
    op.drop_column('payroll_employees', 'is_nonresident_alien')
    op.drop_column('payroll_employees', 'w4_allowances_claimed')
