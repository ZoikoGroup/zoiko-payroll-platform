"""
engine/jurisdictions/mexico/entitlements.py
-------------------------------------------
Statutory vs employer-enhanced benefit entitlements (spec §17, MX-051),
reported separately in the trace for Phase 9 (aguinaldo, vacation, vacation
premium). No special-pay withholding happens here (Q8). A policy below a
statutory floor BLOCKS.
"""

from __future__ import annotations

from decimal import Decimal

from .errors import MXBlock
from .sbc import _dec, policy_vacation_days

_HUNDRED = Decimal("100")


def _pair(name, statutory, employer, unit, daily_salary=None):
    if employer < statutory:
        raise MXBlock("MX_LABOR_POLICY_BELOW_FLOOR", f"the labour policy's {name} is below the statutory minimum")
    out = {"concept": name, "unit": unit, "statutory": statutory, "employer": employer,
           "enhancement": employer - statutory}
    if daily_salary is not None:
        out["statutory_amount"] = statutory * daily_salary
        out["employer_amount"] = employer * daily_salary
    return out


def entitlements(content, policy: dict, service_year: int, daily_salary: Decimal) -> list:
    aguinaldo = _pair("aguinaldo days", content.amount("mx_aguinaldo_min_days"),
                      _dec(policy.get("aguinaldo_days"), "labour-policy aguinaldo days"), "days", daily_salary)
    vacation = _pair("vacation days", content.vacation_days(service_year),
                     policy_vacation_days(policy, service_year), "days", daily_salary)
    premium = _pair("vacation premium %", content.pct("mx_vacation_premium_min_pct") * _HUNDRED,
                    _dec(policy.get("vacation_premium_pct"), "labour-policy vacation premium %"), "%")
    premium["statutory_amount"] = vacation["statutory_amount"] * premium["statutory"] / _HUNDRED
    premium["employer_amount"] = vacation["employer_amount"] * premium["employer"] / _HUNDRED
    return [aguinaldo, vacation, premium]
