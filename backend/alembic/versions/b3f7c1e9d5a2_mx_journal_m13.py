"""mx_journal_m13: Mexico payroll journal mappings and exports (Phase 10b)

Revision ID: b3f7c1e9d5a2
Revises: a1d5e8c2f7b4
Create Date: 2026-10-22

ZP-MX-ENG-001 Phase 10b (docs/mexico/MEXICO_PHASE_10_PLAN.md §3, D6): TWO new
tables — payroll_mx_journal_mappings and payroll_mx_journal_exports. No column
is added to any shared table.

Merging to main runs this in production. Creating the FKs to organizations /
payroll_runs / users takes a brief SHARE ROW EXCLUSIVE lock on each (reads
continue; writes wait) that alembic/env.py holds until the upgrade transaction
commits — so the revision runs under SET LOCAL lock_timeout = '5s'. Measured on
PostgreSQL 17 in tests/test_mexico_journal_migrations.py.

Row-level security (ZP-PRIV, d7f9b1c3e5a6) is put only on tables that exist
when it runs, so this revision gives the two new tables the policy
d7f9b1c3e5a6 derives for them — on THESE tables only, with the predicate fixed
(both have organization_id and no worker column: TENANT tables).
tests/test_mexico_journal_migrations.py proves classify() agrees.
Guarded and idempotent; downgrade drops only these tables.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3f7c1e9d5a2"
down_revision: Union[str, Sequence[str], None] = "a1d5e8c2f7b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MAP = "payroll_mx_journal_mappings"
EXP = "payroll_mx_journal_exports"
NEW_TABLES = (MAP, EXP)


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
    if not _has_table(MAP):
        op.create_table(
            "payroll_mx_journal_mappings",
            sa.Column("id", i(), primary_key=True),
            sa.Column("organization_id", i(), _fk("organizations", "CASCADE"), nullable=False),
            sa.Column("version", i(), nullable=False),
            sa.Column("status", s(10), nullable=False),
            sa.Column("accounts", sa.JSON(), nullable=False),
            sa.Column("note", s(300), nullable=True),
            sa.Column("maker_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("approved_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            _ts("approved_at"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            _ts("updated_at"),
            sa.UniqueConstraint("organization_id", "version", name="uq_mx_journal_mapping_version"),
            sa.CheckConstraint("status IN ('DRAFT', 'APPROVED', 'SUPERSEDED', 'WITHDRAWN')",
                               name="ck_mx_journal_mapping_status"),
        )
    if not _has_table(EXP):
        op.create_table(
            "payroll_mx_journal_exports",
            sa.Column("id", i(), primary_key=True),
            sa.Column("organization_id", i(), _fk("organizations", "CASCADE"), nullable=False),
            sa.Column("payroll_run_id", i(), _fk("payroll_runs", "RESTRICT"), nullable=False),
            sa.Column("mapping_id", i(), _fk("payroll_mx_journal_mappings", "RESTRICT"), nullable=False),
            sa.Column("status", s(10), nullable=False),
            sa.Column("line_count", i(), nullable=False),
            sa.Column("debit_total", n(16, 2), nullable=False),
            sa.Column("credit_total", n(16, 2), nullable=False),
            sa.Column("file_sha256", s(64), nullable=False),
            sa.Column("created_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("voided_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("voided_reason", s(300), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            _ts("updated_at"),
            sa.CheckConstraint("status IN ('CURRENT', 'VOIDED')", name="ck_mx_journal_export_status"),
            sa.CheckConstraint("debit_total = credit_total", name="ck_mx_journal_export_balanced"),
        )
    for col in ("id", "organization_id"):
        _index(f"ix_{MAP}_{col}", MAP, [col])
    for col in ("id", "organization_id", "payroll_run_id"):
        _index(f"ix_{EXP}_{col}", EXP, [col])
    if bind.dialect.name == "postgresql":
        _rls_for_new_tables(bind)


def _rls_for_new_tables(bind) -> None:
    rls = _rls_module()
    for table in NEW_TABLES:
        predicate = rls._TENANT_PREDICATE
        rls._sql(bind, f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        rls._sql(bind, f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        rls._sql(bind, f'DROP POLICY IF EXISTS {rls.POLICY} ON "{table}"')
        rls._sql(bind, f'CREATE POLICY {rls.POLICY} ON "{table}" USING {predicate} WITH CHECK {predicate}')


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for table in (EXP, MAP):
        if _has_table(table):
            op.drop_table(table)
