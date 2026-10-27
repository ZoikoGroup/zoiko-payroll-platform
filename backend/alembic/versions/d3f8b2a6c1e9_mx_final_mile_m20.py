"""mx_final_mile_m20: the Mexico decision register (final mile X1)

Revision ID: d3f8b2a6c1e9
Revises: c7d2e9a4f1b6
Create Date: 2026-10-27

Mexico final mile (MEXICO_FINAL_MILE_MASTER_PROMPT.md), one revision for the programme:
  * X1 — payroll_mx_decisions: the recorded answer to each open decision (four-eyes,
    versioned). Platform configuration (no organisation_id, no worker column): no
    row-level-security policy, like every other platform table.
  * X4 — payroll_mx_parallel_imports (TENANT) and payroll_mx_parallel_differences
    (WORKER: employee_id): the G8 parallel-payroll comparison. Row-level security
    (ZP-PRIV, d7f9b1c3e5a6) is put only on tables that exist when it runs, so this
    revision gives these two tables the policy d7f9b1c3e5a6's classify() derives for
    them — on THESE tables only, never a sweep over every table (PR #115).
User ids are plain integers (no foreign key to users). The X4 foreign keys to
organizations / payroll_runs / payroll_employees take a brief SHARE ROW EXCLUSIVE lock
on each (reads continue; writes wait) until the upgrade transaction commits.

Merging to main runs this in production, under SET LOCAL lock_timeout = '5s'.
Measured on PostgreSQL 17 in tests/test_mexico_final_mile_migrations.py. Guarded and
idempotent; downgrade drops only this table.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3f8b2a6c1e9"
down_revision: Union[str, Sequence[str], None] = "c7d2e9a4f1b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DECISIONS = "payroll_mx_decisions"
IMPORTS = "payroll_mx_parallel_imports"                  # X4 (TENANT)
DIFFS = "payroll_mx_parallel_differences"                # X4 (WORKER: employee_id)
NEW_TABLES = (DECISIONS, IMPORTS, DIFFS)


def _insp():
    return sa.inspect(op.get_bind())


def _has_table(name):
    return name in _insp().get_table_names()


def _has_index(table, name):
    return _has_table(table) and name in {i["name"] for i in _insp().get_indexes(table)}


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    i, s, t, j, dt = sa.Integer, sa.String, sa.Text, sa.JSON, sa.DateTime
    if not _has_table(DECISIONS):
        op.create_table(
            "payroll_mx_decisions",                 # literal: scripts/drift_pending_filter reads it
            sa.Column("id", i(), primary_key=True),
            sa.Column("code", s(10), nullable=False),
            sa.Column("version", i(), nullable=False),
            sa.Column("title", s(200), nullable=False),
            sa.Column("gates", j(), nullable=False),
            sa.Column("owner_role", s(60), nullable=True),
            sa.Column("question", t(), nullable=False),
            sa.Column("options", j(), nullable=False),
            sa.Column("question_sources", j(), nullable=False),
            sa.Column("block_codes", j(), nullable=False),
            sa.Column("content_keys", j(), nullable=False),
            sa.Column("answer_kind", s(20), nullable=False),
            sa.Column("allowed_values", j(), nullable=True),
            sa.Column("status", s(12), nullable=False),
            sa.Column("chosen_option", t(), nullable=True),
            sa.Column("rationale", t(), nullable=True),
            sa.Column("cited_sources", j(), nullable=True),
            sa.Column("content_hash", s(64), nullable=True),
            sa.Column("supersedes_id", i(), sa.ForeignKey(f"{DECISIONS}.id", ondelete="RESTRICT"), nullable=True),
            sa.Column("proposed_by_id", i(), nullable=True),
            sa.Column("proposed_at", dt(timezone=True), nullable=True),
            sa.Column("approved_by_id", i(), nullable=True),
            sa.Column("approved_at", dt(timezone=True), nullable=True),
            sa.Column("transcribed_by_id", i(), nullable=True),
            sa.Column("transcribed_at", dt(timezone=True), nullable=True),
            sa.Column("transcription_ref", s(200), nullable=True),
            sa.Column("created_at", dt(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", dt(timezone=True), nullable=True),
            sa.CheckConstraint("status IN ('OPEN', 'PROPOSED', 'APPROVED', 'TRANSCRIBED', 'WITHDRAWN', 'SUPERSEDED')",
                               name="ck_mx_decision_status"),
            sa.CheckConstraint("answer_kind IN ('FREE_TEXT', 'ENUM', 'ROUNDING_RULE', 'PAY_PERIOD', 'AMOUNT')",
                               name="ck_mx_decision_answer_kind"),
            sa.UniqueConstraint("code", "version", name="uq_mx_decision_code_version"),
        )
    for column in ("id", "code"):
        if not _has_index(DECISIONS, f"ix_{DECISIONS}_{column}"):
            op.create_index(f"ix_{DECISIONS}_{column}", DECISIONS, [column])
    n = sa.Numeric
    if not _has_table(IMPORTS):
        op.create_table(
            "payroll_mx_parallel_imports",
            sa.Column("id", i(), primary_key=True),
            sa.Column("organization_id", i(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("payroll_run_id", i(), sa.ForeignKey("payroll_runs.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("source_label", s(120), nullable=False),
            sa.Column("column_mapping", j(), nullable=False),
            sa.Column("file_sha256", s(64), nullable=False),
            sa.Column("row_count", i(), nullable=False),
            sa.Column("unmatched", j(), nullable=False),
            sa.Column("status", s(12), nullable=False),
            sa.Column("created_by_id", i(), nullable=True),
            sa.Column("created_at", dt(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", dt(timezone=True), nullable=True),
            sa.CheckConstraint("status IN ('CURRENT', 'SUPERSEDED', 'WITHDRAWN')", name="ck_mx_parallel_import_status"),
        )
    if not _has_table(DIFFS):
        op.create_table(
            "payroll_mx_parallel_differences",
            sa.Column("id", i(), primary_key=True),
            sa.Column("organization_id", i(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("import_id", i(), sa.ForeignKey(f"{IMPORTS}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("employee_id", i(), sa.ForeignKey("payroll_employees.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("concept", s(30), nullable=False),
            sa.Column("legacy_amount", n(16, 2), nullable=False),
            sa.Column("zoiko_amount", n(16, 2), nullable=False),
            sa.Column("delta", n(16, 2), nullable=False),
            sa.Column("state", s(12), nullable=False),
            sa.Column("reason", s(500), nullable=True),
            sa.Column("explained_by_id", i(), nullable=True),
            sa.Column("explained_at", dt(timezone=True), nullable=True),
            sa.Column("accepted_by_id", i(), nullable=True),
            sa.Column("accepted_at", dt(timezone=True), nullable=True),
            sa.Column("created_at", dt(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.CheckConstraint("state IN ('MATCH', 'UNEXPLAINED', 'EXPLAINED', 'ACCEPTED')",
                               name="ck_mx_parallel_difference_state"),
            sa.UniqueConstraint("import_id", "employee_id", "concept", name="uq_mx_parallel_difference"),
        )
    for table, cols in ((IMPORTS, ("id", "organization_id", "payroll_run_id")),
                        (DIFFS, ("id", "organization_id", "import_id", "employee_id"))):
        for column in cols:
            if not _has_index(table, f"ix_{table}_{column}"):
                op.create_index(f"ix_{table}_{column}", table, [column])
    if op.get_bind().dialect.name == "postgresql":
        _rls_for_new_tables(op.get_bind())


def _rls_module():
    path = Path(__file__).with_name("d7f9b1c3e5a6_postgres_row_level_security.py")
    spec = importlib.util.spec_from_file_location("zp_rls_d7f9", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rls_for_new_tables(bind) -> None:
    """The policy classify() derives, on the two X4 tables only."""
    rls = _rls_module()
    for table, predicate in ((IMPORTS, rls._TENANT_PREDICATE), (DIFFS, rls._worker_predicate("org"))):
        rls._sql(bind, f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        rls._sql(bind, f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        rls._sql(bind, f'DROP POLICY IF EXISTS {rls.POLICY} ON "{table}"')
        rls._sql(bind, f'CREATE POLICY {rls.POLICY} ON "{table}" USING {predicate} WITH CHECK {predicate}')


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for table in (DIFFS, IMPORTS, DECISIONS):
        if _has_table(table):
            op.drop_table(table)
