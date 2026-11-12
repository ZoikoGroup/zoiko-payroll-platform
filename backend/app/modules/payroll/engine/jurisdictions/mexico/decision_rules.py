"""
engine/jurisdictions/mexico/decision_rules.py
---------------------------------------------
Sweep S1: the options of the interface-type decisions, built so that answering
the decision selects one (decisions.switch). None answered = the module
constant in mexico_content (None in production: the case BLOCKS).

  D-18  FIXED SBC items (LSS Art. 30 I) — a periodic amount to a daily amount:
        PERIOD_DAYS      the amount ÷ the calendar days of the pay period
        ANNUALISED_365   the amount × the item's payments per year ÷ 365
                         (needs the earning line's payments_per_year)
  D-19  fixed salary days when employment ends inside a fixed-days period:
        FIXED_DAYS_PRORATED   the period's fixed days × (days worked ÷ the
                              period's calendar days)
        CALENDAR_DAYS_WORKED  the calendar days from the period start to the
                              termination date
"""

from __future__ import annotations

from decimal import Decimal

from .decisions import switch
from .errors import MXBlock

_ZERO = Decimal("0")
# The fixed days a period name carries (QUINCENAL_15 = 15 …); MONTHLY pays 30.
_PERIOD_FIXED_DAYS = {"WEEKLY_7": Decimal("7"), "DECENAL_10": Decimal("10"), "QUINCENAL_15": Decimal("15"),
                      "MONTHLY": Decimal("30")}


def _dec(value, what):
    try:
        return Decimal(str(value))
    except Exception:
        raise MXBlock("MX_SBC_FIXED_RULE_INVALID", f"{what} is not a number")


class PeriodDaysRule:
    name = "PERIOD_DAYS"

    def daily_amount(self, line, facts) -> Decimal:
        days = sum((_dec(s.get("days"), "segment days") for s in facts.get("segments") or []), _ZERO)
        if days <= 0:
            raise MXBlock("MX_SBC_FIXED_RULE_INVALID", "the pay period has no days to spread a FIXED item over")
        return _dec(line.get("amount"), f"{line.get('code')} amount") / days


class Annualised365Rule:
    name = "ANNUALISED_365"

    def daily_amount(self, line, facts) -> Decimal:
        per_year = line.get("payments_per_year")
        if per_year in (None, ""):
            raise MXBlock("MX_SBC_FIXED_FREQUENCY_MISSING",
                          f"earning {line.get('code')} has no payments-per-year — annualising it (D-18) needs it")
        return _dec(line.get("amount"), f"{line.get('code')} amount") * _dec(per_year, "payments per year") / 365


class FixedDaysProratedRule:
    name = "FIXED_DAYS_PRORATED"

    def days_paid(self, tariff, period_start, period_end, termination_date) -> Decimal:
        fixed = _PERIOD_FIXED_DAYS.get(tariff)
        if fixed is None:
            raise MXBlock("MX_SALARY_DAYS_PARTIAL_PERIOD", f"{tariff} is not a fixed-days period")
        calendar = Decimal((period_end - period_start).days + 1)
        worked = Decimal((termination_date - period_start).days + 1)
        return fixed * worked / calendar


class CalendarDaysWorkedRule:
    name = "CALENDAR_DAYS_WORKED"

    def days_paid(self, tariff, period_start, period_end, termination_date) -> Decimal:
        return Decimal((termination_date - period_start).days + 1)


SBC_FIXED_RULES = {r.name: r for r in (PeriodDaysRule(), Annualised365Rule())}
FIXED_DAYS_TERMINATION_RULES = {r.name: r for r in (FixedDaysProratedRule(), CalendarDaysWorkedRule())}


def sbc_fixed_integration_rule(fallback):
    """D-18's answered rule, else the transcribed constant (None = BLOCK)."""
    name = switch("D-18")
    return SBC_FIXED_RULES.get(name, fallback) if name else fallback


def fixed_days_termination_rule(fallback):
    """D-19's answered rule, else the transcribed constant (None = BLOCK)."""
    name = switch("D-19")
    return FIXED_DAYS_TERMINATION_RULES.get(name, fallback) if name else fallback
