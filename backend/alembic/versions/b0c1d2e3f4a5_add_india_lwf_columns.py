"""add india labour welfare fund payslip item columns

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
Create Date: 2026-09-08 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b0c1d2e3f4a5'
down_revision: Union[str, Sequence[str], None] = 'a9b0c1d2e3f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'payslip_items',
        sa.Column('employee_lwf', sa.Numeric(12, 2), nullable=True, server_default='0'),
    )
    op.add_column(
        'payslip_items',
        sa.Column('employer_lwf', sa.Numeric(12, 2), nullable=True, server_default='0'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payslip_items', 'employer_lwf')
    op.drop_column('payslip_items', 'employee_lwf')
