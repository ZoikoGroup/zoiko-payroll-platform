"""
modules/payroll/engine/countries/india.py
--------------------------------------------
India: PF, ESI, Professional Tax, TDS. Moved verbatim out of
engine/standard.py's _calc_india — see that module's docstring for the
backward-compatibility contract this preserves.
"""

from datetime import date
from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import (
    MONTHS_PER_YEAR, _calculate_annual_tax, resolve_jurisdiction_parameter,
    _IN_PF_WAGE_CEILING_ENABLED_COUNTRIES, _IN_CODE_WAGES_ENABLED_COUNTRIES,
    _IN_OLD_REGIME_AGE_BANDS_ENABLED_COUNTRIES,
)

# Labour Codes' 50% allowance-cap rule (ZP-TAX-IN-2026-27-001 §8.1) — a
# fixed statutory fraction the Ministry of Labour FAQ states applies
# uniformly across all four Codes, not a jurisdiction-variable rate. Same
# footing as MONTHS_PER_YEAR elsewhere in this engine: a plain constant,
# not something Tax Ops configures per organization.
_IN_CODE_WAGES_ALLOWANCE_CAP_PCT = Decimal("50")
# Fallback constants moved to hardcoded_defaults.py (the consolidated home
# for every hardcoded fallback value in the payroll module) — imported
# back under their original names so nothing else needs to change.
from app.modules.payroll.hardcoded_defaults import (
    ESI_MONTHLY_WAGE_CEILING, _IN_STANDARD_DEDUCTION, _IN_STANDARD_DEDUCTION_OLD,
    _IN_REBATE_87A_LIMIT, _IN_REBATE_87A_MAX, _IN_REBATE_87A_LIMIT_OLD,
    _IN_REBATE_87A_MAX_OLD, _IN_CESS_PCT, _IN_PF_WAGE_CEILING,
)


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
    # Key shortened from "rebate_87a_marginal_relief" (26 chars) to fit
    # payroll_contribution_rates.component_key's VARCHAR(20) — the original
    # name always failed to save from the Tax Parameters UI.
    marginal_relief_on = resolve_jurisdiction_parameter(rate_map, "rebate_87a_mrelief", Decimal("1"), country="IN") == Decimal("1")

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

    # Key shortened from "surcharge_marginal_relief" (25 chars) — same
    # VARCHAR(20) fix as rebate_87a_mrelief above.
    marginal_relief_on = resolve_jurisdiction_parameter(rate_map, "surcharge_mrelief", Decimal("1"), country="IN") == Decimal("1")
    if not marginal_relief_on:
        return surcharge
    # Relief caps (tax + surcharge) at (plain tax at the tier's own
    # threshold + the excess income above it) — plain tax at the threshold
    # excludes surcharge itself (surcharge is 0 right at the threshold).
    bracket_slabs = [s for s in slabs if getattr(s, "rule_type", None) != "SURCHARGE"]
    tax_at_threshold = _calculate_annual_tax(tier.min_amount, bracket_slabs)
    excess_income = taxable_income - tier.min_amount
    return _capped_marginal_amount(annual_tax, surcharge, tax_at_threshold, excess_income)


_IN_PT_ADJUSTMENT_MONTH = 2  # February — the only real-world case this document gives (Maharashtra, §13.2)
_IN_PT_HALF_YEAR_MONTHS = Decimal("6")


def _pt_assessment_income(gross: Decimal, assessment_basis: str | None) -> Decimal:
    """Which income figure a PT_FLAT tier's min_amount/max_amount are
    measured against, per that tier's own assessment_basis
    (§12.1's state_rule schema field) — NULL/"MONTHLY_WAGE" (every
    existing state's data, e.g. Telangana) matches monthly gross
    unchanged; "HALF_YEAR_INCOME" (Greater Chennai Corporation's local
    half-yearly schedule, §14.1) matches an average half-yearly income.

    DISCLOSED SIMPLIFICATION: this engine has no rolling multi-month
    gross history for India (see MONTHS_PER_YEAR's identical
    current-period-times-N annualization for salary TDS elsewhere in
    this file) — half-yearly income is approximated as 6x this period's
    gross rather than a true trailing 6-month average."""
    basis = (assessment_basis or "MONTHLY_WAGE").strip().upper()
    if basis == "HALF_YEAR_INCOME":
        return gross * _IN_PT_HALF_YEAR_MONTHS
    if basis == "ANNUAL_SALARY":
        return gross * MONTHS_PER_YEAR
    return gross  # MONTHLY_WAGE / OTHER / unrecognized -> today's exact existing behavior


