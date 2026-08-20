"""
modules/payroll/engine/countries/uk.py
-----------------------------------------
UK: National Insurance + Employer Pension + PAYE. Moved verbatim out of
engine/standard.py's _calc_uk.
"""

from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import MONTHS_PER_YEAR, _calculate_annual_tax, resolve_jurisdiction_parameter

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
# Student/Postgraduate Loan — real UK mechanism, two worked examples
# (Plan 2, the most common undergraduate plan, and the Postgraduate
# Loan) rather than every plan variant. Any other/unset study_loan_plan
# value deducts 0, same as having no loan at all.
_UK_STUDENT_LOAN_PLANS = {
    "UK_PLAN1": (Decimal("24990"), Decimal("9")),
    "UK_PLAN2": (Decimal("27295"), Decimal("9")),
    "UK_PLAN4": (Decimal("31395"), Decimal("9")),
    "UK_POSTGRAD": (Decimal("21000"), Decimal("6")),
}


def _calculate_annual_tax_uk(annual_gross: Decimal, slabs, rate_map: dict) -> Decimal:
    pa = resolve_jurisdiction_parameter(rate_map, "personal_allowance", _UK_PERSONAL_ALLOWANCE, country="UK")
    taper_threshold = resolve_jurisdiction_parameter(rate_map, "pa_taper_threshold", _UK_PA_TAPER_THRESHOLD, country="UK")
    if annual_gross > taper_threshold:
        taper = (annual_gross - taper_threshold) / Decimal("2")
        pa = max(Decimal("0"), pa - taper)
    taxable = max(Decimal("0"), annual_gross - pa)
    return _calculate_annual_tax(taxable, slabs)


def calculate(ctx: PayrollContext) -> dict:
    """UK: Employee + Employer National Insurance + Employer Pension +
    PAYE (Scotland's own bands where configured) + Student/Postgraduate
    Loan.

    NI rates/thresholds and the employer pension rate come from
    rate_map's "national-insurance"/"employer-pension" ContributionRate
    rows rather than being ignored in favour of hardcoded module
    constants."""
    rate_map = ctx.rate_map
    annual_gross = ctx.gross * MONTHS_PER_YEAR

    ni_primary_threshold = resolve_jurisdiction_parameter(rate_map, "ni_primary_thresh", _UK_NI_PRIMARY_THRESHOLD, country="UK")
    ni_upper_threshold = resolve_jurisdiction_parameter(rate_map, "ni_upper_threshold", _UK_NI_UPPER_THRESHOLD, country="UK")
    ni_primary_rate = resolve_jurisdiction_parameter(rate_map, "national-insurance", _UK_NI_PRIMARY_RATE, side="employee", country="UK")
    ni_upper_rate = resolve_jurisdiction_parameter(rate_map, "ni_upper_rate", _UK_NI_UPPER_RATE, side="employee", country="UK")

    ni_basicable = max(Decimal("0"), min(annual_gross, ni_upper_threshold) - ni_primary_threshold)
    ni_upperable = max(Decimal("0"), annual_gross - ni_upper_threshold)
    ni_employee_annual = (ni_basicable * ni_primary_rate / Decimal("100")) + (ni_upperable * ni_upper_rate / Decimal("100"))
    ni_employee = _round2(ni_employee_annual / MONTHS_PER_YEAR)

    ni_secondary_threshold = resolve_jurisdiction_parameter(rate_map, "ni_secondary_thresh", _UK_NI_SECONDARY_THRESHOLD, country="UK")
    ni_employer_rate = resolve_jurisdiction_parameter(rate_map, "national-insurance", _UK_NI_EMPLOYER_RATE, side="employer", country="UK")
    ni_employer_annual = max(Decimal("0"), annual_gross - ni_secondary_threshold) * ni_employer_rate / Decimal("100")
    employer_ni = _round2(ni_employer_annual / MONTHS_PER_YEAR)

    pension_rate = resolve_jurisdiction_parameter(rate_map, "employer-pension", _UK_PENSION_MIN_ENPLOYER, side="employer", country="UK")
    employer_pension = _round2(annual_gross * pension_rate / Decimal("100") / MONTHS_PER_YEAR)

    # Scotland sets its own income tax bands (Starter/Basic/Intermediate/
    # Higher/Top) — England/Wales/Northern Ireland share the national
    # slabs. Only used when a real Scotland-scoped TaxSlab set has been
    # configured (ctx.state_slabs); otherwise falls back to the national
    # bands exactly as before this existed.
    slabs_for_tax = ctx.state_slabs if (ctx.work_state == "Scotland" and ctx.state_slabs) else ctx.slabs
    annual_tax = _calculate_annual_tax_uk(annual_gross, slabs_for_tax, rate_map)
    tds = _round2(annual_tax / MONTHS_PER_YEAR)

    # Deducted whenever an outstanding balance exists, at the plan's
    # threshold/rate — NOT capped by the balance itself: real Student
    # Loan repayment reduces the balance over time via cumulative YTD
    # tracking, which this engine doesn't yet do (see the plan's explicit
    # YTD-calculation deferral). study_loan_balance > 0 is only used as
    # "does this employee currently have a loan to repay," not as a
    # per-payslip cap.
    study_loan_deduction = Decimal("0")
    plan = _UK_STUDENT_LOAN_PLANS.get(ctx.study_loan_plan)
    if plan and ctx.study_loan_balance and ctx.study_loan_balance > 0:
        threshold, rate = plan
        annual_repayment = max(Decimal("0"), annual_gross - threshold) * rate / Decimal("100")
        study_loan_deduction = _round2(annual_repayment / MONTHS_PER_YEAR)

    return dict(
        ni_employee=ni_employee,
        employer_ni=employer_ni,
        employer_pension=employer_pension,
        study_loan_deduction=study_loan_deduction,
        tds=tds, annual_tax=annual_tax,
    )
