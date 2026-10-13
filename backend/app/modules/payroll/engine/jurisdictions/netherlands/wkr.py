"""
engine/jurisdictions/netherlands/wkr.py
---------------------------------------
Werkkostenregeling (WKR) — ZP-NL-ENG-001 §8, NL-022/NL-023.

WKR is an EMPLOYER-level annual accumulator layered over payroll:
  free space   = band1% × fiscal wage up to the band boundary
               + band2% × fiscal wage above it        (pack NL_WKR_BAND rows)
  excess       = designated final-levy wage − free space   (never negative)
  excess levy  = levy% × excess                          (80% in 2026)
Targeted exemptions are tracked OUTSIDE free-space consumption.

Per payslip the engine only reports the employee's contribution (fiscal wage,
designated final-levy items, targeted exemptions — from each earning code's
wkr_treatment, never from a label, NL-022). The employer accumulator is
advanced once per committed run (insert-only revisions); the levy itself is
settled annually. Pure: no ORM, no framework.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Mapping, Optional

NL_WKR_BAND_RULE = "NL_WKR_BAND"
TREATMENTS = ("WAGE", "TARGETED_EXEMPTION", "ZERO_VALUATION", "FINAL_LEVY_DESIGNATED", "N_A")


class WkrError(Exception):
    pass


def _q(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class WkrState:
    fiscal_wage_cumulative: Decimal = Decimal("0")
    designated_wage_cumulative: Decimal = Decimal("0")
    targeted_exemptions_cumulative: Decimal = Decimal("0")
    revision: int = 0


@dataclass(frozen=True)
class WkrPosition:
    state: WkrState
    free_space_available: Decimal
    excess_amount: Decimal
    excess_levy: Decimal

    def as_dict(self) -> dict:
        return {"fiscalWageCumulative": str(self.state.fiscal_wage_cumulative),
                "designatedWageCumulative": str(self.state.designated_wage_cumulative),
                "targetedExemptionsCumulative": str(self.state.targeted_exemptions_cumulative),
                "freeSpaceAvailable": str(self.free_space_available), "excessAmount": str(self.excess_amount),
                "excessLevy": str(self.excess_levy), "revision": self.state.revision}


def payslip_components(earnings: Mapping[str, Decimal], classifications: Mapping[str, Mapping[str, Any]],
                       fiscal_wage: Decimal) -> dict:
    """One payslip's contribution to the employer's WKR accumulator."""
    designated = Decimal("0")
    targeted = Decimal("0")
    for code, amount in earnings.items():
        treatment = (classifications.get(code) or {}).get("wkr_treatment")
        if treatment not in TREATMENTS:
            raise WkrError(f"earning {code!r} has no WKR treatment (NL-022)")
        if treatment == "FINAL_LEVY_DESIGNATED":
            designated += Decimal(str(amount))
        elif treatment == "TARGETED_EXEMPTION":
            targeted += Decimal(str(amount))
    return {"fiscalWage": str(_q(Decimal(fiscal_wage))), "designated": str(_q(designated)),
            "targetedExemptions": str(_q(targeted))}


def _bands(slabs: Iterable[Any]):
    free = sorted([s for s in slabs or () if getattr(s, "rule_type", None) == NL_WKR_BAND_RULE
                   and getattr(s, "filing_status", None) == "FREE_SPACE"],
                  key=lambda s: Decimal(str(s.min_amount or 0)))
    levy = [s for s in slabs or () if getattr(s, "rule_type", None) == NL_WKR_BAND_RULE
            and getattr(s, "filing_status", None) == "EXCESS_LEVY"]
    if not free or not levy:
        raise WkrError("NL_WKR_BAND free-space / excess-levy rows not configured in the active pack")
    return free, Decimal(str(levy[0].rate_pct))


def free_space(fiscal_wage: Decimal, slabs: Iterable[Any]) -> Decimal:
    bands, _ = _bands(slabs)
    total = Decimal("0")
    for band in bands:
        lo = Decimal(str(band.min_amount or 0))
        hi = None if band.max_amount is None else Decimal(str(band.max_amount))
        portion = max(min(fiscal_wage, hi) - lo, Decimal("0")) if hi is not None else max(fiscal_wage - lo, Decimal("0"))
        total += portion * Decimal(str(band.rate_pct)) / Decimal("100")
    return _q(total)


def advance(state: WkrState, *, fiscal_wage: Decimal, designated: Decimal, targeted: Decimal,
            slabs: Iterable[Any]) -> WkrPosition:
    new = WkrState(
        fiscal_wage_cumulative=state.fiscal_wage_cumulative + Decimal(fiscal_wage),
        designated_wage_cumulative=state.designated_wage_cumulative + Decimal(designated),
        targeted_exemptions_cumulative=state.targeted_exemptions_cumulative + Decimal(targeted),
        revision=state.revision + 1,
    )
    space = free_space(new.fiscal_wage_cumulative, slabs)
    _, levy_pct = _bands(slabs)
    excess = max(new.designated_wage_cumulative - space, Decimal("0"))
    return WkrPosition(state=new, free_space_available=space, excess_amount=_q(excess),
                       excess_levy=_q(excess * levy_pct / Decimal("100")))


__all__ = ["WkrError", "WkrState", "WkrPosition", "payslip_components", "free_space", "advance",
           "NL_WKR_BAND_RULE", "TREATMENTS"]
