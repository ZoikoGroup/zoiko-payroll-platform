"""ELStAM (Elektronische LohnSteuerAbzugsMerkmale) retrieval boundary.

Phase 8K. Design-only, by explicit instruction: Zoiko holds no ELSTER
organizational certificate, no BZSt employer registration, and no legal/
compliance authorization to query live ELStAM data, so no real connector
is implemented here — only the interface a future, separately-authorized
phase would implement, plus the one concrete implementation that always
fails closed. This deliberately mirrors core.py's PapExecutor /
UnavailablePapExecutor / resolve_pap_executor() pattern exactly: same
shape, same fail-closed guarantee, same "one production swap point" idea.

Today, Zoiko's EmployeeStatutoryProfile (Phase 2) is populated by manual
data entry or by the employer manually transcribing the employee's paper
"Bescheinigung für den Lohnsteuerabzug" (de_elstam_source=
FALLBACK_CERTIFICATE, §39c EStG) — not by calling this module. Nothing in
countries/germany.py or service.py calls resolve_elstam_provider(); it
exists purely as the documented boundary for a future phase to fill in,
so that phase has a single, obvious swap point instead of a call-site
hunt, exactly as resolve_pap_executor()'s own docstring explains for PAP.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from .core import GermanyCalculationError


class GermanyElstamDataUnavailableError(GermanyCalculationError):
    """No ELStAM retrieval connector exists/is authorized in this
    codebase (Phase 8K). Raised by UnavailableElstamProvider.fetch() —
    never by the production calculation path, since that path never
    calls this module at all today (see module docstring)."""

    def __init__(self, message: str, trace=None):
        super().__init__("GERMANY_ELSTAM_DATA_UNAVAILABLE", message, trace)


@dataclass
class ElstamQuery:
    """What a real connector would need to look up one employee's
    current ELStAM record. `as_of` matters because ELStAM values are
    themselves effective-dated at the tax-authority end (change lists),
    independent of EmployeeStatutoryProfile's own effective_from/_to."""

    employee_id: int
    organization_id: int
    as_of: date


@dataclass
class ElstamResult:
    """What a real connector would return, using the same field
    identifiers as PapInputContract/EmployeeStatutoryProfile so a future
    phase's mapping is a rename, not a redesign. Never constructed by
    any code in this codebase today — no ELStAM values are invented."""

    tax_class: str
    factor: Optional[Decimal]
    church_tax_liable: bool
    child_allowance_count: Decimal
    retrieved_at: date
    elstam_change_list_reference: Optional[str] = None
    jfreib_cents: int = 0
    lzzfreib_cents: int = 0
    jhinzu_cents: int = 0
    lzzhinzu_cents: int = 0
    warnings: list = field(default_factory=list)


class ElstamProvider(ABC):
    """Interface a future, separately-authorized phase implements once
    Zoiko holds a real ELSTER organizational certificate and BZSt
    employer registration. Deliberately abstract here — this phase does
    not, and per its own explicit instructions must not, implement or
    simulate a concrete ELStAM/ELSTER connection."""

    @abstractmethod
    def fetch(self, query: ElstamQuery) -> ElstamResult:
        raise NotImplementedError


class UnavailableElstamProvider(ElstamProvider):
    """The only ElstamProvider implementation that exists in this
    codebase. Always raises, deterministically, with a clear reason —
    never returns a fabricated ELStAM value. Mirrors
    UnavailablePapExecutor exactly."""

    def __init__(self, reason: str):
        self._reason = reason

    def fetch(self, query: ElstamQuery) -> ElstamResult:
        raise GermanyElstamDataUnavailableError(self._reason)


def resolve_elstam_provider() -> ElstamProvider:
    """Return the ElstamProvider to use. Today this ALWAYS returns
    UnavailableElstamProvider, regardless of any argument, because no
    concrete ELStAM/ELSTER connector exists in this codebase and no
    authorization to build one has been given — see module docstring.
    Kept as a function (not a hardcoded call site) so a future phase's
    change is a one-line swap, matching resolve_pap_executor()'s own
    stated rationale."""
    return UnavailableElstamProvider(
        "No ELStAM/ELSTER retrieval connector is implemented or authorized in "
        "this codebase. Zoiko does not hold an ELSTER organizational "
        "certificate or BZSt employer registration, and no compliance/legal "
        "authorization to query live ELStAM data has been given. Record "
        "EmployeeStatutoryProfile tax fields manually or from the employee's "
        "own 'Bescheinigung für den Lohnsteuerabzug' "
        "(de_elstam_source=FALLBACK_CERTIFICATE) until a future, explicitly-"
        "authorized phase implements a real connector here."
    )
