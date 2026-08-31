"""
modules/payroll/engine/countries/canada.py
----------------------------------------------
Canada: CPP + EI (each with its own separate cap) + progressive federal
income tax with the Basic Personal Amount. Moved verbatim out of
engine/standard.py's _calc_canada.
"""

from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import MONTHS_PER_YEAR, _calculate_annual_tax, resolve_jurisdiction_parameter
# Fallback constants moved to hardcoded_defaults.py — imported back under
# their original names so nothing else needs to change.
from app.modules.payroll.hardcoded_defaults import (
    _CA_CPP_YMPE, _CA_CPP_BASIC_EXEMPTION, _CA_EI_MIE, _CA_BASIC_PERSONAL_AMOUNT,
    _CA_CPP2_YAMPE, _CA_CPP2_RATE,
)


def _calculate_annual_tax_ca(annual_gross: Decimal, slabs, rate_map: dict) -> Decimal:
    # Key shortened from "basic_personal_amount" (21 chars) to fit
    # payroll_contribution_rates.component_key's VARCHAR(20).
    bpa = resolve_jurisdiction_parameter(rate_map, "basic_personal_amt", _CA_BASIC_PERSONAL_AMOUNT, country="CA")
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

    cpp_ympe = resolve_jurisdiction_parameter(rate_map, "cpp_ympe", _CA_CPP_YMPE, country="CA")
    cpp_basic_exemption = resolve_jurisdiction_parameter(rate_map, "cpp_basic_exemption", _CA_CPP_BASIC_EXEMPTION, country="CA")
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

    # CPP2 — a second, higher-earnings-only band, on top of the first
    # tier above. rate_map has no dedicated "cpp2" ContributionRate row
    # seeded (a % is enough here; there's no separate employer-vs-
    # employee rate story beyond the shared 4%), so this is resolved as
    # a plain percentage parameter, not a rate_map.get() lookup like the
    # first-tier "cpp" row.
    cpp2_yampe = resolve_jurisdiction_parameter(rate_map, "cpp2_yampe", _CA_CPP2_YAMPE, country="CA")
    cpp2_rate = resolve_jurisdiction_parameter(rate_map, "cpp2_rate", _CA_CPP2_RATE, side="employee", country="CA")
    annual_cpp2_pensionable = max(Decimal("0"), min(annual_gross, cpp2_yampe) - cpp_ympe)
    cpp2 = _round2((annual_cpp2_pensionable * cpp2_rate / Decimal("100")) / MONTHS_PER_YEAR)

    ei_mie = resolve_jurisdiction_parameter(rate_map, "ei_mie", _CA_EI_MIE, country="CA")
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
        cpp2=cpp2,
        tds=tds, annual_tax=annual_tax,
    )
