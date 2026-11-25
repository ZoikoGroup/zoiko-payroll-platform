"""Strict readers for Spanish pack values (ZP-ES-ENG-001, docs/spain D3).

Every statutory value comes from the ES canonical pack rows in ``rate_map``
(component_key -> ContributionRate). A missing row or field raises
ESCalculationBlockedError(ES_RATE_MISSING:<key>) — there is no default and no
hardcoded fallback. Percentages are fractions (0.047 = 4.70%).
"""
from decimal import ROUND_HALF_UP, Decimal

from app.modules.payroll.engine.jurisdictions.spain import errors as E

ZERO = Decimal("0")
CENT = Decimal("0.01")


def round2(value) -> Decimal:
    """Half-up to the euro cent, per line (D13)."""
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def _missing(key: str, what: str):
    return E.ESCalculationBlockedError(
        E.keyed(E.RATE_MISSING, key),
        f"'{key}' ({what}) is not configured in the active Spain pack — "
        "add it in Super Admin → Compliance → Spain → Contribution Rates.")


def has(rate_map: dict, key: str) -> bool:
    return (rate_map or {}).get(key) is not None


def pct(rate_map: dict, key: str, side: str) -> Decimal:
    row = (rate_map or {}).get(key)
    value = getattr(row, f"{side}_rate_pct", None) if row is not None else None
    if value is None:
        raise _missing(key, f"{side} percentage")
    return Decimal(str(value))


def pct_or_zero(rate_map: dict, key: str, side: str) -> Decimal:
    """For a side the row legitimately leaves empty (FOGASA has no employee
    share) — the ROW itself must still exist, so a missing family still blocks."""
    row = (rate_map or {}).get(key)
    if row is None:
        raise _missing(key, f"{side} percentage")
    value = getattr(row, f"{side}_rate_pct", None)
    return Decimal(str(value)) if value is not None else ZERO


def amount(rate_map: dict, key: str) -> Decimal:
    row = (rate_map or {}).get(key)
    value = getattr(row, "flat_amount", None) if row is not None else None
    if value is None:
        raise _missing(key, "amount")
    return Decimal(str(value))
