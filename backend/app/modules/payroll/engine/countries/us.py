"""
modules/payroll/engine/countries/us.py
-----------------------------------------
US: Social Security + Medicare + Federal Income Tax. Moved verbatim out
of engine/standard.py's _calc_us.
"""

from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import MONTHS_PER_YEAR, _calculate_annual_tax, _param_amount, _param_pct

_US_STANDARD_DEDUCTION = Decimal("15000")
_US_SOCIAL_SECURITY_WAGE_BASE = Decimal("176100")
_US_SOCIAL_SECURITY_RATE = Decimal("6.2")
_US_MEDICARE_RATE = Decimal("1.45")
_US_MEDICARE_ADDITIONAL_RATE = Decimal("0.9")
# Previously inlined at its one call site — named so it can be sourced
# from rate_map like every other parameter here.
_US_MEDICARE_ADDITIONAL_THRESHOLD = Decimal("200000")


def _calculate_annual_tax_us(annual_gross: Decimal, slabs, rate_map: dict) -> Decimal:
    standard_deduction = _param_amount(rate_map, "standard_deduction", _US_STANDARD_DEDUCTION)
    taxable = max(Decimal("0"), annual_gross - standard_deduction)
    return _calculate_annual_tax(taxable, slabs)


def calculate(ctx: PayrollContext) -> dict:
    """US: Social Security + Medicare + Federal Income Tax.

    Employee/employer Social Security and Medicare rates come from
    rate_map's "social-security"/"medicare" ContributionRate rows rather
    than being ignored in favour of a hardcoded module constant — editing
    these rates via Compliance has a real calculation effect."""
    rate_map = ctx.rate_map
    annual_gross = ctx.gross * MONTHS_PER_YEAR

    ss_rate_employee = _param_pct(rate_map, "social-security", "employee", _US_SOCIAL_SECURITY_RATE)
    ss_rate_employer = _param_pct(rate_map, "social-security", "employer", _US_SOCIAL_SECURITY_RATE)
    ss_wage_base = _param_amount(rate_map, "ss_wage_base", _US_SOCIAL_SECURITY_WAGE_BASE)
    annual_ss_wage = min(annual_gross, ss_wage_base)
    social_security = _round2((annual_ss_wage * ss_rate_employee / Decimal("100")) / MONTHS_PER_YEAR)
    employer_ss = _round2((annual_ss_wage * ss_rate_employer / Decimal("100")) / MONTHS_PER_YEAR)

    medicare_rate_employee = _param_pct(rate_map, "medicare", "employee", _US_MEDICARE_RATE)
    medicare_rate_employer = _param_pct(rate_map, "medicare", "employer", _US_MEDICARE_RATE)
    medicare_additional_rate = _param_pct(rate_map, "medicare_additional", "employee", _US_MEDICARE_ADDITIONAL_RATE)
    medicare_additional_threshold = _param_amount(rate_map, "medicare_addl_thresh", _US_MEDICARE_ADDITIONAL_THRESHOLD)

    medicare = _round2((annual_gross * medicare_rate_employee / Decimal("100")) / MONTHS_PER_YEAR)
    if annual_gross > medicare_additional_threshold:
        medicare += _round2(((annual_gross - medicare_additional_threshold) * medicare_additional_rate / Decimal("100")) / MONTHS_PER_YEAR)
    employer_medicare = _round2((annual_gross * medicare_rate_employer / Decimal("100")) / MONTHS_PER_YEAR)

    annual_tax = _calculate_annual_tax_us(annual_gross, ctx.slabs, rate_map)
    tds = _round2(annual_tax / MONTHS_PER_YEAR)

    return dict(
        social_security=social_security, employer_social_security=employer_ss,
        medicare=medicare, employer_medicare=employer_medicare,
        tds=tds, annual_tax=annual_tax,
    )
