"""Belgium calculation errors and reason codes (ZP-BE-ENG-001 BE-004 / BE-005).

A block code is the ``key`` of BECalculationBlockedError; keyed() adds detail
after a colon (``BE_ROW_MISSING:be_rounding_onss``). Exception codes are not
blocks: once the engine exists (Phase 5) they ride on ``be_result["exceptions"]``
and stop run approval.

Phase 1: only the fail-closed scaffold codes exist. The engine always blocks.
"""
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError

_COUNTRY = "BE"


class BECalculationBlockedError(MissingComplianceConfigurationError):
    """A Belgian statutory calculation that must not proceed — engine not built,
    missing classification or rule, unsigned content, or an unsupported worker
    category / special regime. A MissingComplianceConfigurationError, so the
    existing MISSING_COMPLIANCE_CONFIGURATION 400 handler applies unchanged.
    Never falls back to the generic calculator or simple mode."""

    def __init__(self, key: str, reason: str, organization_id: int = None):
        super().__init__(key, _COUNTRY, organization_id)
        self.reason = reason
        self.args = (f"Belgium calculation blocked ({key}): {reason}",)


def keyed(code: str, detail) -> str:
    return f"{code}:{detail}"


# ── block codes ─────────────────────────────────────────────────────────────
SIMPLE_MODE_UNSUPPORTED = "BE_SIMPLE_MODE_UNSUPPORTED"
ENGINE_NOT_BUILT = "BE_ENGINE_NOT_BUILT"
# Phase 3A (pack reader): content not signed, empty, or decided NOT_SUPPORTED.
CONTENT_PENDING = "BE_CONTENT_PENDING"
FEATURE_BLOCKED = "BE_FEATURE_BLOCKED"
ROW_MISSING = "BE_ROW_MISSING"
TABLE_EMPTY = "BE_TABLE_EMPTY"
ROUNDING_KEY_INVALID = "BE_ROUNDING_KEY_INVALID"

# ── exception codes (not blocks) ────────────────────────────────────────────
# Special social security contribution: no spec requirement ID; pending
# external specialist confirmation (gap G-06 / G-17, decision D7). The engine
# only ever emits this exception and never computes the contribution.
BSSC_PENDING = "BE_BSSC_PENDING"

# ── Block A2: applicability resolver (spec §2, fail closed) ─────────────────
PACK_MISSING = "BE_PACK_MISSING"
REGISTRATION_MISSING = "BE_REGISTRATION_MISSING"
REGISTRATION_NOT_ACTIVE = "BE_REGISTRATION_NOT_ACTIVE"
REGISTRATION_UNVERIFIED = "BE_REGISTRATION_UNVERIFIED"
EMPLOYER_CATEGORY_UNSUPPORTED = "BE_EMPLOYER_CATEGORY_UNSUPPORTED"
PROFILE_MISSING = "BE_PROFILE_MISSING"
PROFILE_NOT_ACTIVE = "BE_PROFILE_NOT_ACTIVE"
WORKER_CATEGORY_UNSUPPORTED = "BE_WORKER_CATEGORY_UNSUPPORTED"
WORKER_CODE_UNSUPPORTED = "BE_WORKER_CODE_UNSUPPORTED"
SPECIAL_STATUS_UNSUPPORTED = "BE_SPECIAL_STATUS_UNSUPPORTED"
FACT_MISSING = "BE_FACT_MISSING"
CONTRACT_UNSUPPORTED = "BE_CONTRACT_UNSUPPORTED"
FREQUENCY_UNSUPPORTED = "BE_FREQUENCY_UNSUPPORTED"
PAY_BASIS_UNSUPPORTED = "BE_PAY_BASIS_UNSUPPORTED"
CLASSIFICATION_MISSING = "BE_CLASSIFICATION_MISSING"
CLASSIFICATION_NOT_ACTIVE = "BE_CLASSIFICATION_NOT_ACTIVE"
JOINT_COMMITTEE_MISSING = "BE_JOINT_COMMITTEE_MISSING"
AGREEMENT_INVALID = "BE_AGREEMENT_INVALID"
UNIT_INVALID = "BE_UNIT_INVALID"
SCHEDULE_MISSING = "BE_SCHEDULE_MISSING"
SCHEDULE_AMBIGUOUS = "BE_SCHEDULE_AMBIGUOUS"
MID_PERIOD_CHANGE = "BE_MID_PERIOD_CLASSIFICATION_CHANGE"
# exceptions (not blocks): stop approval, never auto-pay (spec §2 / §4)
SECTOR_AGREEMENT_MISSING = "BE_SECTOR_AGREEMENT_MISSING"
SCALE_INPUT_MISSING = "BE_SCALE_INPUT_MISSING"
