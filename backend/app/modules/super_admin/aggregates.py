"""
super_admin/aggregates.py
-------------------------
Central small-cohort suppression and differencing defence for every
cross-tenant aggregate the platform plane can see (ZP-PRIV A06 / B.2).

Nothing here returns an identity. It exists so a Super Admin can read
operational totals without the totals themselves becoming a way to single
out one worker or expose one tenant's payroll.

Four layers:

1. Primary suppression. A cell whose worker cohort is below k (5, decision 1)
   is never returned as a number; it becomes ``SUPPRESSED`` ("<5, hidden").
   Money cells additionally need at least ``MIN_ORG_COHORT`` organizations,
   so a "jurisdiction x month" cell can never be one tenant's payroll total.

2. Complementary suppression (``suppress_group``). When sibling cells sum to
   a total that is disclosed elsewhere, hiding one cell is not enough: the
   total minus the visible siblings gives it back. If any sibling is hidden,
   more siblings are hidden (smallest first) until the hidden ones together
   cover at least k workers.

3. Result-based differencing guard (``guard_cohort``). Two queries whose
   filter sets are nested (one adds a predicate to the other) and whose
   cohorts differ by 1..k-1 workers isolate that handful of people. The
   second such query is refused (403 AGGREGATE_DIFFERENCING_DETECTED) and
   the refusal is audited by the caller's exception handler.

4. Query budget (``guard_aggregate_request``): at most ``BUDGET_MAX`` aggregate
   reads per principal per window (429), so differencing cannot be brute-
   forced across many windows' worth of filter combinations.

The probing ledger is per process. Workers behind a load balancer each keep
their own ledger; the budget is therefore per worker, which still bounds a
principal to BUDGET_MAX x workers per window — recorded as a residual risk in
docs/privacy/control_register.yaml (A06).
"""

from __future__ import annotations

import threading
import time
from typing import Dict, FrozenSet, Iterable, Optional, Sequence

from app.core.exceptions import ZoikoException

# ── Suppression ──────────────────────────────────────────────────────────────

MIN_COHORT = 5  # decision 1: suppression k = 5 (venu@zoikogroup.com, 2026-10-15)
MIN_ORG_COHORT = 2  # a money cell must span at least two organizations
SUPPRESSED = "<5, hidden"


def is_suppressed(cohort: Optional[int]) -> bool:
    """A cell is suppressed when its cohort is unknown or below k."""
    try:
        return int(cohort) < MIN_COHORT  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return True


def suppress(value, cohort: Optional[int]):
    """Return ``value`` unless its cohort is below k, then the hidden token."""
    return SUPPRESSED if is_suppressed(cohort) else value


def suppress_row(row: dict, cohort: Optional[int], keys: Iterable[str]) -> dict:
    """In-place suppress the named money/count keys when the cohort is small."""
    if is_suppressed(cohort):
        for key in keys:
            if key in row:
                row[key] = SUPPRESSED
    return row


def suppress_money_row(row: dict, workers: Optional[int], organizations: Optional[int],
                       keys: Iterable[str]) -> dict:
    """Money needs >= k workers AND >= MIN_ORG_COHORT organizations."""
    try:
        too_few_orgs = int(organizations) < MIN_ORG_COHORT  # type: ignore[arg-type]
    except (TypeError, ValueError):
        too_few_orgs = True
    if is_suppressed(workers) or too_few_orgs:
        for key in keys:
            if key in row:
                row[key] = SUPPRESSED
    return row


def cohort_bucket(cohort: Optional[int]) -> str:
    """A label safe to show instead of an exact small headcount."""
    if is_suppressed(cohort):
        return SUPPRESSED
    return str(int(cohort))


