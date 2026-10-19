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
# ZP-PRIV B08
MFA_CHALLENGE_ISSUED = "MFA_CHALLENGE_ISSUED"
MFA_ENROLLED = "MFA_ENROLLED"
MFA_VERIFIED = "MFA_VERIFIED"
MFA_FAILED = "MFA_FAILED"
MFA_STEP_UP = "MFA_STEP_UP"
MFA_STEP_UP_FAILED = "MFA_STEP_UP_FAILED"
MFA_RECOVERY_CODE_USED = "MFA_RECOVERY_CODE_USED"
MFA_RECOVERY_CODES_REGENERATED = "MFA_RECOVERY_CODES_REGENERATED"
MFA_DISABLED = "MFA_DISABLED"
REFRESH_REUSE_DETECTED = "REFRESH_REUSE_DETECTED"
REAUTH_REQUIRED = "REAUTH_REQUIRED"
TEMPORARY_ACCESS_ENDED = "TEMPORARY_ACCESS_ENDED"


# ZP-PRIV E01: authentication events that are also security events (the auth
# table stays the detailed record; security_events references it by type).
_SECURITY_EVENT_TYPES = {
    "LOGIN_FAILED": "deny", "MFA_FAILED": "deny", "MFA_STEP_UP_FAILED": "deny", "MFA_VERIFIED": "allow",
    "MFA_STEP_UP": "allow", "MFA_ENROLLED": "allow", "MFA_DISABLED": "allow", "MFA_RECOVERY_CODE_USED": "allow",
    "REFRESH_REUSE_DETECTED": "deny", "REAUTH_REQUIRED": "deny", "TEMPORARY_ACCESS_ENDED": "deny",
    "PASSWORD_RESET": "allow", "LOGIN_SUCCESS": "allow",
}


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
        if event_type in _SECURITY_EVENT_TYPES:
            from app.modules.security import events as security_events

            role = getattr(getattr(user, "role", None), "value", None) or (str(user.role) if user else None)
            security_events.emit(db, event_type, result=_SECURITY_EVENT_TYPES[event_type],
                                 actor_user_id=getattr(user, "id", None), actor_role=role,
                                 organization_id=getattr(user, "organization_id", None),
                                 target_type="account", target_id=f"user:{getattr(user, 'id', None)}",
                                 reason_code=(reason or None) and str(reason)[:60], request=request)
    except Exception:  # noqa: BLE001
        audit_db.rollback()
        logger.exception("[auth-audit] could not record %s", event_type)
        if required:
            raise ZoikoException(503, "AUTH_AUDIT_UNAVAILABLE",
                                 "Sign-in is temporarily unavailable: the audit record could not be written.")
    finally:
        audit_db.close()
