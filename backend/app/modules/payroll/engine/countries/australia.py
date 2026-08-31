"""
modules/payroll/engine/countries/australia.py
-------------------------------------------------
Australia: Superannuation Guarantee + Medicare Levy/Surcharge + progressive
income tax. Moved verbatim out of engine/standard.py's _calc_australia.
"""

from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import MONTHS_PER_YEAR, _calculate_annual_tax, resolve_jurisdiction_parameter
# Fallback constants moved to hardcoded_defaults.py — imported back under
# their original names so nothing else needs to change.
from app.modules.payroll.hardcoded_defaults import (
    _AU_MEDICARE_LEVY_LOW_INCOME_THRESHOLD, _AU_MLS_THRESHOLD, _AU_MLS_RATE,
    _AU_SUPER_MAX_CONTRIBUTION_BASE, _AU_HELP_THRESHOLD, _AU_HELP_RATE,
)


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

    # Key shortened from "super_max_contribution_base" (27 chars) to fit
    # payroll_contribution_rates.component_key's VARCHAR(20).
    super_cap = resolve_jurisdiction_parameter(rate_map, "super_max_contrib", _AU_SUPER_MAX_CONTRIBUTION_BASE, country="AU")
    super_rate = rate_map.get("super")
    annual_super_base = min(annual_gross, super_cap)
    employer_pension = (
        _round2((annual_super_base * (super_rate.employer_rate_pct / 100)) / MONTHS_PER_YEAR)
        if super_rate and super_rate.employer_rate_pct else Decimal("0")
    )

    # Key shortened from "medicare_levy_low_income_threshold" (34 chars) —
    # same VARCHAR(20) fix as super_max_contrib above.
    medicare_threshold = resolve_jurisdiction_parameter(rate_map, "medicare_low_inc_thr", _AU_MEDICARE_LEVY_LOW_INCOME_THRESHOLD, country="AU")
    medicare_rate = rate_map.get("medicare-levy")
    if annual_gross > medicare_threshold and medicare_rate and medicare_rate.employee_rate_pct:
        medicare = _round2(gross * (medicare_rate.employee_rate_pct / 100))
    else:
        medicare = Decimal("0")

    mls_threshold = resolve_jurisdiction_parameter(rate_map, "mls_threshold", _AU_MLS_THRESHOLD, country="AU")
    mls_rate = resolve_jurisdiction_parameter(rate_map, "mls_rate", _AU_MLS_RATE, side="employee", country="AU")
    if annual_gross > mls_threshold:
        medicare += _round2((annual_gross * mls_rate / Decimal("100")) / MONTHS_PER_YEAR)

    annual_tax = _calculate_annual_tax(annual_gross, ctx.slabs)
    tds = _round2(annual_tax / MONTHS_PER_YEAR)

    # HELP/HECS — the same shared study_loan_plan/study_loan_balance
    # mechanism UK's Student Loan uses (both are "government study-loan
    # repayment via payroll deduction above an income threshold").
    study_loan_deduction = Decimal("0")
    if ctx.study_loan_plan == "AU_HELP" and ctx.study_loan_balance and ctx.study_loan_balance > 0:
        help_threshold = resolve_jurisdiction_parameter(rate_map, "help_threshold", _AU_HELP_THRESHOLD, country="AU")
        help_rate = resolve_jurisdiction_parameter(rate_map, "help_rate", _AU_HELP_RATE, side="employee", country="AU")
        if annual_gross > help_threshold:
            study_loan_deduction = _round2((annual_gross * help_rate / Decimal("100")) / MONTHS_PER_YEAR)

    return dict(
        medicare=medicare,
        employer_pension=employer_pension,
        study_loan_deduction=study_loan_deduction,
        tds=tds, annual_tax=annual_tax,
    )
