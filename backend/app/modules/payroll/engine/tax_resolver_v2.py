"""
modules/payroll/engine/tax_resolver_v2
----------------------------------------
Resolver for the new, generic jurisdiction/tax hierarchy
(app/modules/payroll/hierarchy/models.py). Same contract as
engine/tax_resolver.py's resolve_tax_configuration: this module does not
calculate anything (calculation stays in engine/standard.py) — it only
answers "as of this date, what is the applicable TaxVersion for this Tax
at this Jurisdiction (or the nearest ancestor that has one)?"

The layering fix: engine/tax_resolver.py's resolve_tax_configuration
resolves ONE pack per (country, state) — an exact state match returns
that pack's ENTIRE rate/slab set, completely replacing the country-level
pack for every tax the employee has, not just the state-specific one.
This resolver instead resolves PER TAX: each Tax independently walks the
jurisdiction chain from most-specific to root and takes the first Active
version it finds, so e.g. a state's Professional-Tax-only TaxVersion and
the country's Income-Tax/PF/ESI TaxVersions can all apply to the same
employee simultaneously, each from whichever level actually defines them.

engine/tax_resolver.py itself is UNCHANGED and stays the permanent
mechanism for resolving frozen historical data (JurisdictionPack/
ContributionRate/TaxSlab, referenced by old PayslipItem rows) — this
module is additive, used only for organizations with
CompanyComplianceDetails.tax_hierarchy_v2_enabled = True.
"""

from __future__ import annotations

from datetime import date as date_cls
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll.hierarchy.models import (
    Country, Jurisdiction, Tax, TaxParameter, TaxRule, TaxRuleRate, TaxRuleSlab, TaxVersion,
)


def _parent_of(db: Session, jurisdiction_id: int) -> Optional[int]:
    return (
        db.query(Jurisdiction.parent_jurisdiction_id)
        .filter(Jurisdiction.id == jurisdiction_id)
        .scalar()
    )


def _find_active_version_at(
    db: Session, jurisdiction_id: int, tax_code: str, tax_regime: Optional[str], as_of: date_cls,
) -> Optional[TaxVersion]:
    query = (
        db.query(TaxVersion)
        .join(Tax, Tax.id == TaxVersion.tax_id)
        .filter(
            TaxVersion.jurisdiction_id == jurisdiction_id,
            Tax.tax_code == tax_code,
            TaxVersion.status == "Active",
            TaxVersion.effective_from <= as_of,
        )
        .filter((TaxVersion.effective_to.is_(None)) | (TaxVersion.effective_to >= as_of))
    )
    if tax_regime:
        query = query.filter(TaxVersion.tax_regime == tax_regime)
    # Overlap is prevented at write time (see activate_tax_version) — this
    # ordering is a tie-break of last resort, not a substitute for that
    # guard, matching the old resolver's own "most recently updated wins"
    # fallback for anything that somehow still conflicts.
    return query.order_by(TaxVersion.updated_at.desc()).first()


def resolve_tax_version(
    db: Session, jurisdiction_id: int, tax_code: str,
    tax_regime: Optional[str] = None, payroll_date: Optional[date_cls] = None,
) -> Optional[TaxVersion]:
    """Walk the jurisdiction parent chain from `jurisdiction_id` upward
    (self, then parent, then grandparent, ...), returning the first
    Active TaxVersion found for `tax_code` effective on `payroll_date`.
    Returns None if no ancestor at any level defines an Active version
    for this tax — never raises, matching resolve_tax_configuration's
    "empty means not configured yet, not an error" contract."""
    as_of = payroll_date or date_cls.today()
    current_id: Optional[int] = jurisdiction_id
    while current_id is not None:
        version = _find_active_version_at(db, current_id, tax_code, tax_regime, as_of)
        if version:
            return version
        current_id = _parent_of(db, current_id)
    return None


def list_applicable_tax_codes(db: Session, jurisdiction_id: int) -> List[str]:
    """Every distinct Tax.tax_code with AT LEAST ONE TaxVersion anywhere
    in this jurisdiction's chain (self + every ancestor) — the "which
    taxes could possibly apply here" set that resolve_applicable_
    compliance_configuration then resolves one-by-one via
    resolve_tax_version. Different jurisdiction levels may define
    different taxes (a country defines Income Tax/PF/ESI; a state
    defines only Professional Tax) — this returns the union, not just
    what's defined at the exact starting jurisdiction."""
    chain: List[int] = []
    current_id: Optional[int] = jurisdiction_id
    while current_id is not None:
        chain.append(current_id)
        current_id = _parent_of(db, current_id)
    if not chain:
        return []
    rows = (
        db.query(Tax.tax_code)
        .join(TaxVersion, TaxVersion.tax_id == Tax.id)
        .filter(TaxVersion.jurisdiction_id.in_(chain))
        .distinct()
        .all()
    )
    return [r[0] for r in rows]


