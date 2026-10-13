"""
engine/jurisdictions/netherlands/sickness_pay.py
------------------------------------------------
Wage continuation during sickness — ZP-NL-ENG-001 §14, NL-042.

The employer generally continues pay for up to two years at no less than the
statutory percentage (pack: nl_sick_pay_pct, 70.00), with a minimum-wage
floor in the first year for ordinary cases. NL-042: the percentage, waiting
days and CAO enhancements are an effective-dated EMPLOYER POLICY layered over
that floor (payroll_nl_absence_pay_policies) — never one hard-coded 70%.

This module computes the floor the period's pay must meet; the payroll engine
compares the actual pay with it and raises a BLOCK exception when the pay is
below the floor (it never silently rewrites the operator's pay).
Pure: no ORM, no framework.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping, Optional


class SicknessPayError(Exception):
    """Policy or statutory parameter missing — the caller blocks."""


@dataclass(frozen=True)
class SicknessFloor:
    sickness_year: int          # 1 or 2 (0 = beyond the statutory period)
    pct: Decimal
    pct_floor: Decimal          # pct × contractual wage
    min_wage_floor: Decimal     # year-1 minimum-wage floor (0 when not applicable)
    floor: Decimal

    def as_dict(self) -> dict:
        return {"sicknessYear": self.sickness_year, "pct": str(self.pct), "pctFloor": str(self.pct_floor),
                "minWageFloor": str(self.min_wage_floor), "floor": str(self.floor)}


def _q(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def sickness_year(first_sick_day: date, on: date) -> int:
    days = (on - first_sick_day).days
    if days < 0:
        return 0
    if days < 365:
        return 1
    if days < 730:
        return 2
    return 0


def floor(*, policy: Mapping[str, Any], statutory_pct: Optional[Decimal], first_sick_day: date, on: date,
          contractual_wage: Decimal, min_wage_period: Optional[Decimal]) -> Optional[SicknessFloor]:
    """The minimum pay for a period in which the employee is sick, or None
    when the statutory continuation period has ended."""
    if statutory_pct is None:
        raise SicknessPayError("statutory sick-pay % not configured in the active pack (nl_sick_pay_pct)")
    year = sickness_year(first_sick_day, on)
    if year == 0:
        return None
    statutory = Decimal(str(statutory_pct))
    pct = Decimal(str(policy.get("year1_pct" if year == 1 else "year2_pct")))
    topups = policy.get("cao_enhancements") or {}
    pct += Decimal(str(topups.get("year1_pct_topup" if year == 1 else "year2_pct_topup", 0)))
    if pct < statutory:
        raise SicknessPayError(f"employer sick-pay policy {pct}% is below the statutory {statutory}% (NL-042)")
    pct_floor = _q(Decimal(contractual_wage) * pct / Decimal("100"))
    mw_floor = Decimal("0.00")
    if year == 1 and policy.get("year1_min_wage_floor"):
        if min_wage_period is None:
            raise SicknessPayError("first-year minimum-wage floor needs the period's statutory minimum wage")
        mw_floor = _q(Decimal(min_wage_period))
    return SicknessFloor(sickness_year=year, pct=pct, pct_floor=pct_floor, min_wage_floor=mw_floor,
                         floor=max(pct_floor, mw_floor))


__all__ = ["SicknessPayError", "SicknessFloor", "sickness_year", "floor"]
