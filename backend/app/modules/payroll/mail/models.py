"""
modules/payroll/mail/models.py
--------------------------------
SQLAlchemy ORM models for Payroll email (SMTP send identity + IMAP inbound
leave-request capture).

This is an ADDITIVE submodule (mirrors app/modules/payroll/policy/ and
app/modules/payroll/enterprise/) — it does not modify any existing table.

Design notes (see the architecture report this was built from):
  - PayrollEmailSettings does NOT store third-party SMTP/IMAP passwords by
    default. The safe, low-risk v1 is a per-org "From" identity (address +
    display name) sent through the ALREADY-WORKING shared platform SMTP
    connection (app/services/email_service.py) — this fixes "employees see
    the wrong sender" without introducing new credential-storage risk.
    The optional custom_smtp_*/custom_imap_* columns exist so a tenant can
    later supply their own real mailbox credentials if/when they have one,
    but nothing populates them automatically and no code path requires them.
  - InboundMessage/InboundAttachment mirror the existing ComplianceDocument
    file-metadata shape (file_path/file_name/file_size/mime_type) rather
    than inventing a new storage convention.
"""

import enum
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey, UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class InboundMessageStatus(str, enum.Enum):
    UNMATCHED = "unmatched"   # sender didn't match any known employee — needs human review
    MATCHED   = "matched"     # sender matched an employee, not yet actioned
    CONVERTED = "converted"   # turned into a real PayrollLeaveRequest
    IGNORED   = "ignored"     # reviewed and dismissed (not a leave request)


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

    # NOTE: the IMAP inbound mailbox columns (imap_enabled, imap_host,
    # imap_port, imap_username, imap_password, imap_use_ssl, last_polled_at)
    # were intentionally dropped from this table by migration
    # f4a5b6c7d8e9_remove_payroll_imap_mail_receiver.py ("no real data was
    # lost... zero organizations had imap_enabled=true"). This model class
    # was never updated to match, so every `db.query(PayrollEmailSettings)`
    # — including is_notification_enabled(), on the payroll run-approval
    # path — was selecting columns the table no longer has and 500ing.
    # imap_configured always reads False now; the IMAP mailbox feature
    # (InboundMessage/InboundAttachment below, the /mail router endpoints,
    # and the frontend Leave Inbox tab) needs a separate decision — either
    # finish removing it end-to-end, or restore these columns/tables.
    imap_configured = False

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<PayrollEmailSettings org={self.organization_id}>"


class InboundMessage(Base):
    """One row per email fetched from an org's leave-request mailbox."""
    __tablename__ = "payroll_inbound_messages"

    id              = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    message_uid = Column(String(100), nullable=False)   # IMAP UID — dedup key so re-polling never reprocesses
    from_email  = Column(String(255), nullable=False)
    to_email    = Column(String(255), nullable=True)
    subject     = Column(String(500), nullable=True)
    body_text   = Column(Text, nullable=True)
    body_html   = Column(Text, nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=True)

    status = Column(String(20), default=InboundMessageStatus.UNMATCHED.value, nullable=False)
    matched_employee_id = Column(Integer, ForeignKey("payroll_employees.id"), nullable=True)
    leave_request_id    = Column(Integer, ForeignKey("payroll_leave_requests.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    employee    = relationship("PayrollEmployee", foreign_keys=[matched_employee_id], viewonly=True)
    attachments = relationship("InboundAttachment", cascade="all, delete-orphan", backref="message")

    __table_args__ = (
        UniqueConstraint("organization_id", "message_uid", name="uq_org_message_uid"),
        Index("ix_inbound_messages_org_status", "organization_id", "status"),
    )

    def __repr__(self):
        return f"<InboundMessage org={self.organization_id} from={self.from_email} status={self.status}>"


class InboundAttachment(Base):
    """Mirrors ComplianceDocument's file-metadata shape exactly — same
    local-disk storage convention, not a new one."""
    __tablename__ = "payroll_inbound_attachments"

    id         = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("payroll_inbound_messages.id"), nullable=False, index=True)

    file_path  = Column(String(500), nullable=False)
    file_name  = Column(String(255), nullable=False)
    file_size  = Column(Integer, nullable=True)
    mime_type  = Column(String(100), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
