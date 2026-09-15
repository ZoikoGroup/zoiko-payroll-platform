"""
modules/billing/schemas.py
---------------------------
Pydantic v2 schemas for the billing data model (see models.py). One
Create/Update/Response set per table added in Prompt 1, mirroring the
plain, explicit style used in organizations/schemas.py — snake_case field
names, `from_attributes=True` on every Response schema, no aliasing
gymnastics, and no business logic (validation of things like "a PUBLISHED
plan version is immutable" belongs in the service layer, not here).

This module does not import from or modify payroll, organizations, auth, or
super_admin schemas/models.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.modules.billing.models import (
    BillingAuthority,
    CatalogItemStatus,
    DunningStage,
    PlanCode,
    PlanVersionStatus,
    SubscriptionStatus,
)


# ── Plan catalog ─────────────────────────────────────────────────────────

class BillingPlanCreate(BaseModel):
    code: PlanCode
    name: str = Field(..., min_length=1, max_length=100)


class BillingPlanUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)


class BillingPlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    created_at: datetime
    updated_at: datetime


class BillingPlanVersionCreate(BaseModel):
    plan_id: int
    version: int
    feature_set: Optional[dict] = None
    scale_limits: Optional[dict] = None


class BillingPlanVersionUpdate(BaseModel):
    """Only meaningful while the version is still DRAFT/APPROVED — the
    service layer (plan_catalog.publish_plan_version) is the only path
    that may move a version to PUBLISHED, and a PUBLISHED version must
    never be updated through this schema again."""

    feature_set: Optional[dict] = None
    scale_limits: Optional[dict] = None
    status: Optional[PlanVersionStatus] = None


class BillingPlanVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    plan_id: int
    version: int
    status: str
    published_at: Optional[datetime] = None
    feature_set: Optional[dict] = None
    scale_limits: Optional[dict] = None
    created_at: datetime
    updated_at: datetime


class BillingEntitlementFlagCreate(BaseModel):
    plan_version_id: int
    feature_key: str = Field(..., min_length=1, max_length=100)
    limit_value: Optional[int] = None


class BillingEntitlementFlagUpdate(BaseModel):
    limit_value: Optional[int] = None


class BillingEntitlementFlagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    plan_version_id: int
    feature_key: str
    limit_value: Optional[int] = None
    created_at: datetime


class BillingEntitlementOverrideCreate(BaseModel):
    organization_id: int
    feature_key: str = Field(..., min_length=1, max_length=100)
    limit_value: Optional[int] = None
    granted_by_user_id: int
    reason: str = Field(..., min_length=1)
    expires_at: datetime


class BillingEntitlementOverrideUpdate(BaseModel):
    limit_value: Optional[int] = None
    reason: Optional[str] = Field(None, min_length=1)
    expires_at: Optional[datetime] = None


class BillingEntitlementOverrideResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    feature_key: str
    limit_value: Optional[int] = None
    granted_by_user_id: int
    reason: str
    expires_at: datetime
    created_at: datetime


# ── Subscriptions ────────────────────────────────────────────────────────

class BillingSubscriptionCreate(BaseModel):
    organization_id: int
    plan_version_id: int
    billing_authority: BillingAuthority = BillingAuthority.STANDALONE
    status: SubscriptionStatus = SubscriptionStatus.TRIALING
    current_period_start: datetime
    current_period_end: datetime
    stripe_subscription_id: Optional[str] = None


class BillingSubscriptionUpdate(BaseModel):
    plan_version_id: Optional[int] = None
    billing_authority: Optional[BillingAuthority] = None
    status: Optional[SubscriptionStatus] = None
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    stripe_subscription_id: Optional[str] = None


class BillingSubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    plan_version_id: int
    billing_authority: str
    status: str
    current_period_start: datetime
    current_period_end: datetime
    stripe_subscription_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class BillingSubscriptionItemCreate(BaseModel):
    subscription_id: int
    component_type: str = Field(..., min_length=1, max_length=50)
    unit_price_catalog_ref: Optional[int] = None
    quantity: int = 1


class BillingSubscriptionItemUpdate(BaseModel):
    unit_price_catalog_ref: Optional[int] = None
    quantity: Optional[int] = None


class BillingSubscriptionItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subscription_id: int
    component_type: str
    unit_price_catalog_ref: Optional[int] = None
    quantity: int
    created_at: datetime
    updated_at: datetime


class BillingPriceCatalogItemCreate(BaseModel):
    catalog_version: str = Field(..., min_length=1, max_length=30)
    component_type: str = Field(..., min_length=1, max_length=50)
    currency: str = Field(..., min_length=3, max_length=3)
    unit_amount: Decimal
    status: CatalogItemStatus = CatalogItemStatus.DRAFT


class BillingPriceCatalogItemUpdate(BaseModel):
    unit_amount: Optional[Decimal] = None
    status: Optional[CatalogItemStatus] = None


class BillingPriceCatalogItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    catalog_version: str
    component_type: str
    currency: str
    unit_amount: Decimal
    status: str
    created_at: datetime
    updated_at: datetime


# ── Billable Worker Month (BWM) ──────────────────────────────────────────

class BillingWorkerMonthRecordCreate(BaseModel):
    organization_id: int
    employer_entity_id: Optional[int] = None
    payroll_employee_id: int
    billing_month: date
    counted: bool = True
    reason_code: Optional[str] = None


class BillingWorkerMonthRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    employer_entity_id: Optional[int] = None
    payroll_employee_id: int
    billing_month: date
    counted: bool
    reason_code: Optional[str] = None
    created_at: datetime


# ── Invoicing ────────────────────────────────────────────────────────────

class BillingInvoiceCreate(BaseModel):
    organization_id: int
    subscription_id: Optional[int] = None
    stripe_invoice_id: Optional[str] = None
    status: str
    total: Decimal
    tax_amount: Decimal = Decimal("0")
    currency: str = Field(..., min_length=3, max_length=3)
    issued_at: Optional[datetime] = None


class BillingInvoiceUpdate(BaseModel):
    status: Optional[str] = None
    stripe_invoice_id: Optional[str] = None
    issued_at: Optional[datetime] = None


class BillingInvoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    subscription_id: Optional[int] = None
    stripe_invoice_id: Optional[str] = None
    status: str
    total: Decimal
    tax_amount: Decimal
    currency: str
    issued_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class BillingInvoiceLineCreate(BaseModel):
    invoice_id: int
    description: str = Field(..., min_length=1, max_length=255)
    component_type: str = Field(..., min_length=1, max_length=50)
    quantity: int
    unit_amount: Decimal
    line_total: Decimal


class BillingInvoiceLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_id: int
    description: str
    component_type: str
    quantity: int
    unit_amount: Decimal
    line_total: Decimal
    created_at: datetime


class BillingCreditNoteCreate(BaseModel):
    invoice_id: int
    reason: str = Field(..., min_length=1)
    amount: Decimal
    approved_by_user_id: int


class BillingCreditNoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_id: int
    reason: str
    amount: Decimal
    approved_by_user_id: int
    created_at: datetime


# ── Dunning ──────────────────────────────────────────────────────────────

class BillingDunningStateCreate(BaseModel):
    organization_id: int
    stage: DunningStage = DunningStage.RETRY
    in_flight_run_guard: bool = False


class BillingDunningStateUpdate(BaseModel):
    stage: Optional[DunningStage] = None
    in_flight_run_guard: Optional[bool] = None


class BillingDunningStateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    stage: str
    entered_at: datetime
    in_flight_run_guard: bool
    created_at: datetime
    updated_at: datetime


# ── Audit ────────────────────────────────────────────────────────────────
# Append-only — no BillingCommercialAuditEventUpdate exists, matching how
# EmployeeStatutoryProfile (payroll/models.py) and AssistAuditEvent
# (assist/models.py) offer no update schema for their own append-only rows.

class BillingCommercialAuditEventCreate(BaseModel):
    organization_id: Optional[int] = None
    actor_user_id: Optional[int] = None
    event_type: str = Field(..., min_length=1, max_length=80)
    payload: Optional[dict] = None


class BillingCommercialAuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: Optional[int] = None
    actor_user_id: Optional[int] = None
    event_type: str
    payload: Optional[dict] = None
    created_at: datetime


class BillingAuditEventListResponse(BaseModel):
    events: list[BillingCommercialAuditEventResponse]
    total: int


# ── Router request/response shapes (Prompt 3) ─────────────────────────────
# These are thin, path/current_user-aware variants of the Create schemas
# above — e.g. a plan version's create body never repeats {plan_id} once
# it's already in the URL. The table-mirroring Create/Update/Response
# schemas above remain the source of truth for each table's own shape.

class BillingPlanVersionCreateRequest(BaseModel):
    """Body for POST /super-admin/billing/plans/{plan_id}/versions.
    `version` is not accepted here — plan_catalog.create_plan_version
    auto-assigns the next version number for the plan, so a new DRAFT
    version is always a deliberate, server-numbered append, never a
    client-chosen number that could collide."""

    feature_set: Optional[dict] = None
    scale_limits: Optional[dict] = None


class BillingPlanVersionStatusTransition(BaseModel):
    """Body for PUT /super-admin/billing/plan-versions/{id}/status. Only
    DRAFT->APPROVED and APPROVED->PUBLISHED are valid targets; any other
    requested status is rejected by the router with 400."""

    status: PlanVersionStatus


class BillingEntitlementFlagCreateRequest(BaseModel):
    """Body for POST /super-admin/billing/plan-versions/{id}/entitlement-flags."""

    feature_key: str = Field(..., min_length=1, max_length=100)
    limit_value: Optional[int] = None


class BillingEntitlementOverrideCreateRequest(BaseModel):
    """Body for POST /super-admin/billing/organizations/{org_id}/entitlement-overrides.
    `organization_id` comes from the URL and `granted_by_user_id` from the
    authenticated super admin — neither is accepted in the body."""

    feature_key: str = Field(..., min_length=1, max_length=100)
    limit_value: Optional[int] = None
    reason: str = Field(..., min_length=1)
    expires_at: datetime


class BillingPublishedPlanResponse(BaseModel):
    """GET /billing/plans — one entry per plan that currently has a
    PUBLISHED version, with that version's entitlement flags resolved.
    No price data — billing_price_catalog_items is out of scope here."""

    plan_id: int
    code: str
    name: str
    plan_version_id: int
    version: int
    published_at: Optional[datetime] = None
    feature_set: Optional[dict] = None
    scale_limits: Optional[dict] = None
    entitlement_flags: dict = {}


class BillingMySubscriptionResponse(BaseModel):
    """GET /billing/my-subscription."""

    subscription: BillingSubscriptionResponse
    entitlement_flags: dict = {}
