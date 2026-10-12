"""widen ContributionRate rate_pct precision to allow >100% (UK small-employer recovery rate)

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-09-08 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4a5b6c7d8e9'
down_revision: Union[str, Sequence[str], None] = 'e3f4a5b6c7d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    ZP-TAX-UK-2026-27-001 s.11.1: the small-employer Statutory Family Pay
    recovery rate is 109% (employers recover MORE than they paid out) —
    a genuine, real statutory value that exceeds the previous
    Numeric(6,4) column's ~99.9999% ceiling. Widened to Numeric(7,4)
    (max ~999.9999%), comfortably covering this and any realistic future
    value, without switching away from exact decimal precision.
    """
    op.alter_column('payroll_contribution_rates', 'employee_rate_pct', type_=sa.Numeric(7, 4))
    op.alter_column('payroll_contribution_rates', 'employer_rate_pct', type_=sa.Numeric(7, 4))


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('payroll_contribution_rates', 'employee_rate_pct', type_=sa.Numeric(6, 4))
    op.alter_column('payroll_contribution_rates', 'employer_rate_pct', type_=sa.Numeric(6, 4))
