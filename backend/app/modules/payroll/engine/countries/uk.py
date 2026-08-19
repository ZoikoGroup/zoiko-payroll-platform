"""
modules/payroll/engine/countries/uk.py
-----------------------------------------
UK: National Insurance + Employer Pension + PAYE. Moved verbatim out of
engine/standard.py's _calc_uk.
"""

from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import MONTHS_PER_YEAR, _calculate_annual_tax, _param_amount, _param_pct

_UK_PERSONAL_ALLOWANCE = Decimal("12570")
_UK_PA_TAPER_THRESHOLD = Decimal("100000")
_UK_NI_PRIMARY_THRESHOLD = Decimal("12570")
_UK_NI_UPPER_THRESHOLD = Decimal("50270")
_UK_NI_PRIMARY_RATE = Decimal("8")
_UK_NI_UPPER_RATE = Decimal("2")
_UK_PENSION_MIN_ENPLOYER = Decimal("3")


def _calculate_annual_tax_uk(annual_gross: Decimal, slabs, rate_map: dict) -> Decimal:
    pa = _param_amount(rate_map, "personal_allowance", _UK_PERSONAL_ALLOWANCE)
    taper_threshold = _param_amount(rate_map, "pa_taper_threshold", _UK_PA_TAPER_THRESHOLD)
    if annual_gross > taper_threshold:
        taper = (annual_gross - taper_threshold) / Decimal("2")
        pa = max(Decimal("0"), pa - taper)
    taxable = max(Decimal("0"), annual_gross - pa)
    return _calculate_annual_tax(taxable, slabs)


def calculate(ctx: PayrollContext) -> dict:
    """UK: National Insurance + Employer Pension + PAYE.

    NI rates/thresholds and the employer pension rate come from
    rate_map's "national-insurance"/"employer-pension" ContributionRate
    rows rather than being ignored in favour of hardcoded module
    constants."""
    rate_map = ctx.rate_map
    annual_gross = ctx.gross * MONTHS_PER_YEAR

    ni_primary_threshold = _param_amount(rate_map, "ni_primary_thresh", _UK_NI_PRIMARY_THRESHOLD)
    ni_upper_threshold = _param_amount(rate_map, "ni_upper_threshold", _UK_NI_UPPER_THRESHOLD)
    ni_primary_rate = _param_pct(rate_map, "national-insurance", "employee", _UK_NI_PRIMARY_RATE)
    ni_upper_rate = _param_pct(rate_map, "ni_upper_rate", "employee", _UK_NI_UPPER_RATE)

    ni_basicable = max(Decimal("0"), min(annual_gross, ni_upper_threshold) - ni_primary_threshold)
    ni_upperable = max(Decimal("0"), annual_gross - ni_upper_threshold)
    ni_employee_annual = (ni_basicable * ni_primary_rate / Decimal("100")) + (ni_upperable * ni_upper_rate / Decimal("100"))
    ni_employee = _round2(ni_employee_annual / MONTHS_PER_YEAR)

    pension_rate = _param_pct(rate_map, "employer-pension", "employer", _UK_PENSION_MIN_ENPLOYER)
    employer_pension = _round2(annual_gross * pension_rate / Decimal("100") / MONTHS_PER_YEAR)

    annual_tax = _calculate_annual_tax_uk(annual_gross, ctx.slabs, rate_map)
    tds = _round2(annual_tax / MONTHS_PER_YEAR)

    return dict(
        ni_employee=ni_employee,
        employer_pension=employer_pension,
        tds=tds, annual_tax=annual_tax,
    )
