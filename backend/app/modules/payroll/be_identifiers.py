"""Belgium identifier boundary (ZP-BE-ENG-001 Block A1; spec §15 "National
identifiers", BE-040; decision D14).

A worker's NISS / INSZ (or BIS number) and the employer's ONSS number are
"encrypted at rest, masked in the UI, never placed in logs, URLs, analytics or
idempotency keys". Pure helpers: no database, no routes, no logging of a value.
The vault (payroll_be_identifier_vault) stores only ``encrypt()``'s ciphertext
plus its key version and ``fingerprint()``'s keyed HMAC (duplicate
detection); ``decrypt()`` is the only way back to the digits, and a UI is only
ever given ``masked()``.

Same design as the Poland vault (pl_identifiers.py): AES-GCM with a MANDATORY
owner binding (associated data), so a ciphertext copied to another vault row,
employee, identifier type or organisation never decrypts; versioned keyring; a
separate never-rotated fingerprint key; NO fallback key of any kind.

Keys: ``settings.BE_IDENTIFIER_KEYRING`` (JSON {"1": "<32-byte key>"}) and
``settings.BE_IDENTIFIER_FINGERPRINT_KEY``. Both empty while Belgium is dormant
— every operation then refuses.

Normalisation checks the FORMAT only (digits, length shape). The NISS / BIS
check-digit rule and the ONSS number format are unverified (gap G-16): no
check-digit algorithm is applied until it is confirmed.
"""
import base64
import binascii
import hashlib
import hmac
import json
import os
import re
from typing import Dict, Optional, Tuple

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings

NISS, BIS, ONSS = "NISS", "BIS", "ONSS"
IDENTIFIER_TYPES = (NISS, BIS, ONSS)
SUBJECT_EMPLOYEE = "EMPLOYEE"
SUBJECT_EMPLOYER = "EMPLOYER"
SUBJECT_IDENTIFIERS = {SUBJECT_EMPLOYEE: (NISS, BIS), SUBJECT_EMPLOYER: (ONSS,)}
PURPOSE = "PAYROLL_STATUTORY"

# Format shapes only (G-16: no check digit is verified yet).
_PERSON_NUMBER = re.compile(r"^\d{11}$")          # NISS / BIS: eleven digits
_ONSS_NUMBER = re.compile(r"^\d{5,16}$")          # ONSS employer number: digits only
_SEPARATORS = re.compile(r"[\s./-]")

_NONCE_BYTES = 12
_KEY_BYTES = 32
_FINGERPRINT_LABEL = b"zp-be-identifier-fingerprint-v1:"
_AAD_LABEL = b"zp-be-identifier-vault-v1:"


class BeIdentifierError(ValueError):
    """Invalid identifier, keyring, owner binding or ciphertext.

    Messages are deliberately generic: they never contain the identifier, a
    key, or any part of either."""


def normalise(identifier_type: str, raw) -> str:
    """Canonical digits for one identifier type (format only, G-16)."""
    if identifier_type not in IDENTIFIER_TYPES:
        raise BeIdentifierError("unknown Belgian identifier type")
    if not isinstance(raw, str):
        raise BeIdentifierError(f"{identifier_type} must be text")
    value = _SEPARATORS.sub("", raw)
    pattern = _ONSS_NUMBER if identifier_type == ONSS else _PERSON_NUMBER
    if not pattern.fullmatch(value):
        raise BeIdentifierError(f"{identifier_type} does not have the expected format")
    return value


