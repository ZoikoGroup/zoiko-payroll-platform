"""add germany overtime grundlohn hourly field

Revision ID: b3f7c1a9d4e2
Revises: a1b2c3d4e5f6
Create Date: 2026-09-04 00:00:00.000000

Phase 8AB (docs/PHASE_8AB_GERMANY_GRUNDLOHN_SOURCE_IMPLEMENTATION.md).

Additive only:

One new nullable column on payroll_employee_statutory_profiles —
de_grundlohn_hourly (Numeric(10, 2)). NULL on every existing row (identical
to the "not yet captured" convention every other Germany statutory-profile
field on this table already uses). This is the approved Phase 8AB product
decision: an explicit, per-employee, effective-dated overtime/shift-premium
hourly Grundlohn (spec-adjacent — §3b EStG / §1 SvEV, Phase 8Z;
ARCHITECTURE_D, Phase 8AA) — never derived from salary, pay_frequency, or
any assumed hours formula. Not read by any calculation code this phase.

No existing column/table altered or dropped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3f7c1a9d4e2'
down_revision: Union[str, Sequence[str], None] = 'a4b5c6d7e8f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'payroll_employee_statutory_profiles',
        sa.Column('de_grundlohn_hourly', sa.Numeric(10, 2), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_employee_statutory_profiles', 'de_grundlohn_hourly')
