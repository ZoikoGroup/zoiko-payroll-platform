"""
modules/payroll/engine/countries/germany.py
-----------------------------------------------
Germany: Pension + Social Insurance (capped) + progressive income tax with
Grundfreibetrag and Solidarity Surcharge. Moved verbatim out of
engine/standard.py's _calc_germany.
"""

from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import MONTHS_PER_YEAR, _calculate_annual_tax, _param_amount, _param_pct

_DE_GRUNDFREIBETRAG = Decimal("11784")
_DE_CONTRIBUTION_CEILING = Decimal("96600")
_DE_SOLI_THRESHOLD = Decimal("18130")
_DE_SOLI_RATE = Decimal("5.5")


def _calculate_annual_tax_de(annual_gross: Decimal, slabs, rate_map: dict) -> Decimal:
    grundfreibetrag = _param_amount(rate_map, "grundfreibetrag", _DE_GRUNDFREIBETRAG)
    taxable = max(Decimal("0"), annual_gross - grundfreibetrag)
    tax = _calculate_annual_tax(taxable, slabs)

    soli_threshold = _param_amount(rate_map, "soli_threshold", _DE_SOLI_THRESHOLD)
    soli_rate = _param_pct(rate_map, "soli_rate", "employee", _DE_SOLI_RATE)
    if tax > soli_threshold:
        tax += tax * soli_rate / Decimal("100")
    return tax


def calculate(ctx: PayrollContext) -> dict:
    """Germany: Pension insurance (Rentenversicherung) + combined Health/
    Unemployment/Long-term-care insurance (simplified into one "social
    insurance" component), both capped at the annual Contribution
    Ceiling (Beitragsbemessungsgrenze) + progressive income tax with the
    Basic Tax-Free Allowance (Grundfreibetrag) deducted first and the
    Solidarity Surcharge added above a tax-liability threshold. DB-backed
    rates.

    Reused PayrollResult fields: `employee_pf`/`employer_pf` (Pension
    insurance) and `employee_esi`/`employer_esi` (combined social
    insurance) — payslip labels are swapped to German terminology for
    this country in generate_payslip_pdf_bytes."""
    rate_map = ctx.rate_map
    gross = ctx.gross
    annual_gross = gross * MONTHS_PER_YEAR

    contribution_ceiling = _param_amount(rate_map, "contribution_ceiling", _DE_CONTRIBUTION_CEILING)
    annual_contribution_base = min(annual_gross, contribution_ceiling)

    pension_rate = rate_map.get("pension")
    employee_pf = (
        _round2((annual_contribution_base * (pension_rate.employee_rate_pct / 100)) / MONTHS_PER_YEAR)
        if pension_rate and pension_rate.employee_rate_pct else Decimal("0")
    )
    employer_pf = (
        _round2((annual_contribution_base * (pension_rate.employer_rate_pct / 100)) / MONTHS_PER_YEAR)
        if pension_rate and pension_rate.employer_rate_pct else Decimal("0")
    )

    social_rate = rate_map.get("social-insurance")
    employee_esi = (
        _round2((annual_contribution_base * (social_rate.employee_rate_pct / 100)) / MONTHS_PER_YEAR)
        if social_rate and social_rate.employee_rate_pct else Decimal("0")
    )
    employer_esi = (
        _round2((annual_contribution_base * (social_rate.employer_rate_pct / 100)) / MONTHS_PER_YEAR)
        if social_rate and social_rate.employer_rate_pct else Decimal("0")
    )

    annual_tax = _calculate_annual_tax_de(annual_gross, ctx.slabs, rate_map)
    tds = _round2(annual_tax / MONTHS_PER_YEAR)

    return dict(
        employee_pf=employee_pf, employer_pf=employer_pf,
        employee_esi=employee_esi, employer_esi=employer_esi,
        tds=tds, annual_tax=annual_tax,
    )
