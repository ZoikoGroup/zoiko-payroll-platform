"""
modules/payroll/router.py
-------------------------
HTTP endpoints for the Zoiko Payroll module.

Paths below are relative to this router's prefix ("/payroll"). The frontend
(payrollService.js) calls them under "/api/payroll/...", so make sure your
app mounts this router with an "/api" prefix at the top level, e.g.:

    app.include_router(payroll_router, prefix="/api")

  Employees (payroll's own — see models.py: PayrollEmployee)
    GET    /payroll/employees                     → List employees (search/department/status)
    GET    /payroll/employees/{id}                → Get single employee
    POST   /payroll/employees                     → Create employee
    PUT    /payroll/employees/{id}                → Update employee
    DELETE /payroll/employees/{id}                 → Delete employee (blocked if payslip history exists)

  Payroll Runs
    POST   /payroll/runs                         → Create a run (auto-generates payslips)
    GET    /payroll/runs                         → List runs
    GET    /payroll/runs/{id}                    → Get single run
    PUT    /payroll/runs/{id}                    → Update run (Draft only)
    PUT    /payroll/runs/{id}/approve             → Advance run to next lifecycle status
    DELETE /payroll/runs/{id}                    → Delete a Draft run
    POST   /payroll/runs/{id}/items               → Manually add/override a payslip in a run
    GET    /payroll/runs/{id}/items               → List payslips for a run

  Payslips
    GET    /payroll/payslips                      → List payslips org-wide (search/period/employeeId)
    GET    /payroll/payslips/{id}                 → Get single payslip
    GET    /payroll/payslips/{id}/download         → Download payslip PDF
    DELETE /payroll/payslips/{id}                 → Delete a payslip (Draft runs only)

  Compliance
    GET    /payroll/filings                       → { company, filings }
    GET    /payroll/compliance/contribution-rates
    GET    /payroll/compliance/tax-slabs
    PUT    /payroll/compliance/company-details
    POST   /payroll/compliance/documents          → Upload a compliance document

  Dashboard
    GET    /payroll/dashboard/summary
    GET    /payroll/dashboard/trend
    GET    /payroll/dashboard/activity
"""

import os
import uuid
from datetime import date
from typing import Optional, List
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import io

from app.database import get_db
from app.core import object_storage
from app.core.dependencies import (
    get_current_user, get_current_payroll_operator, get_current_super_admin, get_organization_id,
    require_active_subscription,
)
from app.core.exceptions import ForbiddenException
from app.modules.payroll import service
from app.modules.payroll.policy import policy_router
from app.modules.payroll.enterprise import enterprise_router
from app.modules.payroll.mail import mail_router
from app.modules.payroll.forms import forms_router
from app.modules.payroll.schemas import (
    PayrollRunCreate, PayrollRunUpdate, PayrollRunResponse,
    PayrollRunPreviewRequest, PayrollRunPreviewResponse,
    PayslipItemCreate, PayslipItemResponse,
    CompanyDetailsUpdate, ComplianceDataResponse,
    ComplianceDocumentResponse,
    ContributionRateResponse, TaxSlabResponse,
    ApplyExtractedRateRequest, ApplyExtractedRateResponse,
    JurisdictionPackResponse, JurisdictionPackUpsert,
    DashboardSummaryResponse, DashboardTrendPoint, RecentActivityItem,
    SuccessResponse,
    EmployeeCreate, EmployeeUpdate, EmployeeResponse,
    BulkEmployeeRequest, BulkUpsertResponse, BulkUpdateResponse, BulkDeleteRequest,
    AttendanceRecordCreate, BulkAttendanceRequest, AttendanceRecordResponse,
    AttendanceSummaryResponse, BulkAttendanceResponse,
    LeaveAllocationCreate, BulkLeaveRequest, LeaveAllocationResponse,
    PayrollLeaveRequestCreate, PayrollLeaveRequestUpdate, PayrollLeaveRequestResponse,
    UKStatutoryPayRequest, UKStatutoryPayResponse,
    UKEmployerChargesSummaryResponse, UKEmploymentAllowanceRequest, UKEmploymentAllowanceResponse,
    UKClass1A1BRequest, UKClass1A1BResponse,
    UKNiReliefFactCreate, UKNiReliefFactResponse,
    UKMileageReimbursementRequest, UKMileageReimbursementResponse,
    UKAdvisoryFuelRateRequest, UKAdvisoryFuelRateResponse,
    UKNmwComplianceRequest, UKNmwComplianceResponse,
    UKCourtOrderCreate, UKCourtOrderStatusUpdate, UKCourtOrderResponse,
    UKCourtOrderCalculateRequest, UKCourtOrderCalculateResponse,
    GratuityCalculateRequest, GratuityCalculateResponse,
    IndiaForm138GenerateRequest, IndiaForm123GenerateRequest,
    SalaryTdsDeclarationCreate, SalaryTdsDeclarationResponse,
    SalaryTdsClaimCreate, SalaryTdsClaimResponse, SalaryTdsClaimRejectRequest,
    EmployeeBenefitValuationCreate, EmployeeBenefitValuationResponse,
    UKEmployeeReportGenerateRequest, UKEpsGenerateRequest,
    RtiSubmissionCreate, RtiSubmissionStatusUpdate, RtiSubmissionResponse,
    HolidayCreate, BulkHolidayRequest, HolidayResponse,
    ApplicableTemplateResponse, GenerateReportRequest, GeneratedReportResponse, VoidGeneratedReportRequest,
    FilingCalendarResponse,
)

payroll_router = APIRouter(
    prefix="/payroll",
    tags=["Payroll Module"],
    dependencies=[Depends(require_active_subscription("payroll"))],
)

payroll_router.include_router(policy_router)
payroll_router.include_router(enterprise_router)
payroll_router.include_router(mail_router)
payroll_router.include_router(forms_router)


# ── Employees ────────────────────────────────────────────────────────

