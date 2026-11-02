"""jp_run_payment_kind: make Japan SALARY/BONUS a run-level choice

Revision ID: 9c1d7e4a2b6f
Revises: 668472e4eb72
Create Date: 2026-11-02

ZP-JP-ENG-001 Phase 5 correction. Japan payment kind was read from employee
settings, so once an employee was marked BONUS every later run stayed BONUS
and monthly social insurance was never charged again. This adds one nullable
run column; NULL means SALARY. Additive only, idempotent both ways,
lock_timeout fail-fast on PostgreSQL.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "9c1d7e4a2b6f"
down_revision: Union[str, Sequence[str], None] = "668472e4eb72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RUNS = "payroll_runs"


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _columns(table: str) -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    if "jp_payment_kind" not in _columns(RUNS):
        op.add_column(RUNS, sa.Column("jp_payment_kind", sa.String(length=10), nullable=True))


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    if "jp_payment_kind" in _columns(RUNS):
        op.drop_column(RUNS, "jp_payment_kind")
