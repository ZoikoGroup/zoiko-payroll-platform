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

from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import (
    _calculate_annual_tax, resolve_jurisdiction_parameter,
    _param_text, resolve_periods_per_year,
)

_UK_PERSONAL_ALLOWANCE = Decimal("12570")
_UK_PA_TAPER_THRESHOLD = Decimal("100000")
_UK_NI_PRIMARY_THRESHOLD = Decimal("12570")
_UK_NI_UPPER_THRESHOLD = Decimal("50270")
_UK_NI_PRIMARY_RATE = Decimal("8")
_UK_NI_UPPER_RATE = Decimal("2")
_UK_PENSION_MIN_ENPLOYER = Decimal("3")
# Employer NI — genuinely absent until now (only employee NI was ever
# modeled). Secondary Threshold + standard employer rate.
_UK_NI_SECONDARY_THRESHOLD = Decimal("9100")
_UK_NI_EMPLOYER_RATE = Decimal("13.8")
# Real 2025/26 Qualifying Earnings band for Workplace Pension auto-enrolment.
_UK_PENSION_QE_LOWER = Decimal("6240")
_UK_PENSION_QE_UPPER = Decimal("50270")
# Student/Postgraduate Loan — real UK mechanism. Plan 5 covers post-2023
# starters (in effect from April 2026). Any other/unset study_loan_plan
# value deducts 0, same as having no loan at all.
_UK_STUDENT_LOAN_PLANS = {
    "UK_PLAN1": (Decimal("24990"), Decimal("9")),
    "UK_PLAN2": (Decimal("27295"), Decimal("9")),
    "UK_PLAN4": (Decimal("31395"), Decimal("9")),
    "UK_PLAN5": (Decimal("25000"), Decimal("9")),
    "UK_POSTGRAD": (Decimal("21000"), Decimal("6")),
}
# Threshold-only override keys for the plans exposed in the Compliance UI's
# Statutory Thresholds tab. Kept to <=20 chars — ContributionRate.component_key
# is varchar(20).
_UK_STUDENT_LOAN_PARAM_KEYS = {
    "UK_PLAN1": "sl_plan1_thresh",
    "UK_PLAN2": "sl_plan2_thresh",
    "UK_PLAN4": "sl_plan4_thresh",
    "UK_PLAN5": "sl_plan5_thresh",
    "UK_POSTGRAD": "pg_loan_thresh",
}


# ── PAYE tax-code interpretation ────────────────────────────────────────
# Handles standard codes ("1257L" -> allowance = digits x 10), K-codes
# (negative allowance -- untaxed benefit added to income, never tapered),
# and the flat-rate override codes BR/D0/D1/NT. Deliberately NOT
# implementing true cumulative (Week1/Month1 vs cumulative YTD) PAYE basis
# -- that requires year-to-date income tracking this engine doesn't have
# for ANY country yet (same explicit deferral already on record for
# Student Loan balance tracking, below). `basis` is recorded on the
# result but every calculation stays period-by-period, as today.
def interpret_tax_code(tax_code: str | None, default_personal_allowance: Decimal) -> dict:
    if not tax_code:
        return {"personal_allowance": default_personal_allowance, "flat_rate_pct": None, "basis": "CUMULATIVE"}
    code = tax_code.upper().strip()
    if code == "BR":
        return {"personal_allowance": Decimal("0"), "flat_rate_pct": Decimal("20"), "basis": "NONCUMULATIVE"}
    if code == "D0":
        return {"personal_allowance": Decimal("0"), "flat_rate_pct": Decimal("40"), "basis": "NONCUMULATIVE"}
    if code == "D1":
        return {"personal_allowance": Decimal("0"), "flat_rate_pct": Decimal("45"), "basis": "NONCUMULATIVE"}
    if code == "NT":
        return {"personal_allowance": None, "flat_rate_pct": Decimal("0"), "basis": "NONCUMULATIVE"}
    if code.startswith("K") and code[1:].isdigit():
        return {"personal_allowance": -(Decimal(code[1:]) * 10), "flat_rate_pct": None, "basis": "CUMULATIVE"}
    digits = "".join(ch for ch in code if ch.isdigit())
    if digits:
        return {"personal_allowance": Decimal(digits) * 10, "flat_rate_pct": None, "basis": "CUMULATIVE"}
    return {"personal_allowance": default_personal_allowance, "flat_rate_pct": None, "basis": "CUMULATIVE"}


def _calculate_annual_tax_uk(annual_gross: Decimal, slabs, rate_map: dict, tax_code: str | None = None) -> Decimal:
    default_pa = resolve_jurisdiction_parameter(rate_map, "personal_allowance", _UK_PERSONAL_ALLOWANCE, country="UK")
    interpreted = interpret_tax_code(tax_code, default_pa)
    if interpreted["flat_rate_pct"] is not None:
        # BR/D0/D1 (flat rate on full income, no allowance) or NT (0%, no tax at all).
        return annual_gross * interpreted["flat_rate_pct"] / Decimal("100")

    pa = interpreted["personal_allowance"]
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
    real the moment rows exist for it, no engine change required."""
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

    # Deducted whenever an outstanding balance exists, at the plan's
    # threshold/rate — NOT capped by the balance itself: real Student
    # Loan repayment reduces the balance over time via cumulative YTD
    # tracking, which this engine doesn't yet do. study_loan_balance > 0
    # is only used as "does this employee currently have a loan to
    # repay," not as a per-payslip cap.
    study_loan_deduction = Decimal("0")
    plan = _UK_STUDENT_LOAN_PLANS.get(ctx.study_loan_plan)
    if plan and ctx.study_loan_balance and ctx.study_loan_balance > 0:
        default_threshold, rate = plan
        param_key = _UK_STUDENT_LOAN_PARAM_KEYS.get(ctx.study_loan_plan)
        threshold = (
            resolve_jurisdiction_parameter(rate_map, param_key, default_threshold, country="UK")
            if param_key else default_threshold
        )
        annual_repayment = max(Decimal("0"), annual_gross - threshold) * rate / Decimal("100")
        study_loan_deduction = _round2(annual_repayment / periods_per_year)

    return dict(
        ni_employee=ni_employee,
        employer_ni=employer_ni,
        employer_pension=employer_pension,
        employee_pension=employee_pension,
        study_loan_deduction=study_loan_deduction,
        tds=tds, annual_tax=annual_tax,
    )
