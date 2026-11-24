"""Spain calculation errors and reason codes (ZP-ES-ENG-001, docs/spain).

A block code is the ``key`` of ESCalculationBlockedError; keyed() adds detail
after a colon (``ES_RATE_MISSING:es_cc``). A block stops this employee's
calculation with a clear message — never a guessed figure.
"""
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError

_COUNTRY = "ES"


class ESCalculationBlockedError(MissingComplianceConfigurationError):
    """A Spanish calculation that must not proceed: a pack value is missing, an
    employee or employer fact is missing or invalid, or the case is outside the
    launch scope (docs/spain). A MissingComplianceConfigurationError, so the
    existing MISSING_COMPLIANCE_CONFIGURATION 400 handler applies unchanged.
    Never falls back to the generic calculator."""

    def __init__(self, key: str, reason: str, organization_id: int = None):
        super().__init__(key, _COUNTRY, organization_id)
        self.reason = reason
        self.args = (f"Spain calculation blocked ({key}): {reason}",)


def keyed(code: str, detail) -> str:
    return f"{code}:{detail}"


SIMPLE_MODE_UNSUPPORTED = "ES_SIMPLE_MODE_UNSUPPORTED"
RATE_MISSING = "ES_RATE_MISSING"                          # a pack value the calculation needs is not configured
EMPLOYEE_FACT_MISSING = "ES_EMPLOYEE_FACT_MISSING"        # contract type / group / extra-pay policy ...
OUT_OF_SCOPE = "ES_OUT_OF_SCOPE"                          # ES-001: regimes / cases outside the launch wedge
PART_TIME_NOT_SUPPORTED = "ES_PART_TIME_NOT_SUPPORTED"    # G-04: no part-time hourly minimum bases
DAILY_GROUP_NOT_SUPPORTED = "ES_DAILY_GROUP_NOT_SUPPORTED"  # G-05: groups 8-11 (daily contributors)
AT_EP_RATE_MISSING = "ES_AT_EP_RATE_MISSING"              # G-03 / ES-008: employer's own premium tariff
BELOW_SMI = "ES_BELOW_SMI"                                # D11: below the minimum interprofessional wage
