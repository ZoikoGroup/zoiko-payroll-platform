"""Malaysia identifier boundary (ZP-MY-ENG-001 Phase 2, spec §15, MY-029).

MyKad/NRIC, TIN, EPF and SOCSO member numbers and work-pass numbers are
"encrypted/tokenized; reveal privileged and audited" (spec §15). Pure
helpers: no database, no routes, no logging of a value. The vault
(payroll_my_identifier_vault) stores only ``encrypt()``'s ciphertext plus its
key version and ``fingerprint()``'s keyed HMAC (duplicate detection);
``decrypt()`` is the only way back to the value, and a UI is only ever given
``masked()``.

Same design as the Poland vault (pl_identifiers.py): AES-GCM with a MANDATORY
owner binding (associated data), so a ciphertext copied to another vault row,
employee, identifier type or organisation never decrypts; versioned keyring;
a separate never-rotated fingerprint key; NO fallback to PAYROLL_SECRET_KEY.
Every Malaysian vault identifier belongs to an employee.

Keys: ``settings.MY_IDENTIFIER_KEYRING`` (JSON {"1": "<32-byte key>"}) and
``settings.MY_IDENTIFIER_FINGERPRINT_KEY``. Both empty while Malaysia is
dormant — every operation then refuses.
"""
import base64
import binascii
import hashlib
import hmac
import json
import os
import re
from typing import Dict, Tuple

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings

NRIC, TIN, EPF_NO, SOCSO_NO, WORK_PASS_NO = "NRIC", "TIN", "EPF_NO", "SOCSO_NO", "WORK_PASS_NO"
IDENTIFIER_TYPES = (NRIC, TIN, EPF_NO, SOCSO_NO, WORK_PASS_NO)
PURPOSE = "PAYROLL_STATUTORY"

_NONCE_BYTES = 12
_FINGERPRINT_LABEL = b"zp-my-identifier-fingerprint-v1:"
_AAD_LABEL = b"zp-my-identifier-vault-v1:"


class MyIdentifierError(ValueError):
    """Invalid identifier, keyring, owner binding or ciphertext.

    Messages are deliberately generic: they never contain the identifier, a
    key, or any part of either."""


def normalise(identifier_type: str, raw) -> str:
    """Canonical form for one identifier type; raises when invalid.

    NRIC: 12 digits with a real YYMMDD date and a non-zero place code (MyKad
    has no check digit). TIN: letters + digits. EPF / SOCSO / work-pass
    numbers: 6-20 letters or digits (exact authority formats pending G1)."""
    from app.modules.payroll.employee_validation import my_member_no_format_ok, my_nric_is_valid, my_tin_format_ok

    if identifier_type not in IDENTIFIER_TYPES:
        raise MyIdentifierError("unknown Malaysian identifier type")
    if not isinstance(raw, str):
        raise MyIdentifierError(f"{identifier_type} must be text")
    value = re.sub(r"[\s-]", "", raw).upper()
    if identifier_type == NRIC:
        if not my_nric_is_valid(value):
            raise MyIdentifierError("NRIC is not valid")
        return value
    if identifier_type == TIN:
        if not my_tin_format_ok(value):
            raise MyIdentifierError("TIN is not valid")
        return value
    if not my_member_no_format_ok(value):
        raise MyIdentifierError(f"{identifier_type} is not valid")
    return value


