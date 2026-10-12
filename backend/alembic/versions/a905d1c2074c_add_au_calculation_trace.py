"""add au calculation trace column

Revision ID: a905d1c2074c
Revises: 40efec6cf8b7
Create Date: 2026-09-17

Australia 2026-27 statutory build (ZP-TAX-AU-2026-27-001), §25
"Calculation Trace — Minimum Audit Payload" — payslip_items.
au_calculation_trace, an AU-only JSON payload recording how each AU
statutory figure (PAYG scale/coefficient band, STSL, Medicare Levy
Surcharge, Super Guarantee method, state payroll tax) was derived this
period. Option A of the two architecture choices raised in the
2026-09-16/17 gap analysis (a platform-wide PayrollCalculationTrace
table was the alternative, explicitly declined for now) — see
models.PayslipItem's own docstring.

NOTE: two alembic heads exist (b33ef13051bb from a merged billing branch,
40efec6cf8b7 from the AU branch) — this migration chains on the AU
branch's own head, same as every prior AU migration. Head reconciliation
is a separate, cross-team decision; this file is not applied to any
database.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a905d1c2074c'
down_revision: Union[str, Sequence[str], None] = '40efec6cf8b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payslip_items', sa.Column('au_calculation_trace', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payslip_items', 'au_calculation_trace')
