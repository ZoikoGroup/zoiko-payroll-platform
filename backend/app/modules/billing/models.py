"""
modules/billing/models.py
--------------------------
SQLAlchemy ORM models for the Zoiko Payroll Commercial Layer (billing).

This module owns the billing data model described in the Commercial Layer
Implementation Blueprint §2.2 "New billing tables":

  - BillingPlan                    → immutable catalog of plan classes (CORE/
                                       PROFESSIONAL/BUSINESS/ENTERPRISE)
  - BillingPlanVersion              → a specific, versioned snapshot of a plan;
                                       immutable at the application layer once
                                       status=PUBLISHED
  - BillingEntitlementFlag          → normalized, queryable feature keys per
                                       plan version (denormalized from
                                       BillingPlanVersion.feature_set for fast
                                       lookups on the entitlement check path)
  - BillingEntitlementOverride      → temporary, time-boxed per-org entitlement
                                       overrides
  - BillingSubscription             → one active commercial relationship per org
  - BillingSubscriptionItem         → variable components on a subscription
                                       (BWM rate, entity packs, jurisdiction
                                       packs, add-ons)
  - BillingPriceCatalogItem         → versioned, approved price book — the only
                                       table a monetary unit_amount may live in
                                       across the whole app
  - BillingWorkerMonthRecord        → one row per employment relationship per
                                       billing month (BWM engine output; this
                                       module only stores the record, it does
                                       not compute it)
  - BillingInvoice                  → one invoice per org per billing cycle
  - BillingInvoiceLine              → individual line items on an invoice
  - BillingCreditNote                → a credit issued against an invoice
  - BillingDunningState              → current dunning stage per org
  - BillingCommercialAuditEvent      → append-only audit trail for commercial
                                       (billing/entitlement/subscription) events

This module does not import from or modify payroll, organizations, auth, or
super_admin models — it only references their primary keys via ForeignKey.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)

from app.database import Base


# ── Enums ────────────────────────────────────────────────────────────────

class PlanCode(str, enum.Enum):
    CORE = "CORE"
    PROFESSIONAL = "PROFESSIONAL"
    BUSINESS = "BUSINESS"
    ENTERPRISE = "ENTERPRISE"


class PlanVersionStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class BillingAuthority(str, enum.Enum):
    STANDALONE = "STANDALONE"
    ZOIKO_ONE_BUNDLE = "ZOIKO_ONE_BUNDLE"
    ENTERPRISE_ORDER_FORM = "ENTERPRISE_ORDER_FORM"


class SubscriptionStatus(str, enum.Enum):
    TRIALING = "TRIALING"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class CatalogItemStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"


class DunningStage(str, enum.Enum):
    RETRY = "RETRY"
    RESTRICT_EXPANSION = "RESTRICT_EXPANSION"
    RESTRICT_NEW_RUN = "RESTRICT_NEW_RUN"
    READ_ONLY = "READ_ONLY"


# ── Plan catalog ─────────────────────────────────────────────────────────

class BillingPlan(Base):
    """Immutable catalog of plan classes (CORE/PROFESSIONAL/BUSINESS/ENTERPRISE)."""
    __tablename__ = "billing_plans"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(30), unique=True, nullable=False)
    name = Column(String(100), nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<BillingPlan id={self.id} code={self.code}>"


class BillingPlanVersion(Base):
    """A specific, versioned snapshot of a plan.

    Once status == PlanVersionStatus.PUBLISHED, this row is immutable at the
    application layer — the service layer must reject any update to a
    published version and require a new version instead. Not enforced via a
    DB trigger.
    """
    __tablename__ = "billing_plan_versions"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("billing_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    status = Column(String(20), default=PlanVersionStatus.DRAFT.value, nullable=False)
    published_at = Column(DateTime, nullable=True)
    feature_set = Column(JSON, nullable=True)
    scale_limits = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("plan_id", "version", name="uq_billing_plan_version_plan_version"),
    )

    def __repr__(self):
        return f"<BillingPlanVersion id={self.id} plan_id={self.plan_id} version={self.version} status={self.status}>"


class BillingEntitlementFlag(Base):
    """Normalized, queryable feature keys per plan version.

    Denormalized from BillingPlanVersion.feature_set so the entitlement
    check path can query by feature_key without deserializing JSON.
    """
    __tablename__ = "billing_entitlement_flags"

    id = Column(Integer, primary_key=True, index=True)
    plan_version_id = Column(
        Integer, ForeignKey("billing_plan_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    feature_key = Column(String(100), nullable=False, index=True)
    # NULL means a boolean/unlimited flag (feature is simply on); a value
    # means a numeric limit (e.g. max_entities=1).
    limit_value = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("plan_version_id", "feature_key", name="uq_billing_entitlement_flag_version_key"),
    )

    def __repr__(self):
        return f"<BillingEntitlementFlag id={self.id} plan_version_id={self.plan_version_id} key={self.feature_key}>"


class BillingEntitlementOverride(Base):
    """Temporary, time-boxed per-org entitlement override.

    expires_at is indexed so a future sweep job can cheaply find all
    overrides expiring before now (e.g. `WHERE expires_at < :now`).
    """
    __tablename__ = "billing_entitlement_overrides"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    feature_key = Column(String(100), nullable=False, index=True)
    limit_value = Column(Integer, nullable=True)
    granted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    reason = Column(Text, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<BillingEntitlementOverride id={self.id} org_id={self.organization_id} key={self.feature_key} expires_at={self.expires_at}>"


# ── Subscriptions ────────────────────────────────────────────────────────

class BillingSubscription(Base):
    """One active commercial relationship for an org.

    v1 assumes exactly one active subscription per org — enforced via the
    unique constraint on organization_id.
    """
    __tablename__ = "billing_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(
        Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True, unique=True
    )
    plan_version_id = Column(Integer, ForeignKey("billing_plan_versions.id"), nullable=False, index=True)
    billing_authority = Column(String(30), default=BillingAuthority.STANDALONE.value, nullable=False)
    status = Column(String(20), default=SubscriptionStatus.TRIALING.value, nullable=False, index=True)
    current_period_start = Column(DateTime, nullable=False)
    current_period_end = Column(DateTime, nullable=False)
    stripe_subscription_id = Column(String(100), nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<BillingSubscription id={self.id} org_id={self.organization_id} status={self.status}>"


class BillingSubscriptionItem(Base):
    """A variable component on a subscription (BWM rate, entity packs,
    jurisdiction packs, add-ons)."""
    __tablename__ = "billing_subscription_items"

    id = Column(Integer, primary_key=True, index=True)
    subscription_id = Column(
        Integer, ForeignKey("billing_subscriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    component_type = Column(String(50), nullable=False)
    unit_price_catalog_ref = Column(Integer, ForeignKey("billing_price_catalog_items.id"), nullable=True, index=True)
    quantity = Column(Integer, default=1, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<BillingSubscriptionItem id={self.id} subscription_id={self.subscription_id} component_type={self.component_type}>"


class BillingPriceCatalogItem(Base):
    """Versioned, approved price book.

    The ONLY table a monetary unit_amount may live in across the whole app —
    every other billing table references a price via unit_price_catalog_ref
    rather than storing its own amount.
    """
    __tablename__ = "billing_price_catalog_items"

    id = Column(Integer, primary_key=True, index=True)
    catalog_version = Column(String(30), nullable=False, index=True)
    component_type = Column(String(50), nullable=False)
    currency = Column(String(3), nullable=False)
    unit_amount = Column(Numeric(12, 2), nullable=False)
    status = Column(String(20), default=CatalogItemStatus.DRAFT.value, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<BillingPriceCatalogItem id={self.id} catalog_version={self.catalog_version} component_type={self.component_type}>"


# ── Billable Worker Month (BWM) ──────────────────────────────────────────

class BillingWorkerMonthRecord(Base):
    """One row per employment relationship per billing month (BWM engine
    output). Write-only from this module's perspective — no BWM counting
    logic lives here.
    """
    __tablename__ = "billing_worker_month_records"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    # No employer-entity table exists yet in this repo. Store as a plain
    # nullable Integer for now; add a real ForeignKey once that table exists.
    employer_entity_id = Column(Integer, nullable=True)
    payroll_employee_id = Column(Integer, ForeignKey("payroll_employees.id"), nullable=False, index=True)
    billing_month = Column(Date, nullable=False)
    counted = Column(Boolean, default=True, nullable=False)
    reason_code = Column(String(50), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "payroll_employee_id", "billing_month",
            name="uq_billing_bwm_org_employee_month",
        ),
    )

    def __repr__(self):
        return f"<BillingWorkerMonthRecord id={self.id} org_id={self.organization_id} employee_id={self.payroll_employee_id} month={self.billing_month}>"


# ── Invoicing ────────────────────────────────────────────────────────────

class BillingInvoice(Base):
    __tablename__ = "billing_invoices"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    subscription_id = Column(Integer, ForeignKey("billing_subscriptions.id"), nullable=True, index=True)
    stripe_invoice_id = Column(String(100), nullable=True, index=True)
    status = Column(String(30), nullable=False)
    total = Column(Numeric(12, 2), nullable=False)
    tax_amount = Column(Numeric(12, 2), default=0, nullable=False)
    currency = Column(String(3), nullable=False)
    issued_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<BillingInvoice id={self.id} org_id={self.organization_id} status={self.status} total={self.total}>"


class BillingInvoiceLine(Base):
    __tablename__ = "billing_invoice_lines"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("billing_invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    description = Column(String(255), nullable=False)
    component_type = Column(String(50), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_amount = Column(Numeric(12, 2), nullable=False)
    line_total = Column(Numeric(12, 2), nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<BillingInvoiceLine id={self.id} invoice_id={self.invoice_id} component_type={self.component_type}>"


class BillingCreditNote(Base):
    __tablename__ = "billing_credit_notes"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("billing_invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    reason = Column(Text, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    approved_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<BillingCreditNote id={self.id} invoice_id={self.invoice_id} amount={self.amount}>"


# ── Dunning ──────────────────────────────────────────────────────────────

class BillingDunningState(Base):
    """Current dunning state for an org — one row per org."""
    __tablename__ = "billing_dunning_state"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(
        Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True, unique=True
    )
    stage = Column(String(30), default=DunningStage.RETRY.value, nullable=False)
    entered_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # True means an approved payroll run is currently in flight for this org
    # and must not be interrupted by a dunning restriction taking effect.
    in_flight_run_guard = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<BillingDunningState id={self.id} org_id={self.organization_id} stage={self.stage}>"


# ── Audit ────────────────────────────────────────────────────────────────

class BillingCommercialAuditEvent(Base):
    """Append-only audit trail for commercial (billing/entitlement/
    subscription) events. No update/delete path should ever be written
    against this table.
    """
    __tablename__ = "billing_commercial_audit_events"

    id = Column(Integer, primary_key=True, index=True)
    # Nullable because some events are platform-level, not org-scoped.
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    event_type = Column(String(80), nullable=False, index=True)
    payload = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self):
        return f"<BillingCommercialAuditEvent id={self.id} event_type={self.event_type} org_id={self.organization_id}>"
