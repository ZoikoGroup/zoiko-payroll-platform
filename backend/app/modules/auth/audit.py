"""G5 F-5: write one auth_audit_events row per authentication event.

`required=True` (successful login / refresh): if the row cannot be written the
caller refuses the request (503) - no session without an audit record.
Otherwise (failures, logout, reset): best effort, logged on error."""

import hashlib
import logging

from sqlalchemy.orm import Session

from app.core.exceptions import ZoikoException

logger = logging.getLogger("zoiko_payroll.auth.audit")

LOGIN_SUCCESS = "LOGIN_SUCCESS"
LOGIN_FAILED = "LOGIN_FAILED"
ACCOUNT_INACTIVE = "ACCOUNT_INACTIVE"
REFRESH = "REFRESH"
REFRESH_FAILED = "REFRESH_FAILED"
LOGOUT = "LOGOUT"
PASSWORD_RESET_REQUESTED = "PASSWORD_RESET_REQUESTED"
PASSWORD_RESET = "PASSWORD_RESET"
INVITATION_ACCEPTED = "INVITATION_ACCEPTED"


def email_sha256(email) -> str:
    return hashlib.sha256((email or "").strip().lower().encode("utf-8")).hexdigest()


def record(db: Session, event_type: str, *, user=None, email=None, request=None, reason=None,
           required: bool = False) -> None:
    from app.modules.auth.models import AuthAuditEvent

    audit_db = Session(bind=db.get_bind())
    try:
        audit_db.add(AuthAuditEvent(
            event_type=event_type,
            user_id=getattr(user, "id", None),
            organization_id=getattr(user, "organization_id", None),
            email_sha256=email_sha256(email) if (email and user is None) else None,
            reason=(reason or None) and str(reason)[:80],
            client_address=(getattr(getattr(request, "client", None), "host", None) or None),
            user_agent=(request.headers.get("user-agent", "")[:300] or None) if request is not None else None,
        ))
        audit_db.commit()
    except Exception:  # noqa: BLE001
        audit_db.rollback()
        logger.exception("[auth-audit] could not record %s", event_type)
        if required:
            raise ZoikoException(503, "AUTH_AUDIT_UNAVAILABLE",
                                 "Sign-in is temporarily unavailable: the audit record could not be written.")
    finally:
        audit_db.close()
