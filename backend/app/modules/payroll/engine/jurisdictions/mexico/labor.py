"""
engine/jurisdictions/mexico/labor.py
------------------------------------
Labour checks and hour-based earnings (spec §16, MX-048–MX-050):

- minimum wage: the daily salary must reach the applicable minimum — the
  employee's professional minimum when one is recorded, else the zone's
  (GENERAL / ZLFN, resolved by the service from the work location);
- workweek: the labour policy's ordinary weekly hours must not exceed the
  statutory maximum in force on the pay date (2026 vs the staged reductions,
  selected by date — MX-048);
- overtime is paid ONLY from approved hours supplied as input (MX-049, Q9):
  per week, hours up to `mx_overtime_double_weekly_max_hours` at
  `mx_overtime_double_multiplier`, the rest at `mx_overtime_triple_multiplier`,
  × the supplied hourly rate. Missing tier content BLOCKS; no hours → no
  overtime; an overtime line not derived from hours BLOCKS;
- Sunday premium: the policy % (never below `mx_sunday_premium_min_pct`) ×
  daily salary × Sundays worked;
- mandatory rest-day (holiday) work BLOCKS: no rest-day content exists yet.

The generated lines carry the earning codes the integration names, and are
classified like every other line.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .classification import OVERTIME, SUNDAY_PREMIUM
from .errors import MXBlock

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


def _dec(value, what: str, code: str = "MX_HOURS_INVALID") -> Decimal:
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise MXBlock(code, f"{what} is not a number")
    if not out.is_finite() or out < 0:
        raise MXBlock(code, f"{what} must be zero or more")
    return out


def minimum_wage(content, daily_salary: Decimal, zone: str, professional_code: str = None) -> dict:
    if zone not in ("GENERAL", "ZLFN"):
        raise MXBlock("MX_MIN_WAGE_ZONE_UNRESOLVED", "the employee's minimum-wage zone is not resolved")
    if professional_code:
        minimum, applied = content.min_wage(professional_code, zone), professional_code
    else:
        minimum, applied = content.min_wage(zone), zone
    if daily_salary < minimum:
        raise MXBlock("MX_BELOW_MINIMUM_WAGE", f"daily salary {daily_salary} is below the {applied} minimum wage")
    return {"zone": zone, "applied": applied, "minimum": minimum, "daily_salary": daily_salary}


def workweek(content, policy: dict) -> dict:
    maximum = content.workweek_max_hours()
    hours = _dec((policy or {}).get("ordinary_weekly_hours"), "labour-policy ordinary weekly hours",
                 "MX_LABOR_POLICY_INCOMPLETE")
    if hours > maximum:
        raise MXBlock("MX_WORKWEEK_ABOVE_MAXIMUM",
                      f"the labour policy's {hours} ordinary weekly hours exceed the statutory {maximum}")
    return {"policy_hours": hours, "statutory_max": maximum}


def hour_lines(content, hours, policy: dict, daily_salary: Decimal) -> dict:
    """{lines:[{code, kind, amount}], overtime:[…per week], sunday:{…}}."""
    hours = hours or {}
    out, weeks = [], []
    overtime = [_dec(w.get("overtime_hours") or 0, f"week {i + 1} overtime hours")
                for i, w in enumerate(hours.get("weeks") or [])]
    if any(h > 0 for h in overtime):
        keys = ("mx_overtime_double_weekly_max_hours", "mx_overtime_double_multiplier", "mx_overtime_triple_multiplier")
        if not all(content.has(k) for k in keys):
            raise MXBlock("MX_OVERTIME_RULES_MISSING", "overtime tiers are not transcribed (S26/S18)")
        tier_max, double, triple = (content.amount(k) for k in keys)
        rate = _dec(hours.get("hourly_rate"), "hourly rate")
        code = hours.get("overtime_code")
        if rate <= 0 or not code:
            raise MXBlock("MX_HOURS_INVALID", "approved overtime needs an hourly rate and an overtime earning code")
        total = _ZERO
        for i, h in enumerate(overtime):
            first = min(h, tier_max)
            amount = rate * (first * double + (h - first) * triple)
            weeks.append({"week": i + 1, "hours": h, "first_tier_hours": first, "second_tier_hours": h - first,
                          "amount": amount})
            total += amount
        out.append({"code": code, "kind": OVERTIME, "amount": total})
    sunday = None
    sundays = _dec(hours.get("sundays_worked") or 0, "Sundays worked")
    if sundays > 0:
        floor = content.pct("mx_sunday_premium_min_pct")
        policy_pct = _dec((policy or {}).get("sunday_premium_pct"), "labour-policy Sunday premium %",
                          "MX_LABOR_POLICY_INCOMPLETE") / _HUNDRED
        if policy_pct < floor:
            raise MXBlock("MX_LABOR_POLICY_BELOW_FLOOR", "the labour policy's Sunday premium is below the statutory minimum")
        code = hours.get("sunday_premium_code")
        if not code:
            raise MXBlock("MX_HOURS_INVALID", "Sundays worked need a Sunday-premium earning code")
        amount = daily_salary * policy_pct * sundays
        sunday = {"sundays": sundays, "policy_pct": policy_pct * _HUNDRED, "statutory_min_pct": floor * _HUNDRED,
                  "amount": amount}
        out.append({"code": code, "kind": SUNDAY_PREMIUM, "amount": amount})
    if _dec(hours.get("holiday_days") or 0, "rest days worked") > 0:
        raise MXBlock("MX_REST_DAY_CONTENT_MISSING", "work on a mandatory rest day — no rest-day content is transcribed")
    return {"lines": out, "overtime": weeks, "sunday": sunday}
