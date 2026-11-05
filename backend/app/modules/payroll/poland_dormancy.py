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
"""

from __future__ import annotations

from typing import Optional

PL = "PL"
DORMANT_MESSAGE = ("Poland is not open for onboarding on this platform yet - Polish payroll stays "
                   "disabled until its release gates are signed.")


def onboarding_enabled() -> bool:
    from app.config import settings

    return bool(getattr(settings, "PL_TENANT_ONBOARDING_ENABLED", False))


def is_poland(country: Optional[str]) -> bool:
    if not country:
        return False
    from app.core.jurisdiction import get_jurisdiction_code

    return get_jurisdiction_code(country) == PL


def entering_poland_refusal(old_country: Optional[str], new_country: Optional[str]) -> Optional[str]:
    if is_poland(new_country) and not is_poland(old_country) and not onboarding_enabled():
        return DORMANT_MESSAGE
    return None
