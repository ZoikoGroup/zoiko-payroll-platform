"""MFA, refresh-token rotation and JIT Support Access (ZP-PRIV B08 / Part D)

Revision ID: c5e7a9b1d3f4
Revises: b2f4d6a8c0e1
Create Date: 2026-10-19

New tables
  mfa_credentials, mfa_recovery_codes      TOTP seed (encrypted) + hashed codes
  auth_refresh_tokens                      refresh rotation / reuse detection
  support_access_grants                    JIT grants (constraints below)
  support_grant_employees                  resolved employee scope
  support_access_audit_events              append-only, hash-chained trail

PostgreSQL guarantees
  * nobody approves / reviews their own request (CHECK);
  * requested_minutes 1..30 and expires_at - activated_at <= 30 minutes (CHECK);
  * one pending/active grant per operator (partial unique index);
  * support_access_audit_events is append-only: UPDATE is refused except the
    one-time NULL -> value fill of row_hash with every other column unchanged
    (JSON compared as jsonb - json has no equality operator), and DELETE only
    inside an explicit audit purge scope.

Legacy assisted-access sessions still open are ended here as well (the app
also refuses their tokens); their tables stay for history.

Deploy note: existing refresh tokens have no rotation record, so every user
signs in once more after this release (and privileged users set up MFA).
"""

import sqlalchemy as sa
from alembic import op

revision = "c5e7a9b1d3f4"
down_revision = "b2f4d6a8c0e1"
branch_labels = None
depends_on = None


def _sql(bind, statement: str) -> None:
    """Run one DDL statement. sa.text() escapes the % in plpgsql bodies for
    the psycopg2 driver (exec_driver_sql would treat it as a parameter)."""
    bind.execute(sa.text(statement))

