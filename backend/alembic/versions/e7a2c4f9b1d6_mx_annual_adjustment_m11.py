"""mx_annual_adjustment_m11: Mexico annual ISR adjustments (Phase 9e)

Revision ID: e7a2c4f9b1d6
Revises: c6e1a9d4f2b7
Create Date: 2026-10-21

ZP-MX-ENG-001 Phase 9e (docs/mexico/MEXICO_PHASE_9E_PLAN.md §3): ONE new table —
payroll_mx_annual_isr_adjustments. No column is added to any shared table.

Merging to main runs this in production. Creating the FKs to payroll_runs /
payroll_employees / payslip_items / users takes a brief SHARE ROW EXCLUSIVE
lock on each (reads continue; writes wait) that alembic/env.py holds until the
upgrade transaction commits — so the revision runs under SET LOCAL
lock_timeout = '5s'. Measured on PostgreSQL 17 in
tests/test_mexico_annual_adjustment_migrations.py.

Row-level security (ZP-PRIV): the new table gets the policy d7f9b1c3e5a6
derives for it (employee_id + organization_id: a WORKER table, strategy
"org") on THIS table only — never re-running apply_rls() over existing tables
(deploy 39561229230). The test proves classify() agrees. Guarded and
idempotent; downgrade drops only this table.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7a2c4f9b1d6"
down_revision: Union[str, Sequence[str], None] = "c6e1a9d4f2b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ADJ = "payroll_mx_annual_isr_adjustments"
NEW_TABLES = (ADJ,)


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
    if not _has_table(ADJ):
        op.create_table(
            "payroll_mx_annual_isr_adjustments",
            sa.Column("id", i(), primary_key=True),
            sa.Column("organization_id", i(), _fk("organizations", "CASCADE"), nullable=False),
            sa.Column("employer_profile_id", i(), _fk("payroll_mx_employer_profiles", "RESTRICT"), nullable=False),
            sa.Column("fiscal_year", i(), nullable=False),
            sa.Column("employee_id", i(), _fk("payroll_employees", "RESTRICT"), nullable=False),
            sa.Column("status", s(10), nullable=False),
            sa.Column("eligible", sa.Boolean(), nullable=False),
            sa.Column("exclusion_reason", s(60), nullable=True),
            sa.Column("exclusion_evidence_ref", s(300), nullable=True),
            sa.Column("exclusion_recorded_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("exclusion_approved_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("income_by_run_type", sa.JSON(), nullable=True),
            sa.Column("annual_taxable", n(16, 2), nullable=False),
            sa.Column("withheld_total", n(16, 2), nullable=False),
            sa.Column("subsidy_applied_total", n(16, 2), nullable=False),
            sa.Column("annual_isr", n(16, 2), nullable=True),
            sa.Column("difference", n(16, 2), nullable=True),
            sa.Column("inputs_fingerprint", s(64), nullable=True),
            sa.Column("rule_source", s(200), nullable=True),
            sa.Column("computed_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("approved_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("applied_run_id", i(), _fk("payroll_runs", "SET NULL"), nullable=True),
            sa.Column("applied_item_id", i(), _fk("payslip_items", "RESTRICT"), nullable=True),
            sa.Column("applied_withheld_change", n(16, 2), nullable=True),
            sa.Column("carry_forward", n(16, 2), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            _ts("updated_at"),
            sa.UniqueConstraint("employer_profile_id", "fiscal_year", "employee_id",
                                name="uq_mx_annual_adjustment_worker"),
            sa.CheckConstraint("status IN ('COMPUTED', 'APPROVED', 'APPLIED', 'WAIVED')",
                               name="ck_mx_annual_adjustment_status"),
        )
    for col in ("id", "organization_id", "employer_profile_id", "employee_id", "applied_run_id", "applied_item_id"):
        _index(f"ix_{ADJ}_{col}", ADJ, [col])
    if bind.dialect.name == "postgresql":
        rls = _rls_module()
        predicate = rls._worker_predicate("org")
        rls._sql(bind, f'ALTER TABLE "{ADJ}" ENABLE ROW LEVEL SECURITY')
        rls._sql(bind, f'ALTER TABLE "{ADJ}" FORCE ROW LEVEL SECURITY')
        rls._sql(bind, f'DROP POLICY IF EXISTS {rls.POLICY} ON "{ADJ}"')
        rls._sql(bind, f'CREATE POLICY {rls.POLICY} ON "{ADJ}" USING {predicate} WITH CHECK {predicate}')


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    if _has_table(ADJ):
        op.drop_table(ADJ)
