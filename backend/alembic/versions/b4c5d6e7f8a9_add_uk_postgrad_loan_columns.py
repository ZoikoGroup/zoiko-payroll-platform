"""add uk concurrent postgraduate loan columns

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-09-07 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4c5d6e7f8a9'
down_revision: Union[str, Sequence[str], None] = 'a3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'payroll_employees',
        sa.Column('has_postgrad_loan', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'payslip_items',
        sa.Column('postgrad_loan_deduction', sa.Numeric(12, 2), nullable=True, server_default='0'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payslip_items', 'postgrad_loan_deduction')
    op.drop_column('payroll_employees', 'has_postgrad_loan')
