"""
modules/payroll/hierarchy/models.py
------------------------------------
SQLAlchemy ORM models for the generic jurisdiction/tax hierarchy engine.

This is an ADDITIVE submodule — it does not modify any existing table.
`JurisdictionPack`/`ContributionRate`/`TaxSlab`/`CompanyComplianceDetails`/
`EnterpriseJurisdiction`/`TaxConfigurationAudit` (app/modules/payroll/models.py,
app/modules/payroll/enterprise/models.py) are kept exactly as they are,
forever — every payslip ever generated references them
(`PayslipItem.tax_policy_pack_id`/`tax_rule_snapshot`), and historical
payroll must remain reproducible byte-for-byte. Nothing here reads from or
writes to those tables directly; a one-time migration script
(backend/scripts/migrate_tax_hierarchy.py, a later phase) populates these
new tables FROM the old ones.

Replaces the old model's fixed two-level geography (`jurisdiction_country`
+ optional single `jurisdiction_state`) with a generic, per-country
configurable depth:

    Country -> JurisdictionLevel (ordered, per-country) -> Jurisdiction (self-referential tree)
        -> Tax (the concept, e.g. "Income Tax") -> TaxVersion (effective-dated)
            -> TaxRule (one calculation mechanism: bracket / flat rate / formula / ...)
                -> TaxRuleSlab (bracket rows) | TaxRuleRate (percentage/flat leg)
            -> TaxParameter (standalone named constants, e.g. "standard_deduction")

Org-facing:
    OrganizationJurisdictionAssignment  -> which jurisdictions apply to an org, effective-dated
    OrganizationTaxOverride             -> an explicit, auditable, approved org-specific override
    TaxVersionAudit                     -> audit trail for every mutation in this submodule

Tables:
  - Country
  - JurisdictionLevel
  - Jurisdiction
  - Tax
  - TaxVersion
  - TaxRule
  - TaxRuleSlab
  - TaxRuleRate
  - TaxParameter
  - OrganizationJurisdictionAssignment
  - OrganizationTaxOverride
  - TaxVersionAudit

Nothing in this file is read by the payroll engine yet — it is wired in
behind an explicit per-organization flag
(`CompanyComplianceDetails.tax_hierarchy_v2_enabled`, see
app/modules/payroll/models.py) that defaults to False for every existing
and new organization, so creating these tables is a pure no-op for every
org until that flag is deliberately flipped on a case-by-case basis.
"""

from sqlalchemy import (
    Column, Integer, String, Date, DateTime, Boolean, Numeric, Text, JSON,
    ForeignKey, UniqueConstraint, Index, CheckConstraint, text,
)
from sqlalchemy.sql import func
from app.database import Base


class Country(Base):
    """Root of the hierarchy. One row per country the platform supports."""
    __tablename__ = "payroll_hierarchy_countries"

    id       = Column(Integer, primary_key=True, index=True)
    code     = Column(String(2), nullable=False, unique=True, index=True)  # "IN", "US", "UK", "AU", "DE", "CA"
    name     = Column(String(100), nullable=False)
    currency = Column(String(10), nullable=True)  # default currency; a TaxVersion may override

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class JurisdictionLevel(Base):
    """Per-country ORDERED depth definition — this is what makes the
    hierarchy configurable instead of hardcoded: India defines
    Central/State (rank 0/1); a country needing County/City later adds
    rows here, with zero schema change and zero UI-code change once the
    UI reads this table instead of a fixed dropdown."""
    __tablename__ = "payroll_hierarchy_levels"

    id         = Column(Integer, primary_key=True, index=True)
    country_id = Column(Integer, ForeignKey("payroll_hierarchy_countries.id"), nullable=False, index=True)

    level_code = Column(String(30), nullable=False)  # "NATIONAL" | "STATE" | "COUNTY" | "CITY" | "LOCAL"
    label      = Column(String(50), nullable=False)  # display label, e.g. "Central" (IN), "Federal" (US/DE), "Länder" (DE)
    rank       = Column(Integer, nullable=False)      # 0-based depth; 0 = country root

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("country_id", "level_code", name="uq_hierarchy_level_country_code"),
        UniqueConstraint("country_id", "rank", name="uq_hierarchy_level_country_rank"),
    )


