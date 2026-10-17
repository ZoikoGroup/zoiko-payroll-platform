"""
engine/jurisdictions/mexico/isr.py
----------------------------------
Ordinary ISR withholding (spec §4, MX-008): from the payment period's
Art. 96 tariff in force on the pay date,

    ISR = fixed quota + (taxable base − lower limit) × marginal rate

The bracket is the one with the greatest lower limit not above the base; the
tariff's own top bracket must be open-ended. Every figure comes from the
tariff rows — none is typed here.
"""

from __future__ import annotations

from decimal import Decimal

from .errors import MXBlock

_ZERO = Decimal("0")


def bracket_for(base: Decimal, brackets: list) -> dict:
    if not brackets:
        raise MXBlock("MX_CONTENT_MISSING", "the ISR tariff has no brackets")
    if brackets[-1]["upper"] is not None and base > brackets[-1]["upper"]:
        raise MXBlock("MX_CONTENT_INVALID", "the ISR tariff's top bracket is not open-ended and the base is above it")
    chosen = None
    for b in brackets:
        if b["lower"] <= base:
            chosen = b
    if chosen is None:
        raise MXBlock("MX_ISR_BELOW_TARIFF", f"taxable base {base} is below the tariff's first lower limit")
    return chosen


def withholding(base: Decimal, brackets: list) -> dict:
    """{isr, bracket} at full precision — rounding is the caller's (rounding.py)."""
    if base < 0:
        raise MXBlock("MX_EARNING_INVALID", "the ISR base is negative")
    if base == 0:
        return {"isr": _ZERO, "bracket": None, "base": base}
    b = bracket_for(base, brackets)
    isr = b["fixed"] + (base - b["lower"]) * b["rate"]
    return {"isr": isr, "base": base,
            "bracket": {"lower": b["lower"], "upper": b["upper"], "fixed": b["fixed"], "rate_pct": b["rate_pct"]}}