def _pt_half_year_deduction_active(state_rate_map: dict, pay_date) -> bool:
    """Half-yearly PT (assessment_basis="HALF_YEAR_INCOME") is a
    twice-a-year collection, not a monthly one — this returns True only
    in a state/locality's own configured collection month(s)
    (state_rate_map's pt_half_year_deduct_month_1/_2, same per-state-
    configurable-month convention as calculate()'s own LWF
    lwf_deduct_month below). No hardcoded fallback: an unconfigured
    half-year-assessed locality charges nothing in any month, rather than
    guessing a due date the source document doesn't give (§1.1's "never
    hard-code... a due date")."""
    if pay_date is None:
        return False
    for key in ("pt_half_year_deduct_month_1", "pt_half_year_deduct_month_2"):
        row = (state_rate_map or {}).get(key)
        if row is not None and row.flat_amount is not None and int(row.flat_amount) == pay_date.month:
            return True
    return False


def _resolve_state_pt_bracket(gross: Decimal, state_slabs, gender: str | None = None, pay_date=None):
    """Professional Tax is genuinely income-bracketed by law in several
    states (e.g. Telangana: Nil up to ₹15,000/month, ₹150 up to ₹20,000,
    ₹200 above) — this matches an employee's MONTHLY gross against the
    state's own PT_FLAT TaxSlab rows (min_amount/max_amount, same
    open-ended-top-bracket convention as every other TaxSlab use in this
    engine: max_amount=None means "and above"). Returns None when the
    state has no PT_FLAT rows configured (every state except Telangana
    today) — the caller falls back to the single-flat-rate behavior that
    already existed before this.

    Maharashtra (§13.2) needs two further dimensions this originally
    didn't:

    1. A gender-differentiated bracket — filing_status is repurposed to
    carry gender (MALE/FEMALE) rather than a new column, since PT has no
    concept of "filing status" of its own; same "specific tag beats
    generic NULL" precedence already used for filing_status elsewhere in
    this engine (US/Canada bracket resolution). Fails closed (returns
    None, never a guess) when every candidate tier in an income band is
    gender-tagged and the employee's own gender either isn't recorded or
    doesn't match any of them — this must NOT silently fall back to an
    arbitrary tagged tier for the wrong gender just because it sorts
    first.

    2. A February-only override amount ("₹200/month; ₹300 in February")
    — TaxSlab already has an `adjustment_amount` column built for exactly
    this ("many states adjust February so 11×monthly + this equals the
    statutory annual ceiling"), with existing Super Admin UI support
    (PTSlabFormModal's "Adjustment Month Amount" field) — this reads that
    existing column rather than inventing a parallel one."""
    tiers = sorted(
        (s for s in (state_slabs or []) if getattr(s, "rule_type", None) == "PT_FLAT"),
        key=lambda s: s.min_amount,
    )
    candidates = [
        t for t in tiers
        if (assessed := _pt_assessment_income(gross, getattr(t, "assessment_basis", None))) >= t.min_amount
        and (t.max_amount is None or assessed <= t.max_amount)
    ]
    if not candidates:
        return None
    tagged = [t for t in candidates if getattr(t, "filing_status", None)]
    if not tagged:
        # No tier in this band carries a gender tag at all (Telangana's
        # exact original shape) — plain, ungated match.
        match = candidates[0]
    elif gender and [t for t in tagged if t.filing_status == gender]:
        match = [t for t in tagged if t.filing_status == gender][0]
    else:
        generic = [t for t in candidates if not getattr(t, "filing_status", None)]
        match = generic[0] if generic else None

    if match is None:
        return None
    if (
        pay_date is not None and pay_date.month == _IN_PT_ADJUSTMENT_MONTH
        and getattr(match, "adjustment_amount", None) is not None
    ):
        return _PtAdjustmentAmount(match.adjustment_amount, getattr(match, "assessment_basis", None))
    return match


