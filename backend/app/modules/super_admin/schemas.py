"""
modules/super_admin/schemas.py
------------------------------
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr

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


class PolicyStatusUpdate(BaseModel):
    status: str


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
