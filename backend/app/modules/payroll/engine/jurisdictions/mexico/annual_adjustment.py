"""
engine/jurisdictions/mexico/annual_adjustment.py
------------------------------------------------
The annual ISR adjustment (ZP-MX-ENG-001 §4 MX-010; Phase 9e). Every rule comes
from content written at transcription (mexico_content.MX_ANNUAL_ADJUSTMENT_RULE
/ MX_ANNUAL_ADJUSTMENT_EXCLUSION_REASONS); with none present nothing is
computed. A historical payslip or CFDI is never edited: a difference is applied
in a later run, as its own section of that payslip.

The engine fixes only the INTERFACE a transcribed rule must provide:

  AnnualAdjustmentRule  source, source_ref
      eligibility(worker, fiscal_year) -> (eligible: bool, reason: str | None)
          `worker`: {employee_id, income_by_run_type, annual_taxable,
          withheld_total, subsidy_applied_total, date_of_joining,
          date_of_leaving, operator_exclusion} (LISR Art. 97 — S24)
      annual_isr(annual_taxable, fiscal_year, facts) -> Decimal ≥ 0
          (the annual tariff, LISR Art. 152 — S24)
      apply_in_run(period_withheld, difference, facts)
          -> {"withheld": Decimal ≥ 0, "carry_forward": Decimal}
          with (withheld − period_withheld) + carry_forward == difference
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
        raise MXBlock("MX_ANNUAL_ADJUSTMENT_RULE_INVALID", f"the transcribed rule returned an invalid {what}")


def rule():
    found = _content.MX_ANNUAL_ADJUSTMENT_RULE
    if found is None:
        raise MXBlock("MX_ANNUAL_ADJUSTMENT_RULE_MISSING",
                      "the annual ISR adjustment — eligibility (LISR Art. 97), the annual tariff (Art. 152) and how a "
                      "difference is applied — is not transcribed (S24)")
    return found


def rule_source() -> str:
    r = rule()
    return f"{r.source} {r.source_ref}"


def exclusion_reason(code: str):
    if not _content.MX_ANNUAL_ADJUSTMENT_EXCLUSION_REASONS:
        raise MXBlock("MX_ANNUAL_ADJUSTMENT_EXCLUSION_RULE_MISSING",
                      "the catalog of annual-adjustment exclusions an operator may assert (S24) is not transcribed")
    found = _content.MX_ANNUAL_ADJUSTMENT_EXCLUSION_REASONS.get(str(code or "").strip())
    if found is None:
        raise MXBlock("MX_ANNUAL_ADJUSTMENT_EXCLUSION_REASON_UNKNOWN",
                      f"'{code}' is not a transcribed annual-adjustment exclusion reason")
    return found


def exclusion_catalog() -> list:
    return [{"code": code, "label": getattr(r, "label", code), "source": r.source, "sourceRef": r.source_ref}
            for code, r in sorted(_content.MX_ANNUAL_ADJUSTMENT_EXCLUSION_REASONS.items())]


def compute(worker: dict, fiscal_year: int) -> dict:
    """{eligible, reason, annual_isr, difference} for one worker. An operator
    exclusion always excludes, with its reason; the rule may exclude more."""
    r = rule()
    if worker.get("operator_exclusion"):
        return {"eligible": False, "reason": worker["operator_exclusion"], "annual_isr": None, "difference": None}
    eligible, reason = r.eligibility(worker, fiscal_year)
    if not eligible:
        if not (reason or "").strip():
            raise MXBlock("MX_ANNUAL_ADJUSTMENT_RULE_INVALID", "the rule excluded a worker without a reason")
        return {"eligible": False, "reason": reason, "annual_isr": None, "difference": None}
    annual = _dec(r.annual_isr(worker["annual_taxable"], fiscal_year, worker), "annual ISR")
    if annual < _ZERO:
        raise MXBlock("MX_ANNUAL_ADJUSTMENT_RULE_INVALID", "the rule returned a negative annual ISR")
    # withheld_total is the ISR actually withheld (net of the subsidy applied
    # each period); how the subsidy enters the annual figure is the rule's
    # (annual_isr receives the facts). Positive: owed; negative: a refund.
    difference = annual - worker["withheld_total"]
    return {"eligible": True, "reason": None, "annual_isr": annual, "difference": difference}


def apply_in_run(period_withheld: Decimal, difference: Decimal, facts: dict) -> dict:
    out = rule().apply_in_run(period_withheld, difference, facts) or {}
    withheld = _dec(out.get("withheld"), "withholding")
    carry = _dec(out.get("carry_forward", 0), "carry-forward")
    if withheld < _ZERO:
        raise MXBlock("MX_ANNUAL_ADJUSTMENT_RULE_INVALID", "the rule returned a negative withholding")
    if (withheld - period_withheld) + carry != difference:
        raise MXBlock("MX_ANNUAL_ADJUSTMENT_RULE_INVALID",
                      f"the applied change ({withheld - period_withheld}) plus the carry-forward ({carry}) is not the "
                      f"difference ({difference})")
    return {"withheld": withheld, "carry_forward": carry, "change": withheld - period_withheld,
            "rule_source": rule_source()}
