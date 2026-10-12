"""add payroll_employees state_income_tax_election_pct column

Revision ID: 11f962110a47
Revises: a229ce14b4da
Create Date: 2026-09-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '11f962110a47'
down_revision: Union[str, Sequence[str], None] = 'a229ce14b4da'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'payroll_employees',
        sa.Column('state_income_tax_election_pct', sa.Numeric(5, 2), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_employees', 'state_income_tax_election_pct')
