"""modules/payroll/engine/countries/malaysia.py
---------------------------------------------
Malaysia (ZP-MY-ENG-001) — fail-closed calculation entry point.

Phase 0: the Malaysian engine does not exist yet, so EVERY calculation is
refused with a named reason. Registering this module in
standard._COUNTRY_CALC means a Malaysian context can never fall through to
the generic calculator and return a plausible but wrong net (spec: determine
applicability before calculation; unsupported cases fail closed). Phase 3
replaces `calculate` with the orchestrator over engine/jurisdictions/malaysia/*.

Pure module: no ORM, no clock, no network.
"""

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.jurisdictions.malaysia import errors as E
from app.modules.payroll.engine.jurisdictions.malaysia.errors import MYCalculationBlockedError  # noqa: F401 (re-export)


def calculate(ctx: PayrollContext) -> dict:
    raise MYCalculationBlockedError(
        E.ENGINE_NOT_BUILT,
        "Malaysian payroll calculation is not available yet (ZP-MY-ENG-001 Phase 3).",
        getattr(ctx, "organization_id", None),
    )
