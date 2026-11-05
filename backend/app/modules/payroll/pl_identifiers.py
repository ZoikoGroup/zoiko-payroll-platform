"""Poland identifier boundary (ZP-PL-ENG-001 Phase 2, spec §13, PL-025).

PESEL, an employee's NIP and the employer's ZUS contribution account (NRS)
are "encrypted at rest and masked in logs/analytics/support tools" (spec §13).
Pure helpers: no database, no routes, no logging of a value. The vault
(payroll_pl_identifier_vault) stores only ``encrypt()``'s ciphertext plus its
key version and ``fingerprint()``'s keyed HMAC (duplicate detection);
``decrypt()`` is the only way back to the digits, and a UI is only ever given
``masked()``.

Same design as the New Zealand IRD vault (nz_ird_number.py), itself the Japan
My Number vault's: AES-GCM with a MANDATORY owner binding (associated data),
so a ciphertext copied to another vault row, employee, identifier type or
organisation never decrypts; versioned keyring; a separate never-rotated
fingerprint key; NO fallback to PAYROLL_SECRET_KEY.

Keys: ``settings.PL_IDENTIFIER_KEYRING`` (JSON {"1": "<32-byte key>"}) and
``settings.PL_IDENTIFIER_FINGERPRINT_KEY``. Both empty while Poland is
dormant — every operation then refuses.
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

PESEL, NIP, NRS = "PESEL", "NIP", "NRS"
IDENTIFIER_TYPES = (PESEL, NIP, NRS)
SUBJECT_EMPLOYEE = "EMPLOYEE"
SUBJECT_EMPLOYER = "EMPLOYER"
SUBJECT_IDENTIFIERS = {SUBJECT_EMPLOYEE: (PESEL, NIP), SUBJECT_EMPLOYER: (NRS,)}
PURPOSE = "PAYROLL_STATUTORY"

_NONCE_BYTES = 12
_FINGERPRINT_LABEL = b"zp-pl-identifier-fingerprint-v1:"
_AAD_LABEL = b"zp-pl-identifier-vault-v1:"


class PlIdentifierError(ValueError):
    """Invalid identifier, keyring, owner binding or ciphertext.

    Messages are deliberately generic: they never contain the identifier, a
    key, or any part of either."""


def normalise(identifier_type: str, raw) -> str:
    """Canonical digits for one identifier type; raises when invalid.

    PESEL: 11 digits with a real birth date and check digit. NIP: 10 digits
    with the mod-11 check digit. NRS: the 26-digit Polish account number (NRB),
    accepted with or without the "PL" IBAN prefix, mod-97 checked."""
    from app.modules.payroll.employee_validation import iban_checksum_ok, pl_nip_is_valid, pl_pesel_is_valid

    if identifier_type not in IDENTIFIER_TYPES:
        raise PlIdentifierError("unknown Polish identifier type")
    if not isinstance(raw, str):
        raise PlIdentifierError(f"{identifier_type} must be text")
    value = re.sub(r"[\s-]", "", raw).upper()
    if identifier_type == PESEL:
        if not pl_pesel_is_valid(value):
            raise PlIdentifierError("PESEL is not valid")
        return value
    if identifier_type == NIP:
        if not pl_nip_is_valid(value):
            raise PlIdentifierError("NIP is not valid")
        return value
    digits = value[2:] if value.startswith("PL") else value
    if not re.fullmatch(r"\d{26}", digits) or not iban_checksum_ok("PL" + digits):
        raise PlIdentifierError("NRS is not a valid Polish account number")
    return digits


def _keyring() -> Dict[int, bytes]:
    raw = (getattr(settings, "PL_IDENTIFIER_KEYRING", "") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        raise PlIdentifierError("PL_IDENTIFIER_KEYRING is not valid JSON")
    if not isinstance(parsed, dict) or not parsed:
        raise PlIdentifierError("PL_IDENTIFIER_KEYRING must be a non-empty JSON object")
    keyring: Dict[int, bytes] = {}
    for version_text, value in parsed.items():
        try:
            version = int(version_text)
        except (TypeError, ValueError):
            raise PlIdentifierError("PL_IDENTIFIER_KEYRING has a non-integer key version")
        if version < 1:
            raise PlIdentifierError("PL_IDENTIFIER_KEYRING key versions start at 1")
        keyring[version] = _decode_key(value, "PL_IDENTIFIER_KEYRING")
    return keyring


def _decode_key(value, name: str) -> bytes:
    """Accept a literal 32-byte string, 64 hex characters, or base64."""
    if not isinstance(value, str):
        raise PlIdentifierError(f"{name} entries must be strings")
    if len(value) == 32:
        key = value.encode("utf-8")
    elif len(value) == 64 and all(c in "0123456789abcdefABCDEF" for c in value):
        key = bytes.fromhex(value)
    else:
        try:
            padded = value + "=" * (-len(value) % 4)
            key = base64.urlsafe_b64decode(padded.encode("ascii"))
        except (ValueError, binascii.Error, UnicodeEncodeError):
            raise PlIdentifierError(f"{name} entry is not a 32-byte key")
    if len(key) != 32:
        raise PlIdentifierError(f"{name} entry is not a 32-byte key")
    return key


def vault_owner(organization_id: int, subject_type: str, subject_id: Optional[int], identifier_type: str,
                vault_id) -> str:
    """Canonical AAD owner for a vault row: organisation + subject (employee id,
    or the legal entity id for the employer NRS — None for the organisation
    itself) + identifier type + vault row id."""
    if vault_id is None:
        raise PlIdentifierError("a vault id is required to bind identifier ciphertext")
    allowed = SUBJECT_IDENTIFIERS.get(subject_type)
    if allowed is None:
        raise PlIdentifierError("unknown identifier vault subject")
    if identifier_type not in allowed:
        raise PlIdentifierError("identifier type does not belong to this subject")
    if subject_type == SUBJECT_EMPLOYEE and subject_id is None:
        raise PlIdentifierError("an employee identifier needs its employee")
    subject = "org" if subject_id is None else str(int(subject_id))
    return (f"org={int(organization_id)}/{subject_type.lower()}={subject}/"
            f"type={identifier_type.lower()}/vault={int(vault_id)}")


def _aad(owner: str) -> bytes:
    if not owner:
        raise PlIdentifierError("an owner binding is required")
    return _AAD_LABEL + owner.encode("utf-8")


def _type_from_owner(owner: str) -> str:
    match = re.search(r"/type=(pesel|nip|nrs)/", owner or "")
    if not match:
        raise PlIdentifierError("owner binding has no identifier type")
    return match.group(1).upper()


def encrypt(value: str, owner: str) -> Tuple[str, int]:
    """Encrypt a valid identifier with the newest keyring version, bound to
    ``owner`` (use :func:`vault_owner`; the identifier type is taken from it)."""
    plain = normalise(_type_from_owner(owner), value)
    keyring = _keyring()
    if not keyring:
        raise PlIdentifierError("PL_IDENTIFIER_KEYRING is not configured")
    version = max(keyring)
    nonce = os.urandom(_NONCE_BYTES)
    body = AESGCM(keyring[version]).encrypt(nonce, plain.encode("utf-8"), _aad(owner))
    return base64.urlsafe_b64encode(nonce + body).decode("ascii"), version


def decrypt(ciphertext: str, key_version: int, owner: str) -> str:
    """Decrypt with the key version that encrypted it and the same owner
    binding. Any failure raises PlIdentifierError (never InvalidTag)."""
    keyring = _keyring()
    if not keyring:
        raise PlIdentifierError("PL_IDENTIFIER_KEYRING is not configured")
    try:
        key = keyring[int(key_version)]
    except (KeyError, TypeError, ValueError):
        raise PlIdentifierError("identifier key version is not in the keyring")
    aad = _aad(owner)
    try:
        blob = base64.urlsafe_b64decode(str(ciphertext).encode("ascii"))
        nonce, body = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
        if len(nonce) != _NONCE_BYTES or not body:
            raise ValueError
        plain = AESGCM(key).decrypt(nonce, body, aad).decode("utf-8")
    except (InvalidTag, ValueError, TypeError, UnicodeError, binascii.Error):
        raise PlIdentifierError("identifier ciphertext could not be decrypted")
    return normalise(_type_from_owner(owner), plain)


def reencrypt(ciphertext: str, key_version: int, owner: str) -> Tuple[str, int]:
    """Key rotation: decrypt under the stored version, encrypt under the newest."""
    return encrypt(decrypt(ciphertext, key_version, owner), owner)


def _fingerprint_key() -> bytes:
    raw = (getattr(settings, "PL_IDENTIFIER_FINGERPRINT_KEY", "") or "").strip()
    if not raw:
        raise PlIdentifierError("PL_IDENTIFIER_FINGERPRINT_KEY is not configured")
    return _decode_key(raw, "PL_IDENTIFIER_FINGERPRINT_KEY")


def fingerprint(identifier_type: str, value: str) -> str:
    """Keyed HMAC-SHA256 used only to detect duplicates, per identifier type
    (a PESEL and an NRS never collide), on the never-rotated fingerprint key."""
    plain = normalise(identifier_type, value)
    derived = hmac.new(_fingerprint_key(), _FINGERPRINT_LABEL + identifier_type.encode("ascii"),
                       hashlib.sha256).digest()
    return hmac.new(derived, plain.encode("utf-8"), hashlib.sha256).hexdigest()


def masked(identifier_type: str) -> str:
    """The only representation a UI ever receives — no digit of the value."""
    return {PESEL: "•••••••••••", NIP: "•••-•••-••-••", NRS: "•• •••• •••• •••• •••• •••• ••••"}[identifier_type]
