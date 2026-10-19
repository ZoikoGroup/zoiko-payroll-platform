"""
modules/security/models.py
--------------------------
ZP-PRIV sections D, E, F: the platform security plane.

  security_events          unified, append-only, hash-chained security log (E01/E02).
                           NO payloads and NO personal data: ids, codes and
                           results only. Anchored periodically to
                           retention-locked external storage.
  security_event_anchors   the anchors written (chain head + count + sink receipt).
  alert_rules / alert_events   detection rules and deduplicated alerts (E03).
  machine_clients          tenant-pinned API clients with least-privilege scopes (D06).
  webhook_endpoints        tenant-pinned outbound webhooks, signed + replay-protected.
  webhook_deliveries       one row per delivery attempt (idempotency / replay).
  data_access_requests     DSAR / retention requests (F03).

New tables use timezone-aware timestamps (timestamptz on PostgreSQL).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SecurityEvent(Base):
    __tablename__ = "security_events"

    id = Column(Integer, primary_key=True, index=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    correlation_id = Column(String(64), nullable=True, index=True)
    event_type = Column(String(60), nullable=False, index=True)
    actor_user_id = Column(Integer, nullable=True, index=True)
    actor_role = Column(String(40), nullable=True)
    # For a temporary support login: the named human who requested the grant.
    on_behalf_of_user_id = Column(Integer, nullable=True, index=True)
    organization_id = Column(Integer, nullable=True, index=True)
    grant_id = Column(Integer, nullable=True, index=True)
    ticket_reference = Column(String(120), nullable=True)
    target_type = Column(String(60), nullable=True)
    # Opaque: a route template or a record kind + id; never a name or value.
    target_id = Column(String(200), nullable=True)
    action = Column(String(30), nullable=True)
    result = Column(String(10), nullable=False)  # allow | deny | error
    reason_code = Column(String(60), nullable=True, index=True)
    decision_trace_id = Column(String(64), nullable=True, index=True)
    ip = Column(String(64), nullable=True)
    user_agent = Column(String(300), nullable=True)
    prev_hash = Column(String(64), nullable=True)
    row_hash = Column(String(64), nullable=True)


class SecurityEventAnchor(Base):
    __tablename__ = "security_event_anchors"

    id = Column(Integer, primary_key=True, index=True)
    anchored_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_event_id = Column(Integer, nullable=False)
    last_row_hash = Column(String(64), nullable=False)
    event_count = Column(Integer, nullable=False)
    sink = Column(String(60), nullable=False)
    sink_receipt = Column(String(300), nullable=True)


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(60), nullable=False, unique=True)
    description = Column(Text, nullable=False)
    window_seconds = Column(Integer, nullable=False)
    threshold = Column(Integer, nullable=False)
    severity = Column(String(10), nullable=False)
    channel = Column(String(40), nullable=False, default="email+console")
    enabled = Column(Boolean, nullable=False, default=True)


class AlertEvent(Base):
    __tablename__ = "alert_events"
    __table_args__ = (UniqueConstraint("rule_key", "dedupe_key", "window_start", name="uq_alert_dedupe_window"),)

    id = Column(Integer, primary_key=True, index=True)
    rule_key = Column(String(60), nullable=False, index=True)
    dedupe_key = Column(String(200), nullable=False)
    window_start = Column(DateTime(timezone=True), nullable=False)
    severity = Column(String(10), nullable=False)
    # Ids and counts only - never a name, email address or value.
    summary = Column(String(400), nullable=False)
    organization_id = Column(Integer, nullable=True, index=True)
    first_seen = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_seen = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    count = Column(Integer, nullable=False, default=1)
    status = Column(String(20), nullable=False, default="open")  # open | acknowledged | resolved
    acknowledged_by = Column(Integer, nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    delivery_receipt = Column(String(300), nullable=True)
    is_drill = Column(Boolean, nullable=False, default=False)


class MachineClient(Base):
    __tablename__ = "machine_clients"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    client_key = Column(String(32), nullable=False, unique=True, index=True)
    scopes = Column(JSON, nullable=False)
    secret_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    last_used_ip = Column(String(64), nullable=True)
    known_networks = Column(JSON, nullable=True)
    rotated_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    url = Column(String(500), nullable=False)
    signing_secret_hash = Column(String(64), nullable=False)
    # Encrypted (core/secretbox): needed to sign every outbound delivery.
    signing_secret_encrypted = Column(Text, nullable=False)
    events = Column(JSON, nullable=False)
    status = Column(String(20), nullable=False, default="active")
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id = Column(Integer, primary_key=True, index=True)
    endpoint_id = Column(Integer, ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(Integer, nullable=False, index=True)
    event_id = Column(String(64), nullable=False, unique=True)
    event_type = Column(String(80), nullable=False)
    sent_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    status = Column(String(20), nullable=False, default="pending")
    response_code = Column(Integer, nullable=True)


class DataAccessRequest(Base):
    """DSAR / erasure / retention requests raised by a tenant (F03). The
    fulfilment is tenant-side; platform staff never see the subject's data."""

    __tablename__ = "data_access_requests"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("payroll_employees.id", ondelete="SET NULL"), nullable=True, index=True)
    request_type = Column(String(20), nullable=False)  # access | erasure | rectification
    status = Column(String(20), nullable=False, default="received")
    requested_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    received_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    due_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    outcome = Column(Text, nullable=True)
