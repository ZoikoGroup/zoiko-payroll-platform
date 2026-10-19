"""mx_run_m4: Mexico payroll run integration (snapshot, approval, ledgers, approved hours)

Revision ID: c4f7a2d9e6b1
Revises: b7a1c9e3d5f2
Create Date: 2026-10-17

ZP-MX-ENG-001 Phase 6 (docs/mexico/MEXICO_PHASE_6_PLAN.md §4–§5):
  new tables   payroll_mx_preflight_exceptions, payroll_mx_imss_branch_lines,
               payroll_mx_isn_liabilities, payroll_mx_sbc_history,
               payroll_mx_variable_accumulators, payroll_mx_benefit_accruals,
               payroll_mx_approved_hours
  Mexico-only  payroll_mx_labor_policies.salary_days_convention (D13)
  SHARED LIVE  payslip_items.mx_calculation_snapshot
               payroll_runs.mx_approval_fingerprint, payroll_runs.mx_run_type

Merging to main runs this in production. Lock ordering (plan §5, approved 2026-10-17):
alembic/env.py runs the whole upgrade in ONE transaction (no
transaction_per_migration), so locks are held until it commits. Therefore:
  1. New tables (+ their FKs, created with the table) and the Mexico-only column first,
     in the migration transaction under SET LOCAL lock_timeout = '5s'.
  2. autocommit_block(): commits step 1 (releasing its brief SHARE ROW EXCLUSIVE locks
     on the FK targets), then each ALTER on a shared table is its OWN transaction under a
     session lock_timeout of 5 s — the ACCESS EXCLUSIVE lock on payslip_items is held only
     for its own metadata-only statement, never while payroll_runs is waited for.
     Nullable, no DEFAULT, no CHECK: no rewrite, no validation scan.
Guarded and idempotent: every step checks the catalog first, so a deploy that failed in
step 2 (step 1 already committed) simply re-runs. SQLite (dev/test): plain DDL.
Downgrade removes only what this revision added, each shared ALTER in its own transaction.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4f7a2d9e6b1"
down_revision: Union[str, Sequence[str], None] = "b7a1c9e3d5f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ITEMS, RUNS, POLICIES = "payslip_items", "payroll_runs", "payroll_mx_labor_policies"
NEW_TABLES = ("payroll_mx_preflight_exceptions", "payroll_mx_imss_branch_lines", "payroll_mx_isn_liabilities",
              "payroll_mx_sbc_history", "payroll_mx_variable_accumulators", "payroll_mx_benefit_accruals",
              "payroll_mx_approved_hours")


def _insp():
    return sa.inspect(op.get_bind())


def _has_table(name):
    return name in _insp().get_table_names()


def _columns(table):
    return {c["name"] for c in _insp().get_columns(table)} if _has_table(table) else set()


def _has_index(table, name):
    return _has_table(table) and name in {i["name"] for i in _insp().get_indexes(table)}


def _fk(target, ondelete):
    return sa.ForeignKey(f"{target}.id", ondelete=ondelete)


def _created_at():
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _tables():
    """(name, columns + constraints, indexes) — mirrors models.py."""
    i, n, d, s = sa.Integer, sa.Numeric, sa.Date, sa.String
    return (
        ("payroll_mx_preflight_exceptions", [
            sa.Column("id", i(), primary_key=True),
            sa.Column("payroll_run_id", i(), _fk("payroll_runs", "CASCADE"), nullable=False),
            sa.Column("payslip_item_id", i(), _fk("payslip_items", "CASCADE"), nullable=True),
            sa.Column("employee_id", i(), _fk("payroll_employees", "CASCADE"), nullable=False),
            sa.Column("code", s(60), nullable=False),
            sa.Column("severity", s(8), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("acknowledged_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("acknowledgement_note", s(500), nullable=True),
            sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
            _created_at(),
            sa.CheckConstraint("severity IN ('BLOCK', 'WARN')", name="ck_mx_preflight_severity"),
        ], ("id", "payroll_run_id", "payslip_item_id", "employee_id")),
        ("payroll_mx_imss_branch_lines", [
            sa.Column("id", i(), primary_key=True),
            sa.Column("payslip_item_id", i(), _fk("payslip_items", "RESTRICT"), nullable=False),
            sa.Column("organization_id", i(), _fk("organizations", "CASCADE"), nullable=False),
            sa.Column("branch_code", s(30), nullable=False),
            sa.Column("side", s(10), nullable=False),
            sa.Column("segment_start", d(), nullable=False),
            sa.Column("base_amount", n(14, 4), nullable=False),
            sa.Column("contribution_days", n(6, 2), nullable=False),
            sa.Column("rate_pct", n(9, 5), nullable=False),
            sa.Column("amount", n(14, 4), nullable=False),
            sa.Column("band", s(20), nullable=True),
            _created_at(),
            sa.UniqueConstraint("payslip_item_id", "branch_code", "side", "segment_start", name="uq_mx_imss_line"),
        ], ("id", "payslip_item_id", "organization_id")),
        ("payroll_mx_isn_liabilities", [
            sa.Column("id", i(), primary_key=True),
            sa.Column("payslip_item_id", i(), _fk("payslip_items", "RESTRICT"), nullable=False),
            sa.Column("organization_id", i(), _fk("organizations", "CASCADE"), nullable=False),
            sa.Column("state_code", s(5), nullable=False),
            sa.Column("base_amount", n(14, 4), nullable=False),
            sa.Column("rate_pct", n(9, 5), nullable=False),
            sa.Column("amount", n(14, 4), nullable=False),
            sa.Column("jurisdiction_pack_id", s(60), nullable=True),
            sa.Column("period_key", s(10), nullable=False),
            _created_at(),
            sa.UniqueConstraint("payslip_item_id", "state_code", name="uq_mx_isn_liability"),
        ], ("id", "payslip_item_id", "organization_id")),
        ("payroll_mx_sbc_history", [
            sa.Column("id", i(), primary_key=True),
            sa.Column("organization_id", i(), _fk("organizations", "CASCADE"), nullable=False),
            sa.Column("employee_id", i(), _fk("payroll_employees", "RESTRICT"), nullable=False),
            sa.Column("payroll_run_id", i(), _fk("payroll_runs", "RESTRICT"), nullable=False),
            sa.Column("effective_from", d(), nullable=False),
            sa.Column("sbc_fixed", n(14, 4), nullable=False),
            sa.Column("sbc_variable", n(14, 4), nullable=False),
            sa.Column("sbc_total", n(14, 4), nullable=False),
            sa.Column("factor", n(14, 10), nullable=False),
            sa.Column("components", sa.JSON(), nullable=False),
            sa.Column("source", s(10), nullable=False),
            _created_at(),
            sa.UniqueConstraint("employee_id", "effective_from", "payroll_run_id", name="uq_mx_sbc_history"),
        ], ("id", "organization_id", "employee_id", "payroll_run_id")),
        ("payroll_mx_variable_accumulators", [
            sa.Column("id", i(), primary_key=True),
            sa.Column("organization_id", i(), _fk("organizations", "CASCADE"), nullable=False),
            sa.Column("employee_id", i(), _fk("payroll_employees", "RESTRICT"), nullable=False),
            sa.Column("payroll_run_id", i(), _fk("payroll_runs", "RESTRICT"), nullable=True),
            sa.Column("bimester_key", s(8), nullable=False),
            sa.Column("variable_total", n(14, 4), nullable=False),
            sa.Column("days", n(6, 2), nullable=False),
            sa.Column("kind", s(8), nullable=False),
            sa.Column("evidence_document_id", i(), _fk("payroll_compliance_documents", "SET NULL"), nullable=True),
            sa.Column("recorded_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("approved_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            _created_at(),
            sa.CheckConstraint("kind IN ('RUN', 'OPENING')", name="ck_mx_varacc_kind"),
            sa.UniqueConstraint("employee_id", "bimester_key", "payroll_run_id", name="uq_mx_varacc"),
        ], ("id", "organization_id", "employee_id", "payroll_run_id")),
        ("payroll_mx_benefit_accruals", [
            sa.Column("id", i(), primary_key=True),
            sa.Column("organization_id", i(), _fk("organizations", "CASCADE"), nullable=False),
            sa.Column("employee_id", i(), _fk("payroll_employees", "RESTRICT"), nullable=False),
            sa.Column("payroll_run_id", i(), _fk("payroll_runs", "RESTRICT"), nullable=False),
            sa.Column("concept", s(20), nullable=False),
            sa.Column("period_key", s(10), nullable=False),
            sa.Column("statutory_amount", n(14, 4), nullable=False),
            sa.Column("employer_amount", n(14, 4), nullable=False),
            _created_at(),
            sa.UniqueConstraint("employee_id", "concept", "period_key", "payroll_run_id", name="uq_mx_benefit_accrual"),
        ], ("id", "organization_id", "employee_id", "payroll_run_id")),
        ("payroll_mx_approved_hours", [
            sa.Column("id", i(), primary_key=True),
            sa.Column("organization_id", i(), _fk("organizations", "CASCADE"), nullable=False),
            sa.Column("employee_id", i(), _fk("payroll_employees", "CASCADE"), nullable=False),
            sa.Column("week_start", d(), nullable=False),
            sa.Column("ordinary_hours", n(6, 2), nullable=False),
            sa.Column("overtime_hours", n(6, 2), nullable=False),
            sa.Column("sundays_worked", i(), nullable=False),
            sa.Column("rest_days_worked", i(), nullable=False),
            sa.Column("evidence_document_id", i(), _fk("payroll_compliance_documents", "SET NULL"), nullable=True),
            sa.Column("status", s(12), nullable=False),
            sa.Column("recorded_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("approved_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            _created_at(),
            sa.CheckConstraint("status IN ('DRAFT', 'APPROVED', 'SUPERSEDED')", name="ck_mx_hours_status"),
            sa.CheckConstraint("ordinary_hours >= 0 AND overtime_hours >= 0 AND sundays_worked >= 0 "
                               "AND rest_days_worked >= 0", name="ck_mx_hours_nonneg"),
        ], ("id", "organization_id", "employee_id")),
    )


# One literal op.create_table per table (tests/test_model_tables_have_migrations.py).
_CREATE = {
    "payroll_mx_preflight_exceptions": lambda cols: op.create_table("payroll_mx_preflight_exceptions", *cols),
    "payroll_mx_imss_branch_lines": lambda cols: op.create_table("payroll_mx_imss_branch_lines", *cols),
    "payroll_mx_isn_liabilities": lambda cols: op.create_table("payroll_mx_isn_liabilities", *cols),
    "payroll_mx_sbc_history": lambda cols: op.create_table("payroll_mx_sbc_history", *cols),
    "payroll_mx_variable_accumulators": lambda cols: op.create_table("payroll_mx_variable_accumulators", *cols),
    "payroll_mx_benefit_accruals": lambda cols: op.create_table("payroll_mx_benefit_accruals", *cols),
    "payroll_mx_approved_hours": lambda cols: op.create_table("payroll_mx_approved_hours", *cols),
}


def _create_tables():
    for name, cols, indexed in _tables():
        if not _has_table(name):
            _CREATE[name](cols)
        for col in indexed:
            ix = f"ix_{name}_{col}"
            if not _has_index(name, ix):
                op.create_index(ix, name, [col])
    if not _has_index("payroll_mx_approved_hours", "uq_mx_hours_employee_week_approved"):
        where = "status = 'APPROVED'"
        op.create_index("uq_mx_hours_employee_week_approved", "payroll_mx_approved_hours", ["employee_id", "week_start"],
                        unique=True, postgresql_where=sa.text(where), sqlite_where=sa.text(where))


def upgrade() -> None:
    postgres = op.get_bind().dialect.name == "postgresql"
    if postgres:
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    # Step 1 — new tables and the Mexico-only column.
    _create_tables()
    if "salary_days_convention" not in _columns(POLICIES):
        if postgres:
            op.execute(sa.text(f"ALTER TABLE {POLICIES} ADD COLUMN salary_days_convention VARCHAR(10)"))
        else:
            with op.batch_alter_table(POLICIES) as batch:
                batch.add_column(sa.Column("salary_days_convention", sa.String(10), nullable=True))
    # Step 2 — the two shared live tables, LAST, each ALTER its own transaction.
    item_missing = "mx_calculation_snapshot" not in _columns(ITEMS)
    run_cols = _columns(RUNS)
    run_clauses = [c for name, c in (("mx_approval_fingerprint", "ADD COLUMN mx_approval_fingerprint JSON"),
                                     ("mx_run_type", "ADD COLUMN mx_run_type VARCHAR(16)")) if name not in run_cols]
    if not postgres:
        if item_missing:
            op.add_column(ITEMS, sa.Column("mx_calculation_snapshot", sa.JSON(), nullable=True))
        if "mx_approval_fingerprint" not in run_cols:
            op.add_column(RUNS, sa.Column("mx_approval_fingerprint", sa.JSON(), nullable=True))
        if "mx_run_type" not in run_cols:
            op.add_column(RUNS, sa.Column("mx_run_type", sa.String(16), nullable=True))
        return
    with op.get_context().autocommit_block():
        op.execute(sa.text("SET lock_timeout = '5s'"))
        try:
            if item_missing:
                op.execute(sa.text(f"ALTER TABLE {ITEMS} ADD COLUMN mx_calculation_snapshot JSON"))
            if run_clauses:
                op.execute(sa.text(f"ALTER TABLE {RUNS} " + ", ".join(run_clauses)))
        finally:
            op.execute(sa.text("RESET lock_timeout"))


def downgrade() -> None:
    postgres = op.get_bind().dialect.name == "postgresql"
    item_has = "mx_calculation_snapshot" in _columns(ITEMS)
    run_cols = _columns(RUNS)
    run_drops = [f"DROP COLUMN {c}" for c in ("mx_approval_fingerprint", "mx_run_type") if c in run_cols]
    if postgres:
        with op.get_context().autocommit_block():
            op.execute(sa.text("SET lock_timeout = '5s'"))
            try:
                if run_drops:
                    op.execute(sa.text(f"ALTER TABLE {RUNS} " + ", ".join(run_drops)))
                if item_has:
                    op.execute(sa.text(f"ALTER TABLE {ITEMS} DROP COLUMN mx_calculation_snapshot"))
            finally:
                op.execute(sa.text("RESET lock_timeout"))
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    else:
        if item_has:
            with op.batch_alter_table(ITEMS) as batch:
                batch.drop_column("mx_calculation_snapshot")
        if run_drops:
            with op.batch_alter_table(RUNS) as batch:
                for c in ("mx_approval_fingerprint", "mx_run_type"):
                    if c in run_cols:
                        batch.drop_column(c)
    if "salary_days_convention" in _columns(POLICIES):
        if postgres:
            op.execute(sa.text(f"ALTER TABLE {POLICIES} DROP COLUMN salary_days_convention"))
        else:
            with op.batch_alter_table(POLICIES) as batch:
                batch.drop_column("salary_days_convention")
    for name in reversed(NEW_TABLES):
        if _has_table(name):
            op.drop_table(name)
