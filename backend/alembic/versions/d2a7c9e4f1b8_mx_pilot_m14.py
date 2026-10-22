"""mx_pilot_m14: Mexico pilot grants and master-data copies (Phase 10e)

Revision ID: d2a7c9e4f1b8
Revises: b3f7c1e9d5a2
Create Date: 2026-10-22

ZP-MX-ENG-001 Phase 10e (docs/mexico/MEXICO_PHASE_10E_PLAN.md §5): TWO new
tables — payroll_mx_pilot_grants and payroll_mx_master_copies. No column
is added to any shared table.

Merging to main runs this in production. Creating the FKs to organizations /
users takes a brief SHARE ROW EXCLUSIVE lock on each (reads
continue; writes wait) that alembic/env.py holds until the upgrade transaction
commits — so the revision runs under SET LOCAL lock_timeout = '5s'. Measured on
PostgreSQL 17 in tests/test_mexico_pilot_migrations.py.

Row-level security (ZP-PRIV, d7f9b1c3e5a6) is put only on tables that exist
when it runs, so this revision gives the two new tables the policy
d7f9b1c3e5a6 derives for them — on THESE tables only, with the predicate fixed
(both have organization_id and no worker column: TENANT tables).
tests/test_mexico_pilot_migrations.py proves classify() agrees.
Guarded and idempotent; downgrade drops only these tables.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d2a7c9e4f1b8"
down_revision: Union[str, Sequence[str], None] = "b3f7c1e9d5a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

GRANT = "payroll_mx_pilot_grants"
COPY = "payroll_mx_master_copies"
NEW_TABLES = (GRANT, COPY)


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
    i, s = sa.Integer, sa.String
    if not _has_table(GRANT):
        op.create_table(
            "payroll_mx_pilot_grants",
            sa.Column("id", i(), primary_key=True),
            sa.Column("organization_id", i(), _fk("organizations", "CASCADE"), nullable=False),
            sa.Column("status", s(10), nullable=False),
            sa.Column("reason", s(300), nullable=False),
            sa.Column("scope_note", s(300), nullable=True),
            _ts("expires_at", nullable=False),
            sa.Column("proposed_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("approved_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            _ts("approved_at"),
            sa.Column("revoked_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            _ts("revoked_at"),
            sa.Column("revoke_reason", s(300), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            _ts("updated_at"),
            sa.CheckConstraint("status IN ('PROPOSED', 'APPROVED', 'REVOKED', 'WITHDRAWN')", name="ck_mx_pilot_grant_status"),
        )
    if not _has_table(COPY):
        op.create_table(
            "payroll_mx_master_copies",
            sa.Column("id", i(), primary_key=True),
            sa.Column("source_organization_id", i(), _fk("organizations", "RESTRICT"), nullable=False),
            sa.Column("organization_id", i(), _fk("organizations", "CASCADE"), nullable=False),
            sa.Column("status", s(10), nullable=False),
            sa.Column("reason", s(300), nullable=False),
            sa.Column("plan", sa.JSON(), nullable=False),
            sa.Column("plan_sha256", s(64), nullable=False),
            sa.Column("report", sa.JSON(), nullable=True),
            sa.Column("proposed_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("approved_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            _ts("executed_at"),
            sa.Column("cancelled_reason", s(300), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            _ts("updated_at"),
            sa.CheckConstraint("status IN ('PROPOSED', 'EXECUTED', 'CANCELLED')", name="ck_mx_master_copy_status"),
            sa.CheckConstraint("source_organization_id <> organization_id", name="ck_mx_master_copy_distinct"),
        )
    for col in ("id", "organization_id"):
        _index(f"ix_{GRANT}_{col}", GRANT, [col])
    for col in ("id", "organization_id", "source_organization_id"):
        _index(f"ix_{COPY}_{col}", COPY, [col])
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
    for table in (COPY, GRANT):
        if _has_table(table):
            op.drop_table(table)
