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