class _PtAdjustmentAmount:
    """Thin wrapper so the caller's existing `pt_bracket.flat_amount`
    read (calculate() below) picks up the February-adjusted figure
    without needing to know which of the two columns won. Also carries
    the original tier's assessment_basis through, so a half-year-assessed
    tier's February adjustment (if one ever exists) still gates on the
    half-year deduction month check rather than silently losing that
    classification."""
    def __init__(self, amount: Decimal, assessment_basis: str | None = None):
        self.flat_amount = amount
        self.assessment_basis = assessment_basis


# Default classification when no TaxabilityRule(tax_component="code_wages")
# row exists for a component — preserves this function's ORIGINAL
# basic-vs-everything-else approximation exactly: only "basic" defaults
# to core-included, every other named component defaults to excluded
# (subject to the add-back test), matching real Wage-Code practice
# (Basic/DA included; HRA/allowances excluded) as well as this engine's
# own pre-Phase-B behavior.
_IN_CODE_WAGES_DEFAULT_INCLUDED_COMPONENT = "basic"


def _resolve_code_wages_classification(component_key: str, code_wages_rules: dict) -> bool:
    """True = counts toward core_included_wages; False = excluded,
    subject to the 50%-cap add-back test. An explicit row in
    code_wages_rules (service.py's get_code_wages_classification, backed
    by TaxabilityRule) always wins; absent one, falls back to the default
    above."""
    if component_key in code_wages_rules:
        return code_wages_rules[component_key]
    return component_key == _IN_CODE_WAGES_DEFAULT_INCLUDED_COMPONENT


def _calculate_code_wages(ctx: PayrollContext, code_wages_rules: dict) -> Decimal:
    """ZP-TAX-IN-2026-27-001 §8.1's canonical Code-wages object — the
    50%-allowance-cap add-back that becomes the wage base for EPF/EPS/
    EDLI, not Basic directly.

    Phase B (2026-09-10 gap-closure follow-up): real per-component
    classification, replacing the earlier basic-vs-(gross-basic)
    two-bucket approximation. Classifies each of the employee's own named
    salary components (basic/hra/special_allowance/overtime/
    additional_compensation) plus a residual "named_allowances" bucket —
    for org-policy-driven allowances that are folded into ctx.gross but
    not individually exposed as their own PayrollContext field — via
    code_wages_rules (see _resolve_code_wages_classification). Every
    rupee of ctx.gross lands in exactly one bucket: named_allowances is
    defined as whatever remains of gross after the other five, so it
    always equals the org's configured allowance total exactly, and
    core_included_wages + excluded_total always equals ctx.gross."""
    named_allowances = max(
        Decimal("0"),
        ctx.gross - ctx.basic - ctx.hra - ctx.special_allowance - ctx.overtime - ctx.additional_compensation,
    )
    components = {
        "basic": ctx.basic,
        "hra": ctx.hra,
        "special_allowance": ctx.special_allowance,
        "overtime": ctx.overtime,
        "additional_compensation": ctx.additional_compensation,
        "named_allowances": named_allowances,
    }
    core_included_wages = Decimal("0")
    excluded_total = Decimal("0")
    for key, amount in components.items():
        if _resolve_code_wages_classification(key, code_wages_rules):
            core_included_wages += amount
        else:
            excluded_total += amount

    allowance_cap = ctx.gross * _IN_CODE_WAGES_ALLOWANCE_CAP_PCT / Decimal("100")
    add_back = max(Decimal("0"), excluded_total - allowance_cap)
    return core_included_wages + add_back


def _apply_cess(tax_plus_surcharge: Decimal, rate_map: dict) -> Decimal:
    cess_pct = resolve_jurisdiction_parameter(rate_map, "cess_pct", _IN_CESS_PCT, country="IN")
    return _round2(tax_plus_surcharge * (cess_pct / Decimal("100")))


_IN_SENIOR_AGE = 60
_IN_SUPER_SENIOR_AGE = 80


