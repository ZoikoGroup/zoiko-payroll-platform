"""
modules/security/federation.py
------------------------------
Zoiko One identity federation gate (ZP-PRIV D05). INTEGRATION PENDING: no
Zoiko One code exists in this repository, so the contract below, the gate and
its tests (a fake IdP) ship now and the exchange stays disabled until
FEDERATION_ISSUER / FEDERATION_PUBLIC_KEY_PEM are configured.

Claim contract (a short-lived RS256 JWT from the Zoiko One IdP):

  iss            must equal settings.FEDERATION_ISSUER
  aud            must equal "zoiko-payroll" (any other product's token is refused)
  sub            the IdP subject (informational)
  email          the person's login; must be an existing, active user here
  tenant_id      the Zoiko One tenant id; must map to exactly one payroll
                 organization (organizations.organization_code == payroll_org)
  payroll_org    the payroll organization code the tenant id maps to
  entity_ids     optional: legal entities the session is limited to - must be
                 within what the user is already allowed here
  products       must contain "payroll" (product entitlement)
  amr            optional: contains "mfa" when the IdP performed MFA
  iat / exp      lifetime at most FEDERATION_MAX_TOKEN_SECONDS (300)

The exchange yields ONLY the existing user's own tenant-scoped session: the
role comes from this platform's database, never from claims. Any global /
platform-wide claim ("global_admin", "platform_admin", "super_admin", a "*"
tenant) is refused - platform-wide authentication must never become
platform-wide payroll data access. Platform roles cannot federate at all.
"""

from __future__ import annotations

import time
from typing import Optional

from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import UnauthorizedException

AUDIENCE = "zoiko-payroll"
GLOBAL_ROLE_CLAIMS = frozenset({"global_admin", "platform_admin", "super_admin", "zoiko_admin", "root"})


class FederationRefused(UnauthorizedException):
    def __init__(self, reason: str):
        super().__init__("This sign-in could not be accepted.")
        self.reason = reason


def enabled() -> bool:
    return bool(getattr(settings, "FEDERATION_ISSUER", "") and getattr(settings, "FEDERATION_PUBLIC_KEY_PEM", ""))


def validate_claims(token: str, *, public_key_pem: str, issuer: str, max_lifetime: int, now: Optional[int] = None) -> dict:
    """Signature + standard + contract checks. Raises FederationRefused."""
    try:
        claims = jwt.decode(token, public_key_pem, algorithms=["RS256"], audience=AUDIENCE, issuer=issuer,
                            options={"require_exp": True, "require_iat": True})
    except JWTError as exc:
        raise FederationRefused(f"INVALID_TOKEN:{type(exc).__name__}")
    now = int(now if now is not None else time.time())
    if int(claims["exp"]) - int(claims["iat"]) > max_lifetime:
        raise FederationRefused("TOKEN_LIFETIME_TOO_LONG")
    if int(claims["iat"]) > now + 60:
        raise FederationRefused("TOKEN_FROM_THE_FUTURE")
    roles = {str(r).lower() for r in (claims.get("roles") or [])}
    if roles & GLOBAL_ROLE_CLAIMS or claims.get("tenant_id") in ("*", "", None) or claims.get("global") is True:
        raise FederationRefused("GLOBAL_CLAIM_REFUSED")
    if "payroll" not in (claims.get("products") or []):
        raise FederationRefused("NO_PAYROLL_ENTITLEMENT")
    for required in ("email", "payroll_org", "sub"):
        if not claims.get(required):
            raise FederationRefused(f"MISSING_{required.upper()}")
    return claims


def exchange(db: Session, token: str, request=None) -> dict:
    """Validate a Zoiko One token and return a normal payroll session (or an
    MFA step) for the matching existing user."""
    from app.core.security import MFA_CHALLENGE_TOKEN_TYPE, MFA_ENROLL_TOKEN_TYPE, create_mfa_token
    from app.core.authz.scopes import assigned_scope
    from app.modules.auth import mfa
    from app.modules.auth.models import User
    from app.modules.auth.service import issue_session, temporary_access_ended
    from app.modules.organizations.models import Organization
    from app.modules.security import events as security_events

    def refuse(reason: str, **kw):
        security_events.emit(db, "FEDERATION_REFUSED", result="deny", target_type="federation",
                             reason_code=reason[:60], request=request, **kw)
        raise FederationRefused(reason)

    if not enabled():
        refuse("FEDERATION_NOT_CONFIGURED")
    try:
        claims = validate_claims(token, public_key_pem=settings.FEDERATION_PUBLIC_KEY_PEM,
                                 issuer=settings.FEDERATION_ISSUER,
                                 max_lifetime=settings.FEDERATION_MAX_TOKEN_SECONDS)
    except FederationRefused as exc:
        refuse(exc.reason)
    org = db.query(Organization).filter(Organization.organization_code == claims["payroll_org"]).first()
    if org is None or not org.is_active:
        refuse("UNKNOWN_OR_INACTIVE_ORGANIZATION")
    user = db.query(User).filter(User.email == claims["email"]).first()
    if user is None or not user.is_active or temporary_access_ended(user) or user.is_temporary:
        refuse("UNKNOWN_OR_INACTIVE_USER", organization_id=org.id)
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if user.organization_id is None or role in ("super_admin", "support_operator", "platform_security"):
        refuse("PLATFORM_ROLE_CANNOT_FEDERATE", actor_user_id=user.id)
    if user.organization_id != org.id:
        refuse("CROSS_TENANT_CLAIM", actor_user_id=user.id, organization_id=org.id)
    requested_entities = set(claims.get("entity_ids") or [])
    if requested_entities:
        entities, groups = assigned_scope(db, user.id, org.id)
        if (entities or groups) and not requested_entities <= set(entities):
            refuse("ENTITY_SCOPE_EXCEEDS_USER_SCOPE", actor_user_id=user.id, organization_id=org.id)
    security_events.emit(db, "FEDERATION_EXCHANGE", result="allow", actor_user_id=user.id, actor_role=role,
                         organization_id=org.id, target_type="federation", target_id=f"sub:{claims['sub']}"[:200],
                         request=request)
    idp_mfa = "mfa" in [str(a).lower() for a in (claims.get("amr") or [])]
    if mfa.mfa_required_for(user) and not idp_mfa:
        if mfa.is_enrolled(db, user):
            return {"mfa_required": True, "mfa_token": create_mfa_token(user.id, MFA_CHALLENGE_TOKEN_TYPE)}
        return {"mfa_enrollment_required": True, "mfa_token": create_mfa_token(user.id, MFA_ENROLL_TOKEN_TYPE)}
    return issue_session(db, user, request, mfa_at=int(time.time()) if idp_mfa else None)
