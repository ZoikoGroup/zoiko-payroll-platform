"""
modules/payroll/engine/countries/jamaica.py
------------------------------------------------
Jamaica (JM) — Phase 1 statutory build (ZP-JM-ENG-001).

Four independent statutory obligations (JM-008 — never one generic
"taxable gross" field standing in for all of them):
  1. PAYE — gross minus employee NIS, minus the personal allowance, then
     progressive bands (the spec's own §12 fixture computes PAYE on
     194,000 = 200,000 gross minus 6,000 NIS employee, not on full
     gross). The spec itself
     flags its own PAYE band candidate values (25%/30% at a 6,000,000
     annual chargeable-income breakpoint) as unconfirmed ("Do not
     activate from this document") pending TAJ's real withholding
     method/tables (JM gate G1) — bands therefore come entirely from
     `ctx.slabs` (canonical TaxSlab rows for country="JM") via the
     generic `_calculate_annual_tax` bracket engine, annualized/
     de-annualized like every other bracket-based country (Barbados,
     UK, India, ...). The personal allowance is period-by-period, not
     one blended annual figure: the spec's own §3 table gives a
     January-March 2026 monthly rate (149,948) that is genuinely lower
     than the April-December rate (158,530) — JM-005 requires selecting
     content by the actual pay date's month, not a server-date/blended
     guess. `ctx.pay_date.month <= 3` selects the Jan-Mar monthly
     allowance (own Python fallback, `jm_personal_allowance_jan_mar_
     monthly`); every other month uses the existing annual
     `jm_personal_allowance` value (still the Apr-Dec annualized
     figure, unchanged, already live-seeded) divided by
     periods_per_year. `ctx.pay_date is None` (e.g. an older caller)
     falls back to the Apr-Dec value exactly as before this change —
     no behavior change for existing callers that never set pay_date.
     Reused field: `tds`.
  2. NIS — employee 3% / employer 3%. Reused fields: `social_security` /
     `employer_social_security`.
  3. NHT — employee 2% / employer 3%, no ceiling. Reused fields
     (repurposed, NOT a literal pension): `employee_pension` /
     `employer_pension`.
  4. Education Tax — employee 2.25% / employer 3.5% on (gross minus
     employee NIS). Reused fields (repurposed, NOT UK National
     Insurance): `ni_employee` / `employer_ni`.
  5. HEART — employer-only 3% once EMPLOYER-WIDE monthly emoluments
     exceed JMD 14,444 (JM-008's "evaluate across all pay groups").
     Phase 1 evaluates the threshold against this employee's own gross
     only — genuine employer-wide aggregation across pay groups needs a
     YTD/org-level accumulator not yet wired (same deferred-until-real-
     data discipline as every other cross-employee aggregate in this
     codebase). Reused field: `employer_payroll_tax`.

Validated against ZP-JM-ENG-001 §12 Fixture F1 (200,000/mo) — see
tests/test_jamaica.py; matches the fixture's exact totals (23,232.50
employee deductions, 24,790.00 employer contributions, 176,767.50 net).
"""

from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import (
    resolve_periods_per_year,
    resolve_jurisdiction_parameter,
    _calculate_annual_tax,
)

_JM_ANNUAL_ALLOWANCE = Decimal("1902360")  # 158,530 x 12 (Apr-Dec 2026 rate) — see module docstring
_JM_JAN_MAR_MONTHLY_ALLOWANCE = Decimal("149948")  # Jan-Mar 2026 monthly rate — see module docstring

_JM_NIS_RATE = Decimal("0.03")
_JM_NHT_EMPLOYEE_RATE = Decimal("0.02")
_JM_NHT_EMPLOYER_RATE = Decimal("0.03")
_JM_EDU_TAX_EMPLOYEE_RATE = Decimal("0.0225")
_JM_EDU_TAX_EMPLOYER_RATE = Decimal("0.035")
_JM_HEART_RATE = Decimal("0.03")
_JM_HEART_THRESHOLD = Decimal("14444")


