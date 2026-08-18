"""
modules/payroll/engine/countries/india.py
--------------------------------------------
India: PF, ESI, Professional Tax, TDS. Moved verbatim out of
engine/standard.py's _calc_india — see that module's docstring for the
backward-compatibility contract this preserves.
"""

from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import MONTHS_PER_YEAR, _calculate_annual_tax, _param_amount, _param_pct

ESI_MONTHLY_WAGE_CEILING = Decimal("21000")
_IN_STANDARD_DEDUCTION = Decimal("75000")
_IN_REBATE_87A_LIMIT = Decimal("1200000")
_IN_REBATE_87A_MAX = Decimal("60000")


def _apply_section_87a_rebate(annual_tax: Decimal, taxable_income: Decimal, rate_map: dict) -> Decimal:
    rebate_limit = _param_amount(rate_map, "rebate_87a_limit", _IN_REBATE_87A_LIMIT)
    rebate_max = _param_amount(rate_map, "rebate_87a_max", _IN_REBATE_87A_MAX)
    if taxable_income <= rebate_limit:
        rebate = min(annual_tax, rebate_max)
        return annual_tax - rebate
    tax_on_threshold = rebate_max
    if annual_tax > tax_on_threshold:
        excess_income = taxable_income - rebate_limit
        excess_tax = annual_tax - tax_on_threshold
        if excess_tax <= excess_income:
            return tax_on_threshold + excess_tax
        return annual_tax
    return annual_tax


def _calculate_annual_tax_in(annual_gross: Decimal, slabs, rate_map: dict) -> Decimal:
    standard_deduction = _param_amount(rate_map, "standard_deduction", _IN_STANDARD_DEDUCTION)
    taxable = max(Decimal("0"), annual_gross - standard_deduction)
    tax = _calculate_annual_tax(taxable, slabs)
    tax = _apply_section_87a_rebate(tax, taxable, rate_map)
    return max(Decimal("0"), tax)


def calculate(ctx: PayrollContext) -> dict:
    """India: PF, ESI, Professional Tax, TDS."""
    rate_map = ctx.rate_map
    gross = ctx.gross
    basic = ctx.basic

    pf_rate = rate_map.get("pf")
    employee_pf = _round2(basic * (pf_rate.employee_rate_pct / 100)) if pf_rate and pf_rate.employee_rate_pct else Decimal("0")
    employer_pf = _round2(basic * (pf_rate.employer_rate_pct / 100)) if pf_rate and pf_rate.employer_rate_pct else Decimal("0")

    esi_rate = rate_map.get("esi")
    esi_ceiling = _param_amount(rate_map, "esi_wage_ceiling", ESI_MONTHLY_WAGE_CEILING)
    esi_applicable = gross <= esi_ceiling
    employee_esi = _round2(gross * (esi_rate.employee_rate_pct / 100)) if esi_rate and esi_rate.employee_rate_pct and esi_applicable else Decimal("0")
    employer_esi = _round2(gross * (esi_rate.employer_rate_pct / 100)) if esi_rate and esi_rate.employer_rate_pct and esi_applicable else Decimal("0")

    pt_rate = rate_map.get("pt")
    professional_tax = pt_rate.flat_amount if pt_rate and pt_rate.flat_amount else Decimal("0")

    annual_gross = gross * MONTHS_PER_YEAR
    annual_tax = _calculate_annual_tax_in(annual_gross, ctx.slabs, rate_map)
    tds = _round2(annual_tax / MONTHS_PER_YEAR)

    return dict(
        employee_pf=employee_pf, employer_pf=employer_pf,
        employee_esi=employee_esi, employer_esi=employer_esi,
        professional_tax=professional_tax,
        tds=tds, annual_tax=annual_tax,
    )
