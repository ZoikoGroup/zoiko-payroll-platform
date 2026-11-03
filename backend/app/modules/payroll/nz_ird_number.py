"""New Zealand IRD-number boundary (ZP-NZ-ENG-001 Phase 2, spec §13, NZ-023).

Pure helpers: no database, no routes, no logging of the number. The vault
(payroll_nz_ird_vault) stores only ``encrypt()``'s ciphertext plus its key
version and ``fingerprint()``'s keyed HMAC (for duplicate detection).
``decrypt()`` is the only way back to the digits, and a UI is only ever given
``masked()``.

The design is the Japan My Number vault's (japan_my_number.py), with two
differences that tighten it:
  * the owner binding (AES-GCM associated data) is MANDATORY — there is no
    legacy unbound format, so a ciphertext copied to another vault row,
    employee or organisation never decrypts;
  * the IRD check digit is Inland Revenue's modulus-11 algorithm
    (core.jurisdiction.nz_ird_number_valid).

The keyring is a JSON object in ``settings.NZ_IRD_KEYRING`` mapping a key
version to a 32-byte key, e.g. ``{"1": "<32-byte key>"}``. Rotation means
adding ``"2"``; rows encrypted under ``"1"`` still decrypt because the old key
stays in the keyring. There is deliberately NO fallback to
``PAYROLL_SECRET_KEY``.

``fingerprint()`` uses its own key, ``settings.NZ_IRD_FINGERPRINT_KEY``, which
is never rotated, so duplicate detection keeps matching across rotations.
"""
import base64
import binascii
import hashlib
import hmac
import json
import os
from typing import Dict, Optional, Tuple

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings
from app.core.jurisdiction import nz_ird_number_valid

PURPOSE = "PAYE_PAYDAY_FILING"
SUBJECT_EMPLOYEE = "EMPLOYEE"
SUBJECT_EMPLOYER = "EMPLOYER"

_NONCE_BYTES = 12
_FINGERPRINT_LABEL = b"zp-nz-ird-number-fingerprint-v1"
_AAD_LABEL = b"zp-nz-ird-vault-v1:"


class IrdNumberError(ValueError):
    """Raised for an invalid number, keyring, owner binding or ciphertext.

    Messages are deliberately generic: they never contain the number, a key,
    or any part of either."""


def normalise(raw) -> str:
    """Digits only (spaces and dashes removed), 8-digit numbers left-padded to
    9. Raises when the result is not a valid IRD number."""
    if not isinstance(raw, str):
        raise IrdNumberError("IRD number must be text")
    digits = "".join(ch for ch in raw if ch not in " -")
    if not nz_ird_number_valid(digits):
        raise IrdNumberError("IRD number is not valid")
    return digits.zfill(9)


def validate(raw) -> str:
    return normalise(raw)


