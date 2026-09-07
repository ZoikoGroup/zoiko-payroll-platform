"""
modules/payroll/engine/countries/uk.py
-----------------------------------------
UK: National Insurance + Employer/Employee Pension + PAYE (tax-code aware,
sub-jurisdiction data-driven) + Student/Postgraduate Loan.

Genuinely jurisdiction-agnostic: this file never compares ctx.work_state
against a jurisdiction name (no `if ctx.work_state == "Scotland"`). Which
sub-jurisdiction's slabs/rates apply is decided once, upstream, by
service.py's resolve_uk_configuration() — this file only ever reads
whatever ended up in ctx.slabs/ctx.state_slabs/ctx.rate_map.
"""

from decimal import Decimal, ROUND_DOWN

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import (
    _calculate_annual_tax, resolve_jurisdiction_parameter,
    _param_text, resolve_periods_per_year, resolve_direct_period_threshold,
    _UK_NO_INDEPENDENT_PA_TAPER_ENABLED_COUNTRIES, _UK_K_CODE_50PCT_CAP_ENABLED_COUNTRIES,
    _UK_NI_CATEGORY_BANDS_ENABLED_COUNTRIES, _UK_NI_DIRECT_PERIOD_CALC_ENABLED_COUNTRIES,
    _UK_STUDENT_LOAN_ROUND_DOWN_ENABLED_COUNTRIES,
)

# Fallback constants moved to hardcoded_defaults.py — imported back under
# their original names so nothing else needs to change. See that file for
# the provenance comments on each.
from app.modules.payroll.hardcoded_defaults import (
    _UK_PERSONAL_ALLOWANCE, _UK_PA_TAPER_THRESHOLD, _UK_NI_PRIMARY_THRESHOLD,
    _UK_NI_UPPER_THRESHOLD, _UK_NI_PRIMARY_RATE, _UK_NI_UPPER_RATE,
    _UK_PENSION_MIN_ENPLOYER, _UK_NI_SECONDARY_THRESHOLD, _UK_NI_EMPLOYER_RATE,
    _UK_PENSION_QE_LOWER, _UK_PENSION_QE_UPPER, _UK_STUDENT_LOAN_PLANS, _UK_FLAT_RATE_CODES,
    _UK_NI_PRIMARY_THRESHOLD_BY_FREQUENCY, _UK_NI_UPPER_THRESHOLD_BY_FREQUENCY,
    _UK_NI_SECONDARY_THRESHOLD_BY_FREQUENCY, _UK_K_CODE_CAP_PCT,
)

# Threshold-only override keys for the plans exposed in the Compliance UI's
# Statutory Thresholds tab. Kept to <=20 chars — ContributionRate.component_key
# is varchar(20). This is a DB-key-name registry, not a hardcoded value
# itself, so it stays here rather than moving to hardcoded_defaults.py.
_UK_STUDENT_LOAN_PARAM_KEYS = {
    "UK_PLAN1": "sl_plan1_thresh",
    "UK_PLAN2": "sl_plan2_thresh",
    "UK_PLAN4": "sl_plan4_thresh",
    "UK_PLAN5": "sl_plan5_thresh",
    "UK_POSTGRAD": "pg_loan_thresh",
}


