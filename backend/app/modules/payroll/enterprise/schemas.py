"""
modules/payroll/enterprise/schemas.py
----------------------------------------
Pydantic schemas for Enterprise Policy jurisdiction onboarding.

Follows the same convention as the rest of the payroll module: camelCase
aliases for the frontend, response_model_by_alias=True on every route
that returns these models.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field


class GeneralConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    payroll_frequency: Optional[str] = Field(None, alias="payrollFrequency")
    time_zone: Optional[str] = Field(None, alias="timeZone")


class ComplianceConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    government_filing_schedule: Optional[str] = Field(None, alias="governmentFilingSchedule")
    required_reports: Optional[List[str]] = Field(None, alias="requiredReports")
    payroll_registration_numbers: Optional[str] = Field(None, alias="payrollRegistrationNumbers")
    tax_identification_numbers: Optional[str] = Field(None, alias="taxIdentificationNumbers")


class PayrollRulesConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    overtime: Optional[str] = None
    leave: Optional[str] = None
    holiday_calendar: Optional[str] = Field(None, alias="holidayCalendar")
    termination_rules: Optional[str] = Field(None, alias="terminationRules")


class JurisdictionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    country_code: str = Field(..., alias="countryCode")
    status: str
    general_config: Optional[Dict[str, Any]] = Field(None, alias="generalConfig")
    compliance_config: Optional[Dict[str, Any]] = Field(None, alias="complianceConfig")
    payroll_rules_config: Optional[Dict[str, Any]] = Field(None, alias="payrollRulesConfig")
    configured_at: Optional[datetime] = Field(None, alias="configuredAt")
    verified_at: Optional[datetime] = Field(None, alias="verifiedAt")
    created_at: datetime = Field(..., alias="createdAt")


class JurisdictionCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    country_code: str = Field(..., alias="countryCode")


class JurisdictionConfigUpdate(BaseModel):
    """Partial update — only sections present in the request are changed.
    Tax/Employer/Employee Contributions are NOT here — those go through the
    existing contribution-rate/tax-slab endpoints (see enterprise/router.py
    rate/slab passthrough helpers)."""
    model_config = ConfigDict(populate_by_name=True)
    general_config: Optional[GeneralConfig] = Field(None, alias="generalConfig")
    compliance_config: Optional[ComplianceConfig] = Field(None, alias="complianceConfig")
    payroll_rules_config: Optional[PayrollRulesConfig] = Field(None, alias="payrollRulesConfig")
    mark_configured: Optional[bool] = Field(None, alias="markConfigured")


class ValidationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    can_activate: bool = Field(..., alias="canActivate")
    blocking_reasons: List[str] = Field(default_factory=list, alias="blockingReasons")
    configured_jurisdictions: List[str] = Field(default_factory=list, alias="configuredJurisdictions")


class ActivationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    activated: bool
    enterprise_status: str = Field(..., alias="enterpriseStatus")
    activated_jurisdictions: List[str] = Field(default_factory=list, alias="activatedJurisdictions")


class EnterpriseDashboardResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    configured_count: int = Field(..., alias="configuredCount")
    pending_count: int = Field(..., alias="pendingCount")
    active_countries: List[str] = Field(default_factory=list, alias="activeCountries")
    completion_pct: float = Field(..., alias="completionPct")
    upcoming_filings: List[Dict[str, Any]] = Field(default_factory=list, alias="upcomingFilings")
    recent_changes: List[Dict[str, Any]] = Field(default_factory=list, alias="recentChanges")


class ContributionRateNumericResponse(BaseModel):
    """Numeric-value companion to the existing (display-string-only)
    ContributionRateResponse — needed so the Enterprise config panel can
    pre-fill and edit real percentages, not formatted text."""
    model_config = ConfigDict(populate_by_name=True)
    id: int
    component_key: str = Field(..., alias="componentKey")
    label: str
    employee_rate_pct: Optional[Decimal] = Field(None, alias="employeeRatePct")
    employer_rate_pct: Optional[Decimal] = Field(None, alias="employerRatePct")
    flat_amount: Optional[Decimal] = Field(None, alias="flatAmount")


class SuccessResponse(BaseModel):
    success: bool = True
    message: Optional[str] = None
