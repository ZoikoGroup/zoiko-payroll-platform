"""
modules/payroll/engine/countries/us.py
-----------------------------------------
US: Social Security + Medicare + Federal Income Tax. Moved verbatim out
of engine/standard.py's _calc_us.
"""

from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import MONTHS_PER_YEAR, _calculate_annual_tax, resolve_jurisdiction_parameter

_US_STANDARD_DEDUCTION = Decimal("15000")
_US_SOCIAL_SECURITY_WAGE_BASE = Decimal("176100")
_US_SOCIAL_SECURITY_RATE = Decimal("6.2")
_US_MEDICARE_RATE = Decimal("1.45")
_US_MEDICARE_ADDITIONAL_RATE = Decimal("0.9")
# Previously inlined at its one call site — named so it can be sourced
# from rate_map like every other parameter here.
_US_MEDICARE_ADDITIONAL_THRESHOLD = Decimal("200000")
# FUTA has been seeded as a display-only ContributionRate row ("futa")
# since day one but was never actually read anywhere until now. Real
# FUTA is 6.0% on the first $7,000 of annual wages per employee (before
# the standard state-unemployment-tax credit, which this engine does not
# model) — employer-only, no employee side.
_US_FUTA_RATE = Decimal("6.0")
_US_FUTA_WAGE_BASE = Decimal("7000")


def _calculate_annual_tax_us(annual_gross: Decimal, slabs, rate_map: dict) -> Decimal:
    standard_deduction = resolve_jurisdiction_parameter(rate_map, "standard_deduction", _US_STANDARD_DEDUCTION, country="US")
    taxable = max(Decimal("0"), annual_gross - standard_deduction)
    return _calculate_annual_tax(taxable, slabs)


def calculate(ctx: PayrollContext) -> dict:
    """US: Social Security + Medicare + Federal Income Tax + FUTA +
    (where a state-scoped TaxSlab set exists) State Income Tax.

    Employee/employer Social Security and Medicare rates come from
    rate_map's "social-security"/"medicare" ContributionRate rows rather
    than being ignored in favour of a hardcoded module constant — editing
    these rates via Compliance has a real calculation effect."""
    rate_map = ctx.rate_map
    annual_gross = ctx.gross * MONTHS_PER_YEAR

    ss_rate_employee = resolve_jurisdiction_parameter(rate_map, "social-security", _US_SOCIAL_SECURITY_RATE, side="employee", country="US")
    ss_rate_employer = resolve_jurisdiction_parameter(rate_map, "social-security", _US_SOCIAL_SECURITY_RATE, side="employer", country="US")
    ss_wage_base = resolve_jurisdiction_parameter(rate_map, "ss_wage_base", _US_SOCIAL_SECURITY_WAGE_BASE, country="US")
    annual_ss_wage = min(annual_gross, ss_wage_base)
    social_security = _round2((annual_ss_wage * ss_rate_employee / Decimal("100")) / MONTHS_PER_YEAR)
    employer_ss = _round2((annual_ss_wage * ss_rate_employer / Decimal("100")) / MONTHS_PER_YEAR)

    medicare_rate_employee = resolve_jurisdiction_parameter(rate_map, "medicare", _US_MEDICARE_RATE, side="employee", country="US")
    medicare_rate_employer = resolve_jurisdiction_parameter(rate_map, "medicare", _US_MEDICARE_RATE, side="employer", country="US")
    medicare_additional_rate = resolve_jurisdiction_parameter(rate_map, "medicare_additional", _US_MEDICARE_ADDITIONAL_RATE, side="employee", country="US")
    medicare_additional_threshold = resolve_jurisdiction_parameter(rate_map, "medicare_addl_thresh", _US_MEDICARE_ADDITIONAL_THRESHOLD, country="US")

    medicare = _round2((annual_gross * medicare_rate_employee / Decimal("100")) / MONTHS_PER_YEAR)
    if annual_gross > medicare_additional_threshold:
        medicare += _round2(((annual_gross - medicare_additional_threshold) * medicare_additional_rate / Decimal("100")) / MONTHS_PER_YEAR)
    employer_medicare = _round2((annual_gross * medicare_rate_employer / Decimal("100")) / MONTHS_PER_YEAR)

    futa_rate = resolve_jurisdiction_parameter(rate_map, "futa", _US_FUTA_RATE, side="employer", country="US")
    futa_wage_base = resolve_jurisdiction_parameter(rate_map, "futa_wage_base", _US_FUTA_WAGE_BASE, country="US")
    annual_futa_wage = min(annual_gross, futa_wage_base)
    employer_futa = _round2((annual_futa_wage * futa_rate / Decimal("100")) / MONTHS_PER_YEAR)

    # State income tax: ctx.state_slabs is only ever non-empty when the
    # employee's work_state resolved a real state-scoped TaxSlab set
    # (California, New York) — states with no income tax (Texas, Florida)
    # or with no configured slabs correctly resolve to 0 here, never a
    # guess. Federal slabs (ctx.slabs) are never reused as a stand-in.
    state_slabs = ctx.state_slabs or []
    annual_state_tax = _calculate_annual_tax(annual_gross, state_slabs) if state_slabs else Decimal("0")
    state_income_tax = _round2(annual_state_tax / MONTHS_PER_YEAR)

    annual_tax = _calculate_annual_tax_us(annual_gross, ctx.slabs, rate_map)
    tds = _round2(annual_tax / MONTHS_PER_YEAR) + state_income_tax

    return dict(
        social_security=social_security, employer_social_security=employer_ss,
        medicare=medicare, employer_medicare=employer_medicare,
        employer_futa=employer_futa,
        tds=tds, annual_tax=annual_tax,
    )
