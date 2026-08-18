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
from app.core.dependencies import (
    get_current_user, get_current_payroll_operator, get_current_super_admin, require_active_subscription,
)
from app.core.exceptions import ForbiddenException
from app.modules.payroll import service
from app.modules.payroll.policy import policy_router
from app.modules.payroll.enterprise import enterprise_router
from app.modules.payroll.mail import mail_router
from app.modules.payroll.forms import forms_router
# Registration-only import — no router yet (data model + resolver phase
# only; the API surface lands in a later phase). Ensures the new
# hierarchy tables are picked up by create_all/sync_schema.
import app.modules.payroll.hierarchy  # noqa: F401
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
    HolidayCreate, BulkHolidayRequest, HolidayResponse,
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
    return service.update_employee(db, employee_id, data, current_user.organization_id)


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
    current_user=Depends(get_current_user),
):
    return service.get_compliance_data(db, current_user.organization_id)


@payroll_router.get(
    "/compliance/contribution-rates", response_model=List[ContributionRateResponse], response_model_by_alias=True,
    summary="Get statutory contribution rates",
)
def get_contribution_rates(
    country: str = Query("IN", description="Jurisdiction country code (IN, US, UK, …)"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_contribution_rates(db, current_user.organization_id, country)


@payroll_router.get(
    "/compliance/tax-slabs", response_model=List[TaxSlabResponse], response_model_by_alias=True,
    summary="Get income tax slabs",
)
def get_tax_slabs(
    country: str = Query("IN", description="Jurisdiction country code (IN, US, UK, …)"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_tax_slabs(db, current_user.organization_id, country)


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
    upload_dir = service._COMPLIANCE_DOC_UPLOAD_DIR
    os.makedirs(upload_dir, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1]
    unique_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(upload_dir, unique_name)
    contents = await file.read()
    with open(file_path, "wb") as fh:
        fh.write(contents)

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