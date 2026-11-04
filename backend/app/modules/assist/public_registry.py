"""
modules/assist/public_registry.py
-----------------------------------
Public payroll-jurisdiction registry for the Global Payroll AI Concierge's
"Check your country" panel (chatbot wireframe ZP-PUB-AI-UX-001, section 05).

The registry — not the frontend and not the language model — is the single
source of truth for which countries are publicly shown as live. The seed below
is the "baseline registry seed" from section 05.1 of the wireframe (the most
recently supplied production-ready list, verified 2026-10-09). Changes need
the content owner's approval; editing this list is the only way public
readiness changes.

Capabilities are deliberately left empty until each one is verified per
module: the UI then shows "Capability details haven't been published yet"
instead of implying that tax filing or payments are supported (wireframe
acceptance test A05).
"""

from __future__ import annotations

REGISTRY_VERIFIED_AT = "2026-10-09"

# (ISO 3166-1 alpha-2, display name, aliases)
_LIVE_JURISDICTIONS: list[tuple[str, str, list[str]]] = [
    # Americas / Caribbean
    ("US", "United States", ["USA", "United States of America", "America"]),
    ("CA", "Canada", []),
    ("BB", "Barbados", []),
    ("BS", "Bahamas", ["The Bahamas"]),
    ("KY", "Cayman Islands", ["Cayman"]),
    ("DO", "Dominican Republic", []),
    ("GY", "Guyana", []),
    ("JM", "Jamaica", []),
    ("PR", "Puerto Rico", []),
    ("TT", "Trinidad and Tobago", ["Trinidad", "Tobago"]),
    # Europe
    ("GB", "United Kingdom", ["UK", "Britain", "Great Britain", "England", "Scotland", "Wales"]),
    ("DE", "Germany", ["Deutschland"]),
    ("FR", "France", []),
    ("IE", "Ireland", []),
    ("SE", "Sweden", []),
    ("IT", "Italy", []),
    # APAC / other
    ("IN", "India", []),
    ("AU", "Australia", []),
    ("SG", "Singapore", []),
]


def list_public_countries() -> dict:
    countries = [
        {
            "code": code,
            "name": name,
            "launch_status": "live",
            "aliases": aliases,
            "capabilities": {},
            "verified_at": REGISTRY_VERIFIED_AT,
            "source_url": None,
        }
        for code, name, aliases in _LIVE_JURISDICTIONS
    ]
    live_count = len({c["code"] for c in countries if c["launch_status"] == "live"})
    return {"countries": countries, "live_count": live_count, "updated_at": REGISTRY_VERIFIED_AT}


def live_country_names() -> list[str]:
    return [name for _code, name, _aliases in _LIVE_JURISDICTIONS]


def is_live_country(country_name: str) -> bool:
    """Whether `country_name` (display name or alias, any case) is live."""
    wanted = (country_name or "").strip().lower()
    return any(
        wanted == name.lower() or wanted in (alias.lower() for alias in aliases)
        for _code, name, aliases in _LIVE_JURISDICTIONS
    )
