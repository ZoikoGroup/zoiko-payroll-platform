"""add Quebec HSF and labour standards columns

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-09-04 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'payslip_items',
        sa.Column('employer_qc_hsf', sa.Numeric(12, 2), nullable=True, server_default='0'),
    )
    op.add_column(
        'payslip_items',
        sa.Column('employer_qc_labour_standards', sa.Numeric(12, 2), nullable=True, server_default='0'),
    )
    op.add_column(
        'payroll_company_compliance',
        sa.Column('qc_hsf_employer_category', sa.String(30), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_company_compliance', 'qc_hsf_employer_category')
    op.drop_column('payslip_items', 'employer_qc_labour_standards')
    op.drop_column('payslip_items', 'employer_qc_hsf')
