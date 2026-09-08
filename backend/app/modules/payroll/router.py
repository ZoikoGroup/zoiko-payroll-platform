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
    require_active_subscription,
)
from app.core.exceptions import ForbiddenException, NotFoundException
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
    AttendanceRecordCreate, BulkAttendanceRequest, AttendanceRecordResponse,
    AttendanceSummaryResponse, BulkAttendanceResponse,
    LeaveAllocationCreate, BulkLeaveRequest, LeaveAllocationResponse,
    PayrollLeaveRequestCreate, PayrollLeaveRequestUpdate, PayrollLeaveRequestResponse,
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
    dependencies=[Depends(get_current_payroll_operator)],
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
    dependencies=[Depends(get_current_payroll_operator)],
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
    dependencies=[Depends(get_current_payroll_operator)],
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
    dependencies=[Depends(get_current_payroll_operator)],
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
    dependencies=[Depends(get_current_payroll_operator)],
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
    dependencies=[Depends(get_current_payroll_operator)],
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
    dependencies=[Depends(get_current_payroll_operator)],
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
    dependencies=[Depends(get_current_payroll_operator)],
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
    dependencies=[Depends(get_current_payroll_operator)],
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
    dependencies=[Depends(get_current_payroll_operator)],
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
    dependencies=[Depends(get_current_payroll_operator)],
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
    dependencies=[Depends(get_current_payroll_operator)],
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
    dependencies=[Depends(get_current_payroll_operator)],
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
    dependencies=[Depends(get_current_payroll_operator)],
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