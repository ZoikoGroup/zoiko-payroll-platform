"""Japan My Number boundary (ZP-JP-ENG-001 Phase 2).

Pure helpers: no database, no routes, no logging of the number. The vault
stores only ``encrypt()``'s ciphertext plus its key version and
``fingerprint()``'s keyed HMAC (for duplicate detection). ``decrypt()`` is the
only way back to the 12 digits, and a UI is only ever given ``masked()``.

The keyring is a JSON object in ``settings.JP_MY_NUMBER_KEYRING`` mapping a
key version to a 32-byte key, e.g. ``{"1": "<32-byte key>"}``. Rotation means
adding ``"2"``; rows encrypted under ``"1"`` still decrypt because the old key
stays in the keyring. There is deliberately NO fallback to
``PAYROLL_SECRET_KEY``: rotating that would make every stored number
unreadable.

``fingerprint()`` uses its own key, ``settings.JP_MY_NUMBER_FINGERPRINT_KEY``,
which is never rotated: a fingerprint keyed on the newest encryption key
would change at every rotation and duplicate detection would silently stop
matching the rows already stored.
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

PURPOSE = "TAX_SOCIAL_INSURANCE"

_WEIGHTS = (6, 5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
_DIGITS = re.compile(r"^\d{12}$")
_NONCE_BYTES = 12
_FINGERPRINT_LABEL = b"zp-jp-my-number-fingerprint-v1"


class MyNumberError(ValueError):
    """Raised for an invalid number, keyring or ciphertext.

    Messages are deliberately generic: they never contain the number, a key,
    or any part of either.
    """


def _keyring() -> Dict[int, bytes]:
    """Parse ``settings.JP_MY_NUMBER_KEYRING`` into ``{version: 32-byte key}``."""
    raw = (getattr(settings, "JP_MY_NUMBER_KEYRING", "") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        raise MyNumberError("JP_MY_NUMBER_KEYRING is not valid JSON")
    if not isinstance(parsed, dict) or not parsed:
        raise MyNumberError("JP_MY_NUMBER_KEYRING must be a non-empty JSON object")

    keyring: Dict[int, bytes] = {}
    for version_text, value in parsed.items():
        try:
            version = int(version_text)
        except (TypeError, ValueError):
            raise MyNumberError("JP_MY_NUMBER_KEYRING has a non-integer key version")
        if version < 1:
            raise MyNumberError("JP_MY_NUMBER_KEYRING key versions start at 1")
        keyring[version] = _decode_key(value)
    return keyring


def _decode_key(value) -> bytes:
    """Accept a literal 32-byte string, 64 hex characters, or base64."""
    if not isinstance(value, str):
        raise MyNumberError("JP_MY_NUMBER_KEYRING entries must be strings")
    if len(value) == 32:
        key = value.encode("utf-8")
    elif len(value) == 64 and all(c in "0123456789abcdefABCDEF" for c in value):
        key = bytes.fromhex(value)
    else:
        try:
            padded = value + "=" * (-len(value) % 4)
            key = base64.urlsafe_b64decode(padded.encode("ascii"))
        except (ValueError, binascii.Error, UnicodeEncodeError):
            raise MyNumberError("JP_MY_NUMBER_KEYRING entry is not a 32-byte key")
    if len(key) != 32:
        raise MyNumberError("JP_MY_NUMBER_KEYRING entry is not a 32-byte key")
    return key


def validate(number: str) -> str:
    """Return ``number`` when it is 12 digits with a correct check digit."""
    if not isinstance(number, str) or not _DIGITS.match(number):
        raise MyNumberError("My Number must be exactly 12 digits")
    total = sum(int(digit) * weight for digit, weight in zip(number[:11], _WEIGHTS))
    check = 11 - (total % 11)
    if check >= 10:
        check = 0
    if int(number[11]) != check:
        raise MyNumberError("My Number check digit is invalid")
    return number


def encrypt(number: str) -> Tuple[str, int]:
    """Encrypt a validated My Number with the newest keyring version."""
    validate(number)
    keyring = _keyring()
    if not keyring:
        raise MyNumberError("JP_MY_NUMBER_KEYRING is not configured")
    version = max(keyring)
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(keyring[version]).encrypt(nonce, number.encode("utf-8"), None)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii"), version


def decrypt(ciphertext: str, key_version: int) -> str:
    """Decrypt a stored value with the key version that encrypted it."""
    keyring = _keyring()
    if not keyring:
        raise MyNumberError("JP_MY_NUMBER_KEYRING is not configured")
    try:
        key = keyring[int(key_version)]
    except (KeyError, TypeError, ValueError):
        raise MyNumberError("My Number key version is not in the keyring")
    try:
        blob = base64.urlsafe_b64decode(str(ciphertext).encode("ascii"))
        nonce, body = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
        if len(nonce) != _NONCE_BYTES or not body:
            raise ValueError
        number = AESGCM(key).decrypt(nonce, body, None).decode("utf-8")
    except (InvalidTag, ValueError, TypeError, UnicodeError, binascii.Error):
        # InvalidTag (tampered data or the wrong key) is not a ValueError.
        raise MyNumberError("My Number ciphertext could not be decrypted")
    return validate(number)


def _fingerprint_key() -> bytes:
    raw = (getattr(settings, "JP_MY_NUMBER_FINGERPRINT_KEY", "") or "").strip()
    if not raw:
        raise MyNumberError("JP_MY_NUMBER_FINGERPRINT_KEY is not configured")
    return _decode_key(raw)


def fingerprint(number: str) -> str:
    """Keyed HMAC-SHA256 used only to detect duplicate My Numbers. Keyed on
    the dedicated, never-rotated fingerprint key so it is stable across
    encryption-key rotations."""
    validate(number)
    derived = hmac.new(_fingerprint_key(), _FINGERPRINT_LABEL, hashlib.sha256).digest()
    return hmac.new(derived, number.encode("utf-8"), hashlib.sha256).hexdigest()


def masked() -> str:
    """The only representation a UI ever receives."""
    return "\u2022\u2022\u2022\u2022 \u2022\u2022\u2022\u2022 \u2022\u2022\u2022\u2022"
