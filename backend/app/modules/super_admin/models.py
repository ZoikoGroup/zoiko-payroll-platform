"""
modules/super_admin/models.py
-----------------------------
Platform-level configuration for the standalone Payroll Platform.

Deliberately minimal: the old platform's super_admin module held
PlatformProduct / OrganizationProduct / AuditLog / LoginActivity tables
that the Payroll module never imports. The standalone platform keeps only
PlatformSetting (key/value config, e.g. SMTP override) plus platform-wide
aggregate queries in the router.
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, Numeric, String, Text, text

from app.database import Base


class PlatformSetting(Base):
    __tablename__ = "platform_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, index=True, nullable=False)
    value = Column(Text, nullable=True)
    description = Column(String(500), nullable=True)
    is_public = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<PlatformSetting key={self.key!r}>"


class GlobalStatutoryRate(Base):
    """DEPRECATED as of the Global Payroll Tax Engine refactor — superseded
    by the canonical (organization_id IS NULL) rows on
    payroll_contribution_rates/payroll_tax_slabs, linked to a
    JurisdictionPack (pack_type="tax") via jurisdiction_pack_id. That is
    now the single, versioned, effective-dated, audited source of truth
    Super Admin manages (see payroll/service.py's
    list_canonical_contribution_rates/list_canonical_tax_slabs and
    engine/tax_resolver.py).

    This table is kept (not dropped — Phase 26: never drop before
    migration/regression validation) for backward read compatibility with
    the existing Statutory Rates page during transition. Do not write new
    data here; use the canonical rows instead. A follow-up should migrate
    the Statutory Rates UI onto the canonical rows and then drop this table.

    Original docstring, for context: platform-wide defaults for statutory
    components (PF/ESI/PT, Social Security, Medicare, National Insurance,
    …) keyed by jurisdiction country — organizations started from these on
    first Compliance setup. The Payroll engine never read this table
    directly; it read org-scoped ContributionRate/TaxSlab rows only.
    """

    __tablename__ = "platform_statutory_rates"

    id               = Column(Integer, primary_key=True, index=True)
    jurisdiction_country = Column(String(10), nullable=False, server_default="IN", default="IN")
    # null = country-level default, same "null means country-level"
    # convention JurisdictionPack.jurisdiction_state already uses.
    jurisdiction_state = Column(String(100), nullable=True)

    component_key    = Column(String(20), nullable=False)   # "pf" | "esi" | "pt" | "tds" | ...
    label            = Column(String(100), nullable=False)
    employee_share   = Column(String(50), nullable=False, default="")
    employer_share   = Column(String(50), nullable=False, default="")
    total            = Column(String(50), nullable=False, default="")

    employee_rate_pct = Column(Numeric(6, 4), nullable=True)  # e.g. 0.1200 for 12%
    employer_rate_pct = Column(Numeric(6, 4), nullable=True)
    flat_amount       = Column(Numeric(10, 2), nullable=True)  # for flat components like PT

    sort_order       = Column(Integer, default=0)
    is_active        = Column(Boolean, default=True, nullable=False)

    created_at       = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at       = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Two partial unique indexes instead of one plain UniqueConstraint,
    # because Postgres treats every NULL as distinct — a plain 3-column
    # constraint including the nullable jurisdiction_state would silently
    # allow duplicate country-level (state=NULL) rows for the same
    # component. Splitting by "state IS NULL" vs "state IS NOT NULL"
    # keeps both "one default per country" and "one default per
    # country+state" uniquely enforced.
    __table_args__ = (
        Index(
            "uq_global_rate_country_component_no_state",
            "jurisdiction_country", "component_key",
            unique=True, postgresql_where=text("jurisdiction_state IS NULL"),
        ),
        Index(
            "uq_global_rate_country_state_component",
            "jurisdiction_country", "jurisdiction_state", "component_key",
            unique=True, postgresql_where=text("jurisdiction_state IS NOT NULL"),
        ),
    )

    def __repr__(self):
        return f"<GlobalStatutoryRate country={self.jurisdiction_country} component={self.component_key}>"
