"""
engine/jurisdictions/mexico/ptu.py
----------------------------------
PTU — employee profit sharing (ZP-MX-ENG-001 §17 MX-054–MX-056; Phase 9d).
The distributable amount is the employer's own figure (never derived here,
MX-054). Every allocation rule comes from content written at transcription
(mexico_content.MX_PTU_RULE / MX_PTU_EXCLUSION_REASONS); with none present no
PTU is allocated.

The engine fixes only the INTERFACE a transcribed rule must provide:

  PtuRule   source, source_ref
            allocate(pool, workers, fiscal_year) -> {"workers": [{employee_id,
                eligible, exclusion_reason, days_share, salary_share,
                cap_reference, cap_applied, final_amount}], "residue": Decimal,
                "residue_rule": str}
                `workers`: [{employee_id, days, salary_by_kind, finiquito_by_kind,
                date_of_joining, date_of_leaving, operator_exclusion}] — the rule
                decides which days and salary count, eligibility, the split,
                the caps and the rounding (LFT Arts. 117–131 — S26)
            payment_deadline(fiscal_year, employer) -> date | None   (S21)
  PtuExclusionReason  source, source_ref, label — the reasons an operator may
            assert (with evidence and a second approver)

What the engine enforces on any rule's output (else MX_PTU_RULE_INVALID):
every worker given back exactly once; amounts and shares ≥ 0; an excluded
worker gets nothing and carries a reason; an operator-excluded worker is
excluded with that reason; the final amounts plus the residue equal the pool.
"""

from __future__ import annotations

from decimal import Decimal

from ...countries import mexico_content as _content
from .errors import MXBlock

_ZERO = Decimal("0")


def _dec(value, what: str) -> Decimal:
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except Exception:                                   # noqa: BLE001 — a rule returned something unusable
        raise MXBlock("MX_PTU_RULE_INVALID", f"the transcribed PTU rule returned an invalid {what}")


def rule():
    found = _content.MX_PTU_RULE
    if found is None:
        raise MXBlock("MX_PTU_RULE_MISSING",
                      "the PTU rule — split, qualifying days and salary, eligibility, caps, rounding (LFT Arts. "
                      "117–131, S26) and the payment window (S21) — is not transcribed")
    return found


def exclusion_reason(code: str):
    if not _content.MX_PTU_EXCLUSION_REASONS:
        raise MXBlock("MX_PTU_EXCLUSION_RULE_MISSING",
                      "the catalog of PTU exclusions an operator may assert (S26) is not transcribed")
    found = _content.MX_PTU_EXCLUSION_REASONS.get(str(code or "").strip())
    if found is None:
        raise MXBlock("MX_PTU_EXCLUSION_REASON_UNKNOWN", f"'{code}' is not a transcribed PTU exclusion reason")
    return found


def exclusion_catalog() -> list:
    return [{"code": code, "label": getattr(r, "label", code), "source": r.source, "sourceRef": r.source_ref}
            for code, r in sorted(_content.MX_PTU_EXCLUSION_REASONS.items())]


def rule_source() -> str:
    r = rule()
    return f"{r.source} {r.source_ref}"


def payment_deadline(fiscal_year: int, employer: dict):
    return rule().payment_deadline(fiscal_year, employer)


def allocate(pool: Decimal, workers: list, fiscal_year: int) -> dict:
    """The rule's allocation, validated."""
    out = rule().allocate(pool, workers, fiscal_year) or {}
    rows = list(out.get("workers") or [])
    asked = {int(w["employee_id"]) for w in workers}
    given = [int(r.get("employee_id")) for r in rows]
    if sorted(given) != sorted(asked):
        raise MXBlock("MX_PTU_RULE_INVALID", "the PTU rule did not return every worker exactly once")
    operator = {int(w["employee_id"]): w.get("operator_exclusion") for w in workers if w.get("operator_exclusion")}
    clean, total = [], _ZERO
    for r in rows:
        emp = int(r["employee_id"])
        days_share = _dec(r.get("days_share", 0), "days share")
        salary_share = _dec(r.get("salary_share", 0), "salary share")
        final = _dec(r.get("final_amount", 0), "final amount")
        if min(days_share, salary_share, final) < _ZERO:
            raise MXBlock("MX_PTU_RULE_INVALID", f"the PTU rule returned a negative amount for worker {emp}")
        eligible = bool(r.get("eligible"))
        reason = (r.get("exclusion_reason") or "").strip() or None
        if not eligible and (final != _ZERO or not reason):
            raise MXBlock("MX_PTU_RULE_INVALID",
                          f"worker {emp} is excluded without a reason or still receives an amount")
        if emp in operator and (eligible or reason != operator[emp]):
            raise MXBlock("MX_PTU_RULE_INVALID",
                          f"worker {emp} carries an approved operator exclusion ({operator[emp]}) the rule ignored")
        total += final
        clean.append({"employee_id": emp, "eligible": eligible, "exclusion_reason": reason,
                      "days_share": days_share, "salary_share": salary_share,
                      "cap_reference": r.get("cap_reference") or {}, "cap_applied": bool(r.get("cap_applied")),
                      "final_amount": final})
    residue = _dec(out.get("residue", 0), "residue")
    if residue < _ZERO or total + residue != pool:
        raise MXBlock("MX_PTU_RULE_INVALID",
                      f"the allocations ({total}) plus the residue ({residue}) do not equal the pool ({pool})")
    return {"workers": clean, "residue": residue, "residue_rule": str(out.get("residue_rule") or ""),
            "rule_source": rule_source()}
