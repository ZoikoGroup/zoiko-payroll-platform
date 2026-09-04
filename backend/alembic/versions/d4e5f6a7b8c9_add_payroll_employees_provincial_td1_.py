"""add payroll_employees provincial_td1_claim_amount/qc_tp1015_claim_amount columns

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-03 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'payroll_employees',
        sa.Column('provincial_td1_claim_amount', sa.Numeric(precision=12, scale=2), nullable=True),
    )
    op.add_column(
        'payroll_employees',
        sa.Column('qc_tp1015_claim_amount', sa.Numeric(precision=12, scale=2), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_employees', 'qc_tp1015_claim_amount')
    op.drop_column('payroll_employees', 'provincial_td1_claim_amount')
