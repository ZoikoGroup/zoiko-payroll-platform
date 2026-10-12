"""widen payroll_tax_slabs.rate_pct/employer_rate_pct to numeric(6,4)

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-09-04 07:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, Sequence[str], None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        'payroll_tax_slabs', 'rate_pct',
        existing_type=sa.Numeric(5, 2), type_=sa.Numeric(6, 4), existing_nullable=False,
    )
    op.alter_column(
        'payroll_tax_slabs', 'employer_rate_pct',
        existing_type=sa.Numeric(5, 2), type_=sa.Numeric(6, 4), existing_nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        'payroll_tax_slabs', 'employer_rate_pct',
        existing_type=sa.Numeric(6, 4), type_=sa.Numeric(5, 2), existing_nullable=True,
    )
    op.alter_column(
        'payroll_tax_slabs', 'rate_pct',
        existing_type=sa.Numeric(6, 4), type_=sa.Numeric(5, 2), existing_nullable=False,
    )
