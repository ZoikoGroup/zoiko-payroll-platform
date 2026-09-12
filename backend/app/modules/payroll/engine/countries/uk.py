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

from datetime import date
from decimal import Decimal, ROUND_DOWN

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import (
    _calculate_annual_tax, resolve_jurisdiction_parameter,
    _param_text, resolve_periods_per_year, resolve_direct_period_threshold,
    telescope_period_amount,
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


def _annual_ni_due(cumulative_gross: Decimal, rate_map: dict) -> tuple[Decimal, Decimal]:
    """Employee+employer NIC due on `cumulative_gross`, computed against
    the ANNUAL PT/UEL/ST thresholds and flat Category-A-shaped rates —
    the core of a director's statutory "annual earnings method" (§9.2):
    NIC is assessed against cumulative-to-date earnings and the ANNUAL
    thresholds directly, never a per-period slice. Same threshold/rate
    keys the ordinary employee calculation already resolves — a
    director's NIC rates are not a separately configured statutory
    figure per §9.2, only the earnings-PERIOD method differs."""
    pt = resolve_jurisdiction_parameter(rate_map, "ni_primary_thresh", _UK_NI_PRIMARY_THRESHOLD, country="UK")
    uel = resolve_jurisdiction_parameter(rate_map, "ni_upper_threshold", _UK_NI_UPPER_THRESHOLD, country="UK")
    st = resolve_jurisdiction_parameter(rate_map, "ni_secondary_thresh", _UK_NI_SECONDARY_THRESHOLD, country="UK")
    employee_rate = resolve_jurisdiction_parameter(rate_map, "national-insurance", _UK_NI_PRIMARY_RATE, side="employee", country="UK")
    upper_rate = resolve_jurisdiction_parameter(rate_map, "ni_upper_rate", _UK_NI_UPPER_RATE, side="employee", country="UK")
    employer_rate = resolve_jurisdiction_parameter(rate_map, "national-insurance", _UK_NI_EMPLOYER_RATE, side="employer", country="UK")

    basicable = max(Decimal("0"), min(cumulative_gross, uel) - pt)
    upperable = max(Decimal("0"), cumulative_gross - uel)
    employee_due = basicable * employee_rate / Decimal("100") + upperable * upper_rate / Decimal("100")
    employer_due = max(Decimal("0"), cumulative_gross - st) * employer_rate / Decimal("100")
    return employee_due, employer_due


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

    # Directors NIC (§9.2: "Do not process a director as an ordinary
    # employee solely because the same percentage rates apply") — takes
    # precedence over every other NI path below. Dormant until REAL
    # cumulative YTD data is actually loaded (ctx.ytd_director_ni_gross is
    # not None): without it, there is no meaningful "annual earnings
    # method" to perform (a single period's gross annualized-as-a-guess
    # is exactly what the ordinary-employee path below already computes),
    # so this deliberately falls through to that unchanged path rather
    # than invent a director-specific number from no real history.
    use_director_annual_method = (
        ctx.is_director and ctx.ytd_director_ni_gross is not None
        and (ctx.director_ni_method != "ALTERNATIVE" or ctx.is_final_ni_period)
    )
    if use_director_annual_method:
        cumulative_gross = ctx.ytd_director_ni_gross + ctx.gross
        ytd_employee_paid = ctx.ytd_director_ni_employee_paid or Decimal("0")
        ytd_employer_paid = ctx.ytd_director_ni_employer_paid or Decimal("0")
        employee_due_to_date, employer_due_to_date = _annual_ni_due(cumulative_gross, rate_map)
        ni_employee = _round2(max(Decimal("0"), employee_due_to_date - ytd_employee_paid))
        employer_ni = _round2(max(Decimal("0"), employer_due_to_date - ytd_employer_paid))
    elif (ni_bands := _resolve_ni_bands(ctx.slabs, ctx.ni_category)):
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

    # Directors NIC YTD — accumulation must continue correctly regardless
    # of WHICH branch above priced this period (annual method, ALTERNATIVE
    # method's ordinary calc, or the fully-dormant fallback when no
    # accumulator was loaded at all): whatever ni_employee/employer_ni
    # ended up being, it's added to the running cumulative totals so
    # service.py can persist the correct "after" state. None (not
    # computed at all) for a non-director, matching every other YTD
    # field's "None means not applicable" contract.
    ytd_director_ni_gross_after = None
    ytd_director_ni_employee_paid_after = None
    ytd_director_ni_employer_paid_after = None
    if ctx.is_director:
        ytd_director_ni_gross_after = (ctx.ytd_director_ni_gross or Decimal("0")) + ctx.gross
        ytd_director_ni_employee_paid_after = (ctx.ytd_director_ni_employee_paid or Decimal("0")) + ni_employee
        ytd_director_ni_employer_paid_after = (ctx.ytd_director_ni_employer_paid or Decimal("0")) + employer_ni

    # Apprenticeship Levy (§14) — banded on the ORG's aggregate annual pay
    # bill, not this employee's own pay; zero and dormant (appr_levy_ytd_pay_bill_after
    # stays None) until the org-level accumulator is wired for this
    # calculation, same "None means not applicable" contract as Ontario
    # EHT (canada.py). calculate_apprenticeship_levy_period_amount itself
    # separately fails closed (returns None) when the rate/allowance
    # aren't configured — treated the same as "not wired" here.
    employer_apprenticeship_levy = Decimal("0")
    appr_levy_ytd_pay_bill_after = None
    if ctx.appr_levy_ytd_pay_bill_before is not None:
        levy_amount = calculate_apprenticeship_levy_period_amount(ctx.gross, ctx.appr_levy_ytd_pay_bill_before, rate_map)
        employer_apprenticeship_levy = levy_amount if levy_amount is not None else Decimal("0")
        appr_levy_ytd_pay_bill_after = ctx.appr_levy_ytd_pay_bill_before + ctx.gross

    # Employment Allowance (§14) — reduces the ORG's CUMULATIVE employer
    # secondary Class 1 NIC liability when remitting to HMRC (claimed via
    # EPS), NOT any individual payslip's own employer_ni figure at all
    # (§14: "Employer eligibility/claim state; reduce eligible secondary
    # Class 1 NIC liability; claim through EPS") — a REPORTING/remittance-
    # level offset, not a payroll deduction. This block only tracks the
    # org's cumulative employer_ni total across every employee (same
    # org-level-accumulator shape as the Levy's pay bill above); the
    # actual net-of-allowance liability is computed separately, on
    # demand, by calculate_employment_allowance_net_liability below —
    # never per payslip, since the allowance is a whole-organization,
    # whole-tax-year concept, not a per-employee one.
    employer_ni_ytd_after = None
    if ctx.employer_ni_ytd_before is not None:
        employer_ni_ytd_after = ctx.employer_ni_ytd_before + employer_ni

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
        ytd_director_ni_gross=ytd_director_ni_gross_after,
        ytd_director_ni_employee_paid=ytd_director_ni_employee_paid_after,
        ytd_director_ni_employer_paid=ytd_director_ni_employer_paid_after,
        employer_apprenticeship_levy=employer_apprenticeship_levy,
        appr_levy_ytd_pay_bill_after=appr_levy_ytd_pay_bill_after,
        employer_ni_ytd_after=employer_ni_ytd_after,
        employer_pension=employer_pension,
        employee_pension=employee_pension,
        study_loan_deduction=study_loan_deduction,
        postgrad_loan_deduction=postgrad_loan_deduction,
        tds=tds, annual_tax=annual_tax,
    )