def activate_tax_version(db: Session, tax_version_id: int, actor_id: Optional[int] = None) -> TaxVersion:
    """Transition a TaxVersion to status="Active", with the overlap/
    duplicate-Active guard the old system never had (the confirmed live
    bug: two simultaneously-Active Canada tax packs, silently resolved by
    "whichever was updated most recently" — see resolve_tax_version's
    ordering fallback above, which is exactly that same silent behavior
    this guard exists to make unreachable going forward).

    Locks every other row for the same (tax_id, jurisdiction_id,
    tax_regime) via SELECT ... FOR UPDATE before checking for an
    overlapping effective-date range with status="Active", so two
    concurrent activations can't both succeed and produce the same
    conflict again.
    """
    version = db.query(TaxVersion).filter(TaxVersion.id == tax_version_id).first()
    if not version:
        raise NotFoundException("TaxVersion", tax_version_id)

    siblings = (
        db.query(TaxVersion)
        .filter(
            TaxVersion.tax_id == version.tax_id,
            TaxVersion.jurisdiction_id == version.jurisdiction_id,
            TaxVersion.tax_regime == version.tax_regime,
            TaxVersion.id != version.id,
            TaxVersion.status == "Active",
        )
        .with_for_update()
        .all()
    )
    for sibling in siblings:
        sibling_end = sibling.effective_to or date_cls.max
        version_end = version.effective_to or date_cls.max
        overlaps = version.effective_from <= sibling_end and sibling.effective_from <= version_end
        if overlaps:
            raise BadRequestException(
                f"Cannot activate - TaxVersion {sibling.version_label} (id={sibling.id}) is already "
                f"Active for this Tax/Jurisdiction with an overlapping effective period "
                f"({sibling.effective_from} to {sibling.effective_to or 'open-ended'}). "
                f"Retire or expire it first."
            )

    version.status = "Active"
    db.commit()
    db.refresh(version)
    return version


def find_jurisdiction_for_country_state(db: Session, country_code: str, state_name: Optional[str] = None) -> Optional[Jurisdiction]:
    """Bridges the old (country_code, state_name) string pair — still
    what PayrollEmployee/CompanyComplianceDetails store — to the new
    Jurisdiction row. Returns None if this country/state hasn't been
    onboarded into the new hierarchy yet (no migration has run, or this
    exact state was never migrated) — callers must treat that as "fall
    back to the old resolver," never as an error."""
    country = db.query(Country).filter(Country.code == country_code).first()
    if not country:
        return None
    query = db.query(Jurisdiction).filter(Jurisdiction.country_id == country.id)
    query = query.filter(Jurisdiction.name == state_name) if state_name else query.filter(Jurisdiction.parent_jurisdiction_id.is_(None))
    return query.first()


class _V2RateRow:
    """Duck-types the exact attributes engine/standard.py's rate_map
    entries already expose (component_key, employee_rate_pct,
    employer_rate_pct, flat_amount) so _calc_india/_calc_us/.../
    _param_amount/_param_pct read v2-resolved data with ZERO changes to
    that file."""
    __slots__ = ("component_key", "employee_rate_pct", "employer_rate_pct", "flat_amount")

    def __init__(self, component_key, employee_rate_pct, employer_rate_pct, flat_amount):
        self.component_key = component_key
        self.employee_rate_pct = employee_rate_pct
        self.employer_rate_pct = employer_rate_pct
        self.flat_amount = flat_amount


class _V2SlabRow:
    """Duck-types TaxSlab's engine-facing attributes. rate_pct may be
    None here (TaxRuleSlab allows a pure flat_fee_amount band) — the old
    bracket loop (_calculate_annual_tax) always divides by rate_pct, so a
    None would raise; this adapter is only ever exercised by an org whose
    migrated data was produced by the (not-yet-built) migration script,
    which never emits a None rate_pct for a MARGINAL_RATE-style slab (see
    the Phase 3 plan's migration step 6) — flat-fee-only slabs are a
    future capability the engine doesn't consume via this flattened path
    yet, matching the plan's explicit "additive only" note for that case.
    """
    __slots__ = ("min_amount", "max_amount", "rate_pct", "rate_label", "rule_type", "formula_expression")

    def __init__(self, min_amount, max_amount, rate_pct, rate_label, rule_type, formula_expression):
        self.min_amount = min_amount
        self.max_amount = max_amount
        self.rate_pct = rate_pct
        self.rate_label = rate_label
        self.rule_type = rule_type
        self.formula_expression = formula_expression


