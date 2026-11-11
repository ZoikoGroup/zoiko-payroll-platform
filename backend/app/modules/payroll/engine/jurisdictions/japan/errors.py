"""Japan calculation errors shared by the engine and its pure helpers."""
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError

_COUNTRY = "JP"


class JapanCalculationBlockedError(MissingComplianceConfigurationError):
    def __init__(self, key: str, reason: str, organization_id: int = None):
        super().__init__(key, _COUNTRY, organization_id)
        self.reason = reason
        self.args = (f"Japan calculation blocked ({key}): {reason}",)
