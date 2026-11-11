"""modules/payroll/engine/countries/belgium.py
--------------------------------------------
Belgium (ZP-BE-ENG-001) — the calculation orchestrator over the bounded rule
modules in engine/jurisdictions/belgium/.

FAIL-CLOSED BY DESIGN UNTIL PHASE 5. ``calculate()`` always raises
BECalculationBlockedError(BE_ENGINE_NOT_BUILT). Belgium is registered in
standard._COUNTRY_CALC only so that it can never fall through to the generic
calculator, and resolver.calculate_payroll refuses simple mode for it.

BE-004: ordinary salaried and hourly payroll first; unsupported special
profiles block finalisation with an actionable reason.
BE-005: calculation readiness is separate from declaration / payment
readiness — nothing here implies either.

No statutory value lives in this module or anywhere in code: every rate,
threshold, band, rounding rule and date will be a signed, effective-dated pack
row, and unsigned ("[PENDING G1]") content blocks calculation.
"""
from __future__ import annotations

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.jurisdictions.belgium import errors as E
from app.modules.payroll.engine.jurisdictions.belgium.errors import BECalculationBlockedError

__all__ = ["BECalculationBlockedError", "calculate"]


def calculate(ctx: PayrollContext) -> dict:
    raise BECalculationBlockedError(
        E.ENGINE_NOT_BUILT,
        "the Belgian payroll engine is not built yet (ZP-BE-ENG-001 Phase 5); Belgian payroll cannot be "
        "calculated, previewed or committed.",
        organization_id=getattr(ctx, "organization_id", None),
    )
