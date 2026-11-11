"""
payroll/japan_dormancy.py
-------------------------
Japan (ZP-JP-ENG-001 Phase 1) dormancy switch, mirroring brazil_dormancy and
south_africa_dormancy.

Japan stays PLANNED/dormant in production until its release gates G0–G8 are
signed. One setting, ``JP_TENANT_ONBOARDING_ENABLED`` (default False, unset
in production), decides whether an organisation may become Japanese:

  * `Organization.country` → Japan (org admin `PUT /organizations/me` and the
    Super Admin organization update) — via
    tax_resolver.get_jurisdiction_change_block_reason;
  * the payroll company jurisdiction → JP (`update_company_details`) and the
    Organization.country → jurisdiction back-fill in `get_company_details`.

Deliberately dependency-free (settings + the jurisdiction code map only) so
the engine-level tax_resolver can import it without a cycle. It is never a
substitute for the release gates.
"""

from __future__ import annotations

from typing import Optional

JP = "JP"
DORMANT_MESSAGE = ("Japan is not open for onboarding on this platform yet — Japanese payroll stays disabled "
                   "until its release gates (G0–G8) are signed.")


def onboarding_enabled() -> bool:
    from app.config import settings

    return bool(getattr(settings, "JP_TENANT_ONBOARDING_ENABLED", False))


def is_japan(country: Optional[str]) -> bool:
    if not country:
        return False
    from app.core.jurisdiction import get_jurisdiction_code

    return get_jurisdiction_code(country) == JP


def entering_japan_refusal(old_country: Optional[str], new_country: Optional[str]) -> Optional[str]:
    """The refusal message when a change moves INTO Japan while onboarding is
    disabled; None for every other change."""
    if is_japan(new_country) and not is_japan(old_country) and not onboarding_enabled():
        return DORMANT_MESSAGE
    return None
