"""
core/synthetic.py
-----------------
Synthetic identity values for non-production data (ZP-PRIV D09).

Every generator returns a value that LOOKS like the real thing (so forms,
validators of shape and UI layouts behave) but can never be a real person's:

* emails use reserved domains (RFC 2606 ``.example`` / ``example.com``);
* IBANs carry check digits ``00`` and an account part chosen so the ISO
  13616 mod-97 check fails;
* Dutch BSNs fail the 11-proof;
* US SSNs use area ``000`` (never issued);
* UK NINOs use prefix ``QQ`` (never issued; HMRC's own example prefix);
* Indian PANs use an invalid holder-type character (4th letter ``X``);
* phone numbers sit in Ofcom's drama range (07700 900000-900999).

The validators below implement the real checksums so tests can prove each
synthetic value fails them, and the CI scan (scripts/scan_test_data.py) uses
the same validators to flag real-looking identifiers in fixtures and dumps.
"""

from __future__ import annotations

import re
import string

RESERVED_EMAIL_DOMAINS = ("example.com", "example.org", "example.net")
RESERVED_EMAIL_TLDS = (".example", ".test", ".invalid", ".localhost")


# ── Generators ──────────────────────────────────────────────────────────────

def email(n: int, tenant: str = "tenant") -> str:
    return f"worker{n}@{re.sub(r'[^a-z0-9-]', '', tenant.lower()) or 'tenant'}.example"


def iban(n: int, country: str = "GB") -> str:
    # "00" alone is not enough ("00" is congruent to the valid "97" mod 97),
    # so step the account part until the mod-97 check fails.
    for k in range(n * 3, n * 3 + 3):
        value = f"{country}00ZOIK{k:014d}"
        if not iban_valid(value):
            return value
    raise RuntimeError("unreachable")


def bsn(n: int) -> str:
    base = (100000000 + n * 7) % 1000000000
    for candidate in range(base, base + 20):
        value = f"{candidate % 1000000000:09d}"
        if not bsn_valid(value):
            return value
    raise RuntimeError("unreachable")


def ssn(n: int) -> str:
    return f"000-{(n // 10000) % 100:02d}-{n % 10000:04d}"


def nino(n: int) -> str:
    return f"QQ{n % 1000000:06d}{'ABCD'[n % 4]}"


def pan(n: int) -> str:
    letters = string.ascii_uppercase
    return f"ZZZX{letters[n % 26]}{n % 10000:04d}{letters[(n // 26) % 26]}"


def phone(n: int) -> str:
    return f"+447700900{n % 1000:03d}"


def person(n: int, tenant: str = "tenant") -> dict:
    return {"name": f"Synthetic Worker {n}", "email": email(n, tenant), "phone": phone(n),
            "bank_account": iban(n), "pan": pan(n), "tax_code": "1257L", "address_line1": f"{n} Synthetic Street"}


# ── Real-world validators ───────────────────────────────────────────────────

def iban_valid(value: str) -> bool:
    s = re.sub(r"\s+", "", value or "").upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", s):
        return False
    rearranged = s[4:] + s[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97 == 1


def bsn_valid(value: str) -> bool:
    s = re.sub(r"\D", "", value or "")
    if len(s) != 9 or s == "000000000":
        return False
    total = sum(int(d) * w for d, w in zip(s[:8], range(9, 1, -1))) - int(s[8])
    return total % 11 == 0


def luhn_valid(value: str) -> bool:
    s = re.sub(r"\D", "", value or "")
    if not 12 <= len(s) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(s)):
        x = int(d)
        if i % 2:
            x = x * 2 - 9 if x > 4 else x * 2
        total += x
    return total % 10 == 0


def ssn_valid(value: str) -> bool:
    m = re.fullmatch(r"(\d{3})-?(\d{2})-?(\d{4})", value or "")
    if not m:
        return False
    area, group, serial = m.groups()
    return area not in ("000", "666") and not area.startswith("9") and group != "00" and serial != "0000"


_NINO_BAD_PREFIXES = {"BG", "GB", "NK", "KN", "TN", "NT", "ZZ", "QQ"}


def nino_valid(value: str) -> bool:
    s = re.sub(r"\s+", "", value or "").upper()
    m = re.fullmatch(r"([A-CEGHJ-PR-TW-Z])([A-CEGHJ-NPR-TW-Z])(\d{6})([A-D])", s)
    return bool(m) and (m.group(1) + m.group(2)) not in _NINO_BAD_PREFIXES


def pan_valid(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{3}[PCHFATBLJG][A-Z]\d{4}[A-Z]", (value or "").upper()))


def email_is_reserved(value: str) -> bool:
    domain = (value or "").rsplit("@", 1)[-1].lower()
    return domain in RESERVED_EMAIL_DOMAINS or domain.endswith(RESERVED_EMAIL_TLDS)
