"""
core/crypto.py
---------------
Reversible symmetric encryption for secrets that the app must read back in
plaintext to use (e.g. a third-party IMAP/SMTP mailbox password) — unlike
core/security.py's bcrypt hashing, which is one-way and can only ever
*verify* a match, never recover the original value.

The encryption key is derived from the existing SECRET_KEY (already
required in .env for JWT signing) via HKDF, so no new secret needs to be
generated or added to .env — but the derived key is still cryptographically
independent of the JWT signing use of SECRET_KEY.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

_HKDF_INFO = b"zoiko-payroll-mail-credential-encryption-v1"


def _derive_fernet_key() -> bytes:
    # HKDF-SHA256 (RFC 5869), single-block since we only need 32 bytes.
    prk = hashlib.sha256(settings.PAYROLL_SECRET_KEY.encode("utf-8")).digest()
    okm = hashlib.sha256(prk + _HKDF_INFO + b"\x01").digest()
    return base64.urlsafe_b64encode(okm)


_fernet = Fernet(_derive_fernet_key())


def encrypt_secret(plain: str) -> str:
    """Encrypts a plaintext credential for storage. None/empty in, None out —
    callers should never write an encrypted empty string."""
    if not plain:
        return None
    return _fernet.encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str:
    """Decrypts a value previously written by encrypt_secret. Returns None
    if token is empty or can't be decrypted (e.g. it predates this scheme,
    or the value was corrupted) rather than raising — a bad stored value
    should surface as "credentials not configured", not crash a poll job."""
    if not token:
        return None
    try:
        return _fernet.decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
