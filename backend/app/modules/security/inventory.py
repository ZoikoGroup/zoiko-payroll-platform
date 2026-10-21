"""
modules/security/inventory.py
-----------------------------
Privileged access inventory (ZP-PRIV E04): every privileged human (platform
roles and tenant org admins), every machine client, every live or emergency
support grant, with last login and MFA status. Used by
GET /api/super-admin/privileged-inventory and scripts/privileged_inventory.py.
Platform accounts are listed by email (they are Zoiko staff); tenant admins
by id and organization code only.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

PLATFORM_ROLES = ("super_admin", "support_operator", "platform_security")
PRIVILEGED_TENANT_ROLES = ("org_admin",)


def _z(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_inventory(db: Session) -> dict:
    from app.modules.auth.models import AuthAuditEvent, MfaCredential, User, UserRole
    from app.modules.organizations.models import Organization
    from app.modules.security.models import MachineClient
    from app.modules.support_access.models import ACTIVE, PENDING, SupportAccessGrant

    roles = [UserRole(r) for r in PLATFORM_ROLES + PRIVILEGED_TENANT_ROLES]
    users = (db.query(User).filter(User.role.in_(roles), User.is_temporary.is_(False))
             .order_by(User.role, User.id).all())
    last_login = dict(db.query(AuthAuditEvent.user_id, func.max(AuthAuditEvent.occurred_at))
                      .filter(AuthAuditEvent.event_type == "LOGIN_SUCCESS").group_by(AuthAuditEvent.user_id).all())
    mfa = {r[0] for r in db.query(MfaCredential.user_id).filter(MfaCredential.confirmed_at.isnot(None)).all()}
    org_codes = dict(db.query(Organization.id, Organization.organization_code).all())

    humans = []
    for u in users:
        role = u.role.value
        platform = role in PLATFORM_ROLES
        humans.append({
            "userId": u.id, "role": role, "plane": "platform" if platform else "tenant",
            "account": u.email if platform else None, "organizationCode": org_codes.get(u.organization_id),
            "isActive": u.is_active, "mfaEnrolled": u.id in mfa, "lastLogin": _z(last_login.get(u.id)),
        })

    now = datetime.now(timezone.utc)
    machines = [{
        "id": c.id, "organizationCode": org_codes.get(c.organization_id), "name": c.name,
        "scopes": list(c.scopes or []), "lastUsedAt": _z(c.last_used_at), "expiresAt": _z(c.expires_at),
        "status": "revoked" if c.revoked_at else (
            "expired" if (c.expires_at if c.expires_at.tzinfo else c.expires_at.replace(tzinfo=timezone.utc)) <= now
            else "active"),
    } for c in db.query(MachineClient).order_by(MachineClient.id).all()]

    grants = [{
        "grantId": g.id, "organizationCode": org_codes.get(g.organization_id), "status": g.status,
        "requestedByUserId": g.requested_by_user_id, "scopeType": g.scope_type, "isBreakGlass": g.is_break_glass,
        "expiresAt": _z(g.expires_at), "reviewDueAt": _z(g.review_due_at), "reviewed": g.reviewed_at is not None,
    } for g in db.query(SupportAccessGrant)
        .filter((SupportAccessGrant.status.in_((ACTIVE, PENDING)))
                | ((SupportAccessGrant.is_break_glass.is_(True)) & (SupportAccessGrant.reviewed_at.is_(None))))
        .order_by(SupportAccessGrant.id).all()]

    return {
        "generatedAt": _z(now),
        "summary": {
            "platformHumans": sum(1 for h in humans if h["plane"] == "platform"),
            "tenantAdmins": sum(1 for h in humans if h["plane"] == "tenant"),
            "withoutMfa": sum(1 for h in humans if not h["mfaEnrolled"] and h["isActive"]),
            "machineClients": len(machines),
            "liveGrants": sum(1 for g in grants if g["status"] in ("active", "pending_approval")),
            "emergencyGrantsAwaitingReview": sum(1 for g in grants if g["isBreakGlass"] and not g["reviewed"]),
        },
        "humans": humans,
        "machineClients": machines,
        "grants": grants,
    }
