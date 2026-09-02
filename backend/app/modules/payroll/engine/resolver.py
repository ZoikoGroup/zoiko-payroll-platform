"""
modules/payroll/engine/resolver
-------------------------------
Resolves the organization's payroll policy to the correct strategy
and provides the top-level ``calculate_payroll()`` entry point.

The core payroll engine ORCHESTRATES only — all calculation logic
lives in the resolved strategy.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from app.modules.payroll.engine.base import (
    PAYROLL_DAYS,
    PayrollContext,
    PayrollResult,
    PayrollStrategy,
    _round2,
)
from app.modules.payroll.engine.simple import SimpleStrategy
from app.modules.payroll.engine.standard import StandardStrategy
from app.modules.payroll.engine.enterprise import EnterpriseStrategy

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# ── Strategy registry ──────────────────────────────────────────────────────

_STRATEGY_MAP: dict[str, type[PayrollStrategy]] = {
    "simple": SimpleStrategy,
    "standard": StandardStrategy,
    "enterprise": EnterpriseStrategy,
}

# Singleton instances (stateless strategies — safe to reuse)
_STRATEGY_INSTANCES: dict[str, PayrollStrategy] = {
    k: cls() for k, cls in _STRATEGY_MAP.items()
}


def resolve_strategy(calculation_mode: str | None = None) -> PayrollStrategy:
    """Return the strategy instance for the given calculation mode.

    Falls back to ``StandardStrategy`` for unknown / ``None`` modes.
    """
    key = (calculation_mode or "standard").lower().strip()
    return _STRATEGY_INSTANCES.get(key, _STRATEGY_INSTANCES["standard"])


def calculate_payroll(
    ctx: PayrollContext,
    calculation_mode: str | None = None,
) -> PayrollResult:
    """Convenience entry point — resolve strategy and calculate in one call.

    This is the single function that the rest of the payroll module should
    call.  It replaces the old ``_calculate_employee_monthly_payroll()``
    and the duplicated logic in ``preview_payroll_run``.
    """
    strategy = resolve_strategy(calculation_mode)
    return strategy.calculate(ctx)


def build_context_from_employee(
    employee,
    gross: Decimal,
    basic: Decimal,
    hra: Decimal = Decimal("0"),
    special_allowance: Decimal = Decimal("0"),
    overtime: Decimal = Decimal("0"),
    additional_compensation: Decimal = Decimal("0"),
    unpaid_leave_days: int = 0,
    country: str = "IN",
    rate_map: dict | None = None,
    slabs: list | None = None,
    payroll_days: int = PAYROLL_DAYS,
    work_state: str | None = None,
    state_rate_map: dict | None = None,
    state_slabs: list | None = None,
    employer_tax_profiles: dict | None = None,
    reciprocity_suppresses_work_state: bool = False,
    resident_state_rate_map: dict | None = None,
    resident_state_slabs: list | None = None,
    locality_rate=None,
) -> PayrollContext:
    """Helper to build a PayrollContext from a PayrollEmployee ORM object
    and pre-computed salary components. Tax-profile fields (tax_code,
    ni_category, study_loan_plan/balance, church_tax_liable) are read
    directly off `employee` here rather than added as more explicit
    params to every caller — they're genuinely employee-sourced, exactly
    like the identity/bank fields _compute_payslip_values already reads
    straight off `employee` elsewhere."""
    return PayrollContext(
        gross=gross,
        basic=basic,
        hra=hra,
        special_allowance=special_allowance,
        overtime=overtime,
        additional_compensation=additional_compensation,
        unpaid_leave_days=unpaid_leave_days,
        payroll_days=payroll_days,
        country=country,
        rate_map=rate_map or {},
        slabs=slabs or [],
        work_state=work_state,
        state_rate_map=state_rate_map or {},
        state_slabs=state_slabs or [],
        employer_tax_profiles=employer_tax_profiles or {},
        reciprocity_suppresses_work_state=reciprocity_suppresses_work_state,
        resident_state_rate_map=resident_state_rate_map or {},
        resident_state_slabs=resident_state_slabs or [],
        locality_rate=locality_rate,
        tax_code=getattr(employee, "tax_code", None),
        ni_category=getattr(employee, "ni_category", None),
        study_loan_plan=getattr(employee, "study_loan_plan", None),
        study_loan_balance=getattr(employee, "study_loan_balance", None),
        church_tax_liable=bool(getattr(employee, "church_tax_liable", False)),
        tax_regime=getattr(employee, "tax_regime", None),
        pay_frequency=getattr(employee, "pay_frequency", None) or "Monthly",
        w4_filing_status=getattr(employee, "w4_filing_status", None),
        w4_form_vintage=getattr(employee, "w4_form_vintage", None),
        td1_claim_amount=getattr(employee, "td1_claim_amount", None),
        td1_additional_tax=getattr(employee, "td1_additional_tax", None),
        cpp_qpp_election_status=getattr(employee, "cpp_qpp_election_status", None),
    )
