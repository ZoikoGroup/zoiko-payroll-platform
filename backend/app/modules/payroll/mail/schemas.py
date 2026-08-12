"""
modules/payroll/mail/schemas.py
----------------------------------
Pydantic schemas for Payroll email settings (SMTP send identity +
notification toggles).
"""

from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, EmailStr


class PayrollEmailSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    from_email: Optional[str] = Field(None, alias="fromEmail")
    from_display_name: Optional[str] = Field(None, alias="fromDisplayName")
    notify_payslip_ready: bool = Field(True, alias="notifyPayslipReady")
    notify_run_approved: bool = Field(True, alias="notifyRunApproved")
    use_custom_smtp: bool = Field(False, alias="useCustomSmtp")


class PayrollEmailSettingsUpdate(BaseModel):
    """Identity + notification toggles."""
    model_config = ConfigDict(populate_by_name=True)

    from_email: Optional[EmailStr] = Field(None, alias="fromEmail")
    from_display_name: Optional[str] = Field(None, alias="fromDisplayName")
    notify_payslip_ready: Optional[bool] = Field(None, alias="notifyPayslipReady")
    notify_run_approved: Optional[bool] = Field(None, alias="notifyRunApproved")
