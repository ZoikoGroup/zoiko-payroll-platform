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
    """Global statutory contribution-rate defaults, managed by Super Admin.

    These are the platform-wide defaults for statutory components (PF/ESI/PT,
    Social Security, Medicare, National Insurance, …) keyed by jurisdiction
    country. Organizations start from these defaults on first Compliance
    setup; an org's own ContributionRate rows (payroll_contribution_rates,
    org-scoped) can then diverge. The Payroll engine only reads the
    org-scoped tables — this table is the Super Admin's "global rate table"
    management surface, not the runtime calc source.
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
