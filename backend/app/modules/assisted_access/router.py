"""
modules/assisted_access/router.py
----------------------------------
API surface for Assisted Access ("SafeGuard"):

  Super Admin side
    POST /api/super-admin/assisted-access/{organization_id}/request   (CONSENT or BREAK_GLASS; no token)
    POST /api/super-admin/assisted-access/{organization_id}/start     (= CONSENT request, kept path)
    POST /api/super-admin/assisted-access/{session_id}/approve-break-glass  (a DIFFERENT Super Admin)
    POST /api/super-admin/assisted-access/{session_id}/activate       (requester; returns the token)
    POST /api/super-admin/assisted-access/{session_id}/end
    GET  /api/super-admin/assisted-access/active
    POST /api/super-admin/assisted-access/sweep

  Customer side (org-facing)
    GET  /api/organization-admin/assisted-access/status
    GET  /api/organization-admin/assisted-access/requests             (pending CONSENT requests)
    POST /api/organization-admin/assisted-access/requests/{id}/approve
    POST /api/organization-admin/assisted-access/requests/{id}/reject (reason required)

No token exists until a request is approved (tenant org admin, or for
break-glass a second Super Admin) and activated. Activation issues a
narrowly-scoped token carrying
assisted_access_session_id + organization_id with token type
"assisted_access" — distinguishable from (and never accepted as) a normal
login token. Empty reasons are rejected here AND enforced in service.py;
the frontend gating is UX, not the security boundary.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_org_admin, get_current_super_admin
from app.database import get_db
from app.modules.assisted_access import service as assisted_service


class StartAssistedAccessRequest(BaseModel):
    reason: str = ""
    mode: str = "CONSENT"
    durationMinutes: Optional[int] = None


class DecisionRequest(BaseModel):
    reason: str = ""


sa_router = APIRouter(
    prefix="/super-admin/assisted-access",
    tags=["Super Admin - Assisted Access"],
)

org_router = APIRouter(
    prefix="/organization-admin/assisted-access",
    tags=["Organization Admin - Assisted Access"],
)


def _session_json(session, token=None):
    out = {
        "session_id": session.id,
        "organization_id": session.organization_id,
        "requested_by_user_id": session.requested_by_user_id,
        "reason": session.reason,
        "started_at": session.started_at,
        "expires_at": session.expires_at,
        "ended_at": session.ended_at,
        "ended_reason": session.ended_reason,
        "access_mode": session.access_mode,
        "approval_status": session.approval_status,
        "requested_minutes": session.requested_minutes,
        "request_expires_at": session.request_expires_at,
        "approved_by_user_id": session.approved_by_user_id,
        "activated_at": session.activated_at,
        "tenant_notified_at": session.tenant_notified_at,
    }
    if token is not None:
        out["token"] = token
        out["expires_in_minutes"] = int(
            (session.expires_at - session.started_at).total_seconds() // 60
        )
    return out


def _session_or_404(db: Session, session_id: int, organization_id: int = None):
    from app.modules.assisted_access.models import AssistedAccessSession

    session = db.query(AssistedAccessSession).filter(AssistedAccessSession.id == session_id).first()
    if session is None or (organization_id is not None and session.organization_id != organization_id):
        raise HTTPException(status_code=404, detail="assisted access session not found")
    return session


def _guard(fn):
    try:
        return fn()
    except assisted_service.AssistedAccessRefused as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@sa_router.post("/{organization_id}/request")
def request_assisted_access(
    organization_id: int,
    body: StartAssistedAccessRequest,
    db: Session = Depends(get_db),
    admin=Depends(get_current_super_admin),
):
    """Request access to an organization. CONSENT waits for its org admin;
    BREAK_GLASS waits for a second Super Admin. No token is issued here."""
    session = _guard(lambda: assisted_service.request_assisted_access(
        db, organization_id=organization_id, requested_by=admin, reason=body.reason, mode=body.mode,
        duration_minutes=body.durationMinutes))
    return _session_json(session)


@sa_router.post("/{organization_id}/start")
def start_assisted_access(
    organization_id: int,
    body: StartAssistedAccessRequest,
    db: Session = Depends(get_db),
    admin=Depends(get_current_super_admin),
):
    """Kept path: now creates a CONSENT request (no token until the tenant
    approves and the requester activates). Blank reason → 422."""
    session = _guard(lambda: assisted_service.request_assisted_access(
        db, organization_id=organization_id, requested_by=admin, reason=body.reason, mode="CONSENT",
        duration_minutes=body.durationMinutes))
    return _session_json(session)


@sa_router.post("/{session_id}/approve-break-glass")
def approve_break_glass(
    session_id: int,
    body: DecisionRequest,
    db: Session = Depends(get_db),
    admin=Depends(get_current_super_admin),
):
    """A second Super Admin (never the requester) approves an emergency
    request; the session starts and the tenant is notified at once."""
    session = _session_or_404(db, session_id)
    if session.access_mode != "BREAK_GLASS":
        _guard(lambda: assisted_service._refuse(db, session, admin.id, "approve",
                                                "This is a CONSENT request — only the organization's admin can approve it."))
    _guard(lambda: assisted_service.approve_assisted_access(db, session, approver=admin, decision_reason=body.reason))
    return _session_json(session)


@sa_router.post("/{session_id}/activate")
def activate_assisted_access(
    session_id: int,
    db: Session = Depends(get_db),
    admin=Depends(get_current_super_admin),
):
    """The requester starts an approved CONSENT session and receives its token."""
    session = _session_or_404(db, session_id)
    session, token = _guard(lambda: assisted_service.activate_assisted_access(db, session, requested_by=admin))
    return _session_json(session, token=token)


@sa_router.post("/{session_id}/end")
def end_assisted_access(
    session_id: int,
    db: Session = Depends(get_db),
    admin=Depends(get_current_super_admin),
):
    """Manually end a session. Idempotent."""
    from app.modules.assisted_access.models import AssistedAccessSession

    session = db.query(AssistedAccessSession).filter(AssistedAccessSession.id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="assisted access session not found")
    assisted_service.end_assisted_access(
        db, session, ended_reason="MANUAL_END", actor_user_id=admin.id
    )
    return _session_json(session)


@sa_router.get("/active")
def list_active_sessions(
    db: Session = Depends(get_db),
    _admin=Depends(get_current_super_admin),
):
    """All currently-active sessions, for the Super Admin Operations view."""
    sessions = assisted_service.get_active_sessions_all(db)
    return {"sessions": [_session_json(s) for s in sessions], "total": len(sessions)}


@sa_router.post("/sweep")
def run_sweep_now(
    db: Session = Depends(get_db),
    _admin=Depends(get_current_super_admin),
):
    """Manually run the expiry sweep — same logic the background scheduler
    runs on a timer. Mirrors POST /super-admin/billing/trial-expiry-run as
    the on-demand counterpart to a scheduled sweep."""
    result = assisted_service.run_expiry_sweep(db)
    return {"scanned": result["scanned"], "ended": result["ended"]}


@org_router.get("/status")
def assisted_access_status(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_org_admin),
):
    """Customer-facing: is Zoiko support currently assisting this org?
    Powers the persistent banner in PayrollShell. Returns nothing but the
    active window — never the session reason or the requesting SA's id."""
    org_id = current_user.organization_id
    active = assisted_service.get_active_sessions_for_org(db, organization_id=org_id)
    session = active[0] if active else None
    pending = len(assisted_service.pending_requests_for_org(db, org_id))
    if session is None:
        return {"active": False, "started_at": None, "expires_at": None, "pending_requests": pending}
    return {
        "active": True,
        "started_at": session.started_at,
        "expires_at": session.expires_at,
        "break_glass": session.access_mode == "BREAK_GLASS",
        "pending_requests": pending,
    }


