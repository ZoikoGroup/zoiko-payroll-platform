"""
modules/auth/social.py
----------------------
Microsoft and Apple sign-in / sign-up, plus Company SSO discovery.

Same contract as Google Sign-In (service.google_sign_in):

  * a known identity → the account's session, or its second factor;
  * an unknown identity → a single-use pending hold and the registration
    page (/register?pending=&provider=), never an auto-created account.

Identity matching, in order:

  1. a linked identity: user_oauth_identities (provider, subject);
  2. an existing account with the same email — linked on first use — but
     only when the provider vouches for that email. Apple always verifies
     its addresses. Microsoft verifies personal accounts; for work / school
     accounts the email claim is admin-editable, so it is trusted only with
     the xms_edov (domain owner verified) claim. Linking on an unverified
     email would let anyone who controls a tenant sign in as any user.

Each provider is off until its settings are present (see config.py); the
sign-in page asks GET /auth/providers which buttons to enable.
"""

from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode, urlsplit

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.core import social_oauth
from app.core.exceptions import BadRequestException, UnauthorizedException
from app.modules.auth.models import OAuthIdentity, OAuthPending, OrganizationSsoDomain, User

logger = logging.getLogger("zoiko_payroll.auth.social")

PROVIDERS = ("microsoft", "apple")
PROVIDER_LABELS = {"google": "Google", "microsoft": "Microsoft", "apple": "Apple"}
PENDING_TTL_MINUTES = 10

_EMAIL_RE = re.compile(r"^[^@\s]+@([^@\s]+\.[^@\s]+)$")


# ── Configuration ────────────────────────────────────────────────────────────

def provider_configured(provider: str) -> bool:
    if provider == "google":
        return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)
    if provider == "microsoft":
        return bool(settings.MICROSOFT_CLIENT_ID and settings.MICROSOFT_CLIENT_SECRET)
    if provider == "apple":
        return bool(settings.APPLE_CLIENT_ID and settings.APPLE_TEAM_ID
                    and settings.APPLE_KEY_ID and settings.APPLE_PRIVATE_KEY)
    return False


def provider_status() -> dict:
    """Which sign-in buttons work on this server. Company SSO is behind the
    COMPANY_SSO_ENABLED flag (off by default) until organization SSO is built."""
    return {
        "google": provider_configured("google"),
        "microsoft": provider_configured("microsoft"),
        "apple": provider_configured("apple"),
        "sso": bool(settings.COMPANY_SSO_ENABLED),
    }


def _require(provider: str) -> None:
    if provider not in PROVIDERS:
        raise BadRequestException("Unknown sign-in provider.")
    if not provider_configured(provider):
        raise BadRequestException(f"{PROVIDER_LABELS[provider]} sign-in is not configured on this server.")


def authorization_url(provider: str, state: str) -> str:
    """The provider's consent URL for a CSRF state value."""
    _require(provider)
    if provider == "microsoft":
        params = {
            "client_id": settings.MICROSOFT_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": settings.MICROSOFT_REDIRECT_URI,
            "response_mode": "query",
            "scope": "openid email profile",
            "state": state,
            "prompt": "select_account",
        }
        return social_oauth.microsoft_endpoint(settings.MICROSOFT_TENANT, "authorize") + "?" + urlencode(params)
    # Apple: asking for name/email requires response_mode=form_post, so the
    # callback is a cross-site POST to the API.
    params = {
        "client_id": settings.APPLE_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": settings.APPLE_REDIRECT_URI,
        "response_mode": "form_post",
        "scope": "name email",
        "state": state,
    }
    return social_oauth.APPLE_AUTHORIZATION_ENDPOINT + "?" + urlencode(params)


# ── Provider profile ─────────────────────────────────────────────────────────

def _split_name(full_name: str) -> tuple[str, str]:
    parts = (full_name or "").strip().split(" ", 1)
    return (parts[0], parts[1] if len(parts) > 1 else "") if parts[0] else ("", "")