# ── Statutory Sick Pay — a per-sickness-episode payment, NOT a recurring ──
# payroll deduction. ZP-TAX-UK-2026-27-001 §12: "SSP is not recoverable" —
# unlike SMP/SPP/etc. (§11.1's 92%/109% employer recovery split), so no
# recovery logic belongs here at all. Deliberately a standalone function,
# same architecture as india.py's calculate_gratuity: this needs inputs
# (Average Weekly Earnings, qualifying-day counts, the illness episode's
# OWN start date) that don't exist in PayrollContext and aren't computed
# every recurring payroll cycle for every employee — only for whichever
# employee is actually off sick.

# 6 April 2026 is the real, fixed legal effective date of THIS specific
# reform (day-one entitlement, LEL test removed) — a historical/legal
# fact, not a jurisdiction-variable rate, same footing as the Payment of
# Gratuity Act's own formula constants in india.py.
_UK_SSP_2026_REFORM_DATE = date(2026, 4, 6)


def calculate_ssp(
    illness_start_date: date,
    qualifying_days_in_period: int,
    qualifying_days_per_week: int,
    average_weekly_earnings: Decimal,
    rate_map: dict,
) -> dict:
    """Returns a dict with `eligible` (bool), `reason` (str), and
    `ssp_amount` (Decimal, 0 when not eligible/not computable).

    §12: "the payable weekly amount is the LOWER of £123.25 and 80% of
    the employee's Average Weekly Earnings", allocated across qualifying
    days (§12.1 — the reference table there is just this weekly figure
    divided by qualifying_days_per_week, a pure derivation, not
    independent data requiring its own table).

    Both the weekly cap and the AWE percentage are genuinely statutory
    data HMRC republishes most tax years — no hardcoded fallback: fails
    closed (not a guessed rate) whenever either isn't configured.

    Fails closed for any illness_start_date before the 2026 reform too
    (§12.2: "absences beginning before 6 April 2026 can remain subject to
    transitional rules, including prior LEL/waiting-day treatment") —
    this document gives no figures for the PRIOR rules at all, so
    computing them would mean fabricating a number it never supplied;
    Tax Ops must handle any such pre-reform episode outside this
    function until a source document for the prior rules exists."""
    if illness_start_date < _UK_SSP_2026_REFORM_DATE:
        return {"eligible": False, "reason": "pre-6-April-2026 SSP rules are not implemented — no source figures for the prior LEL/waiting-day rules", "ssp_amount": Decimal("0")}

    weekly_cap_row = rate_map.get("ssp_weekly_cap")
    awe_pct_row = rate_map.get("ssp_awe_pct")
    if not weekly_cap_row or weekly_cap_row.flat_amount is None:
        return {"eligible": False, "reason": "ssp_weekly_cap not configured", "ssp_amount": Decimal("0")}
    if not awe_pct_row or awe_pct_row.employee_rate_pct is None:
        return {"eligible": False, "reason": "ssp_awe_pct not configured", "ssp_amount": Decimal("0")}
    if not qualifying_days_per_week:
        return {"eligible": False, "reason": "qualifying_days_per_week must be > 0", "ssp_amount": Decimal("0")}

    weekly_cap = weekly_cap_row.flat_amount
    awe_based_weekly = average_weekly_earnings * awe_pct_row.employee_rate_pct / Decimal("100")
    weekly_amount = min(weekly_cap, awe_based_weekly)
    daily_rate = weekly_amount / Decimal(qualifying_days_per_week)
    ssp_amount = _round2(daily_rate * Decimal(qualifying_days_in_period))

    return {"eligible": True, "reason": "", "ssp_amount": ssp_amount}


