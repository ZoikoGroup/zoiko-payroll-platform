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
  - expires_at is set once at creation and never extended in place.
  - the acting principal on every request is the requesting Super Admin
    (requested_by_user_id), never the org admin's identity.
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


def start_assisted_access(
    db: Session,
    *,
    organization_id: int,
    requested_by,
    reason: str,
    duration_minutes=None,
):
    """Create a session + token. Returns (session, token)."""
    from app.modules.assisted_access.models import AssistedAccessSession
    from app.modules.organizations.models import Organization

    reason = (reason or "").strip()
    if not reason:
        raise ValueError("a non-empty reason is required to start assisted access")

    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if org is None:
        raise ValueError("organization not found")

    minutes = int(duration_minutes or settings.ASSISTED_ACCESS_SESSION_MINUTES)
    if minutes < 1:
        minutes = 1
    started_at = _now()
    expires_at = started_at + timedelta(minutes=minutes)

    session = AssistedAccessSession(
        organization_id=org.id,
        requested_by_user_id=requested_by.id,
        reason=reason,
        started_at=started_at,
        expires_at=expires_at,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    token = create_access_token(
        {
            "sub": requested_by.email,
            "user_id": requested_by.id,
            "role": requested_by.role.value,
            "organization_id": org.id,
            "assisted_access_session_id": session.id,
        },
        expires_delta=expires_at - started_at,
        token_type=ASSISTED_ACCESS_TOKEN_TYPE,
    )

    _audit(
        db, session, requested_by.id, "ASSISTED_ACCESS_STARTED",
        payload={
            "reason": reason,
            "started_at": started_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "duration_minutes": minutes,
        },
    )
    db.commit()
    logger.info(
        "[assisted-access] STARTED session=%s org=%s by=%s expires=%s",
        session.id, org.id, requested_by.id, expires_at.isoformat(),
    )
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
    expired = (
        db.query(AssistedAccessSession)
        .filter(
            AssistedAccessSession.ended_at.is_(None),
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
    return {"scanned": len(expired), "ended": ended}


def get_active_sessions_for_org(db: Session, organization_id: int) -> list:
    from app.modules.assisted_access.models import AssistedAccessSession

    return (
        db.query(AssistedAccessSession)
        .filter(
            AssistedAccessSession.organization_id == organization_id,
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
            AssistedAccessSession.ended_at.is_(None),
            AssistedAccessSession.expires_at > _now(),
        )
        .order_by(AssistedAccessSession.started_at.desc())
        .all()
    )