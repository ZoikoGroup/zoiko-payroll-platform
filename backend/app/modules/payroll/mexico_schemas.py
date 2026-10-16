"""
payroll/mexico_schemas.py
-------------------------
Pydantic schemas for the Mexico payroll API (ZP-MX-ENG-001) — camelCase
request and response fields, like netherlands_schemas.py.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from pydantic import BaseModel


class MXGateState(BaseModel):
    gate: str
    label: str
    state: str  # OPEN / SUBMITTED / SIGNED


class MXReadinessResponse(BaseModel):
    jurisdiction: str
    spec: str
    available: bool
    engineVersion: str
    phase: int
    gates: List[MXGateState]
    note: str


class MXClassificationCreate(BaseModel):
    """Every statutory axis is decided explicitly — no field defaults to
    'taxable' (MX-005)."""
    organizationId: Optional[int] = None
    earningCode: str
    label: str
    effectiveFrom: date
    isrTreatment: str
    isrExemptRuleKey: Optional[str] = None
    sbcTreatment: str
    sbcExclusionCondition: Optional[str] = None
    infonavitIncluded: bool
    isnDefaultIncluded: bool
    isnStateOverrides: Optional[Dict[str, bool]] = None
    ptuWageBaseIncluded: bool
    cfdiNodeType: str
    cfdiConceptCode: Optional[str] = None

    def to_service(self) -> dict:
        return {"organization_id": self.organizationId, "earning_code": self.earningCode, "label": self.label,
                "effective_from": self.effectiveFrom, "isr_treatment": self.isrTreatment,
                "isr_exempt_rule_key": self.isrExemptRuleKey, "sbc_treatment": self.sbcTreatment,
                "sbc_exclusion_condition": self.sbcExclusionCondition, "infonavit_included": self.infonavitIncluded,
                "isn_default_included": self.isnDefaultIncluded, "isn_state_overrides": self.isnStateOverrides,
                "ptu_wage_base_included": self.ptuWageBaseIncluded, "cfdi_node_type": self.cfdiNodeType,
                "cfdi_concept_code": self.cfdiConceptCode}


class MXClassificationArchive(BaseModel):
    reason: str


class MXReleaseCreate(BaseModel):
    cfdiVersion: str
    complementVersion: str
    revision: Optional[str] = None
    xsdChecksum: Optional[str] = None
    catalogRelease: Optional[str] = None
    pacValidationVersion: Optional[str] = None
    sourceDocumentId: Optional[int] = None

    def to_service(self) -> dict:
        return {"cfdi_version": self.cfdiVersion, "complement_version": self.complementVersion,
                "revision": self.revision, "xsd_checksum": self.xsdChecksum, "catalog_release": self.catalogRelease,
                "pac_validation_version": self.pacValidationVersion, "source_document_id": self.sourceDocumentId}


class MXCatalogEntryCreate(BaseModel):
    catalogName: str
    code: str
    description: str
    validFrom: Optional[date] = None
    validTo: Optional[date] = None

    def to_service(self) -> dict:
        return {"catalog_name": self.catalogName, "code": self.code, "description": self.description,
                "valid_from": self.validFrom, "valid_to": self.validTo}


# ── Phase 3 — employer onboarding (organisation API, /api/payroll/mexico) ────
# extra="forbid": a field the API does not define (a password, a private key,
# a typed statutory value) is refused instead of silently dropped. No
# statutory or identity field has a default.

from pydantic import ConfigDict  # noqa: E402
from typing import Any  # noqa: E402


class _MXIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    def to_service(self) -> dict:
        import re as _re

        return {_re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower(): v for k, v in self.model_dump().items()}


class MXEmployerCreate(_MXIn):
    effectiveFrom: date
    taxpayerType: str
    rfc: str
    legalName: str
    fiscalRegimeCode: str
    fiscalPostalCode: str
    fiscalAddress: Optional[Dict[str, Any]] = None
    placeOfIssuePostalCode: str
    withholdingObligationActive: bool
    taxContact: Optional[Dict[str, Any]] = None
    bankContact: Optional[Dict[str, Any]] = None
    pacProvider: Optional[str] = None
    pacEnvironment: Optional[str] = None


class MXEstablishmentCreate(_MXIn):
    name: str
    stateCode: str
    municipality: str
    municipalityCode: Optional[str] = None
    postalCode: str
    imssRegistrationId: Optional[int] = None


class MXRegistrationCreate(_MXIn):
    registroPatronal: str
    riskClass: str
    fraction: str
    subdelegationCode: Optional[str] = None
    effectiveFrom: date
    effectiveTo: Optional[date] = None
    infonavitOperatingModel: Optional[str] = None


class MXInfonavitModel(_MXIn):
    infonavitOperatingModel: str


class MXClose(_MXIn):
    effectiveTo: date


class MXRiskPremiumCreate(_MXIn):
    determinationYear: int
    premiumRatePct: str
    periodFrom: date
    periodTo: date
    evidenceDocumentId: Optional[int] = None


class MXIsnRegistrationCreate(_MXIn):
    stateCode: str
    localAccountNumber: str
    effectiveFrom: date
    returnFrequency: Optional[str] = None


class MXVacationBand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    serviceYearFrom: int
    serviceYearTo: Optional[int] = None
    days: str


class MXLaborPolicyCreate(_MXIn):
    effectiveFrom: date
    effectiveTo: Optional[date] = None
    collectiveAgreementId: Optional[int] = None
    ordinaryWeeklyHours: str
    weeklySchedule: Optional[Dict[str, Any]] = None
    aguinaldoDays: str
    vacationPolicy: List[MXVacationBand]
    vacationPremiumPct: str
    sundayPremiumPct: str
    savingsFund: Optional[Dict[str, Any]] = None
    foodVouchers: Optional[Dict[str, Any]] = None
    otherBenefits: Optional[Dict[str, Any]] = None
    timeRecordDependency: Optional[Dict[str, Any]] = None


class MXCredentialCreate(_MXIn):
    kind: str
    secretRef: str
    imssRegistrationId: Optional[int] = None


class MXInfonavitNoticeCreate(_MXIn):
    """Copied from the INFONAVIT notice itself (MX-031) — with its evidence."""
    creditNumber: str
    noticeType: str
    discountMethod: Optional[str] = None
    discountValue: Optional[str] = None
    effectiveFrom: date
    authorityReference: str
    evidenceDocumentId: Optional[int] = None
