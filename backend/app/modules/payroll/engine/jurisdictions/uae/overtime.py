"""UAE overtime minimum hourly pay (ZP-AE-ENG-001 §11, AE-037, F6).

Overtime is paid on Basic Wage, never total Wage:

    basic hourly    = Basic Wage / day divisor / normal hours per day
    ordinary rate   = basic hourly × (1 + ordinary premium)
    night rate      = basic hourly × (1 + night premium)        (10pm-4am, non-shift)
    rest-day rate   = basic hourly × (1 + rest-day premium)     (no substitute rest)

The overtime AMOUNT paid in a run arrives as an ordinary earning (ctx.overtime);
these statutory minimum hourly rates are shown in the payslip breakdown so the
amount can be checked against them.
"""
from decimal import Decimal

from app.modules.payroll.engine.base import _round2
from app.modules.payroll.engine.jurisdictions.uae import params as P


def hourly_rates(basic_wage: Decimal, rate_map: dict) -> dict:
    hourly = basic_wage / P.amount(rate_map, "ae_eos_day_divisor") / P.amount(rate_map, "ae_ot_hours_per_day")
    return rates_from_hourly(hourly, rate_map)


def rates_from_hourly(hourly: Decimal, rate_map: dict) -> dict:
    one = Decimal("1")
    return {
        "basic_hourly": _round2(hourly),
        "ordinary": _round2(hourly * (one + P.pct(rate_map, "ae_ot_ordinary", "employee"))),
        "night": _round2(hourly * (one + P.pct(rate_map, "ae_ot_night", "employee"))),
        "rest_day": _round2(hourly * (one + P.pct(rate_map, "ae_ot_rest_day", "employee"))),
    }
