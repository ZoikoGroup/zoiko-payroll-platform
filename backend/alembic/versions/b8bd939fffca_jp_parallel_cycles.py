"""jp_parallel_cycles: Japan parallel payroll cycles against the incumbent payroll

Revision ID: b8bd939fffca
Revises: 41a1fafbbfdc
Create Date: 2026-11-02

ZP-JP-ENG-001 Phase 9 (release gate G7).

  payroll_jp_parallel_imports      one incumbent payroll file compared with a
      committed Japan run: source, SHA-256, column mapping, match counts and
      status OPEN -> ACCEPTED (a second person) or WITHDRAWN;
  payroll_jp_parallel_differences  one per employee and concept whose amounts
      differ (tolerance zero): UNEXPLAINED -> EXPLAINED (reason) -> ACCEPTED
      by a different person.

No identifier is stored: an incumbent file with an identifier-like column or
a 12-digit value is refused before any row is written.

Additive only, literal table names, idempotent both ways, lock_timeout
fail-fast and tenant row-level security on PostgreSQL.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b8bd939fffca"
down_revision: Union[str, Sequence[str], None] = "41a1fafbbfdc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

IMPORTS = "payroll_jp_parallel_imports"
DIFFERENCES = "payroll_jp_parallel_differences"


def _json():
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _user(name):
    return sa.Column(name, sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


def _rls_module():
    path = Path(__file__).with_name("d7f9b1c3e5a6_postgres_row_level_security.py")
    spec = importlib.util.spec_from_file_location("zp_rls_d7f9", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rls_for_new_tables(bind) -> None:
    rls = _rls_module()
    predicate = rls._TENANT_PREDICATE
    for table in (IMPORTS, DIFFERENCES):
        rls._sql(bind, f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        rls._sql(bind, f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        rls._sql(bind, f'DROP POLICY IF EXISTS {rls.POLICY} ON "{table}"')
        rls._sql(bind, f'CREATE POLICY {rls.POLICY} ON "{table}" USING {predicate} WITH CHECK {predicate}')


def upgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    if not _has_table(IMPORTS):
        op.create_table(
            "payroll_jp_parallel_imports",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(),
                      sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("payroll_run_id", sa.Integer(),
                      sa.ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("period", sa.String(7), nullable=False),
            sa.Column("source_label", sa.String(120), nullable=False),
            sa.Column("file_sha256", sa.String(64), nullable=False),
            sa.Column("column_mapping", _json(), nullable=False),
            sa.Column("row_count", sa.Integer(), nullable=False),
            sa.Column("matched_count", sa.Integer(), nullable=False),
            sa.Column("unmatched_count", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(12), nullable=False, server_default="OPEN"),
            _user("created_by_id"),
            _user("accepted_by_id"),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.CheckConstraint("status IN ('OPEN', 'ACCEPTED', 'WITHDRAWN')", name="ck_jp_parallel_import_status"),
        )
        op.create_index("ix_jp_parallel_import_org_period", IMPORTS, ["organization_id", "period"])
        op.create_index("uq_jp_parallel_import_run_file", IMPORTS, ["payroll_run_id", "file_sha256"], unique=True)

    if not _has_table(DIFFERENCES):
        op.create_table(
            "payroll_jp_parallel_differences",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(),
                      sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("import_id", sa.Integer(),
                      sa.ForeignKey("payroll_jp_parallel_imports.id", ondelete="CASCADE"), nullable=False),
            sa.Column("employee_id", sa.Integer(),
                      sa.ForeignKey("payroll_employees.id", ondelete="SET NULL"), nullable=True),
            sa.Column("concept", sa.String(40), nullable=False),
            sa.Column("zoiko_amount", sa.Numeric(14, 0), nullable=False),
            sa.Column("incumbent_amount", sa.Numeric(14, 0), nullable=False),
            sa.Column("delta", sa.Numeric(14, 0), nullable=False),
            sa.Column("status", sa.String(12), nullable=False, server_default="UNEXPLAINED"),
            sa.Column("reason", sa.String(1000), nullable=True),
            _user("explained_by_id"),
            sa.Column("explained_at", sa.DateTime(timezone=True), nullable=True),
            _user("accepted_by_id"),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.CheckConstraint("status IN ('UNEXPLAINED', 'EXPLAINED', 'ACCEPTED')",
                               name="ck_jp_parallel_difference_status"),
        )
        op.create_index("ix_jp_parallel_difference_import", DIFFERENCES, ["import_id"])

    if _postgres():
        _rls_for_new_tables(op.get_bind())


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for table in (DIFFERENCES, IMPORTS):
        if _has_table(table):
            op.drop_table(table)
