"""
payroll/mexico_identity.py
--------------------------
Keyed identity tokens for Mexican identifiers (RFC, CURP, NSS) — Phase 4b,
plan §3, decision Q7 (stricter than HK D-19).

The statutory profile stores `v1:` HMAC-SHA256 tokens and the RFC's last 4,
never the identifier. The key is `MX_IDENTITY_TOKEN_KEY` (GCP Secret Manager
in production). A key derived from PAYROLL_SECRET_KEY under a fixed domain
label exists ONLY for development / test: in any other environment a missing
dedicated key refuses every Mexican identifier write. The key value is never
returned, audited or logged.
"""

from __future__ import annotations

import hashlib
import hmac
import os

from app.core.exceptions import BadRequestException

TOKEN_VERSION = "v1"
_FALLBACK_LABEL = b"zoiko-payroll/mx-identity-token/v1"
KEY_MISSING_MESSAGE = ("MX_IDENTITY_TOKEN_KEY is not configured — Mexican identifiers cannot be stored outside "
                       "development/test without a dedicated token key (Secret Manager).")


def _development_or_test() -> bool:
    """Same authority order as app/config.py's fail-closed guards: an explicit
    ENVIRONMENT / APP_ENV wins (development / dev / test / testing / local);
    only when neither is set is DEBUG consulted."""
    from app.config import settings

    env_name = (os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or "").strip().lower()
    if env_name:
        return env_name in ("development", "dev", "test", "testing", "local")
    return bool(settings.DEBUG)


def key_status() -> str:
    """DEDICATED / DEV_FALLBACK / MISSING (the last only outside dev/test)."""
    from app.config import settings

    if (settings.MX_IDENTITY_TOKEN_KEY or "").strip():
        return "DEDICATED"
    return "DEV_FALLBACK" if _development_or_test() else "MISSING"


def _key() -> bytes:
    from app.config import settings

    dedicated = (settings.MX_IDENTITY_TOKEN_KEY or "").strip()
    if dedicated:
        return dedicated.encode("utf-8")
    if not _development_or_test():
        raise BadRequestException(KEY_MISSING_MESSAGE)
    return hmac.new(settings.PAYROLL_SECRET_KEY.encode("utf-8"), _FALLBACK_LABEL, hashlib.sha256).digest()


def identity_token(kind: str, value: str) -> str:
    """Stable keyed token for one identifier kind (rfc / curp / nss)."""
    normalised = (value or "").strip().upper()
    digest = hmac.new(_key(), f"{kind}:{normalised}".encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{TOKEN_VERSION}:{digest}"