def _keyring() -> Dict[int, bytes]:
    raw = (getattr(settings, "NZ_IRD_KEYRING", "") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        raise IrdNumberError("NZ_IRD_KEYRING is not valid JSON")
    if not isinstance(parsed, dict) or not parsed:
        raise IrdNumberError("NZ_IRD_KEYRING must be a non-empty JSON object")
    keyring: Dict[int, bytes] = {}
    for version_text, value in parsed.items():
        try:
            version = int(version_text)
        except (TypeError, ValueError):
            raise IrdNumberError("NZ_IRD_KEYRING has a non-integer key version")
        if version < 1:
            raise IrdNumberError("NZ_IRD_KEYRING key versions start at 1")
        keyring[version] = _decode_key(value, "NZ_IRD_KEYRING")
    return keyring


def _decode_key(value, name: str) -> bytes:
    """Accept a literal 32-byte string, 64 hex characters, or base64."""
    if not isinstance(value, str):
        raise IrdNumberError(f"{name} entries must be strings")
    if len(value) == 32:
        key = value.encode("utf-8")
    elif len(value) == 64 and all(c in "0123456789abcdefABCDEF" for c in value):
        key = bytes.fromhex(value)
    else:
        try:
            padded = value + "=" * (-len(value) % 4)
            key = base64.urlsafe_b64decode(padded.encode("ascii"))
        except (ValueError, binascii.Error, UnicodeEncodeError):
            raise IrdNumberError(f"{name} entry is not a 32-byte key")
    if len(key) != 32:
        raise IrdNumberError(f"{name} entry is not a 32-byte key")
    return key


def vault_owner(organization_id: int, subject_type: str, subject_id: Optional[int], vault_id) -> str:
    """Canonical AAD owner for a vault row: organisation + subject (the
    employee id, or the legal entity id for an employer number — None for the
    organisation itself) + the vault row id. Moving the ciphertext anywhere
    else makes decryption fail instead of revealing a different number."""
    if vault_id is None:
        raise IrdNumberError("a vault id is required to bind IRD-number ciphertext")
    if subject_type not in (SUBJECT_EMPLOYEE, SUBJECT_EMPLOYER):
        raise IrdNumberError("unknown IRD vault subject")
    if subject_type == SUBJECT_EMPLOYEE and subject_id is None:
        raise IrdNumberError("an employee IRD number needs its employee")
    subject = "org" if subject_id is None else str(int(subject_id))
    return f"org={int(organization_id)}/{subject_type.lower()}={subject}/vault={int(vault_id)}"


def _aad(owner: str) -> bytes:
    if not owner:
        raise IrdNumberError("an owner binding is required")
    return _AAD_LABEL + owner.encode("utf-8")


def encrypt(number: str, owner: str) -> Tuple[str, int]:
    """Encrypt a valid IRD number with the newest keyring version, bound to
    ``owner`` (use :func:`vault_owner`)."""
    plain = normalise(number)
    keyring = _keyring()
    if not keyring:
        raise IrdNumberError("NZ_IRD_KEYRING is not configured")
    version = max(keyring)
    nonce = os.urandom(_NONCE_BYTES)
    body = AESGCM(keyring[version]).encrypt(nonce, plain.encode("utf-8"), _aad(owner))
    return base64.urlsafe_b64encode(nonce + body).decode("ascii"), version


def decrypt(ciphertext: str, key_version: int, owner: str) -> str:
    """Decrypt a stored value with the key version that encrypted it and the
    same owner binding. Any failure — tampering, a wrong key, a wrong owner —
    raises IrdNumberError (never cryptography's InvalidTag)."""
    keyring = _keyring()
    if not keyring:
        raise IrdNumberError("NZ_IRD_KEYRING is not configured")
    try:
        key = keyring[int(key_version)]
    except (KeyError, TypeError, ValueError):
        raise IrdNumberError("IRD-number key version is not in the keyring")
    aad = _aad(owner)
    try:
        blob = base64.urlsafe_b64decode(str(ciphertext).encode("ascii"))
        nonce, body = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
        if len(nonce) != _NONCE_BYTES or not body:
            raise ValueError
        plain = AESGCM(key).decrypt(nonce, body, aad).decode("utf-8")
    except (InvalidTag, ValueError, TypeError, UnicodeError, binascii.Error):
        raise IrdNumberError("IRD-number ciphertext could not be decrypted")
    return normalise(plain)


def reencrypt(ciphertext: str, key_version: int, owner: str) -> Tuple[str, int]:
    """Key rotation: decrypt under the stored version, encrypt under the newest."""
    return encrypt(decrypt(ciphertext, key_version, owner), owner)


def _fingerprint_key() -> bytes:
    raw = (getattr(settings, "NZ_IRD_FINGERPRINT_KEY", "") or "").strip()
    if not raw:
        raise IrdNumberError("NZ_IRD_FINGERPRINT_KEY is not configured")
    return _decode_key(raw, "NZ_IRD_FINGERPRINT_KEY")


def fingerprint(number: str) -> str:
    """Keyed HMAC-SHA256 used only to detect duplicate IRD numbers, on the
    dedicated never-rotated fingerprint key."""
    plain = normalise(number)
    derived = hmac.new(_fingerprint_key(), _FINGERPRINT_LABEL, hashlib.sha256).digest()
    return hmac.new(derived, plain.encode("utf-8"), hashlib.sha256).hexdigest()


def masked() -> str:
    """The only representation a UI ever receives — no digit of the number."""
    return "•••-•••-•••"
