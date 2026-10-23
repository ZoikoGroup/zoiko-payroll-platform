"""widen payroll_tax_slabs.rate_pct to numeric(7,4) (allow 100% and above)

Revision ID: 135dbbeb9818
Revises: e4ba9fc8c17c
Create Date: 2026-10-22

Brazil's BR_LABOR OVERTIME_100 row (CLT art. 59 §1, Sundays / holidays) is a
100% premium. Numeric(6,4) tops out at 99.9999, so on PostgreSQL the insert
overflows and rolls back the whole BR-PAYROLL-2026 seed (SQLite never enforces
precision, so the tests did not see it). Same widening ContributionRate got in
f4a5b6c7d8e9 for the UK 109% recovery rate.

Increasing the precision of a numeric with the scale unchanged needs no table
rewrite on PostgreSQL; lock_timeout fail-fast so a held lock aborts the deploy
instead of queueing payroll reads. The downgrade fails if a row now holds a
value of 100 or more — that row must be removed first.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "135dbbeb9818"
down_revision: Union[str, Sequence[str], None] = "e4ba9fc8c17c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _lock_timeout() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")


def upgrade() -> None:
    _lock_timeout()
    with op.batch_alter_table("payroll_tax_slabs") as batch:
        batch.alter_column("rate_pct", existing_type=sa.Numeric(6, 4), type_=sa.Numeric(7, 4),
                           existing_nullable=False)


def downgrade() -> None:
    _lock_timeout()
    with op.batch_alter_table("payroll_tax_slabs") as batch:
        batch.alter_column("rate_pct", existing_type=sa.Numeric(7, 4), type_=sa.Numeric(6, 4),
                           existing_nullable=False)
