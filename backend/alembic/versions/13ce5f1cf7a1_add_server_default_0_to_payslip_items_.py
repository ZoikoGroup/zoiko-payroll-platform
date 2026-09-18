"""add server default 0 to payslip_items soli

Revision ID: 13ce5f1cf7a1
Revises: 2b3c4d5e6f70
Create Date: 2026-09-17 11:44:30.380335

Phase 8DQ correction — this migration's down_revision originally pointed to
`fbfe6d7eeb2e`, a no-op Alembic-bookkeeping merge migration that exists only
on a separate, unrelated `main`-lineage worktree (its own parents,
`b33ef13051bb`/`f1b78410d568`, are Australia-statutory revisions that were
never part of nikhil's history at all). That reference was never valid on
this branch, leaving this migration — and everything chained after it —
disconnected from nikhil's real Alembic graph. Corrected to point at
`2b3c4d5e6f70` (`add_overtime_premium_wage_tax_soli_church_tax_deltas`,
Phase 8BW), nikhil's actual prior head at the time this migration was
authored. No schema change from this correction — `upgrade()`/`downgrade()`
are unchanged.

Phase 8DD — closes the P2 schema drift Phase 8DB's read-only production
audit confirmed: `payslip_items.soli` has no DB-level server default,
even though the ORM model
(app/modules/payroll/models.py: `soli = Column(Numeric(12, 2), default=0,
server_default="0")`) has already declared `server_default="0"` for some
time. Every current write path goes through the ORM, which already
applies SQLAlchemy's client-side `default=0` regardless of the DB's own
default (confirmed by inspecting every `PayslipItem(` construction site
in service.py — none omit `soli` in a way the ORM wouldn't backfill), so
this migration does not change any existing application behavior. It
exists purely so the live schema matches what the model already claims,
and so that a hypothetical future raw-SQL/bulk-import path that bypasses
the ORM cannot silently insert a NULL.

Confirmed via read-only production audit before writing this migration:
`payslip_items` currently has 0 rows in production, so there is no
existing NULL-value data to reconcile — this is a pure additive/schema-
only change.

Additive, minimal, single-purpose: only sets a server-side default on one
existing column. Does not change the column's data type, nullability, or
any other column, table, or existing value.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '13ce5f1cf7a1'
down_revision: Union[str, Sequence[str], None] = '2b3c4d5e6f70'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "payslip_items",
        "soli",
        server_default="0",
        existing_type=sa.Numeric(12, 2),
        existing_nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "payslip_items",
        "soli",
        server_default=None,
        existing_type=sa.Numeric(12, 2),
        existing_nullable=True,
    )
