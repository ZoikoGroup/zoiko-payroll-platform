"""add lst exemption threshold

Revision ID: 4b296dbd4181
Revises: bb8ad4440e65
Create Date: 2026-09-16

Pennsylvania Local Services Tax (LST) low-income exemption threshold.
See models.LocalityRate.lst_exemption_threshold's own docstring.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4b296dbd4181'
down_revision: Union[str, Sequence[str], None] = 'bb8ad4440e65'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payroll_locality_rates', sa.Column('lst_exemption_threshold', sa.Numeric(12, 2), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_locality_rates', 'lst_exemption_threshold')
