"""
modules/payroll/engine/countries/guyana.py
-----------------------------------------------
Guyana (GY) — Phase 1 statutory build (ZP-GY-ENG-001).

PAYE (GY-006/GY-007/GY-009), non-cumulative, period-by-period:
  personal_deduction = max(fixed monthly allowance, one-third of period
  gross) — Phase 1 models the ordinary primary-employee case only
  (overtime/second-job/child/medical-premium deductions, and the
  2026-Jan/Feb statutory refund-credit ledger, are explicitly deferred;
  GY-010's ledger needs a real YTD accumulator, same dormancy discipline
  as every other deferred YTD feature in this codebase — not built yet).
  chargeable = max(gross - personal_deduction - employee_NIS, 0), then
  25% up to the GYD 280,000 chargeable band, 35% above. Reused field:
  `tds`.

Bands come from `ctx.slabs` (canonical TaxSlab rows for country="GY",
period-denominated — the spec's own GYD 280,000 figure IS the monthly
band directly, not an annual figure divided by 12) via the same generic
`_calculate_annual_tax` bracket engine, applied directly to this period's
chargeable income (Guyana's PAYE is genuinely non-cumulative/non-annual
by design, so there is no annualize/de-annualize round-trip here — see
GY-006). Only correct for Monthly pay frequency until dedicated
weekly-band TaxSlab rows are seeded — GY-013's exceptional NIS age class
and GY-014's earning-line NIS-base classification are also deferred.

NIS (GY-011/GY-012): employee 5.6% / employer 8.4% of insurable earnings,
capped at the current monthly (GYD 280,000) or weekly (GYD 64,615)
ceiling. Reused fields: `social_security` / `employer_social_security`.

Validated against ZP-GY-ENG-001 §13 fixtures F1 (200,000/mo) and F2
(600,000/mo) — see tests/test_guyana.py.
"""

from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import (
    resolve_jurisdiction_parameter,
    _calculate_annual_tax,
)

_GY_PERSONAL_ALLOWANCE = Decimal("140000")
_GY_NIS_EMPLOYEE_RATE = Decimal("0.056")
_GY_NIS_EMPLOYER_RATE = Decimal("0.084")
_GY_NIS_MONTHLY_CEILING = Decimal("280000")
_GY_NIS_WEEKLY_CEILING = Decimal("64615")


def _resolve_nis_ceiling(rate_map: dict, pay_frequency: str | None) -> Decimal:
    if (pay_frequency or "Monthly") == "Weekly":
        return resolve_jurisdiction_parameter(rate_map, "gy_nis_ceiling_weekly", _GY_NIS_WEEKLY_CEILING, country="GY")
    return resolve_jurisdiction_parameter(rate_map, "gy_nis_ceiling_monthly", _GY_NIS_MONTHLY_CEILING, country="GY")


def calculate(ctx: PayrollContext) -> dict:
    """Guyana: non-cumulative PAYE (personal deduction = greater of fixed
    allowance or one-third of gross) + NIS (capped)."""
    rate_map = ctx.rate_map
    period_gross = ctx.gross

    nis_ceiling = _resolve_nis_ceiling(rate_map, ctx.pay_frequency)
    nis_base = min(period_gross, nis_ceiling)
    nis_employee_rate = resolve_jurisdiction_parameter(rate_map, "gy_nis", _GY_NIS_EMPLOYEE_RATE, side="employee", country="GY")
    nis_employer_rate = resolve_jurisdiction_parameter(rate_map, "gy_nis", _GY_NIS_EMPLOYER_RATE, side="employer", country="GY")
    social_security = _round2(nis_base * nis_employee_rate)
    employer_social_security = _round2(nis_base * nis_employer_rate)

    fixed_allowance = resolve_jurisdiction_parameter(rate_map, "gy_personal_allowance", _GY_PERSONAL_ALLOWANCE, country="GY")
    one_third = period_gross / Decimal("3")
    personal_deduction = max(fixed_allowance, one_third)

    chargeable = max(period_gross - personal_deduction - social_security, Decimal("0"))
    tds = _round2(_calculate_annual_tax(chargeable, ctx.slabs))

    return dict(
        tds=tds,
        social_security=social_security,
        employer_social_security=employer_social_security,
    )
