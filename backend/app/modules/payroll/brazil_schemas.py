"""
modules/payroll/brazil_schemas.py
---------------------------------
Pydantic schemas for the Brazil (CLT) payroll API (ZP-BR-ENG-001) — camelCase,
like netherlands_schemas.py / mexico_schemas.py.

Inputs forbid unknown fields (`extra="forbid"`), so a stray field — for
example a pasted secret next to a credential reference — is refused rather
than silently ignored, and carry no defaults on identity or statutory fields.
The draft Phase 1/2 profile schemas were removed in Phase 3 (never used by any
route); the employee statutory-profile schemas arrive with Phase 4.
"""

from __future__ import annotations

import re as _re
from datetime import date
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class _BRIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    def to_service(self) -> dict:
        return {_re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower(): v for k, v in self.model_dump().items()}


# ── Phase 3: employer onboarding ─────────────────────────────────────────────

class BREmployerCreate(_BRIn):
    effectiveFrom: date
    cnpjRoot: str
    legalName: str
    tradeName: Optional[str] = None
    taxClassification: str
    cnaePreponderant: str
    esocialEnvironment: str
    contactName: str
    contactCpf: str
    contactEmail: str
    contactPhone: Optional[str] = None


class BREstablishmentCreate(_BRIn):
    activeFrom: date
    cnpj: str
    establishmentName: str
    isHeadquarters: bool
    cnae: str
    fpasCode: str
    thirdPartyCode: str
    thirdPartyPct: Decimal
    fpasEvidenceRef: str
    lotacaoCode: str
    postalCode: str
    streetAddress: str
    neighborhood: str
    cityIbgeCode: str
    stateUf: str
    judicialProcessId: Optional[str] = None


class BRDeactivate(_BRIn):
    activeTo: date


class BRRiskAssignmentCreate(_BRIn):
    calendarYear: int
    ratPct: Decimal
    fapFactor: Decimal
    evidenceRef: str


class BRCprbOptionCreate(_BRIn):
    calendarYear: int
    opted: bool
    sectorReference: Optional[str] = None
    cprbRatePct: Optional[Decimal] = None
    evidenceRef: str


class BRCredentialCreate(_BRIn):
    kind: str
    secretRef: str


# ── Phase 4: employee statutory-profile child records ────────────────────────

class BRConcurrentInssDeclarationCreate(_BRIn):
    competenceMonth: date
    baseExternal: Decimal
    deductedExternal: Decimal
    evidenceRef: Optional[str] = None


class BRAlimonyOrderCreate(_BRIn):
    orderReference: str
    method: str
    fixedAmount: Optional[Decimal] = None
    percentage: Optional[Decimal] = None
    base: Optional[str] = None
    effectiveFrom: date
    evidenceRef: Optional[str] = None


class BRAlimonyOrderClose(_BRIn):
    effectiveTo: date


class BRValeTransporteElectionCreate(_BRIn):
    elected: bool
    dailyCost: Optional[Decimal] = None
    effectiveFrom: date
    evidenceRef: Optional[str] = None


# ── Readiness (Phase 0) ──────────────────────────────────────────────────────

class BRGateState(BaseModel):
    gate: str
    label: str
    state: str  # OPEN / SUBMITTED / SIGNED


class BRReadinessResponse(BaseModel):
    jurisdiction: str
    spec: str
    available: bool
    engineVersion: str
    phase: int
    gates: List[BRGateState]
    note: str
