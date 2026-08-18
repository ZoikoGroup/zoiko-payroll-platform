"""
modules/payroll/hierarchy/schemas.py
--------------------------------------
Pydantic request/response models for the tax-hierarchy API
(hierarchy/router.py). Mirrors the existing JurisdictionPackUpsert /
CanonicalTaxSlabUpsert PUT-as-upsert convention from
app/modules/payroll/schemas.py — presence of `id` means update-in-place,
its absence means create.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List

from pydantic import BaseModel, ConfigDict


class CountryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    currency: Optional[str] = None


class JurisdictionLevelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    country_id: int
    level_code: str
    label: str
    rank: int


# ── Jurisdiction ─────────────────────────────────────────────────────────

class JurisdictionNodeSummary(BaseModel):
    """One row in the lazy-loaded tree — pre-aggregated so the UI never
    fetches a node's children just to render its expand-arrow/badge."""
    id: int
    name: str
    code: Optional[str] = None
    level_code: str
    has_children: bool
    active_tax_version_count: int


class JurisdictionBreadcrumbNode(BaseModel):
    id: int
    name: str
    level_code: str


class JurisdictionDetail(BaseModel):
    id: int
    country_id: int
    level_id: int
    level_code: str
    parent_jurisdiction_id: Optional[int] = None
    name: str
    code: Optional[str] = None
    is_active: bool
    breadcrumb: List[JurisdictionBreadcrumbNode] = []  # root -> self


class JurisdictionUpsert(BaseModel):
    id: Optional[int] = None
    country_id: int
    level_id: int
    parent_jurisdiction_id: Optional[int] = None
    name: str
    code: Optional[str] = None
    external_ref: Optional[str] = None
    is_active: bool = True


# ── Tax ──────────────────────────────────────────────────────────────────

class TaxResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    country_id: int
    tax_code: str
    name: str
    category: str
    description: Optional[str] = None


class TaxUpsert(BaseModel):
    id: Optional[int] = None
    country_id: int
    tax_code: str
    name: str
    category: str = "other_statutory"
    description: Optional[str] = None


# ── TaxVersion ───────────────────────────────────────────────────────────

class TaxVersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    version_label: str
    tax_year: Optional[str] = None
    tax_regime: Optional[str] = None
    status: str
    effective_from: date
    effective_to: Optional[date] = None


class TaxVersionDetail(TaxVersionSummary):
    tax_id: int
    jurisdiction_id: int
    currency: Optional[str] = None
    previous_version_id: Optional[int] = None
    compliance_owner: Optional[str] = None
    engineering_owner: Optional[str] = None
    regulatory_authority: Optional[str] = None
    compliance_category: Optional[str] = None
    source_references: Optional[str] = None
    change_summary: Optional[str] = None
    next_review_date: Optional[date] = None


class TaxVersionUpsert(BaseModel):
    id: Optional[int] = None
    tax_id: int
    jurisdiction_id: int
    version_label: str
    tax_year: Optional[str] = None
    tax_regime: Optional[str] = None
    status: str = "Draft"
    effective_from: date
    effective_to: Optional[date] = None
    currency: Optional[str] = None
    previous_version_id: Optional[int] = None
    compliance_owner: Optional[str] = None
    engineering_owner: Optional[str] = None
    regulatory_authority: Optional[str] = None
    compliance_category: Optional[str] = None
    source_references: Optional[str] = None
    change_summary: Optional[str] = None
    next_review_date: Optional[date] = None


class TaxVersionStatusUpdate(BaseModel):
    status: str


# ── TaxRule / TaxRuleSlab / TaxRuleRate ─────────────────────────────────

class TaxRuleSlabResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    min_amount: Decimal
    max_amount: Optional[Decimal] = None
    rate_pct: Optional[Decimal] = None
    flat_fee_amount: Optional[Decimal] = None
    rate_label: Optional[str] = None
    sort_order: int


class TaxRuleSlabUpsert(BaseModel):
    id: Optional[int] = None
    tax_rule_id: int
    min_amount: Decimal
    max_amount: Optional[Decimal] = None
    rate_pct: Optional[Decimal] = None
    flat_fee_amount: Optional[Decimal] = None
    rate_label: Optional[str] = None
    sort_order: int = 0


class TaxRuleRateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    employee_rate_pct: Optional[Decimal] = None
    employer_rate_pct: Optional[Decimal] = None
    employee_flat_amount: Optional[Decimal] = None
    employer_flat_amount: Optional[Decimal] = None
    display_employee_share: Optional[str] = None
    display_employer_share: Optional[str] = None
    display_total: Optional[str] = None


class TaxRuleRateUpsert(BaseModel):
    id: Optional[int] = None
    tax_rule_id: int
    employee_rate_pct: Optional[Decimal] = None
    employer_rate_pct: Optional[Decimal] = None
    employee_flat_amount: Optional[Decimal] = None
    employer_flat_amount: Optional[Decimal] = None
    display_employee_share: Optional[str] = None
    display_employer_share: Optional[str] = None
    display_total: Optional[str] = None


class TaxRuleResponse(BaseModel):
    id: int
    tax_version_id: int
    rule_type: str
    label: Optional[str] = None
    formula_expression: Optional[str] = None
    sort_order: int
    slabs: List[TaxRuleSlabResponse] = []
    rates: List[TaxRuleRateResponse] = []


class TaxRuleUpsert(BaseModel):
    id: Optional[int] = None
    tax_version_id: int
    rule_type: str = "PROGRESSIVE_BRACKET"
    label: Optional[str] = None
    formula_expression: Optional[str] = None
    sort_order: int = 0


# ── TaxParameter ─────────────────────────────────────────────────────────

class TaxParameterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tax_version_id: int
    parameter_key: str
    label: str
    value_numeric: Optional[Decimal] = None
    value_text: Optional[str] = None
    unit: Optional[str] = None


class TaxParameterUpsert(BaseModel):
    id: Optional[int] = None
    tax_version_id: int
    parameter_key: str
    label: str
    value_numeric: Optional[Decimal] = None
    value_text: Optional[str] = None
    unit: Optional[str] = None


# ── Applicability / Audit ───────────────────────────────────────────────

class JurisdictionApplicabilityRow(BaseModel):
    organization_id: int
    organization_name: str
    organization_code: Optional[str] = None
    assignment_type: str
    status: str


class TaxVersionAuditRow(BaseModel):
    id: int
    actor_id: Optional[int] = None
    actor_name: Optional[str] = None
    action: str
    entity_type: str
    entity_id: int
    old_value: Optional[dict] = None
    new_value: Optional[dict] = None
    reason: Optional[str] = None
    created_at: datetime


# ── Organization-facing ──────────────────────────────────────────────────

class OrganizationJurisdictionAssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int
    jurisdiction_id: int
    assignment_type: str
    status: str
    effective_from: date
    effective_to: Optional[date] = None
    tax_regime: Optional[str] = None


class OrganizationJurisdictionAssignmentUpsert(BaseModel):
    id: Optional[int] = None
    jurisdiction_id: int
    assignment_type: str = "primary"
    status: str = "draft"
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    tax_regime: Optional[str] = None


class ApplicableComplianceConfigurationResponse(BaseModel):
    organization_id: int
    payroll_date: date
    jurisdiction_assignments: list
    applicable_taxes: list


class SuccessResponse(BaseModel):
    message: str
