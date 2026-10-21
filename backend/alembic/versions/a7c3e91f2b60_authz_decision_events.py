"""authz decision events: append-only PDP denial audit (ZP-PRIV A04)

Revision ID: a7c3e91f2b60
Revises: f5c1a8d3e9b2
Create Date: 2026-10-15

Additive: one new table plus one append-only trigger (Postgres). No existing
row is read or rewritten. The trigger reuses zoiko_reject_audit_mutation()
installed by d1e5a7c3b9f2 (created defensively here too, so this migration is
self-contained if applied on a database that predates that revision).
"""

import sqlalchemy as sa
from alembic import op

revision = "a7c3e91f2b60"
down_revision = "f5c1a8d3e9b2"
branch_labels = None
depends_on = None

_TABLE = "authz_decision_events"


def upgrade() -> None:
    op.create_table(
        "authz_decision_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("principal_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("principal_role", sa.String(40), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("route_template", sa.String(300), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("resource", sa.String(80), nullable=False),
        sa.Column("data_class", sa.String(40), nullable=False),
        sa.Column("reason_code", sa.String(60), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("client_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(300), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("path_params", sa.Text(), nullable=True),
    )
    op.create_index(f"ix_{_TABLE}_decision_id", _TABLE, ["decision_id"], unique=True)
    for col in ("created_at", "principal_user_id", "organization_id",
                "reason_code", "correlation_id"):
        op.create_index(f"ix_{_TABLE}_{col}", _TABLE, [col])

    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("""
        CREATE OR REPLACE FUNCTION zoiko_reject_audit_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND current_setting('zoiko.audit_purge', true) = 'on' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'audit rows are append-only (%: % refused)', TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$;
    """)
    op.execute(f"CREATE TRIGGER {_TABLE}_append_only BEFORE UPDATE OR DELETE ON {_TABLE} "
               f"FOR EACH ROW EXECUTE FUNCTION zoiko_reject_audit_mutation()")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"DROP TRIGGER IF EXISTS {_TABLE}_append_only ON {_TABLE}")
    for col in ("correlation_id", "reason_code", "organization_id", "principal_user_id",
                "created_at", "decision_id"):
        op.drop_index(f"ix_{_TABLE}_{col}", table_name=_TABLE)
    op.drop_table(_TABLE)
