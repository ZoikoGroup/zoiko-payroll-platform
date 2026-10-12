"""
payroll/netherlands_schemas.py
------------------------------
Pydantic schemas for Netherlands payroll API — camelCase responses.

Deliberately avoids the SA bug where the UI received snake_case.
All response fields use camelCase; request bodies accept camelCase.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---- Employer Profile ----

class EmployerProfileBase(BaseModel):
    legalName: str
    kvkNumber: Optional[str] = None
    rsin: Optional[str] = None
    address: Optional[Dict[str, Any]] = None
    payrollContact: Optional[Dict[str, Any]] = None
    loonheffingennummer: Optional[str] = None
    loonheffingenSubnumber: Optional[str] = None
    registrationLetterRef: Optional[str] = None
    returnPeriod: str = "MONTH"  # MONTH / FOUR_WEEK
    payrollSchedule: str = "MONTH"  # MONTH / FOUR_WEEK / WEEK
    standardPayDay: Optional[int] = None  # 1-31
    bankLeadDays: int = 2
    bankIbanToken: Optional[str] = None
    bankBic: Optional[str] = None
    pkiCertRef: Optional[str] = None
    pkiCertFingerprint: Optional[str] = None
    pkiCertIssuer: Optional[str] = None
    pkiCertExpiresAt: Optional[datetime] = None
    digipoortChannel: Optional[str] = None
    digipoortTestStatus: Optional[str] = None
    digipoortTestEvidenceId: Optional[int] = None
    caoStatus: str = "NONE"  # NONE / APPLICABLE / UNKNOWN
    collectiveAgreementId: Optional[int] = None
    pensionStatus: Optional[str] = None
    wkrMode: str = "STANDALONE"  # STANDALONE / CONCERN
    wkrConcernId: Optional[int] = None


class EmployerProfileCreate(EmployerProfileBase):
    effectiveFrom: date


class EmployerProfileUpdate(BaseModel):
    effectiveTo: Optional[date] = None
    legalName: Optional[str] = None
    kvkNumber: Optional[str] = None
    rsin: Optional[str] = None
    address: Optional[Dict[str, Any]] = None
    payrollContact: Optional[Dict[str, Any]] = None
    loonheffingennummer: Optional[str] = None
    loonheffingenSubnumber: Optional[str] = None
    registrationLetterRef: Optional[str] = None
    registrationVerifiedAt: Optional[datetime] = None
    registrationVerifiedBy: Optional[int] = None
    returnPeriod: Optional[str] = None
    payrollSchedule: Optional[str] = None
    standardPayDay: Optional[int] = None
    bankLeadDays: Optional[int] = None
    bankIbanToken: Optional[str] = None
    bankBic: Optional[str] = None
    pkiCertRef: Optional[str] = None
    pkiCertFingerprint: Optional[str] = None
    pkiCertIssuer: Optional[str] = None
    pkiCertExpiresAt: Optional[datetime] = None
    digipoortChannel: Optional[str] = None
    digipoortTestStatus: Optional[str] = None
    digipoortTestEvidenceId: Optional[int] = None
    caoStatus: Optional[str] = None
    collectiveAgreementId: Optional[int] = None
    pensionStatus: Optional[str] = None
    wkrMode: Optional[str] = None
    wkrConcernId: Optional[int] = None
    readinessStatus: Optional[str] = None
    readinessEvidence: Optional[Dict[str, Any]] = None


class EmployerProfileResponse(EmployerProfileBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organizationId: int
    version: int
    previousVersionId: Optional[int] = None
    effectiveFrom: date
    effectiveTo: Optional[date] = None
    registrationVerifiedAt: Optional[datetime] = None
    registrationVerifiedBy: Optional[int] = None
    readinessStatus: str
    readinessEvidence: Optional[Dict[str, Any]] = None
    createdBy: Optional[int] = None
    createdAt: datetime


# ---- Income Relationship (IKV) ----

class IncomeRelationshipBase(BaseModel):
    ikvNumber: str
    incomeRelationCode: str
    payrollPeriod: str  # MONTH / FOUR_WEEK / WEEK
    startDate: date
    endDate: Optional[date] = None


class IncomeRelationshipCreate(IncomeRelationshipBase):
    employeeId: int


class IncomeRelationshipUpdate(BaseModel):
    endDate: Optional[date] = None
    status: Optional[str] = None  # ACTIVE / CLOSED
    closedReason: Optional[str] = None
    payrollPeriod: Optional[str] = None


class IncomeRelationshipResponse(IncomeRelationshipBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organizationId: int
    employeeId: int
    status: str
    closedReason: Optional[str] = None
    createdBy: Optional[int] = None
    createdAt: datetime


# ---- Tax Credit Instruction ----

class TaxCreditInstructionBase(BaseModel):
    applyTaxCredit: bool = True
    formVersion: str = "Model opgaaf 2026-08"
    signedAt: datetime
    effectiveFrom: date
    signedDocumentArtifactId: Optional[int] = None


class TaxCreditInstructionCreate(TaxCreditInstructionBase):
    employeeId: int


class TaxCreditInstructionResponse(TaxCreditInstructionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organizationId: int
    employeeId: int
    supersededById: Optional[int] = None
    capturedBy: Optional[int] = None
    createdAt: datetime


# ---- Contract Version ----

class ContractVersionBase(BaseModel):
    contractTerm: str  # INDEFINITE / FIXED
    writtenRecord: bool = False
    writtenEvidenceRef: Optional[str] = None
    onCall: bool = False
    agreedHoursPerWeek: Optional[Decimal] = None
    statutoryExceptionCode: Optional[str] = None
    startDate: date
    endDate: Optional[date] = None
    incomeRelationshipId: Optional[int] = None


class ContractVersionCreate(ContractVersionBase):
    employeeId: int
    version: int


class ContractVersionUpdate(BaseModel):
    endDate: Optional[date] = None
    contractTerm: Optional[str] = None
    writtenRecord: Optional[bool] = None
    writtenEvidenceRef: Optional[str] = None
    onCall: Optional[bool] = None
    agreedHoursPerWeek: Optional[Decimal] = None
    statutoryExceptionCode: Optional[str] = None
    derivedAwfClass: Optional[str] = None  # LOW / HIGH
    awfDerivationReason: Optional[str] = None
    effectiveTo: Optional[date] = None


class ContractVersionResponse(ContractVersionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organizationId: int
    employeeId: int
    incomeRelationshipId: Optional[int] = None
    version: int
    previousVersionId: Optional[int] = None
    derivedAwfClass: Optional[str] = None
    awfDerivationReason: Optional[str] = None
    effectiveFrom: date
    effectiveTo: Optional[date] = None
    createdBy: Optional[int] = None
    createdAt: datetime


# ---- Employer Readiness Card H ----

class ReadinessItem(BaseModel):
    key: str
    label: str
    status: str  # COMPLETE / INCOMPLETE / BLOCKED
    details: Optional[str] = None
    evidenceRefs: List[int] = []


class ReadinessSection(BaseModel):
    section: str
    items: List[ReadinessItem]


class EmployerReadinessCard(BaseModel):
    organizationId: int
    profileVersion: int
    overallStatus: str  # READY / INCOMPLETE / BLOCKED
    sections: List[ReadinessSection]
    lastUpdated: datetime
    updatedBy: Optional[int] = None


# ---- Employee NL Fields (for statutory profile) ----

class EmployeeNLFields(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    bsnVerifiedAt: Optional[datetime] = None
    identityStatus: Optional[str] = None
    residenceCountry: Optional[str] = None
    residenceVariant: Optional[str] = None
    tableColor: Optional[str] = None  # WHITE / GREEN
    zvwPath: Optional[str] = None  # EMPLOYER_LEVY / EMPLOYEE_CONTRIB / SPECIAL
    eiInsured: Optional[bool] = None
    insuranceExceptionCode: Optional[str] = None
    insuranceEvidenceRef: Optional[str] = None
    crossBorderStatus: Optional[str] = None  # NONE / SUPPORTED / BLOCKED
    a1Reference: Optional[str] = None
    pensionSchemeId: Optional[int] = None
    voluntaryExtraWithholding: Optional[Decimal] = None
    vacationAllowancePct: Optional[Decimal] = None
    contractHoursPerWeek: Optional[Decimal] = None
    personnelNumber: Optional[str] = None


# ---- Generic responses ----

class ErrorResponse(BaseModel):
    error: str
    code: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class SuccessResponse(BaseModel):
    success: bool = True
    data: Optional[Any] = None
    message: Optional[str] = None


# ---- Idempotency ----

class IdempotencyRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    idempotencyKey: str
    requestHash: str
    responseStatus: Optional[int] = None
    responseBody: Optional[str] = None
    createdBy: Optional[int] = None
    createdAt: datetime
    expiresAt: datetime


# ---- Pagination ----

class PaginatedResponse(BaseModel):
    items: List[Any]
    total: int
    page: int
    pageSize: int
    hasMore: bool