def _resolve_period_allowance(rate_map: dict, periods_per_year: Decimal, pay_date) -> Decimal:
    """Jan-Mar 2026 uses a genuinely lower monthly personal allowance than
    Apr-Dec (ZP-JM-ENG-001 §3) — selected by the actual pay date's month,
    never server date. `pay_date is None` (no behavior change for callers
    that don't set it) falls back to the existing Apr-Dec annual value."""
    if pay_date is not None and pay_date.month <= 3:
        jan_mar_monthly = resolve_jurisdiction_parameter(
            rate_map, "jm_personal_allowance_jan_mar_monthly", _JM_JAN_MAR_MONTHLY_ALLOWANCE, country="JM",
        )
        return (jan_mar_monthly * Decimal("12")) / periods_per_year
    allowance_annual = resolve_jurisdiction_parameter(rate_map, "jm_personal_allowance", _JM_ANNUAL_ALLOWANCE, country="JM")
    return allowance_annual / periods_per_year


def calculate(ctx: PayrollContext) -> dict:
    """Jamaica: PAYE (annualized bracket lookup) + NIS + NHT + Education
    Tax + HEART (per-employee threshold, Phase 1)."""
    rate_map = ctx.rate_map
    periods_per_year = resolve_periods_per_year(ctx.pay_frequency)
    period_gross = ctx.gross

    nis_rate = resolve_jurisdiction_parameter(rate_map, "jm_nis", _JM_NIS_RATE, side="employee", country="JM")
    nis_employer_rate = resolve_jurisdiction_parameter(rate_map, "jm_nis", _JM_NIS_RATE, side="employer", country="JM")
    social_security = _round2(period_gross * nis_rate)
    employer_social_security = _round2(period_gross * nis_employer_rate)

    nht_employee_rate = resolve_jurisdiction_parameter(rate_map, "jm_nht", _JM_NHT_EMPLOYEE_RATE, side="employee", country="JM")
    nht_employer_rate = resolve_jurisdiction_parameter(rate_map, "jm_nht", _JM_NHT_EMPLOYER_RATE, side="employer", country="JM")
    employee_pension = _round2(period_gross * nht_employee_rate)   # NHT employee — see module docstring
    employer_pension = _round2(period_gross * nht_employer_rate)   # NHT employer — see module docstring

    edu_base = max(period_gross - social_security, Decimal("0"))
    edu_employee_rate = resolve_jurisdiction_parameter(rate_map, "jm_education_tax", _JM_EDU_TAX_EMPLOYEE_RATE, side="employee", country="JM")
    edu_employer_rate = resolve_jurisdiction_parameter(rate_map, "jm_education_tax", _JM_EDU_TAX_EMPLOYER_RATE, side="employer", country="JM")
    ni_employee = _round2(edu_base * edu_employee_rate)            # Education Tax employee — see module docstring
    employer_ni = _round2(edu_base * edu_employer_rate)            # Education Tax employer — see module docstring

    # PAYE base = gross minus employee NIS (the spec's own §12 fixture:
    # "PAYE: (194,000 − 158,530) × 25%", where 194,000 = 200,000 gross
    # minus the 6,000 NIS employee deduction above) — NOT full gross.
    period_allowance = _resolve_period_allowance(rate_map, periods_per_year, ctx.pay_date)
    paye_base_period = max(period_gross - social_security, Decimal("0"))
    taxable_annualized = max(paye_base_period - period_allowance, Decimal("0")) * periods_per_year
    tds = _round2(_calculate_annual_tax(taxable_annualized, ctx.slabs) / periods_per_year)

    heart_threshold = resolve_jurisdiction_parameter(rate_map, "jm_heart_threshold", _JM_HEART_THRESHOLD, country="JM")
    heart_rate = resolve_jurisdiction_parameter(rate_map, "jm_heart", _JM_HEART_RATE, side="employer", country="JM")
    employer_payroll_tax = _round2(period_gross * heart_rate) if period_gross > heart_threshold else Decimal("0")

    return dict(
        tds=tds,
        social_security=social_security,
        employer_social_security=employer_social_security,
        employee_pension=employee_pension,
        employer_pension=employer_pension,
        ni_employee=ni_employee,
        employer_ni=employer_ni,
        employer_payroll_tax=employer_payroll_tax,
    )
