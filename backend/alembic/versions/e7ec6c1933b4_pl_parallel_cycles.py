"""pl_parallel_cycles: Poland parallel payroll cycles (release gate G6)

Revision ID: e7ec6c1933b4
Revises: e75b9219e1f8
Create Date: 2026-11-06

ZP-PL-ENG-001 Phase 9 (AC-PL-03, gate G6). Additive only; mirrors the New
Zealand parallel-cycle tables (a8cde2482ef0).

  payroll_pl_parallel_imports      one incumbent-payroll file compared with a
      committed (Paid / Closed) Poland run at zero tolerance; accepted by a
      person other than its importer.
  payroll_pl_parallel_differences  one employee and concept that differs;
      explained, then accepted by a person other than the explainer.

RLS (d7f9b1c3e5a6 classify): imports TENANT; differences (employee_id) WORKER
"org". PostgreSQL only; literal names; lock_timeout; idempotent both ways.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7ec6c1933b4"
down_revision: Union[str, Sequence[str], None] = "e75b9219e1f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

IMPORTS = "payroll_pl_parallel_imports"
DIFFERENCES = "payroll_pl_parallel_differences"

TENANT_TABLES = (IMPORTS,)
WORKER_TABLES = (DIFFERENCES,)
_TABLES = (DIFFERENCES, IMPORTS)
CONCEPTS = ("('gross', 'pit_advance', 'zus_employee', 'health', 'ppk_employee', 'zus_employer', "
            "'employer_funds', 'ppk_employer', 'net_pay')")


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _json():
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table, name):
    return _has_table(table) and name in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def _index(table, name, cols, unique=False, where=None):
    if _has_index(table, name):
        return
    kw = {}
    if where is not None:
        kw = {"postgresql_where": sa.text(where), "sqlite_where": sa.text(where)}
    op.create_index(name, table, cols, unique=unique, **kw)


def _common(table: str, with_updated: bool = True):
    columns = [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("legal_entity_id", sa.Integer(),
                  sa.ForeignKey("legal_entities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("evidence_ref", sa.String(300), nullable=True),
        sa.Column("previous_version_id", sa.Integer(),
                  sa.ForeignKey(f"{table}.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]
    if with_updated:
        columns.append(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    return columns


def _base_indexes(table, employee=False):
    _index(table, f"ix_{table}_id", ["id"])
    _index(table, f"ix_{table}_organization_id", ["organization_id"])
    _index(table, f"ix_{table}_legal_entity_id", ["legal_entity_id"])
    if employee:
        _index(table, f"ix_{table}_employee_id", ["employee_id"])


def _rls_module():
    path = Path(__file__).with_name("d7f9b1c3e5a6_postgres_row_level_security.py")
    spec = importlib.util.spec_from_file_location("zp_rls_d7f9", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rls_for_new_tables(bind) -> None:
    """Give each table this revision creates the policy d7f9b1c3e5a6 derives."""
    rls = _rls_module()
    policies = [(table, rls._TENANT_PREDICATE) for table in TENANT_TABLES]
    policies += [(table, rls._worker_predicate("org")) for table in WORKER_TABLES]
    for table, predicate in policies:
        rls._sql(bind, f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        rls._sql(bind, f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        rls._sql(bind, f'DROP POLICY IF EXISTS {rls.POLICY} ON "{table}"')
        rls._sql(bind, f'CREATE POLICY {rls.POLICY} ON "{table}" USING {predicate} WITH CHECK {predicate}')


def upgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    # 1) payroll_pl_parallel_imports (TENANT)
    t = IMPORTS
    if not _has_table(t):
        op.create_table(
            "payroll_pl_parallel_imports",
            *_common(t),
            sa.Column("run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("pay_date", sa.Date(), nullable=False),
            sa.Column("cycle_month", sa.Date(), nullable=False),
            sa.Column("source_name", sa.String(100), nullable=False),
            sa.Column("file_hash", sa.String(64), nullable=False),
            sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("matched_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("unmatched_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("column_map", _json(), nullable=False),
            sa.Column("status", sa.String(10), nullable=False, server_default="OPEN"),
            sa.Column("withdrawn_reason", sa.String(300), nullable=True),
            sa.CheckConstraint("row_count >= 0 AND matched_count >= 0 AND unmatched_count >= 0",
                               name="ck_pl_parallel_import_counts"),
            sa.CheckConstraint("status IN ('OPEN', 'ACCEPTED', 'WITHDRAWN')", name="ck_pl_parallel_import_status"),
            sa.CheckConstraint("status <> 'ACCEPTED' OR (approved_by_id IS NOT NULL AND approved_by_id <> created_by_id)",
                               name="ck_pl_parallel_import_four_eyes"),
        )
    _base_indexes(t)
    _index(t, "ix_pl_parallel_import_cycle", ["status", "cycle_month"])
    _index(t, "uq_pl_parallel_import_file", ["organization_id", "run_id", "file_hash"], unique=True,
           where="status <> 'WITHDRAWN'")

    # 2) payroll_pl_parallel_differences (WORKER)
    t = DIFFERENCES
    if not _has_table(t):
        op.create_table(
            "payroll_pl_parallel_differences",
            *_common(t),
            sa.Column("import_id", sa.Integer(), sa.ForeignKey(f"{IMPORTS}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("employee_id", sa.Integer(), sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("payslip_item_id", sa.Integer(), sa.ForeignKey("payslip_items.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("concept", sa.String(24), nullable=False),
            sa.Column("incumbent_amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("zoiko_amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("difference", sa.Numeric(14, 2), nullable=False),
            sa.Column("explanation", sa.String(300), nullable=True),
            sa.Column("explained_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status", sa.String(10), nullable=False, server_default="OPEN"),
            sa.CheckConstraint(f"concept IN {CONCEPTS}", name="ck_pl_parallel_difference_concept"),
            sa.CheckConstraint("status IN ('OPEN', 'EXPLAINED', 'ACCEPTED')", name="ck_pl_parallel_difference_status"),
            sa.CheckConstraint("status = 'OPEN' OR explanation IS NOT NULL", name="ck_pl_parallel_difference_explained"),
            sa.CheckConstraint("status <> 'ACCEPTED' OR (approved_by_id IS NOT NULL AND approved_by_id <> explained_by_id)",
                               name="ck_pl_parallel_difference_four_eyes"),
        )
    _base_indexes(t, employee=True)
    _index(t, "ix_pl_parallel_difference_import", ["import_id"])
    _index(t, "uq_pl_parallel_difference", ["import_id", "employee_id", "concept"], unique=True)

    if _postgres():
        _rls_for_new_tables(op.get_bind())


def downgrade() -> None:
    if _postgres():
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for table in _TABLES:
        if _has_table(table):
            op.drop_table(table)
