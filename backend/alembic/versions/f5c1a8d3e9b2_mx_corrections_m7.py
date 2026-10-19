"""mx_corrections_m7: Mexico correction runs (Phase 9a)

Revision ID: f5c1a8d3e9b2
Revises: e3b9c2d7f4a1
Create Date: 2026-10-19

ZP-MX-ENG-001 Phase 9a (docs/mexico/MEXICO_PHASE_9_PLAN.md §3): ONE new table —
payroll_mx_run_corrections. No column is added to any shared table
(payroll_runs.mx_run_type already exists, Phase 6).

Merging to main runs this in production. Creating the FKs to payroll_runs /
payslip_items / payroll_employees takes a brief SHARE ROW EXCLUSIVE lock on each
(reads continue; writes wait) that alembic/env.py holds until the upgrade
transaction commits — so the revision runs under SET LOCAL lock_timeout = '5s'
(fail fast instead of queueing payroll writes). Measured on PostgreSQL 17 in
tests/test_mexico_corrections_migrations.py. Guarded and idempotent; downgrade
drops only this table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f5c1a8d3e9b2"
down_revision: Union[str, Sequence[str], None] = "e3b9c2d7f4a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CORR = "payroll_mx_run_corrections"
NEW_TABLES = (CORR,)
_LIVE = "status <> 'VOIDED'"


def _insp():
    return sa.inspect(op.get_bind())


def _has_table(name):
    return name in _insp().get_table_names()


def _has_index(table, name):
    return _has_table(table) and name in {i["name"] for i in _insp().get_indexes(table)}


def _fk(target, ondelete):
    return sa.ForeignKey(f"{target}.id", ondelete=ondelete)


def _ts(name, nullable=True):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _index(name, table, cols, **kw):
    if not _has_index(table, name):
        op.create_index(name, table, cols, **kw)


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    i, s = sa.Integer, sa.String
    if not _has_table(CORR):
        op.create_table(
            "payroll_mx_run_corrections",
            sa.Column("id", i(), primary_key=True),
            sa.Column("organization_id", i(), _fk("organizations", "CASCADE"), nullable=False),
            sa.Column("correction_run_id", i(), _fk("payroll_runs", "SET NULL"), nullable=True),
            sa.Column("original_run_id", i(), _fk("payroll_runs", "RESTRICT"), nullable=False),
            sa.Column("original_item_id", i(), _fk("payslip_items", "RESTRICT"), nullable=False),
            sa.Column("corrected_item_id", i(), _fk("payslip_items", "SET NULL"), nullable=True),
            sa.Column("employee_id", i(), _fk("payroll_employees", "RESTRICT"), nullable=False),
            sa.Column("reason", s(500), nullable=False),
            sa.Column("status", s(10), nullable=False),
            sa.Column("deltas", sa.JSON(), nullable=True),
            sa.Column("requested_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("voided_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("void_reason", s(300), nullable=True),
            _ts("committed_at"),
            _ts("voided_at"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            _ts("updated_at"),
            sa.CheckConstraint("status IN ('DRAFT', 'COMMITTED', 'VOIDED')", name="ck_mx_run_correction_status"),
        )
    for col in ("id", "organization_id", "correction_run_id", "original_run_id", "original_item_id",
                "corrected_item_id", "employee_id"):
        _index(f"ix_{CORR}_{col}", CORR, [col])
    _index("uq_mx_run_correction_live_original", CORR, ["original_item_id"], unique=True,
           postgresql_where=sa.text(_LIVE), sqlite_where=sa.text(_LIVE))


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    if _has_table(CORR):
        op.drop_table(CORR)
