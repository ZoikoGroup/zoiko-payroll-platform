"""
modules/assisted_access/audit.py
--------------------------------
Per-request auditing for SafeGuard assisted-access sessions.

Every HTTP request carrying a valid assisted-access token is recorded to
assisted_access_audit_events with source="assisted_access" — the exact
request (method/path/status) that was made under the session. This is the
single chokepoint that makes "nobody can claim they didn't know what the
session touched" structurally true: it needs no per-endpoint cooperation.

Implemented as a FastAPI middleware (see main.py). Failure to audit must
never break the underlying request, so everything here is best-effort and
swallows its own exceptions.
"""

import logging
import re

from app.core.security import decode_assisted_access_token

logger = logging.getLogger("zoiko_payroll.assisted_access.audit")

# Never scribe security tokens that may appear in a query string.
_REDACT_RE = re.compile(r"(?i)([?&](?:token|code)=)[^&\s\"']+")


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
        if session is None or session.ended_at is not None:
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
            },
        ))
        db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("[assisted-access] audit write failed (request skipped — never break traffic)")
        db.rollback()
    finally:
        db.close()