def suppress_group(cells: Sequence[dict], cohort_key: str, keys: Iterable[str]) -> None:
    """Primary + complementary suppression over sibling cells (in place).

    ``cohort_key`` names each cell's worker count (read BEFORE suppression).
    After the call no hidden cell can be recovered as (disclosed total -
    visible siblings): the hidden cells together hold at least k workers,
    or every cell is hidden."""
    keys = tuple(keys)
    counts = []
    for cell in cells:
        try:
            counts.append(int(cell.get(cohort_key) or 0))
        except (TypeError, ValueError):
            counts.append(0)
    hidden = {i for i, c in enumerate(counts) if c < MIN_COHORT}
    if hidden:
        visible = sorted((i for i in range(len(cells)) if i not in hidden), key=lambda i: counts[i])
        while visible and (len(hidden) < 2 or sum(counts[i] for i in hidden) < MIN_COHORT):
            hidden.add(visible.pop(0))
    for i in hidden:
        for key in (cohort_key, *keys):
            if key in cells[i]:
                cells[i][key] = SUPPRESSED


# ── Probing guards ───────────────────────────────────────────────────────────

BUDGET_MAX = 60                 # aggregate reads per principal per window
BUDGET_WINDOW_SECONDS = 300     # 5 minutes
COHORT_MEMORY = 200             # recent (view, filters, cohort) per principal

_lock = threading.Lock()
_state: Dict[int, dict] = {}


class AggregateQueryBudgetExceeded(ZoikoException):
    """429: too many aggregate reads by one principal in one window."""

    def __init__(self) -> None:
        super().__init__(
            status_code=429,
            error_code="AGGREGATE_QUERY_BUDGET_EXCEEDED",
            message="Too many aggregate queries in a short window. Please slow down.",
        )


class AggregateDifferencingDetected(ZoikoException):
    """403: overlapping aggregate filters refused to protect small cohorts."""

    def __init__(self) -> None:
        super().__init__(
            status_code=403,
            error_code="AGGREGATE_DIFFERENCING_DETECTED",
            message="Overlapping aggregate queries were refused to protect small cohorts.",
        )


def _signature(filters: dict) -> FrozenSet[tuple]:
    return frozenset((str(k), str(v)) for k, v in filters.items() if v not in (None, ""))


def _entry(principal_id: int) -> dict:
    bucket = int(time.monotonic() // BUDGET_WINDOW_SECONDS)
    entry = _state.get(principal_id)
    if entry is None or entry["bucket"] != bucket:
        cohorts = entry["cohorts"] if entry else []
        entry = {"bucket": bucket, "count": 0, "cohorts": cohorts}
        _state[principal_id] = entry
    return entry


def guard_aggregate_request(principal_id: Optional[int], filters: Optional[dict] = None) -> None:
    """Count one aggregate read against the principal's budget (429 when
    exceeded). Unknown principals never reach a platform aggregate route:
    the PDP denies them first."""
    if principal_id is None:
        return
    with _lock:
        entry = _entry(principal_id)
        entry["count"] += 1
        if entry["count"] > BUDGET_MAX:
            raise AggregateQueryBudgetExceeded()


def guard_cohort(principal_id: Optional[int], view: str, filters: Optional[dict],
                 cohort: Optional[int]) -> None:
    """Refuse a query whose cohort differs by 1..k-1 workers from an earlier
    query of the same view with a nested filter set (the classic two-query
    isolation attack). Records the query when it is allowed."""
    if principal_id is None or cohort is None:
        return
    sig = _signature(filters or {})
    cohort = int(cohort)
    with _lock:
        entry = _entry(principal_id)
        for prev_view, prev_sig, prev_cohort in entry["cohorts"]:
            if prev_view != view or prev_sig == sig:
                continue
            nested = prev_sig < sig or sig < prev_sig
            if nested and 0 < abs(prev_cohort - cohort) < MIN_COHORT:
                raise AggregateDifferencingDetected()
        entry["cohorts"].append((view, sig, cohort))
        del entry["cohorts"][:-COHORT_MEMORY]


def reset_guard_state() -> None:
    """Test hook: clear the in-process probing ledger."""
    with _lock:
        _state.clear()
