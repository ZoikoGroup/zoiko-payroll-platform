"""
payroll/belgium_dormancy.py
---------------------------
Belgium (ZP-BE-ENG-001 Phase 1) dormancy switch, mirroring poland_dormancy.

Belgium stays PLANNED/dormant in production until release gates G1-G7 are
signed (spec §17). One setting, ``BE_TENANT_ONBOARDING_ENABLED`` (default
False, unset in production), decides whether an organisation may become
Belgian at all. It is never a substitute for the release gates, and it never
authorises payroll for a legal employer whose registrations have not passed
validation (BE-001).

Canary: ``BE_CANARY_ORG_IDS`` admits the listed organisations only, so one
internal organisation can be exercised while Belgium stays PLANNED and dormant
for everyone else.
"""

from __future__ import annotations

from typing import Optional

BE = "BE"
DORMANT_MESSAGE = ("Belgium is not open for onboarding on this platform yet - Belgian payroll stays "
                   "disabled until its release gates are signed.")


def canary_organization_ids() -> frozenset:
    """Organisations on the canary allow-list (BE_CANARY_ORG_IDS, comma-separated,
    empty by default). Anything that is not a whole number is ignored."""
    from app.config import settings

    raw = str(getattr(settings, "BE_CANARY_ORG_IDS", "") or "")
    return frozenset(int(part) for part in (p.strip() for p in raw.split(",")) if part.isdigit())


def onboarding_enabled(organization_id: Optional[int] = None) -> bool:
    """True when Belgium onboarding is on for everyone, or for this organisation
    as a canary."""
    from app.config import settings

    if bool(getattr(settings, "BE_TENANT_ONBOARDING_ENABLED", False)):
        return True
    return organization_id is not None and int(organization_id) in canary_organization_ids()


def is_belgium(country: Optional[str]) -> bool:
    if not country:
        return False
    from app.core.jurisdiction import get_jurisdiction_code

    return get_jurisdiction_code(country) == BE


def entering_belgium_refusal(old_country: Optional[str], new_country: Optional[str],
                             organization_id: Optional[int] = None) -> Optional[str]:
    if is_belgium(new_country) and not is_belgium(old_country) and not onboarding_enabled(organization_id):
        return DORMANT_MESSAGE
    return None
