"""add us state-level statutory program deduction columns

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-09-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5d6e7f8a9b0'
down_revision: Union[str, Sequence[str], None] = 'b4c5d6e7f8a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'payslip_items',
        sa.Column('state_program_deductions', sa.Numeric(12, 2), nullable=True, server_default='0'),
    )
    op.add_column(
        'payslip_items',
        sa.Column('employer_state_program_contributions', sa.Numeric(12, 2), nullable=True, server_default='0'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payslip_items', 'employer_state_program_contributions')
    op.drop_column('payslip_items', 'state_program_deductions')
