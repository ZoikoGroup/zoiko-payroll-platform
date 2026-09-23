"""
modules/payroll/engine/countries/cayman_islands.py
------------------------------------------------------
Cayman Islands (KY) — Phase 1 statutory build (ZP-KY-ENG-001).

Cayman has NO personal income tax (KY-002). `tds` is always Decimal("0")
here — deliberately the same value every other country returns when no
tax is due, not a fabricated tax object; the Super Admin Compliance page
and payslip copy for KY must label this "No Cayman personal income-tax
withholding applies", never a "0% tax band".

Mandatory private pension (KY-005..KY-009): 10% total (employer >= 5%,
employee <= 5% — modelled here as an even 5%/5% split, the ordinary case),
capped at CI$87,000 of mandatory pensionable earnings per calendar year.
Reused fields: `employee_pension` / `employer_pension`.

YTD cap crossing (KY-008's "CAPPED_FOR_YEAR" state, spec fixture F2) needs
a real cumulative accumulator across pay periods — wired to
PayrollYtdAccumulator via service.py's _load_ky_pension_ytd/
_upsert_ky_pension_ytd_accumulator (mirrors Australia's Superannuation
Guarantee MCB accumulator pattern exactly), gated on "KY" being in
engine/countries/shared.py's _YTD_ACCUMULATOR_ENABLED_COUNTRIES. When no
accumulator has been read yet for this employee (ctx.
ytd_ky_mandatory_pensionable_earnings_before is None — the dormant/not-
wired state), this module falls back to a per-period pro-rated share of
the annual cap (annual_cap / periods_per_year) — correct for F1 (an
employee nowhere near the cap) and every ordinary case, but does not
reproduce a genuine mid-year cap-crossing month in that fallback mode.
`pension_cap_ytd_wired` in the returned dict is False whenever the
fallback path is used, and `ytd_ky_mandatory_pensionable_earnings_after`
is only ever set (for service.py to persist) when the real accumulator
path ran.

Health insurance (SHIC) premiums are provider/policy data, not a
statutory rate — KY-010 explicitly forbids hard-coding a national premium
percentage. Not modelled here; a per-org health-deduction line is
authored the same way any other authorised deduction is, outside this
statutory engine.

Validated against ZP-KY-ENG-001 §14 fixture F1 — see tests/test_cayman_islands.py.
"""

from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import (
    resolve_periods_per_year,
    resolve_jurisdiction_parameter,
)

_KY_PENSION_ANNUAL_CAP = Decimal("87000")
_KY_PENSION_EMPLOYEE_RATE = Decimal("0.05")
_KY_PENSION_EMPLOYER_RATE = Decimal("0.05")


def calculate(ctx: PayrollContext) -> dict:
    """Cayman Islands: no income tax + mandatory pension (capped,
    per-period pro-rated cap until YTD accumulator wiring lands)."""
    rate_map = ctx.rate_map
    periods_per_year = resolve_periods_per_year(ctx.pay_frequency)
    period_gross = ctx.gross

    annual_cap = resolve_jurisdiction_parameter(rate_map, "ky_pension_annual_cap", _KY_PENSION_ANNUAL_CAP, country="KY")
    employee_rate = resolve_jurisdiction_parameter(rate_map, "ky_pension", _KY_PENSION_EMPLOYEE_RATE, side="employee", country="KY")
    employer_rate = resolve_jurisdiction_parameter(rate_map, "ky_pension", _KY_PENSION_EMPLOYER_RATE, side="employer", country="KY")

    ytd_before = ctx.ytd_ky_mandatory_pensionable_earnings_before
    pension_cap_ytd_wired = ytd_before is not None
    ytd_after = None
    if pension_cap_ytd_wired:
        remaining_cap = max(annual_cap - ytd_before, Decimal("0"))
        mandatory_base = min(period_gross, remaining_cap)
        ytd_after = ytd_before + mandatory_base
    else:
        period_cap = annual_cap / periods_per_year
        mandatory_base = min(period_gross, period_cap)

    employee_pension = _round2(mandatory_base * employee_rate)
    employer_pension = _round2(mandatory_base * employer_rate)

    return dict(
        tds=Decimal("0"),
        employee_pension=employee_pension,
        employer_pension=employer_pension,
        pension_cap_ytd_wired=pension_cap_ytd_wired,
        ytd_ky_mandatory_pensionable_earnings_after=ytd_after,
    )
