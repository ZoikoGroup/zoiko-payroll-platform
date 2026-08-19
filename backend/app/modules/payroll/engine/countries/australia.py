"""
modules/payroll/engine/countries/australia.py
-------------------------------------------------
Australia: Superannuation Guarantee + Medicare Levy/Surcharge + progressive
income tax. Moved verbatim out of engine/standard.py's _calc_australia.
"""

from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import MONTHS_PER_YEAR, _calculate_annual_tax, _param_amount, _param_pct

_AU_MEDICARE_LEVY_LOW_INCOME_THRESHOLD = Decimal("24276")
_AU_MLS_THRESHOLD = Decimal("97000")
_AU_MLS_RATE = Decimal("1.0")
_AU_SUPER_MAX_CONTRIBUTION_BASE = Decimal("260280")


def calculate(ctx: PayrollContext) -> dict:
    """Australia: Superannuation Guarantee (employer-only, capped at the
    Max Contribution Base) + Medicare Levy (employee, waived below a
    low-income threshold, plus a Medicare Levy Surcharge above a separate
    higher threshold) + progressive income tax. Rates are DB-backed
    (ContributionRate/TaxSlab, seeded with representative defaults on
    first use) — same configuration-driven pattern as India, not
    hardcoded module constants.

    Reused PayrollResult fields: `medicare` (Medicare Levy + MLS combined
    — name already matches AU terminology) and `employer_pension`
    (Superannuation)."""
    rate_map = ctx.rate_map
    gross = ctx.gross
    annual_gross = gross * MONTHS_PER_YEAR

    super_cap = _param_amount(rate_map, "super_max_contribution_base", _AU_SUPER_MAX_CONTRIBUTION_BASE)
    super_rate = rate_map.get("super")
    annual_super_base = min(annual_gross, super_cap)
    employer_pension = (
        _round2((annual_super_base * (super_rate.employer_rate_pct / 100)) / MONTHS_PER_YEAR)
        if super_rate and super_rate.employer_rate_pct else Decimal("0")
    )

    medicare_threshold = _param_amount(rate_map, "medicare_levy_low_income_threshold", _AU_MEDICARE_LEVY_LOW_INCOME_THRESHOLD)
    medicare_rate = rate_map.get("medicare-levy")
    if annual_gross > medicare_threshold and medicare_rate and medicare_rate.employee_rate_pct:
        medicare = _round2(gross * (medicare_rate.employee_rate_pct / 100))
    else:
        medicare = Decimal("0")

    mls_threshold = _param_amount(rate_map, "mls_threshold", _AU_MLS_THRESHOLD)
    mls_rate = _param_pct(rate_map, "mls_rate", "employee", _AU_MLS_RATE)
    if annual_gross > mls_threshold:
        medicare += _round2((annual_gross * mls_rate / Decimal("100")) / MONTHS_PER_YEAR)

    annual_tax = _calculate_annual_tax(annual_gross, ctx.slabs)
    tds = _round2(annual_tax / MONTHS_PER_YEAR)

    return dict(
        medicare=medicare,
        employer_pension=employer_pension,
        tds=tds, annual_tax=annual_tax,
    )
