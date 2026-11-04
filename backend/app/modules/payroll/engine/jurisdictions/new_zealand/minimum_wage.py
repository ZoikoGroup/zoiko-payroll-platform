"""Minimum-wage test (spec §7, NZ-015).

It reports PASS / FAIL / UNDETERMINABLE and never changes pay: a FAIL or an
UNDETERMINABLE result is an exception that stops run approval (Phase 4), not a
calculation block. The category is the evidence-backed one recorded on the
tax profile, never inferred from age or pay rate; without paid hours the
result is UNDETERMINABLE, never "pass".
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from decimal import Decimal
from typing import Optional

from . import errors as E
from .pack import ZERO, NzPack, dec, money, upper

FLOOR_KEY = {"ADULT": "nz_min_wage_adult", "STARTING_OUT": "nz_min_wage_starting_out",
             "TRAINING": "nz_min_wage_training"}
PASS, FAIL, UNDETERMINABLE = "PASS", "FAIL", "UNDETERMINABLE"


@dataclass
class MinWageResult:
    status: str
    reason: Optional[str] = None
    effective_rate: Optional[Decimal] = None
    floor: Optional[Decimal] = None
    shortfall: Optional[Decimal] = None
    category: Optional[str] = None
    hours: Optional[Decimal] = None
    hours_source: Optional[str] = None
    steps: list = dc_field(default_factory=list)


def check_minimum_wage(base: Decimal, hours, hours_source, category, pack: NzPack) -> MinWageResult:
    cat = upper(category) or None
    if cat is None:
        return MinWageResult(UNDETERMINABLE, "no minimum-wage category is recorded", category=cat,
                             hours_source=hours_source)
    if cat not in FLOOR_KEY:
        return MinWageResult(UNDETERMINABLE, f"no signed rule for category {cat}", category=cat,
                             hours_source=hours_source)
    if hours is None or dec(hours) <= ZERO:
        return MinWageResult(UNDETERMINABLE, "paid hours are not known", category=cat, hours_source=hours_source)
    hours = dec(hours)
    floor = pack.amount(FLOOR_KEY[cat])
    effective = base / hours
    steps = [{"step": "effectiveRate", "value": str(effective), "note": f"{money(base)} / {hours} h"},
             {"step": "floor", "value": str(floor), "note": cat}]
    if effective >= floor:
        return MinWageResult(PASS, None, effective, floor, ZERO, cat, hours, hours_source, steps)
    return MinWageResult(FAIL, "effective hourly pay is below the minimum wage", effective, floor,
                         floor * hours - base, cat, hours, hours_source, steps)


def exception_for(result: MinWageResult) -> Optional[dict]:
    if result.status == FAIL:
        return {"code": E.EXC_MIN_WAGE_FAIL, "category": result.category,
                "floor": str(result.floor), "shortfall": money(result.shortfall)}
    if result.status == UNDETERMINABLE:
        return {"code": E.EXC_MIN_WAGE_UNDETERMINABLE, "reason": result.reason}
    return None