class Jurisdiction(Base):
    """Generic self-referential hierarchy node. Even a country-level fact
    is a Jurisdiction row (level=NATIONAL, parent=null) — there is no
    separate "country" vs "state" column anywhere downstream; every
    TaxVersion links to exactly one jurisdiction_id, uniformly, regardless
    of depth."""
    __tablename__ = "payroll_hierarchy_jurisdictions"

    id                     = Column(Integer, primary_key=True, index=True)
    country_id             = Column(Integer, ForeignKey("payroll_hierarchy_countries.id"), nullable=False, index=True)
    level_id               = Column(Integer, ForeignKey("payroll_hierarchy_levels.id"), nullable=False, index=True)
    parent_jurisdiction_id = Column(Integer, ForeignKey("payroll_hierarchy_jurisdictions.id"), nullable=True, index=True)

    name         = Column(String(150), nullable=False)  # e.g. "India", "Telangana", "Hyderabad"
    code         = Column(String(50), nullable=True)     # short code, e.g. "TG" — distinct from the 2-letter country code
    external_ref = Column(String(100), nullable=True)    # ISO-3166-2/FIPS-style code, for future integrations
    is_active    = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("country_id", "level_id", "parent_jurisdiction_id", "name", name="uq_hierarchy_jurisdiction_identity"),
    )


class Tax(Base):
    """The concept — e.g. "Income Tax", "PF", "ESI", "PT" — not tied to a
    specific version or jurisdiction. Replaces `ContributionRate.component_key`/
    the implicit "a TaxSlab group is income tax" convention with a real row."""
    __tablename__ = "payroll_hierarchy_taxes"

    id         = Column(Integer, primary_key=True, index=True)
    country_id = Column(Integer, ForeignKey("payroll_hierarchy_countries.id"), nullable=False, index=True)

    tax_code    = Column(String(50), nullable=False)   # stable machine key, e.g. "INCOME_TAX" | "PF" | "ESI" | "PT"
    name        = Column(String(150), nullable=False)  # display label
    category    = Column(String(20), nullable=False, default="other_statutory")  # "income_tax" | "social_contribution" | "other_statutory"
    description = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("country_id", "tax_code", name="uq_hierarchy_tax_country_code"),
    )


class TaxVersion(Base):
    """An effective-dated version of a Tax within ONE Jurisdiction —
    replaces `JurisdictionPack` for pack_type="tax" rows only (policy
    packs already have their own working override system via
    PayrollPolicy/policy_defaults and are untouched by this submodule).

    Real overlap/duplicate-Active validation lives in
    hierarchy/service.py::activate_tax_version — this column set alone
    does not prevent two Active versions of the same Tax+Jurisdiction
    with overlapping effective dates; the OLD system had exactly that bug
    live (two simultaneously-Active Canada tax packs), and that bug is
    fixed at the service layer, not by a DB constraint alone, matching
    this codebase's existing convention of enforcing business rules in
    the service layer rather than the schema.
    """
    __tablename__ = "payroll_hierarchy_tax_versions"

    id              = Column(Integer, primary_key=True, index=True)
    tax_id          = Column(Integer, ForeignKey("payroll_hierarchy_taxes.id"), nullable=False, index=True)
    jurisdiction_id = Column(Integer, ForeignKey("payroll_hierarchy_jurisdictions.id"), nullable=False, index=True)

    version_label = Column(String(20), nullable=False)  # e.g. "1.0"
    tax_year      = Column(String(20), nullable=True)   # e.g. "2026-27"
    tax_regime    = Column(String(20), nullable=True)    # e.g. "Old" | "New"
    status        = Column(String(20), nullable=False, default="Draft")  # Draft|Scheduled|Active|Expired|Retired|Deprecated

    effective_from = Column(Date, nullable=False)
    effective_to   = Column(Date, nullable=True)
    currency       = Column(String(10), nullable=True)

    previous_version_id = Column(Integer, ForeignKey("payroll_hierarchy_tax_versions.id"), nullable=True)

    compliance_owner      = Column(String(150), nullable=True)
    engineering_owner     = Column(String(150), nullable=True)
    regulatory_authority  = Column(String(200), nullable=True)
    compliance_category   = Column(String(100), nullable=True)
    source_references     = Column(Text, nullable=True)
    change_summary        = Column(Text, nullable=True)
    next_review_date      = Column(Date, nullable=True)

    approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_by_id  = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by_id  = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Migration-traceability bridge only — never read by any resolution
    # logic; lets a human or a script trace a v2 TaxVersion back to the
    # exact legacy JurisdictionPack row it was migrated from.
    legacy_pack_id = Column(Integer, ForeignKey("payroll_jurisdiction_packs.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_hierarchy_tax_version_lookup", "tax_id", "jurisdiction_id", "status"),
        Index("ix_hierarchy_tax_version_effective", "jurisdiction_id", "effective_from"),
    )


