"""add CPP base/first-additional breakdown columns

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-09-04 04:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, Sequence[str], None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'payslip_items',
        sa.Column('cpp_base_amount', sa.Numeric(12, 2), nullable=True, server_default='0'),
    )
    op.add_column(
        'payslip_items',
        sa.Column('cpp_first_additional_amount', sa.Numeric(12, 2), nullable=True, server_default='0'),
    )
    op.add_column(
        'payslip_items',
        sa.Column('employer_cpp_base', sa.Numeric(12, 2), nullable=True, server_default='0'),
    )
    op.add_column(
        'payslip_items',
        sa.Column('employer_cpp_first_additional', sa.Numeric(12, 2), nullable=True, server_default='0'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payslip_items', 'employer_cpp_first_additional')
    op.drop_column('payslip_items', 'employer_cpp_base')
    op.drop_column('payslip_items', 'cpp_first_additional_amount')
    op.drop_column('payslip_items', 'cpp_base_amount')
