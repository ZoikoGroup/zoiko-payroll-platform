"""
modules/organizations/models.py
-------------------------------
Organization model — the multi-tenant root entity of the standalone Payroll
Platform. Replaces the old platform's hr.models.Organization and the
billing BillingConfiguration pre-fill (address / email / phone / tax
details that payroll's get_company_details used to read).

Every payroll row is scoped by organization_id; Super Admin is the only
role that may see across organizations.
"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, Column, DateTime, Integer, String, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)
    organization_name = Column(String(200), nullable=False)
    organization_code = Column(String(20), unique=True, index=True, nullable=False)

    # Contact / registration details (used for payroll company-details pre-fill)
    industry = Column(String(100), nullable=True)
    company_type = Column(String(100), nullable=True)
    address = Column(Text, nullable=True)
    city = Column(String(100), nullable=True)
    state = Column(String(100), nullable=True)
    country = Column(String(100), nullable=True)
    email = Column(String(200), nullable=True)
    phone = Column(String(40), nullable=True)
    # Single column covering GST/PAN/VAT/TIN — mirrors the main platform's
    # BillingConfiguration tax_no which payroll read for the payslip/report footer.
    tax_no = Column(String(50), nullable=True)
    registration_number = Column(String(100), nullable=True)
    # Jurisdiction-aware business tax/registration identifiers collected at
    # registration, keyed by the field keys in app/core/jurisdiction.py
    # (e.g. {"gstin": "...", "pan": "...", "cin": "..."}). Kept as JSON so the
    # field set is driven entirely by the jurisdiction schema — no new columns
    # per country. The primary identifier is also mirrored into tax_no above.
    tax_identifiers = Column(JSON, nullable=True)
    # Path to the uploaded logo file on disk (jpg/svg only) — never exposed
    # directly; served back to the frontend as a base64 data URI via
    # OrganizationDetail.logo_data_uri so no separate public image route
    # or auth-header-on-<img> workaround is needed.
    logo_path = Column(String(500), nullable=True)

    # Explicit ISO 4217 currency override (e.g. "USD"), managed by Super
    # Admin under Finance. Nullable — when unset, the frontend derives the
    # currency from jurisdiction_country (see utils/currency.js) exactly as
    # before; this column only exists for the cases where an org's actual
    # payroll currency doesn't match its jurisdiction's default.
    currency = Column(String(3), nullable=True)

    # Workspace flavor: "PRODUCTION" (regular tenant onboarded via
    # /auth/register) or "EVALUATION" (30-day free evaluation onboarded via
    # /auth/register-trial). Existing rows created before this column existed
    # read as PRODUCTION (NULL == PRODUCTION).
    workspace_type = Column(String(20), nullable=False, default="PRODUCTION")
    # ZP-PRIV F02: where this tenant's data lives (EU, UK, US, IN, ME, APAC -
    # decision 9). Privileged retrieval from a deployment in another region is
    # refused (app/modules/security/governance.py).
    data_region = Column(String(8), nullable=False, default="EU", server_default="EU")
    # Explicit onboarding state for paid self-service registration. A failed
    # Checkout leaves the organization recoverable instead of looking subscribed.
    billing_onboarding_status = Column(String(30), nullable=False, default="PENDING_CHECKOUT")
    terms_accepted_at = Column(DateTime, nullable=True)

    # UK "connected employer" grouping (ZP-TAX-UK-2026-27-001 §14
    # gap-closure Part 7B, 2026-09-09) — HMRC requires connected employers
    # (commonly owned/controlled group companies) to share ONE £10,500
    # Employment Allowance cap between them, not one each. Orgs sharing
    # the same non-null code here are treated as one connected group;
    # NULL (the default) behaves exactly as before — a lone org checked
    # only against its own accumulator. No UI sets this yet — same
    # disclosed "no admin surface yet" pattern as bc_eht_employer_
    # classification/qc_hsf_employer_category on CompanyComplianceDetails.
    connected_group_code = Column(String(50), nullable=True, index=True)

    # ── Commercial account ledger (Commercial Billing & Subscription
    # Operating Standard §A1) — the single source of truth for whether this
    # org may ever be charged, and by which commercial route. Every new
    # org defaults to NON_CHARGEABLE/charge_enabled=False; a human (Super
    # Admin, via trial conversion or Enterprise Order Form recording) is
    # the only thing that ever flips these to COMMERCIAL_ACTIVE/True — see
    # billing/entitlements.py's is_billable().
    billing_classification = Column(String(30), nullable=False, default="NON_CHARGEABLE")
    # COMMERCIAL_ACTIVE | NON_CHARGEABLE | LEGACY | INTERNAL | DEMO | QA
    charge_enabled = Column(Boolean, nullable=False, default=False)
    commercial_account_id = Column(String(50), nullable=True, unique=True, index=True)
    # Set once, the moment recurring charges may legally begin (Part 2) —
    # never inferred from workspace existing, checkout completing, or an
    # admin account existing. May be future-dated for a negotiated delayed
    # start; a subscription is only real-billable once this is set AND past.
    service_commencement_at = Column(DateTime, nullable=True)
    commercial_route = Column(String(30), nullable=True)
    # STANDALONE | ZOIKO_ONE_BUNDLE | ENTERPRISE_ORDER_FORM — mirrors
    # billing.models.BillingAuthority; kept as a separate column (not just
    # read off BillingSubscription.billing_authority) because an org can be
    # commercially routed before any subscription row exists at all.

    # Tenant is onboarded by /auth/register and becomes active immediately
    # (no billing module in the standalone platform). Super Admin may suspend it.
    is_active = Column(Boolean, default=True, nullable=False)

    created_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    users = relationship(
        "User",
        back_populates="organization",
        foreign_keys="[User.organization_id]",
    )

    def __repr__(self):
        return f"<Organization id={self.id} code={self.organization_code} name={self.organization_name!r}>"


class LegalEntity(Base):
    """One row per legal entity registered under an Organization.

    Net-new concept: before this, there was no first-class way to represent
    "how many legal entities does this org have" anywhere in the schema —
    every org was implicitly exactly one entity. This exists specifically
    so billing's max_entities plan limit (see billing/feature_keys.py) has
    a real row count to check against, not a fabricated number. Every org
    is expected to have at least one row here (its own, created alongside
    the org itself is NOT automated yet — see organizations/router.py's
    list-legal-entities endpoint, which returns an empty list for an org
    that hasn't created any yet; the entitlement check treats "about to
    create the 1st" the same as any other count+1 check).
    """
    __tablename__ = "legal_entities"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    name = Column(String(200), nullable=False)
    registration_number = Column(String(100), nullable=True)
    country = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<LegalEntity id={self.id} organization_id={self.organization_id} name={self.name!r}>"


class PayGroup(Base):
    """A pay group inside an organization (ZP-PRIV C.1): the unit a scoped
    payroll admin or a JIT support grant can be limited to. Optionally tied
    to one legal entity."""
    __tablename__ = "pay_groups"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_pay_groups_org_name"),
    )

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    legal_entity_id = Column(Integer, ForeignKey("legal_entities.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String(120), nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class UserScopeAssignment(Base):
    """Limits a tenant user to legal entities and/or pay groups (ZP-PRIV
    B02/C.1). A user with no rows is organization-wide; a user with at least
    one row sees ONLY workers whose legal entity or pay group is assigned —
    an unassigned worker is invisible to a scoped user (fail closed).
    org_admin is always organization-wide; assignments apply to
    payroll_admin."""
    __tablename__ = "user_scope_assignments"
    __table_args__ = (
        CheckConstraint(
            "(legal_entity_id IS NOT NULL AND pay_group_id IS NULL) OR "
            "(legal_entity_id IS NULL AND pay_group_id IS NOT NULL)",
            name="ck_user_scope_exactly_one_target",
        ),
        UniqueConstraint("user_id", "legal_entity_id", "pay_group_id", name="uq_user_scope_target"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    legal_entity_id = Column(Integer, ForeignKey("legal_entities.id", ondelete="CASCADE"), nullable=True, index=True)
    pay_group_id = Column(Integer, ForeignKey("pay_groups.id", ondelete="CASCADE"), nullable=True, index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