def _in_fy_end_date(pay_date: date) -> date:
    """India's financial year runs 1 April - 31 March. Returns the 31
    March that ENDS the FY containing pay_date (e.g. a pay_date anywhere
    in Apr 2026-Mar 2027 returns 2027-03-31)."""
    fy_end_year = pay_date.year + 1 if pay_date.month >= 4 else pay_date.year
    return date(fy_end_year, 3, 31)


def _resolve_old_regime_age_category(date_of_birth: date, tax_residency_status: str, pay_date: date) -> str | None:
    """ZP-TAX-IN-2026-27-001 §4.1/§4.2: Old Regime's senior (60-79)/super-
    senior (80+) basic-exemption bands apply only to RESIDENT individuals
    — §4.2's own instruction: "Nonresident old regime: use ordinary non-
    senior bands; senior-citizen basic exemption is resident-specific."
    Returns "SENIOR"/"SUPER_SENIOR" (matched against TaxSlab.filing_status,
    the same reuse-for-a-second-tag convention Maharashtra's PT gender
    tagging already established) or None (ordinary bands) whenever the
    dormant switch is off, tax_residency_status isn't affirmatively
    RESIDENT, date_of_birth/pay_date aren't both available, or the
    employee is simply under 60 — None is always the safe default,
    matching this engine's existing behavior exactly.

    Age is evaluated as of 31 March at the end of the relevant financial
    year (India's own real convention: turning 60/80 at ANY point during
    the FY, up to and including its last day, qualifies for the whole
    year) — not the literal pay date, so a mid-year birthday doesn't
    change which bands apply payslip-to-payslip."""
    if "IN" not in _IN_OLD_REGIME_AGE_BANDS_ENABLED_COUNTRIES:
        return None
    if not date_of_birth or not pay_date:
        return None
    if (tax_residency_status or "").strip().upper() != "RESIDENT":
        return None
    fy_end = _in_fy_end_date(pay_date)
    age = fy_end.year - date_of_birth.year - ((fy_end.month, fy_end.day) < (date_of_birth.month, date_of_birth.day))
    if age >= _IN_SUPER_SENIOR_AGE:
        return "SUPER_SENIOR"
    if age >= _IN_SENIOR_AGE:
        return "SENIOR"
    return None


def _calculate_annual_tax_in(
    annual_gross: Decimal, slabs, rate_map: dict, tax_regime: str = None, age_category: str = None,
    annual_professional_tax: Decimal = Decimal("0"), annual_employer_nps: Decimal = Decimal("0"),
    annual_other_income: Decimal = Decimal("0"), annual_claims_total: Decimal = Decimal("0"),
    annual_perquisites_total: Decimal = Decimal("0"), annual_tds_already_deducted: Decimal = Decimal("0"),
) -> dict:
    is_old = (tax_regime or "").strip().lower() == "old"
    default_standard_deduction = _IN_STANDARD_DEDUCTION_OLD if is_old else _IN_STANDARD_DEDUCTION
    standard_deduction = resolve_jurisdiction_parameter(rate_map, "standard_deduction", default_standard_deduction, country="IN")
    # Form 123 perquisites/profits-in-lieu-of-salary (§7) are salary
    # income under BOTH regimes — added alongside annual_gross itself,
    # before the standard deduction, not as a post-deduction adjustment.
    taxable = max(Decimal("0"), annual_gross + annual_perquisites_total - standard_deduction)
    # ZP-TAX-IN-2026-27-001 §4.2 "Critical regime separation": Professional
    # Tax reduces taxable salary under the OLD regime's own salary-deduction
    # framework, but must NEVER reduce taxable salary under the New/default
    # section 202 path — two independent eligibility maps, not one PT
    # deduction blindly applied to both (AC-08). Previously this deduction
    # didn't exist for EITHER regime at all.
    if is_old:
        taxable = max(Decimal("0"), taxable - annual_professional_tax)
        # Form 124 Chapter VIII claims (§4.2/§6.2) — Old regime only, per
        # the document's own "Accept only claim types valid for old-regime
        # payroll TDS." No source-given per-claim-type ceiling exists in
        # this pack, so Approved claims are summed uncapped (see
        # SalaryTdsClaim's own docstring for this disclosed choice).
        taxable = max(Decimal("0"), taxable - annual_claims_total)
    else:
        # §3.2's employer-NPS-contribution deduction is listed only under
        # the New Regime's own salary-deductions table (the document gives
        # no old-regime figure for it at all) — scoped here to New only,
        # matching what's actually specified rather than the general real-
        # world 80CCD(2) rule (which also exists under Old regime), since
        # this document is the production source of truth for this build.
        taxable = max(Decimal("0"), taxable - annual_employer_nps)
    # Form 122 (§6.1 step 4) — employee's own declared prior-employer
    # salary / other specified income / house-property loss, aggregated
    # into estimated total income. The document scopes this step
    # generically (not regime-specific like PT/NPS/claims above), so it
    # applies under both regimes.
    taxable = max(Decimal("0"), taxable + annual_other_income)
    tax = _calculate_annual_tax(taxable, slabs, filing_status=age_category)
    tax = max(Decimal("0"), _apply_section_87a_rebate(tax, taxable, rate_map, tax_regime=tax_regime))
    surcharge = _apply_surcharge(tax, taxable, slabs, rate_map)
    cess = _apply_cess(tax + surcharge, rate_map)
    # Form 122 (§6.1 step 7) — credit for tax already deducted by a prior
    # employer this tax year, against the TOTAL liability; never negative.
    net_liability = max(Decimal("0"), (tax + surcharge + cess) - annual_tds_already_deducted)
    return {
        "annual_tax": tax, "annual_surcharge": surcharge, "annual_cess": cess,
        "annual_net_liability": net_liability,
    }


