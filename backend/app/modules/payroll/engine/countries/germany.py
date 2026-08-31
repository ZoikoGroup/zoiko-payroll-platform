"""
modules/payroll/engine/countries/germany.py
-----------------------------------------------
Germany: Pension + Social Insurance (capped) + progressive income tax with
Grundfreibetrag and Solidarity Surcharge. Moved verbatim out of
engine/standard.py's _calc_germany.
"""

from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import MONTHS_PER_YEAR, _calculate_annual_tax, resolve_jurisdiction_parameter
# Fallback constants moved to hardcoded_defaults.py — imported back under
# their original names so nothing else needs to change.
from app.modules.payroll.hardcoded_defaults import (
    _DE_GRUNDFREIBETRAG, _DE_CONTRIBUTION_CEILING, _DE_SOLI_THRESHOLD,
    _DE_SOLI_RATE, _DE_CHURCH_TAX_RATE,
)


def _calculate_annual_tax_de(annual_gross: Decimal, slabs, rate_map: dict) -> Decimal:
    grundfreibetrag = resolve_jurisdiction_parameter(rate_map, "grundfreibetrag", _DE_GRUNDFREIBETRAG, country="DE")
    taxable = max(Decimal("0"), annual_gross - grundfreibetrag)
    base_tax = _calculate_annual_tax(taxable, slabs)

    soli_threshold = resolve_jurisdiction_parameter(rate_map, "soli_threshold", _DE_SOLI_THRESHOLD, country="DE")
    soli_rate = resolve_jurisdiction_parameter(rate_map, "soli_rate", _DE_SOLI_RATE, side="employee", country="DE")
    tax = base_tax
    if tax > soli_threshold:
        tax += tax * soli_rate / Decimal("100")
    return tax, base_tax


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

    contribution_ceiling = resolve_jurisdiction_parameter(rate_map, "contribution_ceiling", _DE_CONTRIBUTION_CEILING, country="DE")
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

    annual_tax, base_tax = _calculate_annual_tax_de(annual_gross, ctx.slabs, rate_map)
    tds = _round2(annual_tax / MONTHS_PER_YEAR)

    church_tax = Decimal("0")
    if ctx.church_tax_liable:
        church_tax_rate = resolve_jurisdiction_parameter(rate_map, "church_tax_rate", _DE_CHURCH_TAX_RATE, side="employee", country="DE")
        church_tax = _round2((base_tax * church_tax_rate / Decimal("100")) / MONTHS_PER_YEAR)

    return dict(
        employee_pf=employee_pf, employer_pf=employer_pf,
        employee_esi=employee_esi, employer_esi=employer_esi,
        church_tax=church_tax,
        tds=tds, annual_tax=annual_tax,
    )
