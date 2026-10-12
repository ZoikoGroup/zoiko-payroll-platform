"""add germany health fund u1 u2 rates

Revision ID: 9d2f4b6c8e1a
Revises: 7c9e1a2b3d4f
Create Date: 2026-09-04 00:00:00.000000

Phase 8U (docs/PHASE_8U_GERMANY_EMPLOYER_CONTRIBUTIONS_U1_U2_U3_ACCIDENT_REPORT.md).

Additive only: two new nullable columns on payroll_germany_health_funds —
u1_rate_pct, u2_rate_pct (spec §14/DE-D06: U1/U2 are health-fund/tariff
specific, not a national rate). NULL on every existing row (identical to
"not yet configured" — never interpreted as 0%). No existing column/table
altered or dropped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9d2f4b6c8e1a'
down_revision: Union[str, Sequence[str], None] = '7c9e1a2b3d4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payroll_germany_health_funds', sa.Column('u1_rate_pct', sa.Numeric(6, 4), nullable=True))
    op.add_column('payroll_germany_health_funds', sa.Column('u2_rate_pct', sa.Numeric(6, 4), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_germany_health_funds', 'u2_rate_pct')
    op.drop_column('payroll_germany_health_funds', 'u1_rate_pct')
