"""
engine/jurisdictions/netherlands/vcr.py
--------------------------------------
Voortschrijdend Cumulatief Rekenen (VCR) — pure cumulative calculation primitive
(ZP-NL-ENG-001 NL-012..NL-014, NL-020, NL-045, NL-046).

Core formula (spec §5):
  cumulative_base = min(cumulative_wage, cumulative_period_maxima)
  base_increment  = cumulative_base_now − cumulative_base_before

This naturally handles:
  - catch-up (F3): excess from earlier period becomes contributable when
    cumulative max grows in a later period
  - annual ceiling: cumulative_base stops growing when cumulative_wage ≥ cumulative_max
  - negative wages: base_increment can be negative
  - mid-year starts: cumulative_max accumulates from first period present
  - separate Zvw series: ZVW_LEVY (employer) and ZVW_CONTRIB (employee) are
    independent families (NL-020)

The state is immutable; the service persists each committed step as a new
payroll_nl_vcr_snapshots row (insert-only, NL-045) whose `revision` is the
optimistic-concurrency token (NL-046). Nothing here touches the database.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping, Optional


class VcrError(Exception):
    """VCR calculation error."""


class VcrFamily:
    """Series discriminators — the CHECK-constrained values of payroll_nl_vcr_snapshots.family."""
    EI = "EI"                    # employee insurance: AWf, Aof, Wko, Whk share one base
    ZVW_LEVY = "ZVW_LEVY"        # Zvw employer levy (own series, NL-020)
    ZVW_CONTRIB = "ZVW_CONTRIB"  # Zvw employee contribution (own series, NL-020)
    ALL = (EI, ZVW_LEVY, ZVW_CONTRIB)


def family_for_premium(premium: str) -> str:
    """Map a premium code to its VCR family."""
    if premium in ("awf", "aof", "wko", "whk"):
        return VcrFamily.EI
    if premium == "zvw_employer":
        return VcrFamily.ZVW_LEVY
    if premium == "zvw_employee":
        return VcrFamily.ZVW_CONTRIB
    raise ValueError(f"Unknown premium for VCR family: {premium}")


def round_currency(amount: Decimal) -> Decimal:
    """Dutch payroll rounding: half-up to cents."""
    return Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class VcrState:
    """Cumulative state of one series after `period_count` committed periods.
    `revision` is 0 for a series with no committed snapshot yet."""
    period_count: int
    cumulative_wage: Decimal
    cumulative_max: Decimal
    cumulative_base: Decimal
    revision: int = 0

    def as_dict(self) -> dict:
        return {
            "period_count": self.period_count,
            "cumulative_wage": str(self.cumulative_wage),
            "cumulative_max": str(self.cumulative_max),
            "cumulative_base": str(self.cumulative_base),
            "revision": self.revision,
        }


@dataclass(frozen=True)
class VcrInput:
    period_wage: Decimal
    period_max: Decimal
    income_relationship_id: Optional[int] = None


@dataclass(frozen=True)
class VcrResult:
    new_state: VcrState
    base_increment: Decimal
    period_wage: Decimal
    period_max: Decimal


def initial_state() -> VcrState:
    return VcrState(period_count=0, cumulative_wage=Decimal("0"), cumulative_max=Decimal("0"),
                    cumulative_base=Decimal("0"), revision=0)


def state_from_dict(data: Optional[Mapping[str, Any]]) -> VcrState:
    """Rebuild a state from a snapshot row / frozen-context dict; None = first period."""
    if not data:
        return initial_state()
    return VcrState(
        period_count=int(data.get("period_count") or 0),
        cumulative_wage=Decimal(str(data.get("cumulative_wage") or "0")),
        cumulative_max=Decimal(str(data.get("cumulative_max") or "0")),
        cumulative_base=Decimal(str(data.get("cumulative_base") or "0")),
        revision=int(data.get("revision") or 0),
    )


def advance(state: VcrState, inp: VcrInput) -> VcrResult:
    """Advance one series by one period. The new state's revision is
    state.revision + 1 — the revision the committed snapshot row will carry."""
    wage = Decimal(inp.period_wage if inp.period_wage is not None else 0)
    maximum = Decimal(inp.period_max if inp.period_max is not None else 0)
    if maximum < 0:
        raise VcrError(f"period maximum cannot be negative (got {maximum})")
    cumulative_wage = state.cumulative_wage + wage
    cumulative_max = state.cumulative_max + maximum
    cumulative_base = min(cumulative_wage, cumulative_max)
    new_state = VcrState(
        period_count=state.period_count + 1,
        cumulative_wage=cumulative_wage,
        cumulative_max=cumulative_max,
        cumulative_base=cumulative_base,
        revision=state.revision + 1,
    )
    return VcrResult(new_state=new_state, base_increment=cumulative_base - state.cumulative_base,
                     period_wage=wage, period_max=maximum)


def advance_batch(state: VcrState, inputs: list[VcrInput]) -> tuple[VcrState, list[VcrResult]]:
    results = []
    current = state
    for inp in inputs:
        res = advance(current, inp)
        results.append(res)
        current = res.new_state
    return current, results


def ensure_expected_revision(current_revision: int, expected_revision: int) -> None:
    """Optimistic-concurrency guard (NL-046): the series must not have moved
    since the payslip was calculated."""
    if current_revision != expected_revision:
        raise VcrError(
            f"stale VCR snapshot: calculated against revision {expected_revision}, "
            f"current committed revision is {current_revision} — recalculate before committing"
        )


__all__ = [
    "VcrError", "VcrFamily", "family_for_premium", "round_currency",
    "VcrState", "VcrInput", "VcrResult",
    "initial_state", "state_from_dict", "advance", "advance_batch", "ensure_expected_revision",
]
