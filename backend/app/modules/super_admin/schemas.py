"""
modules/super_admin/schemas.py
------------------------------
"""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.auth.models import UserRole


class SettingCreate(BaseModel):
    key: str
    value: Optional[str] = None
    description: Optional[str] = None
    is_public: bool = False


class SettingUpdate(BaseModel):
    value: Optional[str] = None
    description: Optional[str] = None
    is_public: Optional[bool] = None


class SettingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    value: Optional[str] = None
    description: Optional[str] = None
    is_public: bool
    updated_at: datetime


class SuperAdminUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: UserRole
    organization_id: Optional[int] = None
    organization_name: Optional[str] = None
    organization_code: Optional[str] = None
    first_name: str
    last_name: str
    is_active: bool
    created_at: datetime


class SuperAdminUserListResponse(BaseModel):
    users: list[SuperAdminUserResponse]
    total: int


class DashboardStats(BaseModel):
    total_organizations: int
    active_organizations: int
    total_users: int
    super_admins: int
    org_admins: int
    payroll_admins: int
    total_payroll_employees: int
    total_payroll_runs: int
    recent_organizations: list[dict]


# Statutory Rate Create/Update/Response/ListResponse schemas were removed
# here along with GlobalStatutoryRate itself (models.py) — the Statutory
# Rates page now reads canonical tax-pack data via
# ActiveTaxConfigurationResponse (app.modules.payroll.schemas) instead.


# ── Compliance (Super Admin) ───────────────────────────────────────────────
# JurisdictionPackResponse/Upsert are reused as-is from app.modules.payroll.schemas
# (imported directly in router.py) — no parallel schema is defined here.

class AssignPolicyRequest(BaseModel):
    organizationIds: list[int]


class ApplicableOrganization(BaseModel):
    id: int
    organizationName: str
    organizationCode: Optional[str] = None


class SgEvidenceReview(BaseModel):
    """Singapore gate / decision evidence review outcome (never the registrant)."""
    outcome: str                      # ACCEPTED | REJECTED
    notes: Optional[str] = None       # required for REJECTED
    validUntil: Optional[date] = None  # ACCEPTED only; the gate turns EXPIRED after it


class SgDecisionCreate(BaseModel):
    """Owner decision D1 / D2 / D3 — the selected option and the reason."""
    key: str
    selectedValue: str
    reason: str


class SgServiceRegistryTransition(BaseModel):
    """Phase 6.10: the owner's Singapore registry step — AVAILABLE (opens
    onboarding, gated server-side) or PLANNED (closes it). The reason is the
    change record."""
    availability: str
    reason: str


class HkServiceRegistryTransition(BaseModel):
    """Final completion program: the owner's Hong Kong registry step —
    AVAILABLE (opens onboarding; refused unless every readiness requirement is
    met, re-derived server-side) or PLANNED (suspends / closes it)."""
    model_config = ConfigDict(extra="forbid")
    availability: str
    reason: str


class HkConfigRowUpdate(BaseModel):
    """Governed edit of one HK statutory row: a reason and a source document are required."""
    model_config = ConfigDict(extra="forbid")
    reason: str
    sourceDocumentId: int
    employeeRatePct: Optional[str] = None
    employerRatePct: Optional[str] = None
    flatAmount: Optional[str] = None
    textValue: Optional[str] = None
    minAmount: Optional[str] = None
    maxAmount: Optional[str] = None
    ratePct: Optional[str] = None
    taxFormula: Optional[str] = None
    effectiveFrom: Optional[str] = None
    effectiveTo: Optional[str] = None
    # Records the HK specialist's (G1) confirmation of a value seeded "[G1]";
    # accepted only with a stored, hashed, independently reviewed source.
    specialistVerified: Optional[bool] = None


class HkNewVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    reason: str


class HkSoftwareApprovalTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str
    reason: str
    formsCovered: Optional[List[str]] = None
    specificationVersion: Optional[str] = None
    applicationReference: Optional[str] = None
    applicationSubmittedOn: Optional[date] = None
    testDataSubmittedOn: Optional[date] = None
    approvalReference: Optional[str] = None
    approvalReceivedOn: Optional[date] = None
    approvalDocumentId: Optional[int] = None
    expiresOn: Optional[date] = None
    notes: Optional[str] = None


