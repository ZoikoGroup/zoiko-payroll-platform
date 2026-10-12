"""add au extra pay calendar column

Revision ID: d356014e3357
Revises: f1b78410d568
Create Date: 2026-09-17

Australia 2026-27 statutory build (ZP-TAX-AU-2026-27-001), Phase 7 —
the §7 "Extra-pay calendar" control (payroll_employees.au_extra_pay_calendar),
closing a previously-undisclosed gap: the 53-weekly-pays/27-fortnightly-pays
additional-withholding table had no employee-level control flag to gate it.
See models.PayrollEmployee.au_extra_pay_calendar's own docstring.

NOTE: two alembic heads currently exist (f1b78410d568 and b33ef13051bb, the
latter from a merged-in billing branch) — this migration chains on the AU
branch's own head, same as every prior AU migration. Head reconciliation is
a separate, cross-team decision; this file is not applied to any database.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd356014e3357'
down_revision: Union[str, Sequence[str], None] = 'f1b78410d568'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('payroll_employees', sa.Column('au_extra_pay_calendar', sa.String(20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payroll_employees', 'au_extra_pay_calendar')
