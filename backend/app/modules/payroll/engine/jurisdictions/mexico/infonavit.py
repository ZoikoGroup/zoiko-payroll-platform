"""
engine/jurisdictions/mexico/infonavit.py
----------------------------------------
INFONAVIT (spec §10):

- employer housing contribution = `mx_infonavit_er_pct` × SBC × days, per
  contribution segment;
- an employee credit deduction exists ONLY from an authority notice in force
  for the whole period (MX-031) — RETENCION / MODIFICACION deduct, a
  SUSPENSION in force means none. The method and value are the notice's; the
  per-period basis of each method is a transcribed rule (Q7):
    PERCENTAGE   → `mx_infonavit_percentage_basis`: SBC_TIMES_DAYS
    FIXED_AMOUNT → `mx_infonavit_fixed_amount_basis`: DAILY_TIMES_DAYS
  VSM and UMA_FACTOR, a missing basis rule, or a notice starting or ending
  inside the period BLOCK until their rule is transcribed (S27/S15).
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal, InvalidOperation

from .errors import MXBlock

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
BASIS_RULES = {"PERCENTAGE": ("mx_infonavit_percentage_basis", ("SBC_TIMES_DAYS",)),
               "FIXED_AMOUNT": ("mx_infonavit_fixed_amount_basis", ("DAILY_TIMES_DAYS",))}


def _as_date(value):
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, str):
        return _dt.date.fromisoformat(value)
    return value


def employer(sbc_segments) -> dict:
    lines = []
    for seg in sbc_segments:
        rate = seg["content"].pct("mx_infonavit_er_pct")
        days = (seg.get("branch_days") or {}).get("INFONAVIT", seg["days"])     # W3-3 (Ley INFONAVIT Art. 29)
        lines.append({"branch": "INFONAVIT", "side": "employer", "segment": seg["start"].isoformat(),
                      "base": seg["sbc"], "days": days, "rate_pct": rate * _HUNDRED,
                      "amount": seg["sbc"] * days * rate})
    return {"lines": lines, "employer": sum((l["amount"] for l in lines), _ZERO)}


def _overlaps(n, start, end) -> bool:
    n_from, n_to = _as_date(n.get("effective_from")), _as_date(n.get("effective_to"))
    return n_from is not None and n_from <= end and (n_to is None or n_to >= start)


def credits(notices, period_start, period_end, sbc_segments, content) -> dict:
    lines = []
    by_credit: dict = {}
    for n in notices or []:
        # By legal window, whatever the row's later status: a notice closed or
        # superseded inside the period still governed part of it.
        if _overlaps(n, period_start, period_end):
            by_credit.setdefault(n.get("credit_number"), []).append(n)
    for credit, rows in sorted(by_credit.items(), key=lambda kv: str(kv[0])):
        if len(rows) > 1:
            raise MXBlock("MX_INFONAVIT_PARTIAL_PERIOD",
                          f"credit {credit} has more than one notice in the period — no proration rule is transcribed")
        n = rows[0]
        n_from, n_to = _as_date(n.get("effective_from")), _as_date(n.get("effective_to"))
        if n_from > period_start or (n_to is not None and n_to < period_end):
            raise MXBlock("MX_INFONAVIT_PARTIAL_PERIOD",
                          f"credit {credit}'s notice starts or ends inside the period — no proration rule is transcribed")
        if n.get("notice_type") == "SUSPENSION":
            continue
        method = n.get("discount_method")
        if method not in BASIS_RULES:
            raise MXBlock("MX_INFONAVIT_METHOD_UNSUPPORTED",
                          f"credit {credit} uses method {method or '(none)'} — its computation rule is not transcribed (Q7)")
        key, allowed = BASIS_RULES[method]
        if not content.has(key):
            raise MXBlock("MX_INFONAVIT_METHOD_UNSUPPORTED",
                          f"credit {credit} uses {method} and {key} is not transcribed (S27/S15, Q7)")
        basis = content.text(key).upper()
        if basis not in allowed:
            raise MXBlock("MX_RULE_UNRECOGNISED", f"{key} {basis!r} is not one of {allowed}")
        try:
            value = Decimal(str(n.get("discount_value")))
        except (InvalidOperation, ValueError):
            raise MXBlock("MX_INFONAVIT_NOTICE_INVALID", f"credit {credit} has no numeric discount value")
        if not value.is_finite() or value < 0:
            raise MXBlock("MX_INFONAVIT_NOTICE_INVALID", f"credit {credit} has an invalid discount value")
        days = sum((s["days"] for s in sbc_segments), _ZERO)
        if method == "PERCENTAGE":
            amount = sum((s["sbc"] * s["days"] for s in sbc_segments), _ZERO) * value / _HUNDRED
        else:
            amount = value * days
        lines.append({"credit_number": credit, "method": method, "basis": basis, "value": value, "days": days,
                      "notice_id": n.get("id"), "authority_reference": n.get("authority_reference"), "amount": amount})
    return {"lines": lines, "employee": sum((l["amount"] for l in lines), _ZERO)}
