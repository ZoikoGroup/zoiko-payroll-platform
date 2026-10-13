"""
engine/jurisdictions/netherlands/expat.py
-----------------------------------------
Expat scheme (30% facility) — ZP-NL-ENG-001 §9, NL-026..NL-028, fixture F5.

Payroll applies the facility only from a VERIFIED Belastingdienst decision
whose granted window covers the pay date (NL-026 — an HR checkbox is not
enough). For the FACILITY_30PCT method the tax-free allowance for a period is
the smallest of:
  * allowance_pct × the package (the package is the wage INCLUDING the
    allowance, capped at the WNT cap for the period),
  * the pack's maximum allowance for the period (nl_expat_allowance_cap ÷ periods),
  * the part of the package above the salary threshold for the period — the
    taxable wage may never drop below the statutory threshold (NL-027).
If the package does not clear the threshold the facility cannot apply this
period: the allowance is 0 and the risk is surfaced (NL-027). Every figure is
kept for the trace and payslip (NL-028). ACTUAL_ET_COSTS is a different route
(reimbursements via earning classification), so it yields no allowance here.
Pure: no ORM, no framework.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping, Optional


class ExpatError(Exception):
    """A required decision fact or pack parameter is missing — the caller blocks."""


_THRESHOLD_KEY = {
    "STANDARD": "nl_expat_salary_threshold",
    "UNDER30_MASTER": "nl_expat_salary_threshold_young_master",
    "RESEARCH_MEDICAL": None,  # separately flagged exception — no salary norm (spec §9)
}


@dataclass(frozen=True)
class ExpatResult:
    applied: bool
    decision_reference: Optional[str]
    method: Optional[str]
    package: Decimal
    allowance: Decimal
    taxable_wage: Decimal
    threshold_period: Optional[Decimal]
    cap_period: Optional[Decimal]
    risk: Optional[str]

    def as_dict(self) -> dict:
        return {"applied": self.applied, "decisionReference": self.decision_reference, "method": self.method,
                "package": str(self.package), "allowance": str(self.allowance), "taxableWage": str(self.taxable_wage),
                "thresholdPeriod": None if self.threshold_period is None else str(self.threshold_period),
                "capPeriod": None if self.cap_period is None else str(self.cap_period), "risk": self.risk}


def _q(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def decision_in_force(decision: Optional[Mapping[str, Any]], on: date) -> bool:
    if not decision or decision.get("status") != "VERIFIED":
        return False
    granted_from, granted_to = decision.get("granted_from"), decision.get("granted_to")
    if isinstance(granted_from, str):
        granted_from = date.fromisoformat(granted_from)
    if isinstance(granted_to, str):
        granted_to = date.fromisoformat(granted_to)
    return granted_from is not None and granted_from <= on and (granted_to is None or granted_to >= on)


def apply(decision: Optional[Mapping[str, Any]], *, package: Decimal, on: date, periods_per_year: int,
          params: Mapping[str, Optional[Decimal]]) -> ExpatResult:
    """params: the pack's nl_expat_* / nl_wnt_cap amounts (Decimal or None)."""
    package = Decimal(package)
    if not decision_in_force(decision, on):
        return ExpatResult(False, None, None, package, Decimal("0.00"), package, None, None, None)
    method = decision.get("method")
    if method != "FACILITY_30PCT":
        return ExpatResult(False, decision.get("decision_reference"), method, package, Decimal("0.00"), package,
                           None, None, None)
    pct = Decimal(str(decision.get("allowance_pct")))
    max_pct = params.get("nl_expat_max_facility_pct")
    if max_pct is None or params.get("nl_expat_allowance_cap") is None or params.get("nl_wnt_cap") is None:
        raise ExpatError("expat facility parameters (max %, allowance cap, WNT cap) not configured in the active pack")
    if pct > Decimal(str(max_pct)):
        raise ExpatError(f"decision allowance {pct}% exceeds the statutory maximum {max_pct}% (NL-026)")
    category = decision.get("threshold_category")
    if category not in _THRESHOLD_KEY:
        raise ExpatError(f"unknown expat threshold category {category!r}")
    periods = Decimal(periods_per_year)
    threshold_key = _THRESHOLD_KEY[category]
    threshold = None
    if threshold_key is not None:
        if params.get(threshold_key) is None:
            raise ExpatError(f"{threshold_key} not configured in the active pack")
        threshold = _q(Decimal(str(params[threshold_key])) / periods)
    cap = _q(Decimal(str(params["nl_expat_allowance_cap"])) / periods)
    wnt_period = _q(Decimal(str(params["nl_wnt_cap"])) / periods)
    allowance = _q(min(package, wnt_period) * pct / Decimal("100"))
    allowance = min(allowance, cap)
    risk = None
    if threshold is not None:
        headroom = package - threshold
        if headroom <= 0:
            return ExpatResult(False, decision.get("decision_reference"), method, package, Decimal("0.00"), package,
                               threshold, cap, "package does not exceed the salary threshold — facility not applied (NL-027)")
        if allowance > headroom:
            allowance = _q(headroom)
            risk = "allowance reduced to keep the taxable wage at the salary threshold (NL-027)"
    return ExpatResult(True, decision.get("decision_reference"), method, package, allowance, package - allowance,
                       threshold, cap, risk)


__all__ = ["ExpatError", "ExpatResult", "decision_in_force", "apply"]