def resolve_engine_inputs_v2(
    db: Session, country_code: str, state: Optional[str] = None,
    tax_regime: Optional[str] = None, payroll_date: Optional[date_cls] = None,
):
    """The engine-facing adapter: resolves the new hierarchy into the
    EXACT (rate_map, slabs) shape _resolve_effective_rate_inputs already
    returns for v1 — a {component_key: rate-like} dict and a list of
    slab-like objects. engine/standard.py requires no changes to consume
    this; only what's resolved BEHIND it differs.

    Returns ({}, []) — "not available for this date" — if this country/
    state hasn't been onboarded into the new hierarchy yet, OR if ANY tax
    this jurisdiction chain defines fails to resolve an Active version for
    `payroll_date` (e.g. a fiscal year whose pack was never actually
    filled in with real rates). This is deliberately all-or-nothing,
    mirroring v1's own resolve_tax_configuration contract (a whole pack
    either resolves for a date or it doesn't — there is no partial-pack
    fallback there either): a caller that got a truthy (non-empty)
    rate_map back must be able to trust it's complete, not missing PF/ESI
    because only Professional Tax happened to have a version covering
    that date while national taxes didn't. Returning a partial result
    here would silently under-calculate deductions once an org is cut
    over — this is exactly the failure mode the migration's correctness
    gate (comparing a real historical payslip against this function)
    caught before it could ship. The caller falls back to the org's own
    cached ContributionRate/TaxSlab rows exactly as the v1 path already
    does when no canonical pack resolves."""
    jurisdiction = find_jurisdiction_for_country_state(db, country_code, state)
    if not jurisdiction:
        return {}, []

    tax_codes = list_applicable_tax_codes(db, jurisdiction.id)
    resolved_versions = {}
    for tax_code in tax_codes:
        version = resolve_tax_version(db, jurisdiction.id, tax_code, tax_regime=tax_regime, payroll_date=payroll_date)
        if not version:
            return {}, []  # fail closed — see docstring; never return a partial rate_map
        resolved_versions[tax_code] = version

    rate_map: dict = {}
    slabs: list = []
    for tax_code, version in resolved_versions.items():
        for rule in db.query(TaxRule).filter(TaxRule.tax_version_id == version.id).order_by(TaxRule.sort_order).all():
            if rule.rule_type in ("FLAT_RATE", "CONTRIBUTION"):
                # Prefer the ORIGINAL, verbatim key a migrated rule carries
                # (TaxRule.legacy_component_key) over tax_code.lower() —
                # tax_code was normalized to uppercase-with-underscores
                # during migration (e.g. "medicare-levy" -> "MEDICARE_LEVY"),
                # but engine/standard.py's _calc_australia/_calc_germany
                # look these up by the EXACT original hyphenated string
                # ("medicare-levy", "social-insurance") — using tax_code
                # here would silently zero those contributions out the
                # moment an org cuts over to this resolver. A rule with no
                # legacy key (created fresh through the new UI, not
                # migrated) has no such constraint, so tax_code.lower() is
                # the sensible default there.
                component_key = (rule.legacy_component_key or tax_code).lower()
                rate = db.query(TaxRuleRate).filter(TaxRuleRate.tax_rule_id == rule.id).first()
                if rate:
                    flat_amount = rate.employee_flat_amount if rate.employee_flat_amount is not None else rate.employer_flat_amount
                    rate_map[component_key] = _V2RateRow(
                        component_key, rate.employee_rate_pct, rate.employer_rate_pct, flat_amount,
                    )
            else:
                for s in db.query(TaxRuleSlab).filter(TaxRuleSlab.tax_rule_id == rule.id).order_by(TaxRuleSlab.sort_order).all():
                    slabs.append(_V2SlabRow(s.min_amount, s.max_amount, s.rate_pct, s.rate_label, rule.rule_type, rule.formula_expression))

        for p in db.query(TaxParameter).filter(TaxParameter.tax_version_id == version.id).all():
            if p.unit == "percent":
                rate_map[p.parameter_key] = _V2RateRow(p.parameter_key, p.value_numeric, p.value_numeric, None)
            else:
                rate_map[p.parameter_key] = _V2RateRow(p.parameter_key, None, None, p.value_numeric)

    return rate_map, slabs
