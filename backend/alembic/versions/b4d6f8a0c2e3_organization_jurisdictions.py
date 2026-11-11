"""organization_jurisdictions: country entitlement ledger

Revision ID: b4d6f8a0c2e3
Revises: c3e5a7b9d1f4
Create Date: 2026-10-27

Additive: ONE new table (billing.models.OrganizationJurisdiction) — which
countries an organization may add employees in and run payroll for, capped
by the plan's max_jurisdictions. No existing row is read or rewritten here.

Backfill is NOT done in this revision: it needs the plan-limit resolution
(plan version flags, live overrides, Enterprise order forms) that lives in
app code, which a migration must not import. Run it right after upgrading:

    python -m scripts.backfill_organization_jurisdictions

It is idempotent and prints a summary. Until it runs, any org without
ledger rows is seeded lazily (same per-org logic) the first time the
entitlement check touches it, so nothing breaks in the meantime.

Guarded and idempotent for databases where Base.metadata.create_all already
created the table. Row-level security is re-applied on PostgreSQL (the
policy set is derived from the live schema, so the new tenant table gets
the standard tenant policy).
"""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "b4d6f8a0c2e3"
down_revision = "c3e5a7b9d1f4"
branch_labels = None
depends_on = None

TABLE = "organization_jurisdictions"


def _insp():
    return sa.inspect(op.get_bind())


def _has_table(name):
    return name in _insp().get_table_names()


def _has_index(table, name):
    return _has_table(table) and name in {i["name"] for i in _insp().get_indexes(table)}


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
    if not _has_table(TABLE):
        op.create_table(
            "organization_jurisdictions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(),
                      sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("country_code", sa.String(2), nullable=False),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
            sa.Column("activated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("activated_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.UniqueConstraint("organization_id", "country_code", name="uq_org_jurisdiction"),
        )
    if not _has_index(TABLE, f"ix_{TABLE}_id"):
        op.create_index(f"ix_{TABLE}_id", TABLE, ["id"])
    if not _has_index(TABLE, f"ix_{TABLE}_organization_id"):
        op.create_index(f"ix_{TABLE}_organization_id", TABLE, ["organization_id"])
    if not _has_index(TABLE, "uq_org_jurisdiction_primary"):
        op.create_index(
            "uq_org_jurisdiction_primary", TABLE, ["organization_id"], unique=True,
            postgresql_where=sa.text("is_primary"), sqlite_where=sa.text("is_primary"),
        )

    if bind.dialect.name == "postgresql":
        _rls_module().apply_rls(bind)


def downgrade() -> None:
    if _has_table(TABLE):
        op.drop_table(TABLE)
