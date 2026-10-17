"""
engine/jurisdictions/mexico/rounding.py
---------------------------------------
The single place Mexican monetary amounts are rounded (Phase 5 Q2). No saved
source states the rule yet, so the mode and quantum come from the national
text row `mx_rounding_rule` ("MODE:QUANTUM", e.g. a mode below and a quantum
like 0.01 — whatever the transcribed source states). Full precision is kept
internally; while the row is missing no amount is emitted.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP, Decimal, InvalidOperation

from .errors import MXBlock

# Vocabulary the transcribed rule may use (names of Decimal modes, no value).
MODES = {"HALF_UP": ROUND_HALF_UP, "HALF_EVEN": ROUND_HALF_EVEN, "DOWN": ROUND_DOWN, "UP": ROUND_UP}


class Rounder:
    def __init__(self, mode: str, quantum: Decimal, text: str):
        self.mode, self.quantum, self.text = mode, quantum, text

    def __call__(self, amount: Decimal) -> Decimal:
        return Decimal(amount).quantize(self.quantum, rounding=MODES[self.mode])


def parse(text: str) -> Rounder:
    mode, sep, quantum = (text or "").strip().partition(":")
    if not sep or mode.strip().upper() not in MODES:
        raise MXBlock("MX_ROUNDING_RULE_INVALID", f"mx_rounding_rule {text!r} is not MODE:QUANTUM with MODE in "
                                                   f"{', '.join(MODES)}")
    try:
        q = Decimal(quantum.strip())
    except (InvalidOperation, ValueError):
        q = None
    if q is None or not q.is_finite() or q <= 0:
        raise MXBlock("MX_ROUNDING_RULE_INVALID", f"mx_rounding_rule {text!r} has no positive quantum")
    return Rounder(mode.strip().upper(), q, text)


def rounder(content) -> Rounder:
    if not content.has("mx_rounding_rule"):
        raise MXBlock("MX_ROUNDING_RULE_MISSING", "no mx_rounding_rule row is in force — no Mexican amount is emitted "
                                                  "until the rounding rule is transcribed from its source (Q2)")
    return parse(content.text("mx_rounding_rule"))
