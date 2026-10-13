"""
engine/jurisdictions/netherlands/pension.py
-------------------------------------------
Pension contribution overlay — ZP-NL-ENG-001 §14, NL-043.

Contribution formulas are scheme-owned: the rates, franchise and maximum
pensionable salary come from the employee's payroll_nl_pension_schemes row in
force on the pay date (annual figures, spread over the pay periods). Two basis
rules exist in the schema:
  * GROSS_MINUS_FRANCHISE  basis = pensionable earnings − franchise
  * CAPPED_PENSIONABLE     same, with pensionable earnings first capped at the
                           scheme's maximum pensionable salary
The employee share is a net deduction; the employer share is employer cost
(never shown as an employee deduction, NL-048).
Pure: no ORM, no framework.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping, Optional


class PensionError(Exception):
    """Scheme facts missing or inconsistent — the caller blocks."""


class PensionComplianceError(PensionError):
    """A mandatory sector scheme applies but is not configured (NL-043)."""


@dataclass(frozen=True)
class PensionResult:
    scheme_code: str
    basis: Decimal
    employee: Decimal
    employer: Decimal

    def as_dict(self) -> dict:
        return {"schemeCode": self.scheme_code, "basis": str(self.basis), "employee": str(self.employee),
                "employer": str(self.employer)}


def _q(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def contributions(scheme: Optional[Mapping[str, Any]], *, pensionable_earnings: Decimal,
                  periods_per_year: int) -> Optional[PensionResult]:
    """None when the employee has no scheme (and none is mandatory — that is
    checked by preflight against the employer's CAO/pension status)."""
    if not scheme:
        return None
    rule = scheme.get("basis_rule")
    if rule not in ("GROSS_MINUS_FRANCHISE", "CAPPED_PENSIONABLE"):
        raise PensionError(f"pension scheme {scheme.get('scheme_code')}: unknown basis rule {rule!r}")
    periods = Decimal(periods_per_year)
    earnings = Decimal(pensionable_earnings)
    if rule == "CAPPED_PENSIONABLE":
        if scheme.get("max_pensionable_salary") is None:
            raise PensionError(f"pension scheme {scheme.get('scheme_code')}: CAPPED_PENSIONABLE needs a maximum pensionable salary")
        earnings = min(earnings, _q(Decimal(str(scheme["max_pensionable_salary"])) / periods))
    franchise = _q(Decimal(str(scheme.get("franchise_amount") or "0")) / periods)
    basis = max(earnings - franchise, Decimal("0.00"))
    ee = _q(basis * Decimal(str(scheme.get("employee_pct") or "0")) / Decimal("100"))
    er = _q(basis * Decimal(str(scheme.get("employer_pct") or "0")) / Decimal("100"))
    return PensionResult(scheme_code=scheme.get("scheme_code") or "", basis=_q(basis), employee=ee, employer=er)


__all__ = ["PensionError", "PensionComplianceError", "PensionResult", "contributions"]
