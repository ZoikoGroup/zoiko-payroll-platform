"""za_parallel_cycles: G6 parallel-payroll comparison

Revision ID: 67c8d7454716
Revises: 3880223bfaa0
Create Date: 2026-10-28

ZP-ZA-ENG-001 Phase 10 (release gates; G6 needs two parallel cycles against an
incumbent payroll). "ZA" is South Africa ("SA" is Saudi Arabia). Same shape as
Mexico X4 (d3f8b2a6c1e9).

  payroll_za_parallel_imports      one incumbent payroll's results for one
      committed ZA run: the column mapping, the file's SHA-256 and counts (the
      file itself is never kept); ACCEPTED only by a second person.
  payroll_za_parallel_differences  one non-zero per-employee, per-concept delta
      between Zoiko's committed snapshot and the incumbent; UNEXPLAINED until a
      reason is recorded, ACCEPTED only by someone other than the explainer.

Additive only: two new tables; nothing existing is touched and no payslip, run,
ledger or filing is ever changed by these tables.
Row-level security: imports get the TENANT policy (organization_id, no worker
column) and differences the WORKER "org" policy (employee_id) that
d7f9b1c3e5a6's classify() derives - on THESE tables only, PostgreSQL only;
tests/test_south_africa_migrations.py proves classify() agrees. Literal table
and column names so scripts/drift_pending_filter explains every change.
PostgreSQL: lock_timeout fail-fast. Idempotent both ways.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "67c8d7454716"
down_revision: Union[str, Sequence[str], None] = "3880223bfaa0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

IMPORTS = "payroll_za_parallel_imports"
DIFFS = "payroll_za_parallel_differences"
_TABLES = (DIFFS, IMPORTS)


def _json():
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table, name):
    return _has_table(table) and name in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def _index(table, name, cols):
    if not _has_index(table, name):
        op.create_index(name, table, cols)


def _rls_module():
    path = Path(__file__).with_name("d7f9b1c3e5a6_postgres_row_level_security.py")
    spec = importlib.util.spec_from_file_location("zp_rls_d7f9", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rls_for_new_tables(bind) -> None:
    """Row-level security (ZP-PRIV, d7f9b1c3e5a6) covers only tables that existed
    when it ran: give each table this revision creates the policy d7f9b1c3e5a6
    derives for it, on THESE tables only, as 447f57564983 / 3880223bfaa0."""
    rls = _rls_module()
    for table, predicate in ((IMPORTS, rls._TENANT_PREDICATE), (DIFFS, rls._worker_predicate("org"))):
        rls._sql(bind, f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        rls._sql(bind, f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        rls._sql(bind, f'DROP POLICY IF EXISTS {rls.POLICY} ON "{table}"')
        rls._sql(bind, f'CREATE POLICY {rls.POLICY} ON "{table}" USING {predicate} WITH CHECK {predicate}')


def upgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    t = IMPORTS
    if not _has_table(t):
        op.create_table(
            "payroll_za_parallel_imports",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("payroll_run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id", ondelete="RESTRICT"),
                      nullable=False),
            sa.Column("source_label", sa.String(120), nullable=False),
            sa.Column("file_sha256", sa.String(64), nullable=False),
            sa.Column("column_mapping", _json(), nullable=False),
            sa.Column("row_count", sa.Integer(), nullable=False),
            sa.Column("matched_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("unmatched_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(12), nullable=False, server_default="OPEN"),
            sa.Column("accepted_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("status IN ('OPEN', 'ACCEPTED', 'WITHDRAWN')", name="ck_za_parallel_import_status"),
        )
    _index(t, "ix_payroll_za_parallel_imports_id", ["id"])
    _index(t, "ix_payroll_za_parallel_imports_organization_id", ["organization_id"])
    _index(t, "ix_za_parallel_import_org_run", ["organization_id", "payroll_run_id"])

    t = DIFFS
    if not _has_table(t):
        op.create_table(
            "payroll_za_parallel_differences",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("import_id", sa.Integer(), sa.ForeignKey("payroll_za_parallel_imports.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("employee_id", sa.Integer(), sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("concept", sa.String(30), nullable=False),
            sa.Column("zoiko_amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("incumbent_amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("delta", sa.Numeric(14, 2), nullable=False),
            sa.Column("status", sa.String(12), nullable=False, server_default="UNEXPLAINED"),
            sa.Column("reason", sa.String(1000), nullable=True),
            sa.Column("explained_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("explained_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("accepted_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("concept IN ('gross', 'paye', 'uif_employee', 'uif_employer', 'sdl', "
                               "'other_deductions', 'net')", name="ck_za_parallel_diff_concept"),
            sa.CheckConstraint("status IN ('UNEXPLAINED', 'EXPLAINED', 'ACCEPTED')", name="ck_za_parallel_diff_status"),
        )
    _index(t, "ix_payroll_za_parallel_differences_id", ["id"])
    _index(t, "ix_payroll_za_parallel_differences_organization_id", ["organization_id"])
    _index(t, "ix_payroll_za_parallel_differences_import_id", ["import_id"])
    _index(t, "ix_payroll_za_parallel_differences_employee_id", ["employee_id"])

    if _postgres():
        _rls_for_new_tables(op.get_bind())


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for table in _TABLES:
        if _has_table(table):
            op.drop_table(table)
