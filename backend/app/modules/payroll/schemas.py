"""
modules/payroll/schemas.py
--------------------------
Pydantic schemas for the Zoiko Payroll module.

Response schemas use explicit `validation_alias` / `serialization_alias`
pairs so the JSON returned to the frontend matches the exact field names
already consumed by payrollService.js and the React components
(RunsTable, RunDetailPage, PayslipsPage, ContributionRatesTable,
TaxSlabTable, StatCards, CostTrendChart, RecentActivity, CompliancePage)
with zero client-side mapping.

IMPORTANT: every route that returns one of these models must pass
`response_model_by_alias=True` on the route decorator (see router.py) so
FastAPI serializes using the camelCase aliases instead of the snake_case
Python field names.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional, List, Annotated, ClassVar
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, BeforeValidator, model_validator
from app.modules.payroll.models import PayrollStatus, PayslipStatus, ActivityStatus


def coerce_str(v):
    if v is None:
        return None
    return str(v)


CoercedStr = Annotated[Optional[str], BeforeValidator(coerce_str)]


def coerce_decimal(v):
    # Spreadsheet cells and cleared form fields arrive as "" (not null/absent)
    # — Decimal's validator rejects "" outright, so normalize it to None first.
    if v == "":
        return None
    return v


CoercedDecimal = Annotated[Optional[Decimal], BeforeValidator(coerce_decimal)]


# ── Employees ────────────────────────────────────────────────────────
# Backed by payroll's own PayrollEmployee model (models.py) — fully
# decoupled from app.modules.employee.Employee (the separate HR/auth
# login record). Full CRUD is appropriate here since this is payroll's
# own master data, org-scoped for multi-tenancy.

class EmployeeCreate(BaseModel):
    employee_code:    Optional[str] = None
    name:             Optional[str] = Field(None, validation_alias="name")
    email:            Optional[str] = None
    phone:            Optional[str] = None
    department:       Optional[str] = None
    designation:      Optional[str] = None
    employment_type:  str = Field("Full-time", validation_alias="employmentType")
    status:           str = "Active"
    date_of_joining:  Optional[date] = Field(None, validation_alias="dateOfJoining")
    ctc:              Optional[Decimal] = Decimal("0")
    basic:            CoercedDecimal = Field(None, validation_alias="basic")
    hra:              CoercedDecimal = Field(None, validation_alias="hra")
    bank_name:        Optional[str] = Field(None, validation_alias="bankName")
    bank_account:     Optional[str] = Field(None, validation_alias="bankAccountNumber")
    pan:              Optional[str] = Field(None, validation_alias="panNumber")
    uan:              Optional[str] = None
    ifsc:             Optional[str] = Field(None, validation_alias="ifscCode")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class EmployeeUpdate(BaseModel):
    employee_code:    Optional[str] = None
    name:             Optional[str] = Field(None, validation_alias="name")
    email:            Optional[str] = None
    phone:            Optional[str] = None
    department:       Optional[str] = None
    designation:      Optional[str] = None
    employment_type:  Optional[str] = Field(None, validation_alias="employmentType")
    status:           Optional[str] = None
    date_of_joining:  Optional[date] = Field(None, validation_alias="dateOfJoining")
    ctc:              Optional[Decimal] = None
    basic:            CoercedDecimal = Field(None, validation_alias="basic")
    hra:              CoercedDecimal = Field(None, validation_alias="hra")
    bank_name:        Optional[str] = Field(None, validation_alias="bankName")
    bank_account:     Optional[str] = Field(None, validation_alias="bankAccountNumber")
    pan:              Optional[str] = Field(None, validation_alias="panNumber")
    uan:              Optional[str] = None
    ifsc:             Optional[str] = Field(None, validation_alias="ifscCode")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class EmployeeResponse(BaseModel):
    id:              int
    employeeCode:    str = Field(validation_alias="employee_code", serialization_alias="employeeCode")
    legacyCode:      Optional[str] = Field(None, validation_alias="legacy_code", serialization_alias="legacyCode")
    name:            str = Field(validation_alias="name", serialization_alias="name")
    email:           Optional[str] = None
    phone:           Optional[str] = None
    department:      Optional[str] = None
    designation:     Optional[str] = None
    employmentType:  str = Field(validation_alias="employment_type", serialization_alias="employmentType")
    status:          str
    dateOfJoining:   Optional[date] = Field(None, validation_alias="date_of_joining", serialization_alias="dateOfJoining")
    ctc:             Optional[Decimal] = Decimal("0")
    basic:           Optional[Decimal] = Field(None, validation_alias="basic", serialization_alias="basic")
    hra:             Optional[Decimal] = Field(None, validation_alias="hra", serialization_alias="hra")
    bankName:        Optional[str] = Field(None, validation_alias="bank_name", serialization_alias="bankName")
    # Serialized as bankAccountNumber/panNumber to match the field names
    # EmployeeCreate/EmployeeUpdate/BulkEmployeeItem already expect on write —
    # this response previously used shorter names ("bankAccount"/"pan"),
    # so the Edit form (which reads bankAccountNumber/panNumber, matching
    # what it also sends on save) always saw them as blank on load.
    bankAccount:     Optional[str] = Field(None, validation_alias="bank_account", serialization_alias="bankAccountNumber")
    pan:             Optional[str] = Field(None, serialization_alias="panNumber")
    uan:             Optional[str] = None
    ifsc:            Optional[str] = Field(None, serialization_alias="ifscCode")
    customFields:    Optional[dict] = Field(None, validation_alias="custom_fields", serialization_alias="customFields")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class BulkEmployeeItem(BaseModel):
    id:                Optional[int] = None  # present only for bulk-update rows; ignored by bulk-create
    name:              Optional[str] = None
    email:             Optional[str] = None
    phone:             CoercedStr = None
    department:        Optional[str] = None
    designation:       Optional[str] = None
    employmentType:    Optional[str] = None
    status:            Optional[str] = None
    dateOfJoining:     CoercedStr = None
    ctc:               Optional[Decimal] = None
    basic:             CoercedDecimal = None
    hra:               CoercedDecimal = None
    bankName:          Optional[str] = None
    bankAccountNumber: CoercedStr = None
    panNumber:         CoercedStr = None
    uan:               CoercedStr = None
    ifscCode:          CoercedStr = None


class BulkEmployeeRequest(BaseModel):
    employees: List[BulkEmployeeItem]


class BulkDeleteRequest(BaseModel):
    employee_ids: List[int]


class BulkUpsertResponse(BaseModel):
    # The router builds a dict with all four of these keys (see
    # bulk_create_employees in router.py), but this schema previously
    # declared only `message` — FastAPI's response_model strips any key not
    # declared on the model, so `created`/`employees`/`failed` were silently
    # dropped from the actual HTTP response. The frontend's "add the new
    # rows to the list instantly" callback never fired as a result — new
    # employees only appeared after a later refetch (e.g. a page reload).
    message:   str
    created:   int = 0
    employees: List[EmployeeResponse] = []
    failed:    List[dict] = []
    created: int
    employees: List[EmployeeResponse]
    failed: List[dict] = []

    model_config = ConfigDict(populate_by_name=True)


class BulkUpdateResponse(BaseModel):
    message: str
    updated: int
    employees: List[EmployeeResponse]
    failed: List[dict] = []

    model_config = ConfigDict(populate_by_name=True)


# ── Payroll Runs ───────────────────────────────────────────────────────

class PayrollRunCreate(BaseModel):
    period_label: Optional[str] = Field(None, alias="periodLabel", description='Display label, e.g. "Jul 1-15, 2026". Auto-generated from dates if omitted.')
    period_start: date = Field(..., alias="periodStart")
    period_end:   date = Field(..., alias="periodEnd")
    pay_date:     date = Field(..., alias="payDate")
    notes:        Optional[str] = None
    schedule:     Optional[str] = None
    employeeIds:  Optional[List[int]] = None
    totals:       Optional[dict] = None
    calculation_mode: Optional[str] = Field(None, alias="calculationMode",
        description="simple|standard|enterprise — stored on the run for auditing. If omitted, resolved from active policy.")
    # If true (default), payslip items are generated for every Active
    # employee in the org as soon as the run is created.
    auto_generate_payslips: bool = True

    model_config = ConfigDict(populate_by_name=True)

    @model_validator(mode="after")
    def _auto_label(self) -> "PayrollRunCreate":
        if not self.period_label and self.period_start and self.period_end:
            from calendar import month_name
            s, e = self.period_start, self.period_end
            if s.month == e.month:
                self.period_label = f"{month_name[s.month][:3]} {s.day}-{e.day}, {s.year}"
            else:
                self.period_label = f"{month_name[s.month][:3]} {s.day} - {month_name[e.month][:3]} {e.day}, {s.year}"
        return self


class PayrollRunUpdate(BaseModel):
    period_label: Optional[str] = None
    period_start: Optional[date] = None
    period_end:   Optional[date] = None
    pay_date:     Optional[date] = None
    notes:        Optional[str] = None


class PayrollRunPreviewRequest(BaseModel):
    employee_ids: List[int] = Field(..., alias="employeeIds", description="Employee IDs to include in preview")
    country: str = Field(default="IN", description="Jurisdiction country code (IN/US/UK)")
    period_start: Optional[date] = Field(None, alias="periodStart",
        description="Optional — if provided, real attendance-recorded rewards/bonus/other compensation for this window are included in the preview.")
    period_end: Optional[date] = Field(None, alias="periodEnd")
    calculation_mode: Optional[str] = Field(None, alias="calculationMode",
        description="simple|standard|enterprise — if omitted, resolved from the org's active policy.")
    model_config = ConfigDict(populate_by_name=True)


class PayrollRunPreviewEmployee(BaseModel):
    employeeId: int
    employeeName: str
    department: Optional[str] = None
    attendanceStatus: str = "active"
    monthlyGross: float
    monthlyTax: float
    monthlyPf: float
    monthlyEsi: float
    monthlyPt: float
    monthlySocialSecurity: float = 0.0
    monthlyMedicare: float = 0.0
    monthlyNi: float = 0.0
    monthlyContributions: float
    monthlyNet: float
    employerPf: float = 0.0
    employerEsi: float = 0.0
    employerSs: float = 0.0
    employerMedicare: float = 0.0
    employerPension: float = 0.0
    taxSlabRate: str = "—"
    payableDays: Optional[float] = None
    totalWorkingDays: Optional[float] = None
    prorated: bool = False
    model_config = ConfigDict(populate_by_name=True)


class PayrollRunPreviewTotals(BaseModel):
    count: int
    totalGross: float
    totalTax: float
    totalContributions: float
    totalNet: float
    model_config = ConfigDict(populate_by_name=True)


class PayrollRunPreviewResponse(BaseModel):
    employees: List[PayrollRunPreviewEmployee]
    totals: PayrollRunPreviewTotals
    calculationMode: Optional[str] = Field(None, alias="calculationMode")
    model_config = ConfigDict(populate_by_name=True)


class PayrollRunResponse(BaseModel):
    id:                    int
    runCode:               Optional[str] = Field(None, validation_alias="run_code", serialization_alias="runCode")
    period:                str     = Field(validation_alias="period_label", serialization_alias="period")
    payDate:               date    = Field(validation_alias="pay_date", serialization_alias="payDate")
    status:                PayrollStatus
    employees:             int     = Field(validation_alias="employee_count", serialization_alias="employees")
    gross:                 Decimal = Field(Decimal("0"), validation_alias="total_gross", serialization_alias="gross")
    deductions:            Decimal = Field(Decimal("0"), validation_alias="total_deductions", serialization_alias="deductions")
    taxes:                 Decimal = Field(Decimal("0"), validation_alias="total_taxes", serialization_alias="taxes")
    employerContribution:  Decimal = Field(Decimal("0"), validation_alias="total_employer_contribution", serialization_alias="employerContribution")
    net:                   Decimal = Field(Decimal("0"), validation_alias="total_net", serialization_alias="net")
    notes:                 Optional[str] = None
    calculationMode:       Optional[str] = Field(None, validation_alias="calculation_mode", serialization_alias="calculationMode")
    createdAt:             datetime = Field(validation_alias="created_at", serialization_alias="createdAt")
    createdBy:             Optional[str] = Field(None, validation_alias="created_by_name", serialization_alias="createdBy")
    approvedBy:            Optional[str] = Field(None, validation_alias="approved_by_name", serialization_alias="approvedBy")
    approvedAt:            Optional[datetime] = Field(None, validation_alias="approved_at", serialization_alias="approvedAt")
    authorizedBy:          Optional[str] = Field(None, validation_alias="authorized_by_name", serialization_alias="authorizedBy")
    authorizedAt:          Optional[datetime] = Field(None, validation_alias="authorized_at", serialization_alias="authorizedAt")
    paidBy:                Optional[str] = Field(None, validation_alias="paid_by_name", serialization_alias="paidBy")
    processedAt:           Optional[datetime] = Field(None, validation_alias="processed_at", serialization_alias="processedAt")
    approvalStatus:        str = ""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @model_validator(mode="after")
    def _set_approval_status(self):
        approved_states = {
            PayrollStatus.APPROVED, PayrollStatus.AUTHORIZED, PayrollStatus.PAID, PayrollStatus.CLOSED,
        }
        self.approvalStatus = "Approved" if self.status in approved_states else "Pending"
        return self


# ── Payslip Items ──────────────────────────────────────────────────────

class PayslipItemCreate(BaseModel):
    """Manually add/override a single employee's payslip within a run.
    (Runs created with auto_generate_payslips=True won't normally need this —
    it exists for corrections, off-cycle additions, or contractors.)
    """
    employee_id:    int
    basic_salary:   Decimal
    hra:            Optional[Decimal] = Decimal("0")
    special_allowance: Optional[Decimal] = Decimal("0")
    overtime:       Optional[Decimal] = Decimal("0")
    notes:          Optional[str] = None


class PayslipItemResponse(BaseModel):
    id:                 int
    payslipNumber:      Optional[str] = Field(None, validation_alias="payslip_number", serialization_alias="payslipNumber")
    employee:           str
    employeeId:         int
    department:         Optional[str] = None
    designation:        Optional[str] = None
    dateOfJoining:      Optional[date] = None
    country:            Optional[str] = None
    period:             str
    payDate:            date
    salary:             Decimal
    basicPay:           Decimal
    hra:                Decimal
    specialAllowance:   Decimal
    overtime:           Decimal
    additionalCompensation: Decimal = Decimal("0")
    payableDays:        Optional[Decimal] = None
    totalWorkingDays:   Optional[Decimal] = None
    unpaidLeaveDays:    Optional[int] = None
    attendanceDeduction: Optional[Decimal] = None
    tds:                Decimal
    pf:                 Decimal
    esi:                Decimal
    professionalTax:    Decimal
    socialSecurity:     Decimal = Decimal("0")
    medicare:           Decimal = Decimal("0")
    niEmployee:         Decimal = Decimal("0")
    totalDeductions:    Decimal = Decimal("0")
    employerPf:         Decimal = Decimal("0")
    employerEsi:        Decimal = Decimal("0")
    employerSs:         Decimal = Decimal("0")
    employerMedicare:   Decimal = Decimal("0")
    employerPension:    Decimal = Decimal("0")
    netPay:             Decimal
    bankName:           Optional[str] = None
    bankAccount:        Optional[str] = None
    pan:                Optional[str] = None
    uan:                Optional[str] = None
    ifsc:               Optional[str] = None
    status:             PayslipStatus
    notes:              Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


# ── Company Holidays ─────────────────────────────────────────────────────

class HolidayCreate(BaseModel):
    date: date
    name: Optional[str] = None


class BulkHolidayRequest(BaseModel):
    holidays: List[HolidayCreate]


class HolidayResponse(BaseModel):
    id:       int
    date:     date
    name:     Optional[str] = None
    country:  Optional[str] = None
    category: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ── Leave Allocations ─────────────────────────────────────────────────

class LeaveAllocationCreate(BaseModel):
    employeeId:         int = Field(validation_alias="employeeId")
    leaveBalances:      Optional[dict] = Field(default=None, validation_alias="leaveBalances")
    periodLabel:        Optional[str] = Field(None, validation_alias="periodLabel")
    notes:              Optional[str] = Field(None, validation_alias="notes")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class BulkLeaveRequest(BaseModel):
    records: List[LeaveAllocationCreate]


class LeaveAllocationResponse(BaseModel):
    id:                 int
    employeeId:         int     = Field(validation_alias="employee_id", serialization_alias="employeeId")
    leaveBalances:      Optional[dict] = Field(default=None, validation_alias="leave_balances", serialization_alias="leaveBalances")
    periodLabel:        Optional[str] = Field(None, validation_alias="period_label", serialization_alias="periodLabel")
    notes:              Optional[str] = Field(None, validation_alias="notes", serialization_alias="notes")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Leave Requests ────────────────────────────────────────────────────

class PayrollLeaveRequestCreate(BaseModel):
    employeeId:         int = Field(validation_alias="employeeId")
    leaveType:          str = Field(validation_alias="leaveType")
    startDate:          date = Field(validation_alias="startDate")
    endDate:            date = Field(validation_alias="endDate")
    reason:             Optional[str] = None

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class PayrollLeaveRequestUpdate(BaseModel):
    status:             Optional[str] = None   # approved / rejected
    reason:             Optional[str] = None

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class PayrollLeaveRequestResponse(BaseModel):
    id:                 int
    requestCode:        Optional[str] = Field(None, validation_alias="request_code", serialization_alias="requestCode")
    employeeId:         int     = Field(validation_alias="employee_id", serialization_alias="employeeId")
    employeeName:       Optional[str] = Field(None, serialization_alias="employeeName")
    department:         Optional[str] = None
    leaveType:          str     = Field(validation_alias="leave_type", serialization_alias="leaveType")
    startDate:          date    = Field(validation_alias="start_date", serialization_alias="startDate")
    endDate:            date    = Field(validation_alias="end_date", serialization_alias="endDate")
    days:               int
    reason:             Optional[str] = None
    status:             str
    reviewedBy:         Optional[int] = Field(None, validation_alias="reviewed_by", serialization_alias="reviewedBy")
    reviewedAt:         Optional[datetime] = Field(None, validation_alias="reviewed_at", serialization_alias="reviewedAt")
    createdAt:          Optional[datetime] = Field(None, validation_alias="created_at", serialization_alias="createdAt")
    updatedAt:          Optional[datetime] = Field(None, validation_alias="updated_at", serialization_alias="updatedAt")
    linkedAttendanceDates: Optional[List[date]] = Field(None, serialization_alias="linkedAttendanceDates")
    isAutoCreated:      Optional[bool] = Field(False, serialization_alias="isAutoCreated")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Attendance & Compensation ──────────────────────────────────────────
# Backed by PayrollAttendanceRecord (models.py). Frontend sends/receives
# camelCase JSON that maps to snake_case DB columns.

class AttendanceRecordCreate(BaseModel):
    employeeId:         Optional[int] = Field(None, validation_alias="employeeId")
    date:               date
    checkIn:            Optional[str] = Field(None, validation_alias="checkIn")
    checkOut:           Optional[str] = Field(None, validation_alias="checkOut")
    checkInPeriod:      Optional[str] = Field("AM", validation_alias="checkInPeriod")
    checkOutPeriod:     Optional[str] = Field("PM", validation_alias="checkOutPeriod")
    breakMinutes:       Optional[int] = Field(60, validation_alias="breakMinutes")
    status:             str = "present"
    leaveType:          Optional[str] = Field(None, validation_alias="leaveType")
    isHalfDay:          Optional[bool] = Field(False, validation_alias="isHalfDay")
    hours:              Optional[str] = None
    rewards:            Optional[Decimal] = Decimal("0")
    bonus:              Optional[Decimal] = Decimal("0")
    otherCompensation:  Optional[Decimal] = Field(Decimal("0"), validation_alias="otherCompensation")
    notes:              Optional[str] = None
    name:               Optional[str] = None
    department:         Optional[str] = None

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class BulkAttendanceRequest(BaseModel):
    records: List[AttendanceRecordCreate]


class AttendanceRecordResponse(BaseModel):
    id:                 int
    employeeId:         int     = Field(validation_alias="employee_id", serialization_alias="employeeId")
    name:               Optional[str] = None
    department:         Optional[str] = None
    designation:        Optional[str] = None
    date:               date
    checkIn:            Optional[str] = Field(None, validation_alias="check_in", serialization_alias="checkIn")
    checkOut:           Optional[str] = Field(None, validation_alias="check_out", serialization_alias="checkOut")
    status:             str
    leaveType:          Optional[str] = Field(None, validation_alias="leave_type", serialization_alias="leaveType")
    isHalfDay:          bool = Field(False, validation_alias="is_half_day", serialization_alias="isHalfDay")
    leaveRequestId:     Optional[int] = Field(None, validation_alias="leave_request_id", serialization_alias="leaveRequestId")
    hours:              Optional[str] = None
    rewards:            Decimal = Decimal("0")
    bonus:              Decimal = Decimal("0")
    otherCompensation:  Decimal = Field(Decimal("0"), validation_alias="other_compensation", serialization_alias="otherCompensation")
    notes:              Optional[str] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SkippedRecordDetail(BaseModel):
    rowName:            Optional[str] = Field(None, serialization_alias="rowName")
    rowId:              Optional[int] = Field(None, serialization_alias="rowId")
    reason:             str = ""
    skip_date:          Optional[date] = Field(None, alias="date")

    model_config = ConfigDict(populate_by_name=True)


class BulkAttendanceResponse(BaseModel):
    saved:              int = 0
    skipped:            int = 0
    skippedDetails:     List[SkippedRecordDetail] = Field(default_factory=list, serialization_alias="skippedDetails")
    records:            List[AttendanceRecordResponse] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)


class AttendanceSummaryResponse(BaseModel):
    total:   int
    present: int
    absent:  int
    leave:   int

    model_config = ConfigDict(populate_by_name=True)

# ── Compliance ─────────────────────────────────────────────────────────

class CompanyDetails(BaseModel):
    name:                 str = ""
    type:                 str = ""
    taxNo:                str = Field("", validation_alias="tax_no", serialization_alias="taxNo")
    employerId:           str = Field("", validation_alias="employer_id", serialization_alias="employerId")
    address:              str = ""
    industry:             str = ""
    email:                str = ""
    phone:                str = ""
    jurisdictionCountry:  str = Field("", validation_alias="jurisdiction_country", serialization_alias="jurisdictionCountry")
    jurisdictionState:    str = Field("", validation_alias="jurisdiction_state", serialization_alias="jurisdictionState")
    compliancePack:       str = Field("", validation_alias="compliance_pack", serialization_alias="compliancePack")
    schedule:             str = ""
    settlementBank:       str = Field("", validation_alias="settlement_bank", serialization_alias="settlementBank")
    settlementAcc:        str = Field("", validation_alias="settlement_acc", serialization_alias="settlementAcc")
    # Jurisdiction-aware tax/registration IDs synced from registration (see
    # app/core/jurisdiction.py) and editable/overridable from the Compliance
    # Details tab. Optional dict so legacy rows without it still serialize.
    taxIdentifiers:       Optional[dict] = Field(None, validation_alias="tax_identifiers", serialization_alias="taxIdentifiers")
    configuredAt:         Optional[datetime] = Field(None, validation_alias="configured_at", serialization_alias="configuredAt")
    isConfigured:         bool = Field(False, validation_alias="is_configured", serialization_alias="isConfigured")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class CompanyDetailsUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    taxNo: Optional[str] = None
    employerId: Optional[str] = None
    address: Optional[str] = None
    industry: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    jurisdictionCountry: Optional[str] = None
    jurisdictionState: Optional[str] = None
    compliancePack: Optional[str] = None
    schedule: Optional[str] = None
    settlementBank: Optional[str] = None
    settlementAcc: Optional[str] = None
    taxIdentifiers: Optional[dict] = None


class ComplianceDataResponse(BaseModel):
    """Shape expected by CompliancePage.jsx: { company, filings }."""
    company: CompanyDetails
    filings: List[dict] = []


class ContributionRateResponse(BaseModel):
    id:       int
    label:    str
    employee: str = Field(validation_alias="employee_share", serialization_alias="employee")
    employer: str = Field(validation_alias="employer_share", serialization_alias="employer")
    total:    str

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class TaxSlabResponse(BaseModel):
    id:   int
    min:  str = ""
    max:  str = ""
    rate: str = Field(validation_alias="rate_label", serialization_alias="rate")
    tax:  str = Field(validation_alias="tax_formula", serialization_alias="tax")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    # Duplicated from service.py's _get_currency_symbol rather than imported,
    # to avoid a schemas.py <-> service.py circular import for a 6-entry map.
    # Must be ClassVar — a bare class attribute here gets wrapped by Pydantic
    # v2 as a ModelPrivateAttr descriptor (no .get()), which silently turned
    # every /compliance/tax-slabs response into a 500 until this was caught.
    _CURRENCY_SYMBOLS: ClassVar[dict] = {"IN": "₹", "US": "$", "UK": "£", "AU": "A$", "DE": "€", "CA": "C$"}

    @model_validator(mode="before")
    @classmethod
    def _extract_and_format_bounds(cls, values):
        """Read min_amount/max_amount from the model and format as display
        strings using the row's own jurisdiction_country — was hardcoded to
        ₹/Indian digit-grouping regardless of which country the slab actually
        belongs to."""
        if not isinstance(values, dict):
            values = dict(getattr(values, "__dict__", {}))
        raw_min = values.get("min_amount")
        raw_max = values.get("max_amount")
        country = (values.get("jurisdiction_country") or "IN").upper()
        symbol = cls._CURRENCY_SYMBOLS.get(country, "$")

        def _fmt(val):
            if val is None:
                return "Above"
            d = Decimal(str(val))
            if d == Decimal("0"):
                return f"{symbol}0"
            sign = "-" if d < 0 else ""
            d = abs(d)
            s = f"{d:,.0f}"
            if country == "IN":
                # Indian numbering: group last 3, then groups of 2
                parts = s.split(",")
                if len(parts) > 2:
                    # Convert Western grouping (3,3,3) to Indian (3,2,2)
                    last3 = parts[-1]
                    rest = parts[:-1]
                    groups = []
                    while rest:
                        groups.insert(0, rest.pop())
                    if groups:
                        first = groups[0]
                        rest = groups[1:]
                        formatted = first
                        for g in rest:
                            formatted += "," + g
                        formatted += "," + last3
                    else:
                        formatted = last3
                else:
                    formatted = ",".join(parts)
            else:
                formatted = s
            return f"{symbol}{sign}{formatted}"

        if raw_min is not None:
            values["min"] = _fmt(raw_min) if isinstance(raw_min, (int, float, str)) else _fmt(raw_min)
        if raw_max is not None:
            values["max"] = _fmt(raw_max) if isinstance(raw_max, (int, float, str)) else _fmt(raw_max)
        else:
            values["max"] = "Above"
        return values


# ── Compliance: Apply Extracted Rate ────────────────────────────────────
# Backs the "Apply" button added to ComplianceDocuments.jsx's extracted-rate
# preview. `row` intentionally accepts whatever shape the frontend already
# renders (label/employee/employer/total for rates; min/max/rate/tax for
# slabs) rather than a stricter schema, since it's echoing back exactly
# what ComplianceDocumentUpload displayed to the user before they clicked
# Apply — see service.apply_extracted_rate for how each kind is mapped
# onto ContributionRate / TaxSlab.

class ApplyExtractedRateRequest(BaseModel):
    documentId: str
    kind: str  # "contributionRate" | "taxSlab"
    row: dict
    countryCode: str = "IN"


class ApplyExtractedRateResponse(BaseModel):
    applied: bool
    componentKey: Optional[str] = None
    message: str = ""


# ── Compliance: Jurisdiction Pack ────────────────────────────────────────

class JurisdictionPackResponse(BaseModel):
    id:                  int
    packId:              str = Field(validation_alias="pack_id", serialization_alias="packId")
    jurisdictionCountry: str = Field(validation_alias="jurisdiction_country", serialization_alias="jurisdictionCountry")
    jurisdictionState:   Optional[str] = Field(None, validation_alias="jurisdiction_state", serialization_alias="jurisdictionState")
    version:             str
    status:              str
    effectiveFrom:       Optional[date] = Field(None, validation_alias="effective_from", serialization_alias="effectiveFrom")
    effectiveTo:         Optional[date] = Field(None, validation_alias="effective_to", serialization_alias="effectiveTo")
    complianceOwner:     str = Field("", validation_alias="compliance_owner", serialization_alias="complianceOwner")
    engineeringOwner:    str = Field("", validation_alias="engineering_owner", serialization_alias="engineeringOwner")
    sourceReferences:    str = Field("", validation_alias="source_references", serialization_alias="sourceReferences")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class JurisdictionPackUpsert(BaseModel):
    packId: str
    jurisdictionCountry: str
    jurisdictionState: Optional[str] = None
    version: str = "1.0"
    status: str = "Draft"
    effectiveFrom: Optional[date] = None
    effectiveTo: Optional[date] = None
    complianceOwner: str = ""
    engineeringOwner: str = ""
    sourceReferences: str = ""


# ── Dashboard ──────────────────────────────────────────────────────────

class DashboardSummaryResponse(BaseModel):
    totalPayrollCost:            Decimal
    totalPayrollCostChangePct:   Optional[float] = None
    totalGross:                  Optional[Decimal] = None
    totalTaxes:                  Optional[Decimal] = None
    totalAttendanceDeduction:    Optional[Decimal] = None
    totalNet:                    Optional[Decimal] = None
    headcount:                   int
    activeCount:                 Optional[int] = None
    onLeaveCount:                Optional[int] = None
    pendingApprovals:            int

    model_config = ConfigDict(populate_by_name=True)


class DashboardTrendPoint(BaseModel):
    month: str
    gross: Optional[Decimal] = None
    net:   Optional[Decimal] = None
    cost:  Optional[Decimal] = None


class RecentActivityItem(BaseModel):
    id:          str
    description: str
    timestamp:   datetime
    status:      ActivityStatus


class SuccessResponse(BaseModel):
    message: str


# ── Compliance: Documents ─────────────────────────────────────────────

class ExtractedContributionRate(BaseModel):
    id:       Optional[str] = None
    label:    str
    employee: str
    employer: str
    total:    str


class ExtractedTaxSlab(BaseModel):
    id:  Optional[str] = None
    min: str
    max: str
    rate: str
    tax:  str


class ExtractedRequirement(BaseModel):
    label: str
    note:  Optional[str] = None


class ExtractedRegisteredEntityDetails(BaseModel):
    # Common
    name:    Optional[str] = None
    address: Optional[str] = None

    # UK
    registrationNumber:    Optional[str] = None
    vatNumber:             Optional[str] = None
    payeReference:         Optional[str] = None
    utr:                   Optional[str] = None
    accountsReferenceDate: Optional[str] = None

    # India
    pan:     Optional[str] = None
    tan:     Optional[str] = None
    gst:     Optional[str] = None
    pfCode:  Optional[str] = None
    esiCode: Optional[str] = None

    # US
    ein:       Optional[str] = None
    stateId:   Optional[str] = None
    naicsCode: Optional[str] = None


class ExtractedComplianceData(BaseModel):
    contributionRates:      List[ExtractedContributionRate] = []
    taxSlabs:               List[ExtractedTaxSlab] = []
    requirements:           List[ExtractedRequirement] = []
    registeredEntityDetails: Optional[ExtractedRegisteredEntityDetails] = None


class ComplianceDocumentResponse(BaseModel):
    """Shape consumed by payrollService.js / ComplianceDocuments.jsx.
    Field names below are the exact contract documented in
    payrollService.js's uploadComplianceDocument() comment block —
    `response_model_by_alias=True` on the route serializes these as
    camelCase for the frontend while the Python side stays snake_case."""
    id:            int
    fileName:      str = Field(validation_alias="file_name", serialization_alias="fileName")
    title:         Optional[str] = None
    documentType:  Optional[str] = Field(None, validation_alias="document_type", serialization_alias="documentType")
    category:      str = "other"
    description:   Optional[str] = None
    fileSize:      Optional[int] = Field(None, validation_alias="file_size", serialization_alias="fileSize")
    mimeType:      Optional[str] = Field(None, validation_alias="mime_type", serialization_alias="mimeType")
    uploadedBy:    Optional[int] = Field(None, validation_alias="uploaded_by", serialization_alias="uploadedBy")
    uploadedAt:    datetime = Field(validation_alias="uploaded_at", serialization_alias="uploadedAt")
    country:       Optional[str] = None
    status:        str  # "processing" | "parsed" | "failed"
    extracted:     Optional[ExtractedComplianceData] = Field(None, validation_alias="extracted_data", serialization_alias="extracted")
    error:         Optional[str] = Field(None, validation_alias="error_message", serialization_alias="error")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)