def calculate(ctx: PayrollContext) -> dict:
    """India: PF, ESI, Professional Tax, TDS."""
    rate_map = ctx.rate_map
    gross = ctx.gross
    basic = ctx.basic

    pf_rate = rate_map.get("pf")
    # ZP-TAX-IN-2026-27-001 §8: the Labour Code's canonical Code-wages
    # object (50%-allowance-cap add-back) is meant to be calculated FIRST,
    # then passed into each scheme calculator (§8.1's "Design rule") —
    # dormant by default (_IN_CODE_WAGES_ENABLED_COUNTRIES), so this stays
    # exactly `basic` until deliberately enabled.
    pf_base_pre_ceiling = basic
    if "IN" in _IN_CODE_WAGES_ENABLED_COUNTRIES:
        pf_base_pre_ceiling = _calculate_code_wages(ctx, ctx.code_wages_rules)
    # ZP-TAX-IN-2026-27-001 §9.1: EPF's contribution base is capped at the
    # statutory monthly wage ceiling (₹15,000), not full uncapped Basic.
    # Dormant by default (_IN_PF_WAGE_CEILING_ENABLED_COUNTRIES) — see
    # shared.py's switch comment for why this real correctness fix still
    # ships behind a rollout gate rather than changing live withholding
    # the moment it merges.
    pf_wage_base = pf_base_pre_ceiling
    if "IN" in _IN_PF_WAGE_CEILING_ENABLED_COUNTRIES:
        pf_ceiling = resolve_jurisdiction_parameter(rate_map, "pf_wage_ceiling", _IN_PF_WAGE_CEILING, country="IN")
        pf_wage_base = min(pf_base_pre_ceiling, pf_ceiling)
    employee_pf = _round2(pf_wage_base * (pf_rate.employee_rate_pct / 100)) if pf_rate and pf_rate.employee_rate_pct else Decimal("0")
    employer_pf = _round2(pf_wage_base * (pf_rate.employer_rate_pct / 100)) if pf_rate and pf_rate.employer_rate_pct else Decimal("0")

    # EPS diversion (§9.1: "8.33% diverted from employer PF share",
    # "Subject to INR 15,000 pensionable-wage ceiling") — an EPFO-internal
    # ROUTING of the SAME employer_pf total computed above, not an
    # additional employer cost. Genuinely new statutory data with no
    # hardcoded fallback (§9.3: "Compute residual, do not hard-code a
    # split that can fail edge cases") — resolves to 0/employer_pf
    # unchanged until Tax Ops configures "eps_rate"/"eps_wage_ceiling" via
    # the Super Admin UI. Reported as an informational breakdown
    # (employer_eps + employer_pf_residual = employer_pf, always) rather
    # than a switch-gated change, since it never alters employer_pf or
    # net pay — only how the existing total is itemized for EPFO filing.
    eps_rate_row = rate_map.get("eps_rate")
    employer_eps = Decimal("0")
    if eps_rate_row and eps_rate_row.employer_rate_pct:
        eps_ceiling_row = rate_map.get("eps_wage_ceiling")
        eps_wage_base = pf_wage_base
        if eps_ceiling_row and eps_ceiling_row.flat_amount:
            eps_wage_base = min(pf_wage_base, eps_ceiling_row.flat_amount)
        uncapped_eps = _round2(eps_wage_base * (eps_rate_row.employer_rate_pct / 100))
        employer_eps = min(employer_pf, uncapped_eps)
    employer_pf_residual = employer_pf - employer_eps

    # EDLI (§9.1: "0.5%", "Current wage ceiling INR 15,000") — a genuinely
    # SEPARATE employer-only statutory liability, additional to
    # employer_pf (not diverted from it). No hardcoded fallback: resolves
    # to 0 until Tax Ops configures "edli_rate"/"edli_wage_ceiling".
    edli_rate_row = rate_map.get("edli_rate")
    employer_edli = Decimal("0")
    if edli_rate_row and edli_rate_row.employer_rate_pct:
        edli_ceiling_row = rate_map.get("edli_wage_ceiling")
        edli_wage_base = pf_wage_base
        if edli_ceiling_row and edli_ceiling_row.flat_amount:
            edli_wage_base = min(pf_wage_base, edli_ceiling_row.flat_amount)
        employer_edli = _round2(edli_wage_base * (edli_rate_row.employer_rate_pct / 100))

    # Employer NPS contribution (§3.2: "Up to statutory percentage under
    # applicable section; 14% path available under new regime for
    # qualifying employer contribution") — a genuinely SEPARATE employer-
    # only cost, additional to employer_pf, computed on Basic (this
    # engine's existing wage-base convention for every scheme-specific
    # employer contribution above). No hardcoded fallback: resolves to 0
    # until Tax Ops configures "nps_employer_pct". Whether it also REDUCES
    # taxable salary (New Regime only, per this document) is decided
    # independently in _calculate_annual_tax_in — an untagged rate applies
    # this COST to both regimes, but only ever reduces taxable income for
    # New, matching §3.2's own scoping regardless of how the rate is tagged.
    nps_rate_row = rate_map.get("nps_employer_pct")
    employer_nps = Decimal("0")
    if nps_rate_row and nps_rate_row.employer_rate_pct:
        employer_nps = _round2(basic * (nps_rate_row.employer_rate_pct / 100))

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
    pt_bracket = _resolve_state_pt_bracket(gross, ctx.state_slabs, gender=ctx.gender, pay_date=ctx.pay_date)
    if pt_bracket is not None:
        professional_tax = pt_bracket.flat_amount or Decimal("0")
        # Half-yearly-assessed PT (Greater Chennai Corporation's local
        # schedule, §14.1) is a twice-a-year collection, not a monthly
        # deduction — zero it out except in the state/locality's own
        # configured collection month(s) (see
        # _pt_half_year_deduction_active's own docstring for why there is
        # no hardcoded fallback due date).
        pt_basis = (getattr(pt_bracket, "assessment_basis", None) or "MONTHLY_WAGE").strip().upper()
        if pt_basis == "HALF_YEAR_INCOME" and not _pt_half_year_deduction_active(ctx.state_rate_map, ctx.pay_date):
            professional_tax = Decimal("0")
    else:
        state_pt_rate = (ctx.state_rate_map or {}).get("pt")
        pt_rate = state_pt_rate if state_pt_rate and state_pt_rate.flat_amount else rate_map.get("pt")
        professional_tax = pt_rate.flat_amount if pt_rate and pt_rate.flat_amount else Decimal("0")

    # Labour Welfare Fund (§15) — a state-specific ANNUAL contribution
    # (Karnataka: ₹50 employee/₹100 employer per year; Tamil Nadu: ₹20/
    # ₹40), not a monthly deduction — charged only in the one payroll
    # month Tax Ops configures as this state's deduction month, out of
    # its own state_rate_map row. Genuinely new statutory data, no
    # hardcoded fallback whatsoever: unconfigured state, unconfigured
    # amount, OR unconfigured month all resolve to 0 rather than a guess
    # at which month "annual" should mean.
    employee_lwf = Decimal("0")
    employer_lwf = Decimal("0")
    lwf_month_row = (ctx.state_rate_map or {}).get("lwf_deduct_month")
    if lwf_month_row and lwf_month_row.flat_amount is not None and ctx.pay_date is not None:
        if int(lwf_month_row.flat_amount) == ctx.pay_date.month:
            lwf_employee_row = (ctx.state_rate_map or {}).get("lwf_employee_amt")
            lwf_employer_row = (ctx.state_rate_map or {}).get("lwf_employer_amt")
            employee_lwf = lwf_employee_row.flat_amount if lwf_employee_row and lwf_employee_row.flat_amount else Decimal("0")
            employer_lwf = lwf_employer_row.flat_amount if lwf_employer_row and lwf_employer_row.flat_amount else Decimal("0")

    annual_gross = gross * MONTHS_PER_YEAR
    age_category = _resolve_old_regime_age_category(ctx.date_of_birth, ctx.tax_residency_status, ctx.pay_date)
    tax_breakdown = _calculate_annual_tax_in(
        annual_gross, ctx.slabs, rate_map, tax_regime=ctx.tax_regime, age_category=age_category,
        annual_professional_tax=professional_tax * MONTHS_PER_YEAR,
        annual_employer_nps=employer_nps * MONTHS_PER_YEAR,
        # Forms 122/123/124 (§6.2) already carry whole-tax-year figures —
        # unlike professional_tax/employer_nps above, these are NOT
        # multiplied by MONTHS_PER_YEAR.
        annual_other_income=ctx.other_income_for_tds, annual_claims_total=ctx.annual_claims_total,
        annual_perquisites_total=ctx.annual_perquisites_total, annual_tds_already_deducted=ctx.tds_already_deducted,
    )
    annual_tax = tax_breakdown["annual_tax"]
    annual_surcharge = tax_breakdown["annual_surcharge"]
    annual_cess = tax_breakdown["annual_cess"]
    annual_net_liability = tax_breakdown["annual_net_liability"]
    # tds is the FULL monthly income-tax liability, net of any Form 122
    # prior-employer-TDS credit — base tax + surcharge + cess, minus that
    # credit, spread evenly over the remaining months. surcharge/cess
    # below are still the un-netted breakdown of what's INSIDE the gross
    # (pre-credit) liability, for display — not additional deductions
    # layered on top of tds.
    tds = _round2(annual_net_liability / MONTHS_PER_YEAR)
    surcharge = _round2(annual_surcharge / MONTHS_PER_YEAR)
    cess = _round2(annual_cess / MONTHS_PER_YEAR)

    return dict(
        employee_pf=employee_pf, employer_pf=employer_pf,
        employer_eps=employer_eps, employer_pf_residual=employer_pf_residual,
        employer_edli=employer_edli, employer_nps=employer_nps,
        employee_esi=employee_esi, employer_esi=employer_esi,
        professional_tax=professional_tax,
        employee_lwf=employee_lwf, employer_lwf=employer_lwf,
        tds=tds, annual_tax=annual_tax, surcharge=surcharge, cess=cess,
    )


