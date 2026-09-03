"""
modules/payroll/engine/tax_resolver
------------------------------------
Resolves the Super-Admin-owned CANONICAL tax/contribution configuration
(organization_id IS NULL rows on ContributionRate/TaxSlab, linked to a
JurisdictionPack with pack_type="tax") for a given jurisdiction and date.

This is the single tax resolver for the platform — it does not calculate
anything itself (that stays in engine/standard.py's per-country strategies)
and it does not replace calculate_payroll()'s entry contract. It only
answers: "as of this date, what are the government-mandated rates/slabs
for this country (+ optional state/regime)?" — returning the exact same
ORM row shapes get_contribution_rates()/get_tax_slabs() already return, so
nothing downstream of it needs to change.

Historical payroll safety (effective dating): callers MUST pass the actual
payroll/pay date, not "today" — resolving whichever pack version was
ACTIVE on that date, not whichever is Active right now. A pack version
that has since been superseded is still resolvable for dates within its
own effective_from/effective_to window, so re-running an old period's
payroll (or comparing old vs new) reproduces the number that was correct
at the time.
"""

from __future__ import annotations

from datetime import date as date_cls
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab


# Rule types that represent a genuine income-tax bracket (something
# _calculate_annual_tax can actually compute a progressive tax from).
# PT_FLAT/SURCHARGE/CONTRIBUTION rows are real TaxSlab data, but for a
# different purpose (India's state-level Professional Tax, a surcharge
# overlay) — a pack whose ONLY slabs are that shape was never meant to
# stand in for a country's real income-tax bands.
_INCOME_TAX_RULE_TYPES = {"MARGINAL_RATE", "FORMULA", "TABLE_LOOKUP", "FIXED_PLUS_MARGINAL"}


def _pack_has_income_tax_slabs(db: Session, pack_id: int) -> bool:
    return (
        db.query(TaxSlab.id)
        .filter(
            TaxSlab.organization_id.is_(None),
            TaxSlab.jurisdiction_pack_id == pack_id,
            TaxSlab.rule_type.in_(_INCOME_TAX_RULE_TYPES),
        )
        .first()
        is not None
    )


def _find_active_tax_pack(
    db: Session, country: str, state: Optional[str], tax_regime: Optional[str], as_of: date_cls,
) -> Optional[JurisdictionPack]:
    """Find the tax pack Active on `as_of`, preferring an exact state match
    and falling back to the country-level (state IS NULL) pack — the same
    "state falls back to country-level" convention used elsewhere in this
    module (list_all_jurisdiction_packs, GlobalStatutoryRate).

    A state match only WINS if that pack actually holds real income-tax
    slabs (see _pack_has_income_tax_slabs). Some state-scoped packs exist
    solely to hold India's Professional Tax brackets (rule_type="PT_FLAT",
    resolved separately and additively via get_state_scoped_config in
    service.py) — letting one of those win here would silently replace the
    country's real income-tax bands with a set of 0%-rate PT rows, zeroing
    everyone's income tax regardless of salary. A state pack that DOES hold
    real bands (UK's Scotland, a US state) is unaffected — this check is
    always true for those, so behavior for them is unchanged."""

    def _query(state_filter):
        q = (
            db.query(JurisdictionPack)
            .filter(
                JurisdictionPack.pack_type == "tax",
                JurisdictionPack.status == "Active",
                JurisdictionPack.jurisdiction_country == country,
            )
        )
        q = state_filter(q)
        if tax_regime:
            q = q.filter(JurisdictionPack.tax_regime == tax_regime)
        q = q.filter(
            (JurisdictionPack.effective_from.is_(None)) | (JurisdictionPack.effective_from <= as_of),
        ).filter(
            (JurisdictionPack.effective_to.is_(None)) | (JurisdictionPack.effective_to >= as_of),
        )
        return q.order_by(JurisdictionPack.updated_at.desc()).first()

    if state:
        pack = _query(lambda q: q.filter(JurisdictionPack.jurisdiction_state == state))
        if pack and _pack_has_income_tax_slabs(db, pack.id):
            return pack
    return _query(lambda q: q.filter(JurisdictionPack.jurisdiction_state.is_(None)))


