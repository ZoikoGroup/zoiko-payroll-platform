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
