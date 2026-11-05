"""
payroll/nz_dormancy.py
----------------------
New Zealand (ZP-NZ-ENG-001 Phase 0) dormancy switch, mirroring japan_dormancy.

New Zealand stays PLANNED and dormant in production until its release gates
G1–G7 are signed. One setting, ``NZ_TENANT_ONBOARDING_ENABLED`` (default False,
unset in production), decides whether an organisation may become a New Zealand
employer — or, for the Option 3 canary (Phase 9), ``NZ_CANARY_ORG_IDS`` lets
the listed organisations only:

  * `Organization.country` → New Zealand (org admin `PUT /organizations/me` and
    the Super Admin organization update), via
    tax_resolver.get_jurisdiction_change_block_reason;
  * the payroll company jurisdiction → NZ (`update_company_details`) and the
    Organization.country → jurisdiction back-fill in `get_company_details`.

Deliberately dependency-free (settings + the jurisdiction code map only) so
the engine-level tax_resolver can import it without a cycle. It is never a
substitute for the release gates.
"""

from __future__ import annotations

from typing import Optional

NZ = "NZ"
DORMANT_MESSAGE = ("New Zealand is not open for onboarding on this platform yet — New Zealand payroll stays "
                   "disabled until its release gates (G1–G7) are signed.")


def canary_organization_ids() -> frozenset:
    """Organisations on the Option 3 canary allow-list (NZ_CANARY_ORG_IDS,
    comma-separated, empty by default). Anything that is not a whole number is
    ignored."""
    from app.config import settings

    raw = str(getattr(settings, "NZ_CANARY_ORG_IDS", "") or "")
    return frozenset(int(part) for part in (p.strip() for p in raw.split(",")) if part.isdigit())


def onboarding_enabled(organization_id: Optional[int] = None) -> bool:
    """True when New Zealand onboarding is on for everyone, or for this
    organisation as an Option 3 canary (Phase 9)."""
    from app.config import settings

    if bool(getattr(settings, "NZ_TENANT_ONBOARDING_ENABLED", False)):
        return True
    return organization_id is not None and int(organization_id) in canary_organization_ids()


def is_new_zealand(country: Optional[str]) -> bool:
    if not country:
        return False
    from app.core.jurisdiction import get_jurisdiction_code

    return get_jurisdiction_code(country) == NZ


def entering_nz_refusal(old_country: Optional[str], new_country: Optional[str],
                        organization_id: Optional[int] = None) -> Optional[str]:
    """The refusal message when a change moves INTO New Zealand while
    onboarding is disabled (for this organisation); None for every other change."""
    if (is_new_zealand(new_country) and not is_new_zealand(old_country)
            and not onboarding_enabled(organization_id)):
        return DORMANT_MESSAGE
    return None
