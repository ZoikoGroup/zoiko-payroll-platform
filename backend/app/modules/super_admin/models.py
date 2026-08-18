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

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

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

# GlobalStatutoryRate (table: platform_statutory_rates) was removed here —
# superseded by the canonical (organization_id IS NULL) rows on
# payroll_contribution_rates/payroll_tax_slabs, linked to a JurisdictionPack
# via jurisdiction_pack_id (see payroll/service.py's
# list_canonical_contribution_rates/list_canonical_tax_slabs and
# engine/tax_resolver.py). The Statutory Rates page now reads that canonical
# data directly (get_active_tax_configuration_for_display). The
# platform_statutory_rates table itself is left in place in the database,
# unused, pending a separate future migration to drop it.
