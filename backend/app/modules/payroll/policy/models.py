"""
modules/payroll/policy/models.py
---------------------------------
SQLAlchemy ORM models for Payroll Policy Management.

This is an ADDITIVE submodule — it does not modify any table in
app/modules/payroll/models.py. Every table here is new and org-scoped.

Tables:
  - PayrollPolicy                     -> one row per named policy per org
  - PolicyEmployeeCategory             -> per-category rules (Full Time, Part Time, Intern, ...)
  - PolicyLeaveRule                    -> per policy leave-type config
  - PolicyOvertimeRule                 -> per policy overtime config
  - PolicyIntegration                  -> per policy provider enable/disable

If no PayrollPolicy row exists for an organization, the payroll engine falls
back to today's exact behavior (see service.py dispatch in Step 3) — this
submodule is safe to deploy with zero behavior change until an org is
explicitly switched onto a non-default policy.
"""

import enum
from sqlalchemy import (
    Column, Integer, String, Date, DateTime, Boolean,
    ForeignKey, Text, UniqueConstraint, Index, JSON, Numeric,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
# Hardcoded column defaults moved to hardcoded_defaults.py (the
# consolidated home for every hardcoded fallback value in the payroll
# module) — imported back under their original meaning, same values.
from app.modules.payroll.hardcoded_defaults import (
    _POLICY_DEFAULT_BASIC_PCT, _POLICY_DEFAULT_HRA_PCT, _POLICY_DEFAULT_WORKING_DAYS,
    _POLICY_DEFAULT_EXPECTED_HOURS, _POLICY_DEFAULT_MINIMUM_HOURS,
    _POLICY_DEFAULT_GRACE_TIME_MINUTES, _POLICY_DEFAULT_MINIMUM_OVERTIME_MINUTES,
)


class CalculationMode(str, enum.Enum):
    SIMPLE     = "simple"       # Frontend label: "Simple Payroll"
    STANDARD   = "standard"     # Frontend label: "Standard Payroll" (today's engine)
    ENTERPRISE = "enterprise"   # Frontend label: "Enterprise Payroll"


class EmployeeCategoryType(str, enum.Enum):
    FULL_TIME  = "full_time"
    PART_TIME  = "part_time"
    INTERN     = "intern"
    CONTRACT   = "contract"
    CONSULTANT = "consultant"
    FREELANCER = "freelancer"


class IntegrationCategory(str, enum.Enum):
    ATTENDANCE    = "attendance"
    BANKING       = "banking"
    NOTIFICATIONS = "notifications"


class LeaveRuleType(str, enum.Enum):
    PAID_LEAVE    = "paid_leave"
    UNPAID_LEAVE  = "unpaid_leave"
    HALF_DAY      = "half_day"
    ABSENT        = "absent"
    HOLIDAY       = "holiday"
    WEEK_OFF      = "week_off"
    INTERN_LEAVE  = "intern_leave"


# ── Policy (General section) ────────────────────────────────────────────

class PayrollPolicy(Base):
    __tablename__ = "payroll_policies"

    id              = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    name            = Column(String(120), nullable=False)
    description     = Column(Text, nullable=True)
    status          = Column(String(20), default="active", nullable=False)   # active | inactive | draft
    effective_date  = Column(Date, nullable=False, server_default=func.now())
    is_default      = Column(Boolean, default=False, nullable=False)

    calculation_mode = Column(String(20), default=CalculationMode.STANDARD.value, nullable=False)

    # Salary structure — what share of monthly gross becomes Basic vs HRA
    # (Special Allowance is always the remainder: gross - basic - hra).
    # This is an organizational compensation-structure choice, not a tax
    # law figure, so it lives here (lockable via policy_defaults, same as
    # calculation_mode) rather than on the canonical tax pack. Only applies
    # to employees who don't have their own explicit Basic/HRA amounts set
    # (see _resolve_salary_split_pct in payroll/service.py).
    basic_pct = Column(Numeric(5, 2), default=_POLICY_DEFAULT_BASIC_PCT, nullable=False)
    hra_pct   = Column(Numeric(5, 2), default=_POLICY_DEFAULT_HRA_PCT, nullable=False)

    # Format used to generate the post-approval bank transfer file for a
    # payroll run (see app/modules/payroll/bank_export/). Independent of the
    # older Banking integration toggles above — this is a dedicated setting
    # for the new export pipeline, not a provider enable/disable flag.
    bank_export_format = Column(String(10), default="csv", nullable=False)   # csv | xlsx | txt | pdf

    # Enterprise onboarding status — see app/modules/payroll/enterprise/.
    # Independent of `calculation_mode`: calculation_mode only flips to
    # "enterprise" once activation succeeds; enterprise_status tracks
    # onboarding progress even before that (not_configured|in_progress|
    # configured|active), so the Policy page can show real progress instead
    # of a binary switched/not-switched state.
    enterprise_status      = Column(String(20), default="not_configured", nullable=False)
    enterprise_activated_at = Column(DateTime(timezone=True), nullable=True)

    # Set the first time an admin explicitly saves this policy via
    # update_policy() — never by _seed_default_policy()'s auto-creation on
    # first GET. This is the real "has an admin configured Payroll Policy"
    # signal the mandatory onboarding gate needs: row existence alone can't
    # tell an auto-seeded default apart from an intentional save.
    configured_at           = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    employee_categories = relationship("PolicyEmployeeCategory", back_populates="policy", cascade="all, delete-orphan")
    leave_rules          = relationship("PolicyLeaveRule", back_populates="policy", cascade="all, delete-orphan")
    overtime_rule        = relationship("PolicyOvertimeRule", back_populates="policy", uselist=False, cascade="all, delete-orphan")
    integrations         = relationship("PolicyIntegration", back_populates="policy", cascade="all, delete-orphan")
    allowance_components = relationship(
        "PolicyAllowanceComponent", back_populates="policy",
        cascade="all, delete-orphan", order_by="PolicyAllowanceComponent.sort_order",
    )

    __table_args__ = (
        Index("ix_payroll_policies_org_status", "organization_id", "status"),
        # Only one default policy per organization:
        UniqueConstraint("organization_id", "is_default", name="uq_one_default_per_org",
                          sqlite_on_conflict=None),
    )

    @property
    def is_configured(self) -> bool:
        """True once an admin has explicitly saved this policy at least
        once — see configured_at above."""
        return self.configured_at is not None

    def __repr__(self):
        return f"<PayrollPolicy id={self.id} org={self.organization_id} mode={self.calculation_mode}>"


# ── Employee Categories ──────────────────────────────────────────────────

class PolicyEmployeeCategory(Base):
    __tablename__ = "payroll_policy_employee_categories"

    id        = Column(Integer, primary_key=True, index=True)
    policy_id = Column(Integer, ForeignKey("payroll_policies.id"), nullable=False, index=True)

    category         = Column(String(20), nullable=False)   # EmployeeCategoryType value
    working_days     = Column(Integer, nullable=False, default=_POLICY_DEFAULT_WORKING_DAYS)
    weekly_off       = Column(JSON, nullable=True)           # e.g. ["Saturday", "Sunday"]
    expected_hours   = Column(Integer, nullable=False, default=_POLICY_DEFAULT_EXPECTED_HOURS)
    minimum_hours    = Column(Integer, nullable=False, default=_POLICY_DEFAULT_MINIMUM_HOURS)
    paid_leave_eligible = Column(Boolean, nullable=False, default=True)
    grace_time_minutes  = Column(Integer, nullable=False, default=_POLICY_DEFAULT_GRACE_TIME_MINUTES)
    half_day_rule       = Column(JSON, nullable=True)        # e.g. {"thresholdHours": 4}

    policy = relationship("PayrollPolicy", back_populates="employee_categories")

    __table_args__ = (
        UniqueConstraint("policy_id", "category", name="uq_policy_category"),
    )


# ── Allowance Components (dynamic, Super-Admin-defined) ──────────────────
# Super Admin defines the available components + defaults on the canonical
# side (JurisdictionPack.policy_defaults["allowance_components"], a dict
# keyed by `key`, same {value, allowOverride} lock shape already used for
# basic_pct/hra_pct/employee_categories — see policy/service.py's
# _apply_allowance_component_defaults). This table is the org's own
# resolved/materialized set of components, seeded/locked from those
# defaults, exactly the same two-tier pattern PolicyEmployeeCategory
# already uses. `key` is admin-typed (e.g. "transport", "medical", "other",
# or any custom slug) — arbitrary and unbounded, which is why this is a
# real child table rather than fixed columns on PayrollPolicy.
class PolicyAllowanceComponent(Base):
    __tablename__ = "payroll_policy_allowance_components"

    id        = Column(Integer, primary_key=True, index=True)
    policy_id = Column(Integer, ForeignKey("payroll_policies.id"), nullable=False, index=True)

    key   = Column(String(50), nullable=False)   # admin-defined slug, e.g. "transport"
    label = Column(String(100), nullable=False)  # display name, e.g. "Transport Allowance"

    # Exactly one of these two is set — percentage of monthly gross, or a
    # flat monthly amount. Same either/or shape ContributionRate already
    # uses for employee_rate_pct vs flat_amount.
    pct         = Column(Numeric(6, 2), nullable=True)
    flat_amount = Column(Numeric(12, 2), nullable=True)

    allow_override = Column(Boolean, nullable=False, default=True)
    sort_order     = Column(Integer, default=0)

    policy = relationship("PayrollPolicy", back_populates="allowance_components")

    __table_args__ = (
        UniqueConstraint("policy_id", "key", name="uq_policy_allowance_component_key"),
    )


# ── Leave Rules ───────────────────────────────────────────────────────────

class PolicyLeaveRule(Base):
    __tablename__ = "payroll_policy_leave_rules"

    id        = Column(Integer, primary_key=True, index=True)
    policy_id = Column(Integer, ForeignKey("payroll_policies.id"), nullable=False, index=True)

    rule_type = Column(String(20), nullable=False)   # LeaveRuleType value
    config    = Column(JSON, nullable=True)

    policy = relationship("PayrollPolicy", back_populates="leave_rules")

    __table_args__ = (
        UniqueConstraint("policy_id", "rule_type", name="uq_policy_leave_rule_type"),
    )


# ── Overtime Rules ────────────────────────────────────────────────────────

class PolicyOvertimeRule(Base):
    __tablename__ = "payroll_policy_overtime_rules"

    id        = Column(Integer, primary_key=True, index=True)
    policy_id = Column(Integer, ForeignKey("payroll_policies.id"), nullable=False, unique=True, index=True)

    enabled              = Column(Boolean, nullable=False, default=False)
    minimum_overtime_minutes = Column(Integer, nullable=False, default=_POLICY_DEFAULT_MINIMUM_OVERTIME_MINUTES)
    approval_required    = Column(Boolean, nullable=False, default=True)

    policy = relationship("PayrollPolicy", back_populates="overtime_rule")


# ── Integrations ──────────────────────────────────────────────────────────

class PolicyIntegration(Base):
    __tablename__ = "payroll_policy_integrations"

    id        = Column(Integer, primary_key=True, index=True)
    policy_id = Column(Integer, ForeignKey("payroll_policies.id"), nullable=False, index=True)

    category     = Column(String(20), nullable=False)   # IntegrationCategory value
    provider_key = Column(String(50), nullable=False)   # e.g. "zoiko_time", "manual_transfer", "email"
    enabled      = Column(Boolean, nullable=False, default=False)

    policy = relationship("PayrollPolicy", back_populates="integrations")

    __table_args__ = (
        UniqueConstraint("policy_id", "category", "provider_key", name="uq_policy_integration"),
    )