# ── Statutory Family Payments — SMP/SPP/SAP/ShPP/SPBP/SNCP (§11) ─────────
# Same standalone-function architecture as calculate_ssp above: each needs
# its own event inputs (an eligibility determination, AWE, which week of
# the claim this is) that PayrollContext doesn't carry and isn't computed
# every recurring cycle for every employee — only for whoever is actually
# on family leave.
#
# All six payment types share ONE published "Standard Rate for statutory
# family pay" each tax year (§11's own table: every type's steady-state
# row is identically "£194.32 or 90% of AWE, whichever is lower") — this
# is a genuine shared legal fact, not a coincidence being assumed
# permanent (contrast Class 1A/1B's four independently-configured rates
# above, which happen to share 15% this year but are stored separately on
# purpose). One shared rate/percentage pair, `fam_pay_flat_rate`/
# `fam_pay_awe_pct`, covers all six.
#
# SMP and SAP alone have a FIRST-6-WEEKS phase at a flat 90% of AWE with
# no flat-rate cap at all (§11's table: "first 6 weeks: 90% of AWE" has no
# "whichever is lower" clause) — SPP/ShPP/SPBP/SNCP have no such phase,
# every week is the standard capped rate.
_UK_FAMILY_PAY_TYPES = {"SMP", "SPP", "SAP", "SHPP", "SPBP", "SNCP"}
_UK_FAMILY_PAY_UNCAPPED_FIRST_WEEKS = {"SMP", "SAP"}
_UK_FAMILY_PAY_FIRST_WEEKS_COUNT = 6


