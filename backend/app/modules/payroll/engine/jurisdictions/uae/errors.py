"""United Arab Emirates calculation errors and reason codes (ZP-AE-ENG-001).

A block code is the ``key`` of AECalculationBlockedError; keyed() adds detail
after a colon (``AE_RATE_MISSING:ae_gpssa_law57``). A block stops this
employee's calculation with a clear message — never a guessed figure.
"""
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError

_COUNTRY = "AE"


class AECalculationBlockedError(MissingComplianceConfigurationError):
    """A UAE calculation that must not proceed: a pack value is missing, an
    employee fact is missing or invalid, or the case is outside the launch
    scope. A MissingComplianceConfigurationError, so the existing
    MISSING_COMPLIANCE_CONFIGURATION 400 handler applies unchanged. Never falls
    back to the generic calculator."""

    def __init__(self, key: str, reason: str, organization_id: int = None):
        super().__init__(key, _COUNTRY, organization_id)
        self.reason = reason
        self.args = (f"United Arab Emirates calculation blocked ({key}): {reason}",)


def keyed(code: str, detail) -> str:
    return f"{code}:{detail}"


SIMPLE_MODE_UNSUPPORTED = "AE_SIMPLE_MODE_UNSUPPORTED"
RATE_MISSING = "AE_RATE_MISSING"                      # a pack value the calculation needs is not configured
EMPLOYEE_FACT_MISSING = "AE_EMPLOYEE_FACT_MISSING"    # nationality / scheme / salary / joining date ...
OUT_OF_SCOPE = "AE_OUT_OF_SCOPE"                      # DIFC / ADGM (AE-002), non-monthly pay
GCC_RATES_NOT_CONFIGURED = "AE_GCC_RATES_NOT_CONFIGURED"   # spec §8 gives no GCC home-country rates
PART_TIME_EOS_NOT_SUPPORTED = "AE_PART_TIME_EOS_NOT_SUPPORTED"   # AE-030: no part-time formula in the spec
PENSION_SALARY_BELOW_MINIMUM = "AE_PENSION_SALARY_BELOW_MINIMUM"
EMIRATI_MINIMUM_SALARY = "AE_EMIRATI_MINIMUM_SALARY"  # AE-014
