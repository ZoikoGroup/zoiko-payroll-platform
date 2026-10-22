"""mx_payments_m12: Mexico salary payment batches and items (Phase 10a)

Revision ID: a1d5e8c2f7b4
Revises: e7a2c4f9b1d6
Create Date: 2026-10-21

ZP-MX-ENG-001 Phase 10a (docs/mexico/MEXICO_PHASE_10_PLAN.md §3): TWO new tables —
payroll_mx_payment_batches and payroll_mx_payment_items. No column is added to
any shared table.

Merging to main runs this in production. Creating the FKs to payroll_runs /
payroll_employees / payslip_items / users takes a brief SHARE ROW EXCLUSIVE
lock on each (reads continue; writes wait) that alembic/env.py holds until the
upgrade transaction commits — so the revision runs under SET LOCAL
lock_timeout = '5s'. Measured on PostgreSQL 17 in
tests/test_mexico_payments_migrations.py.

Row-level security (ZP-PRIV, d7f9b1c3e5a6) is put only on tables that exist
when it runs, so this revision gives the two new tables the policies
d7f9b1c3e5a6 derives for them — on THESE tables only, with the predicate fixed
(the batches table has organization_id and no worker column: a TENANT table;
the items table has employee_id and organization_id: a WORKER table,
strategy "org"). tests/test_mexico_payments_migrations.py proves classify() agrees.
Guarded and idempotent; downgrade drops only these tables.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1d5e8c2f7b4"
down_revision: Union[str, Sequence[str], None] = "e7a2c4f9b1d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BAT = "payroll_mx_payment_batches"
ITEM = "payroll_mx_payment_items"
NEW_TABLES = (BAT, ITEM)


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


def _rls_module():
    path = Path(__file__).with_name("d7f9b1c3e5a6_postgres_row_level_security.py")
    spec = importlib.util.spec_from_file_location("zp_rls_d7f9", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    i, s, n = sa.Integer, sa.String, sa.Numeric
    if not _has_table(BAT):
        op.create_table(
            "payroll_mx_payment_batches",
            sa.Column("id", i(), primary_key=True),
            sa.Column("organization_id", i(), _fk("organizations", "CASCADE"), nullable=False),
            sa.Column("payroll_run_id", i(), _fk("payroll_runs", "RESTRICT"), nullable=False),
            sa.Column("reissue_of_batch_id", i(), _fk("payroll_mx_payment_batches", "RESTRICT"), nullable=True),
            sa.Column("file_mode", s(12), nullable=False),
            sa.Column("status", s(10), nullable=False),
            sa.Column("item_count", i(), nullable=False),
            sa.Column("total_amount", n(16, 2), nullable=False),
            sa.Column("maker_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("checker_id", i(), sa.ForeignKey("users.id"), nullable=True),
            _ts("released_at"),
            sa.Column("last_export_sha256", s(64), nullable=True),
            sa.Column("exports", i(), nullable=False),
            sa.Column("idempotency_key", s(80), nullable=False, unique=True),
            sa.Column("cancelled_reason", s(300), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            _ts("updated_at"),
            sa.CheckConstraint("status IN ('DRAFT', 'RELEASED', 'CLOSED', 'CANCELLED')", name="ck_mx_payment_batch_status"),
            sa.CheckConstraint("file_mode IN ('WORKLIST')", name="ck_mx_payment_batch_mode"),
        )
    if not _has_table(ITEM):
        op.create_table(
            "payroll_mx_payment_items",
            sa.Column("id", i(), primary_key=True),
            sa.Column("organization_id", i(), _fk("organizations", "CASCADE"), nullable=False),
            sa.Column("batch_id", i(), _fk("payroll_mx_payment_batches", "CASCADE"), nullable=False),
            sa.Column("employee_id", i(), _fk("payroll_employees", "RESTRICT"), nullable=False),
            sa.Column("payslip_item_id", i(), _fk("payslip_items", "RESTRICT"), nullable=False),
            sa.Column("clabe_last4", s(4), nullable=False),
            sa.Column("amount", n(16, 2), nullable=False),
            sa.Column("status", s(10), nullable=False),
            sa.Column("outcome_reference", s(120), nullable=True),
            sa.Column("return_reason", s(300), nullable=True),
            sa.Column("reissue_of_item_id", i(), _fk("payroll_mx_payment_items", "RESTRICT"), nullable=True),
            sa.Column("reissued_by_item_id", i(), _fk("payroll_mx_payment_items", "SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            _ts("updated_at"),
            sa.CheckConstraint("status IN ('PENDING', 'SETTLED', 'FAILED', 'RETURNED', 'UNKNOWN')",
                               name="ck_mx_payment_item_status"),
            sa.CheckConstraint("amount > 0", name="ck_mx_payment_item_amount"),
        )
    for col in ("id", "organization_id", "payroll_run_id"):
        _index(f"ix_{BAT}_{col}", BAT, [col])
    for col in ("id", "organization_id", "batch_id", "employee_id", "payslip_item_id"):
        _index(f"ix_{ITEM}_{col}", ITEM, [col])
    if bind.dialect.name == "postgresql":
        _rls_for_new_tables(bind)


def _rls_for_new_tables(bind) -> None:
    rls = _rls_module()
    for table, predicate in ((BAT, rls._TENANT_PREDICATE), (ITEM, rls._worker_predicate("org"))):
        rls._sql(bind, f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        rls._sql(bind, f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        rls._sql(bind, f'DROP POLICY IF EXISTS {rls.POLICY} ON "{table}"')
        rls._sql(bind, f'CREATE POLICY {rls.POLICY} ON "{table}" USING {predicate} WITH CHECK {predicate}')


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for table in (ITEM, BAT):
        if _has_table(table):
            op.drop_table(table)
