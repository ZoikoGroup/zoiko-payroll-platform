"""us employer tax profile: covered headcount + nullable sui fields

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-09-07 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd6e7f8a9b0c1'
down_revision: Union[str, Sequence[str], None] = 'c5d6e7f8a9b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'payroll_employer_tax_profiles',
        sa.Column('covered_employee_count', sa.Integer(), nullable=True),
    )
    op.alter_column('payroll_employer_tax_profiles', 'taxable_wage_base', existing_type=sa.Numeric(12, 2), nullable=True)
    op.alter_column('payroll_employer_tax_profiles', 'employer_rate_pct', existing_type=sa.Numeric(6, 4), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('payroll_employer_tax_profiles', 'employer_rate_pct', existing_type=sa.Numeric(6, 4), nullable=False)
    op.alter_column('payroll_employer_tax_profiles', 'taxable_wage_base', existing_type=sa.Numeric(12, 2), nullable=False)
    op.drop_column('payroll_employer_tax_profiles', 'covered_employee_count')
