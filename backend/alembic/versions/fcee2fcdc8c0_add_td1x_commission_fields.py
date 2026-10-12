"""add payroll_employees td1x commission fields

Revision ID: fcee2fcdc8c0
Revises: 581578d8b7e3
Create Date: 2026-09-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fcee2fcdc8c0'
down_revision: Union[str, Sequence[str], None] = '581578d8b7e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'payroll_employees',
        sa.Column('td1x_estimated_annual_commission', sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        'payroll_employees',
        sa.Column('td1x_estimated_annual_expenses', sa.Numeric(12, 2), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_employees', 'td1x_estimated_annual_expenses')
    op.drop_column('payroll_employees', 'td1x_estimated_annual_commission')