# ── PAYE tax-code interpretation ────────────────────────────────────────
# Handles standard codes ("1257L"/"S1257L"/"C1257L" -> allowance = digits
# x 10), K-codes (negative allowance -- untaxed benefit added to income,
# never tapered), 0T (zero allowance, still uses the regime's progressive
# bands), NT (no deduction), and the flat-rate override code families
# BR/D0/D1, SBR/SD0-3, CBR/CD0/CD1 (ZP-TAX-UK-2026-27-001 section 6.3).
#
# `region_prefix` ("S"/"C"/None) is the ONE place this file reads the
# code's leading letter — per the doc's non-negotiable control ("operate
# the HMRC-issued tax code prefix, never the worksite"), resolve_uk_
# configuration() in service.py uses this to pick the sub-jurisdiction,
# preferring it over employee.work_state. NT is explicitly never given an
# S/C prefix by HMRC (section 6.1) even though its own letters don't
# start with S/C anyway, so no special-casing is needed here.
#
# Deliberately NOT implementing true cumulative (Week1/Month1 vs
# cumulative YTD) PAYE basis -- that requires year-to-date income
# tracking this engine doesn't have for ANY country yet (same explicit
# deferral already on record for Student Loan balance tracking, below).
# `basis` is recorded on the result but every calculation stays
# period-by-period, as today.
def interpret_tax_code(tax_code: str | None, default_personal_allowance: Decimal) -> dict:
    if not tax_code:
        return {"personal_allowance": default_personal_allowance, "flat_rate_pct": None, "basis": "CUMULATIVE", "region_prefix": None}
    code = tax_code.upper().strip()

    # Flat-rate families are matched on the FULL code first: "SD0" and
    # "D0" are different HMRC codes at different rates (21% Scottish
    # intermediate vs 40% rUK higher) — stripping the prefix before this
    # check would wrongly collapse them onto the same rate.
    if code in _UK_FLAT_RATE_CODES:
        region_prefix = code[0] if code[0] in ("S", "C") else None
        return {"personal_allowance": Decimal("0"), "flat_rate_pct": _UK_FLAT_RATE_CODES[code], "basis": "NONCUMULATIVE", "region_prefix": region_prefix}
    if code == "NT":
        return {"personal_allowance": None, "flat_rate_pct": Decimal("0"), "basis": "NONCUMULATIVE", "region_prefix": None}

    region_prefix = None
    body = code
    if code[:1] in ("S", "C") and len(code) > 1:
        region_prefix = code[0]
        body = code[1:]

    if body == "0T":
        return {"personal_allowance": Decimal("0"), "flat_rate_pct": None, "basis": "CUMULATIVE", "region_prefix": region_prefix}
    if body.startswith("K") and body[1:].isdigit():
        return {"personal_allowance": -(Decimal(body[1:]) * 10), "flat_rate_pct": None, "basis": "CUMULATIVE", "region_prefix": region_prefix}
    digits = "".join(ch for ch in body if ch.isdigit())
    if digits:
        return {"personal_allowance": Decimal(digits) * 10, "flat_rate_pct": None, "basis": "CUMULATIVE", "region_prefix": region_prefix}
    return {"personal_allowance": default_personal_allowance, "flat_rate_pct": None, "basis": "CUMULATIVE", "region_prefix": region_prefix}


def _calculate_annual_tax_uk(annual_gross: Decimal, slabs, rate_map: dict, tax_code: str | None = None) -> Decimal:
    default_pa = resolve_jurisdiction_parameter(rate_map, "personal_allowance", _UK_PERSONAL_ALLOWANCE, country="UK")
    interpreted = interpret_tax_code(tax_code, default_pa)
    if interpreted["flat_rate_pct"] is not None:
        # BR/D0/D1 (flat rate on full income, no allowance) or NT (0%, no tax at all).
        return annual_gross * interpreted["flat_rate_pct"] / Decimal("100")

    pa = interpreted["personal_allowance"]
    # ZP-TAX-UK-2026-27-001 §5.1 PAYE implementation rule: "Zoiko Payroll
    # must not independently recompute an employee's tapered Personal
    # Allowance from payroll earnings. HMRC supplies the tax code that
    # operationalizes allowances..." — HMRC bakes any real taper into the
    # numeric code itself (a >£100k earner is issued a genuinely lower
    # code, not "1257L"), so re-tapering on top of that is exactly the
    # forbidden recompute. Dormant by default
    # (_UK_NO_INDEPENDENT_PA_TAPER_ENABLED_COUNTRIES) — while off, this
    # engine's original independent-taper behavior runs unchanged; once
    # on, `pa` is used exactly as parsed from the code, no taper at all.
    if "UK" not in _UK_NO_INDEPENDENT_PA_TAPER_ENABLED_COUNTRIES:
        taper_threshold = resolve_jurisdiction_parameter(rate_map, "pa_taper_threshold", _UK_PA_TAPER_THRESHOLD, country="UK")
        if pa >= 0 and annual_gross > taper_threshold:
            # Taper only applies to a standard positive allowance — a K-code's
            # negative allowance has nothing to taper.
            taper = (annual_gross - taper_threshold) / Decimal("2")
            pa = max(Decimal("0"), pa - taper)
    taxable = max(Decimal("0"), annual_gross - pa)
    return _calculate_annual_tax(taxable, slabs)


