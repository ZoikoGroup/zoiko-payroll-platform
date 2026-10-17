"""
engine/jurisdictions/mexico/sbc.py
----------------------------------
Salario Base de Cotización (spec §7, MX-019–MX-022) with its full component
trace:

- fixed part = daily salary × integration factor, the factor taken from the
  employer's labour policy in force (MX-051: it may improve on a statutory
  floor, never go below it):
      factor = (365 + aguinaldo days + vacation days × vacation premium %) / 365
  with the policy's vacation days for the employee's service year. Any other
  FIXED-classified item BLOCKS until its integration rule (S10) is
  transcribed;
- variable part = prior-bimester variable pay ÷ its days, from the
  accumulator the run integration supplies (MX-020) — never estimated;
- the floor follows the transcribed `mx_sbc_min_rule` (Q5) and the maximum is
  `mx_sbc_max_uma_multiple` × the daily UMA in force for each contribution
  segment (MX-021: a January/February period uses each month's UMA).
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal, InvalidOperation

from .classification import ORDINARY_SALARY
from .errors import MXBlock

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
# The integration-factor formula's day count (spec §7) — a formula constant,
# not a rate; every rate in it comes from the labour policy.
DAYS_IN_YEAR = Decimal("365")
SBC_MIN_RULES = ("RAISE_TO_ZONE_MIN_WAGE", "BLOCK_BELOW_ZONE_MIN_WAGE")


def _dec(value, what: str, code: str = "MX_LABOR_POLICY_INCOMPLETE") -> Decimal:
    if value is None or value == "":
        raise MXBlock(code, f"{what} is missing")
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise MXBlock(code, f"{what} is not a number")
    if not out.is_finite() or out < 0:
        raise MXBlock(code, f"{what} must be a finite number of zero or more")
    return out


def service_year(seniority_date, on: _dt.date) -> int:
    """1 in the first year of service, 2 from the first anniversary, …"""
    if not isinstance(seniority_date, _dt.date):
        raise MXBlock("MX_SENIORITY_DATE_MISSING", "the employee's seniority date is not recorded")
    if seniority_date > on:
        raise MXBlock("MX_SENIORITY_DATE_INVALID", "the seniority date is after the pay date")
    years = on.year - seniority_date.year - ((on.month, on.day) < (seniority_date.month, seniority_date.day))
    return years + 1


def policy_vacation_days(policy: dict, year: int) -> Decimal:
    for row in policy.get("vacation_policy") or []:
        lo = row.get("serviceYearFrom")
        hi = row.get("serviceYearTo")
        if lo is not None and int(lo) <= year and (hi is None or year <= int(hi)):
            return _dec(row.get("days"), f"labour-policy vacation days for service year {year}")
    raise MXBlock("MX_LABOR_POLICY_INCOMPLETE", f"the labour policy has no vacation days for service year {year}")


def integration_factor(policy: dict, year: int) -> dict:
    if not policy:
        raise MXBlock("MX_LABOR_POLICY_MISSING", "no employer labour policy is in force")
    aguinaldo = _dec(policy.get("aguinaldo_days"), "labour-policy aguinaldo days")
    vacation = policy_vacation_days(policy, year)
    premium_pct = _dec(policy.get("vacation_premium_pct"), "labour-policy vacation premium %")
    factor = (DAYS_IN_YEAR + aguinaldo + vacation * premium_pct / _HUNDRED) / DAYS_IN_YEAR
    return {"factor": factor, "aguinaldo_days": aguinaldo, "vacation_days": vacation,
            "vacation_premium_pct": premium_pct, "service_year": year}


def variable_daily(accumulator) -> dict:
    if accumulator is None:
        raise MXBlock("MX_VARIABLE_ACCUMULATOR_MISSING",
                      "the prior-bimester variable-pay accumulator was not supplied (MX-020)")
    total = _dec(accumulator.get("total"), "variable accumulator total", "MX_VARIABLE_ACCUMULATOR_INVALID")
    days = _dec(accumulator.get("days"), "variable accumulator days", "MX_VARIABLE_ACCUMULATOR_INVALID")
    if days == 0:
        if total != 0:
            raise MXBlock("MX_VARIABLE_ACCUMULATOR_INVALID", "variable pay accumulated over zero days")
        return {"daily": _ZERO, "total": total, "days": days}
    return {"daily": total / days, "total": total, "days": days}


def _floor_rule(content):
    if not content.has("mx_sbc_min_rule"):
        return None
    rule = content.text("mx_sbc_min_rule").upper()
    if rule not in SBC_MIN_RULES:
        raise MXBlock("MX_RULE_UNRECOGNISED", f"mx_sbc_min_rule {rule!r} is not one of {SBC_MIN_RULES}")
    return rule


def compute(*, daily_salary, policy, seniority_date, on, lines, accumulator, segments, zone: str) -> dict:
    salary = _dec(daily_salary, "the employee's daily salary", "MX_DAILY_SALARY_MISSING")
    if salary <= 0:
        raise MXBlock("MX_DAILY_SALARY_MISSING", "the employee's daily salary must be more than zero")
    for line in lines:
        if line["sbc"] == "FIXED" and line["kind"] != ORDINARY_SALARY:
            raise MXBlock("MX_SBC_FIXED_RULE_MISSING",
                          f"earning {line['code']} is a FIXED SBC item — its integration rule (S10) is not transcribed")
    integ = integration_factor(policy, service_year(seniority_date, on))
    fixed = salary * integ["factor"]
    variable = variable_daily(accumulator)
    raw = fixed + variable["daily"]
    if zone not in ("GENERAL", "ZLFN"):
        raise MXBlock("MX_MIN_WAGE_ZONE_UNRESOLVED", "the employee's minimum-wage zone is not resolved")
    out = []
    for seg in segments:
        c = seg.content
        rule = _floor_rule(c)
        floor = c.min_wage(zone)
        sbc, floored = raw, False
        if raw < floor:
            if rule is None:
                raise MXBlock("MX_SBC_MIN_RULE_MISSING",
                              "the SBC is below the zone minimum wage and the SBC floor rule is not transcribed (S10, Q5)")
            if rule == "BLOCK_BELOW_ZONE_MIN_WAGE":
                raise MXBlock("MX_SBC_BELOW_MINIMUM", "the SBC is below the zone minimum wage")
            sbc, floored = floor, True
        uma_daily = c.amount("mx_uma_daily")
        cap = c.amount("mx_sbc_max_uma_multiple") * uma_daily
        capped = sbc > cap
        out.append({"start": seg.start, "end": seg.end, "days": seg.days, "sbc": cap if capped else sbc,
                    "uma_daily": uma_daily, "cap": cap, "capped": capped, "floor": floor, "floored": floored,
                    "content": c})
    return {"components": {"daily_salary": salary, **integ, "fixed": fixed,
                           "variable_daily": variable["daily"], "variable_total": variable["total"],
                           "variable_days": variable["days"], "uncapped": raw},
            "segments": out}
