"""
modules/employee/schemas.py
---------------------------
Thin schemas for the employee self-service router. Payroll document shapes
are reused from app.modules.payroll.schemas so the frontend ESS pages get
the exact same contract as the admin payroll pages.
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.modules.payroll.schemas import PayslipItemResponse


class MyProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_code: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    department: Optional[str] = None
    designation: Optional[str] = None
    employment_type: Optional[str] = None
    status: Optional[str] = None
    work_state: Optional[str] = None
    date_of_joining: Optional[date] = None
    ctc: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account: Optional[str] = None
    pan: Optional[str] = None


class MyPayslipsResponse(BaseModel):
    payslips: list[PayslipItemResponse]
    total: int
