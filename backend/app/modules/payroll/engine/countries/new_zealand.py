"""New Zealand (ZP-NZ-ENG-001) payday engine - pure and fail-closed.

Phase 0: registered in standard._COUNTRY_CALC so New Zealand never falls
through to the generic calculator. Every calculation is refused until the
Phase 3 engine and a signed content pack exist.
"""
from __future__ import annotations

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.jurisdictions.new_zealand.errors import NZCalculationBlockedError

__all__ = ["NZCalculationBlockedError", "calculate"]


def calculate(ctx: PayrollContext):
    raise NZCalculationBlockedError(
        "NZ_ENGINE_NOT_BUILT",
        "New Zealand payroll calculation is not available yet; no statutory content pack is signed.",
        getattr(ctx, "organization_id", None),
    )
