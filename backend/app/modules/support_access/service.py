"""
modules/support_access/service.py
---------------------------------
JIT Support Access lifecycle (ZP-PRIV Part D). Every rule is enforced here,
server-side; the routers only map HTTP to these functions.

Lifecycle
  request (support_operator / super_admin / platform_security)
    -> pending_approval  (lapses to expired_unused after 60 minutes)
    -> tenant org admin approves (scope may be narrowed, never widened;
       field classes chosen; default identifier+contact)
       [+ independent Platform Security approval when the scope includes
        worker-level data - decision 4]
    -> active: a temporary read-only tenant login exists until expires_at
       (5, 15 or 30 minutes - 30 is the hard maximum, decision 6)
    -> ends at the earliest of: time limit, operator exit, tenant revoke,
       Platform Security revoke, the operator logging out. Ending deactivates
       the temporary account immediately, wipes its stored password and
       revokes its sessions.
  break-glass (platform_security only, decision 5): fresh MFA + incident
  reference + acknowledgement; 30 minutes, tenant-wide, identifier+contact,
  read-only, no export; tenant admins emailed at once; a DIFFERENT Platform
  Security officer must review within 24 hours; the opener cannot open
  another until their review is closed.

Times are naive UTC (repo convention); the API serialises them with a "Z".
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import string
import uuid
from datetime import datetime, timedelta
from typing import FrozenSet, Iterable, List, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.core import secretbox
from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException, ZoikoException
from app.modules.support_access import models as M

logger = logging.getLogger("zoiko_payroll.support_access")

PASSWORD_PURPOSE = "support-temp-password"
_PASSWORD_ALPHABETS = (
    "ABCDEFGHJKMNPQRSTUVWXYZ",   # no I, L, O
    "abcdefghjkmnpqrstuvwxyz",   # no i, l, o
    "23456789",                  # no 0, 1
    "!#$%&*+-=?@^_",
)
FIELD_CLASS_CHOICES = ("identifier", "contact", "bank", "tax", "salary", "leave")
DEFAULT_FIELD_CLASSES = ("identifier", "contact")
REQUESTER_ROLES = ("super_admin", "support_operator", "platform_security")

# Audit event types (ZP-PRIV D.4).
EV_REQUESTED = "REQUESTED"
EV_TENANT_APPROVED = "TENANT_APPROVED"
EV_ZOIKO_APPROVED = "ZOIKO_APPROVED"
EV_SCOPE_NARROWED = "SCOPE_NARROWED"
EV_GRANTED = "GRANTED"
EV_DENIED = "DENIED"
EV_CANCELLED = "CANCELLED"
EV_REVOKED = "REVOKED"
EV_EXITED = "EXITED"
EV_EXPIRED = "EXPIRED"
EV_EXPIRED_UNUSED = "EXPIRED_UNUSED"
EV_CREDENTIALS_VIEWED = "CREDENTIALS_VIEWED"
EV_BREAK_GLASS_OPENED = "BREAK_GLASS_OPENED"
EV_BREAK_GLASS_REVIEWED = "BREAK_GLASS_REVIEWED"
EV_BREAK_GLASS_REVIEW_OVERDUE = "BREAK_GLASS_REVIEW_OVERDUE"
EV_TENANT_NOTIFIED = "TENANT_NOTIFIED"
EV_TENANT_NOTIFICATION_FAILED = "TENANT_NOTIFICATION_FAILED"
EV_MFA_STEP_UP_FAILED = "MFA_STEP_UP_FAILED"
EV_REFUSED = "REQUEST_REFUSED"
EV_ACCESS_DENIED_OUT_OF_SCOPE = "ACCESS_DENIED_OUT_OF_SCOPE"
EV_EXPORT_ATTEMPT_DENIED = "EXPORT_ATTEMPT_DENIED"
EV_LEGACY_ASSISTED_RETIRED = "LEGACY_ASSISTED_ACCESS_RETIRED"


def _now() -> datetime:
    return datetime.utcnow()


def _role(user) -> str:
    role = getattr(user, "role", "") or ""
    return role.value if hasattr(role, "value") else str(role)


# ── Audit (append-only, hash-chained) ───────────────────────────────────────

def _canonical(event: M.SupportAccessAuditEvent) -> str:
    return json.dumps({
        "recorded_at": event.recorded_at.isoformat() if event.recorded_at else None,
        "event_type": event.event_type, "grant_id": event.grant_id,
        "organization_id": event.organization_id, "actor_user_id": event.actor_user_id,
        "actor_role": event.actor_role, "support_user_id": event.support_user_id,
        "requested_by_user_id": event.requested_by_user_id, "reason": event.reason,
        "correlation_id": event.correlation_id, "client_address": event.client_address,
        "user_agent": event.user_agent, "detail": event.detail, "prev_hash": event.prev_hash,
    }, sort_keys=True, default=str)


def audit(db: Session, event_type: str, grant: Optional[M.SupportAccessGrant] = None, *,
          actor=None, actor_role: Optional[str] = None, organization_id: Optional[int] = None,
          reason: Optional[str] = None, request=None, detail: Optional[dict] = None,
          commit: bool = True) -> M.SupportAccessAuditEvent:
    """Write one support-access audit row in the caller's transaction. A
    failure propagates: the action it describes does not happen without it."""
    prev = (db.query(M.SupportAccessAuditEvent.row_hash)
            .order_by(M.SupportAccessAuditEvent.id.desc()).first())
    event = M.SupportAccessAuditEvent(
        recorded_at=_now(),
        event_type=event_type,
        grant_id=getattr(grant, "id", None),
        organization_id=organization_id if organization_id is not None else getattr(grant, "organization_id", None),
        actor_user_id=getattr(actor, "id", None),
        actor_role=actor_role or (_role(actor) if actor is not None else "system"),
        support_user_id=getattr(grant, "support_user_id", None),
        requested_by_user_id=getattr(grant, "requested_by_user_id", None),
        reason=(reason or None) and str(reason)[:2000],
        correlation_id=getattr(grant, "correlation_id", None),
        client_address=(getattr(getattr(request, "client", None), "host", None) if request is not None else None),
        user_agent=((request.headers.get("user-agent") or "")[:300] or None) if request is not None else None,
        detail=detail or None,
        prev_hash=prev[0] if prev else None,
    )
    event.row_hash = hashlib.sha256(_canonical(event).encode("utf-8")).hexdigest()
    db.add(event)
    if commit:
        db.commit()
    else:
        db.flush()
    if event_type != "API_CALL":  # API calls are emitted by the PDP as PRIVILEGED_READ
        from app.modules.security import events as security_events

        security_events.emit(
            db, f"SUPPORT_{event_type}"[:60],
            result="deny" if event_type in (EV_DENIED, EV_REFUSED, EV_ACCESS_DENIED_OUT_OF_SCOPE,
                                            EV_EXPORT_ATTEMPT_DENIED, EV_MFA_STEP_UP_FAILED) else "allow",
            actor_user_id=event.actor_user_id, actor_role=event.actor_role,
            on_behalf_of_user_id=event.requested_by_user_id, organization_id=event.organization_id,
            grant_id=event.grant_id, ticket_reference=getattr(grant, "ticket_reference", None),
            target_type="support_grant", target_id=f"grant:{event.grant_id}" if event.grant_id else None,
            reason_code=event_type, request=request, correlation_id=event.correlation_id)
    return event


def verify_audit_chain(db: Session) -> bool:
    """Recompute every row hash and link; False if any row was altered."""
    prev_hash = None
    for event in db.query(M.SupportAccessAuditEvent).order_by(M.SupportAccessAuditEvent.id).all():
        if event.prev_hash != prev_hash:
            return False
        if hashlib.sha256(_canonical(event).encode("utf-8")).hexdigest() != event.row_hash:
            return False
        prev_hash = event.row_hash
    return True


def record_pdp_denial(request, decision, policy, principal) -> None:
    """Called by the PDP for every denial of a temporary support user: the
    tenant sees ACCESS_DENIED_OUT_OF_SCOPE / EXPORT_ATTEMPT_DENIED in its own
    Support Access audit tab. Written on a separate session."""
    db = getattr(request.state, "authz_db", None)
    if db is None:
        return
    event_type = (EV_EXPORT_ATTEMPT_DENIED if decision.reason == "EXPORT_ATTEMPT_DENIED"
                  else EV_ACCESS_DENIED_OUT_OF_SCOPE)
    audit_db = Session(bind=db.get_bind())
    try:
        grant = None
        if principal.support_grant_id:
            grant = audit_db.query(M.SupportAccessGrant).filter(
                M.SupportAccessGrant.id == principal.support_grant_id).first()
        audit(audit_db, event_type, grant, actor_role="support_temp",
              organization_id=principal.organization_id, request=request,
              detail={"method": request.method, "route": policy.path, "action": policy.action,
                      "dataClass": policy.data_class, "reasonCode": decision.reason,
                      "decisionId": decision.decision_id, "supportUserId": principal.user_id})
    finally:
        audit_db.close()


# ── Lookups ─────────────────────────────────────────────────────────────────

def _grant(db: Session, grant_id: int) -> Optional[M.SupportAccessGrant]:
    return db.query(M.SupportAccessGrant).filter(M.SupportAccessGrant.id == grant_id).first()


def _active_org_admins(db: Session, organization_id: int):
    from app.modules.auth.models import User, UserRole

    return (db.query(User)
            .filter(User.organization_id == organization_id, User.role == UserRole.ORG_ADMIN,
                    User.is_active.is_(True), User.is_temporary.is_(False))
            .all())


def _organization(db: Session, organization_id: int):
    from app.modules.organizations.models import Organization

    return db.query(Organization).filter(Organization.id == organization_id).first()


# ── Ending a grant ──────────────────────────────────────────────────────────

def _deactivate_temp_user(db: Session, grant: M.SupportAccessGrant, reason: str) -> None:
    from app.modules.auth.models import User
    from app.modules.auth.service import revoke_user_sessions

    if grant.support_user_id:
        user = db.query(User).filter(User.id == grant.support_user_id).first()
        if user is not None:
            user.is_active = False
            if user.access_expires_at is None or user.access_expires_at > _now():
                user.access_expires_at = _now()
            # The password can never be used again: replace its hash.
            from app.core.security import hash_password

            user.hashed_password = hash_password(secrets.token_urlsafe(32))
        db.flush()
        revoke_user_sessions(db, grant.support_user_id, reason[:40])
    grant.support_password_encrypted = None


def _end(db: Session, grant: M.SupportAccessGrant, status: str, event_type: str, *, actor=None,
         reason: Optional[str] = None, request=None, by_tenant: Optional[bool] = None,
         detail: Optional[dict] = None) -> M.SupportAccessGrant:
    now = _now()
    grant.status = status
    grant.ended_at = now
    if status == M.EXITED:
        grant.exited_at = now
    if status == M.REVOKED:
        grant.revoked_at = now
        grant.revoked_by_user_id = getattr(actor, "id", None)
        grant.revoked_by_tenant = by_tenant
        grant.revoke_reason = reason
    _deactivate_temp_user(db, grant, status.upper())
    audit(db, event_type, grant, actor=actor, reason=reason, request=request, detail=detail, commit=False)
    db.commit()
    db.refresh(grant)
    return grant


def lazy_expire(db: Session, grant: Optional[M.SupportAccessGrant]) -> Optional[M.SupportAccessGrant]:
    """Apply any expiry that is due, on read, so a stale grant never blocks a
    new request and never keeps working between sweeps."""
    if grant is None:
        return None
    now = _now()
    if grant.status == M.PENDING and grant.approval_expires_at and grant.approval_expires_at <= now:
        grant.status = M.EXPIRED_UNUSED
        grant.ended_at = now
        audit(db, EV_EXPIRED_UNUSED, grant, reason="No one approved it within 60 minutes", commit=False)
        db.commit()
    elif grant.status == M.ACTIVE and grant.expires_at and grant.expires_at <= now:
        _end(db, grant, M.EXPIRED, EV_EXPIRED, reason="Time limit reached")
    return grant


def run_sweep(db: Session) -> dict:
    """The minute job: end overdue grants, deactivate any temporary account
    past its window, escalate overdue break-glass reviews."""
    from app.modules.auth.models import User

    now = _now()
    ended = []
    for grant in (db.query(M.SupportAccessGrant)
                  .filter(M.SupportAccessGrant.status.in_(M.LIVE_STATUSES)).all()):
        before = grant.status
        lazy_expire(db, grant)
        if grant.status != before:
            ended.append(grant.id)
    stale = (db.query(User)
             .filter(User.is_temporary.is_(True), User.is_active.is_(True),
                     User.access_expires_at.isnot(None), User.access_expires_at <= now).all())
    for user in stale:
        user.is_active = False
    escalated = []
    for grant in (db.query(M.SupportAccessGrant)
                  .filter(M.SupportAccessGrant.is_break_glass.is_(True),
                          M.SupportAccessGrant.reviewed_at.is_(None),
                          M.SupportAccessGrant.review_due_at <= now,
                          M.SupportAccessGrant.review_escalated_at.is_(None)).all()):
        grant.review_escalated_at = now
        audit(db, EV_BREAK_GLASS_REVIEW_OVERDUE, grant, reason="Post-incident review is overdue",
              commit=False)
        escalated.append(grant.id)
        logger.error("[support-access] BREAK-GLASS REVIEW OVERDUE grant=%s org=%s",
                     grant.id, grant.organization_id)
    db.commit()
    return {"ended": ended, "deactivated_users": [u.id for u in stale], "escalated_reviews": escalated}


def end_grants_on_logout(db: Session, user, request=None) -> None:
    """D.1 step 7: the operator logging out of their admin account ends
    their live grant (a pending request is left to lapse or be cancelled)."""
    if _role(user) not in REQUESTER_ROLES:
        return
    for grant in (db.query(M.SupportAccessGrant)
                  .filter(M.SupportAccessGrant.requested_by_user_id == user.id,
                          M.SupportAccessGrant.status == M.ACTIVE).all()):
        _end(db, grant, M.EXITED, EV_EXITED, actor=user, reason="Operator signed out", request=request)


# ── Request ─────────────────────────────────────────────────────────────────

def allowed_minutes() -> List[int]:
    return [int(x) for x in settings.SUPPORT_ACCESS_ALLOWED_MINUTES.split(",") if x.strip()]


def _refuse(db: Session, actor, organization_id: Optional[int], message: str, request=None,
            status_code: int = 400, code: str = "SUPPORT_ACCESS_REFUSED"):
    audit(db, EV_REFUSED, None, actor=actor, organization_id=organization_id, reason=message, request=request)
    raise ZoikoException(status_code, code, message)


def live_grant_for(db: Session, user_id: int) -> Optional[M.SupportAccessGrant]:
    grant = (db.query(M.SupportAccessGrant)
             .filter(M.SupportAccessGrant.requested_by_user_id == user_id,
                     M.SupportAccessGrant.status.in_(M.LIVE_STATUSES))
             .order_by(M.SupportAccessGrant.id.desc()).first())
    grant = lazy_expire(db, grant)
    if grant is not None and grant.status not in M.LIVE_STATUSES:
        return None
    return grant


# Standard request reasons offered in the Support Access form ("Other" lets
# the operator describe it). Shown to the organization's admins.
REQUEST_REASONS = (
    "Payroll calculation discrepancy",
    "Payslip generation or delivery issue",
    "Statutory filing or tax submission issue",
    "Employee data correction requested by the organization",
    "Bank file or salary payment issue",
    "Sign-in or access issue reported by the organization",
    "Data import or integration failure",
    "Investigating a reported defect",
    "Other",
)


def generate_ticket_reference(db: Session) -> str:
    """ZSA-<UTC date>-<6 random chars>, unique among grants."""
    import secrets
    import string

    alphabet = string.ascii_uppercase + string.digits
    for _ in range(10):
        ref = f"ZSA-{_now():%Y%m%d}-{''.join(secrets.choice(alphabet) for _ in range(6))}"
        if not db.query(M.SupportAccessGrant.id).filter(M.SupportAccessGrant.ticket_reference == ref).first():
            return ref
    raise ZoikoException(503, "TICKET_UNAVAILABLE", "Could not allocate a ticket number; please retry.")


def request_grant(db: Session, actor, *, organization_id: int, reason: str, ticket_reference: Optional[str],
                  minutes: int, scope_type: str, scope_entity_id: Optional[int] = None,
                  scope_pay_group_id: Optional[int] = None,
                  employee_codes: Optional[Iterable[str]] = None, request=None) -> M.SupportAccessGrant:
    from app.modules.organizations.models import LegalEntity, PayGroup

    if _role(actor) not in REQUESTER_ROLES or actor.organization_id is not None:
        raise ForbiddenException("Only platform support roles can request support access.")
    reason = (reason or "").strip()
    ticket_reference = (ticket_reference or "").strip()
    if not reason:
        raise BadRequestException("A reason is required.")
    if not ticket_reference or db.query(M.SupportAccessGrant.id).filter(
            M.SupportAccessGrant.ticket_reference == ticket_reference).first():
        ticket_reference = generate_ticket_reference(db)  # missing or already used
    if minutes not in allowed_minutes() or minutes > settings.SUPPORT_ACCESS_MAX_MINUTES:
        raise BadRequestException(f"Duration must be one of {allowed_minutes()} minutes (30 is the maximum).")
    if scope_type not in M.SCOPE_TYPES:
        raise BadRequestException(f"Scope must be one of {list(M.SCOPE_TYPES)}.")

    org = _organization(db, organization_id)
    if org is None or not org.is_active:
        raise NotFoundException("Organization")
    from app.modules.security import governance

    governance.assert_region(org, "Support access")  # ZP-PRIV F02

    if live_grant_for(db, actor.id) is not None:
        _refuse(db, actor, organization_id,
                "You already have a support access request that is pending or active. "
                "End or cancel it before requesting another.", request=request, status_code=409,
                code="SUPPORT_ACCESS_ALREADY_LIVE")
    if not _active_org_admins(db, organization_id):
        _refuse(db, actor, organization_id,
                "This organization has no active administrator who could approve the request. "
                "For a genuine security emergency, Platform Security can use break-glass access.",
                request=request, status_code=409, code="SUPPORT_ACCESS_NO_APPROVER")

    codes: List[str] = []
    if scope_type == M.SCOPE_ENTITY:
        entity = db.query(LegalEntity).filter(LegalEntity.id == scope_entity_id).first()
        if entity is None or entity.organization_id != organization_id:
            raise BadRequestException("Choose one of the organization's legal entities.")
    elif scope_type == M.SCOPE_PAY_GROUP:
        group = db.query(PayGroup).filter(PayGroup.id == scope_pay_group_id).first()
        if group is None or group.organization_id != organization_id:
            raise BadRequestException("Choose one of the organization's pay groups.")
    elif scope_type == M.SCOPE_EMPLOYEES:
        codes = sorted({(c or "").strip() for c in (employee_codes or []) if (c or "").strip()})
        if not codes:
            raise BadRequestException("Enter at least one employee code from the ticket.")
        if len(codes) > settings.SUPPORT_ACCESS_MAX_EMPLOYEES:
            raise BadRequestException(
                f"At most {settings.SUPPORT_ACCESS_MAX_EMPLOYEES} employee codes per request.")

    now = _now()
    grant = M.SupportAccessGrant(
        organization_id=organization_id,
        requested_by_user_id=actor.id,
        reason=reason,
        ticket_reference=ticket_reference,
        requested_minutes=minutes,
        status=M.PENDING,
        correlation_id=uuid.uuid4().hex,
        scope_type=scope_type,
        scope_entity_id=scope_entity_id if scope_type == M.SCOPE_ENTITY else None,
        scope_pay_group_id=scope_pay_group_id if scope_type == M.SCOPE_PAY_GROUP else None,
        requested_employee_codes=codes or None,
        allowed_field_classes=list(DEFAULT_FIELD_CLASSES),
        requested_at=now,
        approval_expires_at=now + timedelta(minutes=settings.SUPPORT_ACCESS_APPROVAL_WINDOW_MINUTES),
        zoiko_required=scope_type != M.SCOPE_DIAGNOSTICS,
    )
    db.add(grant)
    db.flush()
    audit(db, EV_REQUESTED, grant, actor=actor, reason=reason, request=request,
          detail={"ticket": ticket_reference, "minutes": minutes, "scopeType": scope_type,
                  "employeeCodeCount": len(codes), "zoikoRequired": grant.zoiko_required},
          commit=False)
    db.commit()
    db.refresh(grant)
    _notify_tenant_of_request(db, grant)
    return grant


def temp_session_summary(db: Session, temp_user) -> Optional[dict]:
    """What a temporary support login is for (shown on its own session
    screen): organization, ticket, reason, scope, allowed fields, end time."""
    grant = _grant(db, temp_user.support_grant_id)
    if grant is None:
        return None
    org = _organization(db, grant.organization_id)

    def z(value):
        if value is None:
            return None
        if value.tzinfo is not None:  # Postgres: tz-aware; SQLite: naive UTC
            from datetime import timezone as _tz

            value = value.astimezone(_tz.utc).replace(tzinfo=None)
        return value.replace(microsecond=0).isoformat() + "Z"

    return {
        "grantId": grant.id, "organizationName": getattr(org, "organization_name", None),
        "ticketReference": grant.ticket_reference, "reason": grant.reason, "scope": scope_label(grant),
        "allowedFieldClasses": list(grant.allowed_field_classes or []), "expiresAt": z(grant.expires_at),
        "isBreakGlass": bool(grant.is_break_glass), "status": grant.status,
    }


def scope_label(grant: M.SupportAccessGrant) -> str:
    return {
        M.SCOPE_DIAGNOSTICS: "Diagnostics (organization settings only, no employee records)",
        M.SCOPE_ENTITY: "One legal entity's employee records",
        M.SCOPE_PAY_GROUP: "One pay group's employee records",
        M.SCOPE_EMPLOYEES: f"Up to {len(grant.requested_employee_codes or [])} named employee records",
        M.SCOPE_TENANT: "Emergency: all employees, names and contact details only",
    }.get(grant.scope_type, grant.scope_type)


def _notify_tenant_of_request(db: Session, grant: M.SupportAccessGrant) -> None:
    from app.modules.communications.service import dispatch_email, repeatable_idempotency_key
    from app.services.email_service import send_support_access_request_email

    for admin in _active_org_admins(db, grant.organization_id):
        try:
            dispatch_email(
                "support_access", "support_access.requested", None, admin.email,
                repeatable_idempotency_key(grant.organization_id, "support_access.requested", admin.email,
                                           None, f"support_access:{grant.id}", {"grant": grant.id}),
                send_support_access_request_email, admin.email, grant.id, grant.reason,
                grant.ticket_reference, grant.requested_minutes, scope_label(grant),
                organization_id=grant.organization_id, recipient_user_id=admin.id, db=db,
            )
        except Exception:  # noqa: BLE001 - the request stands; the admin page shows it
            logger.exception("[support-access] request email failed grant=%s admin=%s", grant.id, admin.id)


# ── Operator actions ────────────────────────────────────────────────────────

def _own_grant(db: Session, actor, grant_id: int) -> M.SupportAccessGrant:
    grant = lazy_expire(db, _grant(db, grant_id))
    if grant is None or grant.requested_by_user_id != actor.id:
        raise NotFoundException("Support access request")
    return grant


def cancel(db: Session, actor, grant_id: int, request=None) -> M.SupportAccessGrant:
    grant = _own_grant(db, actor, grant_id)
    if grant.status != M.PENDING:
        raise BadRequestException("Only a pending request can be cancelled.")
    grant.status = M.CANCELLED
    grant.ended_at = _now()
    audit(db, EV_CANCELLED, grant, actor=actor, request=request, commit=False)
    db.commit()
    return grant


def exit_grant(db: Session, actor, grant_id: int, request=None) -> M.SupportAccessGrant:
    grant = _own_grant(db, actor, grant_id)
    if grant.status != M.ACTIVE:
        raise BadRequestException("Only an active session can be ended.")
    return _end(db, grant, M.EXITED, EV_EXITED, actor=actor, reason="Ended by the operator", request=request)


def credentials(db: Session, actor, grant_id: int, request=None) -> dict:
    grant = _own_grant(db, actor, grant_id)
    if grant.status != M.ACTIVE:
        raise NotFoundException("Support access credentials")
    password = secretbox.decrypt(grant.support_password_encrypted, PASSWORD_PURPOSE)
    if password is None:
        raise NotFoundException("Support access credentials")
    audit(db, EV_CREDENTIALS_VIEWED, grant, actor=actor, request=request)
    return {"username": grant.support_username, "password": password, "expiresAt": grant.expires_at}


def my_grants(db: Session, actor, limit: int = 50) -> List[M.SupportAccessGrant]:
    rows = (db.query(M.SupportAccessGrant)
            .filter(M.SupportAccessGrant.requested_by_user_id == actor.id)
            .order_by(M.SupportAccessGrant.id.desc()).limit(limit).all())
    return [lazy_expire(db, g) for g in rows]


# ── Tenant decisions ────────────────────────────────────────────────────────

def _tenant_grant(db: Session, org_admin, grant_id: int) -> M.SupportAccessGrant:
    """Only an org admin of THAT organization; any other org gets 404."""
    grant = lazy_expire(db, _grant(db, grant_id))
    if (grant is None or _role(org_admin) != "org_admin"
            or grant.organization_id != org_admin.organization_id):
        raise NotFoundException("Support access request")
    return grant


def tenant_grants(db: Session, org_admin) -> List[M.SupportAccessGrant]:
    rows = (db.query(M.SupportAccessGrant)
            .filter(M.SupportAccessGrant.organization_id == org_admin.organization_id)
            .order_by(M.SupportAccessGrant.id.desc()).limit(200).all())
    return [lazy_expire(db, g) for g in rows]


def resolve_codes(db: Session, grant: M.SupportAccessGrant) -> dict:
    """Tenant-side only: the requested codes resolved inside the org."""
    from app.modules.payroll.models import PayrollEmployee

    codes = grant.requested_employee_codes or []
    rows = (db.query(PayrollEmployee.id, PayrollEmployee.employee_code, PayrollEmployee.name)
            .filter(PayrollEmployee.organization_id == grant.organization_id,
                    PayrollEmployee.employee_code.in_(codes)).all()) if codes else []
    found = {code: (emp_id, name) for emp_id, code, name in rows}
    return {
        "resolved": [{"employeeId": found[c][0], "employeeCode": c, "name": found[c][1]}
                     for c in codes if c in found],
        "unresolved": [c for c in codes if c not in found],
    }


def approve(db: Session, org_admin, grant_id: int, *, note: Optional[str] = None,
            field_classes: Optional[Iterable[str]] = None,
            employee_ids: Optional[Iterable[int]] = None, request=None) -> M.SupportAccessGrant:
    grant = _tenant_grant(db, org_admin, grant_id)
    if grant.status != M.PENDING:
        raise BadRequestException("This request is no longer waiting for approval.")
    if grant.approved_by_user_id is not None:
        raise BadRequestException("This request is already approved by your organization.")
    if org_admin.id == grant.requested_by_user_id:
        raise ForbiddenException("You cannot approve your own request.")

    classes = list(field_classes) if field_classes is not None else list(DEFAULT_FIELD_CLASSES)
    unknown = [c for c in classes if c not in FIELD_CLASS_CHOICES]
    if unknown or not classes:
        raise BadRequestException(f"Field classes must be chosen from {list(FIELD_CLASS_CHOICES)}.")
    if "identifier" not in classes:
        classes.insert(0, "identifier")  # records cannot be told apart without it

    narrowed = False
    if grant.scope_type == M.SCOPE_EMPLOYEES:
        resolved = {r["employeeId"] for r in resolve_codes(db, grant)["resolved"]}
        chosen = set(int(e) for e in employee_ids) if employee_ids is not None else set(resolved)
        if not chosen <= resolved:
            raise BadRequestException("You can narrow the requested employees but never add others.")
        if not chosen:
            raise BadRequestException("Select at least one employee, or decline the request.")
        narrowed = chosen != resolved
        for emp_id in sorted(chosen):
            db.add(M.SupportGrantEmployee(grant_id=grant.id, employee_id=emp_id))

    grant.approved_by_user_id = org_admin.id
    grant.approved_at = _now()
    grant.approval_note = (note or "").strip() or None
    grant.allowed_field_classes = classes
    grant.scope_narrowed = narrowed
    audit(db, EV_TENANT_APPROVED, grant, actor=org_admin, reason=grant.approval_note, request=request,
          detail={"fieldClasses": classes}, commit=False)
    if narrowed:
        audit(db, EV_SCOPE_NARROWED, grant, actor=org_admin, request=request, commit=False)
    db.commit()
    return _maybe_activate(db, grant, request=request)


def deny(db: Session, org_admin, grant_id: int, reason: str, request=None) -> M.SupportAccessGrant:
    grant = _tenant_grant(db, org_admin, grant_id)
    reason = (reason or "").strip()
    if not reason:
        raise BadRequestException("A reason is required to decline; it is shown to the requester.")
    if grant.status != M.PENDING:
        raise BadRequestException("This request is no longer waiting for approval.")
    grant.status = M.DENIED
    grant.declined_by_user_id = org_admin.id
    grant.decline_reason = reason
    grant.ended_at = _now()
    audit(db, EV_DENIED, grant, actor=org_admin, reason=reason, request=request, commit=False)
    db.commit()
    return grant


def tenant_revoke(db: Session, org_admin, grant_id: int, reason: str, request=None) -> M.SupportAccessGrant:
    grant = _tenant_grant(db, org_admin, grant_id)
    reason = (reason or "").strip()
    if not reason:
        raise BadRequestException("A reason is required to revoke access.")
    if grant.status != M.ACTIVE:
        raise BadRequestException("Only active access can be revoked.")
    return _end(db, grant, M.REVOKED, EV_REVOKED, actor=org_admin, reason=reason, request=request,
                by_tenant=True)


def tenant_audit(db: Session, org_admin, limit: int = 500) -> List[M.SupportAccessAuditEvent]:
    return (db.query(M.SupportAccessAuditEvent)
            .filter(M.SupportAccessAuditEvent.organization_id == org_admin.organization_id)
            .order_by(M.SupportAccessAuditEvent.id.desc()).limit(limit).all())


# ── Platform Security ───────────────────────────────────────────────────────

def _security_grant(db: Session, grant_id: int) -> M.SupportAccessGrant:
    grant = lazy_expire(db, _grant(db, grant_id))
    if grant is None:
        raise NotFoundException("Support access request")
    return grant


def approvals_queue(db: Session) -> List[M.SupportAccessGrant]:
    rows = (db.query(M.SupportAccessGrant)
            .filter(M.SupportAccessGrant.status == M.PENDING,
                    M.SupportAccessGrant.zoiko_required.is_(True),
                    M.SupportAccessGrant.zoiko_approved_by_user_id.is_(None))
            .order_by(M.SupportAccessGrant.id).all())
    return [g for g in (lazy_expire(db, r) for r in rows) if g.status == M.PENDING]


def zoiko_approve(db: Session, officer, grant_id: int, request=None) -> M.SupportAccessGrant:
    grant = _security_grant(db, grant_id)
    if grant.status != M.PENDING:
        raise BadRequestException("This request is no longer waiting for approval.")
    if not grant.zoiko_required:
        raise BadRequestException("This request does not need a Zoiko approval.")
    if grant.zoiko_approved_by_user_id is not None:
        raise BadRequestException("This request already has its Zoiko approval.")
    if officer.id == grant.requested_by_user_id:
        raise ForbiddenException("You cannot approve your own request.")
    grant.zoiko_approved_by_user_id = officer.id
    grant.zoiko_approved_at = _now()
    audit(db, EV_ZOIKO_APPROVED, grant, actor=officer, request=request, commit=False)
    db.commit()
    return _maybe_activate(db, grant, request=request)


def live_sessions(db: Session) -> List[M.SupportAccessGrant]:
    rows = (db.query(M.SupportAccessGrant)
            .filter(M.SupportAccessGrant.status.in_(M.LIVE_STATUSES))
            .order_by(M.SupportAccessGrant.id.desc()).all())
    return [g for g in (lazy_expire(db, r) for r in rows) if g.status in M.LIVE_STATUSES]


def security_revoke(db: Session, officer, grant_id: int, reason: str, request=None) -> M.SupportAccessGrant:
    grant = _security_grant(db, grant_id)
    reason = (reason or "").strip()
    if not reason:
        raise BadRequestException("A reason is required to revoke access.")
    if grant.status == M.PENDING:
        grant.status = M.REVOKED
        grant.revoked_at = grant.ended_at = _now()
        grant.revoked_by_user_id = officer.id
        grant.revoked_by_tenant = False
        grant.revoke_reason = reason
        audit(db, EV_REVOKED, grant, actor=officer, reason=reason, request=request, commit=False)
        db.commit()
        return grant
    if grant.status != M.ACTIVE:
        raise BadRequestException("Only pending or active access can be revoked.")
    return _end(db, grant, M.REVOKED, EV_REVOKED, actor=officer, reason=reason, request=request,
                by_tenant=False)


def open_break_glass(db: Session, officer, *, organization_id: int, incident_reference: str, reason: str,
                     acknowledged: bool, request=None) -> M.SupportAccessGrant:
    """Caller has already verified a FRESH MFA code (route)."""
    if _role(officer) != "platform_security":
        raise ForbiddenException("Only Platform Security can open break-glass access.")
    incident_reference = (incident_reference or "").strip()
    reason = (reason or "").strip()
    if not incident_reference or not reason:
        raise BadRequestException("An incident reference and a reason are required.")
    if not acknowledged:
        raise BadRequestException("Confirm that you understand this access will be reviewed.")
    org = _organization(db, organization_id)
    if org is None or not org.is_active:
        raise NotFoundException("Organization")
    from app.modules.security import governance

    governance.assert_region(org, "Emergency access")  # ZP-PRIV F02
    open_review = (db.query(M.SupportAccessGrant)
                   .filter(M.SupportAccessGrant.requested_by_user_id == officer.id,
                           M.SupportAccessGrant.is_break_glass.is_(True),
                           M.SupportAccessGrant.reviewed_at.is_(None)).first())
    if open_review is not None:
        _refuse(db, officer, organization_id,
                "Your previous break-glass access has not been reviewed yet. "
                "Another Platform Security officer must close that review first.",
                request=request, status_code=409, code="BREAK_GLASS_REVIEW_PENDING")
    if live_grant_for(db, officer.id) is not None:
        _refuse(db, officer, organization_id,
                "You already have a support access request that is pending or active.",
                request=request, status_code=409, code="SUPPORT_ACCESS_ALREADY_LIVE")

    now = _now()
    minutes = settings.SUPPORT_ACCESS_BREAK_GLASS_MINUTES
    grant = M.SupportAccessGrant(
        organization_id=organization_id, requested_by_user_id=officer.id, reason=reason,
        ticket_reference=incident_reference, incident_reference=incident_reference,
        requested_minutes=minutes, status=M.PENDING, correlation_id=uuid.uuid4().hex,
        scope_type=M.SCOPE_TENANT, allowed_field_classes=list(DEFAULT_FIELD_CLASSES),
        requested_at=now, is_break_glass=True, zoiko_required=False,
        review_due_at=now + timedelta(hours=settings.SUPPORT_ACCESS_BREAK_GLASS_REVIEW_HOURS),
    )
    db.add(grant)
    db.flush()
    audit(db, EV_BREAK_GLASS_OPENED, grant, actor=officer, reason=reason, request=request,
          detail={"incident": incident_reference, "minutes": minutes, "severity": "high"}, commit=False)
    db.commit()
    _activate(db, grant, request=request)
    _notify_tenant_of_break_glass(db, grant)
    logger.error("[support-access] BREAK-GLASS OPENED grant=%s org=%s officer=%s incident=%s",
                 grant.id, organization_id, officer.id, incident_reference)
    return grant


def _notify_tenant_of_break_glass(db: Session, grant: M.SupportAccessGrant) -> None:
    from app.modules.communications.service import dispatch_email, repeatable_idempotency_key
    from app.services.email_service import send_support_access_break_glass_email

    admins = _active_org_admins(db, grant.organization_id)
    delivered = 0
    for admin in admins:
        try:
            ok = dispatch_email(
                "support_access", "support_access.break_glass", None, admin.email,
                repeatable_idempotency_key(grant.organization_id, "support_access.break_glass", admin.email,
                                           None, f"support_access:{grant.id}", {"grant": grant.id}),
                send_support_access_break_glass_email, admin.email, grant.id, grant.incident_reference,
                grant.reason, grant.activated_at.strftime("%Y-%m-%d %H:%M"),
                grant.expires_at.strftime("%Y-%m-%d %H:%M"),
                organization_id=grant.organization_id, recipient_user_id=admin.id, db=db,
            )
        except Exception:  # noqa: BLE001
            logger.exception("[support-access] break-glass email failed grant=%s admin=%s", grant.id, admin.id)
            ok = False
        delivered += 1 if ok else 0
    event = EV_TENANT_NOTIFIED if admins and delivered == len(admins) else EV_TENANT_NOTIFICATION_FAILED
    audit(db, event, grant, detail={"recipients": len(admins), "delivered": delivered})


def pending_reviews(db: Session) -> List[M.SupportAccessGrant]:
    return (db.query(M.SupportAccessGrant)
            .filter(M.SupportAccessGrant.is_break_glass.is_(True), M.SupportAccessGrant.reviewed_at.is_(None))
            .order_by(M.SupportAccessGrant.review_due_at).all())


def review_break_glass(db: Session, officer, grant_id: int, outcome: str, findings: str,
                       request=None) -> M.SupportAccessGrant:
    grant = _security_grant(db, grant_id)
    if not grant.is_break_glass:
        raise NotFoundException("Break-glass access")
    if grant.reviewed_at is not None:
        raise BadRequestException("This break-glass access has already been reviewed.")
    if officer.id == grant.requested_by_user_id:
        raise ForbiddenException("A different Platform Security officer must review this access.")
    if outcome not in (M.REVIEW_JUSTIFIED, M.REVIEW_NOT_JUSTIFIED):
        raise BadRequestException("Outcome must be 'justified' or 'not_justified'.")
    findings = (findings or "").strip()
    if not findings:
        raise BadRequestException("Findings are required.")
    grant.reviewed_by_user_id = officer.id
    grant.reviewed_at = _now()
    grant.review_outcome = outcome
    grant.review_note = findings
    audit(db, EV_BREAK_GLASS_REVIEWED, grant, actor=officer, reason=findings, request=request,
          detail={"outcome": outcome}, commit=False)
    db.commit()
    return grant


# ── Activation + temporary credentials ──────────────────────────────────────

def _maybe_activate(db: Session, grant: M.SupportAccessGrant, request=None) -> M.SupportAccessGrant:
    if grant.status != M.PENDING or grant.approved_by_user_id is None:
        return grant
    if grant.zoiko_required and grant.zoiko_approved_by_user_id is None:
        return grant
    _activate(db, grant, request=request)
    _notify_operator_ready(db, grant)
    return grant


def generate_password(length: int = 16) -> str:
    """16 characters, at least one of each class, no look-alike characters."""
    chars = [secrets.choice(alphabet) for alphabet in _PASSWORD_ALPHABETS]
    pool = "".join(_PASSWORD_ALPHABETS)
    chars += [secrets.choice(pool) for _ in range(length - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def _username(grant_id: int) -> str:
    suffix = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6))
    return f"support-{grant_id}-{suffix}@{settings.SUPPORT_ACCESS_LOGIN_DOMAIN}"


def _activate(db: Session, grant: M.SupportAccessGrant, request=None) -> None:
    from app.core.security import hash_password
    from app.modules.auth.models import User, UserRole

    now = _now()
    minutes = min(grant.requested_minutes, settings.SUPPORT_ACCESS_MAX_MINUTES)
    password = generate_password()
    user = User(
        email=_username(grant.id), hashed_password=hash_password(password), role=UserRole.SUPPORT_TEMP,
        organization_id=grant.organization_id, first_name="Platform", last_name="Support",
        is_active=True, is_verified=True, is_temporary=True, support_grant_id=grant.id,
        access_expires_at=now + timedelta(minutes=minutes),
    )
    db.add(user)
    db.flush()
    grant.status = M.ACTIVE
    grant.activated_at = now
    grant.expires_at = now + timedelta(minutes=minutes)
    grant.support_user_id = user.id
    grant.support_username = user.email
    grant.support_password_encrypted = secretbox.encrypt(password, PASSWORD_PURPOSE)
    audit(db, EV_GRANTED, grant, reason=f"{minutes} minutes", request=request,
          detail={"expiresAt": grant.expires_at.isoformat() + "Z", "fieldClasses": grant.allowed_field_classes},
          commit=False)
    db.commit()
    db.refresh(grant)


def _notify_operator_ready(db: Session, grant: M.SupportAccessGrant) -> None:
    from app.modules.auth.models import User
    from app.modules.communications.service import dispatch_email, repeatable_idempotency_key
    from app.services.email_service import send_support_access_ready_email

    operator = db.query(User).filter(User.id == grant.requested_by_user_id).first()
    org = _organization(db, grant.organization_id)
    if operator is None:
        return
    try:
        dispatch_email(
            "support_access", "support_access.ready", None, operator.email,
            repeatable_idempotency_key(None, "support_access.ready", operator.email, None,
                                       f"support_access:{grant.id}", {"grant": grant.id}),
            send_support_access_ready_email, operator.email, grant.id,
            getattr(org, "organization_name", ""), recipient_user_id=operator.id, db=db,
        )
    except Exception:  # noqa: BLE001
        logger.exception("[support-access] ready email failed grant=%s", grant.id)


# ── Runtime scope (read by the PDP on every request) ────────────────────────

def live_grant_for_principal(db: Session, principal) -> Optional[M.SupportAccessGrant]:
    """The temporary user's grant if, and only if, it is live right now and
    bound to the same organization."""
    if not getattr(principal, "support_grant_id", None):
        return None
    grant = lazy_expire(db, _grant(db, principal.support_grant_id))
    if (grant is None or grant.status != M.ACTIVE or grant.expires_at is None
            or grant.expires_at <= _now() or grant.organization_id != principal.organization_id
            or grant.support_user_id != principal.user_id):
        return None
    return grant


def grant_employee_scope(db: Session, principal) -> FrozenSet[int]:
    """The worker ids a temporary support user may read (re-read live)."""
    from app.core.authz.scopes import employees_in_units

    grant = live_grant_for_principal(db, principal)
    if grant is None:
        return frozenset()
    if grant.scope_type == M.SCOPE_TENANT and grant.is_break_glass:
        from app.modules.payroll.models import PayrollEmployee

        return frozenset(r[0] for r in db.query(PayrollEmployee.id)
                         .filter(PayrollEmployee.organization_id == grant.organization_id).all())
    if grant.scope_type == M.SCOPE_ENTITY:
        return employees_in_units(db, grant.organization_id, {grant.scope_entity_id}, set())
    if grant.scope_type == M.SCOPE_PAY_GROUP:
        return employees_in_units(db, grant.organization_id, set(), {grant.scope_pay_group_id})
    if grant.scope_type == M.SCOPE_EMPLOYEES:
        return frozenset(r[0] for r in db.query(M.SupportGrantEmployee.employee_id)
                         .filter(M.SupportGrantEmployee.grant_id == grant.id).all())
    return frozenset()  # diagnostics: no worker rows at all


def allowed_field_classes(db: Session, principal) -> FrozenSet[str]:
    grant = live_grant_for_principal(db, principal)
    if grant is None:
        return frozenset()
    return frozenset(grant.allowed_field_classes or DEFAULT_FIELD_CLASSES)


# ── Legacy assisted access retirement ───────────────────────────────────────

def retire_legacy_assisted_sessions(db: Session) -> int:
    """End any assisted-access session still pending or live (deploy step and
    startup safety net): legacy tokens must not outlive the old flow."""
    from app.modules.assisted_access.models import AssistedAccessSession

    now = _now()
    rows = (db.query(AssistedAccessSession)
            .filter(AssistedAccessSession.ended_at.is_(None)).all())
    for row in rows:
        row.ended_at = now
        row.ended_reason = "REQUEST_EXPIRED" if row.approval_status == "PENDING" else "MANUAL_END"
        if row.approval_status == "PENDING":
            row.approval_status = "EXPIRED"
    if rows:
        audit(db, EV_LEGACY_ASSISTED_RETIRED, None, reason="Assisted Access replaced by JIT Support Access",
              detail={"sessions": len(rows)}, commit=False)
    db.commit()
    return len(rows)
