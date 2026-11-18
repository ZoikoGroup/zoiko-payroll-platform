"""UAE end-of-service benefit (ZP-AE-ENG-001 §9 traditional gratuity, §10 savings scheme).

Traditional gratuity (full-time foreign workers, AE-028/AE-029):

    eligible years Y = (service days − unpaid absence days) / 365
    days             = 0                                        if Y < minimum years
                     = first_band_days × min(Y, band) + after_band_days × max(Y − band, 0)
    amount           = min(days × last Basic Wage / day divisor, cap months × total Wage)

The monthly accrual (employer cost) is the change in that entitlement over the
pay period: entitlement(period end) − entitlement(day before period start).

Savings scheme (AE-033/AE-034): employer subscription = Basic Wage × rate, the
lower rate while continuous service (from date of joining, not enrolment) is
within the band, the higher rate after. The traditional gratuity accrued up to
enrolment is frozen at the Basic Wage at enrolment and reported separately
(AE-063: never merged into one 'severance' line).

All values come from the pack (params.py); nothing is hardcoded here.
"""
from datetime import date, timedelta
from decimal import Decimal

from app.modules.payroll.engine.base import _round2
from app.modules.payroll.engine.jurisdictions.uae import params as P

_DAYS_PER_YEAR = Decimal("365")   # calendar-year length for service fractions (spec: "fractions pro-rated")
_ZERO = Decimal("0")


def service_years(date_of_joining: date, as_of: date, unpaid_absence_days: int = 0) -> Decimal:
    """Completed continuous service in years at `as_of` (the joining day is day
    zero; a full year is 365 completed days)."""
    if as_of < date_of_joining:
        return _ZERO
    days = (as_of - date_of_joining).days - max(int(unpaid_absence_days or 0), 0)
    return max(Decimal(days), _ZERO) / _DAYS_PER_YEAR


def entitlement(years: Decimal, basic_wage: Decimal, total_wage: Decimal, rate_map: dict) -> dict:
    """The traditional gratuity for `years` of eligible service (unrounded amount + trace)."""
    minimum = P.amount(rate_map, "ae_eos_min_service_years")
    band = P.amount(rate_map, "ae_eos_band_years")
    first_days = P.amount(rate_map, "ae_eos_days_first_band")
    after_days = P.amount(rate_map, "ae_eos_days_after_band")
    divisor = P.amount(rate_map, "ae_eos_day_divisor")
    cap_months = P.amount(rate_map, "ae_eos_cap_months_wage")
    if years < minimum:
        return {"years": years, "days": _ZERO, "amount": _ZERO, "cap": cap_months * total_wage, "capped": False}
    days = first_days * min(years, band) + after_days * max(years - band, _ZERO)
    raw = days * basic_wage / divisor
    cap = cap_months * total_wage
    return {"years": years, "days": days, "amount": min(raw, cap), "cap": cap, "capped": raw > cap}


def traditional(date_of_joining: date, period_start: date, period_end: date, basic_wage: Decimal,
                total_wage: Decimal, unpaid_absence_days: int, rate_map: dict, period_unpaid_days: int = 0) -> dict:
    """Entitlement at the start and end of the period and the month's accrual.

    `unpaid_absence_days` is the unpaid absence recorded BEFORE this period;
    `period_unpaid_days` is this period's. The period's own absence reduces only
    the end-of-period service, so it is excluded from this month's accrual
    (AE-029) instead of cancelling out across both ends."""
    prior = max(int(unpaid_absence_days or 0), 0)
    before = entitlement(service_years(date_of_joining, period_start - timedelta(days=1), prior),
                         basic_wage, total_wage, rate_map)
    after = entitlement(service_years(date_of_joining, period_end, prior + max(int(period_unpaid_days or 0), 0)),
                        basic_wage, total_wage, rate_map)
    return {
        "regime": "TRADITIONAL",
        "service_years": after["years"],
        "entitlement_days": after["days"],
        "entitlement": _round2(after["amount"]),
        "capped": after["capped"],
        "accrual": _round2(after["amount"] - before["amount"]),
    }


def savings(date_of_joining: date, period_end: date, basic_wage: Decimal, enrollment_date: date,
            enrollment_basic_wage: Decimal, total_wage: Decimal, unpaid_absence_days: int, rate_map: dict) -> dict:
    """Employer subscription for the month + the frozen pre-enrolment gratuity."""
    years = service_years(date_of_joining, period_end, unpaid_absence_days)
    band = P.amount(rate_map, "ae_eos_savings_band_years")
    key = "ae_eos_savings_up_to_band" if years <= band else "ae_eos_savings_over_band"
    rate = P.pct(rate_map, key, "employer")
    frozen = entitlement(service_years(date_of_joining, enrollment_date - timedelta(days=1), unpaid_absence_days),
                         enrollment_basic_wage, total_wage, rate_map)
    return {
        "regime": "SAVINGS_SCHEME",
        "service_years": years,
        "subscription_rate": rate,
        "subscription": _round2(basic_wage * rate),
        "frozen_legacy_gratuity": _round2(frozen["amount"]),
        "enrollment_date": enrollment_date,
    }
