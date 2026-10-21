"""
engine/jurisdictions/mexico/special_pay.py
------------------------------------------
Special payments (ZP-MX-ENG-001 §4 MX-009, §17 MX-052; Phase 9b). Aguinaldo,
vacation premium, PTU and separation payments use their own legally
prescribed exemption and withholding method — they are never simply added to
ordinary salary. Every rule comes from content written at transcription
(mexico_content.MX_SPECIAL_PAY_RULES / MX_AGUINALDO_RULE /
MX_SPECIAL_PAY_ISN_INCLUSION); with none present every special payment BLOCKS.

The engine fixes only the INTERFACE a transcribed rule must provide:

  SpecialPayRule   source, source_ref
                   combine_with_ordinary: bool — True when the taxable part is
                       withheld together with the ordinary pay of the period
                   exempt(concept, amount, facts) -> Decimal   (LISR Art. 93)
                   standalone_isr(taxable, facts) -> Decimal   (when paid in its
                       own run: aguinaldo / PTU / finiquito)
  AguinaldoRule    source, source_ref
                   fraction(year, employed_from, employed_to) -> Decimal in [0, 1]
                   payable_by(year) -> date | None

`facts` carries the pay date, daily salary, the in-force UMA rows and the
ordinary facts a rule may need — the rule decides what it reads.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from ...countries import mexico_content as _content
from .errors import MXBlock

_ZERO, _ONE = Decimal("0"), Decimal("1")
CONCEPTS = ("AGUINALDO", "VACATION_PREMIUM", "VACATION_PAYOUT", "PTU", "SEPARATION")
# The concepts a special run may carry (Phase 9b: aguinaldo; 9c: the finiquito
# — proportional aguinaldo, vacation paid out and its premium, separation
# components; 9d: PTU). Never an ordinary line (MX-009).
RUN_CONCEPTS = {"AGUINALDO": ("AGUINALDO",), "PTU": ("PTU",),
                "FINIQUITO": ("AGUINALDO", "VACATION_PAYOUT", "VACATION_PREMIUM", "SEPARATION")}


def _dec(value, what: str) -> Decimal:
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except Exception:                                   # noqa: BLE001 — a rule returned something unusable
        raise MXBlock("MX_SPECIAL_PAY_RULE_INVALID", f"the transcribed rule returned an invalid {what}")


def rule(concept: str):
    found = _content.MX_SPECIAL_PAY_RULES.get(concept)
    if found is None:
        raise MXBlock("MX_SPECIAL_PAY_RULE_MISSING",
                      f"{concept.replace('_', ' ').lower()}: the exemption and withholding rule (LISR Art. 93 / 96, "
                      f"RLISR Art. 174 — S24 / S25) is not transcribed — never withheld on the ordinary tariff (MX-009)")
    return found


def aguinaldo_rule():
    found = _content.MX_AGUINALDO_RULE
    if found is None:
        raise MXBlock("MX_AGUINALDO_RULE_MISSING",
                      "the aguinaldo proportion for part of a year and its payable-by date (LFT Art. 87 — S26) are not "
                      "transcribed")
    return found


def isn_included(state: Optional[str], concept: str) -> bool:
    entry = _content.MX_SPECIAL_PAY_ISN_INCLUSION.get((state, concept))
    if entry is None:
        raise MXBlock("MX_ISN_SPECIAL_PAY_RULE_MISSING",
                      f"whether {concept.replace('_', ' ').lower()} is in the {state} payroll-tax base is not "
                      f"transcribed from the state's code")
    return bool(entry[0])


def split(concept: str, amount: Decimal, facts: dict) -> dict:
    """{exempt, taxable, rule} — 0 ≤ exempt ≤ amount, or a BLOCK."""
    r = rule(concept)
    exempt = _dec(r.exempt(concept, amount, facts), "exempt amount")
    if exempt < _ZERO or exempt > amount:
        raise MXBlock("MX_SPECIAL_PAY_RULE_INVALID",
                      f"the {concept} rule returned an exempt part outside 0–{amount}")
    return {"exempt": exempt, "taxable": amount - exempt, "rule": r}


def classify(lines, facts: dict, work_state: Optional[str], *, special_run: bool) -> list:
    """Special-payment lines → classified lines (the shape classification.classify
    returns), every problem reported at once. In an ordinary run the rule must
    withhold together with the ordinary pay (combine_with_ordinary); a special
    run withholds on its own (standalone_isr, applied by the orchestrator)."""
    out, problems = [], []
    for line in lines or []:
        concept = str(line.get("kind") or "").upper()
        code = str(line.get("code") or concept)
        try:
            amount = _dec(line.get("amount"), f"{code} amount")
            if amount < _ZERO:
                raise MXBlock("MX_EARNING_INVALID", f"earning {code} is negative")
            parts = split(concept, amount, facts)
            if not special_run and not getattr(parts["rule"], "combine_with_ordinary", False):
                raise MXBlock("MX_SPECIAL_PAY_METHOD_UNSUPPORTED",
                              f"the transcribed {concept} rule is not withheld with the ordinary pay — pay it in its "
                              f"own run")
            included = isn_included(work_state, concept)
        except MXBlock as exc:
            problems.extend(exc.reasons)
            continue
        out.append({"code": code, "kind": concept, "amount": amount, "isr_taxable": parts["taxable"],
                    "isr_exempt": parts["exempt"], "sbc": "EXCLUDED", "infonavit": False, "isn": included,
                    "ptu": None, "cfdi_node": "PERCEPCION", "cfdi_concept_code": None, "classification_id": None,
                    "version": None, "rule_source": f"{parts['rule'].source} {parts['rule'].source_ref}"})
    if problems:
        raise MXBlock(problems[0][0], "; ".join(f"{k}: {d}" for k, d in problems), reasons=problems)
    return out


def aguinaldo_amount(days: Decimal, daily_salary: Decimal, year: int, employed_from, employed_to) -> dict:
    """{days, daily_salary, fraction, amount, payable_by, rule_source} — the
    unrounded entitlement for `year` (rounded by the caller's rounding rule)."""
    r = aguinaldo_rule()
    fraction = _dec(r.fraction(year, employed_from, employed_to), "aguinaldo fraction")
    if fraction < _ZERO or fraction > _ONE:
        raise MXBlock("MX_AGUINALDO_RULE_INVALID", f"the aguinaldo rule returned a fraction {fraction} outside 0–1")
    return {"days": days, "daily_salary": daily_salary, "fraction": fraction, "amount": days * daily_salary * fraction,
            "payable_by": r.payable_by(year), "rule_source": f"{r.source} {r.source_ref}"}
