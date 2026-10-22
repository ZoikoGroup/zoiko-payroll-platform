"""mx_transfer_m15: Mexico master-data releases (Phase 10f, option B)

Revision ID: e5b1d8f3a7c2
Revises: d2a7c9e4f1b8
Create Date: 2026-10-22

ZP-MX-ENG-001 Phase 10f (MEXICO_PHASE_10F_IMPLEMENTATION_REPORT.md): ONE new
table — payroll_mx_master_releases — and ONE nullable column on the Mexico-only,
empty payroll_mx_master_copies (release_id). No shared table is touched.

Merging to main runs this in production. Creating the FKs to organizations /
users takes a brief SHARE ROW EXCLUSIVE lock on each (reads
continue; writes wait) that alembic/env.py holds until the upgrade transaction
commits — so the revision runs under SET LOCAL lock_timeout = '5s'. Measured on
PostgreSQL 17 in tests/test_mexico_transfer_migrations.py.

Row-level security (ZP-PRIV, d7f9b1c3e5a6) is put only on tables that exist
when it runs, so this revision gives the new table its policy — on THIS table
only. It is a TENANT table (organization_id, no worker column), but its
predicate also admits the NAMED TARGET organisation (target_organization_id),
so both parties to a release can read it. This differs from the generic tenant
predicate on purpose and is for the ZP-PRIV owner's sign-off; a future re-run of
apply_rls() would narrow it back to the owner only (fails closed: the target
then sees nothing). tests/test_mexico_transfer_migrations.py proves it.
Guarded and idempotent; downgrade drops only these tables.
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5b1d8f3a7c2"
down_revision: Union[str, Sequence[str], None] = "d2a7c9e4f1b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

REL = "payroll_mx_master_releases"
COPY = "payroll_mx_master_copies"
NEW_TABLES = (REL,)


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


def _has_column(table, column):
    return _has_table(table) and column in {c["name"] for c in _insp().get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    i, s = sa.Integer, sa.String
    if not _has_table(REL):
        op.create_table(
            "payroll_mx_master_releases",
            sa.Column("id", i(), primary_key=True),
            sa.Column("organization_id", i(), _fk("organizations", "CASCADE"), nullable=False),
            sa.Column("target_organization_id", i(), _fk("organizations", "RESTRICT"), nullable=False),
            sa.Column("status", s(10), nullable=False),
            sa.Column("reason", s(300), nullable=False),
            sa.Column("plan", sa.JSON(), nullable=False),
            sa.Column("plan_sha256", s(64), nullable=False),
            sa.Column("proposed_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("released_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            _ts("released_at"),
            _ts("expires_at"),
            _ts("used_at"),
            sa.Column("revoked_by_id", i(), sa.ForeignKey("users.id"), nullable=True),
            _ts("revoked_at"),
            sa.Column("revoke_reason", s(300), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            _ts("updated_at"),
            sa.CheckConstraint("status IN ('PROPOSED', 'RELEASED', 'USED', 'REVOKED')", name="ck_mx_master_release_status"),
            sa.CheckConstraint("organization_id <> target_organization_id", name="ck_mx_master_release_distinct"),
        )
    for col in ("id", "organization_id", "target_organization_id"):
        _index(f"ix_{REL}_{col}", REL, [col])
    if _has_table(COPY) and not _has_column(COPY, "release_id"):
        # the Mexico-only, empty copy table (Phase 10e): ACCESS EXCLUSIVE on it alone, briefly
        with op.batch_alter_table(COPY) as batch:
            batch.add_column(sa.Column("release_id", i(), nullable=True))
            batch.create_foreign_key("fk_mx_master_copy_release", REL, ["release_id"], ["id"], ondelete="RESTRICT")
        _index(f"ix_{COPY}_release_id", COPY, ["release_id"])
    if bind.dialect.name == "postgresql":
        _rls_for_release_table(bind)


def _rls_for_release_table(bind) -> None:
    rls = _rls_module()
    own = rls._TENANT_PREDICATE
    # the owner (organization_id) OR the named target (target_organization_id)
    predicate = own[:-1] + f" OR ({rls._TENANT_MODE} AND target_organization_id = zoiko_rls_tenant()))"
    rls._sql(bind, f'ALTER TABLE "{REL}" ENABLE ROW LEVEL SECURITY')
    rls._sql(bind, f'ALTER TABLE "{REL}" FORCE ROW LEVEL SECURITY')
    rls._sql(bind, f'DROP POLICY IF EXISTS {rls.POLICY} ON "{REL}"')
    rls._sql(bind, f'CREATE POLICY {rls.POLICY} ON "{REL}" USING {predicate} WITH CHECK {own}')


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    if _has_column(COPY, "release_id"):
        if _has_index(COPY, f"ix_{COPY}_release_id"):
            op.drop_index(f"ix_{COPY}_release_id", table_name=COPY)
        with op.batch_alter_table(COPY) as batch:
            batch.drop_constraint("fk_mx_master_copy_release", type_="foreignkey")
            batch.drop_column("release_id")
    if _has_table(REL):
        op.drop_table(REL)
