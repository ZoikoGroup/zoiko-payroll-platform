"""
modules/payroll/enterprise/models.py
-------------------------------------
SQLAlchemy ORM models for Enterprise Policy jurisdiction onboarding.

This is an ADDITIVE submodule (mirrors app/modules/payroll/policy/) — it
does not modify any existing payroll table. One EnterpriseJurisdiction row
is created per organization per country the org configures for Enterprise
Payroll.

The "General"/"Compliance"/"Payroll Rules" config sections (which have no
existing typed table) are stored as JSON so a future jurisdiction/config
category can be added without a schema migration. The "Tax" and
"Employer/Employee Contributions" sections deliberately do NOT duplicate
storage here — they read/write the existing ContributionRate/TaxSlab
tables (app/modules/payroll/models.py), which the calculation engine
already consumes (see engine/standard.py _calc_australia/_calc_germany/
_calc_canada) and which are already scoped by (organization_id,
jurisdiction_country) with a dedicated Compliance UI.
"""

import enum
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, JSON, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class JurisdictionStatus(str, enum.Enum):
    DRAFT      = "draft"
    CONFIGURED = "configured"
    VERIFIED   = "verified"


class EnterpriseJurisdiction(Base):
    """One row per organization per jurisdiction (country) enabled under
    Enterprise Payroll. Tenant-isolated via organization_id, exactly like
    every other payroll table (see service.py _apply_org_filter)."""
    __tablename__ = "payroll_enterprise_jurisdictions"

    id              = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    country_code = Column(String(2), nullable=False)   # AU | UK | US | DE | CA
    status       = Column(String(20), default=JurisdictionStatus.DRAFT.value, nullable=False)

    # Config categories with no existing typed table — see module docstring
    # for why Tax/Contributions are NOT duplicated here.
    general_config       = Column(JSON, nullable=True)   # { payrollFrequency, timeZone }
    compliance_config     = Column(JSON, nullable=True)   # { governmentFilingSchedule, requiredReports, payrollRegistrationNumbers, taxIdentificationNumbers }
    payroll_rules_config  = Column(JSON, nullable=True)   # { overtime, leave, holidayCalendar, terminationRules }

    configured_at = Column(DateTime(timezone=True), nullable=True)
    verified_at   = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("organization_id", "country_code", name="uq_org_jurisdiction_country"),
        Index("ix_enterprise_jurisdictions_org_status", "organization_id", "status"),
    )

    def __repr__(self):
        return f"<EnterpriseJurisdiction org={self.organization_id} country={self.country_code} status={self.status}>"
