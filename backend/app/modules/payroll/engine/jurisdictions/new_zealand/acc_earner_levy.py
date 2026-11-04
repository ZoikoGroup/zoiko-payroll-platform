"""ACC earner levy (spec §6, NZ-013).

The levy is collected through PAYE but traced separately. Its annual cap is
tested against a replayable year-to-date accumulator (employee + legal
employer + tax year), so several pay groups never grant several caps. A
missing accumulator blocks: "no earnings yet" must be an explicit zero.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from decimal import Decimal

from . import errors as E
from .pack import HUNDRED, ZERO, NzPack, dec, money

OBLIGATION = "ACC_LIABLE_EARNINGS"


@dataclass
class AccResult:
    liable: Decimal
    levy: Decimal
    cap: Decimal
    ytd_before: Decimal
    ytd_after: Decimal
    cap_crossed: bool
    cap_reached_before: bool
    steps: list = dc_field(default_factory=list)


def calculate_levy(acc_base: Decimal, accumulators, pack: NzPack) -> AccResult:
    if not accumulators or OBLIGATION not in accumulators or accumulators[OBLIGATION] is None:
        pack.block(E.ACC_ACCUMULATOR_MISSING, "the year-to-date ACC liable earnings are not known")
    ytd = dec(accumulators[OBLIGATION])
    cap = pack.amount("nz_acc_max_liable_earnings")
    liable = min(acc_base, max(cap - ytd, ZERO))
    levy = pack.rounder("nz_acc_rounding")(liable * pack.pct("nz_acc_earner_levy_rate") / HUNDRED)
    steps = [{"step": "ytdBefore", "value": money(ytd), "note": None},
             {"step": "cap", "value": money(cap), "note": None},
             {"step": "liable", "value": money(liable), "note": f"of {money(acc_base)}"},
             {"step": "levy", "value": money(levy), "note": None}]
    return AccResult(liable, levy, cap, ytd, ytd + liable, ytd < cap < ytd + acc_base, ytd >= cap, steps)
