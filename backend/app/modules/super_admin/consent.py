"""
consent.py
----------
ZP-PRIV A03 — platform staff must not be able to take over a tenant account
by creating or resetting a tenant user's credentials.

A Super Admin creating an organization admin, or resetting a tenant user's
password, is a takeover path straight into tenant data that bypasses every
other scoped check in this programme. It is therefore refused unless either

  * the target is a platform-plane user (no ``organization_id``) — no tenant
    data is behind it, so the guard does not apply; or
  * there is a live, tenant-approved support grant covering the target's
    organization (Part D). Until Part D ships there is no such grant table, so
    every tenant-credential action from the platform plane fails closed.

Nothing here creates a session for the actor on the tenant account: a reset
only ever issues a single-use link to the *target* user's own inbox, and this
guard runs before that link is issued.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenException


def _live_tenant_grant_org_ids(db: Session) -> set:
    """Organizations covered by a live, tenant-approved JIT support grant
    (status active, approved by the tenant, not yet expired). A query error
    propagates: it must never be mistaken for consent."""
    from datetime import datetime

    from app.modules.support_access.models import ACTIVE, SupportAccessGrant

    rows = (
        db.query(SupportAccessGrant.organization_id)
        .filter(SupportAccessGrant.status == ACTIVE,
                SupportAccessGrant.approved_by_user_id.isnot(None),
                SupportAccessGrant.expires_at > datetime.utcnow())
        .all()
    )
    return {r[0] for r in rows}


def require_tenant_consent_for_credential_action(
    db: Session, target_user, actor_user_id: Optional[int], action: str,
) -> None:
    """Raise 403 unless a platform-staff credential action against
    ``target_user`` is permitted (platform user, or live tenant grant)."""
    org_id = getattr(target_user, "organization_id", None)
    if org_id is None:
        # Platform-plane account: no tenant data behind it.
        return
    if org_id in _live_tenant_grant_org_ids(db):
        return
    raise ForbiddenException(
        "Platform staff cannot create or reset credentials for a tenant user "
        "without the tenant's consent or a live JIT support grant "
        f"(ZP-PRIV A03, action={action})."
    )
