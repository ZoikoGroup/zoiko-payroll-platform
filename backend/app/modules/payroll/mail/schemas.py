"""
modules/payroll/mail/schemas.py
----------------------------------
Pydantic schemas for Payroll email settings + inbound leave-request mail.

Credential fields (imap_password, custom_smtp_password) are write-only:
accepted on PayrollEmailSettingsUpdate so an org admin can set/rotate them,
encrypted at rest (see app/core/crypto.py + service.py), and NEVER echoed
back by PayrollEmailSettingsResponse — the response only exposes a boolean
"is a password currently set" flag (imapConfigured), never the value.
"""

from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field, EmailStr


class PayrollEmailSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    from_email: Optional[str] = Field(None, alias="fromEmail")
    from_display_name: Optional[str] = Field(None, alias="fromDisplayName")
    notify_payslip_ready: bool = Field(True, alias="notifyPayslipReady")
    notify_run_approved: bool = Field(True, alias="notifyRunApproved")
    use_custom_smtp: bool = Field(False, alias="useCustomSmtp")
    imap_enabled: bool = Field(False, alias="imapEnabled")
    imap_host: Optional[str] = Field(None, alias="imapHost")
    imap_port: Optional[str] = Field(None, alias="imapPort")
    imap_username: Optional[str] = Field(None, alias="imapUsername")
    imap_use_ssl: bool = Field(True, alias="imapUseSsl")
    imap_configured: bool = Field(False, alias="imapConfigured")
    last_polled_at: Optional[datetime] = Field(None, alias="lastPolledAt")


class PayrollEmailSettingsUpdate(BaseModel):
    """Identity + notification toggles + IMAP mailbox config. imap_password
    is write-only: send it to set/rotate the password, omit it to leave the
    currently-stored password untouched, send an empty string to clear it."""
    model_config = ConfigDict(populate_by_name=True)

    from_email: Optional[EmailStr] = Field(None, alias="fromEmail")
    from_display_name: Optional[str] = Field(None, alias="fromDisplayName")
    notify_payslip_ready: Optional[bool] = Field(None, alias="notifyPayslipReady")
    notify_run_approved: Optional[bool] = Field(None, alias="notifyRunApproved")

    imap_enabled: Optional[bool] = Field(None, alias="imapEnabled")
    imap_host: Optional[str] = Field(None, alias="imapHost")
    imap_port: Optional[str] = Field(None, alias="imapPort")
    imap_username: Optional[str] = Field(None, alias="imapUsername")
    imap_password: Optional[str] = Field(None, alias="imapPassword")
    imap_use_ssl: Optional[bool] = Field(None, alias="imapUseSsl")


class InboundAttachmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: int
    file_name: str = Field(..., alias="fileName")
    file_size: Optional[int] = Field(None, alias="fileSize")
    mime_type: Optional[str] = Field(None, alias="mimeType")


class InboundMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    from_email: str = Field(..., alias="fromEmail")
    subject: Optional[str] = None
    body_text: Optional[str] = Field(None, alias="bodyText")
    received_at: Optional[datetime] = Field(None, alias="receivedAt")
    status: str
    matched_employee_id: Optional[int] = Field(None, alias="matchedEmployeeId")
    matched_employee_name: Optional[str] = Field(None, alias="matchedEmployeeName")
    leave_request_id: Optional[int] = Field(None, alias="leaveRequestId")
    attachments: List[InboundAttachmentResponse] = Field(default_factory=list)


class ConvertToLeaveRequestRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    leave_type: str = Field(..., alias="leaveType")
    start_date: date = Field(..., alias="startDate")
    end_date: date = Field(..., alias="endDate")
    reason: Optional[str] = None


class SuccessResponse(BaseModel):
    success: bool = True
    message: Optional[str] = None
