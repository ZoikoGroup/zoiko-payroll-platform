"""add payroll_locality_rates bracket_schedule column

Revision ID: 941d9ec5ef7e
Revises: 14a7f3dd4c96
Create Date: 2026-09-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '941d9ec5ef7e'
down_revision: Union[str, Sequence[str], None] = '14a7f3dd4c96'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payroll_locality_rates', sa.Column('bracket_schedule', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_locality_rates', 'bracket_schedule')
