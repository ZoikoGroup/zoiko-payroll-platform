"""Malaysia calculation errors and reason codes (ZP-MY-ENG-001).

A block code is the ``key`` of MYCalculationBlockedError; keyed() adds detail
after a colon (``MY_ROW_MISSING:my_min_wage_monthly``). Later phases add the
obligation-specific codes here (Phase 3 contributions, Phase 4 PCB, Phase 6
labour).
"""
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError

_COUNTRY = "MY"


class MYCalculationBlockedError(MissingComplianceConfigurationError):
    """A Malaysian statutory calculation that must not proceed — missing
    configured row, missing or contradictory fact, or an unsupported case. A
    MissingComplianceConfigurationError, so the existing
    MISSING_COMPLIANCE_CONFIGURATION 400 handler applies unchanged."""

    def __init__(self, key: str, reason: str, organization_id: int = None):
        super().__init__(key, _COUNTRY, organization_id)
        self.reason = reason
        self.args = (f"Malaysia calculation blocked ({key}): {reason}",)


def keyed(code: str, detail) -> str:
    return f"{code}:{detail}"


# ── block codes (Phase 0) ───────────────────────────────────────────────────
ENGINE_NOT_BUILT = "MY_ENGINE_NOT_BUILT"
SIMPLE_MODE_UNSUPPORTED = "MY_SIMPLE_MODE_UNSUPPORTED"
