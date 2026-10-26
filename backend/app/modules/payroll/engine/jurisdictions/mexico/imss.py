"""
engine/jurisdictions/mexico/imss.py
-----------------------------------
IMSS employer / employee contributions (spec §8), every branch separately
(MX-023) and per contribution segment, each with its own base × rate:

- E&M fixed quota: employer % × daily UMA × days;
- E&M excess: % × (SBC − threshold × daily UMA, not below zero) × days;
- E&M cash benefits, pensioner medical, Invalidez y Vida, Guarderías,
  Retiro, employee Cesantía y Vejez: % × SBC × days;
- Riesgos de Trabajo: the registration's approved premium for the period
  (MX-024) × SBC × days.

Employer CEAV is banded (ceav.py). Every rate is a content row.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal, InvalidOperation

from .errors import MXBlock

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")

# (branch, side, content key, base) — base "UMA" = daily UMA, "EXCESS" = SBC
# above the threshold, "SBC" = the segment SBC.
BRANCHES = (
    ("EM_FIXED_QUOTA", "employer", "mx_imss_em_fixed_quota_er_pct", "UMA"),
    ("EM_EXCESS", "employer", "mx_imss_em_excess_er_pct", "EXCESS"),
    ("EM_EXCESS", "employee", "mx_imss_em_excess_ee_pct", "EXCESS"),
    ("EM_CASH", "employer", "mx_imss_em_cash_er_pct", "SBC"),
    ("EM_CASH", "employee", "mx_imss_em_cash_ee_pct", "SBC"),
    ("EM_PENSIONER", "employer", "mx_imss_em_pensioner_er_pct", "SBC"),
    ("EM_PENSIONER", "employee", "mx_imss_em_pensioner_ee_pct", "SBC"),
    ("IV", "employer", "mx_imss_iv_er_pct", "SBC"),
    ("IV", "employee", "mx_imss_iv_ee_pct", "SBC"),
    ("GUARDERIAS", "employer", "mx_imss_guarderias_er_pct", "SBC"),
    ("RETIRO", "employer", "mx_imss_retiro_er_pct", "SBC"),
    ("CEAV", "employee", "mx_imss_ceav_ee_pct", "SBC"),
)


def _as_date(value):
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, str):
        return _dt.date.fromisoformat(value)
    return value


def risk_premium_rate(premium, registration, segments) -> Decimal:
    """The approved premium (percent units) covering every segment, for the
    employee's registration — else BLOCK (MX-024: never a class default)."""
    if not premium:
        raise MXBlock("MX_NO_RISK_PREMIUM", "no approved work-risk premium for the employee's IMSS registration")
    if premium.get("status") != "ACTIVE":
        raise MXBlock("MX_NO_RISK_PREMIUM", "the work-risk premium is not approved (ACTIVE)")
    if registration and premium.get("registration_id") not in (None, registration.get("id")):
        raise MXBlock("MX_NO_RISK_PREMIUM", "the work-risk premium belongs to another IMSS registration")
    start, end = _as_date(premium.get("period_from")), _as_date(premium.get("period_to"))
    for seg in segments:
        if start is None or end is None or seg["start"] < start or seg["end"] > end:
            raise MXBlock("MX_NO_RISK_PREMIUM",
                          f"no approved work-risk premium covers {seg['start'].isoformat()}–{seg['end'].isoformat()}")
    try:
        rate = Decimal(str(premium.get("premium_rate_pct")))
    except (InvalidOperation, ValueError):
        raise MXBlock("MX_NO_RISK_PREMIUM", "the work-risk premium rate is not a number")
    if not rate.is_finite() or rate < 0:
        raise MXBlock("MX_NO_RISK_PREMIUM", "the work-risk premium rate is invalid")
    return rate


def branch_days(seg, branch: str) -> Decimal:
    """W3-3: the days a branch contributes in this segment — the segment's days
    unless absences / incapacity set per-branch days (LSS Art. 31)."""
    return (seg.get("branch_days") or {}).get(branch, seg["days"])


def contributions(sbc_segments, premium_pct: Decimal) -> dict:
    """{lines:[{branch, side, segment, base, days, rate_pct, amount}], employee, employer}."""
    lines = []
    for seg in sbc_segments:
        c, sbc, uma = seg["content"], seg["sbc"], seg["uma_daily"]
        threshold = c.amount("mx_imss_em_excess_threshold_uma") * uma
        excess = max(sbc - threshold, _ZERO)
        bases = {"UMA": uma, "EXCESS": excess, "SBC": sbc}
        for branch, side, key, base in BRANCHES:
            rate, d = c.pct(key), branch_days(seg, branch)
            lines.append({"branch": branch, "side": side, "segment": seg["start"].isoformat(), "key": key,
                          "base": bases[base], "days": d, "rate_pct": rate * _HUNDRED,
                          "amount": bases[base] * d * rate})
        d = branch_days(seg, "RIESGOS_TRABAJO")
        lines.append({"branch": "RIESGOS_TRABAJO", "side": "employer", "segment": seg["start"].isoformat(),
                      "key": "registration premium", "base": sbc, "days": d, "rate_pct": premium_pct,
                      "amount": sbc * d * premium_pct / _HUNDRED})
    return {"lines": lines,
            "employee": sum((l["amount"] for l in lines if l["side"] == "employee"), _ZERO),
            "employer": sum((l["amount"] for l in lines if l["side"] == "employer"), _ZERO)}
