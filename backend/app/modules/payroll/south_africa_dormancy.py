"""
payroll/south_africa_dormancy.py
--------------------------------
South Africa (ZP-ZA-ENG-001 Phase 5) dormancy switch, mirroring
brazil_dormancy and mexico_dormancy.

South Africa stays PLANNED/dormant in production until its release gates are
signed. One setting, ``ZA_TENANT_ONBOARDING_ENABLED`` (default False, unset
in production), decides whether an organisation may become South African or
use the South Africa organisation routes at all. It is never a substitute
for the release gates.
"""

from __future__ import annotations

from typing import Optional

ZA = "ZA"
DORMANT_MESSAGE = ("South Africa is not open for onboarding on this platform yet - South African payroll stays "
                   "disabled until its release gates are signed.")


def onboarding_enabled() -> bool:
    from app.config import settings

    return bool(getattr(settings, "ZA_TENANT_ONBOARDING_ENABLED", False))


def is_south_africa(country: Optional[str]) -> bool:
    if not country:
        return False
    from app.core.jurisdiction import get_jurisdiction_code

    return get_jurisdiction_code(country) == ZA


def entering_south_africa_refusal(old_country: Optional[str], new_country: Optional[str]) -> Optional[str]:
    if (is_south_africa(new_country) and not is_south_africa(old_country)
            and not onboarding_enabled()):
        return DORMANT_MESSAGE
    return None
