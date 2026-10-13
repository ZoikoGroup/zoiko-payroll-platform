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

Immutable insert-only snapshots (NL-045): each period creates a new row;
revision + previous_snapshot_id give full lineage. Optimistic concurrency
via unique (org, employee, IKV, year, family, revision) prevents stale
commits (NL-046).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Tuple


class VcrError(Exception):
    """VCR calculation error."""


class NLBlock(VcrError):
    """Explicit block: required table data missing (do not invent)."""


class NLError(VcrError):
    """Netherlands-specific calculation error."""


@dataclass(frozen=True)
class VcrKey:
    """Key identifying a VCR series (NL-013)."""
    employer_entity_id: int
    employee_id: int
    year: int
    family: str  # VcrFamily.EI / ZVW_LEVY / ZVW_CONTRIB

    def series_key(self) -> Tuple[int, int, int, str]:
        return (self.employer_entity_id, self.employee_id, self.year, self.family)


@dataclass(frozen=True)
class VcrSnapshot:
    """Immutable cumulative snapshot (NL-012, NL-045)."""
    key: VcrKey
    period_count: int = 0
    cumulative_wage: Decimal = Decimal("0")
    cumulative_maximum: Decimal = Decimal("0")
    cumulative_base: Decimal = Decimal("0")
    revision: int = 0
    last_income_relationship_id: Optional[int] = None

    def base_remaining(self) -> Decimal:
        """Premium space not yet consumed: cumulative_maximum - cumulative_base."""
        return self.cumulative_maximum - self.cumulative_base

    def is_zero(self) -> bool:
        return (self.period_count == 0 and self.cumulative_wage == 0
                and self.cumulative_maximum == 0 and self.cumulative_base == 0 and self.revision == 0)


@dataclass(frozen=True)
class VcrIncrement:
    """Result of advancing one period."""
    snapshot: VcrSnapshot
    base_increment: Decimal
    period_wage: Decimal
    period_maximum: Decimal

    def premium_for(self, rate_pct: Decimal) -> Decimal:
        """Premium for this increment at rate_pct (e.g., 6.10), rounded half-up."""
        return round_currency(self.base_increment * rate_pct / Decimal("100"))


def round_currency(amount: Decimal) -> Decimal:
    """Dutch payroll rounding: half-up to cents."""
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def zero_snapshot(key: VcrKey) -> VcrSnapshot:
    return VcrSnapshot(key=key)


def advance(snapshot: VcrSnapshot, *, period_wage: Decimal, period_maximum: Decimal,
            income_relationship_id: Optional[int] = None) -> VcrIncrement:
    """Advance `snapshot` by one period and return a NEW immutable snapshot."""
    wage = Decimal(period_wage if period_wage is not None else 0)
    maximum = Decimal(period_maximum if period_maximum is not None else 0)
    if maximum < 0:
        raise VcrError(f"period maximum cannot be negative (got {maximum})")

    cumulative_wage = snapshot.cumulative_wage + wage
    cumulative_maximum = snapshot.cumulative_maximum + maximum
    cumulative_base = min(cumulative_wage, cumulative_maximum)
    base_increment = cumulative_base - snapshot.cumulative_base

    new_snapshot = replace(
        snapshot,
        period_count=snapshot.period_count + 1,
        cumulative_wage=cumulative_wage,
        cumulative_maximum=cumulative_maximum,
        cumulative_base=cumulative_base,
        revision=snapshot.revision + 1,
        last_income_relationship_id=(
            income_relationship_id if income_relationship_id is not None
            else snapshot.last_income_relationship_id
        ),
    )
    return VcrIncrement(snapshot=new_snapshot, base_increment=base_increment,
                        period_wage=wage, period_maximum=maximum)


def ensure_expected_revision(snapshot: VcrSnapshot, expected_revision: int) -> None:
    """Optimistic-concurrency guard (NL-046)."""
    if snapshot.revision != expected_revision:
        raise VcrError(
            f"stale VCR snapshot: expected revision {expected_revision}, "
            f"current revision {snapshot.revision} — reload and recompute"
        )


# Family discriminators used in the DB snapshot rows
class VcrFamily:
    EI = "EI"              # Employee insurance: AWf, Aof, Wko (combined)
    ZVW_LEVY = "ZVW_LEVY"  # Zvw employer levy (income-dependent, separate series)
    ZVW_CONTRIB = "ZVW_CONTRIB"  # Zvw employee contribution (income-dependent, separate series)


def family_for_premium(premium: str) -> str:
    """Map a premium code to its VCR family."""
    if premium in ("awf", "aof", "wko"):
        return VcrFamily.EI
    if premium == "zvw_employer":
        return VcrFamily.ZVW_LEVY
    if premium == "zvw_employee":
        return VcrFamily.ZVW_CONTRIB
    raise ValueError(f"Unknown premium for VCR family: {premium}")


__all__ = [
    "VcrError", "NLBlock", "NLError",
    "VcrKey", "VcrSnapshot", "VcrIncrement",
    "round_currency", "zero_snapshot", "advance", "ensure_expected_revision",
    "VcrFamily", "family_for_premium",
    # Backwards compatibility (used by premiums.py and tests)
    "VcrState", "VcrInput", "VcrResult", "initial_state", "advance_batch",
]


# --- Backwards-compatible aliases for premiums.py and existing tests ---
# These mirror the old API used by premiums.py and test_netherlands_vcr.py

@dataclass(frozen=True)
class VcrState:
    """Backwards-compatible VCR state (old API)."""
    period_count: int
    cumulative_wage: Decimal
    cumulative_max: Decimal
    cumulative_base: Decimal


@dataclass(frozen=True)
class VcrInput:
    """Backwards-compatible VCR input (old API)."""
    period_wage: Decimal
    period_max: Decimal
    income_relationship_id: Optional[int] = None


@dataclass(frozen=True)
class VcrResult:
    """Backwards-compatible VCR result (old API)."""
    new_state: VcrState
    base_increment: Decimal
    period_wage: Decimal
    period_max: Decimal


def initial_state() -> VcrState:
    """Backwards-compatible initial state."""
    return VcrState(
        period_count=0,
        cumulative_wage=Decimal("0"),
        cumulative_max=Decimal("0"),
        cumulative_base=Decimal("0"),
    )


def advance(state: VcrState, inp: VcrInput) -> VcrResult:
    """Backwards-compatible advance function (old API)."""
    new_cumulative_wage = state.cumulative_wage + inp.period_wage
    new_cumulative_max = state.cumulative_max + inp.period_max
    new_cumulative_base = min(new_cumulative_wage, new_cumulative_max)
    base_increment = new_cumulative_base - state.cumulative_base

    new_state = VcrState(
        period_count=state.period_count + 1,
        cumulative_wage=new_cumulative_wage,
        cumulative_max=new_cumulative_max,
        cumulative_base=new_cumulative_base,
    )
    return VcrResult(
        new_state=new_state,
        base_increment=base_increment,
        period_wage=inp.period_wage,
        period_max=inp.period_max,
    )


def advance_batch(state: VcrState, inputs: list[VcrInput]) -> tuple[VcrState, list[VcrResult]]:
    """Backwards-compatible batch advance."""
    results = []
    current = state
    for inp in inputs:
        res = advance(current, inp)
        results.append(res)
        current = res.new_state
    return current, results