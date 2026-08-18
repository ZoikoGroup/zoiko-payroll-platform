"""
modules/payroll/engine/countries/canada.py
----------------------------------------------
Canada: CPP + EI (each with its own separate cap) + progressive federal
income tax with the Basic Personal Amount. Moved verbatim out of
engine/standard.py's _calc_canada.
"""

from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import MONTHS_PER_YEAR, _calculate_annual_tax, _param_amount

_CA_CPP_YMPE = Decimal("71300")
_CA_CPP_BASIC_EXEMPTION = Decimal("3500")
_CA_EI_MIE = Decimal("65700")
_CA_BASIC_PERSONAL_AMOUNT = Decimal("15705")


def _calculate_annual_tax_ca(annual_gross: Decimal, slabs, rate_map: dict) -> Decimal:
    bpa = _param_amount(rate_map, "basic_personal_amount", _CA_BASIC_PERSONAL_AMOUNT)
    taxable = max(Decimal("0"), annual_gross - bpa)
    return _calculate_annual_tax(taxable, slabs)


def calculate(ctx: PayrollContext) -> dict:
    """Canada: CPP (Canada Pension Plan — contributory earnings floored by
    the Basic Exemption Amount, capped at the Year's Maximum Pensionable
    Earnings) + EI (Employment Insurance — capped separately at its own
    Maximum Insurable Earnings) + progressive federal income tax with the
    Basic Personal Amount deducted first (provincial tax excluded for
    simplicity). DB-backed rates.

    Reused PayrollResult fields: `social_security`/`employer_social_security`
    (CPP) and `employee_esi`/`employer_esi` (EI)."""
    rate_map = ctx.rate_map
    gross = ctx.gross
    annual_gross = gross * MONTHS_PER_YEAR

    cpp_ympe = _param_amount(rate_map, "cpp_ympe", _CA_CPP_YMPE)
    cpp_basic_exemption = _param_amount(rate_map, "cpp_basic_exemption", _CA_CPP_BASIC_EXEMPTION)
    annual_cpp_pensionable = max(Decimal("0"), min(annual_gross, cpp_ympe) - cpp_basic_exemption)
    cpp_rate = rate_map.get("cpp")
    social_security = (
        _round2((annual_cpp_pensionable * (cpp_rate.employee_rate_pct / 100)) / MONTHS_PER_YEAR)
        if cpp_rate and cpp_rate.employee_rate_pct else Decimal("0")
    )
    employer_social_security = (
        _round2((annual_cpp_pensionable * (cpp_rate.employer_rate_pct / 100)) / MONTHS_PER_YEAR)
        if cpp_rate and cpp_rate.employer_rate_pct else Decimal("0")
    )

    ei_mie = _param_amount(rate_map, "ei_mie", _CA_EI_MIE)
    annual_ei_insurable = min(annual_gross, ei_mie)
    ei_rate = rate_map.get("ei")
    employee_esi = (
        _round2((annual_ei_insurable * (ei_rate.employee_rate_pct / 100)) / MONTHS_PER_YEAR)
        if ei_rate and ei_rate.employee_rate_pct else Decimal("0")
    )
    employer_esi = (
        _round2((annual_ei_insurable * (ei_rate.employer_rate_pct / 100)) / MONTHS_PER_YEAR)
        if ei_rate and ei_rate.employer_rate_pct else Decimal("0")
    )

    annual_tax = _calculate_annual_tax_ca(annual_gross, ctx.slabs, rate_map)
    tds = _round2(annual_tax / MONTHS_PER_YEAR)

    return dict(
        social_security=social_security, employer_social_security=employer_social_security,
        employee_esi=employee_esi, employer_esi=employer_esi,
        tds=tds, annual_tax=annual_tax,
    )