_AUDIT = "support_access_audit_events"


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    op.create_table(
        "mfa_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(20), nullable=False, server_default="TOTP"),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("enrolled_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_step", sa.Integer(), nullable=True),
    )
    op.create_index("ix_mfa_credentials_user_id", "mfa_credentials", ["user_id"], unique=True)

    op.create_table(
        "mfa_recovery_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("used_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_mfa_recovery_codes_user_id", "mfa_recovery_codes", ["user_id"])

    op.create_table(
        "auth_refresh_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("jti", sa.String(64), nullable=False),
        sa.Column("family_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("issued_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoke_reason", sa.String(40), nullable=True),
        sa.Column("client_fingerprint", sa.String(64), nullable=True),
        sa.Column("mfa_at", sa.Integer(), nullable=True),
    )
    op.create_index("ix_auth_refresh_tokens_jti", "auth_refresh_tokens", ["jti"], unique=True)
    op.create_index("ix_auth_refresh_tokens_family_id", "auth_refresh_tokens", ["family_id"])
    op.create_index("ix_auth_refresh_tokens_user_id", "auth_refresh_tokens", ["user_id"])

    op.create_table(
        "support_access_grants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("ticket_reference", sa.String(120), nullable=False),
        sa.Column("requested_minutes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_entity_id", sa.Integer(),
                  sa.ForeignKey("legal_entities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("scope_pay_group_id", sa.Integer(),
                  sa.ForeignKey("pay_groups.id", ondelete="SET NULL"), nullable=True),
        sa.Column("requested_employee_codes", sa.JSON(), nullable=True),
        sa.Column("allowed_field_classes", sa.JSON(), nullable=True),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("approval_expires_at", sa.DateTime(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("exited_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approval_note", sa.Text(), nullable=True),
        sa.Column("declined_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decline_reason", sa.Text(), nullable=True),
        sa.Column("scope_narrowed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("zoiko_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("zoiko_approved_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("zoiko_approved_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("revoked_by_tenant", sa.Boolean(), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.Column("is_break_glass", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("incident_reference", sa.String(120), nullable=True),
        sa.Column("review_due_at", sa.DateTime(), nullable=True),
        sa.Column("review_escalated_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("review_outcome", sa.String(20), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("support_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("support_username", sa.String(200), nullable=True),
        sa.Column("support_password_encrypted", sa.Text(), nullable=True),
        sa.CheckConstraint("approved_by_user_id IS NULL OR approved_by_user_id <> requested_by_user_id",
                           name="ck_support_grant_no_self_tenant_approval"),
        sa.CheckConstraint("zoiko_approved_by_user_id IS NULL OR zoiko_approved_by_user_id <> requested_by_user_id",
                           name="ck_support_grant_no_self_zoiko_approval"),
        sa.CheckConstraint("reviewed_by_user_id IS NULL OR reviewed_by_user_id <> requested_by_user_id",
                           name="ck_support_grant_no_self_review"),
        sa.CheckConstraint("requested_minutes >= 1 AND requested_minutes <= 30",
                           name="ck_support_grant_minutes_max_30"),
        sa.CheckConstraint("status IN ('pending_approval','active','denied','cancelled','revoked','exited',"
                           "'expired','expired_unused')", name="ck_support_grant_status"),
    )
    for col in ("organization_id", "requested_by_user_id", "status", "correlation_id"):
        op.create_index(f"ix_support_access_grants_{col}", "support_access_grants", [col])
    op.create_index("uq_support_grant_one_live_per_operator", "support_access_grants",
                    ["requested_by_user_id"], unique=True,
                    sqlite_where=sa.text("status IN ('pending_approval','active')"),
                    postgresql_where=sa.text("status IN ('pending_approval','active')"))

    op.create_table(
        "support_grant_employees",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("grant_id", sa.Integer(),
                  sa.ForeignKey("support_access_grants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Integer(),
                  sa.ForeignKey("payroll_employees.id", ondelete="CASCADE"), nullable=False),
    )
    op.create_index("ix_support_grant_employees_grant_id", "support_grant_employees", ["grant_id"])
    op.create_index("ix_support_grant_employees_employee_id", "support_grant_employees", ["employee_id"])

    op.create_table(
        "support_access_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("grant_id", sa.Integer(), nullable=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_role", sa.String(40), nullable=True),
        sa.Column("support_user_id", sa.Integer(), nullable=True),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("client_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(300), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("prev_hash", sa.String(64), nullable=True),
        sa.Column("row_hash", sa.String(64), nullable=True),
    )
    for col in ("recorded_at", "event_type", "grant_id", "organization_id", "actor_user_id", "correlation_id"):
        op.create_index(f"ix_{_AUDIT}_{col}", _AUDIT, [col])

    if is_pg:
        install_postgres_guards(bind)

    # Retire legacy assisted-access sessions still open (Part D supersedes it).
    op.execute("""
        UPDATE assisted_access_sessions
        SET ended_at = CURRENT_TIMESTAMP,
            ended_reason = CASE WHEN approval_status = 'PENDING' THEN 'REQUEST_EXPIRED' ELSE 'MANUAL_END' END,
            approval_status = CASE WHEN approval_status = 'PENDING' THEN 'EXPIRED' ELSE approval_status END
        WHERE ended_at IS NULL
    """)


def install_postgres_guards(bind) -> None:
    """PostgreSQL-only guarantees for Part D. Plain SQL on ``bind`` so the
    Postgres test suite (tests/privacy/test_postgres_guards.py) applies the
    exact same statements to a create_all schema."""
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
    _sql(bind, 
        "ALTER TABLE support_access_grants DROP CONSTRAINT IF EXISTS ck_support_grant_window_max_30")
    _sql(bind, 
        "ALTER TABLE support_access_grants ADD CONSTRAINT ck_support_grant_window_max_30 "
        "CHECK (activated_at IS NULL OR expires_at IS NULL "
        "OR expires_at - activated_at <= interval '30 minutes')"
    )
    _sql(bind, """
        CREATE OR REPLACE FUNCTION zoiko_support_audit_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF zoiko_audit_purge_allowed() THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION 'audit rows are append-only (%: DELETE refused)', TG_TABLE_NAME
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            -- UPDATE: only the one-time NULL -> value fill of row_hash.
            IF OLD.row_hash IS NULL AND NEW.row_hash IS NOT NULL
               AND NEW.id = OLD.id
               AND NEW.recorded_at IS NOT DISTINCT FROM OLD.recorded_at
               AND NEW.event_type IS NOT DISTINCT FROM OLD.event_type
               AND NEW.grant_id IS NOT DISTINCT FROM OLD.grant_id
               AND NEW.organization_id IS NOT DISTINCT FROM OLD.organization_id
               AND NEW.actor_user_id IS NOT DISTINCT FROM OLD.actor_user_id
               AND NEW.actor_role IS NOT DISTINCT FROM OLD.actor_role
               AND NEW.support_user_id IS NOT DISTINCT FROM OLD.support_user_id
               AND NEW.requested_by_user_id IS NOT DISTINCT FROM OLD.requested_by_user_id
               AND NEW.reason IS NOT DISTINCT FROM OLD.reason
               AND NEW.correlation_id IS NOT DISTINCT FROM OLD.correlation_id
               AND NEW.client_address IS NOT DISTINCT FROM OLD.client_address
               AND NEW.user_agent IS NOT DISTINCT FROM OLD.user_agent
               AND NEW.detail::jsonb IS NOT DISTINCT FROM OLD.detail::jsonb
               AND NEW.prev_hash IS NOT DISTINCT FROM OLD.prev_hash THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'audit rows are append-only (%: UPDATE refused)', TG_TABLE_NAME
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$;
    """)
    _sql(bind, f"DROP TRIGGER IF EXISTS {_AUDIT}_append_only ON {_AUDIT}")
    _sql(bind, f"CREATE TRIGGER {_AUDIT}_append_only BEFORE UPDATE OR DELETE ON {_AUDIT} "
                         f"FOR EACH ROW EXECUTE FUNCTION zoiko_support_audit_guard()")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(f"DROP TRIGGER IF EXISTS {_AUDIT}_append_only ON {_AUDIT}")
        op.execute("DROP FUNCTION IF EXISTS zoiko_support_audit_guard()")
    for col in ("correlation_id", "actor_user_id", "organization_id", "grant_id", "event_type", "recorded_at"):
        op.drop_index(f"ix_{_AUDIT}_{col}", table_name=_AUDIT)
    op.drop_table(_AUDIT)
    op.drop_index("ix_support_grant_employees_employee_id", table_name="support_grant_employees")
    op.drop_index("ix_support_grant_employees_grant_id", table_name="support_grant_employees")
    op.drop_table("support_grant_employees")
    op.drop_index("uq_support_grant_one_live_per_operator", table_name="support_access_grants")
    for col in ("correlation_id", "status", "requested_by_user_id", "organization_id"):
        op.drop_index(f"ix_support_access_grants_{col}", table_name="support_access_grants")
    op.drop_table("support_access_grants")
    op.drop_index("ix_auth_refresh_tokens_user_id", table_name="auth_refresh_tokens")
    op.drop_index("ix_auth_refresh_tokens_family_id", table_name="auth_refresh_tokens")
    op.drop_index("ix_auth_refresh_tokens_jti", table_name="auth_refresh_tokens")
    op.drop_table("auth_refresh_tokens")
    op.drop_index("ix_mfa_recovery_codes_user_id", table_name="mfa_recovery_codes")
    op.drop_table("mfa_recovery_codes")
    op.drop_index("ix_mfa_credentials_user_id", table_name="mfa_credentials")
    op.drop_table("mfa_credentials")
