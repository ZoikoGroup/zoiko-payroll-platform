"""Strict readers for UAE pack values (ZP-AE-ENG-001).

Every statutory value comes from the AE canonical pack rows in ``rate_map``
(component_key -> ContributionRate). A missing row or field raises
AECalculationBlockedError(AE_RATE_MISSING:<key>) — there is no default and no
hardcoded fallback. Percentages are fractions (0.11 = 11%).
"""
from decimal import Decimal

from app.modules.payroll.engine.jurisdictions.uae import errors as E


def _missing(key: str, what: str):
    return E.AECalculationBlockedError(
        E.keyed(E.RATE_MISSING, key),
        f"'{key}' ({what}) is not configured in the active United Arab Emirates pack — "
        "add it in Super Admin → Compliance → United Arab Emirates → Contribution Rates.")


def has(rate_map: dict, key: str) -> bool:
    return (rate_map or {}).get(key) is not None


def pct(rate_map: dict, key: str, side: str) -> Decimal:
    row = (rate_map or {}).get(key)
    value = getattr(row, f"{side}_rate_pct", None) if row is not None else None
    if value is None:
        raise _missing(key, f"{side} percentage")
    return Decimal(str(value))


def amount(rate_map: dict, key: str) -> Decimal:
    row = (rate_map or {}).get(key)
    value = getattr(row, "flat_amount", None) if row is not None else None
    if value is None:
        raise _missing(key, "amount")
    return Decimal(str(value))


def optional_amount(rate_map: dict, key: str):
    row = (rate_map or {}).get(key)
    value = getattr(row, "flat_amount", None) if row is not None else None
    return Decimal(str(value)) if value is not None else None
