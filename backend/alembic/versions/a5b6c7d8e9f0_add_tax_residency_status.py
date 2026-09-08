"""add PayrollEmployee.tax_residency_status (India Old Regime senior/super-senior age bands)

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-09-09 01:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a5b6c7d8e9f0'
down_revision: Union[str, Sequence[str], None] = 'f4a5b6c7d8e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'payroll_employees',
        sa.Column('tax_residency_status', sa.String(20), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_employees', 'tax_residency_status')
