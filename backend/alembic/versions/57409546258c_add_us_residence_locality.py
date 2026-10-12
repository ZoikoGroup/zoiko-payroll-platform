"""add payroll_employees residence_locality column

Revision ID: 57409546258c
Revises: ffa17bbaf0d1
Create Date: 2026-09-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '57409546258c'
down_revision: Union[str, Sequence[str], None] = 'ffa17bbaf0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'payroll_employees',
        sa.Column('residence_locality', sa.String(100), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_employees', 'residence_locality')
