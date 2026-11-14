"""Employee contact fields - email and phone - normalised and validated.

Employee email and phone used to be stored as free text: the API accepted
letters in a phone number and any string as an email, and only the browser
applied a (loose, inconsistent) check. Every employee write path now runs
these helpers on the server:

  * email: trimmed and lowercased; one "@", a dotted domain, no spaces or
    consecutive dots, RFC 5321 length limits (64 local / 254 total).
  * phone: digits, spaces, ( ) - . and a leading "+" (or "00") only; parsed
    with libphonenumber (the ``phonenumbers`` package) and stored in E.164
    (+<country code><number>). A number without a country code is read as a
    number of the employee's own payroll country; a "+" number from any
    country is accepted (an employee may hold a foreign mobile).

The rules are mirrored for the UI in frontend/src/utils/contactValidation.js
(same messages); the server stays the authority.
"""
import re
from typing import Optional

import phonenumbers

EMAIL_MAX_LENGTH = 254
EMAIL_LOCAL_MAX_LENGTH = 64

EMAIL_INVALID = "Enter a valid email address, for example name@company.com."
PHONE_BAD_CHARACTERS = "Phone number may contain only digits, spaces, ( ) - . and a leading +."
PHONE_INVALID = "Enter a valid phone number, for example +44 7700 900123."
PHONE_NEEDS_COUNTRY_CODE = "Enter the phone number with its country code, for example +44 7700 900123."

_EMAIL_LOCAL = re.compile(r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*$")
_EMAIL_DOMAIN_LABEL = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_EMAIL_TLD = re.compile(r"^[A-Za-z]{2,63}$")
_PHONE_ALLOWED = re.compile(r"^\+?[0-9\s().-]+$")

# Payroll country codes that are not the ISO region libphonenumber expects.
_PHONE_REGION_ALIASES = {"UK": "GB"}


class ContactValidationError(ValueError):
    """A contact field failed validation; str(exc) is safe to show the user."""


def normalize_email(value) -> Optional[str]:
    """Trimmed, lowercased email, or None for a blank value. Raises
    ContactValidationError when the address is not a valid email."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.lower()
    if len(text) > EMAIL_MAX_LENGTH or text.count("@") != 1 or any(ch.isspace() for ch in text):
        raise ContactValidationError(EMAIL_INVALID)
    local, domain = text.split("@")
    if not local or len(local) > EMAIL_LOCAL_MAX_LENGTH or not _EMAIL_LOCAL.match(local):
        raise ContactValidationError(EMAIL_INVALID)
    labels = domain.split(".")
    if len(labels) < 2 or not all(_EMAIL_DOMAIN_LABEL.match(label) for label in labels):
        raise ContactValidationError(EMAIL_INVALID)
    if not _EMAIL_TLD.match(labels[-1]):
        raise ContactValidationError(EMAIL_INVALID)
    return text


def phone_region(country_code: Optional[str]) -> Optional[str]:
    """libphonenumber region for a payroll country code (UK -> GB)."""
    code = str(country_code or "").strip().upper()
    if not code:
        return None
    code = _PHONE_REGION_ALIASES.get(code, code)
    return code if code in phonenumbers.SUPPORTED_REGIONS else None


def normalize_phone(value, country_code: Optional[str] = None) -> Optional[str]:
    """E.164 phone number, or None for a blank value. A number without a
    country code is read as a number of `country_code`. Raises
    ContactValidationError for letters or symbols, or a number that is not a
    possible number for its country."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if not _PHONE_ALLOWED.match(text):
        raise ContactValidationError(PHONE_BAD_CHARACTERS)
    if text.startswith("00"):
        text = "+" + text[2:]
    region = None
    if not text.startswith("+"):
        region = phone_region(country_code)
        if region is None:
            raise ContactValidationError(PHONE_NEEDS_COUNTRY_CODE)
    try:
        number = phonenumbers.parse(text, region)
    except phonenumbers.NumberParseException:
        raise ContactValidationError(PHONE_INVALID) from None
    # "Possible" (right length and shape for the country), not "valid": a
    # strict validity check would reject newly allocated number ranges.
    if not phonenumbers.is_possible_number(number):
        raise ContactValidationError(PHONE_INVALID)
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def _same(stored, incoming) -> bool:
    return str(stored or "").strip().lower() == str(incoming or "").strip().lower()


def normalize_employee_contact(fields: dict, country_code: Optional[str], current=None) -> dict:
    """Validate and normalise the "email" / "phone" keys present in `fields`
    (a dict of employee columns), in place, and return it.

    `current` is the existing employee on an update: a value that is
    unchanged from what is already stored is left alone, so a record holding
    a legacy value saved before these rules can still be edited without
    re-validating the untouched field. Blank strings are left as they are
    (the update paths already treat "" as "no change")."""
    for key, normalizer in (("email", normalize_email), ("phone", None)):
        if key not in fields:
            continue
        value = fields[key]
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if current is not None and _same(getattr(current, key, None), value):
            continue
        if key == "email":
            fields[key] = normalize_email(value)
        else:
            fields[key] = normalize_phone(value, country_code)
    return fields
