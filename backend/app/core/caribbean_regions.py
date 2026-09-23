"""
core/caribbean_regions.py
--------------------------
Master/classification list for the full Caribbean region — the ONE new
piece of architecture this build introduces (see the approved 2026-09-21
implementation plan). Nothing else in this codebase groups jurisdictions
by region/classification, and this list is deliberately NOT a database
table: it mirrors the exact convention core/jurisdiction.py already uses
for "which countries exist" (a plain Python dict), because these ~32
Caribbean entries need to exist for BROWSING/DISPLAY purposes only —
most of them have zero configuration and must never be treated as real.

Two completely separate concerns, do not conflate them:
  - "Is this code known to core/jurisdiction.py / engine/standard.py's
    _COUNTRY_CALC / JurisdictionServiceRegistry?" → that is what actually
    gates registration and payroll calculation (see tax_resolver.py).
  - "Should the Caribbean master view show this jurisdiction at all, and
    under which classification heading?" → that is all this file answers.

A jurisdiction appearing here with status COMING_SOON is a promise about
nothing except that a card renders. Activating it for real production
use means: adding it to core/jurisdiction.py's REGISTRATION_COUNTRIES/
JURISDICTION_TAX_SCHEMAS/code-name maps, giving it a dedicated
engine/countries/<country>.py calculator + a _COUNTRY_CALC dispatch
entry, building its Super Admin Compliance page, and flipping its
JurisdictionServiceRegistry row from PLANNED to AVAILABLE — exactly the
work already done for the 7 ACTIVE entries below. This file's own STATUS
field never unlocks any of that by itself.
"""

from typing import Optional

CLASSIFICATION_INDEPENDENT = "INDEPENDENT_COUNTRY"
CLASSIFICATION_BOT = "BRITISH_OVERSEAS_TERRITORY"
CLASSIFICATION_DUTCH = "DUTCH_CARIBBEAN"
CLASSIFICATION_FRENCH = "FRENCH_CARIBBEAN"
CLASSIFICATION_US_TERRITORY = "UNITED_STATES_TERRITORY"

STATUS_ACTIVE = "ACTIVE"
STATUS_COMING_SOON = "COMING_SOON"