# ── Gratuity — an employer termination liability, NOT a payroll deduction ──
# ZP-TAX-IN-2026-27-001 §11: "Gratuity is not a routine employee payroll
# deduction. It is an employer statutory liability and termination/fixed-
# term benefit calculation." Deliberately a standalone function, never
# called from calculate() above — that function runs once per RECURRING
# payroll cycle; gratuity is a ONE-TIME event tied to employment ending,
# with its own inputs (dates, last-drawn wage) that don't exist in
# PayrollContext at all.

# The "15 days' wages per completed year, wages/26" formula and the
# "6+ months of a partial year rounds up to a full year" rule are the
# Payment of Gratuity Act's own long-established formula STRUCTURE (not a
# jurisdiction-variable rate Tax Ops would ever configure differently) —
# same footing as MONTHS_PER_YEAR/_IN_CODE_WAGES_ALLOWANCE_CAP_PCT above.
# What genuinely IS statutory data requiring configuration, with no
# hardcoded fallback (§11: "Do not hard-code an unverified ceiling"): the
# notified maximum amount and the minimum qualifying years of service.
_IN_GRATUITY_DAYS_PER_YEAR = Decimal("15")
_IN_GRATUITY_WAGE_DIVISOR = Decimal("26")
_IN_GRATUITY_PARTIAL_YEAR_ROUND_UP_MONTHS = 6


