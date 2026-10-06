"""
modules/payroll/policy/schemas.py
-----------------------------------
Pydantic schemas for Payroll Policy Management.

Follows the same convention as app/modules/payroll/schemas.py: camelCase
aliases for the frontend, response_model_by_alias=True on every route
that returns these models.
"""

from datetime import date, datetime
from decimal import Decimal
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


# ── Allowance Component (dynamic, Super-Admin-defined) ────────────────────

class AllowanceComponentBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: Optional[int] = Field(None, exclude=True)
    key: str = Field(..., alias="key")
    label: str = Field(..., alias="label")
    pct: Optional[Decimal] = Field(None, alias="pct")
    flat_amount: Optional[Decimal] = Field(None, alias="flatAmount")
    allow_override: bool = Field(True, alias="allowOverride")
    sort_order: int = Field(0, alias="sortOrder")


class AllowanceComponentResponse(AllowanceComponentBase):
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
    basic_pct: Decimal = Field(Decimal("40"), alias="basicPct")
    hra_pct: Decimal = Field(Decimal("20"), alias="hraPct")
    bank_export_format: str = Field("csv", alias="bankExportFormat")
    attendance_required: bool = Field(True, alias="attendanceRequired")
    attendance_required_employment_types: Optional[List[str]] = Field(None, alias="attendanceRequiredEmploymentTypes")
    attendance_weekly_off_days: Optional[List[int]] = Field(None, alias="attendanceWeeklyOffDays")
    enterprise_status: str = Field("not_configured", alias="enterpriseStatus")
    enterprise_activated_at: Optional[datetime] = Field(None, alias="enterpriseActivatedAt")
    configured_at: Optional[datetime] = Field(None, alias="configuredAt")
    is_configured: bool = Field(False, alias="isConfigured")

    employee_categories: List[EmployeeCategoryResponse] = Field(default_factory=list, alias="employeeCategories")
    leave_rules: List[LeaveRuleResponse] = Field(default_factory=list, alias="leaveRules")
    overtime_rule: Optional[OvertimeRuleResponse] = Field(None, alias="overtimeRule")
    integrations: List[IntegrationResponse] = Field(default_factory=list)
    allowance_components: List[AllowanceComponentResponse] = Field(default_factory=list, alias="allowanceComponents")

    # The org's assigned compliance pack's policy_defaults (see
    # JurisdictionPack.policy_defaults) — {} when no pack is assigned or
    # the pack sets no defaults, so the frontend can tell "not locked"
    # apart from "locked to this value" per field.
    policy_locks: dict = Field(default_factory=dict, alias="policyLocks")


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
    basic_pct: Optional[Decimal] = Field(None, alias="basicPct")
    hra_pct: Optional[Decimal] = Field(None, alias="hraPct")
    bank_export_format: Optional[str] = Field(None, alias="bankExportFormat")
    # Attendance gate. Employment types: [] or null = every employee.
    # Weekly off days: Python weekday numbers (Mon=0 … Sun=6); null = Sat+Sun.
    attendance_required: Optional[bool] = Field(None, alias="attendanceRequired")
    attendance_required_employment_types: Optional[List[str]] = Field(None, alias="attendanceRequiredEmploymentTypes")
    attendance_weekly_off_days: Optional[List[int]] = Field(None, alias="attendanceWeeklyOffDays")
    employee_categories: Optional[List[EmployeeCategoryBase]] = Field(None, alias="employeeCategories")
    overtime_rule: Optional[OvertimeRuleUpdate] = Field(None, alias="overtimeRule")
    allowance_components: Optional[List[AllowanceComponentBase]] = Field(None, alias="allowanceComponents")

    @model_validator(mode="after")
    def _validate_attendance_settings(self):
        from app.modules.payroll.models import EmploymentType
        if "attendance_required" in self.model_fields_set and self.attendance_required is None:
            raise ValueError("attendanceRequired must be true or false.")
        if self.attendance_weekly_off_days is not None:
            days = self.attendance_weekly_off_days
            if any(d < 0 or d > 6 for d in days) or len(set(days)) != len(days):
                raise ValueError("attendanceWeeklyOffDays must be distinct weekday numbers 0 (Mon) to 6 (Sun).")
            if len(days) >= 7:
                raise ValueError("attendanceWeeklyOffDays cannot mark every day of the week as off.")
        if self.attendance_required_employment_types is not None:
            allowed = {e.value for e in EmploymentType}
            bad = [t for t in self.attendance_required_employment_types if t not in allowed]
            if bad:
                raise ValueError(f"Unknown employment type(s) {bad}; expected any of {sorted(allowed)}.")
        return self

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