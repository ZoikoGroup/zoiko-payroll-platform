"""
engine/jurisdictions/mexico/classification.py
---------------------------------------------
Splits each earning line of the period by its multi-axis classification in
force on the pay date (MX-005–MX-007, Phase 2 rows): ISR taxable / exempt,
SBC fixed / variable / excluded, INFONAVIT, state ISN (with the work state's
override), PTU base and the CFDI node — never one universal "taxable" flag.

Fail closed:
- a code with no classification, or one not in force on the pay date, BLOCKS;
- an EXEMPT / PARTIAL ISR treatment BLOCKS: exemptions come only from a named
  rule whose content exists (LISR Art. 93, S24), and none is transcribed yet;
- special payments (aguinaldo, vacation premium, PTU, separation) BLOCK —
  their withholding is Phase 9 (Q8);
- a line whose CFDI node is not a perception BLOCKS in ordinary payroll.

Historical results replay with the classification version in force on their
own pay date (MX-006): a SUPERSEDED row still classifies inside its window.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal, InvalidOperation

from .errors import MXBlock
from .termination import SEPARATION_KINDS   # Phase 11b: three separation kinds (S28 022 / 023 / 025)

# Earning-line kinds the run integration supplies (Phase 6). The salary line
# is the one the SBC fixed part and the minimum-wage check are built from.
ORDINARY_SALARY = "ORDINARY_SALARY"
OVERTIME = "OVERTIME"
SUNDAY_PREMIUM = "SUNDAY_PREMIUM"
OTHER = "OTHER"
SPECIAL_PAY_KINDS = ("AGUINALDO", "VACATION_PREMIUM", "PTU") + SEPARATION_KINDS
LINE_KINDS = (ORDINARY_SALARY, OVERTIME, SUNDAY_PREMIUM, OTHER) + SPECIAL_PAY_KINDS

_IN_FORCE_STATUSES = ("ACTIVE", "SUPERSEDED")


def _amount(value, code: str) -> Decimal:
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise MXBlock("MX_EARNING_INVALID", f"earning {code} has no numeric amount")
    if not out.is_finite() or out < 0:
        raise MXBlock("MX_EARNING_INVALID", f"earning {code} must be a finite amount of zero or more")
    return out


def _as_date(value):
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, str):
        return _dt.date.fromisoformat(value)
    return value


def _in_force(row: dict, on: _dt.date) -> bool:
    start, end = _as_date(row.get("effective_from")), _as_date(row.get("effective_to"))
    return (row.get("status") in _IN_FORCE_STATUSES and start is not None and start <= on
            and (end is None or on <= end))


def isn_included(row: dict, work_state: str) -> bool:
    overrides = row.get("isn_state_overrides") or {}
    if work_state in overrides:
        return bool(overrides[work_state])
    return bool(row.get("isn_default_included"))


def classify(lines, classifications, on: _dt.date, work_state: str) -> list:
    """[{code, kind, amount, isr_taxable, sbc, infonavit, isn, ptu, cfdi_node,
    classification_id, version}] — or one BLOCK naming every bad line."""
    classifications = classifications or {}
    out, problems = [], []
    for line in lines or []:
        code = str(line.get("code") or "").strip()
        kind = str(line.get("kind") or OTHER).strip().upper()
        if not code:
            problems.append(("MX_EARNING_INVALID", "an earning line has no code"))
            continue
        if kind not in LINE_KINDS:
            problems.append(("MX_EARNING_INVALID", f"earning {code} has unknown kind {kind!r}"))
            continue
        if kind in SPECIAL_PAY_KINDS:
            # Invariant (Phase 11d): preflight routes special kinds to
            # special_pay.classify first, so an ordinary line never carries one.
            problems.append(("MX_SPECIAL_PAY_PHASE9",
                             f"earning {code} is a special payment ({kind}) — it is calculated by its own rule, never "
                             f"as an ordinary line"))
            continue
        amount = _amount(line.get("amount"), code)
        row = classifications.get(code)
        if not row:
            problems.append(("MX_CLASSIFICATION_MISSING", f"earning {code} has no approved classification"))
            continue
        if not _in_force(row, on):
            problems.append(("MX_CLASSIFICATION_NOT_IN_FORCE",
                             f"earning {code}'s classification is not approved and in force on {on.isoformat()}"))
            continue
        node = row.get("cfdi_node_type")
        if node == "SEPARACION":
            problems.append(("MX_SPECIAL_PAY_PHASE9", f"earning {code} is a separation payment — Phase 9 (Q8)"))
            continue
        if node != "PERCEPCION":
            problems.append(("MX_CLASSIFICATION_UNSUPPORTED",
                             f"earning {code} is classified {node} — ordinary payroll calculates perceptions only"))
            continue
        isr = row.get("isr_treatment")
        if isr != "TAXABLE":
            problems.append(("MX_EXEMPTION_RULE_MISSING",
                             f"earning {code} is ISR {isr} (rule {row.get('isr_exempt_rule_key') or 'unnamed'}) — "
                             f"no exemption content is transcribed yet (LISR Art. 93, S24)"))
            continue
        sbc = row.get("sbc_treatment")
        if sbc not in ("FIXED", "VARIABLE", "EXCLUDED"):
            problems.append(("MX_CLASSIFICATION_INVALID", f"earning {code} has SBC treatment {sbc!r}"))
            continue
        out.append({
            "code": code, "kind": kind, "amount": amount,
            "isr_taxable": amount, "isr_exempt": Decimal("0"),
            "sbc": sbc, "infonavit": bool(row.get("infonavit_included")),
            "isn": isn_included(row, work_state), "ptu": bool(row.get("ptu_wage_base_included")),
            "cfdi_node": node, "cfdi_concept_code": row.get("cfdi_concept_code"),
            "classification_id": row.get("id"), "version": row.get("version"),
        })
    if problems:
        raise MXBlock(problems[0][0], "; ".join(d for _, d in problems), reasons=problems)
    return out
