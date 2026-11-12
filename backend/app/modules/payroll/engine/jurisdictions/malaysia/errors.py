"""Malaysia calculation errors and reason codes (ZP-MY-ENG-001).

A block code is the ``key`` of MYCalculationBlockedError; keyed() adds detail
after a colon (``MY_ROW_MISSING:my_min_wage_monthly``). Exception codes are
not blocks: they ride on ``my_result["exceptions"]`` and stop run APPROVAL
(spec §13 payroll preflight).

MY-008: a missing fact fails only the AFFECTED obligation. The orchestrator
evaluates every obligation separately and, if any is blocked, refuses the
payslip with MY_OBLIGATIONS_BLOCKED listing each blocked obligation and its
reason (``blocked``) plus what was computed (``partial``) — never a net built
on a skipped obligation.
"""
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError

_COUNTRY = "MY"


class MYCalculationBlockedError(MissingComplianceConfigurationError):
    """A Malaysian statutory calculation that must not proceed — missing
    configured row, missing or contradictory fact, or an unsupported case. A
    MissingComplianceConfigurationError, so the existing
    MISSING_COMPLIANCE_CONFIGURATION 400 handler applies unchanged."""

    def __init__(self, key: str, reason: str, organization_id: int = None, blocked: dict = None,
                 partial: dict = None):
        super().__init__(key, _COUNTRY, organization_id)
        self.reason = reason
        self.blocked = blocked or {}
        self.partial = partial
        self.args = (f"Malaysia calculation blocked ({key}): {reason}",)


def keyed(code: str, detail) -> str:
    return f"{code}:{detail}"


# ── whole-payslip blocks ─────────────────────────────────────────────────────
ENGINE_NOT_BUILT = "MY_ENGINE_NOT_BUILT"
SIMPLE_MODE_UNSUPPORTED = "MY_SIMPLE_MODE_UNSUPPORTED"
PAY_DATE_MISSING = "MY_PAY_DATE_MISSING"
PERIOD_MISSING = "MY_PERIOD_MISSING"
PROFILE_MISSING = "MY_PROFILE_MISSING"
PROFILE_NOT_ACTIVE = "MY_PROFILE_NOT_ACTIVE"
REGISTRATION_MISSING = "MY_REGISTRATION_MISSING"
REGISTRATION_NOT_ACTIVE = "MY_REGISTRATION_NOT_ACTIVE"
UNSUPPORTED_CONTRACT = "MY_UNSUPPORTED_CONTRACT"
UNSUPPORTED_DOMESTIC = "MY_UNSUPPORTED_DOMESTIC"
PAY_FREQUENCY_UNSUPPORTED = "MY_PAY_FREQUENCY_UNSUPPORTED"
COMPONENTS_UNMAPPED = "MY_COMPONENTS_UNMAPPED"
COMPONENT_UNKNOWN = "MY_COMPONENT_UNKNOWN"
COMPONENTS_MISMATCH = "MY_COMPONENTS_MISMATCH"
OBLIGATIONS_BLOCKED = "MY_OBLIGATIONS_BLOCKED"

# ── pack / content ───────────────────────────────────────────────────────────
PACK_UNSIGNED = "MY_PACK_UNSIGNED"
ROW_MISSING = "MY_ROW_MISSING"
TABLE_EMPTY = "MY_TABLE_EMPTY"
SCHEDULE_ROW_MISSING = "MY_SCHEDULE_ROW_MISSING"
POLICY_PENDING = "MY_POLICY_PENDING"
POLICY_NOT_SUPPORTED = "MY_POLICY_NOT_SUPPORTED"
EARNING_CLASS_MISSING = "MY_EARNING_CLASS_MISSING"
EARNING_CLASS_REVIEW = "MY_EARNING_CLASS_REVIEW"

# ── per-obligation blocks (MY-008) ───────────────────────────────────────────
FACT_MISSING = "MY_FACT_MISSING"
FACT_CONFLICT = "MY_FACT_CONFLICT"
EPF_AGE_TRANSITION = "MY_EPF_AGE_TRANSITION"
EPF_VOLUNTARY_EXCESS_UNSUPPORTED = "MY_EPF_VOLUNTARY_EXCESS_UNSUPPORTED"
EPF_ABOVE_SCHEDULE = "MY_EPF_ABOVE_SCHEDULE"
HRD_CATEGORY_NOT_IN_FORCE = "MY_HRD_CATEGORY_NOT_IN_FORCE"
PCB_SPEC_NOT_ARCHIVED = "MY_PCB_SPEC_NOT_ARCHIVED"

# ── run exceptions (not blocks) ──────────────────────────────────────────────
EXC_MIN_WAGE_BREACH = "MIN_WAGE_BREACH"
EXC_MIN_WAGE_NOT_EVALUATED = "MIN_WAGE_NOT_EVALUATED"
EXC_NEGATIVE_NET = "NEGATIVE_NET"
