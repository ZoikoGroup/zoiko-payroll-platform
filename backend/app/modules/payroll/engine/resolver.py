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
) -> PayrollContext:
    """Helper to build a PayrollContext from a PayrollEmployee ORM object
    and pre-computed salary components."""
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
    )
