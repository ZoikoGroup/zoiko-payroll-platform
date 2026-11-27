"""Allowlisted outbound HTTP for Microsoft and Apple sign-in (OIDC code flow).

Same boundary rules as core/google_oauth.py: only the fixed token endpoints
below can be called, no redirects are followed, and proxy settings from the
environment are ignored. Both providers return the user's identity in an
``id_token`` from the token endpoint itself; that response comes straight
from the provider over TLS to an authenticated client (client secret), so
its claims are checked (issuer, audience, expiry) without fetching signing
keys — OpenID Connect Core 1.0 §3.1.3.7, step 6.
"""

from __future__ import annotations

import re
import time

import httpx
from jose import jwt

MICROSOFT_LOGIN_HOST = "https://login.microsoftonline.com"
APPLE_AUTHORIZATION_ENDPOINT = "https://appleid.apple.com/auth/authorize"
APPLE_TOKEN_ENDPOINT = "https://appleid.apple.com/auth/token"
APPLE_ISSUER = "https://appleid.apple.com"

# "common", "organizations", "consumers", a tenant GUID or a verified domain.
_TENANT_RE = re.compile(r"^[A-Za-z0-9-]{1,64}(\.[A-Za-z0-9-]{1,63}){0,8}$")
# Personal Microsoft accounts (outlook.com, hotmail.com, live.com …) all sign
# in through this fixed tenant; their email addresses are Microsoft-verified.
MICROSOFT_CONSUMER_TENANT_ID = "9188040d-6c67-4c5b-b112-36a304b66dad"
_MICROSOFT_ISSUER_RE = re.compile(r"^https://login\.microsoftonline\.com/([0-9a-fA-F-]{36})/v2\.0$")


class IdTokenError(ValueError):
    """The provider's id_token is missing, malformed or not meant for us."""


def _client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(20.0), follow_redirects=False, trust_env=False)


# ── Microsoft ────────────────────────────────────────────────────────────────

def microsoft_endpoint(tenant: str, kind: str) -> str:
    """The authorize/token URL for a configured tenant."""
    if not _TENANT_RE.match(tenant or ""):
        raise ValueError("Microsoft tenant is not a valid tenant id or domain")
    if kind not in {"authorize", "token"}:
        raise ValueError("Unknown Microsoft endpoint")
    return f"{MICROSOFT_LOGIN_HOST}/{tenant}/oauth2/v2.0/{kind}"


def microsoft_exchange_code(tenant: str, data: dict) -> httpx.Response:
    endpoint = microsoft_endpoint(tenant, "token")
    with _client() as client:
        return client.post(endpoint, data=data)


def microsoft_claims(id_token: str, client_id: str) -> dict:
    """Claims of a Microsoft id_token after issuer / audience / expiry checks."""
    claims = _unverified_claims(id_token)
    issuer = str(claims.get("iss") or "")
    match = _MICROSOFT_ISSUER_RE.match(issuer)
    if not match or match.group(1).lower() != str(claims.get("tid") or "").lower():
        raise IdTokenError("unexpected issuer")
    _check_audience_and_expiry(claims, client_id)
    if not claims.get("oid") and not claims.get("sub"):
        raise IdTokenError("no subject")
    return claims


def microsoft_email_is_verified(claims: dict) -> bool:
    """Whether Microsoft vouches for the email claim.

    Work/school tenants let an admin put any address in a user's mail
    attribute, so an organizational account's email is trusted only when the
    token says the tenant owns that domain (optional claim xms_edov). Personal
    Microsoft accounts verify their address."""
    if str(claims.get("tid") or "").lower() == MICROSOFT_CONSUMER_TENANT_ID:
        return True
    return claims.get("xms_edov") in (True, "true", "True", 1, "1")


# ── Apple ────────────────────────────────────────────────────────────────────

def apple_client_secret(team_id: str, client_id: str, key_id: str, private_key_pem: str,
                        now: int | None = None) -> str:
    """The ES256-signed client secret Apple's token endpoint requires."""
    issued = int(now if now is not None else time.time())
    key = (private_key_pem or "").replace("\\n", "\n").strip()
    return jwt.encode(
        {"iss": team_id, "iat": issued, "exp": issued + 300, "aud": APPLE_ISSUER, "sub": client_id},
        key,
        algorithm="ES256",
        headers={"kid": key_id},
    )


def apple_exchange_code(data: dict) -> httpx.Response:
    with _client() as client:
        return client.post(APPLE_TOKEN_ENDPOINT, data=data)


def apple_claims(id_token: str, client_id: str) -> dict:
    """Claims of an Apple id_token after issuer / audience / expiry checks."""
    claims = _unverified_claims(id_token)
    if claims.get("iss") != APPLE_ISSUER:
        raise IdTokenError("unexpected issuer")
    _check_audience_and_expiry(claims, client_id)
    if not claims.get("sub"):
        raise IdTokenError("no subject")
    return claims


def is_apple_private_relay(email: str | None) -> bool:
    """True for an Apple "Hide My Email" forwarding address."""
    return bool(email) and email.strip().lower().endswith("@privaterelay.appleid.com")


def truthy_claim(value) -> bool:
    """Apple sends booleans in id_tokens as true/false or "true"/"false"."""
    return value in (True, "true", "True", 1, "1")


# ── Shared ───────────────────────────────────────────────────────────────────

def _unverified_claims(id_token: str) -> dict:
    try:
        claims = jwt.get_unverified_claims(id_token or "")
    except Exception as exc:  # jose raises several error types for malformed tokens
        raise IdTokenError("malformed id_token") from exc
    if not isinstance(claims, dict):
        raise IdTokenError("malformed id_token")
    return claims


def _check_audience_and_expiry(claims: dict, client_id: str, now: float | None = None) -> None:
    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    if not client_id or client_id not in audiences:
        raise IdTokenError("token was issued for another client")
    current = now if now is not None else time.time()
    try:
        expires = float(claims.get("exp"))
    except (TypeError, ValueError) as exc:
        raise IdTokenError("no expiry") from exc
    # 60s of clock skew either way.
    if expires < current - 60:
        raise IdTokenError("token has expired")
