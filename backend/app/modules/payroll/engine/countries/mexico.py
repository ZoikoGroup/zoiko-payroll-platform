"""
engine/countries/mexico.py
--------------------------
Mexico payroll calculator (ZP-MX-ENG-001 v1.0). Pure: no ORM, no framework —
everything it reads will arrive on the PayrollContext (the mx_* fields in
engine/base.py), resolved by mexico_service.

Phase 0 (scaffolding): Mexico is dispatched here by engine/standard.py so it
can never fall through to the generic progressive-tax calculator, and every
calculation BLOCKS (MX-001: unsupported -> BLOCKED). The federal engine (ISR,
subsidy, SBC, IMSS branches, CEAV, INFONAVIT) and the state ISN overlay land
in Phase 5 under engine/jurisdictions/mexico/.

The result will be one `mx_result` dict, like the Netherlands' `nl_result`.
"""

from __future__ import annotations

from .shared import MissingComplianceConfigurationError

_COUNTRY = "MX"
ENGINE_VERSION = "MX-ENGINE-2026.0"

# engine/fallback_registry.py sentinel: Mexico has NO hard-coded statutory
# fallback (master rules 2-3) — a missing pack row BLOCKS. Defined so the
# registry's attribute lookups resolve to a real (None) value.
MX_NO_FALLBACK = None


class MexicoCalculationBlockedError(MissingComplianceConfigurationError):
    """A Mexican statutory calculation that must not proceed — missing pack
    row, missing worker/employer fact, unsupported regime or state, or a case
    not certified in this release (MX-001). `key` is the coded reason."""

    def __init__(self, key: str, reason: str, organization_id: int = None):
        super().__init__(key, _COUNTRY, organization_id)
        self.reason = reason
        self.args = (f"Mexico calculation blocked ({key}): {reason}",)


MXBlock = MexicoCalculationBlockedError


def calculate(ctx) -> dict:
    if (ctx.country or "").upper() != _COUNTRY:
        return {}
    raise MXBlock("MX_ENGINE_NOT_IMPLEMENTED",
                  "the Mexico payroll engine is not built yet (ZP-MX-ENG-001 Phase 5); no Mexican payroll is "
                  "calculated until then",
                  getattr(ctx, "mx_organization_id", None))
