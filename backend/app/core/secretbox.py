"""
core/secretbox.py
-----------------
Symmetric encryption for small application secrets at rest: TOTP seeds
(ZP-PRIV B08) and the temporary support password shown to the operator until
it is revealed (ZP-PRIV D.2). Fernet (AES-128-CBC + HMAC-SHA256) with a key
derived from PAYROLL_SECRET_KEY by HKDF, using a distinct ``purpose`` per use
so a ciphertext from one feature can never be decrypted as another.

Rotating PAYROLL_SECRET_KEY makes existing ciphertexts unreadable: MFA users
re-enrol, and live support passwords are simply unavailable (the grant can be
ended and re-requested). That is the intended fail-closed behaviour.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import settings


@lru_cache(maxsize=16)
def _fernet(purpose: str) -> Fernet:
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"zoiko-payroll-secretbox-v1",
        info=purpose.encode("utf-8"),
    ).derive(settings.PAYROLL_SECRET_KEY.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(plaintext: str, purpose: str) -> str:
    return _fernet(purpose).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: Optional[str], purpose: str) -> Optional[str]:
    """None when there is nothing to decrypt or the ciphertext is not ours."""
    if not ciphertext:
        return None
    try:
        return _fernet(purpose).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
