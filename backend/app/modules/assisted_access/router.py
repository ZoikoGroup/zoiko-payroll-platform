"""
modules/assisted_access/router.py
----------------------------------
API surface for Assisted Access ("SafeGuard"):

  Super Admin side
    POST /api/super-admin/assisted-access/{organization_id}/start
    POST /api/super-admin/assisted-access/{session_id}/end
    GET  /api/super-admin/assisted-access/active
    POST /api/super-admin/assisted-access/sweep

  Customer side (org-facing, powered by the same banner contract as
  modules/assist: a "Zoiko support is currently assisting your
  organization" banner appears while a session is active)
    GET  /api/organization-admin/assisted-access/status

The start endpoint issues a narrowly-scoped token carrying
assisted_access_session_id + organization_id with token type
"assisted_access" — distinguishable from (and never accepted as) a normal
login token. Empty reasons are rejected here AND enforced in service.py;
the frontend gating is UX, not the security boundary.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_org_admin, get_current_super_admin
from app.database import get_db
from app.modules.assisted_access import service as assisted_service


class StartAssistedAccessRequest(BaseModel):
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
    }
    if token is not None:
        out["token"] = token
        out["expires_in_minutes"] = int(
            (session.expires_at - session.started_at).total_seconds() // 60
        )
    return out


@sa_router.post("/{organization_id}/start")
def start_assisted_access(
    organization_id: int,
    body: StartAssistedAccessRequest,
    db: Session = Depends(get_db),
    admin=Depends(get_current_super_admin),
):
    """Start a time-boxed assisted-access session for an organization.
    Non-empty reason is required — blank access is rejected even if a
    client bypasses any frontend disable state and calls this raw."""
    try:
        session, token = assisted_service.start_assisted_access(
            db,
            organization_id=organization_id,
            requested_by=admin,
            reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
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
    if session is None:
        return {"active": False, "started_at": None, "expires_at": None}
    return {
        "active": True,
        "started_at": session.started_at,
        "expires_at": session.expires_at,
    }