"""
payroll/malaysia_dormancy.py
----------------------------
Malaysia (ZP-MY-ENG-001 Phase 0) dormancy switch, mirroring poland_dormancy.

Malaysia stays PLANNED/dormant in production until release gates G1-G7 are
signed (spec §16). One setting, ``MY_TENANT_ONBOARDING_ENABLED`` (default
False, unset in production), decides whether an organisation may become
Malaysian or use the Malaysia organisation routes at all. It is never a
substitute for the release gates (MY-002).

Canary: ``MY_CANARY_ORG_IDS`` admits the listed organisations only, while the
flag stays off for everyone else. It works only once Malaysia's service
registry row is AVAILABLE: while PLANNED, the registry gate refuses even a
canary organisation entering Malaysia.

"MY" is Malaysia. The bare word "my" is never an alias anywhere free text is
normalised (it is an ordinary English word).
"""

from __future__ import annotations

from typing import Optional

MY = "MY"
DORMANT_MESSAGE = ("Malaysia is not open for onboarding on this platform yet - Malaysian payroll stays "
                   "disabled until its release gates are signed.")


def canary_organization_ids() -> frozenset:
    """Organisations on the canary allow-list (MY_CANARY_ORG_IDS, comma-separated,
    empty by default). Anything that is not a whole number is ignored."""
    from app.config import settings

    raw = str(getattr(settings, "MY_CANARY_ORG_IDS", "") or "")
    return frozenset(int(part) for part in (p.strip() for p in raw.split(",")) if part.isdigit())


def onboarding_enabled(organization_id: Optional[int] = None) -> bool:
    """True when Malaysia onboarding is on for everyone, or for this
    organisation as a canary."""
    from app.config import settings

    if bool(getattr(settings, "MY_TENANT_ONBOARDING_ENABLED", False)):
        return True
    return organization_id is not None and int(organization_id) in canary_organization_ids()


def is_malaysia(country: Optional[str]) -> bool:
    """Pure country-code test — independent of the dormancy flag."""
    if not country:
        return False
    from app.core.jurisdiction import get_jurisdiction_code

    return get_jurisdiction_code(country) == MY


def entering_malaysia_refusal(old_country: Optional[str], new_country: Optional[str],
                              organization_id: Optional[int] = None) -> Optional[str]:
    if is_malaysia(new_country) and not is_malaysia(old_country) and not onboarding_enabled(organization_id):
        return DORMANT_MESSAGE
    return None
