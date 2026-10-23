"""
engine/jurisdictions/mexico/termination.py
------------------------------------------
Termination and finiquito (ZP-MX-ENG-001 §17 MX-057 / MX-058; Phase 9c, plan
B6, D5). Every rule comes from content written at transcription
(mexico_content.MX_TERMINATION_REASONS / MX_FINIQUITO_RULE); with none present
no termination is recorded and no finiquito is calculated. An operator never
chooses a tax treatment or a component: the reason decides (MX-057).

The engine fixes only the INTERFACE a transcribed rule must provide:

  TerminationReason  source, source_ref, label
                     separation_components(facts) -> [{code, label, kind, amount}]
                         the indemnity / seniority premium / ... this reason
                         triggers (LFT Arts. 47–53, 162 — S26); [] for none;
                         `kind` is one of SEPARATION_KINDS (Phase 11b)
  FiniquitoRule      source, source_ref
                     vacation_days_owed(years, termination_date)
                         -> {service_year: days} still owed (LFT Arts. 76–81);
                         `years` is the ledger: [{service_year, policy_days,
                         opening, taken, paid_out, start, end}]
                     isr(taxable_by_concept, facts) -> Decimal — the
                         withholding of a finiquito paid on its own (LISR /
                         RLISR — S24 / S25)

`facts` carries the termination and pay dates, the daily salary, the
seniority and joining dates, the work state, the minimum-wage zone and the
in-force content — the rule decides what it reads.
"""

from __future__ import annotations

from decimal import Decimal

from ...countries import mexico_content as _content
from .errors import MXBlock

_ZERO = Decimal("0")
SEPARATION_PREFIX = "MX_SEPARATION:"
# Phase 11b: a separation component is one of three kinds, matching the three
# separation perceptions of the SAT Nómina 1.2 catalog (S28 c_TipoPercepcion
# 022 seniority premium, 023 separation payment, 025 indemnity). Each kind has
# its own transcribed tax rule; the SAT code itself comes from the approved
# system-concept mapping, never from here.
SEPARATION_KINDS = ("SEPARATION_SENIORITY_PREMIUM", "SEPARATION_PAYMENT", "SEPARATION_INDEMNITY")


def _dec(value, what: str, code: str) -> Decimal:
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except Exception:                                   # noqa: BLE001 — a rule returned something unusable
        raise MXBlock(code, f"the transcribed rule returned an invalid {what}")


def reason(code: str):
    """The transcribed reason, or a BLOCK (catalog empty / code unknown)."""
    if not _content.MX_TERMINATION_REASONS:
        raise MXBlock("MX_TERMINATION_RULE_MISSING",
                      "the termination-reason catalog and its components (LFT Arts. 47–53, 162 — S26) are not "
                      "transcribed — no termination can be recorded")
    found = _content.MX_TERMINATION_REASONS.get(str(code or "").strip())
    if found is None:
        raise MXBlock("MX_TERMINATION_REASON_UNKNOWN",
                      f"'{code}' is not a transcribed termination reason")
    return found


def catalog() -> list:
    """[{code, label, source, sourceRef}] — empty until S26 is transcribed."""
    return [{"code": code, "label": getattr(r, "label", code), "source": r.source, "sourceRef": r.source_ref}
            for code, r in sorted(_content.MX_TERMINATION_REASONS.items())]


def finiquito_rule():
    found = _content.MX_FINIQUITO_RULE
    if found is None:
        raise MXBlock("MX_FINIQUITO_RULE_MISSING",
                      "the finiquito rule — vacation owed at termination (LFT Arts. 76–81, S26) and the withholding "
                      "of a finiquito paid on its own (S24 / S25) — is not transcribed")
    return found


def separation_lines(code: str, facts: dict) -> list:
    """The reason's separation components as earning lines of their own
    separation kind (a component without one BLOCKS — Phase 11b)."""
    r = reason(code)
    out = []
    for comp in r.separation_components(facts) or []:
        key = str(comp.get("code") or "").strip()
        if not key:
            raise MXBlock("MX_TERMINATION_RULE_INVALID", f"the '{code}' reason returned a component without a code")
        kind = str(comp.get("kind") or "").strip().upper()
        if kind not in SEPARATION_KINDS:
            raise MXBlock("MX_TERMINATION_RULE_INVALID",
                          f"the '{code}' reason's component {key} has no separation kind — one of "
                          f"{', '.join(SEPARATION_KINDS)} (S28 c_TipoPercepcion 022 / 023 / 025)")
        amount = _dec(comp.get("amount"), f"{key} amount", "MX_TERMINATION_RULE_INVALID")
        if amount < _ZERO:
            raise MXBlock("MX_TERMINATION_RULE_INVALID", f"the '{code}' reason returned a negative {key}")
        if amount:
            out.append({"code": f"{SEPARATION_PREFIX}{key}", "kind": kind, "amount": amount,
                        "label": str(comp.get("label") or key)})
    return out


def vacation_owed(years: list, termination_date) -> dict:
    """{service_year: days} — only years in the ledger, never negative."""
    owed = finiquito_rule().vacation_days_owed(years, termination_date) or {}
    known = {int(y["service_year"]) for y in years}
    out = {}
    for year, days in owed.items():
        if int(year) not in known:
            raise MXBlock("MX_FINIQUITO_RULE_INVALID", f"the finiquito rule returned days for service year {year}, "
                                                       f"which is not in the employee's ledger")
        d = _dec(days, f"service-year {year} days", "MX_FINIQUITO_RULE_INVALID")
        if d < _ZERO:
            raise MXBlock("MX_FINIQUITO_RULE_INVALID", f"the finiquito rule returned negative days for year {year}")
        if d:
            out[int(year)] = d
    return out


def isr(taxable_by_concept: dict, facts: dict) -> Decimal:
    r = finiquito_rule()
    withheld = _dec(r.isr(taxable_by_concept, facts), "ISR amount", "MX_FINIQUITO_RULE_INVALID")
    if withheld < _ZERO:
        raise MXBlock("MX_FINIQUITO_RULE_INVALID", "the finiquito rule returned a negative withholding")
    return withheld


def rule_source() -> str:
    r = finiquito_rule()
    return f"{r.source} {r.source_ref}"
