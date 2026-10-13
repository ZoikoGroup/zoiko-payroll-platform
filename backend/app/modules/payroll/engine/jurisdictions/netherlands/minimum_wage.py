"""
engine/jurisdictions/netherlands/minimum_wage.py
------------------------------------------------
Statutory minimum wage check (ZP-NL-ENG-001 §14, NL-041, fixture F6).

The Netherlands has an HOURLY statutory minimum by age — no universal
monthly minimum — so compliance is reckonable wage ÷ paid hours against the
hourly rate in force on the pay date. The rates come from the active pack's
NL_MIN_WAGE TaxSlab rows (filing_status = age cohort, flat_amount = hourly
rate, effective_from/effective_to = legal window), never from this module.
Pure: no ORM, no framework.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Optional

NL_MIN_WAGE_RULE = "NL_MIN_WAGE"


class MinimumWageError(Exception):
    """A minimum-wage fact or rate is missing — the caller blocks."""


@dataclass(frozen=True)
class MinimumWageResult:
    compliant: bool
    required_hourly: Decimal
    actual_hourly: Decimal
    hours: Decimal
    reckonable_wage: Decimal
    shortfall: Decimal          # total shortfall for the period (hours × hourly gap)
    age_cohort: str
    pay_date: date

    def as_dict(self) -> dict:
        return {"compliant": self.compliant, "requiredHourly": str(self.required_hourly),
                "actualHourly": str(self.actual_hourly), "hours": str(self.hours),
                "reckonableWage": str(self.reckonable_wage), "shortfall": str(self.shortfall),
                "ageCohort": self.age_cohort, "payDate": self.pay_date.isoformat()}


def resolve_age_cohort(date_of_birth: date, pay_date: date) -> str:
    age = pay_date.year - date_of_birth.year - (
        (pay_date.month, pay_date.day) < (date_of_birth.month, date_of_birth.day))
    if age >= 21:
        return "AGE_21_PLUS"
    if age >= 15:
        return f"AGE_{age}"
    raise MinimumWageError(f"Age {age} on {pay_date} is below the statutory minimum-wage scope (15)")


def _in_window(row: Any, on: date) -> bool:
    eff_from, eff_to = getattr(row, "effective_from", None), getattr(row, "effective_to", None)
    return (eff_from is None or eff_from <= on) and (eff_to is None or eff_to >= on)


def required_hourly(slabs: Iterable[Any], age_cohort: str, on: date) -> Decimal:
    """The NL_MIN_WAGE rate for the cohort in force on `on` (inclusive window)."""
    for row in slabs or ():
        if (getattr(row, "rule_type", None) == NL_MIN_WAGE_RULE
                and getattr(row, "filing_status", None) == age_cohort and _in_window(row, on)):
            if getattr(row, "flat_amount", None) is None:
                break
            return Decimal(str(row.flat_amount))
    raise MinimumWageError(
        f"No NL_MIN_WAGE rate in the active pack for {age_cohort} on {on} — the official rate must be "
        f"loaded before this worker can be paid (the January 2026 youth rates are not in ZP-NL-ENG-001)")


def check(*, slabs: Iterable[Any], date_of_birth: date, pay_date: date,
          reckonable_wage: Decimal, hours: Decimal) -> MinimumWageResult:
    if hours is None or Decimal(hours) <= 0:
        raise MinimumWageError("paid/reckonable hours are required for the hourly minimum-wage check (NL-041)")
    cohort = resolve_age_cohort(date_of_birth, pay_date)
    required = required_hourly(slabs, cohort, pay_date)
    hours = Decimal(hours)
    wage = Decimal(reckonable_wage)
    actual = (wage / hours).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    shortfall = max(required * hours - wage, Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return MinimumWageResult(compliant=actual >= required, required_hourly=required, actual_hourly=actual,
                             hours=hours, reckonable_wage=wage, shortfall=shortfall, age_cohort=cohort,
                             pay_date=pay_date)


def period_hours(weekly_hours: Optional[Decimal], periods_per_year: int) -> Optional[Decimal]:
    """Contractual hours in one pay period: weekly hours × 52 ÷ periods per year."""
    if weekly_hours is None:
        return None
    return (Decimal(weekly_hours) * Decimal("52") / Decimal(periods_per_year)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)


__all__ = ["MinimumWageError", "MinimumWageResult", "resolve_age_cohort", "required_hourly", "check",
           "period_hours", "NL_MIN_WAGE_RULE"]