def _microsoft_profile(code: str) -> dict:
    resp = social_oauth.microsoft_exchange_code(settings.MICROSOFT_TENANT, {
        "client_id": settings.MICROSOFT_CLIENT_ID,
        "client_secret": settings.MICROSOFT_CLIENT_SECRET,
        "code": code,
        "redirect_uri": settings.MICROSOFT_REDIRECT_URI,
        "grant_type": "authorization_code",
        "scope": "openid email profile",
    })
    if resp.status_code >= 400:
        logger.warning("Microsoft token exchange failed: %s", resp.text[:200])
        raise UnauthorizedException("Microsoft sign-in failed. Please try again.")
    try:
        claims = social_oauth.microsoft_claims(resp.json().get("id_token", ""), settings.MICROSOFT_CLIENT_ID)
    except social_oauth.IdTokenError as exc:
        logger.warning("Microsoft id_token rejected: %s", exc)
        raise UnauthorizedException("Microsoft sign-in failed. Please try again.")

    email = (claims.get("email") or "").strip()
    verified = bool(email) and social_oauth.microsoft_email_is_verified(claims)
    if not email:
        # Work accounts without a mail attribute: the sign-in name is
        # usually the address, but Microsoft does not vouch for it.
        candidate = (claims.get("preferred_username") or "").strip()
        email = candidate if _EMAIL_RE.match(candidate) else ""
    first, last = claims.get("given_name") or "", claims.get("family_name") or ""
    if not first and not last:
        first, last = _split_name(claims.get("name") or "")
    return {"subject": str(claims["sub"]), "email": email.lower(), "email_verified": verified,
            "given_name": first, "family_name": last, "is_private_relay": False}


def _apple_profile(code: str, user_json: Optional[dict]) -> dict:
    secret = social_oauth.apple_client_secret(settings.APPLE_TEAM_ID, settings.APPLE_CLIENT_ID,
                                              settings.APPLE_KEY_ID, settings.APPLE_PRIVATE_KEY)
    resp = social_oauth.apple_exchange_code({
        "client_id": settings.APPLE_CLIENT_ID,
        "client_secret": secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": settings.APPLE_REDIRECT_URI,
    })
    if resp.status_code >= 400:
        logger.warning("Apple token exchange failed: %s", resp.text[:200])
        raise UnauthorizedException("Apple sign-in failed. Please try again.")
    try:
        claims = social_oauth.apple_claims(resp.json().get("id_token", ""), settings.APPLE_CLIENT_ID)
    except social_oauth.IdTokenError as exc:
        logger.warning("Apple id_token rejected: %s", exc)
        raise UnauthorizedException("Apple sign-in failed. Please try again.")

    email = (claims.get("email") or "").strip().lower()
    relay = social_oauth.truthy_claim(claims.get("is_private_email")) or social_oauth.is_apple_private_relay(email)
    # Apple sends the name only once, on the first authorization, as the
    # form field `user` — never inside the id_token.
    name = (user_json or {}).get("name") or {}
    return {"subject": str(claims["sub"]), "email": email,
            "email_verified": bool(email) and social_oauth.truthy_claim(claims.get("email_verified", True)),
            "given_name": str(name.get("firstName") or "")[:120],
            "family_name": str(name.get("lastName") or "")[:120],
            "is_private_relay": relay}


# ── Accounts ─────────────────────────────────────────────────────────────────

def find_identity_user(db: Session, provider: str, subject: str):
    identity = (db.query(OAuthIdentity)
                .filter(OAuthIdentity.provider == provider, OAuthIdentity.subject == subject).first())
    if identity is None:
        return None
    return db.query(User).filter(User.id == identity.user_id).first()


def _find_or_link_user(db: Session, provider: str, profile: dict):
    user = find_identity_user(db, provider, profile["subject"])
    if user is not None:
        return user
    if not (profile["email"] and profile["email_verified"]) or profile["is_private_relay"]:
        return None
    user = db.query(User).filter(func.lower(User.email) == profile["email"]).first()
    if user is None:
        return None
    # Link this identity to the existing account; a password account stays
    # a password account (both sign-ins work).
    db.add(OAuthIdentity(user_id=user.id, provider=provider, subject=profile["subject"],
                         provider_email=profile["email"], is_private_relay=False))
    db.commit()
    db.refresh(user)
    logger.info("Linked %s sign-in to existing user %s", PROVIDER_LABELS[provider], user.id)
    return user


