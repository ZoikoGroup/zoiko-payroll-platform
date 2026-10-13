"""
engine/jurisdictions/netherlands/transition_payment.py
------------------------------------------------------
Transition payment (transitievergoeding) and final-pay components —
ZP-NL-ENG-001 §14, NL-044.

Statutory framework (S17): it generally accrues from the first day where the
termination / non-renewal is employer-initiated; one third of a monthly salary
per year of service, pro rata for a partial year; capped at the pack's cap
(nl_transition_payment_cap, €102,000 in 2026) or one annual salary when that
is higher. The final settlement keeps final salary, unused leave, vacation
allowance and the transition payment as SEPARATE components (NL-044).
Approval must be by someone other than the preparer.
Pure: no ORM, no framework.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional


class TransitionPaymentError(Exception):
    pass


class FourEyesError(TransitionPaymentError):
    pass


@dataclass(frozen=True)
class TransitionPaymentResult:
    eligible: bool
    service_months: int
    monthly_salary: Decimal
    uncapped: Decimal
    cap: Decimal
    amount: Decimal
    cap_applied: bool
    reason: str

    def as_dict(self) -> dict:
        return {"eligible": self.eligible, "serviceMonths": self.service_months,
                "monthlySalary": str(self.monthly_salary), "uncapped": str(self.uncapped), "cap": str(self.cap),
                "amount": str(self.amount), "capApplied": self.cap_applied, "reason": self.reason}


def _q(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _fraction(text: Optional[str]) -> Decimal:
    if not text or "/" not in text:
        raise TransitionPaymentError("transition-payment month fraction not configured (nl_transition_payment_month_frac)")
    num, den = text.split("/", 1)
    return Decimal(num.strip()) / Decimal(den.strip())


def calculate(*, initiated_by: str, service_months: int, monthly_salary: Decimal, annual_salary: Decimal,
              statutory_cap: Optional[Decimal], month_fraction: Optional[str]) -> TransitionPaymentResult:
    if statutory_cap is None:
        raise TransitionPaymentError("transition-payment cap not configured (nl_transition_payment_cap)")
    if service_months < 0:
        raise TransitionPaymentError("service months cannot be negative")
    monthly = Decimal(monthly_salary)
    cap = max(Decimal(statutory_cap), Decimal(annual_salary))
    if initiated_by != "EMPLOYER":
        # Employee resignation or a mutual settlement does not create the
        # statutory entitlement (a negotiated amount is a separate earning).
        return TransitionPaymentResult(False, service_months, monthly, Decimal("0.00"), cap, Decimal("0.00"), False,
                                       f"termination initiated by {initiated_by} — no statutory entitlement")
    uncapped = _q(monthly * _fraction(month_fraction) * Decimal(service_months) / Decimal("12"))
    amount = min(uncapped, _q(cap))
    return TransitionPaymentResult(True, service_months, monthly, uncapped, _q(cap), amount, amount < uncapped,
                                   "employer-initiated termination / non-renewal")


def validate_four_eyes(prepared_by: Optional[int], approved_by: Optional[int]) -> None:
    if approved_by is None:
        raise FourEyesError("an approver is required")
    if prepared_by is not None and prepared_by == approved_by:
        raise FourEyesError("the preparer cannot approve their own termination settlement (four-eyes)")


__all__ = ["TransitionPaymentError", "FourEyesError", "TransitionPaymentResult", "calculate", "validate_four_eyes"]