@payroll_router.get(
    "/employees", response_model=List[EmployeeResponse], response_model_by_alias=True,
    summary="List employees",
)
def list_employees(
    search: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: Optional[int] = Query(None, ge=1, le=1000),
    offset: Optional[int] = Query(None, ge=0),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_employees(
        db, current_user.organization_id,
        search=search, department=department, status=status,
        limit=limit, offset=offset,
    )


@payroll_router.get(
    "/employees/{employee_id}", response_model=EmployeeResponse, response_model_by_alias=True,
    summary="Get a single employee",
)
def get_employee(
    employee_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_employee_by_id(db, employee_id, current_user.organization_id)


@payroll_router.post(
    "/employees", response_model=EmployeeResponse, response_model_by_alias=True,
    summary="Create an employee", dependencies=[Depends(get_current_payroll_operator)],
)
def create_employee(
    data: EmployeeCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.create_employee(db, data, current_user.organization_id)


@payroll_router.post(
    "/employees/bulk", response_model=BulkUpsertResponse,
    summary="Bulk create employees from imported data",
    dependencies=[Depends(get_current_payroll_operator)],
)
def bulk_create_employees(
    data: BulkEmployeeRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = service.bulk_create_employees(db, data, current_user.organization_id)
    return {
        "message": f"{result['created']} created, {len(result['failed'])} failed.",
        "created": result['created'],
        "employees": result['employees'],
        "failed": result['failed'],
    }


@payroll_router.post(
    "/employees/bulk-update", response_model=BulkUpdateResponse,
    summary="Bulk partial-update employees from imported data, keyed by employee ID",
    dependencies=[Depends(get_current_payroll_operator)],
)
def bulk_update_employees(
    data: BulkEmployeeRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = service.bulk_update_employees(db, data, current_user.organization_id)
    return {
        "message": f"{result['updated']} updated, {len(result['failed'])} failed.",
        "updated": result['updated'],
        "employees": result['employees'],
        "failed": result['failed'],
    }


@payroll_router.post(
    "/employees/bulk-delete",
    summary="Bulk delete employees",
    dependencies=[Depends(get_current_payroll_operator)],
)
def bulk_delete_employees(
    data: BulkDeleteRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = service.bulk_delete_employees(db, data, current_user.organization_id)
    return {
        "message": f"{len(result['deleted'])} deleted, {len(result['failed'])} failed.",
        **result,
    }


@payroll_router.put(
    "/employees/{employee_id}", response_model=EmployeeResponse, response_model_by_alias=True,
    summary="Update an employee", dependencies=[Depends(get_current_payroll_operator)],
)
def update_employee(
    employee_id: int,
    data: EmployeeUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.update_employee(db, employee_id, data, current_user.organization_id, actor_id=current_user.id)


@payroll_router.delete(
    "/employees/{employee_id}", response_model=SuccessResponse,
    summary="Delete an employee", dependencies=[Depends(get_current_payroll_operator)],
)
def delete_employee(
    employee_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service.delete_employee(db, employee_id, current_user.organization_id)
    return {"message": "Employee deleted."}


# ── Payroll Runs ─────────────────────────────────────────────────────

@payroll_router.post(
    "/runs", response_model=PayrollRunResponse, response_model_by_alias=True,
    summary="Create a payroll run", dependencies=[Depends(get_current_payroll_operator)],
)
def create_run(
    data: PayrollRunCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.create_payroll_run(db, current_user.id, data, current_user.organization_id)


@payroll_router.post(
    "/runs/preview", response_model=PayrollRunPreviewResponse, response_model_by_alias=True,
    summary="Dry-run payroll calculation (no DB writes)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def preview_run(
    data: PayrollRunPreviewRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.preview_payroll_run(
        db, current_user.organization_id, data.employee_ids, data.country,
        data.period_start, data.period_end, data.calculation_mode,
    )


@payroll_router.get(
    "/runs", response_model=List[PayrollRunResponse], response_model_by_alias=True,
    summary="List all payroll runs",
)
def list_runs(
    year: Optional[int] = Query(None, ge=2020, le=2099, description="Filter by pay year"),
    month: Optional[int] = Query(None, ge=1, le=12, description="Filter by pay month (1-12)"),
    limit: Optional[int] = Query(None, ge=1, le=1000),
    offset: Optional[int] = Query(None, ge=0),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_payroll_runs(db, current_user.organization_id, year=year, month=month, limit=limit, offset=offset)


@payroll_router.get(
    "/runs/{run_id}", response_model=PayrollRunResponse, response_model_by_alias=True,
    summary="Get a payroll run",
)
def get_run(
    run_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_payroll_run_detail(db, run_id, current_user.organization_id)


@payroll_router.put(
    "/runs/{run_id}", response_model=PayrollRunResponse, response_model_by_alias=True,
    summary="Update payroll run details (Draft only)", dependencies=[Depends(get_current_payroll_operator)],
)
def update_run(
    run_id: int,
    data: PayrollRunUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.update_payroll_run(db, run_id, data, current_user.organization_id)


@payroll_router.put(
    "/runs/{run_id}/approve", response_model=PayrollRunResponse, response_model_by_alias=True,
    summary="Advance a payroll run to its next lifecycle status",
    dependencies=[Depends(get_current_payroll_operator)],
)
def approve_run(
    run_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.advance_payroll_run_status(
        db, run_id, current_user.id, current_user.organization_id, background_tasks=background_tasks,
    )


@payroll_router.put(
    "/runs/{run_id}/employees/{employee_id}/recalculate", response_model=PayrollRunResponse, response_model_by_alias=True,
    summary="Recalculate one employee's payslip within a run (Draft/Review only)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def recalculate_employee_payslip(
    run_id: int,
    employee_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.regenerate_employee_payslip(db, run_id, employee_id, current_user.organization_id, actor_id=current_user.id)


@payroll_router.delete(
    "/runs/{run_id}", response_model=SuccessResponse,
    summary="Delete a Draft payroll run", dependencies=[Depends(get_current_payroll_operator)],
)
def delete_run(
    run_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service.delete_payroll_run(db, run_id, current_user.organization_id)
    return {"message": "Payroll run deleted."}


@payroll_router.post(
    "/runs/{run_id}/items", response_model=PayslipItemResponse, response_model_by_alias=True,
    summary="Manually add/override an employee payslip in a run",
    dependencies=[Depends(get_current_payroll_operator)],
)
def add_item(
    run_id: int,
    data: PayslipItemCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    item = service.add_payslip_item(db, run_id, data, current_user.organization_id)
    run = service.get_payroll_run_by_id(db, run_id, current_user.organization_id)
    country = service._resolve_org_country(db, current_user.organization_id)
    return service._serialize_payslip(item, run, country=country)


@payroll_router.post(
    "/uk/statutory-pay/calculate", response_model=UKStatutoryPayResponse, response_model_by_alias=True,
    summary="On-demand UK Statutory Sick Pay / Statutory Family Pay calculator (preview only, not a payslip mutation)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def calculate_uk_statutory_pay(
    data: UKStatutoryPayRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.calculate_uk_statutory_pay(
        db, current_user.organization_id, data.employee_id,
        data.payment_type, data.event_start_date, week_number=data.week_number,
        qualifying_days_in_period=data.qualifying_days_in_period,
        qualifying_days_per_week=data.qualifying_days_per_week,
        average_weekly_earnings=data.average_weekly_earnings,
        include_employer_recovery=data.include_employer_recovery,
        prior_year_total_class1_nic=data.prior_year_total_class1_nic,
    )


@payroll_router.get(
    "/uk/employer-charges/summary", response_model=UKEmployerChargesSummaryResponse, response_model_by_alias=True,
    summary="Current UK tax-year cumulative employer NI / Apprenticeship Levy pay bill for this org",
    dependencies=[Depends(get_current_payroll_operator)],
)
def get_uk_employer_charges_summary(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_uk_employer_charges_summary(db, current_user.organization_id)


@payroll_router.post(
    "/uk/employer-charges/employment-allowance", response_model=UKEmploymentAllowanceResponse, response_model_by_alias=True,
    summary="Calculate UK Employment Allowance net employer NIC liability (whole-tax-year, not a payslip mutation)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def calculate_uk_employment_allowance(
    data: UKEmploymentAllowanceRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.calculate_uk_employment_allowance(db, current_user.organization_id, data.employer_has_claimed)


@payroll_router.post(
    "/uk/employer-charges/class-1a-1b", response_model=UKClass1A1BResponse, response_model_by_alias=True,
    summary="Calculate a UK Class 1A/1B employer NIC charge for one event (benefits, termination award, testimonial, or PSA item)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def calculate_uk_class_1a_1b_charge(
    data: UKClass1A1BRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.calculate_uk_class_1a_1b_charge(db, current_user.organization_id, data.charge_type, data.amount)


@payroll_router.post(
    "/uk/employees/{employee_id}/ni-relief-facts", response_model=UKNiReliefFactResponse, response_model_by_alias=True,
    summary="Record a UK NI category relief-eligibility fact (Freeport/Investment Zone/veteran/apprentice) for an employee",
    dependencies=[Depends(get_current_payroll_operator)],
)
def create_uk_ni_relief_fact(
    employee_id: int,
    data: UKNiReliefFactCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.create_uk_ni_relief_fact(
        db, current_user.organization_id, employee_id,
        data.relief_type, data.reference, data.effective_from, data.effective_to,
        created_by_id=current_user.id,
    )


@payroll_router.get(
    "/uk/employees/{employee_id}/ni-relief-facts", response_model=list[UKNiReliefFactResponse], response_model_by_alias=True,
    summary="List an employee's UK NI category relief-eligibility facts",
    dependencies=[Depends(get_current_payroll_operator)],
)
def list_uk_ni_relief_facts(
    employee_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_uk_ni_relief_facts(db, current_user.organization_id, employee_id)


@payroll_router.delete(
    "/uk/employees/{employee_id}/ni-relief-facts/{fact_id}", response_model=SuccessResponse,
    summary="Delete a UK NI category relief-eligibility fact",
    dependencies=[Depends(get_current_payroll_operator)],
)
def delete_uk_ni_relief_fact(
    employee_id: int,
    fact_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service.delete_uk_ni_relief_fact(db, current_user.organization_id, employee_id, fact_id)
    return {"message": "NI relief fact deleted."}


@payroll_router.post(
    "/uk/mileage/calculate", response_model=UKMileageReimbursementResponse, response_model_by_alias=True,
    summary="Calculate the HMRC-approved tax-free/NI-free mileage reimbursement for a claim (preview only)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def calculate_uk_mileage_reimbursement(
    data: UKMileageReimbursementRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.calculate_uk_mileage_reimbursement(
        db, current_user.organization_id, data.employee_id,
        data.vehicle_type, data.business_miles, data.claim_date, data.ytd_business_miles_before,
    )


@payroll_router.post(
    "/uk/advisory-fuel-rate", response_model=UKAdvisoryFuelRateResponse, response_model_by_alias=True,
    summary="Resolve the company-car advisory fuel/electricity rate for a fuel type and engine band",
    dependencies=[Depends(get_current_payroll_operator)],
)
def resolve_uk_advisory_fuel_rate(
    data: UKAdvisoryFuelRateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.resolve_uk_advisory_fuel_rate(db, current_user.organization_id, data.fuel_type, data.engine_band, data.as_of)


@payroll_router.post(
    "/uk/nmw/validate", response_model=UKNmwComplianceResponse, response_model_by_alias=True,
    summary="Validate an employee's National Minimum Wage compliance for a pay reference period",
    dependencies=[Depends(get_current_payroll_operator)],
)
def validate_uk_nmw_compliance(
    data: UKNmwComplianceRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.validate_uk_nmw_compliance(
        db, current_user.organization_id, data.employee_id,
        data.period_start, data.period_end, data.nmw_countable_pay,
    )


@payroll_router.post(
    "/uk/employees/{employee_id}/court-orders", response_model=UKCourtOrderResponse, response_model_by_alias=True,
    summary="Record a UK court-ordered deduction (England & Wales AEO / Scottish arrestment / Northern Ireland order) for an employee",
    dependencies=[Depends(get_current_payroll_operator)],
)
def create_uk_court_ordered_deduction(
    employee_id: int,
    data: UKCourtOrderCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.create_court_ordered_deduction(
        db, current_user.organization_id, employee_id,
        data.jurisdiction, data.order_type, data.start_date,
        court_reference=data.court_reference, issue_date=data.issue_date, end_date=data.end_date,
        priority=data.priority,
        fixed_deduction_rate_pct=data.fixed_deduction_rate_pct, fixed_deduction_amount=data.fixed_deduction_amount,
        protected_earnings_amount=data.protected_earnings_amount, total_amount_to_collect=data.total_amount_to_collect,
        created_by_id=current_user.id,
    )


@payroll_router.get(
    "/uk/employees/{employee_id}/court-orders", response_model=list[UKCourtOrderResponse], response_model_by_alias=True,
    summary="List an employee's UK court-ordered deductions",
    dependencies=[Depends(get_current_payroll_operator)],
)
def list_uk_court_ordered_deductions(
    employee_id: int,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_court_ordered_deductions(db, current_user.organization_id, employee_id, status)


@payroll_router.put(
    "/uk/employees/{employee_id}/court-orders/{order_id}/status", response_model=UKCourtOrderResponse, response_model_by_alias=True,
    summary="Cancel/complete a UK court-ordered deduction (no hard delete — a legal instrument stays in the record)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def set_uk_court_ordered_deduction_status(
    employee_id: int,
    order_id: int,
    data: UKCourtOrderStatusUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.set_court_ordered_deduction_status(db, current_user.organization_id, employee_id, order_id, data.status)


@payroll_router.post(
    "/uk/court-orders/calculate", response_model=UKCourtOrderCalculateResponse, response_model_by_alias=True,
    summary="Calculate this period's court-ordered deductions for an employee (whole-tax-year-independent, per-period calculation)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def calculate_uk_court_ordered_deductions(
    data: UKCourtOrderCalculateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.calculate_uk_court_ordered_deductions(
        db, current_user.organization_id, data.employee_id,
        data.attachable_earnings, data.pay_frequency, data.as_of,
    )


@payroll_router.post(
    "/india/gratuity/calculate", response_model=GratuityCalculateResponse, response_model_by_alias=True,
    summary="Calculate an India employee's gratuity liability (termination/fixed-term benefit, not a payroll deduction)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def calculate_india_gratuity(
    data: GratuityCalculateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.calculate_india_employee_gratuity(
        db, current_user.organization_id, data.employee_id,
        eligibility_event=data.eligibility_event, is_fixed_term=data.is_fixed_term,
        date_of_leaving_override=data.date_of_leaving,
        last_drawn_monthly_wage_override=data.last_drawn_monthly_wage,
    )


# ── India: Form 122 (prior-employer salary/other-income declaration) ────

@payroll_router.post(
    "/india/salary-tds-declarations", response_model=SalaryTdsDeclarationResponse, response_model_by_alias=True,
    summary="Create a Form 122 salary TDS declaration (Draft)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def create_salary_tds_declaration(
    data: SalaryTdsDeclarationCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.create_salary_tds_declaration(
        db, current_user.organization_id, data.employee_id, data.tax_year,
        prior_employer_salary=data.prior_employer_salary, prior_employer_tds_deducted=data.prior_employer_tds_deducted,
        other_income=data.other_income, house_property_loss=data.house_property_loss,
    )


@payroll_router.get(
    "/india/salary-tds-declarations", response_model=List[SalaryTdsDeclarationResponse], response_model_by_alias=True,
    summary="List Form 122 salary TDS declarations",
)
def list_salary_tds_declarations(
    employeeId: Optional[int] = None, taxYear: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_salary_tds_declarations(db, current_user.organization_id, employee_id=employeeId, tax_year=taxYear)


@payroll_router.put(
    "/india/salary-tds-declarations/{declaration_id}/submit", response_model=SalaryTdsDeclarationResponse, response_model_by_alias=True,
    summary="Submit a Form 122 declaration (Draft -> Submitted)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def submit_salary_tds_declaration(
    declaration_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.submit_salary_tds_declaration(db, current_user.organization_id, declaration_id)


@payroll_router.put(
    "/india/salary-tds-declarations/{declaration_id}/approve", response_model=SalaryTdsDeclarationResponse, response_model_by_alias=True,
    summary="Approve a Form 122 declaration (Submitted -> Approved) — supersedes any prior Approved declaration for this employee+tax year",
    dependencies=[Depends(get_current_payroll_operator)],
)
def approve_salary_tds_declaration(
    declaration_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.approve_salary_tds_declaration(db, current_user.organization_id, declaration_id, current_user.id)


# ── India: Form 124 (Chapter VIII claims/evidence) ───────────────────────

@payroll_router.post(
    "/india/salary-tds-claims", response_model=SalaryTdsClaimResponse, response_model_by_alias=True,
    summary="Create a Form 124 salary TDS claim (Draft)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def create_salary_tds_claim(
    data: SalaryTdsClaimCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.create_salary_tds_claim(
        db, current_user.organization_id, data.employee_id, data.tax_year,
        data.claim_type, data.claimed_amount, evidence_reference=data.evidence_reference,
    )


@payroll_router.get(
    "/india/salary-tds-claims", response_model=List[SalaryTdsClaimResponse], response_model_by_alias=True,
    summary="List Form 124 salary TDS claims",
)
def list_salary_tds_claims(
    employeeId: Optional[int] = None, taxYear: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_salary_tds_claims(db, current_user.organization_id, employee_id=employeeId, tax_year=taxYear)


@payroll_router.put(
    "/india/salary-tds-claims/{claim_id}/submit", response_model=SalaryTdsClaimResponse, response_model_by_alias=True,
    summary="Submit a Form 124 claim (Draft -> Submitted)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def submit_salary_tds_claim(
    claim_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.submit_salary_tds_claim(db, current_user.organization_id, claim_id)


@payroll_router.put(
    "/india/salary-tds-claims/{claim_id}/approve", response_model=SalaryTdsClaimResponse, response_model_by_alias=True,
    summary="Approve a Form 124 claim (Submitted -> Approved)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def approve_salary_tds_claim(
    claim_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.approve_salary_tds_claim(db, current_user.organization_id, claim_id, current_user.id)


@payroll_router.put(
    "/india/salary-tds-claims/{claim_id}/reject", response_model=SalaryTdsClaimResponse, response_model_by_alias=True,
    summary="Reject a Form 124 claim (Submitted -> Rejected)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def reject_salary_tds_claim(
    claim_id: int,
    data: SalaryTdsClaimRejectRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.reject_salary_tds_claim(db, current_user.organization_id, claim_id, data.reason)


# ── India: Form 123 (employer-recorded perquisite/benefit valuation) ────

@payroll_router.post(
    "/india/employee-benefit-valuations", response_model=EmployeeBenefitValuationResponse, response_model_by_alias=True,
    summary="Create a Form 123 employee benefit valuation (Draft)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def create_employee_benefit_valuation(
    data: EmployeeBenefitValuationCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.create_employee_benefit_valuation(
        db, current_user.organization_id, data.employee_id, data.tax_year,
        data.benefit_type, data.taxable_value, description=data.description,
    )


@payroll_router.get(
    "/india/employee-benefit-valuations", response_model=List[EmployeeBenefitValuationResponse], response_model_by_alias=True,
    summary="List Form 123 employee benefit valuations",
)
def list_employee_benefit_valuations(
    employeeId: Optional[int] = None, taxYear: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_employee_benefit_valuations(db, current_user.organization_id, employee_id=employeeId, tax_year=taxYear)


@payroll_router.put(
    "/india/employee-benefit-valuations/{valuation_id}/issue", response_model=EmployeeBenefitValuationResponse, response_model_by_alias=True,
    summary="Issue a Form 123 benefit valuation (Draft -> Issued)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def issue_employee_benefit_valuation(
    valuation_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.issue_employee_benefit_valuation(db, current_user.organization_id, valuation_id)


@payroll_router.get(
    "/runs/{run_id}/items", response_model=List[PayslipItemResponse], response_model_by_alias=True,
    summary="List payslips in a run",
)
def list_items(
    run_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    run = service.get_payroll_run_by_id(db, run_id, current_user.organization_id)
    items = service.get_payslips_for_run(db, run_id, current_user.organization_id)
    country = service._resolve_org_country(db, current_user.organization_id)
    return [service._serialize_payslip(item, run, country=country) for item in items]


@payroll_router.get(
    "/runs/{run_id}/leave-summary",
    summary="Per-employee leave/attendance breakdown for a run's pay period (read-only)",
)
def get_run_leave_summary(
    run_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_run_leave_summary(db, run_id, current_user.organization_id)


@payroll_router.get(
    "/runs/{run_id}/bank-transfer-summary",
    summary="Payroll summary for the Approval Dialog (org admin only, read-only)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def get_bank_transfer_summary(
    run_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_bank_transfer_summary(db, run_id, current_user.organization_id)


@payroll_router.get(
    "/runs/{run_id}/bank-transfer-file",
    summary="Generate and download the bank transfer file for a run. Defaults to the org's "
            "Banking Policy format; pass ?format=csv|xlsx|txt|pdf to download a different format "
            "for this one download without changing that policy setting.",
    dependencies=[Depends(get_current_payroll_operator)],
)
def download_bank_transfer_file(
    run_id: int,
    format: Optional[str] = Query(None, description="csv | xlsx | txt | pdf — defaults to the Banking Policy format"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    file_bytes, content_type, _ext, filename = service.generate_bank_transfer_file(
        db, run_id, current_user.organization_id, actor_id=current_user.id, format_override=format,
    )
    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@payroll_router.get(
    "/runs/{run_id}/download",
    summary="Download all payslips in a run as a ZIP of PDFs",
)
def download_run_payslips(
    run_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    import zipfile
    run = service.get_payroll_run_by_id(db, run_id, current_user.organization_id)
    items = service.get_payslips_for_run(db, run_id, current_user.organization_id)

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in items:
            pdf_bytes = service.generate_payslip_pdf_bytes(db, item.id, current_user.organization_id)
            safe_name = (item.employee_name or f"employee_{item.employee_id}").replace(" ", "_")
            zf.writestr(f"payslip_{safe_name}_{item.id}.pdf", pdf_bytes)
    zip_buf.seek(0)

    label = (run.period_label or f"run_{run_id}").replace(" ", "_")
    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="payslips_{label}.zip"'},
    )


# ── Payslips (org-wide) ────────────────────────────────────────────────

@payroll_router.get(
    "/payslips", response_model=List[PayslipItemResponse], response_model_by_alias=True,
    summary="List payslips across all runs",
)
def list_payslips(
    search: Optional[str] = Query(None),
    period: Optional[str] = Query(None),
    employeeId: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_payslips(
        db, current_user.organization_id,
        search=search, period=period, employee_id=employeeId,
    )


@payroll_router.get(
    "/payslips/{payslip_id}", response_model=PayslipItemResponse, response_model_by_alias=True,
    summary="Get a single payslip",
)
def get_payslip(
    payslip_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    data, _item, _run = service.get_payslip_by_id(db, payslip_id, current_user.organization_id)
    return data


@payroll_router.get(
    "/payslips/{payslip_id}/download",
    summary="Download a payslip as a PDF",
)
def download_payslip(
    payslip_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    pdf_bytes = service.generate_payslip_pdf_bytes(db, payslip_id, current_user.organization_id)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="payslip-{payslip_id}.pdf"'},
    )


@payroll_router.delete(
    "/payslips/{payslip_id}",
    summary="Delete a payslip",
)
def delete_payslip(
    payslip_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service.delete_payslip(db, payslip_id, current_user.organization_id)
    return {"message": "Payslip deleted."}


# ── Leave Allocations ──────────────────────────────────────────────────

@payroll_router.get(
    "/leaves", response_model=List[LeaveAllocationResponse],
    response_model_by_alias=True,
    summary="List leave allocations",
)
def list_leaves(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_leave_allocations(db, current_user.organization_id)


@payroll_router.post(
    "/leaves/bulk", response_model=List[LeaveAllocationResponse],
    response_model_by_alias=True,
    summary="Bulk save leave allocations",
    dependencies=[Depends(get_current_payroll_operator)],
)
def bulk_save_leaves(
    data: BulkLeaveRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.bulk_save_leaves(db, data, current_user.organization_id)


@payroll_router.delete(
    "/leaves/reset", response_model=SuccessResponse,
    summary="Reset all leave allocations and clear leave attendance records",
    dependencies=[Depends(get_current_payroll_operator)],
)
def reset_leave_allocations(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = service.reset_leave_allocations(db, current_user.organization_id)
    return SuccessResponse(
        message=f"Leave allocations reset for {result['leavesReset']} employees; {result['attendanceCleared']} attendance record(s) cleared."
    )


# ── Leave Requests ───────────────────────────────────────────────────

@payroll_router.get(
    "/leave-requests", response_model=List[PayrollLeaveRequestResponse],
    response_model_by_alias=True,
    summary="List leave requests",
)
def list_leave_requests(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    employee_id: Optional[int] = Query(None),
    leave_status: Optional[str] = Query(None, alias="status"),
    leave_type: Optional[str] = Query(None),
):
    return service.get_payroll_leave_requests(
        db, current_user.organization_id,
        employee_id=employee_id,
        status=leave_status,
        leave_type=leave_type,
    )


@payroll_router.post(
    "/leave-requests", response_model=PayrollLeaveRequestResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a leave request",
)
def create_leave_request(
    data: PayrollLeaveRequestCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.create_payroll_leave_request(db, data, current_user.organization_id)


@payroll_router.put(
    "/leave-requests/{request_id}/review", response_model=PayrollLeaveRequestResponse,
    response_model_by_alias=True,
    summary="Approve or reject a leave request",
    dependencies=[Depends(get_current_payroll_operator)],
)
def review_leave_request(
    request_id: int,
    data: PayrollLeaveRequestUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.review_payroll_leave_request(db, request_id, data, current_user.organization_id, current_user.id)


# ── Company Holidays ─────────────────────────────────────────────────────
# Shared calendar — used by attendance tracking and meant to also back
# the Attendance/Leave pages, so there's one holiday list everyone agrees
# on instead of each page keeping its own.

@payroll_router.get(
    "/holidays", response_model=List[HolidayResponse], response_model_by_alias=True,
    summary="List company holidays",
)
def list_holidays(
    year: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_holidays(db, current_user.organization_id, year=year)


@payroll_router.post(
    "/holidays/bulk", response_model=List[HolidayResponse], response_model_by_alias=True,
    summary="Upsert company holidays (create or update by date)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def bulk_upsert_holidays(
    data: BulkHolidayRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.bulk_upsert_holidays(db, current_user.organization_id, data.holidays)


@payroll_router.delete(
    "/holidays/{holiday_id}", response_model=SuccessResponse,
    summary="Delete a company holiday",
    dependencies=[Depends(get_current_payroll_operator)],
)
def delete_holiday(
    holiday_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service.delete_holiday(db, current_user.organization_id, holiday_id)
    return SuccessResponse(message="Holiday deleted.")


# ── Attendance & Compensation ───────────────────────────────────────────

@payroll_router.post(
    "/attendance/bulk", response_model=BulkAttendanceResponse,
    response_model_by_alias=True,
    summary="Bulk save attendance & compensation records",
    dependencies=[Depends(get_current_payroll_operator)],
)
def bulk_save_attendance(
    data: BulkAttendanceRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.bulk_save_attendance(db, data, current_user.organization_id)


@payroll_router.get(
    "/attendance", response_model=List[AttendanceRecordResponse],
    response_model_by_alias=True,
    summary="List attendance records",
)
def list_attendance(
    startDate: Optional[date] = Query(None),
    endDate: Optional[date] = Query(None),
    employeeId: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_attendance_records(
        db, current_user.organization_id,
        start_date=startDate, end_date=endDate, employee_id=employeeId,
    )


@payroll_router.delete(
    "/attendance", response_model=SuccessResponse,
    summary="Delete all attendance records for the organization",
    dependencies=[Depends(get_current_payroll_operator)],
)
def clear_attendance(
    startDate: Optional[str] = Query(None, alias="startDate"),
    endDate: Optional[str] = Query(None, alias="endDate"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    count = service.clear_attendance_records(
        db, current_user.organization_id, start_date=startDate, end_date=endDate,
    )
    if startDate or endDate:
        return SuccessResponse(message=f"Deleted {count} attendance record(s) in the selected range.")
    return SuccessResponse(message=f"Deleted {count} attendance record(s).")


@payroll_router.get(
    "/attendance/summary", response_model=AttendanceSummaryResponse,
    response_model_by_alias=True,
    summary="Get today's attendance summary",
)
def attendance_summary(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_attendance_summary(db, current_user.organization_id)


# ── Compliance ─────────────────────────────────────────────────────────

@payroll_router.get(
    "/filings", response_model=ComplianceDataResponse, response_model_by_alias=True,
    summary="Get company compliance details + filings",
)
def get_filings(
    db: Session = Depends(get_db),
    organization_id: int = Depends(get_organization_id),
):
    return service.get_compliance_data(db, organization_id)


@payroll_router.get(
    "/compliance/contribution-rates", response_model=List[ContributionRateResponse], response_model_by_alias=True,
    summary="Get statutory contribution rates",
)
def get_contribution_rates(
    country: str = Query("IN", description="Jurisdiction country code (IN, US, UK, …)"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_contribution_rates(db, current_user.organization_id, country=country)


@payroll_router.get(
    "/compliance/tax-slabs", response_model=List[TaxSlabResponse], response_model_by_alias=True,
    summary="Get income tax slabs",
)
def get_tax_slabs(
    country: str = Query("IN", description="Jurisdiction country code (IN, US, UK, …)"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_tax_slabs(db, current_user.organization_id, country=country)


@payroll_router.post(
    "/compliance/apply-extracted-rate", response_model=ApplyExtractedRateResponse,
    summary="Promote a document-extracted rate/slab row into the org's active configuration",
    # KNOWN TRANSITIONAL GAP: this still lets an org Payroll Operator edit
    # ContributionRate/TaxSlab values that are government-mandated, not
    # organization-negotiable — the exact gap the Global Payroll Tax Engine
    # refactor's canonical (Super-Admin-owned) rows are meant to close.
    # Left org-writable for now because org rows are still the engine's
    # live read source and no canonical→org sync exists yet (see
    # sync_org_rates_from_canonical, Milestone 2); once that sync ships,
    # this endpoint's UI should become view-only for Org Admin (Milestone 6)
    # rather than being cut off here with no replacement flow.
    dependencies=[Depends(get_current_payroll_operator)],
)
def apply_extracted_rate(
    payload: ApplyExtractedRateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.apply_extracted_rate(
        db, current_user.organization_id, payload.kind, payload.row, payload.countryCode
    )


@payroll_router.get(
    "/compliance/jurisdiction-packs", response_model=List[JurisdictionPackResponse], response_model_by_alias=True,
    summary="List jurisdiction compliance packs for a country/state",
)
def list_jurisdiction_packs(
    country: str = Query(...),
    state: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_jurisdiction_packs(db, country, state)


@payroll_router.put(
    "/compliance/jurisdiction-packs", response_model=JurisdictionPackResponse, response_model_by_alias=True,
    summary="Create or update a jurisdiction compliance pack's identity/metadata (policy packs only — tax packs are Super Admin-only)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def upsert_jurisdiction_pack(
    payload: JurisdictionPackUpsert,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # Government-mandated tax packs must only ever be authored by Super
    # Admin (see super_admin/router.py's /compliance/policies, which is
    # already Super-Admin-gated and calls this same service function) —
    # this org-facing path stays open for "policy" packs only, matching
    # the existing convention that orgs configure operational policy but
    # never statutory tax values.
    if payload.packType == "tax" and (current_user.role or "").lower() != "super_admin":
        raise ForbiddenException("Tax packs are Super Admin-managed only. Use Super Admin Compliance to create or edit tax configuration.")
    return service.upsert_jurisdiction_pack(db, payload, actor_id=current_user.id)


@payroll_router.put(
    "/compliance/company-details", response_model=SuccessResponse,
    summary="Update company compliance details", dependencies=[Depends(get_current_payroll_operator)],
)
def update_company_details(
    data: CompanyDetailsUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service.update_company_details(db, current_user.organization_id, data)
    return {"message": "Company details saved."}


@payroll_router.get(
    "/compliance/documents", response_model=List[ComplianceDocumentResponse],
    response_model_by_alias=True, response_model_exclude_none=False,
    summary="List compliance documents",
)
def list_compliance_documents(
    country: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_compliance_documents(db, current_user.organization_id, country=country)


@payroll_router.delete(
    "/compliance/documents/{document_id}", response_model=SuccessResponse,
    summary="Delete a compliance document",
)
def delete_compliance_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service.delete_compliance_document(db, document_id, current_user.organization_id)
    return {"message": "Compliance document deleted."}


@payroll_router.post(
    "/compliance/documents", response_model=ComplianceDocumentResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a compliance document",
)
async def upload_compliance_document(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    file: UploadFile = File(..., description="The document file"),
    title: Optional[str] = Form(None, max_length=200),
    document_type: Optional[str] = Form(None, max_length=100),
    category: str = Form("other"),
    description: Optional[str] = Form(None),
    country: Optional[str] = Form(None, max_length=10),
):
    resolved_title = title or document_type or file.filename or "Untitled Document"
    contents = await file.read()
    ext = os.path.splitext(file.filename or "")[1] or ".bin"
    unique_name = f"{uuid.uuid4().hex}{ext}"
    # Persisted via the object-storage abstraction: Cloud Storage in prod
    # (gs:// ref stored on the row), local disk under UPLOAD_BASE_DIR in dev.
    file_path = object_storage.save_upload(
        subdir="payroll_compliance_documents",
        filename=unique_name,
        data=contents,
    )

    doc = service.upload_compliance_document(
        db=db,
        title=resolved_title,
        category=category,
        file_path=file_path,
        file_name=file.filename,
        file_size=len(contents),
        mime_type=file.content_type,
        organization_id=current_user.organization_id,
        country=country,
        description=description,
        document_type=document_type,
        uploaded_by=current_user.id,
    )
    return doc


# ── Reports ─────────────────────────────────────────────────────────────

@payroll_router.get(
    "/reports",
    summary="List payroll reports (derived from completed runs)",
)
def list_reports(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_payroll_reports(db, current_user.organization_id)


@payroll_router.get(
    "/reports/{report_id}/download",
    summary="Download a payroll report as PDF or CSV",
)
def download_report(
    report_id: int,
    format: str = Query("pdf", description="Output format: pdf or csv"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    from fastapi.responses import Response
    if format == "csv":
        csv_bytes = service.generate_report_csv_bytes(db, report_id, current_user.organization_id)
        return Response(
            content=csv_bytes,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="payroll-report-{report_id}.csv"'},
        )
    pdf_bytes = service.generate_report_pdf_bytes(db, report_id, current_user.organization_id)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="payroll-report-{report_id}.pdf"'},
    )


# ── Report Templates (Organization consumption of Super Admin-published
# templates — authoring lives under /super-admin/report-templates) ──────

@payroll_router.get(
    "/report-templates/available",
    summary="Distinct report types/names with a Published/Active template covering this org's jurisdiction+year",
)
def list_available_reports(
    reportingYear: str = Query(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_available_reports_for_org(db, current_user.organization_id, reportingYear)


@payroll_router.get(
    "/report-templates/applicable", response_model=ApplicableTemplateResponse, response_model_by_alias=True,
    summary="Resolve the applicable Published/Active template for a jurisdiction+year+report, plus generation validation for a run",
)
def get_applicable_report_template(
    reportingYear: str = Query(...),
    reportType: str = Query(...),
    payrollRunId: Optional[int] = Query(None, description="If provided, also returns generation validation for this run"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_applicable_report_template_for_org(
        db, current_user.organization_id, reportingYear, reportType, payroll_run_id=payrollRunId,
    )


@payroll_router.post(
    "/generated-reports", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate an actual report from a published template + a finalized payroll run",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_report(
    payload: GenerateReportRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_report_from_template(
        db, current_user.organization_id, payload.reportTemplateId, payload.payrollRunId,
        reporting_period=payload.reportingPeriod, actor_id=current_user.id,
    )


@payroll_router.get(
    "/generated-reports", response_model=List[GeneratedReportResponse], response_model_by_alias=True,
    summary="List this organization's generated reports",
)
def list_generated_reports(
    payrollRunId: Optional[int] = Query(None),
    reportType: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_generated_reports(
        db, current_user.organization_id, payroll_run_id=payrollRunId, report_type=reportType, status=status,
    )


@payroll_router.get(
    "/generated-reports/{generated_report_id}", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Get a single generated report",
)
def get_generated_report(
    generated_report_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_generated_report(db, current_user.organization_id, generated_report_id)


@payroll_router.get(
    "/generated-reports/{generated_report_id}/reconciliation",
    summary="The frozen rendering-consistency check computed at generation time (no recomputation on read)",
)
def get_generated_report_reconciliation(
    generated_report_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    report = service.get_generated_report(db, current_user.organization_id, generated_report_id)
    return report.reconciliation or {}


@payroll_router.post(
    "/generated-reports/{generated_report_id}/void", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Void a generated report (kept for history, never deleted)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def void_generated_report(
    generated_report_id: int,
    payload: VoidGeneratedReportRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.void_generated_report(db, current_user.organization_id, generated_report_id, payload.reason, actor_id=current_user.id)


@payroll_router.get(
    "/generated-reports/{generated_report_id}/certificate/{employee_id}",
    summary="Download a single-employee statutory certificate PDF (only for PER_EMPLOYEE-scoped templates)",
)
def download_report_certificate(
    generated_report_id: int,
    employee_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    pdf_bytes = service.generate_report_certificate_pdf_bytes(db, current_user.organization_id, generated_report_id, employee_id)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="certificate-{generated_report_id}-{employee_id}.pdf"'},
    )


@payroll_router.get(
    "/generated-reports/{generated_report_id}/certificates.zip",
    summary="Download every employee's certificate PDF for a PER_EMPLOYEE-scoped generated report as one ZIP",
)
def download_report_certificates_zip(
    generated_report_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    import zipfile

    report = service.get_generated_report(db, current_user.organization_id, generated_report_id)
    employees = report.rendered_data.get("employees", [])

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in employees:
            pdf_bytes = service.generate_report_certificate_pdf_bytes(
                db, current_user.organization_id, generated_report_id, entry["employeeId"],
            )
            safe_name = (entry.get("employeeName") or f"employee_{entry['employeeId']}").replace(" ", "_")
            zf.writestr(f"certificate_{safe_name}_{entry['employeeId']}.pdf", pdf_bytes)
    zip_buf.seek(0)

    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="certificates-{generated_report_id}.zip"'},
    )


# ── UK RTI: P45/P60 (per-employee) + EPS (per-period) generation, ────────
# RTI XML download, submission tracking (ZP-TAX-UK-2026-27-001 §18
# gap-closure Part 9, 2026-09-09).

@payroll_router.post(
    "/uk/reports/employee", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a per-employee UK RTI report (P45 or P60) — not tied to any PayrollRun",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_uk_employee_report(
    data: UKEmployeeReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_uk_employee_report(
        db, current_user.organization_id, data.report_template_id, data.employee_id,
        data.as_of_date, actor_id=current_user.id,
    )


@payroll_router.post(
    "/uk/reports/eps", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate an Employer Payment Summary (EPS) for a period — employer-level only, no PayrollRun required",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_uk_eps(
    data: UKEpsGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_uk_eps(
        db, current_user.organization_id, data.report_template_id, data.tax_year, data.period_key,
        employer_has_claimed_allowance=data.employer_has_claimed_allowance,
        no_employees_paid=data.no_employees_paid, final_submission=data.final_submission,
        total_statutory_pay_recovered=data.total_statutory_pay_recovered,
        as_of=data.as_of, actor_id=current_user.id,
    )


# ── India: Form 130 (per-employee) + Form 138 (per-quarter) generation ──
# (ZP-TAX-IN-2026-27-001 §6.2/§6.3, gap-closure Phase E, 2026-09-10).

@payroll_router.post(
    "/india/reports/form130", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate an India Form 130 salary TDS certificate for one employee — not tied to any single PayrollRun",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_india_form_130(
    data: UKEmployeeReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_uk_employee_report(
        db, current_user.organization_id, data.report_template_id, data.employee_id,
        data.as_of_date, actor_id=current_user.id,
    )


@payroll_router.post(
    "/india/reports/form138", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate India's Form 138 quarterly salary TDS statement — employer-level, sums every finalized payslip across the quarter's 3 runs",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_india_form_138(
    data: IndiaForm138GenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_india_form_138(
        db, current_user.organization_id, data.report_template_id, data.reporting_year, data.period_key,
        actor_id=current_user.id,
    )


@payroll_router.post(
    "/india/reports/form123", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate an India Form 123 employer perquisite statement for one employee — sourced from Issued benefit valuations",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_india_form_123(
    data: IndiaForm123GenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_india_form_123(
        db, current_user.organization_id, data.report_template_id, data.employee_id, data.tax_year,
        actor_id=current_user.id,
    )


@payroll_router.get(
    "/generated-reports/{generated_report_id}/rti-xml",
    summary="Download a FPS/EPS/P45 GeneratedReport as HMRC RTI-shaped XML (correctly shaped, not yet transmittable)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def download_rti_xml(
    generated_report_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    xml_bytes = service.generate_rti_xml_bytes(db, current_user.organization_id, generated_report_id)
    return StreamingResponse(
        io.BytesIO(xml_bytes),
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="rti-{generated_report_id}.xml"'},
    )


@payroll_router.post(
    "/uk/rti-submissions", response_model=RtiSubmissionResponse, response_model_by_alias=True,
    summary="Start tracking an FPS/EPS/P45 GeneratedReport toward HMRC filing (status tracking only, no transmission)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def create_rti_submission(
    data: RtiSubmissionCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.create_rti_submission(db, current_user.organization_id, data.generated_report_id, created_by_id=current_user.id)


@payroll_router.get(
    "/uk/rti-submissions", response_model=list[RtiSubmissionResponse], response_model_by_alias=True,
    summary="List this organization's RTI submissions, optionally filtered by status",
    dependencies=[Depends(get_current_payroll_operator)],
)
def list_rti_submissions(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_rti_submissions(db, current_user.organization_id, status)


@payroll_router.put(
    "/uk/rti-submissions/{submission_id}/status", response_model=RtiSubmissionResponse, response_model_by_alias=True,
    summary="Record a manual RTI filing status transition (a human filed through HMRC's own tools — this never calls HMRC itself)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def set_rti_submission_status(
    submission_id: int,
    data: RtiSubmissionStatusUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.set_rti_submission_status(
        db, current_user.organization_id, submission_id, data.status,
        hmrc_correlation_id=data.hmrc_correlation_id, rejection_reason=data.rejection_reason,
    )


@payroll_router.get(
    "/report-templates/filing-calendar", response_model=List[FilingCalendarResponse], response_model_by_alias=True,
    summary="This organization's upcoming Active statutory filing due dates, soonest first",
)
def get_upcoming_filing_dates(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_upcoming_filing_dates_for_org(db, current_user.organization_id, limit=limit)


# ── Dashboard ──────────────────────────────────────────────────────────

@payroll_router.get(
    "/dashboard/summary", response_model=DashboardSummaryResponse, response_model_by_alias=True,
    summary="Get dashboard summary stats",
)
def dashboard_summary(
    year: Optional[int] = Query(None, ge=2020, le=2099, description="Filter by year (defaults to current)"),
    month: Optional[int] = Query(None, ge=1, le=12, description="Filter by month (1-12, defaults to current)"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_dashboard_summary(db, current_user.organization_id, year=year, month=month)


@payroll_router.get(
    "/dashboard/trend", response_model=List[DashboardTrendPoint], response_model_by_alias=True,
    summary="Get monthly payroll cost trend",
)
def dashboard_trend(
    months: int = Query(6, ge=1, le=24),
    year: Optional[int] = Query(None, ge=2020, le=2099, description="Center trend around this year"),
    month: Optional[int] = Query(None, ge=1, le=12, description="Center trend around this month"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_dashboard_trend(db, current_user.organization_id, months=months, year=year, month=month)


@payroll_router.get(
    "/dashboard/activity", response_model=List[RecentActivityItem], response_model_by_alias=True,
    summary="Get recent payroll activity",
)
def dashboard_activity(
    limit: int = Query(20, ge=1, le=100),
    year: Optional[int] = Query(None, ge=2020, le=2099, description="Filter by year"),
    month: Optional[int] = Query(None, ge=1, le=12, description="Filter by month (1-12)"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_recent_activity(db, current_user.organization_id, limit=limit, year=year, month=month)


@payroll_router.get(
    "/dashboard/breakdowns",
    summary="Get department, pay-type, and deduction breakdowns from payslip data",
)
def dashboard_breakdowns(
    year: Optional[int] = Query(None, ge=2020, le=2099, description="Filter by year"),
    month: Optional[int] = Query(None, ge=1, le=12, description="Filter by month (1-12)"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_dashboard_breakdowns(db, current_user.organization_id, year=year, month=month)