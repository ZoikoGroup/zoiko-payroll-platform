"""
modules/security/events.py
--------------------------
The unified security event log (ZP-PRIV E01/E02).

``emit()`` is called for every PDP denial, export attempt, privileged read,
support-access grant event, MFA failure and credential reset. The row holds
ids, codes and results only - no payload, no personal data - and is chained:
``row_hash = sha256(canonical(row) + prev_hash)``. The chain is verified by
``verify_chain()`` and anchored to retention-locked external storage by
``anchor()`` (the sink is pluggable; tests use FakeSink).

Writes happen on their own session (an audit write never depends on, or
rolls back with, the business transaction). A failed write is logged and
raises the "failed audit write" alert; the caller decides whether the action
it describes may proceed (the PDP denies regardless; the support intent audit
fails closed).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.security.models import SecurityEvent, SecurityEventAnchor

logger = logging.getLogger("zoiko_payroll.security.events")
_chain_lock = threading.Lock()
CHAIN_LOCK_KEY = 0x5A50_E02  # pg advisory lock id for the security event chain

ALLOW, DENY, ERROR = "allow", "deny", "error"

_FIELDS = ("occurred_at", "correlation_id", "event_type", "actor_user_id", "actor_role", "on_behalf_of_user_id",
           "organization_id", "grant_id", "ticket_reference", "target_type", "target_id", "action", "result",
           "reason_code", "decision_trace_id", "ip", "user_agent", "prev_hash")


def _canonical(row: SecurityEvent) -> str:
    def norm(v):
        if isinstance(v, datetime):
            if v.tzinfo is None:
                v = v.replace(tzinfo=timezone.utc)
            return v.astimezone(timezone.utc).isoformat()
        return v

    return json.dumps({f: norm(getattr(row, f)) for f in _FIELDS}, sort_keys=True, default=str)


def _hash(row: SecurityEvent) -> str:
    return hashlib.sha256(_canonical(row).encode("utf-8")).hexdigest()


def _request_meta(request) -> tuple:
    if request is None:
        return None, None
    host = getattr(getattr(request, "client", None), "host", None)
    agent = (request.headers.get("user-agent") or "")[:300] if hasattr(request, "headers") else None
    return host, agent or None


def emit(bind_or_db, event_type: str, *, result: str, actor_user_id: Optional[int] = None,
         actor_role: Optional[str] = None, on_behalf_of_user_id: Optional[int] = None,
         organization_id: Optional[int] = None, grant_id: Optional[int] = None,
         ticket_reference: Optional[str] = None, target_type: Optional[str] = None,
         target_id: Optional[str] = None, action: Optional[str] = None, reason_code: Optional[str] = None,
         decision_trace_id: Optional[str] = None, request=None, correlation_id: Optional[str] = None
         ) -> Optional[SecurityEvent]:
    """Append one security event. Never raises (see module docstring)."""
    from app.core import correlation

    bind = bind_or_db.get_bind() if hasattr(bind_or_db, "get_bind") else bind_or_db
    ip, agent = _request_meta(request)
    cid = correlation_id or (getattr(getattr(request, "state", None), "correlation_id", None) if request else None) \
        or correlation.current()
    db = Session(bind=bind)
    try:
        with _chain_lock:
            if db.get_bind().dialect.name == "postgresql":
                # The thread lock only serializes one process; workers and
                # app servers share the chain, so take a transaction-scoped
                # advisory lock before reading the head (released on commit).
                db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": CHAIN_LOCK_KEY})
            prev = db.query(SecurityEvent.row_hash).order_by(SecurityEvent.id.desc()).first()
            from app.modules.security.alerts import now as _now  # one injectable clock

            row = SecurityEvent(
                occurred_at=_now(), correlation_id=cid, event_type=event_type[:60],
                actor_user_id=actor_user_id, actor_role=actor_role, on_behalf_of_user_id=on_behalf_of_user_id,
                organization_id=organization_id, grant_id=grant_id,
                ticket_reference=(ticket_reference or None) and ticket_reference[:120],
                target_type=target_type, target_id=(target_id or None) and str(target_id)[:200], action=action,
                result=result, reason_code=reason_code, decision_trace_id=decision_trace_id, ip=ip,
                user_agent=agent, prev_hash=prev[0] if prev else None,
            )
            row.row_hash = _hash(row)
            db.add(row)
            db.commit()
            db.refresh(row)
        _evaluate_alerts(bind, row)
        return row
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("[security-event] write failed: %s", event_type)
        _audit_write_failed(bind, event_type)
        return None
    finally:
        db.close()


def _evaluate_alerts(bind, row: SecurityEvent) -> None:
    try:
        from app.modules.security import alerts

        alerts.observe(bind, row)
    except Exception:  # noqa: BLE001 - alerting must never break the audited action
        logger.exception("[security-event] alert evaluation failed for event %s", row.id)


def _audit_write_failed(bind, event_type: str) -> None:
    try:
        from app.modules.security import alerts

        alerts.raise_alert(bind, "failed_audit_write", dedupe_key=event_type,
                           summary=f"A security event of type {event_type} could not be written")
    except Exception:  # noqa: BLE001
        logger.critical("[security-event] could not raise the failed-audit-write alert")


def verify_chain(db: Session) -> dict:
    """Recompute every hash and link. Any tampering is detected."""
    prev_hash = None
    count = 0
    for row in db.query(SecurityEvent).order_by(SecurityEvent.id).yield_per(500):
        if row.prev_hash != prev_hash or _hash(row) != row.row_hash:
            return {"ok": False, "broken_at": row.id, "checked": count}
        prev_hash = row.row_hash
        count += 1
    return {"ok": True, "checked": count, "head": prev_hash}


class FakeSink:
    """In-memory sink for tests (retention-locked buckets cannot be cleaned)."""

    name = "fake"

    def __init__(self):
        self.objects = []

    def put(self, key: str, body: bytes) -> str:
        self.objects.append((key, body))
        return f"fake://{key}"


class GcsRetentionSink:
    """Writes anchors to a GCS bucket configured with a locked retention
    policy (deploy/security/anchor_bucket.tf). Requires google-cloud-storage
    and runtime credentials; not exercised in CI (awaiting infra owner)."""

    name = "gcs-retention"

    def __init__(self, bucket: str, prefix: str = "security-anchors/"):
        self.bucket, self.prefix = bucket, prefix

    def put(self, key: str, body: bytes) -> str:  # pragma: no cover - needs real GCS
        from google.cloud import storage  # type: ignore

        blob = storage.Client().bucket(self.bucket).blob(self.prefix + key)
        blob.upload_from_string(body, content_type="application/json", if_generation_match=0)
        return f"gs://{self.bucket}/{self.prefix}{key}"


def anchor(db: Session, sink) -> Optional[SecurityEventAnchor]:
    """Write the current chain head to the external sink and record it."""
    head = db.query(SecurityEvent).order_by(SecurityEvent.id.desc()).first()
    if head is None:
        return None
    count = db.query(SecurityEvent).count()
    body = json.dumps({"last_event_id": head.id, "last_row_hash": head.row_hash, "event_count": count,
                       "anchored_at": datetime.now(timezone.utc).isoformat()}, sort_keys=True).encode("utf-8")
    receipt = sink.put(f"anchor-{head.id}-{head.row_hash[:16]}.json", body)
    row = SecurityEventAnchor(last_event_id=head.id, last_row_hash=head.row_hash, event_count=count,
                              sink=sink.name, sink_receipt=receipt)
    db.add(row)
    db.commit()
    return row
