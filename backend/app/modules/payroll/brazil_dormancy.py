"""
payroll/brazil_dormancy.py
--------------------------
Brazil (ZP-BR-ENG-001) dormancy switch — Phase 3 (mirrors mexico_dormancy).

Merging to main deploys to production, so Brazil must stay dormant there
until the release gates G1–G8 are signed. One setting,
`BR_TENANT_ONBOARDING_ENABLED` (default False, unset in production), decides
whether an organisation may become Brazilian or use the Brazil organisation
API at all:

  * `Organization.country` → Brazil (org admin `PUT /organizations/me` and
    the Super Admin organization update) — via
    tax_resolver.get_jurisdiction_change_block_reason;
  * the payroll company jurisdiction → BR (`update_company_details`) and the
    Organization.country → jurisdiction back-fill in `get_company_details`;
  * the Brazil employee validator (employee_validation._DORMANT_STRATEGIES);
  * every `/api/payroll/brazil/...` route (brazil_org_router) — which, with
    the flag on, still requires the caller's organisation to be Brazilian.

Deliberately dependency-free (settings + the jurisdiction code map only) so
the engine-level tax_resolver can import it without a cycle. Phase 11
replaces the flag with the service-registry AVAILABLE state; it is never a
substitute for G1–G8.
"""

from __future__ import annotations

from typing import Optional

BR = "BR"
DORMANT_MESSAGE = ("Brazil is not open for onboarding on this platform yet — Brazilian payroll stays disabled "
                   "until its release gates (G1–G8) are signed.")


def onboarding_enabled() -> bool:
    from app.config import settings

    return bool(getattr(settings, "BR_TENANT_ONBOARDING_ENABLED", False))


def is_brazil(country: Optional[str]) -> bool:
    """Code or name, any case/accent the jurisdiction registry knows. Blank or
    unknown is never Brazil (unlike payroll.service._normalize_country, which
    defaults blanks to IN)."""
    if not country:
        return False
    from app.core.jurisdiction import get_jurisdiction_code

    return get_jurisdiction_code(country) == BR


def entering_brazil_refusal(old_country: Optional[str], new_country: Optional[str]) -> Optional[str]:
    """The refusal message when a change would move an organisation INTO
    Brazil while onboarding is disabled; None otherwise (including any change
    that does not involve Brazil, and an org that is already Brazilian)."""
    if is_brazil(new_country) and not is_brazil(old_country) and not onboarding_enabled():
        return DORMANT_MESSAGE
    return None
