"""
modules/assisted_access/audit.py
--------------------------------
Per-request auditing for SafeGuard assisted-access sessions.

Every HTTP request carrying a valid assisted-access token is recorded to
assisted_access_audit_events with source="assisted_access" — the exact
request (method/path/status) that was made under the session. This is the
single chokepoint that makes "nobody can claim they didn't know what the
session touched" structurally true: it needs no per-endpoint cooperation.

Implemented as a FastAPI middleware (see main.py). This post-response row is
the completion record; the request already ran, so a failure here cannot undo
it and is logged. Since G5 F-4 the request is preceded by an
ORG_API_CALL_STARTED row (core/dependencies.py, fail closed); this row carries
its id as `intent_id`, and a start without a completion raises a Super Admin
security alert (assisted_access.service.assisted_audit_gap_alerts).
"""

import logging
import re

from app.core.security import decode_assisted_access_token

logger = logging.getLogger("zoiko_payroll.assisted_access.audit")

# Never scribe security tokens that may appear in a query string.
# Anchored at the start too: request.url.query carries no leading "?", so the
# old [?&]-only pattern left a first `token=` parameter unredacted (found by the
# F-4 tests).
_REDACT_RE = re.compile(r"(?i)((?:^|[?&])(?:token|code)=)[^&\s\"']+")


def redact(value: str) -> str:
    return _REDACT_RE.sub(r"[REDACTED]", value or "")


def record_request_if_assisted(request, status_code: int) -> None:
    """Middle-ware hook: after the response is produced, persist an audit
    row for any request that ran under an active assisted-access token."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return
    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        return

    payload = decode_assisted_access_token(token)
    if not payload:
        return  # not an assisted-access request — nothing to audit here

    session_id = payload.get("assisted_access_session_id")
    organization_id = payload.get("organization_id")
    if session_id is None or organization_id is None:
        return

    from app.database import SessionLocal
    from app.modules.assisted_access.models import AssistedAccessAuditEvent, AssistedAccessSession

    db = SessionLocal()
    try:
        session = db.query(AssistedAccessSession).filter(AssistedAccessSession.id == session_id).first()
        intent_id = getattr(getattr(request, "state", None), "assisted_intent_id", None)
        if session is None or (session.ended_at is not None and not intent_id):
            return

        path = _REDACT_RE.sub(r"\1[REDACTED]", request.url.path)
        db.add(AssistedAccessAuditEvent(
            assisted_access_session_id=session.id,
            organization_id=session.organization_id,
            actor_user_id=session.requested_by_user_id,
            event_type="ORG_API_CALL",
            method=request.method,
            path=path,
            status_code=status_code,
            payload={
                "query": _REDACT_RE.sub(r"\1[REDACTED]", request.url.query),
                "assisting": True,
                "intent_id": intent_id,
            },
        ))
        db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("[assisted-access] audit write failed (request skipped — never break traffic)")
        db.rollback()
    finally:
        db.close()