# ── National Insurance category bands ──────────────────────────────────
def _resolve_ni_bands(slabs, ni_category: str | None):
    """TaxSlab rows with rule_type="NI_BAND" for this employee's NI
    category, sorted by band. Returns [] when the employee has no
    category set, or no banded rows exist for it — the caller falls back
    to the flat ContributionRate percentage (today's only mechanism),
    exactly the same fallback shape already proven for India's PT_FLAT
    rows. Zero hardcoded per-category behavior: a new category becomes
    real the moment rows exist for it, no engine change required.

    Gated behind _UK_NI_CATEGORY_BANDS_ENABLED_COUNTRIES (shared.py):
    ni_category is already a live, employee-configurable field today, with
    every category currently computing via the flat Category-A-shaped
    fallback regardless of what's actually declared — seeding real banded
    data would otherwise silently change a real number for any org that
    already has an employee set to a non-A category. Returns [] (forcing
    the flat fallback) even once rows exist, until deliberately enabled."""
    if "UK" not in _UK_NI_CATEGORY_BANDS_ENABLED_COUNTRIES:
        return []
    if not ni_category:
        return []
    bands = [
        s for s in slabs
        if getattr(s, "rule_type", None) == "NI_BAND" and getattr(s, "ni_category", None) == ni_category
    ]
    return sorted(bands, key=lambda s: s.min_amount)


def _calculate_ni_from_bands(annual_gross: Decimal, bands: list) -> tuple[Decimal, Decimal]:
    employee_annual = Decimal("0")
    employer_annual = Decimal("0")
    for band in bands:
        lower = band.min_amount
        upper = band.max_amount if band.max_amount is not None else annual_gross
        if annual_gross <= lower:
            continue
        taxable_in_band = min(annual_gross, upper) - lower
        if taxable_in_band > 0:
            employee_annual += taxable_in_band * (band.rate_pct / Decimal("100"))
            employer_annual += taxable_in_band * ((band.employer_rate_pct or Decimal("0")) / Decimal("100"))
    return employee_annual, employer_annual


def _round_down_pound(value: Decimal) -> Decimal:
    """HMRC's Student/Postgraduate Loan rounding rule (ZP-TAX-UK-2026-27-001
    §10.2: "Round the deduction down to the nearest whole pound") — a
    UK-specific rounding convention, deliberately kept local to this file
    rather than added to engine/base.py's general-purpose _round2, which
    every other UK figure (and every other country) still uses unchanged."""
    return value.quantize(Decimal("1"), rounding=ROUND_DOWN)


def _compute_loan_repayment(plan_key: str | None, annual_gross: Decimal, periods_per_year: Decimal, rate_map: dict) -> Decimal:
    """One plan's period repayment — shared by the main study_loan_plan
    deduction and the concurrent Postgraduate Loan deduction (both draw
    from the same _UK_STUDENT_LOAN_PLANS table and the same rounding
    switch). Returns 0 for an unrecognized/unset plan_key, matching
    today's exact existing behavior for study_loan_plan."""
    plan = _UK_STUDENT_LOAN_PLANS.get(plan_key)
    if not plan:
        return Decimal("0")
    default_threshold, rate = plan
    param_key = _UK_STUDENT_LOAN_PARAM_KEYS.get(plan_key)
    threshold = (
        resolve_jurisdiction_parameter(rate_map, param_key, default_threshold, country="UK")
        if param_key else default_threshold
    )
    annual_repayment = max(Decimal("0"), annual_gross - threshold) * rate / Decimal("100")
    period_repayment = annual_repayment / periods_per_year
    # ZP-TAX-UK-2026-27-001 §10.2: "Round the deduction down to the
    # nearest whole pound." Dormant by default
    # (_UK_STUDENT_LOAN_ROUND_DOWN_ENABLED_COUNTRIES) — while off, rounds
    # to the nearest penny (_round2), today's exact existing behavior.
    return (
        _round_down_pound(period_repayment)
        if "UK" in _UK_STUDENT_LOAN_ROUND_DOWN_ENABLED_COUNTRIES
        else _round2(period_repayment)
    )