class TaxRule(Base):
    """One calculation mechanism within a TaxVersion — generalizes the old
    `TaxSlab.rule_type` concept to apply to every kind of tax, not just
    income-tax slabs."""
    __tablename__ = "payroll_hierarchy_tax_rules"

    id             = Column(Integer, primary_key=True, index=True)
    tax_version_id = Column(Integer, ForeignKey("payroll_hierarchy_tax_versions.id"), nullable=False, index=True)

    # PROGRESSIVE_BRACKET | FLAT_RATE | FIXED_PLUS_MARGINAL | FORMULA | TABLE_LOOKUP | CONTRIBUTION
    rule_type          = Column(String(30), nullable=False, default="PROGRESSIVE_BRACKET")
    label              = Column(String(150), nullable=True)  # display (consolidates old rate_label/tax_formula text)
    formula_expression = Column(Text, nullable=True)          # only for rule_type=FORMULA; evaluated by the
                                                                # SAME, unchanged engine/standard.py::evaluate_tax_formula
    sort_order = Column(Integer, nullable=False, default=0)

    # Migration-traceability bridge only.
    legacy_component_key = Column(String(50), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class TaxRuleSlab(Base):
    """A bracket row — child of a PROGRESSIVE_BRACKET / FIXED_PLUS_MARGINAL
    / TABLE_LOOKUP rule. Generalizes `TaxSlab`.

    rate_pct is nullable here — the old TaxSlab.rate_pct was NOT NULL,
    which is a confirmed real bug: it made it impossible to correctly
    represent a purely flat-fee slab band (e.g. a Professional Tax band
    that's a flat rupee amount, not a percentage), forcing a workaround
    of storing 0 and putting the real amount in a display-only label
    field, which produced meaningless "0% tax" data. flat_fee_amount is
    the correct home for that value now.
    """
    __tablename__ = "payroll_hierarchy_tax_rule_slabs"

    id          = Column(Integer, primary_key=True, index=True)
    tax_rule_id = Column(Integer, ForeignKey("payroll_hierarchy_tax_rules.id"), nullable=False, index=True)

    min_amount      = Column(Numeric(14, 2), nullable=False)
    max_amount      = Column(Numeric(14, 2), nullable=True)   # null = "and above"
    rate_pct        = Column(Numeric(7, 4), nullable=True)
    flat_fee_amount = Column(Numeric(12, 2), nullable=True)
    rate_label      = Column(String(30), nullable=True)
    sort_order      = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("rate_pct IS NOT NULL OR flat_fee_amount IS NOT NULL", name="ck_tax_rule_slab_has_value"),
    )


