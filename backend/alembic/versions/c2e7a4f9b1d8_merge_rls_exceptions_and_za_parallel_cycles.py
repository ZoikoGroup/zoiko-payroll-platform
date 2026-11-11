"""merge the reapplied RLS exceptions head with South Africa parallel cycles

Revision ID: c2e7a4f9b1d8
Revises: f8d2c6a0b4e1, 67c8d7454716
Create Date: 2026-10-30

Both heads descend from 3880223bfaa0: rugvedh's country-entitlement chain
(d4c8f1a7b2e9 -> f8d2c6a0b4e1) and main's South Africa Phase 10 parallel
payroll cycles (67c8d7454716). Neither changes the other's tables, and
67c8d7454716 only adds RLS policies to its own new tables (it never reruns
the generic installer), so the named exceptions f8d2c6a0b4e1 reinstalled
stay intact — a plain merge, no schema change.
"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "c2e7a4f9b1d8"
down_revision: Union[str, Sequence[str], None] = ("f8d2c6a0b4e1", "67c8d7454716")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
