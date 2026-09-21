"""
core/security.py
----------------
Password hashing + JWT create/verify for the standalone Payroll Platform.

JWT contract (namespaced — never accepted by the main platform):
  - signed with PAYROLL_SECRET_KEY (own secret, not the main platform's)
  - payload: sub=user email, user_id, role, organization_id (null for
    super_admin), iss=settings.JWT_ISSUER, type=access|refresh, exp, jti

Distinct token namespaces:
  - type=access        → normal login token (get_current_user)
  - type=refresh       → refresh token
  - type=assisted_access → SafeGuard assisted-access token. Same signing
    root but a DIFFERENT type value, so a normal endpoint that decodes via
    decode_access_token rejects it outright, and only the explicit assisted-
    access path in core/dependencies.py accepts it. Carries
    assisted_access_session_id + organization_id so every request is pinned
    to one active, time-boxed session.
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ASSISTED_ACCESS_TOKEN_TYPE = "assisted_access"


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def _encode(data: dict, expires_delta: timedelta, token_type: str) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({
        "exp": expire,
        "iss": settings.JWT_ISSUER,
        "type": token_type,
        # Unique per issued token (not per user/session) so a single
        # access or refresh token can be individually revoked on logout
        # (see auth/router.py's logout, core/dependencies.py's revocation
        # check) without invalidating any other token the same user holds.
        "jti": secrets.token_urlsafe(32),
    })
    return jwt.encode(to_encode, settings.PAYROLL_SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None, token_type: str = "access") -> str:
    delta = expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return _encode(data, delta, token_type)


def create_refresh_token(data: dict) -> str:
    return _encode(data, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS), "refresh")


def decode_access_token(token: str) -> Optional[dict]:
    return _decode(token, expected_type="access")


def decode_assisted_access_token(token: str) -> Optional[dict]:
    """Decode ONLY SafeGuard assisted-access tokens. Normal login tokens
    have type=access and never match this."""
    return _decode(token, expected_type=ASSISTED_ACCESS_TOKEN_TYPE)


def decode_refresh_token(token: str) -> Optional[dict]:
    return _decode(token, expected_type="refresh")


def _decode(token: str, expected_type: str) -> Optional[dict]:
    try:
        payload = jwt.decode(
            token,
            settings.PAYROLL_SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            issuer=settings.JWT_ISSUER,
        )
    except JWTError:
        return None
    if payload.get("type") != expected_type:
        return None
    if payload.get("iss") != settings.JWT_ISSUER:
        return None
    return payload