class HkEmpfConfigurationCreate(BaseModel):
    """Statuses and non-secret descriptors only — extra fields (a password,
    key, certificate body…) are refused outright."""
    model_config = ConfigDict(extra="forbid")
    submissionMethod: str
    environment: str
    reason: str
    fileFormat: Optional[str] = None
    formatVersion: Optional[str] = None
    endpointReference: Optional[str] = None
    credentialStatus: str = "NOT_CONFIGURED"
    certificateStatus: str = "NOT_CONFIGURED"
    certificationEvidenceId: Optional[int] = None


class HkRetentionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recordCategory: str
    retentionYears: int
    endOfRetention: str
    legalBasis: str
    reason: str


class HkReasonBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str


class SgServiceRegistryResponse(BaseModel):
    country: str
    availability: str
    updatedAt: Optional[datetime] = None


class SourceArtifactSupersede(BaseModel):
    """Singapore gate / decision evidence: the artifact that replaces this one."""
    replacementId: int


class PolicyStatusUpdate(BaseModel):
    status: str
    # Optional; kept on the tax pack's status_change audit row.
    reason: Optional[str] = Field(None, max_length=2000)


# ── Finance (Super Admin) ───────────────────────────────────────────────────

class FinanceOverviewItem(BaseModel):
    id: int
    organizationId: int
    organizationName: str
    organizationCode: Optional[str] = None
    jurisdictionCountry: Optional[str] = None
    currency: Optional[str] = None
    periodLabel: str
    periodStart: Optional[date] = None
    periodEnd: Optional[date] = None
    payDate: Optional[date] = None
    status: str
    grossPay: Decimal
    netPay: Decimal
    totalDeductions: Decimal
    totalTaxes: Decimal
    employerCost: Decimal
    employeeCount: int


class FinanceOverviewResponse(BaseModel):
    items: list[FinanceOverviewItem]
    total: int


class FinanceCountryTotal(BaseModel):
    country: str
    organizations: int
    payrollRuns: int
    grossPay: Decimal
    netPay: Decimal
    totalDeductions: Decimal
    employerCost: Decimal


class FinanceSummaryResponse(BaseModel):
    byCountry: list[FinanceCountryTotal]
    totalOrganizations: int
    totalPayrollRuns: int
    payrollsPending: int
    payrollsCompleted: int


class FinanceOrganizationTotal(BaseModel):
    organizationId: int
    organizationName: str
    jurisdictionCountry: Optional[str] = None
    currency: Optional[str] = None
    runCount: int
    grossPay: Decimal
    netPay: Decimal
    totalDeductions: Decimal
    employerCost: Decimal
    lastPayDate: Optional[date] = None


class FinanceByOrganizationResponse(BaseModel):
    organizations: list[FinanceOrganizationTotal]
    total: int


# ── Reports (Super Admin) ───────────────────────────────────────────────────

class ReportsListResponse(BaseModel):
    items: list[dict]
    total: int


# ── Organization currency management (Finance) ─────────────────────────────

class UpdateCurrencyRequest(BaseModel):
    currency: Optional[str] = None


# ── Dashboard charts (Super Admin) ─────────────────────────────────────────

class DashboardChartsResponse(BaseModel):
    payrollTrend: list[dict]
    grossVsNet: dict
    organizationsByCountry: list[dict]
    organizationsByStatus: dict
    payrollByJurisdiction: list[dict]
    complianceOverview: dict
    employeesByCountry: list[dict]


# ── Singapore statutory administration (read-only, tenant-independent) ────
# Same {items, total} list convention as FinanceOverviewResponse /
# ReportsListResponse; values are the service's own serialization (money as
# Decimal strings, dates ISO strings), never re-derived here.

class SgpPwmScheduleResponse(BaseModel):
    id: int
    jurisdiction: str
    sector: str
    occupationGroup: str
    jobLevel: str
    roleLabel: str
    effectiveFrom: str
    effectiveTo: Optional[str] = None
    overtimeHours: int
    requiredGross: str
    sourceDocumentId: int
    sourceTitle: Optional[str] = None
    sourceUrl: Optional[str] = None
    sourceSha256: str
    retrievedAt: Optional[str] = None
    status: str


class SgpPwmSchedulePageResponse(BaseModel):
    items: list[SgpPwmScheduleResponse]
    total: int
    skip: int
    limit: int
    readOnly: bool
    classification: str


class SgpStatutoryAdminSummaryResponse(BaseModel):
    jurisdiction: str
    asOf: str
    activationReadiness: dict
    activePack: Optional[dict] = None
    valuesFromPack: Optional[dict] = None
    valuesFromActivePack: bool
    packs: list[dict]
    sections: list[dict]
    certification: str