def calculate_statutory_family_pay(
    payment_type: str,
    week_number: int,
    average_weekly_earnings: Decimal,
    rate_map: dict,
) -> dict:
    """Returns a dict with `eligible` (bool), `reason` (str), and
    `weekly_amount` (Decimal, 0 when not eligible/not computable).
    `payment_type` — one of SMP/SPP/SAP/SHPP/SPBP/SNCP. `week_number` is
    1-indexed within this claim (used only to detect SMP/SAP's first-6-
    weeks phase). No hardcoded fallback for the rate or the AWE
    percentage — fails closed whenever either isn't configured."""
    if payment_type not in _UK_FAMILY_PAY_TYPES:
        return {"eligible": False, "reason": f"unknown payment_type {payment_type!r}", "weekly_amount": Decimal("0")}

    awe_pct_row = rate_map.get("fam_pay_awe_pct")
    if not awe_pct_row or awe_pct_row.employee_rate_pct is None:
        return {"eligible": False, "reason": "fam_pay_awe_pct not configured", "weekly_amount": Decimal("0")}
    awe_based_weekly = average_weekly_earnings * awe_pct_row.employee_rate_pct / Decimal("100")

    if payment_type in _UK_FAMILY_PAY_UNCAPPED_FIRST_WEEKS and week_number <= _UK_FAMILY_PAY_FIRST_WEEKS_COUNT:
        return {"eligible": True, "reason": "", "weekly_amount": _round2(awe_based_weekly)}

    flat_rate_row = rate_map.get("fam_pay_flat_rate")
    if not flat_rate_row or flat_rate_row.flat_amount is None:
        return {"eligible": False, "reason": "fam_pay_flat_rate not configured", "weekly_amount": Decimal("0")}
    weekly_amount = min(flat_rate_row.flat_amount, awe_based_weekly)
    return {"eligible": True, "reason": "", "weekly_amount": _round2(weekly_amount)}


def calculate_family_pay_employer_recovery(
    prior_year_total_class1_nic: Decimal,
    payment_amount: Decimal,
    rate_map: dict,
) -> dict:
    """Returns a dict with `eligible` (bool), `reason` (str), and
    `recovery_amount` (Decimal). §11.1: employer recovers 92% of what
    they paid out, or 109% if their prior-year total Class 1 NIC was
    £45,000 or lower (the "small employer" relief). SSP is explicitly
    EXCLUDED from this — §11.1/AC-20 — never call this for an SSP
    payment; there is no recovery function for SSP at all in this file.
    No hardcoded fallback — fails closed whenever the threshold or either
    rate isn't configured."""
    threshold_row = rate_map.get("fam_pay_recov_thresh")
    small_rate_row = rate_map.get("fam_pay_recov_small")
    standard_rate_row = rate_map.get("fam_pay_recov_std")
    if not threshold_row or threshold_row.flat_amount is None:
        return {"eligible": False, "reason": "fam_pay_recov_thresh not configured", "recovery_amount": Decimal("0")}
    if not small_rate_row or small_rate_row.employer_rate_pct is None:
        return {"eligible": False, "reason": "fam_pay_recov_small not configured", "recovery_amount": Decimal("0")}
    if not standard_rate_row or standard_rate_row.employer_rate_pct is None:
        return {"eligible": False, "reason": "fam_pay_recov_std not configured", "recovery_amount": Decimal("0")}

    rate = small_rate_row.employer_rate_pct if prior_year_total_class1_nic <= threshold_row.flat_amount else standard_rate_row.employer_rate_pct
    return {"eligible": True, "reason": "", "recovery_amount": _round2(payment_amount * rate / Decimal("100"))}


