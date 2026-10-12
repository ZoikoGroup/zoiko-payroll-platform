"""
modules/assisted_access/models.py
----------------------------------
Assisted Access ("SafeGuard") domain models.

Two tables:
  - assisted_access_sessions: an active, time-boxed take-over of an
    organization by a Super Admin. NEVER a generic "become this user"
    mechanism — the org admin's own credentials are never involved and the
    acting identity is always the requesting Super Admin, recorded in every
    audit row.
  - assisted_access_audit_events: append-only log of every request made
    under a session (plus session lifecycle events). Mirrors
    BillingCommercialAuditEvent / AssistAuditEvent shapes closely enough to
    be merged by the Security & Audit read model, but the session-bound
    fields (assisted_access_session_id, method, path, status_code) don't
    fit either existing table, so it gets its own table with
    source="assisted_access".
"""

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    func,
)

from app.database import Base


class AssistedAccessSession(Base):
    """One time-boxed support-assist session for an organization."""

    __tablename__ = "assisted_access_sessions"

    id = Column(Integer, primary_key=True, index=True)
    # Which org is being assisted. Indexed because every org-scoped lookup
    # (customer banner status, sweep, audit read) filters on it.
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    # The Super Admin who requested the session — the acting principal on
    # every audited request, never the org admin.
    requested_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    # Required — blank-reason access is rejected at the API layer.
    reason = Column(Text, nullable=False)

    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # Hard cap — started_at + ASSISTED_ACCESS_SESSION_MINUTES by default.
    expires_at = Column(DateTime, nullable=False)

    ended_at = Column(DateTime, nullable=True)
    # EXPIRED (sweep) | MANUAL_END (POST .../end).
    ended_reason = Column(String(20), nullable=True)

    def __repr__(self):
        return f"<AssistedAccessSession id={self.id} org={self.organization_id} active={self.ended_at is None}>"


class AssistedAccessAuditEvent(Base):
    """Append-only. No update/delete path should ever be written here."""

    __tablename__ = "assisted_access_audit_events"

    id = Column(Integer, primary_key=True, index=True)
    assisted_access_session_id = Column(
        Integer, ForeignKey("assisted_access_sessions.id"), nullable=False, index=True
    )
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Lifecycle events (ASSISTED_ACCESS_STARTED / _ENDED / _EXPIRED) and
    # per-request ORG_API_CALL rows.
    event_type = Column(String(80), nullable=False, index=True)

    # The exact request that was viewed/changed, for per-request audit rows.
    method = Column(String(10), nullable=True)
    path = Column(String(300), nullable=True)
    status_code = Column(Integer, nullable=True)

    payload = Column(JSON, nullable=True)
    recorded_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_assisted_access_audit_org_created", "organization_id", "recorded_at"),
    )

    def __repr__(self):
        return f"<AssistedAccessAuditEvent id={self.id} {self.event_type} org={self.organization_id}>"


def ensure_tables() -> None:
    """Create just this module's tables if missing. Called at app startup
    after initialize_database, which skips create_all entirely once ANY
    table exists (a migrated DB) — without this, the two assisted-access
    tables would silently never be created on an existing deployment."""
    from app.database import Base, engine

    Base.metadata.create_all(
        bind=engine,
        tables=[AssistedAccessSession.__table__, AssistedAccessAuditEvent.__table__],
    )