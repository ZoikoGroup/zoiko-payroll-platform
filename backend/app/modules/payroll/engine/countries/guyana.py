"""
modules/payroll/engine/countries/guyana.py
-----------------------------------------------
Guyana (GY) — Phase 1 statutory build (ZP-GY-ENG-001).

PAYE (GY-006/GY-007/GY-009), non-cumulative, period-by-period:
  personal_deduction = max(fixed monthly allowance, one-third of period
  gross) — Phase 1 models the ordinary primary-employee case only
  (overtime/second-job/child/medical-premium deductions are still
  deferred).
  chargeable = max(gross - personal_deduction - employee_NIS, 0), then
  25% up to the GYD 280,000 chargeable band, 35% above. Reused field:
  `tds`.

GY-010 statutory credit ledger: `ctx.ytd_gy_paye_credit_before`, when
not None and > 0, is applied against this period's calculated PAYE
liability to determine the ACTUAL cash withheld from the employee.
DISCLOSED SIMPLIFICATION: GY-010 itself distinguishes "current-period
tax liability" (what a Form 5 return would report) from "cash
remittance" (what's actually withheld) as two separate values — this
module does not persist both. `tds` is the field every strategy
(engine/standard.py) actually deducts from net pay, so `tds` here is
the POST-CREDIT cash-withheld figure (the correctness-critical one —
an employee must not be shown paying more than they actually owe this
period); the pre-credit calculated liability is not separately
retained. Verified against the spec's own §13 Fixture F4 (5,000 credit
applied against a 12,200 March liability -> `tds` = 7,200 actual
withholding, credit exhausted to 0). DISCLOSED SCOPE: see
PayrollContext.ytd_gy_paye_credit_before's own docstring
(engine/base.py) — this is a general-purpose mechanism, not hardcoded
to the spec's specific 2026 Jan-Feb scenario, and there is no UI/API
yet to populate a real opening balance. `ctx.ytd_gy_paye_credit_before
is None` (every employee today) means no credit — identical behavior
to before this feature existed.

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
    calculated_liability = _round2(_calculate_annual_tax(chargeable, ctx.slabs))

    # GY-010 statutory credit ledger — see module docstring. credit_before
    # is None for every employee until a real opening balance is entered
    # (dormant today); ytd_gy_paye_credit_after is only ever set (for
    # service.py to persist) when the credit path actually ran.
    credit_before = ctx.ytd_gy_paye_credit_before
    if credit_before is not None and credit_before > 0:
        credit_applied = min(credit_before, calculated_liability)
        tds = _round2(calculated_liability - credit_applied)
        credit_after = _round2(credit_before - credit_applied)
    else:
        tds = calculated_liability
        credit_after = None

    return dict(
        tds=tds,
        social_security=social_security,
        employer_social_security=employer_social_security,
        ytd_gy_paye_credit_after=credit_after,
    )
