"""add payroll_employees.sgp_work_pass_issue_date / sgp_work_pass_end_date

Revision ID: e5f9a3b7c2d4
Revises: d4e8f2a6b9c1
Create Date: 2026-09-24

Singapore S Pass partial-month levy (approved Phase 2) — MOM: the levy
liability starts the day the S Pass is issued and ends when it is
cancelled or expires, so the pass validity dates are captured. Two
nullable Date columns; every existing row keeps NULL (a full month is
still levied as before; a partial month without dates stays BLOCKED).
Idempotent (inspector-guarded), same shape as c3d9e1f4a7b2.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f9a3b7c2d4'
down_revision: Union[str, Sequence[str], None] = 'd4e8f2a6b9c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = ("sgp_work_pass_issue_date", "sgp_work_pass_end_date")


def _existing_columns() -> set:
    return {col["name"] for col in sa.inspect(op.get_bind()).get_columns("payroll_employees")}


def upgrade() -> None:
    """Upgrade schema."""
    existing = _existing_columns()
    for name in _COLUMNS:
        if name not in existing:
            op.add_column('payroll_employees', sa.Column(name, sa.Date(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    existing = _existing_columns()
    for name in reversed(_COLUMNS):
        if name in existing:
            op.drop_column('payroll_employees', name)
