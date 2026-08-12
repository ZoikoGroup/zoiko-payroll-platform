"""
modules/payroll/mail/models.py
--------------------------------
SQLAlchemy ORM models for Payroll email (SMTP send identity only).

This is an ADDITIVE submodule (mirrors app/modules/payroll/policy/ and
app/modules/payroll/enterprise/) — it does not modify any existing table.

Design notes:
  - PayrollEmailSettings does NOT store third-party SMTP passwords by
    default. The safe, low-risk v1 is a per-org "From" identity (address +
    display name) sent through the ALREADY-WORKING shared platform SMTP
    connection (app/services/email_service.py) — this fixes "employees see
    the wrong sender" without introducing new credential-storage risk.
    The optional custom_smtp_* columns exist so a tenant can later supply
    their own real mailbox credentials if/when they have one, but nothing
    populates them automatically and no code path requires them.
"""

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


class PayrollEmailSettings(Base):
    """One row per organization. Get-or-created lazily the same way
    PayrollPolicy/CompanyComplianceDetails already are — absence of a row
    means "use the shared platform default," never an error."""
    __tablename__ = "payroll_email_settings"

    id              = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, unique=True, index=True)

    # ── Outbound (SMTP) identity override ──
    # Sent through the existing shared platform SMTP connection — this is a
    # "From" header override, not a separate mail server. Leave both null to
    # keep using the platform default (Info@zoikoone.com) unchanged.
    from_email          = Column(String(255), nullable=True)
    from_display_name   = Column(String(150), nullable=True)
    notify_payslip_ready = Column(Boolean, default=True, nullable=False)
    notify_run_approved  = Column(Boolean, default=True, nullable=False)

    # ── Optional: tenant's own SMTP server, if they have one. Nullable —
    # nothing in this codebase populates these; they exist only so a real
    # value can be entered later without a schema change. ──
    use_custom_smtp = Column(Boolean, default=False, nullable=False)
    custom_smtp_host     = Column(String(255), nullable=True)
    custom_smtp_port     = Column(String(10), nullable=True)
    custom_smtp_username = Column(String(255), nullable=True)
    custom_smtp_password = Column(Text, nullable=True)   # plaintext today, same as PlatformSetting — see report's security note

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<PayrollEmailSettings org={self.organization_id}>"
