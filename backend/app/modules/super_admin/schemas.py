"""
modules/super_admin/schemas.py
------------------------------
"""
from datetime import datetime
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
    org_admins: int
    payroll_admins: int
    employees: int
    total_payroll_employees: int
    total_payroll_runs: int
    recent_organizations: list[dict]


# ── Global statutory rate table (Super Admin) ──────────────────────────────

class StatutoryRateCreate(BaseModel):
    jurisdiction_country: str = "IN"
    component_key: str
    label: str
    employee_share: str = ""
    employer_share: str = ""
    total: str = ""
    employee_rate_pct: Optional[Decimal] = None
    employer_rate_pct: Optional[Decimal] = None
    flat_amount: Optional[Decimal] = None
    sort_order: int = 0


class StatutoryRateUpdate(BaseModel):
    label: Optional[str] = None
    employee_share: Optional[str] = None
    employer_share: Optional[str] = None
    total: Optional[str] = None
    employee_rate_pct: Optional[Decimal] = None
    employer_rate_pct: Optional[Decimal] = None
    flat_amount: Optional[Decimal] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class StatutoryRateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    jurisdiction_country: str
    component_key: str
    label: str
    employee_share: str
    employer_share: str
    total: str
    employee_rate_pct: Optional[Decimal] = None
    employer_rate_pct: Optional[Decimal] = None
    flat_amount: Optional[Decimal] = None
    sort_order: int
    is_active: bool
    updated_at: datetime


class StatutoryRateListResponse(BaseModel):
    rates: list[StatutoryRateResponse]
    total: int