@org_router.get("/requests")
def pending_requests(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_org_admin),
):
    """Pending CONSENT requests for this organization (reason shown so the
    org admin can decide; the requesting Super Admin's id is not exposed)."""
    return {"requests": [
        {"session_id": s.id, "reason": s.reason, "requested_minutes": s.requested_minutes,
         "requested_at": s.started_at, "request_expires_at": s.request_expires_at}
        for s in assisted_service.pending_requests_for_org(db, current_user.organization_id)]}


@org_router.post("/requests/{session_id}/approve")
def approve_request(
    session_id: int,
    body: DecisionRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_org_admin),
):
    """An org admin of this organization approves (the service refuses — and
    audits — anyone else, including a Super Admin or an assisted session)."""
    session = _session_or_404(db, session_id, organization_id=current_user.organization_id)
    _guard(lambda: assisted_service.approve_assisted_access(db, session, approver=current_user,
                                                            decision_reason=body.reason))
    return {"session_id": session.id, "approval_status": session.approval_status}


@org_router.post("/requests/{session_id}/reject")
def reject_request(
    session_id: int,
    body: DecisionRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_org_admin),
):
    session = _session_or_404(db, session_id, organization_id=current_user.organization_id)
    _guard(lambda: assisted_service.reject_assisted_access(db, session, actor=current_user, reason=body.reason))
    return {"session_id": session.id, "approval_status": session.approval_status}