def _keyring() -> Dict[int, bytes]:
    raw = (getattr(settings, "MY_IDENTIFIER_KEYRING", "") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        raise MyIdentifierError("MY_IDENTIFIER_KEYRING is not valid JSON")
    if not isinstance(parsed, dict) or not parsed:
        raise MyIdentifierError("MY_IDENTIFIER_KEYRING must be a non-empty JSON object")
    keyring: Dict[int, bytes] = {}
    for version_text, value in parsed.items():
        try:
            version = int(version_text)
        except (TypeError, ValueError):
            raise MyIdentifierError("MY_IDENTIFIER_KEYRING has a non-integer key version")
        if version < 1:
            raise MyIdentifierError("MY_IDENTIFIER_KEYRING key versions start at 1")
        keyring[version] = _decode_key(value, "MY_IDENTIFIER_KEYRING")
    return keyring


def _decode_key(value, name: str) -> bytes:
    """Accept a literal 32-byte string, 64 hex characters, or base64."""
    if not isinstance(value, str):
        raise MyIdentifierError(f"{name} entries must be strings")
    if len(value) == 32:
        key = value.encode("utf-8")
    elif len(value) == 64 and all(c in "0123456789abcdefABCDEF" for c in value):
        key = bytes.fromhex(value)
    else:
        try:
            padded = value + "=" * (-len(value) % 4)
            key = base64.urlsafe_b64decode(padded.encode("ascii"))
        except (ValueError, binascii.Error, UnicodeEncodeError):
            raise MyIdentifierError(f"{name} entry is not a 32-byte key")
    if len(key) != 32:
        raise MyIdentifierError(f"{name} entry is not a 32-byte key")
    return key


def vault_owner(organization_id: int, employee_id: int, identifier_type: str, vault_id) -> str:
    """Canonical AAD owner for a vault row: organisation + employee +
    identifier type + vault row id."""
    if vault_id is None:
        raise MyIdentifierError("a vault id is required to bind identifier ciphertext")
    if employee_id is None:
        raise MyIdentifierError("a Malaysian identifier needs its employee")
    if identifier_type not in IDENTIFIER_TYPES:
        raise MyIdentifierError("unknown Malaysian identifier type")
    return (f"org={int(organization_id)}/employee={int(employee_id)}/"
            f"type={identifier_type.lower()}/vault={int(vault_id)}")


def _aad(owner: str) -> bytes:
    if not owner:
        raise MyIdentifierError("an owner binding is required")
    return _AAD_LABEL + owner.encode("utf-8")


def type_from_owner(owner: str) -> str:
    match = re.search(r"/type=(nric|tin|epf_no|socso_no|work_pass_no)/", owner or "")
    if not match:
        raise MyIdentifierError("owner binding has no identifier type")
    return match.group(1).upper()


def encrypt(value: str, owner: str) -> Tuple[str, int]:
    """Encrypt a valid identifier with the newest keyring version, bound to
    ``owner`` (use :func:`vault_owner`; the identifier type is taken from it)."""
    plain = normalise(type_from_owner(owner), value)
    keyring = _keyring()
    if not keyring:
        raise MyIdentifierError("MY_IDENTIFIER_KEYRING is not configured")
    version = max(keyring)
    nonce = os.urandom(_NONCE_BYTES)
    body = AESGCM(keyring[version]).encrypt(nonce, plain.encode("utf-8"), _aad(owner))
    return base64.urlsafe_b64encode(nonce + body).decode("ascii"), version


def decrypt(ciphertext: str, key_version: int, owner: str) -> str:
    """Decrypt with the key version that encrypted it and the same owner
    binding. Any failure raises MyIdentifierError (never InvalidTag)."""
    keyring = _keyring()
    if not keyring:
        raise MyIdentifierError("MY_IDENTIFIER_KEYRING is not configured")
    try:
        key = keyring[int(key_version)]
    except (KeyError, TypeError, ValueError):
        raise MyIdentifierError("identifier key version is not in the keyring")
    aad = _aad(owner)
    try:
        blob = base64.urlsafe_b64decode(str(ciphertext).encode("ascii"))
        nonce, body = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
        if len(nonce) != _NONCE_BYTES or not body:
            raise ValueError
        plain = AESGCM(key).decrypt(nonce, body, aad).decode("utf-8")
    except (InvalidTag, ValueError, TypeError, UnicodeError, binascii.Error):
        raise MyIdentifierError("identifier ciphertext could not be decrypted")
    return normalise(type_from_owner(owner), plain)


def reencrypt(ciphertext: str, key_version: int, owner: str) -> Tuple[str, int]:
    """Key rotation: decrypt under the stored version, encrypt under the newest."""
    return encrypt(decrypt(ciphertext, key_version, owner), owner)


def _fingerprint_key() -> bytes:
    raw = (getattr(settings, "MY_IDENTIFIER_FINGERPRINT_KEY", "") or "").strip()
    if not raw:
        raise MyIdentifierError("MY_IDENTIFIER_FINGERPRINT_KEY is not configured")
    return _decode_key(raw, "MY_IDENTIFIER_FINGERPRINT_KEY")


def fingerprint(identifier_type: str, value: str) -> str:
    """Keyed HMAC-SHA256 used only to detect duplicates, per identifier type,
    on the never-rotated fingerprint key."""
    plain = normalise(identifier_type, value)
    derived = hmac.new(_fingerprint_key(), _FINGERPRINT_LABEL + identifier_type.encode("ascii"),
                       hashlib.sha256).digest()
    return hmac.new(derived, plain.encode("utf-8"), hashlib.sha256).hexdigest()


def masked(identifier_type: str) -> str:
    """The only representation a UI ever receives — no character of the value."""
    return {NRIC: "••••••-••-••••", TIN: "•••••••••••", EPF_NO: "••••••••", SOCSO_NO: "••••••••",
            WORK_PASS_NO: "••••••••"}[identifier_type]
