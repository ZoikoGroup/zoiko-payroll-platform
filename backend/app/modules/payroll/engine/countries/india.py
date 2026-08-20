"""
modules/payroll/engine/countries/india.py
--------------------------------------------
India: PF, ESI, Professional Tax, TDS. Moved verbatim out of
engine/standard.py's _calc_india — see that module's docstring for the
backward-compatibility contract this preserves.
"""

from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import MONTHS_PER_YEAR, _calculate_annual_tax, resolve_jurisdiction_parameter

ESI_MONTHLY_WAGE_CEILING = Decimal("21000")
_IN_STANDARD_DEDUCTION = Decimal("75000")
# Old Regime's own standard deduction — only read when ctx.tax_regime == "Old".
_IN_STANDARD_DEDUCTION_OLD = Decimal("50000")
# New Regime Section 87A defaults (today's only regime, unchanged).
_IN_REBATE_87A_LIMIT = Decimal("1200000")
_IN_REBATE_87A_MAX = Decimal("60000")
# Old Regime Section 87A defaults — only read when ctx.tax_regime == "Old".
_IN_REBATE_87A_LIMIT_OLD = Decimal("500000")
_IN_REBATE_87A_MAX_OLD = Decimal("12500")
# Health & Education Cess — applied on (tax + surcharge). Absent from this
# engine entirely before this change; every Indian org's computed TDS grows
# by ~4% as of this change, a deliberate, confirmed correction, not a bug.
_IN_CESS_PCT = Decimal("4")


def _capped_marginal_amount(base_amount: Decimal, added_amount: Decimal, amount_at_threshold: Decimal, excess_income: Decimal) -> Decimal:
    """General marginal-relief cap, shared by Section 87A and the
    surcharge: `base_amount + added_amount` (tax, or tax+surcharge) can
    never exceed `amount_at_threshold + excess_income` — i.e. crossing an
    income threshold by ₹1 can never cost more than ₹1 in extra liability.
    Returns the (possibly relieved) `added_amount`, with `base_amount` held
    fixed. `excess_income` must already be >= 0 (caller only invokes this
    once the relevant threshold has actually been crossed)."""
    capped_total = min(base_amount + added_amount, amount_at_threshold + excess_income)
    return max(Decimal("0"), capped_total - base_amount)


def _apply_section_87a_rebate(annual_tax: Decimal, taxable_income: Decimal, rate_map: dict, tax_regime: str = None) -> Decimal:
    is_old = (tax_regime or "").strip().lower() == "old"
    default_limit = _IN_REBATE_87A_LIMIT_OLD if is_old else _IN_REBATE_87A_LIMIT
    default_max = _IN_REBATE_87A_MAX_OLD if is_old else _IN_REBATE_87A_MAX
    rebate_limit = resolve_jurisdiction_parameter(rate_map, "rebate_87a_limit", default_limit, country="IN")
    rebate_max = resolve_jurisdiction_parameter(rate_map, "rebate_87a_max", default_max, country="IN")
    marginal_relief_on = resolve_jurisdiction_parameter(rate_map, "rebate_87a_marginal_relief", Decimal("1"), country="IN") == Decimal("1")

    if taxable_income <= rebate_limit:
        rebate = min(annual_tax, rebate_max)
        return annual_tax - rebate
    if not marginal_relief_on:
        return annual_tax
    # Tax payable exactly at the rebate limit is 0 (the rebate, calibrated
    # to rebate_max, fully cancels tax there) — so relief simply caps
    # payable tax at the amount of income above the limit.
    excess_income = taxable_income - rebate_limit
    return _capped_marginal_amount(Decimal("0"), annual_tax, Decimal("0"), excess_income)


def _apply_surcharge(annual_tax: Decimal, taxable_income: Decimal, slabs, rate_map: dict) -> Decimal:
    """India's surcharge on high incomes — a % of the TAX amount itself
    (not of income), applied above a series of income thresholds. Tiers are
    TaxSlab rows with rule_type="SURCHARGE" (min_amount=threshold,
    rate_pct=surcharge %); slabs with no such rows configured (every org
    today) produce zero surcharge, exactly today's behavior."""
    tiers = sorted(
        (s for s in slabs if getattr(s, "rule_type", None) == "SURCHARGE"),
        key=lambda s: s.min_amount,
    )
    applicable = [t for t in tiers if taxable_income > t.min_amount]
    if not applicable:
        return Decimal("0")
    tier = applicable[-1]  # highest threshold crossed
    surcharge = annual_tax * (tier.rate_pct / Decimal("100"))

    marginal_relief_on = resolve_jurisdiction_parameter(rate_map, "surcharge_marginal_relief", Decimal("1"), country="IN") == Decimal("1")
    if not marginal_relief_on:
        return surcharge
    # Relief caps (tax + surcharge) at (plain tax at the tier's own
    # threshold + the excess income above it) — plain tax at the threshold
    # excludes surcharge itself (surcharge is 0 right at the threshold).
    bracket_slabs = [s for s in slabs if getattr(s, "rule_type", None) != "SURCHARGE"]
    tax_at_threshold = _calculate_annual_tax(tier.min_amount, bracket_slabs)
    excess_income = taxable_income - tier.min_amount
    return _capped_marginal_amount(annual_tax, surcharge, tax_at_threshold, excess_income)