# ── Class 1A / Class 1B — employer-only, event/annual charges, NOT a ────
# recurring payroll deduction. §9.3: benefits/termination awards/sporting
# testimonials (Class 1A) and PAYE Settlement Agreement items (Class 1B)
# each need their own event VALUE as input (a P11D benefit valuation, a
# termination package amount, a testimonial committee payment, a PSA
# item) — none of which this engine tracks per payslip, same standalone-
# function architecture as calculate_gratuity/calculate_ssp above.
#
# componentKey max 20 chars (payroll_contribution_rates.component_key is
# VARCHAR(20)) — "class1a_benefits_rate" etc. all exceed it, hence the
# shortened "c1a_*"/"c1b_*" keys below.
#
# All four charge types happen to share the same 15% rate this document
# gives (§9.3's own table lists them as 4 separate line items even
# though the number coincides) — configured as 4 INDEPENDENT rates
# rather than one shared one, same principle as this document's own
# "Preserve the C prefix" instruction for Welsh PAYE (§5.4): a coincidence
# this year is not a reason to assume they'll always move together.
_UK_CLASS_1A_1B_CHARGE_TYPES = {
    "BENEFITS": ("c1a_benefits_rate", None),
    "TERMINATION_AWARDS": ("c1a_term_rate", "c1a_term_thresh"),
    "SPORTING_TESTIMONIAL": ("c1a_testim_rate", "c1a_testim_thresh"),
    "PSA": ("c1b_psa_rate", None),
}


def calculate_class_1a_1b_charge(charge_type: str, amount: Decimal, rate_map: dict) -> dict:
    """Returns a dict with `eligible` (bool), `reason` (str), and
    `charge_amount` (Decimal, 0 when not eligible/not computable).
    `charge_type` — one of BENEFITS/TERMINATION_AWARDS/
    SPORTING_TESTIMONIAL/PSA. TERMINATION_AWARDS and
    SPORTING_TESTIMONIAL charge only the EXCESS above their own
    threshold (§9.3: "above £30,000"/"above £100,000"); BENEFITS and PSA
    charge the full amount, since the document gives no threshold for
    either. No hardcoded fallback for the rate or either threshold —
    fails closed (not a guess) whenever the relevant one isn't
    configured."""
    if charge_type not in _UK_CLASS_1A_1B_CHARGE_TYPES:
        return {"eligible": False, "reason": f"unknown charge_type {charge_type!r}", "charge_amount": Decimal("0")}
    rate_key, threshold_key = _UK_CLASS_1A_1B_CHARGE_TYPES[charge_type]
    rate_row = rate_map.get(rate_key)
    if not rate_row or rate_row.employer_rate_pct is None:
        return {"eligible": False, "reason": f"{rate_key} not configured", "charge_amount": Decimal("0")}

    threshold = Decimal("0")
    if threshold_key:
        threshold_row = rate_map.get(threshold_key)
        if not threshold_row or threshold_row.flat_amount is None:
            return {"eligible": False, "reason": f"{threshold_key} not configured", "charge_amount": Decimal("0")}
        threshold = threshold_row.flat_amount

    chargeable = max(Decimal("0"), amount - threshold)
    charge_amount = _round2(chargeable * rate_row.employer_rate_pct / Decimal("100"))
    return {"eligible": True, "reason": "", "charge_amount": charge_amount}


