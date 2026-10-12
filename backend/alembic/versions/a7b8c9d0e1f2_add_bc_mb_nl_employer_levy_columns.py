"""add BC/MB/NL employer levy columns

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-09-04 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'payslip_items',
        sa.Column('employer_bc_eht', sa.Numeric(12, 2), nullable=True, server_default='0'),
    )
    op.add_column(
        'payslip_items',
        sa.Column('employer_mb_he_levy', sa.Numeric(12, 2), nullable=True, server_default='0'),
    )
    op.add_column(
        'payslip_items',
        sa.Column('employer_nl_hapset', sa.Numeric(12, 2), nullable=True, server_default='0'),
    )
    op.add_column(
        'payroll_company_compliance',
        sa.Column('bc_eht_employer_classification', sa.String(20), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_company_compliance', 'bc_eht_employer_classification')
    op.drop_column('payslip_items', 'employer_nl_hapset')
    op.drop_column('payslip_items', 'employer_mb_he_levy')
    op.drop_column('payslip_items', 'employer_bc_eht')
