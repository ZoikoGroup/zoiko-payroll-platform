"""
modules/support_access/models.py
--------------------------------
JIT Support Access (ZP-PRIV Part D, controls C01-C08).

A Zoiko operator never holds standing access to tenant worker data. To help
with a ticket they request a grant; the tenant's org admin approves (and, for
worker-level scope, an independent Zoiko Platform Security officer approves
too); on activation a temporary, read-only tenant login is created that works
for at most 30 minutes and only inside the approved scope.

Database-level guarantees (also enforced in the service layer):
  * nobody approves their own request (tenant or Zoiko approval);
  * a break-glass review is never done by the person who opened it;
  * requested_minutes is 1..30, and expires_at - activated_at <= 30 minutes
    (CHECK on PostgreSQL via the migration; trigger on SQLite below);
  * one live (pending or active) grant per operator (partial unique index).

The audit trail (support_access_audit_events) is append-only (F-6) and
hash-chained: each row stores the previous row's hash and its own.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    event,
    text,
)

from app.database import Base

# ── Statuses ─────────────────────────────────────────────────────────────────
PENDING = "pending_approval"
ACTIVE = "active"
DENIED = "denied"
CANCELLED = "cancelled"
REVOKED = "revoked"
EXITED = "exited"
EXPIRED = "expired"
EXPIRED_UNUSED = "expired_unused"

LIVE_STATUSES = (PENDING, ACTIVE)
ENDED_STATUSES = (DENIED, CANCELLED, REVOKED, EXITED, EXPIRED, EXPIRED_UNUSED)
ALL_STATUSES = LIVE_STATUSES + ENDED_STATUSES

# ── Scope types ──────────────────────────────────────────────────────────────
SCOPE_DIAGNOSTICS = "diagnostics"   # tenant metadata only, no worker rows
SCOPE_ENTITY = "entity"             # one legal entity's workers
SCOPE_PAY_GROUP = "pay_group"       # one pay group's workers
SCOPE_EMPLOYEES = "employees"       # up to 10 named workers
SCOPE_TENANT = "tenant"             # break-glass only: tenant-wide, id+contact
SCOPE_TYPES = (SCOPE_DIAGNOSTICS, SCOPE_ENTITY, SCOPE_PAY_GROUP, SCOPE_EMPLOYEES)

# ── Break-glass review outcomes ──────────────────────────────────────────────
REVIEW_JUSTIFIED = "justified"
REVIEW_NOT_JUSTIFIED = "not_justified"


class SupportAccessGrant(Base):
    __tablename__ = "support_access_grants"
    __table_args__ = (
        CheckConstraint("approved_by_user_id IS NULL OR approved_by_user_id <> requested_by_user_id",
                        name="ck_support_grant_no_self_tenant_approval"),
        CheckConstraint("zoiko_approved_by_user_id IS NULL OR zoiko_approved_by_user_id <> requested_by_user_id",
                        name="ck_support_grant_no_self_zoiko_approval"),
        CheckConstraint("reviewed_by_user_id IS NULL OR reviewed_by_user_id <> requested_by_user_id",
                        name="ck_support_grant_no_self_review"),
        CheckConstraint("requested_minutes >= 1 AND requested_minutes <= 30",
                        name="ck_support_grant_minutes_max_30"),
        CheckConstraint("status IN ('pending_approval','active','denied','cancelled','revoked','exited',"
                        "'expired','expired_unused')", name="ck_support_grant_status"),
        Index("uq_support_grant_one_live_per_operator", "requested_by_user_id", unique=True,
              sqlite_where=text("status IN ('pending_approval','active')"),
              postgresql_where=text("status IN ('pending_approval','active')")),
    )

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    reason = Column(Text, nullable=False)
    ticket_reference = Column(String(120), nullable=False)
    requested_minutes = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default=PENDING, index=True)
    correlation_id = Column(String(64), nullable=False, index=True)

    scope_type = Column(String(20), nullable=False, default=SCOPE_DIAGNOSTICS)
    scope_entity_id = Column(Integer, ForeignKey("legal_entities.id", ondelete="SET NULL"), nullable=True)
    scope_pay_group_id = Column(Integer, ForeignKey("pay_groups.id", ondelete="SET NULL"), nullable=True)
    # Codes typed by the operator from the ticket. Resolved server-side only
    # at tenant approval; never returned to the operator.
    requested_employee_codes = Column(JSON, nullable=True)
    allowed_field_classes = Column(JSON, nullable=True)

    requested_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    approval_expires_at = Column(DateTime, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    activated_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    exited_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)

    # Tenant decision.
    approved_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    approval_note = Column(Text, nullable=True)
    declined_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    decline_reason = Column(Text, nullable=True)
    scope_narrowed = Column(Boolean, default=False, nullable=False)

    # Independent Zoiko approval (worker-level scope only, decision 4).
    zoiko_required = Column(Boolean, default=False, nullable=False)
    zoiko_approved_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    zoiko_approved_at = Column(DateTime, nullable=True)

    # Revocation.
    revoked_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    revoked_by_tenant = Column(Boolean, nullable=True)
    revoke_reason = Column(Text, nullable=True)

    # Break-glass (decision 5: fresh MFA + independent review within 24 h).
    is_break_glass = Column(Boolean, default=False, nullable=False)
    incident_reference = Column(String(120), nullable=True)
    review_due_at = Column(DateTime, nullable=True)
    review_escalated_at = Column(DateTime, nullable=True)
    reviewed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_outcome = Column(String(20), nullable=True)
    review_note = Column(Text, nullable=True)

    # Temporary login (password encrypted with core/secretbox; the login
    # itself uses the user's normal bcrypt hash). Wiped when the grant ends.
    support_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    support_username = Column(String(200), nullable=True)
    support_password_encrypted = Column(Text, nullable=True)


class SupportGrantEmployee(Base):
    """The resolved worker scope of an ``employees`` grant (tenant-resolved
    at approval; never shown to the operator)."""

    __tablename__ = "support_grant_employees"

    id = Column(Integer, primary_key=True, index=True)
    grant_id = Column(Integer, ForeignKey("support_access_grants.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("payroll_employees.id", ondelete="CASCADE"), nullable=False, index=True)


class SupportAccessAuditEvent(Base):
    """Append-only, hash-chained support access trail (ZP-PRIV D.4, C07)."""

    __tablename__ = "support_access_audit_events"

    id = Column(Integer, primary_key=True, index=True)
    recorded_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    event_type = Column(String(50), nullable=False, index=True)
    grant_id = Column(Integer, nullable=True, index=True)
    organization_id = Column(Integer, nullable=True, index=True)
    actor_user_id = Column(Integer, nullable=True, index=True)
    actor_role = Column(String(40), nullable=True)
    # Named human attribution: the temporary account AND the person behind it.
    support_user_id = Column(Integer, nullable=True)
    requested_by_user_id = Column(Integer, nullable=True)
    reason = Column(Text, nullable=True)
    correlation_id = Column(String(64), nullable=True, index=True)
    client_address = Column(String(64), nullable=True)
    user_agent = Column(String(300), nullable=True)
    detail = Column(JSON, nullable=True)
    prev_hash = Column(String(64), nullable=True)
    row_hash = Column(String(64), nullable=True)


# SQLite has no interval arithmetic in CHECK constraints, so the 30-minute
# window is a trigger there; PostgreSQL gets a CHECK in the migration.
_SQLITE_WINDOW_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS support_grant_window_ins BEFORE INSERT ON support_access_grants "
    "WHEN NEW.activated_at IS NOT NULL AND NEW.expires_at IS NOT NULL AND "
    "(julianday(NEW.expires_at) - julianday(NEW.activated_at)) * 1440.0 > 30.0001 "
    "BEGIN SELECT RAISE(ABORT, 'support access window exceeds 30 minutes'); END",
    "CREATE TRIGGER IF NOT EXISTS support_grant_window_upd BEFORE UPDATE ON support_access_grants "
    "WHEN NEW.activated_at IS NOT NULL AND NEW.expires_at IS NOT NULL AND "
    "(julianday(NEW.expires_at) - julianday(NEW.activated_at)) * 1440.0 > 30.0001 "
    "BEGIN SELECT RAISE(ABORT, 'support access window exceeds 30 minutes'); END",
)


@event.listens_for(SupportAccessGrant.__table__, "after_create")
def _install_sqlite_window_triggers(target, connection, **kw):
    if connection.dialect.name == "sqlite":
        for ddl in _SQLITE_WINDOW_TRIGGERS:
            connection.exec_driver_sql(ddl)
