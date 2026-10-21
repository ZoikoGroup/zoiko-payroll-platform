"""mx_ptu_m10: Mexico PTU cycles and allocations (Phase 9d)

Revision ID: c6e1a9d4f2b7
Revises: b4d8f2c6a9e3
Create Date: 2026-10-21

ZP-MX-ENG-001 Phase 9d (docs/mexico/MEXICO_PHASE_9D_PLAN.md §3): TWO new tables —
payroll_mx_ptu_cycles and payroll_mx_ptu_allocations. No column is added to
any shared table.

Merging to main runs this in production. Creating the FKs to payroll_runs /
payroll_employees / payslip_items / users takes a brief SHARE ROW EXCLUSIVE
lock on each (reads continue; writes wait) that alembic/env.py holds until the
upgrade transaction commits — so the revision runs under SET LOCAL
lock_timeout = '5s'. Measured on PostgreSQL 17 in
tests/test_mexico_ptu_migrations.py.

Row-level security (ZP-PRIV, d7f9b1c3e5a6) is put only on tables that exist
when it runs, so this revision gives the two new tables the policies
d7f9b1c3e5a6 derives for them — on THESE tables only, with the predicate fixed
(the cycles table has organization_id and no worker column: a TENANT table;
the allocations table has employee_id and organization_id: a WORKER table,
strategy "org"). tests/test_mexico_ptu_migrations.py proves classify() agrees.
Guarded and idempotent; downgrade drops only these tables.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c6e1a9d4f2b7"
down_revision: Union[str, Sequence[str], None] = "b4d8f2c6a9e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CYC = "payroll_mx_ptu_cycles"
ALLOC = "payroll_mx_ptu_allocations"
NEW_TABLES = (CYC, ALLOC)


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
    if not _has_table(CYC):
        op.create_table(
            "payroll_mx_ptu_cycles",
            sa.Column("id", i(), primary_key=True),
            sa.Column("organization_id", i(), _fk("organizations", "CASCADE"), nullable=False),
            sa.Column("employer_profile_id", i(), _fk("payroll_mx_employer_profiles", "RESTRICT"), nullable=False),
            sa.Column("fiscal_year", i(), nullable=False),
            sa.Column("distributable_amount", n(16, 2), nullable=False),
            sa.Column("evidence_ref", s(300), nullable=False),
            sa.Column("note", s(300), nullable=True),
            sa.Column("status", s(16), nullable=False),
            sa.Column("recorded_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("approved_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            _ts("amount_approved_at"),
            sa.Column("operator_exclusions", sa.JSON(), nullable=True),
            sa.Column("allocated_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            _ts("allocated_at"),
            sa.Column("allocation_fingerprint", s(64), nullable=True),
            sa.Column("allocation_residue", n(16, 2), nullable=True),
            sa.Column("allocation_approved_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("ptu_run_id", i(), _fk("payroll_runs", "SET NULL"), nullable=True),
            sa.Column("payment_deadline", sa.Date(), nullable=True),
            sa.Column("deadline_rule_ref", s(200), nullable=True),
            sa.Column("rule_source", s(200), nullable=True),
            sa.Column("cancelled_reason", s(300), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            _ts("updated_at"),
            sa.CheckConstraint("status IN ('DRAFT', 'AMOUNT_APPROVED', 'ALLOCATED', 'APPROVED', 'DISTRIBUTED', "
                               "'CANCELLED')", name="ck_mx_ptu_cycle_status"),
            sa.CheckConstraint("distributable_amount > 0", name="ck_mx_ptu_cycle_amount"),
        )
    if not _has_table(ALLOC):
        op.create_table(
            "payroll_mx_ptu_allocations",
            sa.Column("id", i(), primary_key=True),
            sa.Column("organization_id", i(), _fk("organizations", "CASCADE"), nullable=False),
            sa.Column("cycle_id", i(), _fk("payroll_mx_ptu_cycles", "CASCADE"), nullable=False),
            sa.Column("employee_id", i(), _fk("payroll_employees", "RESTRICT"), nullable=False),
            sa.Column("eligible", sa.Boolean(), nullable=False),
            sa.Column("exclusion_reason", s(60), nullable=True),
            sa.Column("exclusion_evidence_ref", s(300), nullable=True),
            sa.Column("exclusion_approved_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("qualifying_days", n(8, 2), nullable=False),
            sa.Column("qualifying_salary", n(16, 2), nullable=False),
            sa.Column("salary_by_kind", sa.JSON(), nullable=True),
            sa.Column("days_share", n(16, 2), nullable=False),
            sa.Column("salary_share", n(16, 2), nullable=False),
            sa.Column("cap_reference", sa.JSON(), nullable=True),
            sa.Column("cap_applied", sa.Boolean(), nullable=False),
            sa.Column("final_amount", n(16, 2), nullable=False),
            sa.Column("payslip_item_id", i(), _fk("payslip_items", "RESTRICT"), nullable=True),
            sa.Column("rule_source", s(200), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("cycle_id", "employee_id", name="uq_mx_ptu_allocation_worker"),
            sa.CheckConstraint("final_amount >= 0", name="ck_mx_ptu_allocation_amount"),
        )
    for col in ("id", "organization_id", "employer_profile_id", "ptu_run_id"):
        _index(f"ix_{CYC}_{col}", CYC, [col])
    for col in ("id", "organization_id", "cycle_id", "employee_id", "payslip_item_id"):
        _index(f"ix_{ALLOC}_{col}", ALLOC, [col])
    _index("uq_mx_ptu_cycle_live", CYC, ["employer_profile_id", "fiscal_year"], unique=True,
           sqlite_where=sa.text("status <> 'CANCELLED'"), postgresql_where=sa.text("status <> 'CANCELLED'"))
    if bind.dialect.name == "postgresql":
        _rls_for_new_tables(bind)


def _rls_for_new_tables(bind) -> None:
    rls = _rls_module()
    for table, predicate in ((CYC, rls._TENANT_PREDICATE), (ALLOC, rls._worker_predicate("org"))):
        rls._sql(bind, f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        rls._sql(bind, f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        rls._sql(bind, f'DROP POLICY IF EXISTS {rls.POLICY} ON "{table}"')
        rls._sql(bind, f'CREATE POLICY {rls.POLICY} ON "{table}" USING {predicate} WITH CHECK {predicate}')


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for table in (ALLOC, CYC):
        if _has_table(table):
            op.drop_table(table)