def resolve_tax_configuration(
    db: Session,
    country: str,
    state: Optional[str] = None,
    tax_regime: Optional[str] = None,
    payroll_date: Optional[date_cls] = None,
) -> Tuple[List[ContributionRate], List[TaxSlab], Optional[JurisdictionPack]]:
    """Return (contribution_rates, tax_slabs, pack) for the canonical tax
    configuration applicable to this jurisdiction on `payroll_date`.

    Empty lists (with pack=None) mean no canonical tax pack has been
    configured for this jurisdiction yet — callers should fall back to
    whatever they did before this resolver existed (org's own rows /
    the hardcoded per-country defaults), never raise, so a jurisdiction
    with no canonical data yet keeps working exactly as today.
    """
    as_of = payroll_date or date_cls.today()
    pack = _find_active_tax_pack(db, country, state, tax_regime, as_of)
    if not pack:
        return [], [], None

    rates = (
        db.query(ContributionRate)
        .filter(ContributionRate.organization_id.is_(None), ContributionRate.jurisdiction_pack_id == pack.id)
        .order_by(ContributionRate.sort_order)
        .all()
    )
    slabs = (
        db.query(TaxSlab)
        .filter(TaxSlab.organization_id.is_(None), TaxSlab.jurisdiction_pack_id == pack.id)
        .order_by(TaxSlab.sort_order, TaxSlab.min_amount)
        .all()
    )
    return rates, slabs, pack


def find_active_tax_pack(
    db: Session,
    country: str,
    state: Optional[str] = None,
    tax_regime: Optional[str] = None,
    as_of: Optional[date_cls] = None,
) -> Optional[JurisdictionPack]:
    """Public wrapper over _find_active_tax_pack — same resolution rules
    (state match only wins if it holds real income-tax slabs, respects
    effective_from/effective_to, excludes Draft), exposed under a public
    name for callers outside this module that need the pack itself rather
    than resolve_tax_configuration's (rates, slabs, pack) tuple."""
    return _find_active_tax_pack(db, country, state, tax_regime, as_of or date_cls.today())


def get_jurisdiction_onboarding_block_reason(
    db: Session,
    country: Optional[str],
    state: Optional[str] = None,
    as_of: Optional[date_cls] = None,
) -> Optional[str]:
    """Whether an organization should be allowed to onboard into `country`
    right now — never raises, returns None when onboarding should proceed,
    else a clean, business-friendly reason string safe to show a user
    directly (no stack traces, no internal names).

    Deliberately uses the EXACT SAME acceptance test
    _resolve_effective_rate_inputs (service.py) already uses to decide
    whether canonical configuration is usable for payroll
    (`pack is not None and (rates or slabs)`) — so registration accepts
    precisely what payroll would accept for this jurisdiction, one source
    of truth, not a parallel "is configured" notion.

    Country is normalized via app.core.jurisdiction.get_jurisdiction_code,
    NOT payroll.service._normalize_country — that function silently
    defaults unrecognized/empty input to "IN", which would be actively
    dangerous at a rejection gate (an unrecognized country would silently
    pass as if it were India)."""
    from app.core.jurisdiction import get_jurisdiction_code

    code = get_jurisdiction_code(country)
    if not code:
        return (
            f"'{country}' is not a supported payroll jurisdiction yet — "
            "please contact your administrator or select a supported country."
        )
    rates, slabs, pack = resolve_tax_configuration(db, code, state=state, tax_regime=None, payroll_date=as_of)
    if pack is None or not (rates or slabs):
        return (
            "This jurisdiction is not yet configured for organization registration — "
            "please contact your administrator or select a supported jurisdiction."
        )
    return None