# code -> (name, classification, status)
CARIBBEAN_JURISDICTIONS = {
    # ── Independent countries ────────────────────────────────────────────
    "BB": ("Barbados", CLASSIFICATION_INDEPENDENT, STATUS_ACTIVE),
    "BS": ("Bahamas", CLASSIFICATION_INDEPENDENT, STATUS_ACTIVE),
    "DO": ("Dominican Republic", CLASSIFICATION_INDEPENDENT, STATUS_ACTIVE),
    "GY": ("Guyana", CLASSIFICATION_INDEPENDENT, STATUS_ACTIVE),
    "JM": ("Jamaica", CLASSIFICATION_INDEPENDENT, STATUS_ACTIVE),
    "TT": ("Trinidad and Tobago", CLASSIFICATION_INDEPENDENT, STATUS_ACTIVE),
    "AG": ("Antigua and Barbuda", CLASSIFICATION_INDEPENDENT, STATUS_COMING_SOON),
    "BZ": ("Belize", CLASSIFICATION_INDEPENDENT, STATUS_COMING_SOON),
    "CU": ("Cuba", CLASSIFICATION_INDEPENDENT, STATUS_COMING_SOON),
    "DM": ("Dominica", CLASSIFICATION_INDEPENDENT, STATUS_COMING_SOON),
    "GD": ("Grenada", CLASSIFICATION_INDEPENDENT, STATUS_COMING_SOON),
    "HT": ("Haiti", CLASSIFICATION_INDEPENDENT, STATUS_COMING_SOON),
    "KN": ("Saint Kitts and Nevis", CLASSIFICATION_INDEPENDENT, STATUS_COMING_SOON),
    "LC": ("Saint Lucia", CLASSIFICATION_INDEPENDENT, STATUS_COMING_SOON),
    "VC": ("Saint Vincent and the Grenadines", CLASSIFICATION_INDEPENDENT, STATUS_COMING_SOON),
    "SR": ("Suriname", CLASSIFICATION_INDEPENDENT, STATUS_COMING_SOON),

    # ── British Overseas Territories ─────────────────────────────────────
    "KY": ("Cayman Islands", CLASSIFICATION_BOT, STATUS_ACTIVE),
    "AI": ("Anguilla", CLASSIFICATION_BOT, STATUS_COMING_SOON),
    "BM": ("Bermuda", CLASSIFICATION_BOT, STATUS_COMING_SOON),
    "VG": ("British Virgin Islands", CLASSIFICATION_BOT, STATUS_COMING_SOON),
    "MS": ("Montserrat", CLASSIFICATION_BOT, STATUS_COMING_SOON),
    "TC": ("Turks and Caicos Islands", CLASSIFICATION_BOT, STATUS_COMING_SOON),

    # ── Dutch Caribbean ───────────────────────────────────────────────────
    "AW": ("Aruba", CLASSIFICATION_DUTCH, STATUS_COMING_SOON),
    "CW": ("Curaçao", CLASSIFICATION_DUTCH, STATUS_COMING_SOON),
    "SX": ("Sint Maarten", CLASSIFICATION_DUTCH, STATUS_COMING_SOON),
    "BQ": ("Bonaire", CLASSIFICATION_DUTCH, STATUS_COMING_SOON),

    # ── French Caribbean ──────────────────────────────────────────────────
    "GP": ("Guadeloupe", CLASSIFICATION_FRENCH, STATUS_COMING_SOON),
    "MQ": ("Martinique", CLASSIFICATION_FRENCH, STATUS_COMING_SOON),
    "GF": ("French Guiana", CLASSIFICATION_FRENCH, STATUS_COMING_SOON),
    "MF": ("Saint Martin", CLASSIFICATION_FRENCH, STATUS_COMING_SOON),
    "BL": ("Saint Barthélemy", CLASSIFICATION_FRENCH, STATUS_COMING_SOON),

    # ── United States Territories ────────────────────────────────────────
    "PR": ("Puerto Rico", CLASSIFICATION_US_TERRITORY, STATUS_COMING_SOON),
    "VI": ("U.S. Virgin Islands", CLASSIFICATION_US_TERRITORY, STATUS_COMING_SOON),
}

# The 7 codes actually wired into core/jurisdiction.py + engine/standard.py
# today. Kept as a derived constant (not hand-duplicated) so this file and
# core/jurisdiction.py can never silently drift apart on WHICH codes are
# real — if a code is ACTIVE here, this codebase's test suite asserts it
# also resolves via app.core.jurisdiction.get_jurisdiction_code.
ACTIVE_CARIBBEAN_CODES = frozenset(
    code for code, (_, _, status) in CARIBBEAN_JURISDICTIONS.items() if status == STATUS_ACTIVE
)
COMING_SOON_CARIBBEAN_CODES = frozenset(
    code for code, (_, _, status) in CARIBBEAN_JURISDICTIONS.items() if status == STATUS_COMING_SOON
)

CLASSIFICATION_LABELS = {
    CLASSIFICATION_INDEPENDENT: "Independent Countries",
    CLASSIFICATION_BOT: "British Overseas Territories",
    CLASSIFICATION_DUTCH: "Dutch Caribbean",
    CLASSIFICATION_FRENCH: "French Caribbean",
    CLASSIFICATION_US_TERRITORY: "United States Territories",
}


def list_caribbean_master() -> list[dict]:
    """Every Caribbean jurisdiction, grouped by classification, for the
    Super Admin Compliance > Caribbean master view. Read-only — this
    function creates nothing and gates nothing; it only describes what
    the Caribbean region browsing screen should render."""
    rows = [
        {"code": code, "name": name, "classification": classification, "status": status}
        for code, (name, classification, status) in CARIBBEAN_JURISDICTIONS.items()
    ]
    rows.sort(key=lambda r: (r["classification"], r["name"]))
    return rows


def get_caribbean_classification(code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    entry = CARIBBEAN_JURISDICTIONS.get(code.upper())
    return entry[1] if entry else None


def is_active_caribbean(code: Optional[str]) -> bool:
    return bool(code) and code.upper() in ACTIVE_CARIBBEAN_CODES


def is_coming_soon_caribbean(code: Optional[str]) -> bool:
    return bool(code) and code.upper() in COMING_SOON_CARIBBEAN_CODES