# ── Workplace Pension ────────────────────────────────────────────────────
def _resolve_pensionable_pay(ctx: PayrollContext, basis: str, qe_lower_period: Decimal, qe_upper_period: Decimal) -> Decimal:
    if basis == "BASIC_PAY":
        return ctx.basic
    if basis == "PENSIONABLE_EARNINGS":
        return ctx.gross
    # QUALIFYING_EARNINGS (default): banded slice of gross between the QE limits.
    return max(Decimal("0"), min(ctx.gross, qe_upper_period) - qe_lower_period)


def calculate(ctx: PayrollContext) -> dict:
    """UK: Employee + Employer National Insurance (category-banded where
    configured) + Employer/Employee Workplace Pension + PAYE (tax-code
    aware, sub-jurisdiction bands where configured) + Student/Postgraduate
    Loan. Frequency-aware: annualizes/de-annualizes using ctx.pay_frequency
    (defaults to "Monthly", so every existing employee's numbers are
    unchanged)."""
    rate_map = ctx.rate_map
    periods_per_year = resolve_periods_per_year(ctx.pay_frequency)
    annual_gross = ctx.gross * periods_per_year

    # NI_BAND rows (if any) live in the same TaxSlab list as income-tax
    # brackets — filtered out before either consumer sees the other's rows.
    income_slabs = [s for s in ctx.slabs if getattr(s, "rule_type", None) != "NI_BAND"]
    state_income_slabs = [s for s in ctx.state_slabs if getattr(s, "rule_type", None) != "NI_BAND"]

    ni_bands = _resolve_ni_bands(ctx.slabs, ctx.ni_category)
    if ni_bands:
        ni_employee_annual, ni_employer_annual = _calculate_ni_from_bands(annual_gross, ni_bands)
        ni_employee = _round2(ni_employee_annual / periods_per_year)
        employer_ni = _round2(ni_employer_annual / periods_per_year)
    elif "UK" in _UK_NI_DIRECT_PERIOD_CALC_ENABLED_COUNTRIES and (ctx.pay_frequency or "Monthly") in ("Weekly", "Monthly"):
        # Direct period calculation — no annualize/de-annualize round-trip
        # at all (ZP-TAX-UK-2026-27-001 §8.1: "Class 1 NIC is based on the
        # earnings period rather than cumulative annual earnings... must
        # not cause ordinary payroll to annualize NIC"). Real Weekly/
        # Monthly figures (hardcoded_defaults.py) don't derive from the
        # annual ones by division — HMRC rounds each period's table
        # independently. Scoped to Weekly/Monthly only: the document
        # doesn't publish Fortnightly/FourWeekly tables, so those keep
        # the annualize-then-divide fallback below.
        ni_primary_rate = resolve_jurisdiction_parameter(rate_map, "national-insurance", _UK_NI_PRIMARY_RATE, side="employee", country="UK")
        ni_upper_rate = resolve_jurisdiction_parameter(rate_map, "ni_upper_rate", _UK_NI_UPPER_RATE, side="employee", country="UK")
        ni_employer_rate = resolve_jurisdiction_parameter(rate_map, "national-insurance", _UK_NI_EMPLOYER_RATE, side="employer", country="UK")
        annual_ni_primary_threshold = resolve_jurisdiction_parameter(rate_map, "ni_primary_thresh", _UK_NI_PRIMARY_THRESHOLD, country="UK")
        annual_ni_upper_threshold = resolve_jurisdiction_parameter(rate_map, "ni_upper_threshold", _UK_NI_UPPER_THRESHOLD, country="UK")
        annual_ni_secondary_threshold = resolve_jurisdiction_parameter(rate_map, "ni_secondary_thresh", _UK_NI_SECONDARY_THRESHOLD, country="UK")

        period_primary_threshold = resolve_direct_period_threshold(_UK_NI_PRIMARY_THRESHOLD_BY_FREQUENCY, annual_ni_primary_threshold, ctx.pay_frequency)
        period_upper_threshold = resolve_direct_period_threshold(_UK_NI_UPPER_THRESHOLD_BY_FREQUENCY, annual_ni_upper_threshold, ctx.pay_frequency)
        period_secondary_threshold = resolve_direct_period_threshold(_UK_NI_SECONDARY_THRESHOLD_BY_FREQUENCY, annual_ni_secondary_threshold, ctx.pay_frequency)

        period_basicable = max(Decimal("0"), min(ctx.gross, period_upper_threshold) - period_primary_threshold)
        period_upperable = max(Decimal("0"), ctx.gross - period_upper_threshold)
        ni_employee = _round2((period_basicable * ni_primary_rate / Decimal("100")) + (period_upperable * ni_upper_rate / Decimal("100")))
        employer_ni = _round2(max(Decimal("0"), ctx.gross - period_secondary_threshold) * ni_employer_rate / Decimal("100"))
    else:
        ni_primary_threshold = resolve_jurisdiction_parameter(rate_map, "ni_primary_thresh", _UK_NI_PRIMARY_THRESHOLD, country="UK")
        ni_upper_threshold = resolve_jurisdiction_parameter(rate_map, "ni_upper_threshold", _UK_NI_UPPER_THRESHOLD, country="UK")
        ni_primary_rate = resolve_jurisdiction_parameter(rate_map, "national-insurance", _UK_NI_PRIMARY_RATE, side="employee", country="UK")
        ni_upper_rate = resolve_jurisdiction_parameter(rate_map, "ni_upper_rate", _UK_NI_UPPER_RATE, side="employee", country="UK")

        ni_basicable = max(Decimal("0"), min(annual_gross, ni_upper_threshold) - ni_primary_threshold)
        ni_upperable = max(Decimal("0"), annual_gross - ni_upper_threshold)
        ni_employee_annual = (ni_basicable * ni_primary_rate / Decimal("100")) + (ni_upperable * ni_upper_rate / Decimal("100"))
        ni_employee = _round2(ni_employee_annual / periods_per_year)

        ni_secondary_threshold = resolve_jurisdiction_parameter(rate_map, "ni_secondary_thresh", _UK_NI_SECONDARY_THRESHOLD, country="UK")
        ni_employer_rate = resolve_jurisdiction_parameter(rate_map, "national-insurance", _UK_NI_EMPLOYER_RATE, side="employer", country="UK")
        ni_employer_annual = max(Decimal("0"), annual_gross - ni_secondary_threshold) * ni_employer_rate / Decimal("100")
        employer_ni = _round2(ni_employer_annual / periods_per_year)

    employer_pension_rate = resolve_jurisdiction_parameter(rate_map, "employer-pension", _UK_PENSION_MIN_ENPLOYER, side="employer", country="UK")
    employer_pension = _round2(annual_gross * employer_pension_rate / Decimal("100") / periods_per_year)

    # Employee pension deduction — stays 0 (today's exact behavior) unless
    # an employee-side rate has been explicitly configured on the pension
    # row. Deliberately not defaulted to a nonzero statutory minimum here:
    # doing so would silently start deducting a new amount from every
    # existing UK organization's very next payslip. A Super Admin turns
    # this on explicitly via the Compliance UI when ready.
    employee_pension = Decimal("0")
    employee_pension_rate = resolve_jurisdiction_parameter(rate_map, "employer-pension", Decimal("0"), side="employee", country="UK")
    if employee_pension_rate > 0:
        qe_lower = resolve_jurisdiction_parameter(rate_map, "pension_qe_lower", _UK_PENSION_QE_LOWER, country="UK") / periods_per_year
        qe_upper = resolve_jurisdiction_parameter(rate_map, "pension_qe_upper", _UK_PENSION_QE_UPPER, country="UK") / periods_per_year
        basis = _param_text(rate_map, "pension_basis", "QUALIFYING_EARNINGS")
        pensionable_pay = _resolve_pensionable_pay(ctx, basis, qe_lower, qe_upper)
        employee_pension = _round2(pensionable_pay * employee_pension_rate / Decimal("100"))

    # Sub-jurisdiction (Scotland/Wales/Northern Ireland) sets its own
    # income tax bands where configured — resolved upstream by
    # service.py's resolve_uk_configuration(), never compared here.
    slabs_for_tax = state_income_slabs if state_income_slabs else income_slabs
    annual_tax = _calculate_annual_tax_uk(annual_gross, slabs_for_tax, rate_map, tax_code=ctx.tax_code)
    tds = _round2(annual_tax / periods_per_year)

    # K-code 50% cap (ZP-TAX-UK-2026-27-001 §6.2: "tax deduction cannot
    # exceed 50% of pre-tax pay/pension for the pay period"). Applied to
    # THIS PERIOD'S actual pay (ctx.gross), not the annual figure — the
    # cap exists specifically to protect a single low/irregular period
    # from a K-code's added notional income, which an annual-level cap
    # would only catch under perfectly uniform pay all year. Dormant by
    # default (_UK_K_CODE_50PCT_CAP_ENABLED_COUNTRIES) — while off, a
    # K-code's tax stays uncapped, today's exact existing behavior.
    if "UK" in _UK_K_CODE_50PCT_CAP_ENABLED_COUNTRIES:
        default_pa_for_cap = resolve_jurisdiction_parameter(rate_map, "personal_allowance", _UK_PERSONAL_ALLOWANCE, country="UK")
        pa_for_cap = interpret_tax_code(ctx.tax_code, default_pa_for_cap)["personal_allowance"]
        if pa_for_cap is not None and pa_for_cap < 0:
            k_code_cap_pct = resolve_jurisdiction_parameter(rate_map, "k_code_cap_pct", _UK_K_CODE_CAP_PCT, side="employee", country="UK")
            tds = min(tds, _round2(ctx.gross * k_code_cap_pct / Decimal("100")))

    # Deducted whenever an outstanding balance exists, at the plan's
    # threshold/rate — NOT capped by the balance itself: real Student
    # Loan repayment reduces the balance over time via cumulative YTD
    # tracking, which this engine doesn't yet do. study_loan_balance > 0
    # is only used as "does this employee currently have a loan to
    # repay," not as a per-payslip cap.
    # NOT capped by the balance itself: real Student Loan repayment
    # reduces the balance over time via cumulative YTD tracking, which
    # this engine doesn't yet do. study_loan_balance > 0 is only used as
    # "does this employee currently have a loan to repay."
    study_loan_deduction = Decimal("0")
    if ctx.study_loan_balance and ctx.study_loan_balance > 0:
        study_loan_deduction = _compute_loan_repayment(ctx.study_loan_plan, annual_gross, periods_per_year, rate_map)

    # Concurrent Postgraduate Loan (ZP-TAX-UK-2026-27-001 §10.2's own
    # worked example: Plan 5 + Postgraduate = two separate deduction
    # lines). Only ever additional to an UNDERGRADUATE plan — never
    # double-applied for an employee whose study_loan_plan is ALREADY
    # "UK_POSTGRAD" alone, which is fully handled by study_loan_deduction
    # above via the existing single-field mechanism. False/absent for
    # every employee today, so this is 0 unless explicitly configured.
    postgrad_loan_deduction = Decimal("0")
    if ctx.has_postgrad_loan and ctx.study_loan_plan != "UK_POSTGRAD":
        postgrad_loan_deduction = _compute_loan_repayment("UK_POSTGRAD", annual_gross, periods_per_year, rate_map)

    return dict(
        ni_employee=ni_employee,
        employer_ni=employer_ni,
        employer_pension=employer_pension,
        employee_pension=employee_pension,
        study_loan_deduction=study_loan_deduction,
        postgrad_loan_deduction=postgrad_loan_deduction,
        tds=tds, annual_tax=annual_tax,
    )