def sign_in(db: Session, provider: str, code: str, request=None, mode: str = "login",
            apple_user: Optional[dict] = None) -> dict:
    """Full provider sign-in. Same result shapes as service.google_sign_in:
    {"action": "session"|"mfa"|"pending", ...}."""
    from app.modules.auth import service

    _require(provider)
    profile = _microsoft_profile(code) if provider == "microsoft" else _apple_profile(code, apple_user)

    user = _find_or_link_user(db, provider, profile)
    if user is not None:
        service.refuse_inactive_federated_user(db, user, request)
        return service.federated_session_or_mfa(db, user, request, via=PROVIDER_LABELS[provider])

    if not profile["email"]:
        raise UnauthorizedException(
            f"Your {PROVIDER_LABELS[provider]} account didn't share an email address. "
            "Please sign up with your work email.")
    token = _create_pending(db, provider, profile, mode)
    logger.info("New %s identity needs registration (mode=%s)", PROVIDER_LABELS[provider], mode)
    return {"action": "pending", "token": token, "email": profile["email"], "provider": provider,
            "is_private_relay": profile["is_private_relay"]}


# ── Pending registrations ────────────────────────────────────────────────────

def _create_pending(db: Session, provider: str, profile: dict, mode: str) -> str:
    token = secrets.token_urlsafe(32)
    db.add(OAuthPending(
        token=token, provider=provider, subject=profile["subject"], email=profile["email"],
        given_name=profile["given_name"] or None, family_name=profile["family_name"] or None,
        is_private_relay=profile["is_private_relay"], mode=mode,
        expires_at=datetime.utcnow() + timedelta(minutes=PENDING_TTL_MINUTES),
    ))
    db.commit()
    return token


def _live_pending(db: Session, token: str, provider: Optional[str] = None):
    if not token:
        return None
    query = db.query(OAuthPending).filter(OAuthPending.token == token)
    if provider:
        query = query.filter(OAuthPending.provider == provider)
    row = query.first()
    if row is None or row.consumed_at is not None or row.expires_at <= datetime.utcnow():
        return None
    return row


def get_pending(db: Session, token: str, provider: Optional[str] = None) -> Optional[dict]:
    """A pending profile without consuming it, or None when missing / expired
    / used. Consumed only when registration succeeds (register_enterprise)."""
    row = _live_pending(db, token, provider)
    if row is None:
        return None
    return {"provider": row.provider, "subject": row.subject, "email": row.email,
            "given_name": row.given_name, "family_name": row.family_name,
            "is_private_relay": bool(row.is_private_relay), "mode": row.mode}


def public_pending(db: Session, token: str) -> Optional[dict]:
    """What the registration page may see: no provider subject id."""
    profile = get_pending(db, token)
    if profile is None:
        return None
    return {key: profile[key] for key in ("provider", "email", "given_name", "family_name", "is_private_relay")}


def consume_pending(db: Session, token: str) -> bool:
    row = _live_pending(db, token)
    if row is None:
        return False
    row.consumed_at = datetime.utcnow()
    db.commit()
    return True


# ── Company SSO discovery ────────────────────────────────────────────────────

def email_domain(email: str) -> str:
    match = _EMAIL_RE.match((email or "").strip().lower())
    return match.group(1) if match else ""


def discover_sso(db: Session, email: str) -> dict:
    """Where "Continue with Company SSO" should go for this email address.

    {"sso": True, "login_url": ...} when the address's domain belongs to an
    organization with SSO set up; otherwise {"sso": False}. Nothing about
    the organization itself is returned. 404 while COMPANY_SSO_ENABLED is off."""
    if not settings.COMPANY_SSO_ENABLED:
        from app.core.exceptions import NotFoundException

        raise NotFoundException("Company SSO")
    domain = email_domain(email)
    if not domain:
        raise BadRequestException("Enter a valid work email address.")
    row = (db.query(OrganizationSsoDomain)
           .filter(OrganizationSsoDomain.domain == domain, OrganizationSsoDomain.is_active.is_(True)).first())
    if row is None or urlsplit(row.login_url or "").scheme != "https":
        return {"sso": False}
    return {"sso": True, "login_url": row.login_url}
