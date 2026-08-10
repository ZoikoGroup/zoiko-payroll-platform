"""
modules/payroll/policy/schemas.py
-----------------------------------
Pydantic schemas for Payroll Policy Management.

Follows the same convention as app/modules/payroll/schemas.py: camelCase
aliases for the frontend, response_model_by_alias=True on every route
that returns these models.
"""

from datetime import date, datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field, model_validator


# ── Employee Category ────────────────────────────────────────────────────

class EmployeeCategoryBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: Optional[int] = Field(None, exclude=True)
    category: str = Field(..., alias="category")
    working_days: int = Field(5, alias="workingDays")
    weekly_off: Optional[List[str]] = Field(None, alias="weeklyOff")
    expected_hours: int = Field(8, alias="expectedHours")
    minimum_hours: int = Field(4, alias="minimumHours")
    paid_leave_eligible: bool = Field(True, alias="paidLeaveEligible")
    grace_time_minutes: int = Field(10, alias="graceTimeMinutes")
    half_day_rule: Optional[Dict[str, Any]] = Field(None, alias="halfDayRule")


class EmployeeCategoryResponse(EmployeeCategoryBase):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: int


# ── Leave Rule ────────────────────────────────────────────────────────────

class LeaveRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: int
    rule_type: str = Field(..., alias="ruleType")
    config: Optional[Dict[str, Any]] = None


# ── Overtime Rule ─────────────────────────────────────────────────────────

class OvertimeRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    enabled: bool
    minimum_overtime_minutes: int = Field(..., alias="minimumOvertimeMinutes")
    approval_required: bool = Field(..., alias="approvalRequired")


# ── Integration ───────────────────────────────────────────────────────────

class IntegrationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: int
    category: str
    provider_key: str = Field(..., alias="providerKey")
    enabled: bool


class IntegrationToggleRequest(BaseModel):
    """Body is empty on purpose — category/provider_key come from the URL path,
    organization_id comes from current_user, never from client input."""
    pass


# ── Policy (full read model) ───────────────────────────────────────────────

class PayrollPolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    name: str
    description: Optional[str] = None
    status: str
    effective_date: date = Field(..., alias="effectiveDate")
    is_default: bool = Field(..., alias="isDefault")
    calculation_mode: str = Field(..., alias="calculationMode")
    bank_export_format: str = Field("csv", alias="bankExportFormat")
    enterprise_status: str = Field("not_configured", alias="enterpriseStatus")
    enterprise_activated_at: Optional[datetime] = Field(None, alias="enterpriseActivatedAt")
    configured_at: Optional[datetime] = Field(None, alias="configuredAt")
    is_configured: bool = Field(False, alias="isConfigured")

    employee_categories: List[EmployeeCategoryResponse] = Field(default_factory=list, alias="employeeCategories")
    leave_rules: List[LeaveRuleResponse] = Field(default_factory=list, alias="leaveRules")
    overtime_rule: Optional[OvertimeRuleResponse] = Field(None, alias="overtimeRule")
    integrations: List[IntegrationResponse] = Field(default_factory=list)


class OvertimeRuleUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: Optional[int] = Field(None, exclude=True)
    enabled: Optional[bool] = None
    minimum_overtime_minutes: Optional[int] = Field(None, alias="minimumOvertimeMinutes")
    approval_required: Optional[bool] = Field(None, alias="approvalRequired")


class PayrollPolicyUpdate(BaseModel):
    """Partial update — only fields present in the request are changed."""
    model_config = ConfigDict(populate_by_name=True)

    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    effective_date: Optional[date] = Field(None, alias="effectiveDate")
    calculation_mode: Optional[str] = Field(None, alias="calculationMode")
    bank_export_format: Optional[str] = Field(None, alias="bankExportFormat")
    employee_categories: Optional[List[EmployeeCategoryBase]] = Field(None, alias="employeeCategories")
    overtime_rule: Optional[OvertimeRuleUpdate] = Field(None, alias="overtimeRule")

    @model_validator(mode="before")
    @classmethod
    def _drop_blank_effective_date(cls, data):
        # <input type="date"> reports "" (not null) when a user clears it.
        # effective_date is a NOT NULL column, so an explicit null would fail
        # at the DB layer (update_policy uses exclude_unset=True — a key
        # that's *present* but None still gets written). Dropping the key
        # entirely makes "" behave as "no change", the only sane meaning
        # for clearing a required date on a partial-update endpoint.
        if isinstance(data, dict):
            for key in ("effectiveDate", "effective_date"):
                if data.get(key) == "":
                    data.pop(key)
        return data


class SuccessResponse(BaseModel):
    success: bool = True
    message: Optional[str] = None