def _keyring() -> Dict[int, bytes]:
    raw = (getattr(settings, "BE_IDENTIFIER_KEYRING", "") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        raise BeIdentifierError("BE_IDENTIFIER_KEYRING is not valid JSON")
    if not isinstance(parsed, dict) or not parsed:
        raise BeIdentifierError("BE_IDENTIFIER_KEYRING must be a non-empty JSON object")
    keyring: Dict[int, bytes] = {}
    for version_text, value in parsed.items():
        try:
            version = int(version_text)
        except (TypeError, ValueError):
            raise BeIdentifierError("BE_IDENTIFIER_KEYRING has a non-integer key version")
        if version < 1:
            raise BeIdentifierError("BE_IDENTIFIER_KEYRING key versions start at 1")
        keyring[version] = _decode_key(value, "BE_IDENTIFIER_KEYRING")
    return keyring


def _decode_key(value, name: str) -> bytes:
    """Accept a literal 32-byte string, 64 hex characters, or base64."""
    if not isinstance(value, str):
        raise BeIdentifierError(f"{name} entries must be strings")
    if len(value) == _KEY_BYTES:
        key = value.encode("utf-8")
    elif len(value) == 2 * _KEY_BYTES and all(c in "0123456789abcdefABCDEF" for c in value):
        key = bytes.fromhex(value)
    else:
        try:
            padded = value + "=" * (-len(value) % 4)
            key = base64.urlsafe_b64decode(padded.encode("ascii"))
        except (ValueError, binascii.Error, UnicodeEncodeError):
            raise BeIdentifierError(f"{name} entry is not a 32-byte key")
    if len(key) != _KEY_BYTES:
        raise BeIdentifierError(f"{name} entry is not a 32-byte key")
    return key


def vault_owner(organization_id: int, subject_type: str, subject_id: Optional[int], identifier_type: str,
                vault_id) -> str:
    """Canonical AAD owner: organisation + subject (employee id, or the legal
    entity id for the employer ONSS number — None for the organisation itself) +
    identifier type + vault row id."""
    if vault_id is None:
        raise BeIdentifierError("a vault id is required to bind identifier ciphertext")
    allowed = SUBJECT_IDENTIFIERS.get(subject_type)
    if allowed is None:
        raise BeIdentifierError("unknown identifier vault subject")
    if identifier_type not in allowed:
        raise BeIdentifierError("identifier type does not belong to this subject")
    if subject_type == SUBJECT_EMPLOYEE and subject_id is None:
        raise BeIdentifierError("an employee identifier needs its employee")
    subject = "org" if subject_id is None else str(int(subject_id))
    return (f"org={int(organization_id)}/{subject_type.lower()}={subject}/"
            f"type={identifier_type.lower()}/vault={int(vault_id)}")


def _aad(owner: str) -> bytes:
    if not owner:
        raise BeIdentifierError("an owner binding is required")
    return _AAD_LABEL + owner.encode("utf-8")


def _type_from_owner(owner: str) -> str:
    match = re.search(r"/type=(niss|bis|onss)/", owner or "")
    if not match:
        raise BeIdentifierError("owner binding has no identifier type")
    return match.group(1).upper()


def encrypt(value: str, owner: str) -> Tuple[str, int]:
    """Encrypt a valid identifier with the newest keyring version, bound to
    ``owner`` (use :func:`vault_owner`; the identifier type is taken from it).
    Refuses when the keyring is not configured (no fallback key)."""
    plain = normalise(_type_from_owner(owner), value)
    keyring = _keyring()
    if not keyring:
        raise BeIdentifierError("BE_IDENTIFIER_KEYRING is not configured")
    version = max(keyring)
    nonce = os.urandom(_NONCE_BYTES)
    body = AESGCM(keyring[version]).encrypt(nonce, plain.encode("utf-8"), _aad(owner))
    return base64.urlsafe_b64encode(nonce + body).decode("ascii"), version


def decrypt(ciphertext: str, key_version: int, owner: str) -> str:
    """Decrypt with the key version that encrypted it and the same owner
    binding. Any failure raises BeIdentifierError (never InvalidTag)."""
    keyring = _keyring()
    if not keyring:
        raise BeIdentifierError("BE_IDENTIFIER_KEYRING is not configured")
    try:
        key = keyring[int(key_version)]
    except (KeyError, TypeError, ValueError):
        raise BeIdentifierError("identifier key version is not in the keyring")
    aad = _aad(owner)
    try:
        blob = base64.urlsafe_b64decode(str(ciphertext).encode("ascii"))
        nonce, body = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
        if len(nonce) != _NONCE_BYTES or not body:
            raise ValueError
        plain = AESGCM(key).decrypt(nonce, body, aad).decode("utf-8")
    except (InvalidTag, ValueError, TypeError, UnicodeError, binascii.Error):
        raise BeIdentifierError("identifier ciphertext could not be decrypted")
    return normalise(_type_from_owner(owner), plain)


def reencrypt(ciphertext: str, key_version: int, owner: str) -> Tuple[str, int]:
    """Key rotation: decrypt under the stored version, encrypt under the newest."""
    return encrypt(decrypt(ciphertext, key_version, owner), owner)


def _fingerprint_key() -> bytes:
    raw = (getattr(settings, "BE_IDENTIFIER_FINGERPRINT_KEY", "") or "").strip()
    if not raw:
        raise BeIdentifierError("BE_IDENTIFIER_FINGERPRINT_KEY is not configured")
    return _decode_key(raw, "BE_IDENTIFIER_FINGERPRINT_KEY")


def fingerprint(identifier_type: str, value: str) -> str:
    """Keyed HMAC-SHA256 used only to detect duplicates, per identifier type, on
    the never-rotated fingerprint key."""
    plain = normalise(identifier_type, value)
    derived = hmac.new(_fingerprint_key(), _FINGERPRINT_LABEL + identifier_type.encode("ascii"),
                       hashlib.sha256).digest()
    return hmac.new(derived, plain.encode("utf-8"), hashlib.sha256).hexdigest()


def masked(identifier_type: str) -> str:
    """The only representation a UI ever receives — no digit of the value."""
    return {NISS: "••.••.••-•••.••", BIS: "••.••.••-•••.••", ONSS: "•••••••-••"}[identifier_type]
