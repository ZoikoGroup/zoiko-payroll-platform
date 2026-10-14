"""
modules/assisted_access/service.py
-----------------------------------
Session lifecycle logic for Assisted Access ("SafeGuard"): create a
time-boxed session + narrowly-scoped token, end it manually, end everything
past its hard cap. Every transition writes an AssistedAccessAuditEvent so
the full lifecycle is visible in Security & Audit with source
"assisted_access".

Deliberate boundaries (the spec is safety-critical here):
  - reason is required; blank reason raises ValueError → 422 at the API.
  - expires_at is set once at activation and never extended in place.
  - the acting principal on every request is the requesting Super Admin
    (requested_by_user_id), never the org admin's identity.

Consent / break-glass (launch readiness G5, F-3 / F-7):
  - CONSENT (default): a Super Admin REQUESTS access; an org admin of THAT
    organisation approves or rejects (reason required to reject). Only then
    can the requester ACTIVATE it and receive a token. The request lapses if
    not approved and activated within ASSISTED_ACCESS_APPROVAL_WINDOW_MINUTES.
  - BREAK_GLASS (emergency): mandatory reason; a DIFFERENT Super Admin must
    approve (never the requester); the tenant's org admins are notified at
    once; the session lasts ASSISTED_ACCESS_BREAK_GLASS_MINUTES.
  - Every refusal (wrong approver, self-approval, expired window, wrong
    state) writes an ASSISTED_ACCESS_REFUSED audit event before raising.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import create_access_token, ASSISTED_ACCESS_TOKEN_TYPE

logger = logging.getLogger("zoiko_payroll.assisted_access")


def _now() -> datetime:
    # Sessions carry naive-UTC timestamps (Column DateTime default
    # datetime.utcnow) — keep every comparison on the same basis.
    return datetime.utcnow()


def _audit(db: Session, session, actor_user_id, event_type: str, method=None, path=None, status_code=None, payload=None):
    from app.modules.assisted_access.models import AssistedAccessAuditEvent

    db.add(AssistedAccessAuditEvent(
        assisted_access_session_id=session.id,
        organization_id=session.organization_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        method=method,
        path=path,
        status_code=status_code,
        payload=payload,
    ))


class AssistedAccessRefused(Exception):
    """A refused lifecycle step; already audited when raised. Maps to 403."""


MODES = ("CONSENT", "BREAK_GLASS")


def _refuse(db: Session, session, actor_user_id, attempted: str, message: str):
    _audit(db, session, actor_user_id, "ASSISTED_ACCESS_REFUSED",
           payload={"attempted": attempted, "reason": message, "approval_status": session.approval_status})
    db.commit()
    logger.info("[assisted-access] REFUSED session=%s attempted=%s by=%s: %s",
                session.id, attempted, actor_user_id, message)
    raise AssistedAccessRefused(message)


def _lapse_if_window_passed(db: Session, session, actor_user_id, attempted: str):
    if session.request_expires_at is not None and session.request_expires_at <= _now() \
            and session.activated_at is None and session.approval_status in ("PENDING", "APPROVED"):
        session.approval_status = "EXPIRED"
        session.ended_at, session.ended_reason = _now(), "REQUEST_EXPIRED"
        _audit(db, session, actor_user_id, "ASSISTED_ACCESS_REQUEST_EXPIRED",
               payload={"request_expires_at": session.request_expires_at.isoformat()})
        db.commit()
        _refuse(db, session, actor_user_id, attempted, "The approval window for this request has passed — request again.")


def request_assisted_access(db: Session, *, organization_id: int, requested_by, reason: str,
                            mode: str = "CONSENT", duration_minutes=None):
    """A Super Admin asks for access. No token exists until the request is
    approved (by the tenant, or for BREAK_GLASS by a second Super Admin) and
    then activated by the requester."""
    from app.modules.assisted_access.models import AssistedAccessSession
    from app.modules.organizations.models import Organization

    reason = (reason or "").strip()
    if not reason:
        raise ValueError("a non-empty reason is required to request assisted access")
    mode = (mode or "CONSENT").upper()
    if mode not in MODES:
        raise ValueError(f"mode must be one of {list(MODES)}")
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if org is None:
        raise ValueError("organization not found")
    cap = settings.ASSISTED_ACCESS_BREAK_GLASS_MINUTES if mode == "BREAK_GLASS" else settings.ASSISTED_ACCESS_SESSION_MINUTES
    minutes = max(1, min(int(duration_minutes or cap), int(cap)))
    now = _now()
    session = AssistedAccessSession(
        organization_id=org.id, requested_by_user_id=requested_by.id, reason=reason,
        started_at=now, expires_at=now,                    # not usable until activated
        access_mode=mode, approval_status="PENDING", requested_minutes=minutes,
        request_expires_at=now + timedelta(minutes=int(settings.ASSISTED_ACCESS_APPROVAL_WINDOW_MINUTES)),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    _audit(db, session, requested_by.id, "ASSISTED_ACCESS_REQUESTED",
           payload={"mode": mode, "reason": reason, "requested_minutes": minutes,
                    "request_expires_at": session.request_expires_at.isoformat()})
    db.commit()
    logger.info("[assisted-access] REQUESTED session=%s org=%s mode=%s by=%s", session.id, org.id, mode, requested_by.id)
    return session


def _org_admins(db: Session, organization_id: int) -> list:
    from app.modules.auth.models import User, UserRole

    return (db.query(User).filter(User.organization_id == organization_id, User.role == UserRole.ORG_ADMIN,
                                  User.is_active.is_(True)).all())


def approve_assisted_access(db: Session, session, *, approver, decision_reason: str = None):
    """CONSENT: an active org admin of the session's organisation. BREAK_GLASS:
    a Super Admin other than the requester. Anyone else is refused (audited)."""
    from app.modules.auth.models import UserRole

    role = getattr(approver, "role", None)
    role = getattr(role, "value", role)
    if session.approval_status != "PENDING":
        _refuse(db, session, approver.id, "approve", f"This request is {session.approval_status}, not PENDING.")
    _lapse_if_window_passed(db, session, approver.id, "approve")
    if session.access_mode == "CONSENT":
        if role != UserRole.ORG_ADMIN.value or approver.organization_id != session.organization_id \
                or not getattr(approver, "is_active", False):
            _refuse(db, session, approver.id, "approve",
                    "Only an organisation admin of the organisation being accessed can approve this request.")
    else:
        if role != UserRole.SUPER_ADMIN.value or approver.organization_id is not None:
            _refuse(db, session, approver.id, "approve", "Break-glass access is approved by a second Super Admin.")
        if approver.id == session.requested_by_user_id:
            _refuse(db, session, approver.id, "approve", "Break-glass access cannot be approved by its requester.")
    session.approval_status, session.approved_by_user_id, session.approved_at = "APPROVED", approver.id, _now()
    session.decision_reason = (decision_reason or "").strip() or None
    _audit(db, session, approver.id, "ASSISTED_ACCESS_APPROVED",
           payload={"mode": session.access_mode, "approved_by": approver.id, "decision_reason": session.decision_reason})
    db.commit()
    if session.access_mode == "BREAK_GLASS":
        activate_assisted_access(db, session, requested_by=None, _break_glass_grant=True)
    return session


def reject_assisted_access(db: Session, session, *, actor, reason: str):
    """CONSENT only: an org admin of the organisation declines (reason required)."""
    from app.modules.auth.models import UserRole

    role = getattr(actor, "role", None)
    role = getattr(role, "value", role)
    if session.approval_status != "PENDING":
        _refuse(db, session, actor.id, "reject", f"This request is {session.approval_status}, not PENDING.")
    if session.access_mode != "CONSENT" or role != UserRole.ORG_ADMIN.value \
            or actor.organization_id != session.organization_id:
        _refuse(db, session, actor.id, "reject",
                "Only an organisation admin of the organisation being accessed can reject this request.")
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("a rejection needs a reason")
    session.approval_status, session.decision_reason = "REJECTED", reason
    session.approved_by_user_id, session.approved_at = actor.id, _now()
    session.ended_at, session.ended_reason = _now(), "REJECTED"
    _audit(db, session, actor.id, "ASSISTED_ACCESS_REJECTED", payload={"reason": reason})
    db.commit()
    return session


def _notify_tenant_break_glass(db: Session, session) -> dict:
    """Immediate notice to every active org admin, sent synchronously through
    the audited email path (dispatch_email returns whether it was delivered).
    Only full delivery to at least one admin counts as notified: otherwise the
    session stays active and auditable, an ASSISTED_ACCESS_TENANT_NOTIFICATION_FAILED
    event is written, tenant_notified_at stays empty, and the Super Admin
    Alerts feed shows a high-severity security alert until someone handles it."""
    from app.modules.communications.service import dispatch_email, repeatable_idempotency_key
    from app.services.email_service import send_break_glass_access_notice_email

    admins = _org_admins(db, session.organization_id)
    delivered, failed = [], []
    for admin in admins:
        try:
            ok = dispatch_email(
                "assisted_access", "assisted_access.break_glass", None, admin.email,
                repeatable_idempotency_key(session.organization_id, "assisted_access.break_glass", admin.email,
                                           None, f"assisted_access:{session.id}", {"session": session.id}),
                send_break_glass_access_notice_email, admin.email, session.id, session.reason,
                session.started_at.strftime("%Y-%m-%d %H:%M"), session.expires_at.strftime("%Y-%m-%d %H:%M"),
                organization_id=session.organization_id, actor_user_id=session.approved_by_user_id,
                recipient_user_id=admin.id, db=db,
            )
        except Exception as exc:  # noqa: BLE001 — recorded below, never silently ignored
            logger.exception("[assisted-access] break-glass notice raised session=%s admin=%s", session.id, admin.id)
            ok, err = False, f"{type(exc).__name__}: {exc}"[:200]
        else:
            err = None if ok else "not delivered (see communication_events)"
        (delivered if ok else failed).append({"userId": admin.id, **({"error": err} if err else {})})
    if admins and not failed:
        session.tenant_notified_at = _now()
        _audit(db, session, session.approved_by_user_id, "ASSISTED_ACCESS_TENANT_NOTIFIED",
               payload={"recipients": len(delivered), "channel": "email + in-app banner"})
    else:
        reason = "the organisation has no active org admin to notify" if not admins else "email delivery failed"
        _audit(db, session, session.approved_by_user_id, "ASSISTED_ACCESS_TENANT_NOTIFICATION_FAILED",
               payload={"reason": reason, "recipients": len(admins), "delivered": delivered, "failed": failed,
                        "followUp": "notify the tenant manually and record it (runbook #22)"})
        logger.error("[assisted-access] BREAK-GLASS TENANT NOTIFICATION FAILED session=%s org=%s: %s",
                     session.id, session.organization_id, reason)
    db.commit()
    return {"recipients": len(admins), "delivered": len(delivered), "failed": failed}


def break_glass_notification_alerts(db: Session, days: int = 7) -> list:
    """Break-glass sessions started in the last `days` days whose tenant was
    never confirmed notified — fed into the Super Admin Alerts page."""
    from app.modules.assisted_access.models import AssistedAccessSession
    from app.modules.organizations.models import Organization

    since = _now() - timedelta(days=days)
    rows = (db.query(AssistedAccessSession, Organization.organization_name)
            .join(Organization, Organization.id == AssistedAccessSession.organization_id)
            .filter(AssistedAccessSession.access_mode == "BREAK_GLASS",
                    AssistedAccessSession.activated_at.isnot(None),
                    AssistedAccessSession.activated_at >= since,
                    AssistedAccessSession.tenant_notified_at.is_(None))
            .order_by(AssistedAccessSession.activated_at.desc()).all())
    return [{"session_id": s.id, "organization_name": name, "activated_at": s.activated_at} for s, name in rows]


def activate_assisted_access(db: Session, session, *, requested_by, _break_glass_grant: bool = False):
    """Start the approved session and issue its token. CONSENT: only the
    requester, inside the approval window. BREAK_GLASS: started at approval
    (the tenant is notified at the same moment). Returns (session, token)."""
    from app.modules.auth.models import User

    actor_id = getattr(requested_by, "id", None)
    if not _break_glass_grant:
        if session.approval_status != "APPROVED" or session.activated_at is not None:
            _refuse(db, session, actor_id, "activate",
                    f"This request is {session.approval_status}" + (" and already active." if session.activated_at else "."))
        if actor_id != session.requested_by_user_id:
            _refuse(db, session, actor_id, "activate", "Only the Super Admin who requested access can activate it.")
        _lapse_if_window_passed(db, session, actor_id, "activate")
    sa = db.query(User).filter(User.id == session.requested_by_user_id).first()
    now = _now()
    session.started_at, session.activated_at = now, now
    session.expires_at = now + timedelta(minutes=int(session.requested_minutes or settings.ASSISTED_ACCESS_SESSION_MINUTES))
    db.commit()
    token = create_access_token(
        {"sub": sa.email, "user_id": sa.id, "role": sa.role.value, "organization_id": session.organization_id,
         "assisted_access_session_id": session.id},
        expires_delta=session.expires_at - session.started_at, token_type=ASSISTED_ACCESS_TOKEN_TYPE,
    )
    _audit(db, session, session.requested_by_user_id, "ASSISTED_ACCESS_STARTED",
           payload={"mode": session.access_mode, "reason": session.reason, "started_at": now.isoformat(),
                    "expires_at": session.expires_at.isoformat(),
                    "duration_minutes": int((session.expires_at - now).total_seconds() // 60),
                    "approved_by": session.approved_by_user_id})
    db.commit()
    if session.access_mode == "BREAK_GLASS":
        _notify_tenant_break_glass(db, session)
    session._issued_token = token
    logger.info("[assisted-access] STARTED session=%s org=%s mode=%s expires=%s",
                session.id, session.organization_id, session.access_mode, session.expires_at.isoformat())
    return session, token


def end_assisted_access(db: Session, session, *, ended_reason: str = "MANUAL_END", actor_user_id=None):
    """Manually end a session. Idempotent — a session can only end once."""
    if session.ended_at is not None:
        return session

    session.ended_at = _now()
    session.ended_reason = ended_reason
    _audit(
        db, session, actor_user_id, "ASSISTED_ACCESS_ENDED",
        payload={"ended_reason": ended_reason, "ended_at": session.ended_at.isoformat()},
    )
    db.commit()
    logger.info(
        "[assisted-access] ENDED session=%s org=%s reason=%s",
        session.id, session.organization_id, ended_reason,
    )
    return session


def run_expiry_sweep(db: Session) -> dict:
    """Auto-end every session past its expires_at — the hard cap cannot be
    talked around by forgetting to end a session manually. Pattern mirrors
    run_dunning_sweep (billing/dunning.py): iterate matches in one session,
    commit per row so one failure can't corrupt the rest."""
    from app.modules.assisted_access.models import AssistedAccessSession

    now = _now()
    lapsed = (
        db.query(AssistedAccessSession)
        .filter(
            AssistedAccessSession.ended_at.is_(None),
            AssistedAccessSession.activated_at.is_(None),
            AssistedAccessSession.approval_status.in_(("PENDING", "APPROVED")),
            AssistedAccessSession.request_expires_at.isnot(None),
            AssistedAccessSession.request_expires_at <= now,
        )
        .all()
    )
    for session in lapsed:
        session.approval_status = "EXPIRED"
        session.ended_at, session.ended_reason = now, "REQUEST_EXPIRED"
        _audit(db, session, session.requested_by_user_id, "ASSISTED_ACCESS_REQUEST_EXPIRED",
               payload={"request_expires_at": session.request_expires_at.isoformat()})
        db.commit()
    expired = (
        db.query(AssistedAccessSession)
        .filter(
            AssistedAccessSession.ended_at.is_(None),
            AssistedAccessSession.approval_status == "APPROVED",
            # an approved request that was never activated is not a session yet
            (AssistedAccessSession.activated_at.isnot(None)) | (AssistedAccessSession.request_expires_at.is_(None)),
            AssistedAccessSession.expires_at <= now,
        )
        .all()
    )
    ended = []
    for session in expired:
        try:
            session.ended_at = now
            session.ended_reason = "EXPIRED"
            _audit(
                db, session, session.requested_by_user_id, "ASSISTED_ACCESS_EXPIRED",
                payload={"expired_at": now.isoformat(), "expires_at": session.expires_at.isoformat()},
            )
            db.add(session)
            db.commit()
            ended.append({"session_id": session.id, "organization_id": session.organization_id})
            logger.info(
                "[assisted-access] EXPIRED session=%s org=%s (past expires_at=%s)",
                session.id, session.organization_id, session.expires_at.isoformat(),
            )
        except Exception:  # noqa: BLE001
            logger.exception("[assisted-access] sweep failed for session=%s", session.id)
            db.rollback()
    return {"scanned": len(expired) + len(lapsed), "ended": ended,
            "requestsExpired": [x.id for x in lapsed]}


