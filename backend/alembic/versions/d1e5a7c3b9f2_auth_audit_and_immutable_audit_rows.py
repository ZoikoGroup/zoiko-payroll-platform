"""auth audit events (G5 F-5) and append-only audit tables (G5 F-6)

Revision ID: d1e5a7c3b9f2
Revises: 08f0f142574e
Create Date: 2026-10-14

Additive: one new table, one function, two triggers per audit table. No
existing row is read or rewritten. CREATE TRIGGER takes SHARE ROW EXCLUSIVE on
each audit table briefly (blocks writes to that table for the DDL only).

Re-parented 2026-10-15 from 8b14824fb575 onto main's 08f0f142574e when
origin/main was merged into nikhil: written in parallel with the Netherlands
M8/M9 chain on the same parent, never on main and never applied to
production, so moving its parent keeps the history linear (no merge revision).
"""

import sqlalchemy as sa
from alembic import op

revision = "d1e5a7c3b9f2"
down_revision = "08f0f142574e"
branch_labels = None
depends_on = None

AUDIT_TABLES = ("payroll_tax_configuration_audit", "assisted_access_audit_events",
                "payroll_personal_data_access_events", "auth_audit_events")


def upgrade() -> None:
    op.create_table(
        "auth_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("email_sha256", sa.String(64), nullable=True),
        sa.Column("reason", sa.String(80), nullable=True),
        sa.Column("client_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(300), nullable=True),
    )
    for col in ("id", "occurred_at", "event_type", "user_id", "organization_id"):
        op.create_index(f"ix_auth_audit_events_{col}", "auth_audit_events", [col])

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
        $$
    """)
    for t in AUDIT_TABLES:
        op.execute(f"CREATE TRIGGER {t}_append_only BEFORE UPDATE OR DELETE ON {t} "
                   f"FOR EACH ROW EXECUTE FUNCTION zoiko_reject_audit_mutation()")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for t in AUDIT_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {t}_append_only ON {t}")
        op.execute("DROP FUNCTION IF EXISTS zoiko_reject_audit_mutation()")
    for col in ("organization_id", "user_id", "event_type", "occurred_at", "id"):
        op.drop_index(f"ix_auth_audit_events_{col}", table_name="auth_audit_events")
    op.drop_table("auth_audit_events")