class TaxRuleRate(Base):
    """A single percentage/flat leg — child of a FLAT_RATE / CONTRIBUTION
    rule. Generalizes `ContributionRate`'s numeric fields. One TaxRule of
    this rule_type has exactly one TaxRuleRate child (unlike slabs, which
    have many rows per rule)."""
    __tablename__ = "payroll_hierarchy_tax_rule_rates"

    id          = Column(Integer, primary_key=True, index=True)
    tax_rule_id = Column(Integer, ForeignKey("payroll_hierarchy_tax_rules.id"), nullable=False, index=True)

    employee_rate_pct     = Column(Numeric(7, 4), nullable=True)
    employer_rate_pct     = Column(Numeric(7, 4), nullable=True)
    employee_flat_amount  = Column(Numeric(12, 2), nullable=True)
    employer_flat_amount  = Column(Numeric(12, 2), nullable=True)

    display_employee_share = Column(String(50), nullable=True)
    display_employer_share = Column(String(50), nullable=True)
    display_total           = Column(String(50), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class TaxParameter(Base):
    """A standalone named constant (today's "fixed semantic key"
    ContributionRate rows, e.g. "standard_deduction", "esi_wage_ceiling")
    — a direct child of a TaxVersion, not of a rule, since it's a
    referenced value the engine looks up by name, not a calculation
    mechanism in its own right."""
    __tablename__ = "payroll_hierarchy_tax_parameters"

    id             = Column(Integer, primary_key=True, index=True)
    tax_version_id = Column(Integer, ForeignKey("payroll_hierarchy_tax_versions.id"), nullable=False, index=True)

    parameter_key = Column(String(60), nullable=False)   # e.g. "standard_deduction", "esi_wage_ceiling"
    label         = Column(String(150), nullable=False)
    value_numeric = Column(Numeric(14, 2), nullable=True)
    value_text    = Column(String(100), nullable=True)    # for non-numeric constants
    unit          = Column(String(20), nullable=True)     # "currency" | "percent" | "count" | "days"

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tax_version_id", "parameter_key", name="uq_hierarchy_tax_parameter_key"),
    )


