"""
engine/jurisdictions/netherlands/vacation_allowance.py
------------------------------------------------------
Vacation allowance (vakantiegeld) accrual — ZP-NL-ENG-001 §4, NL-009.

The allowance is a balance SEPARATE from taxable wage: each period accrues
pct × the earnings whose classification has vacation_allowance_basis = True
(earning-code driven, NL-009). The statutory minimum percentage comes from the
pack (nl_vacation_allowance_pct, 8.00 in 2026); a CAO/contract may set a
HIGHER percentage, never a lower one unless a lawful alternative is recorded.
The accrual is written to payroll_nl_vacation_allowance_ledger only on run
commit; the payout itself is an earning (classified SPECIAL for wage tax).
Pure: no ORM, no framework.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping, Optional


class VacationAllowanceError(Exception):
    """Statutory minimum not configured, or a below-minimum percentage."""


@dataclass(frozen=True)
class VacationAllowanceResult:
    basis_amount: Decimal
    pct: Decimal
    accrual: Decimal
    prior_balance: Decimal
    payout: Decimal
    balance_after: Decimal

    def as_dict(self) -> dict:
        return {"basis": str(self.basis_amount), "pct": str(self.pct), "accrual": str(self.accrual),
                "priorBalance": str(self.prior_balance), "payout": str(self.payout),
                "balanceAfter": str(self.balance_after)}


def resolve_pct(statutory_min_pct: Optional[Decimal], employee_pct: Optional[Decimal],
                lawful_alternative_ref: Optional[str] = None) -> Decimal:
    """The percentage to accrue: the employee/CAO percentage when set, which
    may not be below the statutory minimum without a recorded lawful alternative."""
    if statutory_min_pct is None:
        raise VacationAllowanceError("statutory vacation-allowance % not configured (nl_vacation_allowance_pct)")
    statutory = Decimal(str(statutory_min_pct))
    if employee_pct is None:
        return statutory
    pct = Decimal(str(employee_pct))
    if pct < statutory and not lawful_alternative_ref:
        raise VacationAllowanceError(
            f"vacation allowance {pct}% is below the statutory minimum {statutory}% with no recorded lawful alternative")
    return pct


def basis(earnings: Mapping[str, Decimal], classifications: Mapping[str, Mapping]) -> Decimal:
    """Sum of earnings classified vacation_allowance_basis = True (NL-009)."""
    total = Decimal("0")
    for code, amount in earnings.items():
        if bool((classifications.get(code) or {}).get("vacation_allowance_basis")):
            total += Decimal(str(amount))
    return total


def accrue(*, basis_amount: Decimal, pct: Decimal, prior_balance: Decimal = Decimal("0"),
           payout: Decimal = Decimal("0")) -> VacationAllowanceResult:
    accrual = (Decimal(basis_amount) * Decimal(pct) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    prior = Decimal(prior_balance)
    paid = Decimal(payout)
    return VacationAllowanceResult(basis_amount=Decimal(basis_amount), pct=Decimal(pct), accrual=accrual,
                                   prior_balance=prior, payout=paid, balance_after=prior + accrual - paid)


__all__ = ["VacationAllowanceError", "VacationAllowanceResult", "resolve_pct", "basis", "accrue"]
