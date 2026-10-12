"""add payroll_employees nj_rate_table column

Revision ID: ffa17bbaf0d1
Revises: 47244789b05a
Create Date: 2026-09-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ffa17bbaf0d1'
down_revision: Union[str, Sequence[str], None] = '47244789b05a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'payroll_employees',
        sa.Column('nj_rate_table', sa.String(2), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_employees', 'nj_rate_table')
