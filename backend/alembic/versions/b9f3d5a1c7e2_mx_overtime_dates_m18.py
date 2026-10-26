"""mx_overtime_dates_m18: the dates on which approved overtime was worked (Phase 11c)

Revision ID: b9f3d5a1c7e2
Revises: a8e4c1f7d3b5
Create Date: 2026-10-23

ZP-MX-ENG-001 Phase 11c (MEXICO_PHASE_11C_IMPLEMENTATION_REPORT.md): ONE new nullable
JSON column, payroll_mx_approved_hours.overtime_dates — the ISO dates inside the week
on which the overtime was worked, which the CFDI HorasExtra node needs (S4 p. 51).
No table is created; no RLS policy changes (the table's policy does not name columns).

Merging to main runs this in production. ADD COLUMN takes a brief ACCESS EXCLUSIVE
lock on payroll_mx_approved_hours only (a Mexico table, empty in production), held
until the upgrade transaction commits — so the revision runs under SET LOCAL
lock_timeout = '5s'. Measured on PostgreSQL 17 in tests/test_mexico_overtime_dates_migrations.py.
Guarded and idempotent; downgrade drops only this column.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b9f3d5a1c7e2"
down_revision: Union[str, Sequence[str], None] = "a8e4c1f7d3b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

HOURS = "payroll_mx_approved_hours"
NEW_COLUMNS = ((HOURS, "overtime_dates"),)


def _has_column(table, column):
    insp = sa.inspect(op.get_bind())
    return table in insp.get_table_names() and column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    if not _has_column(HOURS, "overtime_dates"):
        op.add_column("payroll_mx_approved_hours", sa.Column("overtime_dates", sa.JSON(), nullable=True))


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    if _has_column(HOURS, "overtime_dates"):
        with op.batch_alter_table(HOURS) as batch:
            batch.drop_column("overtime_dates")
