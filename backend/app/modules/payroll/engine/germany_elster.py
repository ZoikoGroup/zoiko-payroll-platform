"""engine/germany_elster.py
--------------------------------
ELSTER (ELektronische STeuerERklärung) transmission boundary.

Phase 8BF. Design-only, by explicit instruction: Zoiko holds no ELSTER
organizational certificate and no BZSt employer registration, so no real
transmitter is implemented here — only the interface a future, separately
-authorized phase would implement, plus the one concrete implementation
that always fails closed. This deliberately mirrors
germany_pap/elstam.py's own ElstamProvider / UnavailableElstamProvider /
resolve_elstam_provider() pattern exactly (itself modeled on
germany_pap/core.py's PapExecutor / UnavailablePapExecutor /
resolve_pap_executor()): same shape, same fail-closed guarantee, same
"one production swap point" idea.

Nothing in service.py's transmission-record functions calls a real ELSTER
endpoint — they only prepare and validate a GermanyElsterTransmission row
(models.py) and then, via resolve_elster_transmitter() below, deterministically
land on BLOCKED_EXTERNAL. No certificate material, no ERiC library
integration, no payload actually leaves this application. Configuring a
GermanyElsterCertificateConfig.is_configured=True does NOT by itself
unblock transmission — resolve_elster_transmitter() ignores it entirely
today, exactly as documented on that model, because is_configured only
answers "does a certificate reference exist", never "is a real ELSTER
client wired up" (it isn't, in this codebase, at all).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .germany_pap.core import GermanyCalculationError


class GermanyElsterUnavailableError(GermanyCalculationError):
    """No ELSTER transmission connector exists/is authorized in this
    codebase (Phase 8BF). Raised by UnavailableElsterTransmitter.transmit()
    — never returns a fabricated transmission acknowledgement."""

    def __init__(self, message: str, trace=None):
        super().__init__("GERMANY_ELSTER_UNAVAILABLE", message, trace)


@dataclass
class ElsterTransmissionRequest:
    """What a real transmitter would need to submit one filing. Mirrors
    ElstamQuery's own "future-mapping, not future-redesign" intent."""

    organization_id: int
    transmission_type: str
    period_start: date
    period_end: date
    payload_summary: dict = field(default_factory=dict)


@dataclass
class ElsterTransmissionResult:
    """What a real transmitter would return on success — a Transferticket
    (ELSTER's own delivery-confirmation identifier) and the authority's
    response. Never constructed by any code in this codebase today; no
    Transferticket is ever fabricated."""

    transferticket: str
    acknowledged_at: date
    raw_response_summary: Optional[dict] = None


class ElsterTransmitter(ABC):
    """Interface a future, separately-authorized phase implements once
    Zoiko holds a real ELSTER organizational certificate and BZSt employer
    registration (and, per the ERiC SDK's own licensing terms, a formal
    software-integration agreement). Deliberately abstract here — this
    phase does not, and per its own explicit instructions must not,
    implement or simulate a concrete ELSTER connection."""

    @abstractmethod
    def transmit(self, request: ElsterTransmissionRequest) -> ElsterTransmissionResult:
        raise NotImplementedError


class UnavailableElsterTransmitter(ElsterTransmitter):
    """The only ElsterTransmitter implementation that exists in this
    codebase. Always raises, deterministically, with a clear reason —
    never returns a fabricated Transferticket. Mirrors
    UnavailableElstamProvider / UnavailablePapExecutor exactly."""

    def __init__(self, reason: str):
        self._reason = reason

    def transmit(self, request: ElsterTransmissionRequest) -> ElsterTransmissionResult:
        raise GermanyElsterUnavailableError(self._reason)


def resolve_elster_transmitter(certificate_config=None) -> ElsterTransmitter:
    """Return the ElsterTransmitter to use. Today this ALWAYS returns
    UnavailableElsterTransmitter, regardless of `certificate_config`
    (including a configured one — see module docstring for why), because
    no concrete ELSTER connector exists in this codebase and no
    authorization to build one has been given. Kept as a function (not a
    hardcoded call site) so a future phase's change is a one-line swap,
    matching resolve_pap_executor()'s and resolve_elstam_provider()'s own
    stated rationale."""
    return UnavailableElsterTransmitter(
        "No ELSTER transmission connector is implemented or authorized in "
        "this codebase. Zoiko does not hold an ELSTER organizational "
        "certificate, a BZSt employer registration, or an ERiC SDK "
        "integration agreement, and no compliance/legal authorization to "
        "transmit live ELSTER filings has been given. This transmission "
        "record stays BLOCKED_EXTERNAL until a future, explicitly-"
        "authorized phase implements a real connector here."
    )
