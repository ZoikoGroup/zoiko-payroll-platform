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

from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, Text, ForeignKey
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
