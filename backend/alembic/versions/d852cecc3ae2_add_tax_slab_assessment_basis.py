"""add payroll_tax_slabs.assessment_basis column

Revision ID: d852cecc3ae2
Revises: 9f06735e9259
Create Date: 2026-09-10 00:00:00.000000

ZP-TAX-IN-2026-27-001 §12.1 gap-closure Phase C: which income figure a
PT_FLAT tier's min_amount/max_amount are measured against (NULL/
"MONTHLY_WAGE" = today's exact existing behavior; "HALF_YEAR_INCOME" =
Greater Chennai Corporation's local half-yearly schedule, §14.1). NULL
for every existing row — no calculation impact until a row explicitly
opts in.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd852cecc3ae2'
down_revision: Union[str, Sequence[str], None] = '9f06735e9259'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payroll_tax_slabs', sa.Column('assessment_basis', sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_tax_slabs', 'assessment_basis')