def _resolve_state_pt_bracket(gross: Decimal, state_slabs):
    """Professional Tax is genuinely income-bracketed by law in several
    states (e.g. Telangana: Nil up to ₹15,000/month, ₹150 up to ₹20,000,
    ₹200 above) — this matches an employee's MONTHLY gross against the
    state's own PT_FLAT TaxSlab rows (min_amount/max_amount, same
    open-ended-top-bracket convention as every other TaxSlab use in this
    engine: max_amount=None means "and above"). Returns None when the
    state has no PT_FLAT rows configured (every state except Telangana
    today) — the caller falls back to the single-flat-rate behavior that
    already existed before this."""
    tiers = sorted(
        (s for s in (state_slabs or []) if getattr(s, "rule_type", None) == "PT_FLAT"),
        key=lambda s: s.min_amount,
    )
    for tier in tiers:
        if gross >= tier.min_amount and (tier.max_amount is None or gross <= tier.max_amount):
            return tier
    return None


def _apply_cess(tax_plus_surcharge: Decimal, rate_map: dict) -> Decimal:
    cess_pct = resolve_jurisdiction_parameter(rate_map, "cess_pct", _IN_CESS_PCT, country="IN")
    return _round2(tax_plus_surcharge * (cess_pct / Decimal("100")))


def _calculate_annual_tax_in(annual_gross: Decimal, slabs, rate_map: dict, tax_regime: str = None) -> dict:
    is_old = (tax_regime or "").strip().lower() == "old"
    default_standard_deduction = _IN_STANDARD_DEDUCTION_OLD if is_old else _IN_STANDARD_DEDUCTION
    standard_deduction = resolve_jurisdiction_parameter(rate_map, "standard_deduction", default_standard_deduction, country="IN")
    taxable = max(Decimal("0"), annual_gross - standard_deduction)
    tax = _calculate_annual_tax(taxable, slabs)
    tax = max(Decimal("0"), _apply_section_87a_rebate(tax, taxable, rate_map, tax_regime=tax_regime))
    surcharge = _apply_surcharge(tax, taxable, slabs, rate_map)
    cess = _apply_cess(tax + surcharge, rate_map)
    return {"annual_tax": tax, "annual_surcharge": surcharge, "annual_cess": cess}


def calculate(ctx: PayrollContext) -> dict:
    """India: PF, ESI, Professional Tax, TDS."""
    rate_map = ctx.rate_map
    gross = ctx.gross
    basic = ctx.basic

    pf_rate = rate_map.get("pf")
    employee_pf = _round2(basic * (pf_rate.employee_rate_pct / 100)) if pf_rate and pf_rate.employee_rate_pct else Decimal("0")
    employer_pf = _round2(basic * (pf_rate.employer_rate_pct / 100)) if pf_rate and pf_rate.employer_rate_pct else Decimal("0")

    esi_rate = rate_map.get("esi")
    esi_ceiling = resolve_jurisdiction_parameter(rate_map, "esi_wage_ceiling", ESI_MONTHLY_WAGE_CEILING, country="IN")
    esi_applicable = gross <= esi_ceiling
    employee_esi = _round2(gross * (esi_rate.employee_rate_pct / 100)) if esi_rate and esi_rate.employee_rate_pct and esi_applicable else Decimal("0")
    employer_esi = _round2(gross * (esi_rate.employer_rate_pct / 100)) if esi_rate and esi_rate.employer_rate_pct and esi_applicable else Decimal("0")

    # Professional Tax is genuinely state-specific in India, and in several
    # states genuinely bracketed by the employee's own gross salary (not a
    # single flat number) — checked first via ctx.state_slabs' PT_FLAT
    # rows (Telangana: Nil/₹150/₹200 by income tier). Only when no such
    # bracket resolves (every state except Telangana today) does this fall
    # back to the single-flat-rate ctx.state_rate_map lookup, then the
    # country-level flat "pt" rate — both exactly as before this existed.
    pt_bracket = _resolve_state_pt_bracket(gross, ctx.state_slabs)
    if pt_bracket is not None:
        professional_tax = pt_bracket.flat_amount or Decimal("0")
    else:
        state_pt_rate = (ctx.state_rate_map or {}).get("pt")
        pt_rate = state_pt_rate if state_pt_rate and state_pt_rate.flat_amount else rate_map.get("pt")
        professional_tax = pt_rate.flat_amount if pt_rate and pt_rate.flat_amount else Decimal("0")

    annual_gross = gross * MONTHS_PER_YEAR
    tax_breakdown = _calculate_annual_tax_in(annual_gross, ctx.slabs, rate_map, tax_regime=ctx.tax_regime)
    annual_tax = tax_breakdown["annual_tax"]
    annual_surcharge = tax_breakdown["annual_surcharge"]
    annual_cess = tax_breakdown["annual_cess"]
    # tds is the FULL monthly income-tax liability — base tax + surcharge +
    # cess, all three, matching how TDS actually works in practice.
    # surcharge/cess below are just the breakdown of what's already
    # inside tds, not additional deductions layered on top of it.
    tds = _round2((annual_tax + annual_surcharge + annual_cess) / MONTHS_PER_YEAR)
    surcharge = _round2(annual_surcharge / MONTHS_PER_YEAR)
    cess = _round2(annual_cess / MONTHS_PER_YEAR)

    return dict(
        employee_pf=employee_pf, employer_pf=employer_pf,
        employee_esi=employee_esi, employer_esi=employer_esi,
        professional_tax=professional_tax,
        tds=tds, annual_tax=annual_tax, surcharge=surcharge, cess=cess,
    )
