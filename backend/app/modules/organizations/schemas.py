"""
modules/organizations/schemas.py
--------------------------------
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class OrganizationBase(BaseModel):
    organization_name: str = Field(..., min_length=1, max_length=200)
    industry: Optional[str] = None
    address: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    tax_no: Optional[str] = None
    registration_number: Optional[str] = None


class OrganizationUpdate(BaseModel):
    organization_name: Optional[str] = Field(None, min_length=1, max_length=200)
    industry: Optional[str] = None
    address: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    tax_no: Optional[str] = None
    registration_number: Optional[str] = None


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_name: str
    organization_code: str
    industry: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    tax_no: Optional[str] = None
    registration_number: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class OrganizationListResponse(BaseModel):
    organizations: list[OrganizationResponse]
    total: int


class DepartmentHeadcount(BaseModel):
    name: str
    count: int
    pct: int


class RecentEmployee(BaseModel):
    name: str
    initials: str
    dept: Optional[str] = None
    designation: Optional[str] = None
    status: str
    statusColor: str


class OrganizationDashboardStats(BaseModel):
    total_employees: int = 0
    active_employees: int = 0
    departments: int = 0
    designations: int = 0
    hr_admins: int = 0
    pending_leave_requests: int = 0
    pending_approvals: int = 0
    monthly_payroll: Optional[float] = None
    assets: int = 0
    department_headcount: list[DepartmentHeadcount] = []
    recent_employees: list[RecentEmployee] = []


class OrganizationDetail(BaseModel):
    id: int
    name: str
    code: str
    status: str
    admin_name: Optional[str] = None
    admin_email: Optional[str] = None
    industry: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    timezone: str = "UTC"
    domain: Optional[str] = None
    subscription_plan: str = "STANDARD"
    subscription_status: str = "active"
    currency: str = "USD"
    max_users: Optional[int] = None
    total_employees: int = 0
    active_employees: int = 0
    hr_admins: int = 0
    created_at: datetime
