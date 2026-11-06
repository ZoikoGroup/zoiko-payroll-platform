"""
payroll/poland_dormancy.py
--------------------------
Poland (ZP-PL-ENG-001 Phase 0) dormancy switch, mirroring
south_africa_dormancy and brazil_dormancy.

Poland stays PLANNED/dormant in production until release gates G1-G7 are
signed (spec §15). One setting, ``PL_TENANT_ONBOARDING_ENABLED`` (default
False, unset in production), decides whether an organisation may become
Polish or use the Poland organisation routes at all. It is never a
substitute for the release gates, and it never authorises payroll for a legal
employer whose registrations have not passed validation (PL-001).

Canary (Phase 9, AC-PL-08): ``PL_CANARY_ORG_IDS`` admits the listed
organisations only, so one internal organisation can run the Active pack in
production while Poland stays PLANNED and dormant for everyone else.
"""

from __future__ import annotations

from typing import Optional

PL = "PL"
DORMANT_MESSAGE = ("Poland is not open for onboarding on this platform yet - Polish payroll stays "
                   "disabled until its release gates are signed.")


def canary_organization_ids() -> frozenset:
    """Organisations on the canary allow-list (PL_CANARY_ORG_IDS, comma-separated,
    empty by default). Anything that is not a whole number is ignored."""
    from app.config import settings

    raw = str(getattr(settings, "PL_CANARY_ORG_IDS", "") or "")
    return frozenset(int(part) for part in (p.strip() for p in raw.split(",")) if part.isdigit())


def onboarding_enabled(organization_id: Optional[int] = None) -> bool:
    """True when Poland onboarding is on for everyone, or for this organisation
    as a canary (Phase 9)."""
    from app.config import settings

    if bool(getattr(settings, "PL_TENANT_ONBOARDING_ENABLED", False)):
        return True
    return organization_id is not None and int(organization_id) in canary_organization_ids()


def is_poland(country: Optional[str]) -> bool:
    if not country:
        return False
    from app.core.jurisdiction import get_jurisdiction_code

    return get_jurisdiction_code(country) == PL


def entering_poland_refusal(old_country: Optional[str], new_country: Optional[str],
                            organization_id: Optional[int] = None) -> Optional[str]:
    if is_poland(new_country) and not is_poland(old_country) and not onboarding_enabled(organization_id):
        return DORMANT_MESSAGE
    return None
