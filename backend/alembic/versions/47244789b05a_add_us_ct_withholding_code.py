"""add payroll_employees ct_withholding_code column

Revision ID: 47244789b05a
Revises: f61cb4b650f4
Create Date: 2026-09-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '47244789b05a'
down_revision: Union[str, Sequence[str], None] = 'f61cb4b650f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'payroll_employees',
        sa.Column('ct_withholding_code', sa.String(2), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_employees', 'ct_withholding_code')
