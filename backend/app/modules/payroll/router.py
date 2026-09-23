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
    GET    /payroll/employees/{id}/statutory-profile          → Resolve statutory profile as of a date (default: today)
    GET    /payroll/employees/{id}/statutory-profile/history  → List every effective-dated version
    POST   /payroll/employees/{id}/statutory-profile          → Record a new effective-dated version

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
)
from app.core.exceptions import ForbiddenException, NotFoundException
from app.modules.billing.entitlements import require_writeable_workspace, require_active_subscription, require_scope_limit, require_not_dunning_restricted
from app.modules.billing.feature_keys import MAX_BWM
from app.modules.billing.models import DunningStage
from app.modules.billing import bwm as billing_bwm
from app.modules.payroll import service
from app.modules.payroll.policy.router import policy_router
from app.modules.payroll.enterprise.router import enterprise_router
from app.modules.payroll.mail.router import mail_router
from app.modules.payroll.forms.router import forms_router
from app.modules.payroll.schemas import (
    PayrollRunCreate, PayrollRunUpdate, PayrollRunResponse,
    PayrollRunPreviewRequest, PayrollRunPreviewResponse,
    PayslipItemCreate, PayslipItemResponse,
    CompanyDetailsUpdate, ComplianceDataResponse,
    ComplianceDocumentResponse,
    ContributionRateResponse, TaxSlabResponse, LocalityRateResponse,
    ApplyExtractedRateRequest, ApplyExtractedRateResponse,
    JurisdictionPackResponse, JurisdictionPackUpsert,
    DashboardSummaryResponse, DashboardTrendPoint, RecentActivityItem,
    SuccessResponse,
    EmployeeCreate, EmployeeUpdate, EmployeeResponse,
    BulkEmployeeRequest, BulkUpsertResponse, BulkUpdateResponse, BulkDeleteRequest,
    EmployeeStatutoryProfileCreate, EmployeeStatutoryProfileResponse,
    GermanyOvertimeWorkRecordCreate, GermanyOvertimeWorkRecordResponse, GermanyOvertimeWorkRecordApprovalUpdate,
    GermanyOvertimeTimeSegmentResponse, GermanyOvertimeWageTaxResultResponse,
    GermanyOvertimeSocialInsuranceResultResponse,
    GermanyOvertimePremiumComponentResponse, GermanyOvertimePremiumComponentAttachRequest,
    GermanyOvertimePremiumComponentEligibleResponse,
    GermanyOvertimePremiumComponentBatchAttachRequest, GermanyOvertimePremiumComponentBatchAttachResponse,
    GermanyCalculationPreviewRequest,
    GermanyElstamChangeListBatchCreate, GermanyElstamChangeListBatchStatusUpdate,
    GermanyElstamChangeListBatchResponse, GermanyElstamImportRequest, GermanyElstamImportAttemptResponse,
    GermanyElsterCertificateConfigSet, GermanyElsterTransmissionCreate,
    GermanyElsterCertificateConfigResponse, GermanyElsterTransmissionResponse,
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
    AUCourtOrderCalculateRequest,
    GratuityCalculateRequest, GratuityCalculateResponse,
    IndiaForm138GenerateRequest, IndiaForm123GenerateRequest, USW2GenerateRequest,
    USForm941GenerateRequest, USForm940GenerateRequest,
    AUSuperstreamGenerateRequest, AUPayrollTaxReturnGenerateRequest,
    NewHireReportCreate, NewHireReportMarkFiledRequest, NewHireReportResponse,
    SalaryTdsDeclarationCreate, SalaryTdsDeclarationResponse,
    SalaryTdsClaimCreate, SalaryTdsClaimResponse, SalaryTdsClaimRejectRequest,
    EmployeeBenefitValuationCreate, EmployeeBenefitValuationResponse,
    UKEmployeeReportGenerateRequest, UKEpsGenerateRequest,
    CAPd7aGenerateRequest,
    GYMonthlyReportGenerateRequest,
    JMAnnualReportGenerateRequest,
    CASpecialPaymentCalculateRequest, CASpecialPaymentCalculateResponse,
    AUSchedule5CalculateRequest, AUSchedule5CalculateResponse,
    AUSchedule4CalculateRequest, AUSchedule4CalculateResponse,
    USSupplementalWageCalculateRequest, USSupplementalWageCalculateResponse,
    USFederalDepositScheduleRequest, USFederalDepositScheduleResponse,
    CARetiringAllowanceCalculateRequest, CARetiringAllowanceCalculateResponse,
    CATd1xCommissionCalculateRequest, CATd1xCommissionCalculateResponse,
    CAWsdrfCalculateRequest, CAWsdrfCalculateResponse,
    RtiSubmissionCreate, RtiSubmissionStatusUpdate, RtiSubmissionResponse,
    HolidayCreate, BulkHolidayRequest, HolidayResponse,
    ApplicableTemplateResponse, GenerateReportRequest, GeneratedReportResponse, VoidGeneratedReportRequest,
    FilingCalendarResponse,
)

