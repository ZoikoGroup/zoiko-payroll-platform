"""modules/payroll/engine/countries/poland.py
-------------------------------------------
Poland (ZP-PL-ENG-001) — fail-closed calculation entry point.

Phase 0: the Polish engine does not exist yet, so EVERY calculation is
refused with a named reason. Registering this module in
standard._COUNTRY_CALC means a Polish context can never fall through to the
generic calculator and return a plausible but wrong net (spec: applicability
precedes calculation; unsupported cases fail closed). Phase 3 replaces
`calculate` with the orchestrator over engine/jurisdictions/poland/*.

Pure module: no ORM, no clock, no network (PL-021).
"""

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError

_COUNTRY = "PL"


class PLCalculationBlockedError(MissingComplianceConfigurationError):
    """A Polish statutory calculation that must not proceed — missing
    configured row, missing employee/employer fact, or an unsupported case.
    A MissingComplianceConfigurationError, so the existing
    MISSING_COMPLIANCE_CONFIGURATION 400 handler applies unchanged."""

    def __init__(self, key: str, reason: str, organization_id: int = None):
        super().__init__(key, _COUNTRY, organization_id)
        self.reason = reason
        self.args = (f"Poland calculation blocked ({key}): {reason}",)


def calculate(ctx: PayrollContext) -> dict:
    raise PLCalculationBlockedError(
        "PL_ENGINE_NOT_BUILT",
        "Polish payroll calculation is not available yet (ZP-PL-ENG-001 Phase 3).",
        getattr(ctx, "organization_id", None),
    )