def _completed_service_months(date_of_joining: date, date_of_leaving: date) -> int:
    months = (date_of_leaving.year - date_of_joining.year) * 12 + (date_of_leaving.month - date_of_joining.month)
    if date_of_leaving.day < date_of_joining.day:
        months -= 1
    return max(0, months)


def calculate_gratuity(
    date_of_joining: date,
    date_of_leaving: date,
    last_drawn_monthly_wage: Decimal,
    rate_map: dict,
    eligibility_event: str = "RESIGNATION",
    is_fixed_term: bool = False,
) -> dict:
    """Returns a dict with `eligible` (bool), `reason` (str), and
    `gratuity_amount` (Decimal, 0 when not eligible/not computable).
    `eligibility_event` — one of RETIREMENT/RESIGNATION/TERMINATION/
    DEATH/DISABLEMENT/FIXED_TERM_END (§11's eligibility-event list);
    DEATH/DISABLEMENT waive the minimum-qualifying-years requirement,
    matching the real Act's own well-established treatment of those two
    events specifically — this is NOT a guessed number, unlike the min-
    years threshold itself, which stays fully DB-configurable.

    `is_fixed_term=True` uses PRO-RATA fractional-year service (§11:
    "Support statutory fixed-term gratuity treatment and pro-rata
    calculation") instead of the completed-year rounding rule, since a
    fixed-term employee's gratuity isn't gated by the same multi-year
    minimum service test at all.

    Fails closed (§1.1: "Unsupported or unverified... must fail closed:
    block activation instead of silently using a historical or guessed
    rate") whenever gratuity_min_yrs isn't configured and the event isn't
    DEATH/DISABLEMENT/FIXED_TERM_END — this function will never silently
    assume a 5-year (or any other) threshold on your behalf.

    componentKey max 20 chars (payroll_contribution_rates.component_key
    is VARCHAR(20)) — "gratuity_min_qualifying_years"/
    "gratuity_max_notified_amount" both exceed it, so this reads the
    shortened "gratuity_min_yrs"/"gratuity_max_amt" instead."""
    months = _completed_service_months(date_of_joining, date_of_leaving)
    wage_per_day = last_drawn_monthly_wage / _IN_GRATUITY_WAGE_DIVISOR
    per_year_amount = wage_per_day * _IN_GRATUITY_DAYS_PER_YEAR

    if is_fixed_term or eligibility_event == "FIXED_TERM_END":
        service_years = Decimal(months) / Decimal("12")
        gratuity_amount = _round2(per_year_amount * service_years)
    else:
        completed_years = months // 12
        remainder_months = months % 12
        if remainder_months >= _IN_GRATUITY_PARTIAL_YEAR_ROUND_UP_MONTHS:
            completed_years += 1

        waives_min_service = eligibility_event in ("DEATH", "DISABLEMENT")
        if not waives_min_service:
            min_years_row = rate_map.get("gratuity_min_yrs")
            if not min_years_row or min_years_row.flat_amount is None:
                return {"eligible": False, "reason": "gratuity_min_yrs not configured", "gratuity_amount": Decimal("0")}
            if Decimal(completed_years) < min_years_row.flat_amount:
                return {"eligible": False, "reason": "below minimum qualifying years of service", "gratuity_amount": Decimal("0")}

        gratuity_amount = _round2(per_year_amount * Decimal(completed_years))

    max_row = rate_map.get("gratuity_max_amt")
    if max_row and max_row.flat_amount is not None:
        gratuity_amount = min(gratuity_amount, max_row.flat_amount)

    return {"eligible": True, "reason": "", "gratuity_amount": gratuity_amount}