class OrganizationJurisdictionAssignment(Base):
    """Which jurisdictions apply to which org, effective-dated — replaces
    `CompanyComplianceDetails.active_pack_id` for tax purposes (that
    column stays, unchanged, for policy-pack assignment only) and
    `EnterpriseJurisdiction`'s org<->jurisdiction relationship.

    Deliberately has NO tax_version_id column: an org's applicable tax
    version(s) are resolved dynamically at read time by
    (jurisdiction_id, tax_code, effective_date) via
    hierarchy/service.py::resolve_applicable_compliance_configuration,
    never pinned by a static FK. Pinning one pack row per org was the
    root cause of the old tax/policy assignment-tracking conflation bug
    (CompanyComplianceDetails.active_pack_id being a single FK shared by
    both pack types) — not repeating that mistake here is the point.
    """
    __tablename__ = "payroll_hierarchy_org_jurisdiction_assignments"

    id              = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    jurisdiction_id = Column(Integer, ForeignKey("payroll_hierarchy_jurisdictions.id"), nullable=False, index=True)

    assignment_type = Column(String(20), nullable=False, default="primary")  # "primary" | "secondary"
    status          = Column(String(20), nullable=False, default="draft")    # draft|configured|verified|active|inactive

    effective_from = Column(Date, nullable=False, server_default=func.current_date())
    effective_to   = Column(Date, nullable=True)
    tax_regime     = Column(String(20), nullable=True)  # org-level default regime for this jurisdiction

    general_config    = Column(JSON, nullable=True)  # absorbs EnterpriseJurisdiction's JSON config blobs 1:1
    compliance_config = Column(JSON, nullable=True)
    payroll_rules_config = Column(JSON, nullable=True)

    configured_at = Column(DateTime(timezone=True), nullable=True)
    verified_at   = Column(DateTime(timezone=True), nullable=True)

    # Migration-traceability bridges only.
    legacy_compliance_details_id     = Column(Integer, ForeignKey("payroll_company_compliance.id"), nullable=True)
    legacy_enterprise_jurisdiction_id = Column(Integer, ForeignKey("payroll_enterprise_jurisdictions.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("organization_id", "jurisdiction_id", name="uq_hierarchy_org_jurisdiction"),
        Index(
            "uq_hierarchy_org_primary_jurisdiction", "organization_id",
            unique=True, postgresql_where=text("assignment_type = 'primary'"),
        ),
    )


class OrganizationTaxOverride(Base):
    """An explicit, auditable org-specific override on a rule's rate or a
    named parameter — replaces the old unprotected clobber path
    (`apply_extracted_rate` writing straight into an org's own
    ContributionRate row with nothing distinguishing "canonical-synced"
    from "org-overridden," so a later canonical sync could silently
    overwrite a value an Org Admin had just deliberately set)."""
    __tablename__ = "payroll_hierarchy_org_tax_overrides"

    id              = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    tax_version_id  = Column(Integer, ForeignKey("payroll_hierarchy_tax_versions.id"), nullable=False, index=True)

    # Exactly one of these is set — see ck_org_tax_override_target below.
    tax_rule_id      = Column(Integer, ForeignKey("payroll_hierarchy_tax_rules.id"), nullable=True)
    tax_parameter_id = Column(Integer, ForeignKey("payroll_hierarchy_tax_parameters.id"), nullable=True)

    override_employee_rate_pct    = Column(Numeric(7, 4), nullable=True)
    override_employer_rate_pct    = Column(Numeric(7, 4), nullable=True)
    override_employee_flat_amount = Column(Numeric(12, 2), nullable=True)
    override_employer_flat_amount = Column(Numeric(12, 2), nullable=True)
    override_value_numeric        = Column(Numeric(14, 2), nullable=True)

    reason = Column(Text, nullable=False)  # mandatory — unlike the old silent-clobber path
    status = Column(String(20), nullable=False, default="pending_approval")  # pending_approval|approved|rejected|expired|withdrawn

    requested_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_by_id  = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at     = Column(DateTime(timezone=True), nullable=True)

    effective_from = Column(Date, nullable=True)
    effective_to   = Column(Date, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "(tax_rule_id IS NOT NULL AND tax_parameter_id IS NULL) "
            "OR (tax_rule_id IS NULL AND tax_parameter_id IS NOT NULL)",
            name="ck_org_tax_override_target",
        ),
        Index("ix_hierarchy_org_tax_override_lookup", "organization_id", "tax_version_id", "status"),
    )


class TaxVersionAudit(Base):
    """Audit trail for every mutation in this submodule. The OLD
    `TaxConfigurationAudit` (app/modules/payroll/models.py) stays alive,
    unchanged, auditing only the frozen legacy tables — the two tables
    coexist permanently, they are never merged, since the legacy table's
    rows must remain exactly as they were for any historical review."""
    __tablename__ = "payroll_hierarchy_tax_version_audit"

    id        = Column(Integer, primary_key=True, index=True)
    actor_id  = Column(Integer, ForeignKey("users.id"), nullable=True)

    # create|update|status_change|delete|override_request|override_approve|override_reject
    action      = Column(String(30), nullable=False)
    entity_type = Column(String(30), nullable=False)  # tax|tax_version|tax_rule|tax_rate|tax_slab|tax_parameter|jurisdiction|jurisdiction_assignment|tax_override
    entity_id   = Column(Integer, nullable=False)

    tax_version_id  = Column(Integer, ForeignKey("payroll_hierarchy_tax_versions.id"), nullable=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)  # set for override actions

    old_value = Column(JSON, nullable=True)
    new_value = Column(JSON, nullable=True)
    reason    = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_hierarchy_audit_entity", "entity_type", "entity_id"),
        Index("ix_hierarchy_audit_tax_version", "tax_version_id"),
    )
