"""
payroll/mexico_dormancy.py
--------------------------
Mexico (ZP-MX-ENG-001) dormancy switch — Phase 4a.

Merging to main deploys to production, so Mexico must stay dormant there
until the release gates G1–G8 are signed. One setting,
`MX_TENANT_ONBOARDING_ENABLED` (default False, unset in production), decides
whether an organisation may become Mexican or use the Mexico organisation
API at all:

  * `Organization.country` → Mexico (org admin `PUT /organizations/me` and
    the Super Admin organization update) — via
    tax_resolver.get_jurisdiction_change_block_reason;
  * the payroll company jurisdiction → MX (`update_company_details`) and the
    Organization.country → jurisdiction back-fill in `get_company_details`;
  * every `/api/payroll/mexico/...` route (mexico_org_router) — which, with
    the flag on, still requires the caller's organisation to be Mexican.

Deliberately dependency-free (settings + the jurisdiction code map only) so
the engine-level tax_resolver can import it without a cycle. Phase 10
replaces the flag with the service-registry AVAILABLE state; it is never a
substitute for G1–G8.
"""

from __future__ import annotations

from typing import Optional

MX = "MX"
DORMANT_MESSAGE = ("Mexico is not open for onboarding on this platform yet — Mexican payroll stays disabled "
                   "until its release gates (G1–G8) are signed.")


def onboarding_enabled() -> bool:
    from app.config import settings

    return bool(getattr(settings, "MX_TENANT_ONBOARDING_ENABLED", False))


def is_mexico(country: Optional[str]) -> bool:
    """Code or name, any case/accent the jurisdiction registry knows. Blank or
    unknown is never Mexico (unlike payroll.service._normalize_country, which
    defaults blanks to IN)."""
    if not country:
        return False
    from app.core.jurisdiction import get_jurisdiction_code

    return get_jurisdiction_code(country) == MX


def entering_mexico_refusal(old_country: Optional[str], new_country: Optional[str]) -> Optional[str]:
    """The refusal message when a change would move an organisation INTO
    Mexico while onboarding is disabled; None otherwise (including any change
    that does not involve Mexico, and an org that is already Mexican)."""
    if is_mexico(new_country) and not is_mexico(old_country) and not onboarding_enabled():
        return DORMANT_MESSAGE
    return None
