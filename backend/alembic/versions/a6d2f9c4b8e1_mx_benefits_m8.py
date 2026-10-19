"""mx_benefits_m8: Mexico vacation records (Phase 9b)

Revision ID: a6d2f9c4b8e1
Revises: f5c1a8d3e9b2
Create Date: 2026-10-19

ZP-MX-ENG-001 Phase 9b (docs/mexico/MEXICO_PHASE_9_PLAN.md §3): ONE new table —
payroll_mx_vacation_records. No column is added to any shared table. (The
aguinaldo computation lives in the payslip snapshot like every Mexican line —
no separate table.)

Merging to main runs this in production. Creating the FKs to payroll_runs /
payslip_items / payroll_employees takes a brief SHARE ROW EXCLUSIVE lock on each
(reads continue; writes wait) that alembic/env.py holds until the upgrade
transaction commits — so the revision runs under SET LOCAL lock_timeout = '5s'.
Measured on PostgreSQL 17 in tests/test_mexico_benefits_migrations.py. Guarded and
idempotent; downgrade drops only this table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a6d2f9c4b8e1"
down_revision: Union[str, Sequence[str], None] = "f5c1a8d3e9b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VAC = "payroll_mx_vacation_records"
NEW_TABLES = (VAC,)


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
    if not _has_table(VAC):
        op.create_table(
            "payroll_mx_vacation_records",
            sa.Column("id", i(), primary_key=True),
            sa.Column("organization_id", i(), _fk("organizations", "CASCADE"), nullable=False),
            sa.Column("employee_id", i(), _fk("payroll_employees", "RESTRICT"), nullable=False),
            sa.Column("service_year", i(), nullable=False),
            sa.Column("kind", s(10), nullable=False),
            sa.Column("days", sa.Numeric(6, 2), nullable=False),
            sa.Column("start_date", sa.Date(), nullable=True),
            sa.Column("end_date", sa.Date(), nullable=True),
            sa.Column("status", s(10), nullable=False),
            sa.Column("note", s(300), nullable=True),
            sa.Column("recorded_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("approved_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            _ts("approved_at"),
            sa.Column("premium_run_id", i(), _fk("payroll_runs", "RESTRICT"), nullable=True),
            sa.Column("premium_item_id", i(), _fk("payslip_items", "RESTRICT"), nullable=True),
            sa.Column("withdrawn_reason", s(300), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            _ts("updated_at"),
            sa.CheckConstraint("kind IN ('TAKEN', 'OPENING', 'PAID_OUT')", name="ck_mx_vacation_record_kind"),
            sa.CheckConstraint("status IN ('DRAFT', 'APPROVED', 'PAID', 'WITHDRAWN')",
                               name="ck_mx_vacation_record_status"),
            sa.CheckConstraint("days > 0", name="ck_mx_vacation_record_days"),
        )
    for col in ("id", "organization_id", "employee_id", "premium_run_id", "premium_item_id"):
        _index(f"ix_{VAC}_{col}", VAC, [col])


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    if _has_table(VAC):
        op.drop_table(VAC)