payroll_router = APIRouter(
    prefix="/payroll",
    tags=["Payroll Module"],
    dependencies=[Depends(require_active_subscription)],
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
    summary="Create an employee", dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def create_employee(
    data: EmployeeCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    current_count = billing_bwm.count_billable_workers(db, current_user.organization_id)
    require_scope_limit(MAX_BWM, requested_qty=current_count + 1)(current_user=current_user, db=db)
    return service.create_employee(db, data, current_user.organization_id)


@payroll_router.post(
    "/employees/bulk", response_model=BulkUpsertResponse,
    summary="Bulk create employees from imported data",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
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
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
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
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
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
    summary="Update an employee", dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
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
    summary="Delete an employee", dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def delete_employee(
    employee_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service.delete_employee(db, employee_id, current_user.organization_id)
    return {"message": "Employee deleted."}


# ── Employee Statutory Profile (effective-dated) ────────────────────────
# Foundation-only in this phase: no Germany calculation reads these yet.
# Same RBAC tier as employee CRUD above (payroll operator) — this is
# tenant-owned employee data, a different security domain from Super
# Admin's jurisdiction-wide statutory configuration (JurisdictionPack).

@payroll_router.get(
    "/employees/{employee_id}/statutory-profile", response_model=Optional[EmployeeStatutoryProfileResponse],
    response_model_by_alias=True, summary="Get an employee's statutory profile as of a date (defaults to today)",
)
def get_employee_statutory_profile(
    employee_id: int,
    as_of: Optional[date] = Query(None, description="Resolve the profile applicable on this date; defaults to today."),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_employee_statutory_profile_as_of(db, employee_id, current_user.organization_id, as_of)


@payroll_router.get(
    "/employees/{employee_id}/statutory-profile/history", response_model=List[EmployeeStatutoryProfileResponse],
    response_model_by_alias=True, summary="List every effective-dated statutory profile version for an employee",
)
def get_employee_statutory_profile_history(
    employee_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_employee_statutory_profile_history(db, employee_id, current_user.organization_id)


@payroll_router.post(
    "/employees/{employee_id}/statutory-profile", response_model=EmployeeStatutoryProfileResponse,
    response_model_by_alias=True, summary="Record a new effective-dated statutory profile version for an employee",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def create_employee_statutory_profile(
    employee_id: int,
    data: EmployeeStatutoryProfileCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.create_employee_statutory_profile_version(
        db, employee_id, current_user.organization_id, data, current_user.id,
    )


# ── Germany overtime/shift-premium work records (Phase 8AC) ─────────────
# Fact capture only — no premium/tax/SI calculation. Same tenant-owned
# security tier as the statutory-profile endpoints above.

@payroll_router.get(
    "/employees/{employee_id}/germany-overtime-work-records",
    response_model=List[GermanyOvertimeWorkRecordResponse], response_model_by_alias=True,
    summary="List an employee's Germany overtime/shift-premium work records",
)
def list_germany_overtime_work_records(
    employee_id: int,
    date_from: Optional[date] = Query(None, alias="dateFrom"),
    date_to: Optional[date] = Query(None, alias="dateTo"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_germany_overtime_work_records(
        db, employee_id, current_user.organization_id, date_from=date_from, date_to=date_to,
    )


@payroll_router.get(
    "/employees/{employee_id}/germany-overtime-work-records/{record_id}",
    response_model=GermanyOvertimeWorkRecordResponse, response_model_by_alias=True,
    summary="Get a single Germany overtime/shift-premium work record",
)
def get_germany_overtime_work_record(
    employee_id: int,
    record_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = service.get_germany_overtime_work_record_by_id(db, record_id, current_user.organization_id)
    if row.employee_id != employee_id:
        raise NotFoundException("GermanyOvertimeWorkRecord", record_id)
    return row


@payroll_router.post(
    "/employees/{employee_id}/germany-overtime-work-records",
    response_model=GermanyOvertimeWorkRecordResponse, response_model_by_alias=True,
    summary="Record a Germany overtime/shift-premium work-time fact (attendance-derived or manual)",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def create_germany_overtime_work_record(
    employee_id: int,
    data: GermanyOvertimeWorkRecordCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.create_germany_overtime_work_record(
        db, employee_id, current_user.organization_id, data, current_user.id,
    )


@payroll_router.post(
    "/employees/{employee_id}/germany-overtime-work-records/{record_id}/approval",
    response_model=GermanyOvertimeWorkRecordResponse, response_model_by_alias=True,
    summary="Set the HR approval status of a Germany overtime/shift-premium work record",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def set_germany_overtime_work_record_approval(
    employee_id: int,
    record_id: int,
    data: GermanyOvertimeWorkRecordApprovalUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = service.get_germany_overtime_work_record_by_id(db, record_id, current_user.organization_id)
    if row.employee_id != employee_id:
        raise NotFoundException("GermanyOvertimeWorkRecord", record_id)
    return service.set_germany_overtime_work_record_approval(
        db, record_id, current_user.organization_id, data.hr_approval_status, current_user.id,
    )


# ── Germany overtime time-window CLASSIFICATION (Phase 8AE) ─────────────
# Statutory/calendar classification only — never named "calculate"/
# "preview-calculation"/"premium-preview", since this phase computes no
# money. Same tenant-owned security tier as the work-record endpoints
# above.

@payroll_router.post(
    "/employees/{employee_id}/germany-overtime-work-records/{record_id}/classification",
    response_model=List[GermanyOvertimeTimeSegmentResponse], response_model_by_alias=True,
    summary="Classify a Germany overtime work record's §3b EStG time-window categories (no money calculated)",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def classify_germany_overtime_work_record(
    employee_id: int,
    record_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = service.get_germany_overtime_work_record_by_id(db, record_id, current_user.organization_id)
    if row.employee_id != employee_id:
        raise NotFoundException("GermanyOvertimeWorkRecord", record_id)
    return service.classify_and_list_germany_overtime_time_segments(
        db, record_id, current_user.organization_id, actor_id=current_user.id,
    )


@payroll_router.get(
    "/employees/{employee_id}/germany-overtime-work-records/{record_id}/classification",
    response_model=List[GermanyOvertimeTimeSegmentResponse], response_model_by_alias=True,
    summary="Read a Germany overtime work record's existing classification result, if any",
)
def get_germany_overtime_work_record_classification(
    employee_id: int,
    record_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = service.get_germany_overtime_work_record_by_id(db, record_id, current_user.organization_id)
    if row.employee_id != employee_id:
        raise NotFoundException("GermanyOvertimeWorkRecord", record_id)
    return service.list_germany_overtime_time_segments(db, record_id, current_user.organization_id)


# ── Germany overtime WAGE-TAX calculation (Phase 8AF) ────────────────────
# WAGE TAX ONLY — no social-insurance treatment. Same tenant-owned
# security tier as the classification endpoints above.

@payroll_router.post(
    "/employees/{employee_id}/germany-overtime-work-records/{record_id}/wage-tax-calculation",
    response_model=List[GermanyOvertimeWageTaxResultResponse], response_model_by_alias=True,
    summary="Calculate a Germany overtime work record's §3b EStG WAGE-TAX tax-free/taxable split (no social insurance)",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def calculate_germany_overtime_wage_tax(
    employee_id: int,
    record_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = service.get_germany_overtime_work_record_by_id(db, record_id, current_user.organization_id)
    if row.employee_id != employee_id:
        raise NotFoundException("GermanyOvertimeWorkRecord", record_id)
    return service.calculate_and_list_germany_overtime_wage_tax(
        db, record_id, current_user.organization_id, actor_id=current_user.id,
    )


@payroll_router.get(
    "/employees/{employee_id}/germany-overtime-work-records/{record_id}/wage-tax-calculation",
    response_model=List[GermanyOvertimeWageTaxResultResponse], response_model_by_alias=True,
    summary="Read a Germany overtime work record's existing wage-tax calculation result, if any",
)
def get_germany_overtime_wage_tax_result(
    employee_id: int,
    record_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = service.get_germany_overtime_work_record_by_id(db, record_id, current_user.organization_id)
    if row.employee_id != employee_id:
        raise NotFoundException("GermanyOvertimeWorkRecord", record_id)
    return service.list_germany_overtime_wage_tax_results(db, record_id, current_user.organization_id)


# ── Germany overtime SOCIAL-INSURANCE calculation (Phase 8AG) ───────────
# SOCIAL INSURANCE ONLY — independent of the wage-tax endpoints above.
# Same tenant-owned security tier.

@payroll_router.post(
    "/employees/{employee_id}/germany-overtime-work-records/{record_id}/social-insurance-calculation",
    response_model=List[GermanyOvertimeSocialInsuranceResultResponse], response_model_by_alias=True,
    summary="Calculate a Germany overtime work record's §1 SvEV SOCIAL-INSURANCE-free/contributory split (no wage tax)",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def calculate_germany_overtime_social_insurance(
    employee_id: int,
    record_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = service.get_germany_overtime_work_record_by_id(db, record_id, current_user.organization_id)
    if row.employee_id != employee_id:
        raise NotFoundException("GermanyOvertimeWorkRecord", record_id)
    return service.calculate_and_list_germany_overtime_social_insurance(
        db, record_id, current_user.organization_id, actor_id=current_user.id,
    )


@payroll_router.get(
    "/employees/{employee_id}/germany-overtime-work-records/{record_id}/social-insurance-calculation",
    response_model=List[GermanyOvertimeSocialInsuranceResultResponse], response_model_by_alias=True,
    summary="Read a Germany overtime work record's existing social-insurance calculation result, if any",
)
def get_germany_overtime_social_insurance_result(
    employee_id: int,
    record_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = service.get_germany_overtime_work_record_by_id(db, record_id, current_user.organization_id)
    if row.employee_id != employee_id:
        raise NotFoundException("GermanyOvertimeWorkRecord", record_id)
    return service.list_germany_overtime_social_insurance_results(db, record_id, current_user.organization_id)


# ── Germany overtime PREMIUM COMPONENT (Phase 8AH) ──────────────────────
# Combines the wage-tax and social-insurance results above into a single
# presentable output unit. Attach is a SEPARATE, explicit action — never
# performed automatically by build/list. Same tenant-owned security tier.

@payroll_router.post(
    "/employees/{employee_id}/germany-overtime-work-records/{record_id}/premium-components",
    response_model=List[GermanyOvertimePremiumComponentResponse], response_model_by_alias=True,
    summary="Build/rebuild a Germany overtime work record's premium components (combines wage-tax + social-insurance results)",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def build_germany_overtime_premium_components(
    employee_id: int,
    record_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = service.get_germany_overtime_work_record_by_id(db, record_id, current_user.organization_id)
    if row.employee_id != employee_id:
        raise NotFoundException("GermanyOvertimeWorkRecord", record_id)
    return service.build_germany_overtime_premium_components(
        db, record_id, current_user.organization_id, actor_id=current_user.id,
    )


@payroll_router.get(
    "/employees/{employee_id}/germany-overtime-work-records/{record_id}/premium-components",
    response_model=List[GermanyOvertimePremiumComponentResponse], response_model_by_alias=True,
    summary="Read a Germany overtime work record's existing premium components, if any",
)
def get_germany_overtime_premium_components(
    employee_id: int,
    record_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = service.get_germany_overtime_work_record_by_id(db, record_id, current_user.organization_id)
    if row.employee_id != employee_id:
        raise NotFoundException("GermanyOvertimeWorkRecord", record_id)
    return service.list_germany_overtime_premium_components(db, record_id, current_user.organization_id)


@payroll_router.post(
    "/employees/{employee_id}/germany-overtime-work-records/{record_id}/premium-components/{component_id}/attach-to-payslip",
    response_model=GermanyOvertimePremiumComponentResponse, response_model_by_alias=True,
    summary="Explicitly attach one COMPLETE, HR-approved premium component to a real payslip line",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def attach_germany_overtime_premium_component_to_payslip(
    employee_id: int,
    record_id: int,
    component_id: int,
    payload: GermanyOvertimePremiumComponentAttachRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = service.get_germany_overtime_work_record_by_id(db, record_id, current_user.organization_id)
    if row.employee_id != employee_id:
        raise NotFoundException("GermanyOvertimeWorkRecord", record_id)
    return service.attach_germany_overtime_premium_component_to_payslip(
        db, component_id, payload.payslip_item_id, current_user.organization_id, actor_id=current_user.id,
    )


@payroll_router.post(
    "/employees/{employee_id}/germany-overtime-work-records/{record_id}/premium-components/{component_id}/detach-from-payslip",
    response_model=GermanyOvertimePremiumComponentResponse, response_model_by_alias=True,
    summary="Explicitly detach a previously-attached premium component from its payslip line (reverses attach; never deletes history)",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def detach_germany_overtime_premium_component_from_payslip(
    employee_id: int,
    record_id: int,
    component_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = service.get_germany_overtime_work_record_by_id(db, record_id, current_user.organization_id)
    if row.employee_id != employee_id:
        raise NotFoundException("GermanyOvertimeWorkRecord", record_id)
    return service.detach_germany_overtime_premium_component_from_payslip(
        db, component_id, current_user.organization_id, actor_id=current_user.id,
    )


# ── Batch attach (Phase 8AO) ──────────────────────────────────────────────
# Deliberately top-level (not nested under one employee/work-record), since
# a batch naturally spans multiple employees/work records within one
# organization — organization scope comes ONLY from current_user (never
# accepted from the client), exactly like every endpoint above.

@payroll_router.get(
    "/germany-overtime-premium-components/eligible-for-batch-attach",
    response_model=List[GermanyOvertimePremiumComponentEligibleResponse], response_model_by_alias=True,
    summary="Browse Germany overtime premium components across employees, for the batch-attach operator workflow",
    dependencies=[Depends(get_current_payroll_operator)],
)
def list_germany_overtime_premium_components_for_batch_attach(
    employeeId: Optional[int] = Query(None),
    workDateFrom: Optional[date] = Query(None),
    workDateTo: Optional[date] = Query(None),
    attachmentState: Optional[str] = Query(None, description='"ATTACHED" | "UNATTACHED" (omit for both)'),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_germany_overtime_premium_components_for_batch_attach(
        db, current_user.organization_id, employee_id=employeeId,
        work_date_from=workDateFrom, work_date_to=workDateTo, attachment_state=attachmentState,
    )


@payroll_router.post(
    "/germany-overtime-premium-components/batch-attach",
    response_model=GermanyOvertimePremiumComponentBatchAttachResponse, response_model_by_alias=True,
    summary="Explicitly attach a caller-selected batch of COMPLETE, HR-approved premium components to real payslip lines",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def batch_attach_germany_overtime_premium_components_to_payslips(
    payload: GermanyOvertimePremiumComponentBatchAttachRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    items = [(item.component_id, item.payslip_item_id) for item in payload.items]
    return service.batch_attach_germany_overtime_premium_components_to_payslips(
        db, items, current_user.organization_id, actor_id=current_user.id,
    )


# ── Germany ELStAM change-list / structured-import boundary (Phase 8N) ──
# Same tenant-owned security tier as the statutory-profile endpoints above
# (this is employee/employer data, not Super Admin's global statutory
# configuration). Neither endpoint calls ELSTER/BZSt — both operate on
# caller-supplied structured data only; see engine/germany_pap/elstam.py
# for the separate, still-unimplemented-by-design LIVE connector boundary.

@payroll_router.post(
    "/employees/{employee_id}/elstam-import", response_model=GermanyElstamImportAttemptResponse,
    response_model_by_alias=True,
    summary="Import a structured ELStAM payload for one employee (never a live ELSTER/BZSt call)",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def import_employee_elstam_payload(
    employee_id: int,
    data: GermanyElstamImportRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.import_elstam_structured_payload(
        db, employee_id, current_user.organization_id,
        schema_version=data.schema_version, import_reference=data.import_reference,
        change_list_batch_id=data.change_list_batch_id, payload=data.payload, actor_id=current_user.id,
    )


@payroll_router.get(
    "/employees/{employee_id}/elstam-imports", response_model=List[GermanyElstamImportAttemptResponse],
    response_model_by_alias=True, summary="List every ELStAM import attempt (applied or rejected) for an employee",
)
def get_employee_elstam_import_attempts(
    employee_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_elstam_import_attempts_for_employee(db, employee_id, current_user.organization_id)


@payroll_router.post(
    "/germany/elstam-change-list-batches", response_model=GermanyElstamChangeListBatchResponse,
    response_model_by_alias=True, summary="Record that a monthly ELStAM change-list batch was received",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def create_elstam_change_list_batch(
    data: GermanyElstamChangeListBatchCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.create_elstam_change_list_batch(db, current_user.organization_id, data, current_user.id)


@payroll_router.get(
    "/germany/elstam-change-list-batches", response_model=List[GermanyElstamChangeListBatchResponse],
    response_model_by_alias=True, summary="List ELStAM change-list batches received for this organization",
)
def list_elstam_change_list_batches(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_elstam_change_list_batches(db, current_user.organization_id)


@payroll_router.get(
    "/germany/elstam-change-list-batches/{batch_id}", response_model=GermanyElstamChangeListBatchResponse,
    response_model_by_alias=True, summary="Get one ELStAM change-list batch",
)
def get_elstam_change_list_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_elstam_change_list_batch(db, batch_id, current_user.organization_id)


@payroll_router.patch(
    "/germany/elstam-change-list-batches/{batch_id}/status", response_model=GermanyElstamChangeListBatchResponse,
    response_model_by_alias=True, summary="Advance an ELStAM change-list batch's processing status",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def update_elstam_change_list_batch_status(
    batch_id: int,
    data: GermanyElstamChangeListBatchStatusUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.set_elstam_change_list_batch_status(db, batch_id, current_user.organization_id, data, current_user.id)


@payroll_router.post(
    "/germany/calculation-preview", summary="Phase 7 QA diagnostic: preview a Germany employee's calculation "
    "against currently-published registries, without writing anything",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def germany_calculation_preview(
    data: GermanyCalculationPreviewRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Read-only. Never mutates a payroll run/payslip, never accepts a
    caller-supplied PAP version/statutory rate — every value used is
    resolved server-side from the same registries a real payroll run
    would use (see service.preview_germany_calculation). Returns either
    the resolved calculation (unreachable until a real PAP asset is
    ingested and a PapExecutor is implemented — see
    engine/countries/germany_pap.py) or the specific block reason +
    diagnostic trace, so Tax Operations/QA can see exactly what statutory
    source is missing."""
    return service.preview_germany_calculation(
        db, current_user.organization_id, data.employee_id, data.payroll_date,
    )


@payroll_router.get(
    "/germany/statutory-configuration-readiness",
    summary="Phase 8BF: whether Germany's GLOBAL statutory registries "
    "(health funds, contribution ceilings, PV configuration) are published "
    "and effective today — read-only, org-independent",
)
def germany_statutory_configuration_readiness(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Read-only, never seeds/creates a registry row. Answers a narrower,
    earlier question than germany_calculation_preview above: "is Germany
    payroll configuration even possible today, for ANY employee?" — so the
    UI can warn during Germany employee creation instead of only failing
    closed at actual payroll-run time (the previously disclosed onboarding
    gap — see service.get_germany_statutory_configuration_readiness's own
    docstring). These four registries are global (no organization_id
    column), so the result is the same for every caller regardless of
    `current_user.organization_id` — auth is required only because this
    endpoint is reached from inside the authenticated app, not because the
    answer is tenant-specific."""
    return service.get_germany_statutory_configuration_readiness(db)


@payroll_router.get(
    "/germany/reports/summary",
    summary="Phase 8BI: Germany statutory payroll summary — gross/net, "
    "employee counts by classification, statutory contributions, and "
    "wage-tax/PAP-blocked status, aggregated from real persisted payslips",
)
def germany_payroll_summary_report(
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Read-only, tenant-scoped. Never fabricates a figure this codebase
    cannot compute today — see service.get_germany_payroll_summary_report's
    own docstring for the CALCULATED/BLOCKED/UNAVAILABLE contract."""
    return service.get_germany_payroll_summary_report(
        db, current_user.organization_id, period_start=period_start, period_end=period_end,
    )


# ── Germany ELSTER transmission boundary (Phase 8BF) ────────────────────
# See engine/germany_elster.py's own module docstring: no real ELSTER
# connector exists or is authorized. Every endpoint below prepares/
# validates/records a transmission attempt that deterministically lands on
# BLOCKED_EXTERNAL — none of them contact ELSTER/BZSt.

@payroll_router.get(
    "/germany/elster-certificate-config", response_model=Optional[GermanyElsterCertificateConfigResponse],
    response_model_by_alias=True, summary="Whether an ELSTER certificate reference is configured for this organization",
)
def get_germany_elster_certificate_config(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_elster_certificate_config(db, current_user.organization_id)


@payroll_router.put(
    "/germany/elster-certificate-config", response_model=GermanyElsterCertificateConfigResponse,
    response_model_by_alias=True, summary="Record an ELSTER certificate reference (never the certificate/key itself)",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def put_germany_elster_certificate_config(
    data: GermanyElsterCertificateConfigSet,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.set_elster_certificate_config(
        db, current_user.organization_id, data.certificate_reference, data.reference_description, current_user.id,
    )


@payroll_router.post(
    "/germany/elster-transmissions", response_model=GermanyElsterTransmissionResponse,
    response_model_by_alias=True, summary="Record a DRAFT ELSTER transmission attempt",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def create_germany_elster_transmission(
    data: GermanyElsterTransmissionCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.create_elster_transmission(db, current_user.organization_id, data, current_user.id)


@payroll_router.get(
    "/germany/elster-transmissions", response_model=List[GermanyElsterTransmissionResponse],
    response_model_by_alias=True, summary="List this organization's ELSTER transmission attempts",
)
def list_germany_elster_transmissions(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_elster_transmissions(db, current_user.organization_id)


@payroll_router.get(
    "/germany/elster-transmissions/{transmission_id}", response_model=GermanyElsterTransmissionResponse,
    response_model_by_alias=True, summary="Get one ELSTER transmission attempt by id (Phase 8BI)",
)
def get_germany_elster_transmission(
    transmission_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Tenant-scoped: 404s (not a cross-tenant leak) if the transmission
    doesn't belong to this organization — same
    get_elster_transmission_by_id lookup validate/transmit already use
    internally, simply not previously exposed as its own GET route."""
    return service.get_elster_transmission_by_id(db, transmission_id, current_user.organization_id)


@payroll_router.post(
    "/germany/elster-transmissions/{transmission_id}/validate", response_model=GermanyElsterTransmissionResponse,
    response_model_by_alias=True, summary="Structurally validate a DRAFT ELSTER transmission",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def validate_germany_elster_transmission(
    transmission_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.validate_elster_transmission(db, transmission_id, current_user.organization_id, current_user.id)


@payroll_router.post(
    "/germany/elster-transmissions/{transmission_id}/transmit", response_model=GermanyElsterTransmissionResponse,
    response_model_by_alias=True,
    summary="Attempt transmission — today ALWAYS records BLOCKED_EXTERNAL (no real ELSTER connector exists)",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def transmit_germany_elster_transmission(
    transmission_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.attempt_transmit_elster_transmission(db, transmission_id, current_user.organization_id, current_user.id)


# ── Payroll Runs ─────────────────────────────────────────────────────

@payroll_router.post(
    "/runs", response_model=PayrollRunResponse, response_model_by_alias=True,
    summary="Create a payroll run",
    dependencies=[
        Depends(get_current_payroll_operator),
        Depends(require_writeable_workspace()),
        Depends(require_not_dunning_restricted(DunningStage.RESTRICT_NEW_RUN.value)),
    ],
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
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
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
    summary="Update payroll run details (Draft only)", dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
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
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
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
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
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
    summary="Delete a Draft payroll run", dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
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
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
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


# Australia child support/garnishee (§19, Phase 5) — reuses UK's own
# Create/Response/StatusUpdate schemas and the generic
# create_court_ordered_deduction/list_court_ordered_deductions/
# set_court_ordered_deduction_status service functions directly (they
# were never UK-only); only the route prefix and the calculate wrapper
# are AU-specific, same per-country route-namespacing convention every
# other jurisdiction in this router already uses.

@payroll_router.post(
    "/au/employees/{employee_id}/court-orders", response_model=UKCourtOrderResponse, response_model_by_alias=True,
    summary="Record an Australia statutory deduction order (child support/garnishee) for an employee",
    dependencies=[Depends(get_current_payroll_operator)],
)
def create_au_court_ordered_deduction(
    employee_id: int,
    data: UKCourtOrderCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.create_court_ordered_deduction(
        db, current_user.organization_id, employee_id,
        "AUSTRALIA", data.order_type, data.start_date,
        court_reference=data.court_reference, issue_date=data.issue_date, end_date=data.end_date,
        priority=data.priority,
        fixed_deduction_rate_pct=data.fixed_deduction_rate_pct, fixed_deduction_amount=data.fixed_deduction_amount,
        protected_earnings_amount=data.protected_earnings_amount, total_amount_to_collect=data.total_amount_to_collect,
        created_by_id=current_user.id,
    )


@payroll_router.get(
    "/au/employees/{employee_id}/court-orders", response_model=list[UKCourtOrderResponse], response_model_by_alias=True,
    summary="List an employee's Australia statutory deduction orders",
    dependencies=[Depends(get_current_payroll_operator)],
)
def list_au_court_ordered_deductions(
    employee_id: int,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_court_ordered_deductions(db, current_user.organization_id, employee_id, status)


@payroll_router.put(
    "/au/employees/{employee_id}/court-orders/{order_id}/status", response_model=UKCourtOrderResponse, response_model_by_alias=True,
    summary="Cancel/complete an Australia statutory deduction order (no hard delete — a legal instrument stays in the record)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def set_au_court_ordered_deduction_status(
    employee_id: int,
    order_id: int,
    data: UKCourtOrderStatusUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.set_court_ordered_deduction_status(db, current_user.organization_id, employee_id, order_id, data.status)


@payroll_router.post(
    "/au/court-orders/calculate", response_model=UKCourtOrderCalculateResponse, response_model_by_alias=True,
    summary="Preview this period's Australia statutory deductions for an employee (does not write to total_amount_collected)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def calculate_au_court_ordered_deductions(
    data: AUCourtOrderCalculateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.calculate_au_court_ordered_deductions(
        db, current_user.organization_id, data.employee_id, data.attachable_earnings, data.as_of,
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


@payroll_router.post(
    "/canada/special-payment/calculate", response_model=CASpecialPaymentCalculateResponse, response_model_by_alias=True,
    summary="Calculate additional withholding for a Canada bonus/retroactive pay/vacation-not-taken/accumulated-overtime special payment (CRA's real incremental-tax method)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def calculate_ca_special_payment(
    data: CASpecialPaymentCalculateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.calculate_ca_special_payment_withholding(
        db, current_user.organization_id, data.employee_id,
        data.regular_annual_pay, data.special_payment_amount, payroll_date=data.payroll_date,
    )


@payroll_router.post(
    "/us/supplemental-wages/calculate", response_model=USSupplementalWageCalculateResponse, response_model_by_alias=True,
    summary="Calculate US federal withholding on a supplemental wage payment (IRS Pub. 15 flat-rate method: 22%, mandatory 37% above $1,000,000 CYTD)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def calculate_us_supplemental_wages(
    data: USSupplementalWageCalculateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.calculate_us_supplemental_wage_withholding(
        db, current_user.organization_id, data.employee_id,
        data.supplemental_wage_amount, cytd_supplemental_wages_before=data.cytd_supplemental_wages_before,
    )


@payroll_router.post(
    "/australia/schedule5/calculate", response_model=AUSchedule5CalculateResponse, response_model_by_alias=True,
    summary="Calculate Australia PAYG withholding on a back payment/commission/bonus spanning more than one pay period (ATO Schedule 5/NAT 3348 averaging method)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def calculate_au_schedule5(
    data: AUSchedule5CalculateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.calculate_au_employee_schedule5_withholding(
        db, current_user.organization_id, data.employee_id,
        data.regular_period_gross, data.special_payment_amount, payroll_date=data.payroll_date,
    )


@payroll_router.post(
    "/australia/schedule4/calculate", response_model=AUSchedule4CalculateResponse, response_model_by_alias=True,
    summary="Calculate Australia PAYG withholding on a return-to-work payment (ATO Schedule 4/NAT 3347 flat-rate method)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def calculate_au_schedule4(
    data: AUSchedule4CalculateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.calculate_au_employee_schedule4_withholding(
        db, current_user.organization_id, data.employee_id, data.payment_amount,
    )


@payroll_router.post(
    "/us/federal-deposit-schedule/calculate", response_model=USFederalDepositScheduleResponse, response_model_by_alias=True,
    summary="Calculate US federal depositor status (Monthly/Semiweekly), deposit due date, $100,000 next-day rule, FUTA deposit trigger, and Form W-2/W-3 deadline",
    dependencies=[Depends(get_current_payroll_operator)],
)
def calculate_us_federal_deposit_schedule(
    data: USFederalDepositScheduleRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.calculate_us_federal_deposit_schedule(
        db, current_user.organization_id, data.lookback_period_liability, data.payroll_date,
        accumulated_undeposited_liability=data.accumulated_undeposited_liability,
        quarterly_futa_liability=data.quarterly_futa_liability,
    )


@payroll_router.post(
    "/canada/retiring-allowance/calculate", response_model=CARetiringAllowanceCalculateResponse, response_model_by_alias=True,
    summary="Calculate federal lump-sum withholding for a Canada retiring allowance/severance payment (rate-table lookup, no hardcoded rate)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def calculate_ca_retiring_allowance(
    data: CARetiringAllowanceCalculateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.calculate_ca_retiring_allowance_withholding(
        db, current_user.organization_id, data.employee_id, data.amount, payroll_date=data.payroll_date,
    )


@payroll_router.post(
    "/canada/td1x-commission/calculate", response_model=CATd1xCommissionCalculateResponse, response_model_by_alias=True,
    summary="Calculate recommended per-period withholding for a Canada commission employee with TD1X estimates on file",
    dependencies=[Depends(get_current_payroll_operator)],
)
def calculate_ca_td1x_commission(
    data: CATd1xCommissionCalculateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.calculate_ca_td1x_commission_withholding(
        db, current_user.organization_id, data.employee_id,
        payroll_date=data.payroll_date, pay_periods_per_year=data.pay_periods_per_year,
    )


@payroll_router.post(
    "/canada/wsdrf/calculate", response_model=CAWsdrfCalculateResponse, response_model_by_alias=True,
    summary="Calculate Quebec WSDRF shortfall for a period — 1% of total Quebec payroll minus declared eligible training expenditure",
    dependencies=[Depends(get_current_payroll_operator)],
)
def calculate_ca_wsdrf(
    data: CAWsdrfCalculateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.calculate_ca_wsdrf_shortfall(
        db, current_user.organization_id, data.period_start, data.period_end,
        training_expenditure_override=data.training_expenditure_override,
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
    # Phase 8BW: every OTHER delete endpoint in this router (delete_employee,
    # delete_run, delete_holiday, etc.) requires get_current_payroll_operator
    # — this one was the one confirmed outlier still gated on bare
    # get_current_user, allowing ANY authenticated org role to delete a
    # payslip. Fixed to match the established sibling pattern (no new
    # authorization concept introduced).
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
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
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
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
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
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
    dependencies=[Depends(require_writeable_workspace())],
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
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
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
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
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
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
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
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
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
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
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


@payroll_router.get(
    "/compliance/tax-slabs/state", response_model=List[TaxSlabResponse], response_model_by_alias=True,
    summary="Get a state/province's own income tax slabs (e.g. US state tax, CA provincial tax)",
)
def get_state_tax_slabs(
    country: str = Query("IN", description="Jurisdiction country code (IN, US, UK, …)"),
    state: Optional[str] = Query(None, description="State/province/region code, e.g. CA, ON"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_state_tax_slabs(db, country=country, state=state)


@payroll_router.get(
    "/compliance/locality-rates", response_model=List[LocalityRateResponse], response_model_by_alias=True,
    summary="Get local tax rates for this org's own employees' work localities",
)
def get_org_locality_rates(
    country: str = Query("US", description="Jurisdiction country code (US today)"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_org_locality_rates(db, current_user.organization_id, country=country)


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
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
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
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
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
    summary="Update company compliance details", dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
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
    dependencies=[Depends(require_writeable_workspace())],
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
    dependencies=[Depends(require_writeable_workspace())],
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
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
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
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
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


# ── Australia: SuperStream contribution message + state payroll-tax ────
# return generation (ZP-TAX-AU-2026-27-001 §12/§15-18, Phase 9, 2026-09-17).
# STP itself has no dedicated endpoint — it uses the fully generic
# POST /generated-reports above unchanged, same as CA/India/UK's own
# generic-engine report types.

@payroll_router.post(
    "/au/reports/superstream", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate an Australia SuperStream contribution message for one payroll run",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_au_superstream(
    data: AUSuperstreamGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_au_superstream_report(
        db, current_user.organization_id, data.report_template_id, data.payroll_run_id, actor_id=current_user.id,
    )


@payroll_router.post(
    "/au/reports/payroll-tax-return", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate an Australia state/territory payroll tax return — employer-level, sums every finalized payslip across the period's runs",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_au_payroll_tax_return(
    data: AUPayrollTaxReturnGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_au_state_payroll_tax_return(
        db, current_user.organization_id, data.report_template_id, data.work_state,
        data.period_start, data.period_end, actor_id=current_user.id,
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


# ── US: Form W-2 (Production-Readiness Plan Phase 5) ────────────────────

@payroll_router.post(
    "/us/reports/w2", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a US Form W-2 (Wage and Tax Statement) for one employee for a calendar tax year",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_us_w2(
    data: USW2GenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_us_w2(
        db, current_user.organization_id, data.report_template_id, data.employee_id, data.tax_year,
        actor_id=current_user.id,
    )


@payroll_router.post(
    "/us/reports/941", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a US Form 941 (Employer's Quarterly Federal Tax Return) for one IRS calendar quarter",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_us_941(
    data: USForm941GenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_us_941(
        db, current_user.organization_id, data.report_template_id, data.year, data.quarter,
        actor_id=current_user.id,
    )


@payroll_router.post(
    "/us/reports/940", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a US Form 940 (Employer's Annual Federal Unemployment (FUTA) Tax Return) for one calendar year",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_us_940(
    data: USForm940GenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_us_940(
        db, current_user.organization_id, data.report_template_id, data.year,
        actor_id=current_user.id,
    )


# ── US: New Hire Reporting (Production-Readiness Plan Phase 5) ──────────

@payroll_router.get(
    "/us/new-hire-reports", response_model=List[NewHireReportResponse], response_model_by_alias=True,
    summary="List US New Hire Reporting tracking rows for this org (optionally filtered by status)",
)
def list_us_new_hire_reports(
    status: Optional[str] = Query(None, description="Pending | Filed"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_new_hire_reports(db, current_user.organization_id, status=status)


@payroll_router.post(
    "/us/new-hire-reports", response_model=NewHireReportResponse, response_model_by_alias=True,
    summary="Manually create a New Hire Reporting tracking row (e.g. for a pre-existing employee or a rehire)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def create_us_new_hire_report(
    data: NewHireReportCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.create_new_hire_report(
        db, current_user.organization_id, data.employeeId,
        hire_date=data.hireDate, work_state=data.workState, due_date_days=data.dueDateDays,
        actor_id=current_user.id,
    )


@payroll_router.post(
    "/us/new-hire-reports/{report_id}/mark-filed", response_model=NewHireReportResponse, response_model_by_alias=True,
    summary="Mark a New Hire Reporting tracking row as Filed",
    dependencies=[Depends(get_current_payroll_operator)],
)
def mark_us_new_hire_report_filed(
    report_id: int,
    data: NewHireReportMarkFiledRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.mark_new_hire_report_filed(
        db, current_user.organization_id, report_id,
        filed_date=data.filedDate, notes=data.notes, actor_id=current_user.id,
    )


# ── Canada: T4/RL-1/ROE (per-employee) + PD7A (per-period) generation ───
# (ZP-TAX-CA-2026-001, forms/reports gap-closure).

@payroll_router.post(
    "/canada/reports/t4", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a Canada T4 (Statement of Remuneration Paid) for one employee — not tied to any single PayrollRun",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_ca_t4(
    data: UKEmployeeReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_uk_employee_report(
        db, current_user.organization_id, data.report_template_id, data.employee_id,
        data.as_of_date, actor_id=current_user.id,
    )


@payroll_router.post(
    "/canada/reports/rl1", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a Quebec RL-1 (Relevé 1) for one employee — not tied to any single PayrollRun",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_ca_rl1(
    data: UKEmployeeReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_uk_employee_report(
        db, current_user.organization_id, data.report_template_id, data.employee_id,
        data.as_of_date, actor_id=current_user.id,
    )


@payroll_router.post(
    "/canada/reports/roe", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a Canada ROE (Record of Employment) for one employee, triggered by an interruption of earnings",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_ca_roe(
    data: UKEmployeeReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_uk_employee_report(
        db, current_user.organization_id, data.report_template_id, data.employee_id,
        data.as_of_date, actor_id=current_user.id,
    )


@payroll_router.post(
    "/canada/reports/pd7a", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a Canada PD7A statement of account for current source deductions over a remittance period",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_ca_pd7a(
    data: CAPd7aGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_ca_pd7a(
        db, current_user.organization_id, data.report_template_id, data.period_start, data.period_end,
        actor_id=current_user.id,
    )


# ── Guyana: GRA Form 5 (monthly PAYE) + NIS Electronic Schedule (monthly)
# + Form 7B (per-employee, annual) generation (Caribbean forms gap-
# closure, 2026-09-22).

@payroll_router.post(
    "/guyana/reports/form5", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a Guyana GRA Form 5 monthly PAYE return — employer-wide, sums every finalized payslip in the calendar month",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_gy_form_5(
    data: GYMonthlyReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_gy_form_5(
        db, current_user.organization_id, data.report_template_id, data.year, data.month,
        actor_id=current_user.id,
    )


@payroll_router.post(
    "/guyana/reports/nis-schedule", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a Guyana NIS Electronic Schedule for a calendar month — employer-wide, sums every finalized payslip",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_gy_nis_schedule(
    data: GYMonthlyReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_gy_nis_schedule(
        db, current_user.organization_id, data.report_template_id, data.year, data.month,
        actor_id=current_user.id,
    )


@payroll_router.post(
    "/guyana/reports/form7b", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a Guyana Form 7B annual employee earnings statement for one employee — not tied to any single PayrollRun",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_gy_form_7b(
    data: UKEmployeeReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_uk_employee_report(
        db, current_user.organization_id, data.report_template_id, data.employee_id,
        data.as_of_date, actor_id=current_user.id,
    )


# ── Trinidad and Tobago: Monthly PAYE/HS Return + NIBTT contribution
# data (monthly) + TD4 (per-employee, annual) generation (Caribbean
# forms gap-closure, country #2, 2026-09-23).

@payroll_router.post(
    "/tt/reports/monthly-return", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a Trinidad and Tobago Monthly PAYE/Health Surcharge Return — employer-wide, sums every finalized payslip in the calendar month",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_tt_monthly_return(
    data: GYMonthlyReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_tt_monthly_return(
        db, current_user.organization_id, data.report_template_id, data.year, data.month,
        actor_id=current_user.id,
    )


@payroll_router.post(
    "/tt/reports/nibtt-data", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate Trinidad and Tobago NIBTT contribution data for a calendar month — employer-wide, sums every finalized payslip",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_tt_nibtt_data(
    data: GYMonthlyReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_tt_nibtt_data(
        db, current_user.organization_id, data.report_template_id, data.year, data.month,
        actor_id=current_user.id,
    )


@payroll_router.post(
    "/tt/reports/td4", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a Trinidad and Tobago TD4 annual employee certificate for one employee — not tied to any single PayrollRun",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_tt_td4(
    data: UKEmployeeReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_uk_employee_report(
        db, current_user.organization_id, data.report_template_id, data.employee_id,
        data.as_of_date, actor_id=current_user.id,
    )


# ── Jamaica: S01 (monthly) + S02 (annual) return generation (Caribbean
# forms gap-closure, country #3, 2026-09-23).

@payroll_router.post(
    "/jamaica/reports/s01", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a Jamaica S01 monthly PAYE/NIS/NHT/Education Tax/HEART return — employer-wide, sums every finalized payslip in the calendar month",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_jm_s01(
    data: GYMonthlyReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_jm_s01(
        db, current_user.organization_id, data.report_template_id, data.year, data.month,
        actor_id=current_user.id,
    )


@payroll_router.post(
    "/jamaica/reports/s02", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a Jamaica S02 annual employer return for one calendar year — employer-wide, sums every finalized payslip",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_jm_s02(
    data: JMAnnualReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_jm_s02(
        db, current_user.organization_id, data.report_template_id, data.year,
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