def get_active_sessions_for_org(db: Session, organization_id: int) -> list:
    from app.modules.assisted_access.models import AssistedAccessSession

    return (
        db.query(AssistedAccessSession)
        .filter(
            AssistedAccessSession.organization_id == organization_id,
            AssistedAccessSession.approval_status == "APPROVED",
            AssistedAccessSession.ended_at.is_(None),
            AssistedAccessSession.expires_at > _now(),
        )
        .order_by(AssistedAccessSession.started_at.desc())
        .all()
    )


def get_active_sessions_all(db: Session) -> list:
    from app.modules.assisted_access.models import AssistedAccessSession

    return (
        db.query(AssistedAccessSession)
        .filter(
            AssistedAccessSession.approval_status == "APPROVED",
            AssistedAccessSession.ended_at.is_(None),
            AssistedAccessSession.expires_at > _now(),
        )
        .order_by(AssistedAccessSession.started_at.desc())
        .all()
    )

def pending_requests_for_org(db: Session, organization_id: int) -> list:
    from app.modules.assisted_access.models import AssistedAccessSession

    return (db.query(AssistedAccessSession)
            .filter(AssistedAccessSession.organization_id == organization_id,
                    AssistedAccessSession.approval_status == "PENDING",
                    AssistedAccessSession.access_mode == "CONSENT",
                    AssistedAccessSession.request_expires_at > _now())
            .order_by(AssistedAccessSession.id.desc()).all())
