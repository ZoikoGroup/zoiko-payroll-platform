"""security events, alerts, machine clients, webhooks, DSAR, data region (ZP-PRIV D/E/F)

Revision ID: e1a3c5e7f9b2
Revises: d7f9b1c3e5a6
Create Date: 2026-10-19

* security_events (append-only, hash-chained: the row_hash may be set once,
  NULL -> value, with every other column unchanged; UPDATE otherwise and
  DELETE outside an explicit purge scope are refused) and
  security_event_anchors (append-only).
* alert_rules, alert_events, machine_clients, webhook_endpoints,
  webhook_deliveries, data_access_requests.
* organizations.data_region (default EU; decision 9).
* PostgreSQL: the row-level security policy of d7f9b1c3e5a6 is applied to the
  new tenant / worker tables (same derivation, same SQL).
"""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "e1a3c5e7f9b2"
down_revision = "d7f9b1c3e5a6"
branch_labels = None
depends_on = None


def _sql(bind, statement: str) -> None:
    bind.execute(sa.text(statement))


def _tz():
    return sa.DateTime(timezone=True)


def upgrade() -> None:
    bind = op.get_bind()
    op.create_table(
        "security_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("occurred_at", _tz(), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_role", sa.String(40), nullable=True),
        sa.Column("on_behalf_of_user_id", sa.Integer(), nullable=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("grant_id", sa.Integer(), nullable=True),
        sa.Column("ticket_reference", sa.String(120), nullable=True),
        sa.Column("target_type", sa.String(60), nullable=True),
        sa.Column("target_id", sa.String(200), nullable=True),
        sa.Column("action", sa.String(30), nullable=True),
        sa.Column("result", sa.String(10), nullable=False),
        sa.Column("reason_code", sa.String(60), nullable=True),
        sa.Column("decision_trace_id", sa.String(64), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(300), nullable=True),
        sa.Column("prev_hash", sa.String(64), nullable=True),
        sa.Column("row_hash", sa.String(64), nullable=True),
    )
    for col in ("occurred_at", "correlation_id", "event_type", "actor_user_id", "on_behalf_of_user_id",
                "organization_id", "grant_id", "reason_code", "decision_trace_id"):
        op.create_index(f"ix_security_events_{col}", "security_events", [col])

    op.create_table(
        "security_event_anchors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("anchored_at", _tz(), nullable=False),
        sa.Column("last_event_id", sa.Integer(), nullable=False),
        sa.Column("last_row_hash", sa.String(64), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("sink", sa.String(60), nullable=False),
        sa.Column("sink_receipt", sa.String(300), nullable=True),
    )

    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(60), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "alert_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_key", sa.String(60), nullable=False),
        sa.Column("dedupe_key", sa.String(200), nullable=False),
        sa.Column("window_start", _tz(), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("summary", sa.String(400), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("first_seen", _tz(), nullable=False),
        sa.Column("last_seen", _tz(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("acknowledged_by", sa.Integer(), nullable=True),
        sa.Column("acknowledged_at", _tz(), nullable=True),
        sa.Column("delivered_at", _tz(), nullable=True),
        sa.Column("delivery_receipt", sa.String(300), nullable=True),
        sa.Column("is_drill", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("rule_key", "dedupe_key", "window_start", name="uq_alert_dedupe_window"),
    )
    op.create_index("ix_alert_events_rule_key", "alert_events", ["rule_key"])
    op.create_index("ix_alert_events_organization_id", "alert_events", ["organization_id"])

    op.create_table(
        "machine_clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_key", sa.String(32), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("secret_hash", sa.String(64), nullable=False),
        sa.Column("created_at", _tz(), nullable=False),
        sa.Column("expires_at", _tz(), nullable=False),
        sa.Column("last_used_at", _tz(), nullable=True),
        sa.Column("last_used_ip", sa.String(64), nullable=True),
        sa.Column("known_networks", sa.JSON(), nullable=True),
        sa.Column("rotated_at", _tz(), nullable=True),
        sa.Column("revoked_at", _tz(), nullable=True),
    )
    op.create_index("ix_machine_clients_organization_id", "machine_clients", ["organization_id"])
    op.create_index("ix_machine_clients_client_key", "machine_clients", ["client_key"], unique=True)

    op.create_table(
        "webhook_endpoints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("signing_secret_hash", sa.String(64), nullable=False),
        sa.Column("signing_secret_encrypted", sa.Text(), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", _tz(), nullable=False),
    )
    op.create_index("ix_webhook_endpoints_organization_id", "webhook_endpoints", ["organization_id"])
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("endpoint_id", sa.Integer(), sa.ForeignKey("webhook_endpoints.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(64), nullable=False, unique=True),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("sent_at", _tz(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("response_code", sa.Integer(), nullable=True),
    )
    op.create_index("ix_webhook_deliveries_endpoint_id", "webhook_deliveries", ["endpoint_id"])
    op.create_index("ix_webhook_deliveries_organization_id", "webhook_deliveries", ["organization_id"])

    op.create_table(
        "data_access_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("payroll_employees.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("request_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="received"),
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("received_at", _tz(), nullable=False),
        sa.Column("due_at", _tz(), nullable=False),
        sa.Column("completed_at", _tz(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
    )
    op.create_index("ix_data_access_requests_organization_id", "data_access_requests", ["organization_id"])
    op.create_index("ix_data_access_requests_employee_id", "data_access_requests", ["employee_id"])

    with op.batch_alter_table("organizations") as batch:
        batch.add_column(sa.Column("data_region", sa.String(8), nullable=False, server_default="EU"))

    if bind.dialect.name == "postgresql":
        install_postgres_guards(bind)
        spec = importlib.util.spec_from_file_location(
            "zp_rls", Path(__file__).with_name("d7f9b1c3e5a6_postgres_row_level_security.py"))
        rls = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rls)
        rls.apply_rls(bind)


def install_postgres_guards(bind) -> None:
    """Append-only security log with a set-once hash (shared with the
    Postgres test suite)."""
    # ZP-PRIV E02: the transaction-local purge flag alone is settable by any
    # role. A purge is honoured only for members of zoiko_audit_purger (a
    # role ops grant to the migration / retention operator, never to the
    # application role; docs/privacy/rls_runbook.md).
    _sql(bind, """
        CREATE OR REPLACE FUNCTION zoiko_audit_purge_allowed() RETURNS boolean
        LANGUAGE plpgsql STABLE AS $$
        BEGIN
            IF coalesce(current_setting('zoiko.audit_purge', true), '') <> 'on' THEN
                RETURN false;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'zoiko_audit_purger') THEN
                RETURN false;
            END IF;
            RETURN pg_has_role(current_user, 'zoiko_audit_purger', 'MEMBER');
        END;
        $$;
    """)
    _sql(bind, """
        CREATE OR REPLACE FUNCTION zoiko_security_event_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF zoiko_audit_purge_allowed() THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION 'audit rows are append-only (%: DELETE refused)', TG_TABLE_NAME
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            IF OLD.row_hash IS NULL AND NEW.row_hash IS NOT NULL
               AND (to_jsonb(NEW) - 'row_hash') = (to_jsonb(OLD) - 'row_hash') THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'audit rows are append-only (%: UPDATE refused)', TG_TABLE_NAME
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$;
    """)
    _sql(bind, "DROP TRIGGER IF EXISTS security_events_append_only ON security_events")
    _sql(bind, "CREATE TRIGGER security_events_append_only BEFORE UPDATE OR DELETE ON security_events "
               "FOR EACH ROW EXECUTE FUNCTION zoiko_security_event_guard()")
    _sql(bind, """
        CREATE OR REPLACE FUNCTION zoiko_reject_audit_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND zoiko_audit_purge_allowed() THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'audit rows are append-only (%: % refused)', TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$;
    """)
    _sql(bind, "DROP TRIGGER IF EXISTS security_event_anchors_append_only ON security_event_anchors")
    _sql(bind, "CREATE TRIGGER security_event_anchors_append_only BEFORE UPDATE OR DELETE ON security_event_anchors "
               "FOR EACH ROW EXECUTE FUNCTION zoiko_reject_audit_mutation()")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        _sql(bind, "DROP TRIGGER IF EXISTS security_event_anchors_append_only ON security_event_anchors")
        _sql(bind, "DROP TRIGGER IF EXISTS security_events_append_only ON security_events")
        _sql(bind, "DROP FUNCTION IF EXISTS zoiko_security_event_guard()")
    with op.batch_alter_table("organizations") as batch:
        batch.drop_column("data_region")
    for table in ("data_access_requests", "webhook_deliveries", "webhook_endpoints", "machine_clients",
                  "alert_events", "alert_rules", "security_event_anchors", "security_events"):
        op.drop_table(table)
