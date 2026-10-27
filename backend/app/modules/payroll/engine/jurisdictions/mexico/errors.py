"""
engine/jurisdictions/mexico/errors.py
-------------------------------------
The Mexican block error (MX-001: unsupported -> BLOCKED). Defined here so
the pure helper modules can raise it without importing the orchestrator;
engine/countries/mexico.py re-exports it under its historical names.

MexicoActionRefusedError (completion W5-4, OOS-11) is the same error for a
refusal that is not a calculation — four-eyes, payments, filings, the pilot,
the transfer, the journal, the CFDI lifecycle. A subclass, so every handler,
status code and field is unchanged; only the wording differs.
"""

from __future__ import annotations

from ...countries.shared import MissingComplianceConfigurationError

_COUNTRY = "MX"


class MexicoCalculationBlockedError(MissingComplianceConfigurationError):
    """A Mexican statutory calculation that must not proceed — missing pack
    row, missing worker/employer fact, unsupported regime or state, or a case
    not certified in this release (MX-001). `key` is the coded reason;
    `reasons` lists every (code, detail) when preflight collected several."""

    def __init__(self, key: str, reason: str, organization_id: int = None, reasons: list = None):
        super().__init__(key, _COUNTRY, organization_id)
        self.reason = reason
        self.reasons = list(reasons) if reasons else [(key, reason)]
        self.args = (f"Mexico calculation blocked ({key}): {reason}",)


class MexicoActionRefusedError(MexicoCalculationBlockedError):
    """A Mexican action refused for a reason that is not a calculation
    (OOS-11): worded "Mexico action refused (<code>): <reason>"."""

    def __init__(self, key: str, reason: str, organization_id: int = None, reasons: list = None):
        super().__init__(key, reason, organization_id, reasons)
        self.args = (f"Mexico action refused ({key}): {reason}",)


MXBlock = MexicoCalculationBlockedError
MXRefuse = MexicoActionRefusedError