# ── Apprenticeship Levy — banded on the ORGANIZATION's aggregate annual ──
# statutory pay bill, NOT any single employee's own pay (§14: "Cumulative
# charge on statutory pay bill"). Same org-level-accumulator-banded shape
# and cumulative-period-telescoping technique as Canada's Ontario/BC EHT
# (canada.py's _calculate_on_eht_period_amount) — computed as
# annual_levy(cumulative_after) − annual_levy(cumulative_before) so the
# correct annual total accrues exactly once regardless of how many pay
# periods occur or when the allowance is exhausted mid-year. Genuinely
# new statutory data, no hardcoded fallback: an unconfigured rate or
# allowance resolves to "not computable" (returns None, the caller's own
# signal to treat this period's levy as 0 — the levy calculation service.py
# wiring is a separate follow-up, same as this session's other
# standalone-first infrastructure).
def _annual_apprenticeship_levy_amount(total_pay_bill: Decimal, rate: Decimal, allowance: Decimal) -> Decimal:
    gross_levy = total_pay_bill * rate / Decimal("100")
    return max(Decimal("0"), gross_levy - allowance)


def calculate_apprenticeship_levy_period_amount(gross: Decimal, org_ytd_pay_bill_before: Decimal, rate_map: dict) -> Decimal | None:
    """Returns this period's levy charge, or None when
    "appr_levy_rate"/"appr_levy_allowance" aren't configured (fails
    closed rather than guessing 0.5%/£15,000 — this document's own
    figures, but still genuinely statutory data subject to change, same
    footing as every other UK rate/threshold in this file)."""
    rate_row = rate_map.get("appr_levy_rate")
    allowance_row = rate_map.get("appr_levy_allowance")
    if not rate_row or rate_row.employer_rate_pct is None:
        return None
    if not allowance_row or allowance_row.flat_amount is None:
        return None
    rate = rate_row.employer_rate_pct
    allowance = allowance_row.flat_amount
    return telescope_period_amount(
        gross, org_ytd_pay_bill_before,
        lambda total: _annual_apprenticeship_levy_amount(total, rate, allowance),
    )


# ── Employment Allowance — a REPORTING/remittance-level offset, NOT a ───
# per-payslip calculation at all (§14: "Employer eligibility/claim state;
# reduce eligible secondary Class 1 NIC liability; claim through EPS").
# It never changes any individual employee's own employer_ni figure —
# only how much of the ORG's cumulative employer NI bill actually gets
# remitted to HMRC. Deliberately a standalone function, called on demand
# (e.g. by a future EPS/remittance report) against the org's cumulative
# employer_ni_ytd_after accumulator (calculate()'s own tracking above) —
# never wired into calculate()'s per-payslip return dict, since there is
# no per-payslip number for it to produce.
#
# "Employer eligibility/claim state" (§14) is deliberately NOT modeled
# here as an eligibility RULE (e.g. excluded sectors/company sizes) — the
# document names the concept but gives no criteria, so this only reads
# whether the employer has actually CLAIMED it (a plain boolean fact,
# not a computed eligibility test) rather than guessing who qualifies.
def calculate_employment_allowance_net_liability(cumulative_employer_ni: Decimal, employer_has_claimed: bool, rate_map: dict) -> dict:
    """Returns a dict with `eligible` (bool), `reason` (str),
    `net_liability` (Decimal — what the org actually owes HMRC after the
    allowance), and `allowance_remaining` (Decimal). No hardcoded
    fallback for the allowance cap — fails closed when unconfigured."""
    if not employer_has_claimed:
        return {"eligible": False, "reason": "employer has not claimed Employment Allowance", "net_liability": cumulative_employer_ni, "allowance_remaining": Decimal("0")}
    allowance_row = rate_map.get("empl_allowance_cap")
    if not allowance_row or allowance_row.flat_amount is None:
        return {"eligible": False, "reason": "empl_allowance_cap not configured", "net_liability": cumulative_employer_ni, "allowance_remaining": Decimal("0")}
    allowance_cap = allowance_row.flat_amount
    net_liability = max(Decimal("0"), cumulative_employer_ni - allowance_cap)
    allowance_remaining = max(Decimal("0"), allowance_cap - cumulative_employer_ni)
    return {"eligible": True, "reason": "", "net_liability": _round2(net_liability), "allowance_remaining": _round2(allowance_remaining)}
