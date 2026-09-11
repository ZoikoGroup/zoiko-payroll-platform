"""engine/jurisdictions/germany/statutory/deuv.py
------------------------------
DEÜV (Datenübermittlungs-Verordnung) social insurance notification boundary.

Phase 8BR. Design and architectural boundary for German statutory social
insurance electronic reporting (Meldungen zur Sozialversicherung per DEÜV).

In accordance with Phase 8BF/8K patterns, this module establishes:
- The abstract transmitter interface (`DeuvTransmitter`)
- The deterministic fail-closed implementation (`UnavailableDeuvTransmitter`)
- The resolver function (`resolve_deuv_transmitter`)
- The transmission request and result contracts
- Specification-independent lifecycle state machine (DRAFT -> VALIDATED -> SUBMISSION_BLOCKED / READY -> RETRY)

As documented in `docs/DEUV_PRODUCTION_REQUIREMENTS.md`, the official DEÜV
XML/Datensatz schema from GKV-Spitzenverband is an external dependency.
No field definitions or schemas are invented here. When the authoritative
specification arrives, integration requires only schema mapping onto this
scaffolding, with zero architectural redesign needed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

from ..pap.core import GermanyCalculationError


class GermanyDeuvUnavailableError(GermanyCalculationError):
    """Raised when attempting DEÜV transmission while the official
    Datensatz specification or clearinghouse connector is unprovisioned."""

    def __init__(self, message: str, trace=None):
        super().__init__("GERMANY_DEUV_UNAVAILABLE", message, trace)


# Standard DEÜV Meldung (Notification) categories recognized by statute (§28a SGB IV)
# Used as high-level event types without inventing internal field formats.
DEUV_MESSAGE_TYPES = (
    "ANMELDUNG",            # Begin of employment (Grund 10)
    "ABMELDUNG",           # End of employment (Grund 30)
    "JAHRESMELDUNG",       # Annual notification (Grund 50)
    "UNTERBRECHUNG",       # Interruption without pay (Grund 51)
    "BEENDIGUNG",          # End of insurable status
    "STORNIERUNG",         # Cancellation of previous notification
    "KORREKTUR",           # Correction notification
)

DEUV_TRANSMISSION_STATUSES = (
    "DRAFT",
    "VALIDATED",
    "READY",
    "BLOCKED_SPECIFICATION",
    "SUBMISSION_FAILED",
    "RETRY_PENDING",
)


@dataclass(frozen=True)
class DeuvTransmissionRequest:
    """Specification-independent submission request contract.
    Encapsulates all necessary operational and correlation metadata."""

    organization_id: int
    message_type: str
    period_start: date
    period_end: date
    employee_id: Optional[int] = None
    betriebsnummer_employer: Optional[str] = None
    versicherungsnummer_employee: Optional[str] = None
    payload_summary: Dict[str, Any] = field(default_factory=dict)

    def validate_request_bounds(self) -> None:
        """Validate structural boundaries without guessing statutory payload fields."""
        if not self.organization_id:
            raise GermanyDeuvUnavailableError("organization_id must be provided.")
        if self.message_type not in DEUV_MESSAGE_TYPES:
            raise GermanyDeuvUnavailableError(
                f"Unknown DEÜV message type: {self.message_type!r}. Supported types: {DEUV_MESSAGE_TYPES}"
            )
        if self.period_end < self.period_start:
            raise GermanyDeuvUnavailableError("period_end cannot precede period_start.")


@dataclass(frozen=True)
class DeuvTransmissionResult:
    """Result contract returned by an active transmitter."""

    transmission_reference: str
    acknowledged_at: date
    clearinghouse_status: str
    raw_response_summary: Optional[Dict[str, Any]] = None


class DeuvTransmitter(ABC):
    """Abstract interface for DEÜV social insurance notifications."""

    @abstractmethod
    def transmit(self, request: DeuvTransmissionRequest) -> DeuvTransmissionResult:
        """Transmit the notification to the statutory clearinghouse."""
        raise NotImplementedError


class UnavailableDeuvTransmitter(DeuvTransmitter):
    """Fail-closed transmitter implementation.
    Guarantees deterministic rejection with actionable diagnostic feedback
    until the official GKV-Spitzenverband Datensatz specification is acquired."""

    def __init__(self, reason: str):
        self._reason = reason

    def transmit(self, request: DeuvTransmissionRequest) -> DeuvTransmissionResult:
        request.validate_request_bounds()
        raise GermanyDeuvUnavailableError(self._reason)


def resolve_deuv_transmitter(config=None) -> DeuvTransmitter:
    """Return the active DeuvTransmitter.
    Currently always returns UnavailableDeuvTransmitter to enforce fail-closed
    behavior while official GKV-Spitzenverband Datensatz schemas are pending."""
    return UnavailableDeuvTransmitter(
        "No DEÜV transmission connector is implemented. The official DEÜV Datensatz "
        "and XML schema must be acquired from GKV-Spitzenverband before electronic "
        "social insurance notifications can be transmitted. "
        "See docs/DEUV_PRODUCTION_REQUIREMENTS.md. (SPECIFICATION_REQUIRED)"
    )
