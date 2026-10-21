"""br_run_approval_fingerprint: payroll_runs.br_approval_fingerprint

Revision ID: e4ba9fc8c17c
Revises: b9f3a7c2e5d1
Create Date: 2026-10-19

ZP-BR-ENG-001 Phase 6: the run approval binding for Brazil, same shape and
type as nl_approval_fingerprint (972ecd8c1dba). PayrollRun.br_approval_fingerprint
is on the model, and payroll_runs is read by every country, so the column must
exist before that model ships — without it every PayrollRun query fails.

One nullable column, no default (no table rewrite). PostgreSQL: lock_timeout
fail-fast so a held lock aborts the deploy instead of queueing payroll reads.
Idempotent both ways.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e4ba9fc8c17c"
down_revision: Union[str, Sequence[str], None] = "b9f3a7c2e5d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "payroll_runs"
COLUMN = "br_approval_fingerprint"


def _has_column() -> bool:
    return COLUMN in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}


def _lock_timeout() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")


def upgrade() -> None:
    if _has_column():
        return
    _lock_timeout()
    json_type = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")
    op.add_column("payroll_runs", sa.Column("br_approval_fingerprint", json_type, nullable=True))


def downgrade() -> None:
    if not _has_column():
        return
    _lock_timeout()
    op.drop_column(TABLE, COLUMN)
