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
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import io

from app.database import get_db
from app.core import object_storage
from app.core.dependencies import (
    get_current_user, get_current_payroll_operator, get_current_super_admin, get_organization_id,
)
from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
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
    SwedenLeaveLedgerResponse, SwedenLeaveLedgerUpsert, SwedenSickEpisodeResponse, SwedenSickEpisodeUpsert,
    IrelandRpnSnapshotUpsert, IrelandRpnSnapshotResponse,
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
    AttendancePageResponse, EmployeeAttendanceSummaryPageResponse,
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
    HongKongBir56aGenerateRequest, HongKongIr56bGenerateRequest,
    HongKongIr56NotificationGenerateRequest, HongKongEmpfRemittanceGenerateRequest,
    HongKongMpfContributionRecordGenerateRequest, HongKongTerminationStatementGenerateRequest,
    AUSuperstreamGenerateRequest, AUPayrollTaxReturnGenerateRequest,
    NewHireReportCreate, NewHireReportMarkFiledRequest, NewHireReportResponse,
    SalaryTdsDeclarationCreate, SalaryTdsDeclarationResponse,
    PRWithholdingCertificateCreate, PRWithholdingCertificateResponse,
    PRAccrueMonthlyLeaveRequest,
    PRAccrueBonusYearRequest, PRBonusYearTotalsResponse,
    PRChristmasBonusCalculateRequest, PRChristmasBonusCalculateResponse,
    SalaryTdsClaimCreate, SalaryTdsClaimResponse, SalaryTdsClaimRejectRequest,
    EmployeeBenefitValuationCreate, EmployeeBenefitValuationResponse,
    UKEmployeeReportGenerateRequest, UKEpsGenerateRequest,
    CAPd7aGenerateRequest,
    GYMonthlyReportGenerateRequest,
    JMAnnualReportGenerateRequest,
    SGAnnualReportGenerateRequest,
    SGIr21CaseCreateRequest,
    SGIr21CaseTransitionRequest,
    SGCpfEzpayGenerateRequest,
    SGCessationRequest,
    SGRestoreFreezeRequest,
    SGBankHoldReleaseRequest,
    SGCorrectionRequest,
    SGSalaryDeductionCreate,
    SGCpfEzpayTransitionRequest,
    SGIr8aModificationCreateRequest,
    CASpecialPaymentCalculateRequest, CASpecialPaymentCalculateResponse,
    AUSchedule5CalculateRequest, AUSchedule5CalculateResponse,
    AUSchedule4CalculateRequest, AUSchedule4CalculateResponse,
    USSupplementalWageCalculateRequest, USSupplementalWageCalculateResponse,
    USFederalDepositScheduleRequest, USFederalDepositScheduleResponse,
    PRDepositScheduleRequest, PRDepositScheduleResponse,
    CARetiringAllowanceCalculateRequest, CARetiringAllowanceCalculateResponse,
    CATd1xCommissionCalculateRequest, CATd1xCommissionCalculateResponse,
    CAWsdrfCalculateRequest, CAWsdrfCalculateResponse,
    RtiSubmissionCreate, RtiSubmissionStatusUpdate, RtiSubmissionResponse,
    HolidayCreate, BulkHolidayRequest, HolidayResponse,
    ApplicableTemplateResponse, GenerateReportRequest, GeneratedReportResponse, VoidGeneratedReportRequest,
    FilingCalendarResponse,
    EmployerFranceProfileUpsert, FranceEstablishmentRatePackUpsert,
    FrancePASRateUpsert, FranceEffectifRecord,
    FranceDsnSubmissionCreate, FranceDsnStatusUpdate, FranceDsnOutboxCreate,
    FranceDsnSubmissionResponse, FranceDsnOutboxItemResponse,
    ItalyEmployerProfileUpsert, ItalyEmployerProfileResponse,
    ItalyFilingOutboxCreate, ItalyFilingOutboxItemResponse,
    ItalyF24CausaleUpsert, ItalyF24CausaleResponse,
    ItalyF24BuildRequest, ItalyF24LineResponse,
    ItalyLulBuildRequest, ItalyLulCorrectionRequest, ItalyLulEntryResponse,
    ItalyLulIntegrityResponse,
    ItalyTfrAccrualRequest, ItalyTfrRevaluationRequest, ItalyTfrLedgerEntryResponse,
    ItalyTfrBalanceResponse, ItalyTfrIdempotencyResponse,
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
    employees = service.get_employees(
        db, current_user.organization_id,
        search=search, department=department, status=status,
        limit=limit, offset=offset,
    )
    service.audit_sg_shg_read(db, current_user.organization_id, current_user.id, employees)   # Singapore SHG data only
    return employees


@payroll_router.get(
    "/employees/roster",
    response_model=List[dict],
    response_model_by_alias=True,
    summary="Lightweight employee roster for attendance/leave (id, name, code, department, designation)",
)
def list_employee_roster(
    status: Optional[str] = Query(None),
    limit: Optional[int] = Query(None, ge=1, le=5000),
    offset: Optional[int] = Query(None, ge=0),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_employee_roster(
        db, current_user.organization_id,
        status=status, limit=limit, offset=offset,
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
    employee = service.get_employee_by_id(db, employee_id, current_user.organization_id)
    service.audit_sg_shg_read(db, current_user.organization_id, current_user.id, employee)    # Singapore SHG data only
    return employee


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
    result = service.bulk_create_employees(db, data, current_user.organization_id, actor_id=current_user.id)
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
    result = service.bulk_update_employees(db, data, current_user.organization_id, actor_id=current_user.id)
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
    result = service.bulk_delete_employees(db, data, current_user.organization_id, actor_id=current_user.id)
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
    request: Request,
    as_of: Optional[date] = Query(None, description="Resolve the profile applicable on this date; defaults to today."),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = service.get_employee_statutory_profile_as_of(db, employee_id, current_user.organization_id, as_of)
    _log_hk_profile_view(db, current_user, employee_id, profile, request)
    return profile


def _log_hk_profile_view(db, current_user, employee_id, profile, request) -> None:
    """D-19: views of a HONG KONG statutory profile are access-logged; every
    other country's profile read is untouched."""
    if profile is None:
        return
    rows = profile if isinstance(profile, list) else [profile]
    if any((getattr(p, "country_code", None) or "").upper() == "HK" for p in rows):
        from app.modules.payroll import hk_privacy

        hk_privacy.record_access(db, current_user.organization_id, current_user.id, "VIEW_STATUTORY_PROFILE",
                                 "employee_statutory_profile", resource_id=getattr(rows[0], "id", None),
                                 employee_id=employee_id, request=request)


@payroll_router.get(
    "/employees/{employee_id}/statutory-profile/history", response_model=List[EmployeeStatutoryProfileResponse],
    response_model_by_alias=True, summary="List every effective-dated statutory profile version for an employee",
)
def get_employee_statutory_profile_history(
    employee_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    history = service.list_employee_statutory_profile_history(db, employee_id, current_user.organization_id)
    _log_hk_profile_view(db, current_user, employee_id, history, request)
    return history


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


# ── Sweden sick-pay episodes and annual-leave ledgers (ZP-SE-ENG-001 §7/§8)
# Tenant-owned statutory facts — same security tier as the statutory-profile
# endpoints above. Days/deduction state only; no clinical content is accepted.

@payroll_router.get(
    "/sweden/sick-episodes", response_model=List[SwedenSickEpisodeResponse], response_model_by_alias=True,
    summary="List Swedish sick-pay episodes (days 1–14 employer period, qualifying deduction state)",
)
def list_sweden_sick_episodes(
    employee_id: Optional[int] = Query(None, alias="employeeId"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_se_sick_episodes(db, current_user.organization_id, employee_id)


@payroll_router.post(
    "/sweden/sick-episodes", response_model=SwedenSickEpisodeResponse, response_model_by_alias=True,
    summary="Record a Swedish sick-pay episode — recurrence, day 1–14 period and qualifying deduction resolved",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def upsert_sweden_sick_episode(
    data: SwedenSickEpisodeUpsert,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.upsert_se_sick_episode(db, current_user.organization_id, data, current_user.id)


@payroll_router.get(
    "/sweden/leave-ledgers", response_model=List[SwedenLeaveLedgerResponse], response_model_by_alias=True,
    summary="List Swedish annual-leave ledgers (entitlement, paid/unpaid/saved days — separate from money)",
)
def list_sweden_leave_ledgers(
    employee_id: Optional[int] = Query(None, alias="employeeId"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_se_leave_ledgers(db, current_user.organization_id, employee_id)


@payroll_router.post(
    "/sweden/leave-ledgers", response_model=SwedenLeaveLedgerResponse, response_model_by_alias=True,
    summary="Record a Swedish annual-leave ledger row for one entitlement year",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def upsert_sweden_leave_ledger(
    data: SwedenLeaveLedgerUpsert,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.upsert_se_leave_ledger(db, current_user.organization_id, data, current_user.id)


# ── Ireland RPN snapshots (ZP-IE-ENG-001 §5, IE-005/IE-022/IE-033/IE-045) ──
# Fact capture only. The Revenue document is frozen here and READ by the engine;
# the server never calls Revenue on the calculator's behalf (IE-022), so this
# endpoint is how a snapshot gets in. Content-addressed by raw_hash: re-posting
# the identical authority response returns the same row rather than duplicating
# history, while a genuine re-issue adds an immutable row.

@payroll_router.get(
    "/ireland/rpn-snapshots", response_model=List[IrelandRpnSnapshotResponse], response_model_by_alias=True,
    summary="List frozen Revenue Payroll Notification snapshots (audit history, newest authority issue first)",
)
def list_ireland_rpn_snapshots(
    employee_id: Optional[int] = Query(None, alias="employeeId"),
    tax_year: Optional[str] = Query(None, alias="taxYear"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_ie_rpn_snapshots(
        db, current_user.organization_id, employee_id, tax_year)


@payroll_router.post(
    "/ireland/rpn-snapshots", response_model=IrelandRpnSnapshotResponse, response_model_by_alias=True,
    summary="Ingest a frozen Revenue Payroll Notification — same raw_hash returns the existing snapshot",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def upsert_ireland_rpn_snapshot(
    data: IrelandRpnSnapshotUpsert,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.record_ie_rpn_snapshot(db, current_user.organization_id, data)


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
    "/runs/{run_id}/generate-payslips", response_model=PayrollRunResponse, response_model_by_alias=True,
    summary="Generate or recalculate payslips for a draft payroll run",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def generate_run_payslips(
    run_id: int,
    async_dispatch: bool = Query(False, description="Dispatch asynchronously via Celery chord if configured"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Phase 2.1: Generate payslips for a run with optional async chord dispatch."""
    from fastapi.responses import JSONResponse
    from app.config import settings
    from app.modules.payroll.models import PayrollStatus

    run = service.get_payroll_run_by_id(db, run_id, current_user.organization_id)
    if run.status != PayrollStatus.DRAFT.value:
        raise BadRequestException(f"Payslips can only be generated for DRAFT runs (current status: {run.status})")

    if async_dispatch and settings.REDIS_URL:
        from app.tasks.payroll_tasks import generate_payslips_for_run_task
        task = generate_payslips_for_run_task.delay(run_id, current_user.organization_id)
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "taskId": task.id,
                "runId": run_id,
                "status": "QUEUED",
                "message": "Payslip generation queued in background via Celery chord.",
            },
        )

    # Synchronous execution (default or fallback)
    service.generate_payslips_for_run(db, run, current_user.organization_id)
    return service.get_payroll_run_detail(db, run_id, current_user.organization_id)


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
    "/pr/deposit-schedule/calculate", response_model=PRDepositScheduleResponse, response_model_by_alias=True,
    summary="Calculate Puerto Rico Hacienda deposit category (Quarterly Exception/Monthly/Semiweekly), deposit due date, "
            "$100,000 next-day rule, and Form 499R-2 deadline (PR-011)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def calculate_pr_deposit_schedule(
    data: PRDepositScheduleRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.calculate_pr_deposit_schedule(
        db, current_user.organization_id, data.lookback_period_liability, data.current_quarter_withholding,
        data.payroll_date, accumulated_undeposited_liability=data.accumulated_undeposited_liability,
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


# ── Puerto Rico: Form 499 R-4/R-4.1 withholding certificate (PR-005) ────

@payroll_router.post(
    "/pr/withholding-certificates", response_model=PRWithholdingCertificateResponse, response_model_by_alias=True,
    summary="Create a Form 499 R-4/R-4.1 Puerto Rico withholding certificate (Draft)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def create_pr_withholding_certificate(
    data: PRWithholdingCertificateCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.create_pr_withholding_certificate(
        db, current_user.organization_id, data.employee_id,
        personal_exemption_amount=data.personal_exemption_amount, dependents_count=data.dependents_count,
        dependent_exemption_per_dependent=data.dependent_exemption_per_dependent,
        deduction_allowance_amount=data.deduction_allowance_amount,
        optional_married_computation=data.optional_married_computation, msrra_election=data.msrra_election,
        additional_withholding_amount=data.additional_withholding_amount,
    )


@payroll_router.get(
    "/pr/withholding-certificates", response_model=List[PRWithholdingCertificateResponse], response_model_by_alias=True,
    summary="List Form 499 R-4/R-4.1 Puerto Rico withholding certificates",
)
def list_pr_withholding_certificates(
    employeeId: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_pr_withholding_certificates(db, current_user.organization_id, employee_id=employeeId)


@payroll_router.put(
    "/pr/withholding-certificates/{certificate_id}/submit", response_model=PRWithholdingCertificateResponse, response_model_by_alias=True,
    summary="Submit a Form 499 R-4/R-4.1 certificate (Draft -> Submitted)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def submit_pr_withholding_certificate(
    certificate_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.submit_pr_withholding_certificate(db, current_user.organization_id, certificate_id)


@payroll_router.put(
    "/pr/withholding-certificates/{certificate_id}/approve", response_model=PRWithholdingCertificateResponse, response_model_by_alias=True,
    summary="Approve a Form 499 R-4/R-4.1 certificate (Submitted -> Approved) — supersedes any prior Approved certificate for this employee",
    dependencies=[Depends(get_current_payroll_operator)],
)
def approve_pr_withholding_certificate(
    certificate_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.approve_pr_withholding_certificate(db, current_user.organization_id, certificate_id, current_user.id)


@payroll_router.post(
    "/pr/leave/accrue-monthly", response_model=LeaveAllocationResponse, response_model_by_alias=True,
    summary="Accrue one month of Puerto Rico vacation (Act 4-2017/Law 180) + sick leave (PR-028/PR-029) into the "
            "employee's existing leave balances",
    dependencies=[Depends(get_current_payroll_operator)],
)
def accrue_pr_monthly_leave(
    data: PRAccrueMonthlyLeaveRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.accrue_pr_monthly_leave(
        db, current_user.organization_id, data.employee_id,
        hired_before_2017=data.hired_before_2017, years_of_service=data.years_of_service,
        qualifying_small_employer=data.qualifying_small_employer,
        qualifying_hours_in_month=data.qualifying_hours_in_month, period_label=data.period_label,
    )


@payroll_router.post(
    "/pr/christmas-bonus/accrue", response_model=PRBonusYearTotalsResponse, response_model_by_alias=True,
    summary="Add one pay period's wages/hours to an employee's Puerto Rico Christmas Bonus bonus-year (Oct 1-Sep 30) totals (PR-032)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def accrue_pr_bonus_year_totals(
    data: PRAccrueBonusYearRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.accrue_pr_bonus_year_totals(
        db, current_user.organization_id, data.employee_id, data.as_of_date,
        data.wages_this_period, data.hours_this_period,
    )


@payroll_router.post(
    "/pr/christmas-bonus/calculate", response_model=PRChristmasBonusCalculateResponse, response_model_by_alias=True,
    summary="Calculate an employee's Puerto Rico Christmas Bonus (Act 148) from their real accrued bonus-year totals",
    dependencies=[Depends(get_current_payroll_operator)],
)
def calculate_pr_christmas_bonus(
    data: PRChristmasBonusCalculateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.calculate_pr_christmas_bonus_from_accumulator(
        db, current_user.organization_id, data.employee_id, data.as_of_date,
        hired_before_2017=data.hired_before_2017, employer_size_over_threshold=data.employer_size_over_threshold,
        is_first_year=data.is_first_year,
    )


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
    request: Request,
    format: Optional[str] = Query(None, description="csv | xlsx | txt | pdf — defaults to the Banking Policy format"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    file_bytes, content_type, _ext, filename = service.generate_bank_transfer_file(
        db, run_id, current_user.organization_id, actor_id=current_user.id, format_override=format,
    )
    from app.modules.payroll import hk_privacy

    hk_privacy.log_payslip_access(db, current_user.organization_id, current_user.id,
                                  [i.id for i in service.get_payslips_for_run(db, run_id, current_user.organization_id)],
                                  "DOWNLOAD_BANK_FILE", request=request, run_id=run_id)          # HK only
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
    request: Request,
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
    from app.modules.payroll import hk_privacy

    hk_privacy.log_payslip_access(db, current_user.organization_id, current_user.id, [i.id for i in items],
                                  "DOWNLOAD_PAYSLIPS_ZIP", request=request, run_id=run_id)       # HK only

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
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    pdf_bytes = service.generate_payslip_pdf_bytes(db, payslip_id, current_user.organization_id)
    from app.modules.payroll import hk_privacy

    hk_privacy.log_payslip_access(db, current_user.organization_id, current_user.id, [payslip_id],
                                  "DOWNLOAD_PAYSLIP", request=request)                            # HK only
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
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_attendance_records(
        db, current_user.organization_id,
        start_date=startDate, end_date=endDate, employee_id=employeeId,
        limit=limit, offset=offset,
    )


@payroll_router.get(
    "/attendance/page", response_model=AttendancePageResponse,
    response_model_by_alias=True,
    summary="Page through attendance records with an exact total",
)
def list_attendance_page(
    startDate: Optional[date] = Query(None),
    endDate: Optional[date] = Query(None),
    employeeId: Optional[int] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_attendance_records_page(
        db, current_user.organization_id,
        start_date=startDate, end_date=endDate, employee_id=employeeId,
        limit=limit, offset=offset,
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


@payroll_router.get(
    "/attendance/summary/by-employee",
    response_model=EmployeeAttendanceSummaryPageResponse,
    response_model_by_alias=True,
    summary="Paged per-employee attendance aggregates for a date range",
)
def attendance_summary_by_employee(
    startDate: Optional[date] = Query(None),
    endDate: Optional[date] = Query(None),
    search: Optional[str] = Query(None, max_length=200),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Replaces the Summary tab's client-side aggregation, which had to fetch
    every attendance row in the range just to count days per employee."""
    return service.get_attendance_summary_by_employee(
        db, current_user.organization_id,
        start_date=startDate, end_date=endDate,
        search=search, limit=limit, offset=offset,
    )


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
    # The payload's own packType is not enough: a "policy" payload carrying an
    # existing TAX pack's id (or packId/version) would otherwise edit that
    # platform-wide statutory pack from an organization account.
    target = service.find_jurisdiction_pack_upsert_target(db, payload)
    if target is not None and target.pack_type == "tax" and (current_user.role or "").lower() != "super_admin":
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
    try:
        report = service.generate_report_from_template(
            db, current_user.organization_id, payload.reportTemplateId, payload.payrollRunId,
            reporting_period=payload.reportingPeriod, actor_id=current_user.id,
        )
    except Exception as exc:
        # Report-failed notification (best-effort; never masks the real error).
        try:
            report_label = "Report"
            try:
                _tpl = service.get_report_template(db, payload.reportTemplateId)
                report_label = _tpl.report_type or "Report"
            except Exception:
                pass
            service._notify_report_generation_failed(
                db, current_user.organization_id, report_label,
                payload.reportingPeriod or "", str(exc),
            )
        except Exception:
            pass
        raise
    # Report-ready notification (best-effort).
    try:
        service._notify_report_generated(db, report, current_user.organization_id)
    except Exception:
        pass
    return report


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
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    report = service.get_generated_report(db, current_user.organization_id, generated_report_id)
    from app.modules.payroll import hk_privacy

    hk_privacy.log_report_download(db, current_user.organization_id, current_user.id, generated_report_id,
                                   "VIEW_REPORT", request=request)                                  # HK only
    return report


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
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    pdf_bytes = service.generate_report_certificate_pdf_bytes(db, current_user.organization_id, generated_report_id, employee_id)
    from app.modules.payroll import hk_privacy

    hk_privacy.log_report_download(db, current_user.organization_id, current_user.id, generated_report_id,
                                   "DOWNLOAD_CERTIFICATE", employee_id=employee_id, request=request)   # HK only
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
    request: Request,
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
    from app.modules.payroll import hk_privacy

    hk_privacy.log_report_download(db, current_user.organization_id, current_user.id, generated_report_id,
                                   "DOWNLOAD_CERTIFICATES_ZIP", request=request)                    # HK only

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


# ── Hong Kong: IRD reporting and MPF records (ZP-HK-ENG-001 §7, §5, HK-011,
# HK-010). Shaped exactly like /us/reports/* — an Active ReportTemplate, a
# shared GeneratedReport output, employee certificate PDF for the per-employee
# forms via the shared /generated-reports/{id}/certificate/{employee_id}
# route. The HK statutory case/submission tables remain the filing trackers.


@payroll_router.post(
    "/hong-kong/reports/bir56a", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a Hong Kong BIR56A annual employer's return for a year of assessment",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_hong_kong_bir56a(
    data: HongKongBir56aGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_hong_kong_bir56a(
        db, current_user.organization_id, data.report_template_id, data.year_of_assessment,
        actor_id=current_user.id,
    )


@payroll_router.post(
    "/hong-kong/reports/ir56b", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a Hong Kong IR56B per-employee annual return (also the employee's copy)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_hong_kong_ir56b(
    data: HongKongIr56bGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_hong_kong_ir56b(
        db, current_user.organization_id, data.report_template_id, data.employee_id, data.year_of_assessment,
        actor_id=current_user.id,
    )


@payroll_router.post(
    "/hong-kong/reports/ir56-notification", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a Hong Kong IR56E / IR56F / IR56G employee notification from its reporting case",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_hong_kong_ir56_notification(
    data: HongKongIr56NotificationGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_hong_kong_ir56_notification(
        db, current_user.organization_id, data.report_template_id, data.case_id,
        actor_id=current_user.id,
    )


@payroll_router.post(
    "/hong-kong/reports/empf-remittance", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a Hong Kong eMPF remittance statement for a prepared contribution-period submission",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_hong_kong_empf_remittance(
    data: HongKongEmpfRemittanceGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_hong_kong_empf_remittance(
        db, current_user.organization_id, data.report_template_id, data.submission_id,
        actor_id=current_user.id,
    )


@payroll_router.post(
    "/hong-kong/reports/mpf-contribution-record", response_model=GeneratedReportResponse,
    response_model_by_alias=True,
    summary="Generate an employee's Hong Kong MPF contribution record for one contribution period (HK-010)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_hong_kong_mpf_contribution_record(
    data: HongKongMpfContributionRecordGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_hong_kong_mpf_contribution_record(
        db, current_user.organization_id, data.report_template_id, data.employee_id,
        data.contribution_period, actor_id=current_user.id,
    )


@payroll_router.post(
    "/hong-kong/reports/termination-statement", response_model=GeneratedReportResponse,
    response_model_by_alias=True,
    summary="Generate the employee's Hong Kong termination statement from an APPROVED termination calculation",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_hong_kong_termination_statement(
    data: HongKongTerminationStatementGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_hong_kong_termination_statement(
        db, current_user.organization_id, data.report_template_id, data.termination_result_id,
        actor_id=current_user.id,
    )




# ── Puerto Rico: Form 499 R-1B + federal-equivalent 941/940 (ZP-PR-ENG-001
# §10) ────────────────────────────────────────────────────────────────
# Reuses the SAME generic request schemas as the US 941/940 endpoints
# above (report_template_id/year[/quarter] — no country-specific fields),
# but routes to PR's own independently-computed service functions, never
# service.generate_us_941/generate_us_940.

@payroll_router.post(
    "/pr/reports/499r1b", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a Puerto Rico Form 499 R-1B (quarterly Hacienda withholding return) for one calendar quarter",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_pr_499r1b(
    data: USForm941GenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_pr_499r1b(
        db, current_user.organization_id, data.report_template_id, data.year, data.quarter,
        actor_id=current_user.id,
    )


@payroll_router.post(
    "/pr/reports/941", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a federal Form 941 for a Puerto Rico employer (FICA on PR wages) for one IRS calendar quarter",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_pr_941(
    data: USForm941GenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_pr_941(
        db, current_user.organization_id, data.report_template_id, data.year, data.quarter,
        actor_id=current_user.id,
    )


@payroll_router.post(
    "/pr/reports/940", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a federal Form 940 (FUTA-equivalent) for a Puerto Rico employer for one calendar year",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_pr_940(
    data: USForm940GenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_pr_940(
        db, current_user.organization_id, data.report_template_id, data.year,
        actor_id=current_user.id,
    )


@payroll_router.post(
    "/pr/reports/w2pr", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a Puerto Rico Form 499R-2/W-2PR (annual employee withholding statement) for one calendar tax year",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_pr_w2pr(
    data: USW2GenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_pr_w2pr(
        db, current_user.organization_id, data.report_template_id, data.employee_id, data.tax_year,
        actor_id=current_user.id,
    )


@payroll_router.post(
    "/pr/reports/dtrh-quarterly", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate the Puerto Rico DTRH quarterly wage/contribution return for one calendar quarter",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_pr_dtrh_quarterly(
    data: USForm941GenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_pr_dtrh_quarterly(
        db, current_user.organization_id, data.report_template_id, data.year, data.quarter,
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


# Germany Lohnsteuerbescheinigung — same generic per-employee, non-run-
# based engine as UK P60/India Form 130/Canada T4/RL1/ROE above (see
# service.generate_uk_employee_report's own docstring: never actually
# UK-specific, just gated to a report_type allow-list).

@payroll_router.post(
    "/germany/reports/lohnsteuerbescheinigung", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a Germany Lohnsteuerbescheinigung (annual wage tax certificate) for one employee — not tied to any single PayrollRun",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_de_lstb(
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


# ── Singapore: IR8A annual employment-income data extract (EXPORT_READY only)

@payroll_router.post(
    "/singapore/reports/ir8a", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a Singapore IR8A data extract for one income year — EXPORT_READY only, never submitted to IRAS",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_sg_ir8a(
    data: SGAnnualReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_sg_ir8a(
        db, current_user.organization_id, data.report_template_id, data.year,
        actor_id=current_user.id,
    )


@payroll_router.post(
    "/singapore/reports/sdl", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate the Singapore monthly SDL payable — employer total of per-employee SDL, rounded down to the dollar",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_sg_sdl_monthly(
    data: GYMonthlyReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_sg_sdl_monthly(
        db, current_user.organization_id, data.report_template_id, data.year, data.month,
        actor_id=current_user.id,
    )


# Singapore Phase 5.7 — internal compliance reports from the existing
# evaluators (PWM check, engine LQS trace, IR21 case lifecycle). Own
# organization only; payroll operators only; not MOM / IRAS submissions.
@payroll_router.post(
    "/singapore/reports/pwm-compliance", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate the Singapore PWM compliance report for a CPF wage month (internal — not an MOM submission)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_sg_pwm_compliance(
    data: GYMonthlyReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_sg_pwm_compliance(
        db, current_user.organization_id, data.report_template_id, data.year, data.month, actor_id=current_user.id,
    )


@payroll_router.post(
    "/singapore/reports/lqs-compliance", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate the Singapore LQS compliance report for a CPF wage month (internal — not an MOM submission)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_sg_lqs_compliance(
    data: GYMonthlyReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_sg_lqs_compliance(
        db, current_user.organization_id, data.report_template_id, data.year, data.month, actor_id=current_user.id,
    )


@payroll_router.post(
    "/singapore/reports/ir21-register", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate the Singapore IR21 tax-clearance register for a year (internal — not an IRAS filing)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_sg_ir21_register(
    data: JMAnnualReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_sg_ir21_register(
        db, current_user.organization_id, data.report_template_id, data.year, actor_id=current_user.id,
    )


# ── Singapore: CPF EZPay contribution file — prepared here, submitted by the
# employer through CPF EZPay (Corppass). Own organization only; payroll
# operators only; the file itself (full CPF account numbers) only after a
# distinct approver has approved it, and every download is audited.

@payroll_router.post(
    "/singapore/reports/cpf-ezpay", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Prepare the Singapore CPF EZPay (FTP) contribution file for a wage month (status PREPARED)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_sg_cpf_ezpay(
    data: SGCpfEzpayGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_sg_cpf_ezpay(
        db, current_user.organization_id, data.report_template_id, data.year, data.month,
        advice_code=data.advice_code, actor_id=current_user.id,
    )


@payroll_router.get(
    "/singapore/reports/ir8a",
    summary="List the Singapore IR8A extracts with their controlled manual-submission status (SG-023)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def list_sg_ir8a(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_sg_ir8a(db, current_user.organization_id)


@payroll_router.post(
    "/singapore/reports/ir8a/{report_id}/transition",
    summary="Record the manual IR8A submission / IRAS outcome (SUBMITTED_MANUALLY / ACKNOWLEDGED / REJECTED / UNKNOWN)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def transition_sg_ir8a(
    report_id: int,
    data: SGCpfEzpayTransitionRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.transition_sg_ir8a(db, current_user.organization_id, report_id, data.status,
                                      actor_id=current_user.id, reference=data.reference, note=data.note,
                                      errors=data.errors)


# Phase 6.8 (G3): IR8A Revision / Amendment of an IRAS-acknowledged extract —
# own organization only; payroll operators only; filed through the transition
# route above like any IR8A extract.
@payroll_router.post(
    "/singapore/reports/ir8a/{report_id}/modifications",
    summary="Prepare an IR8A Revision (full values) or Amendment (differences) of an IRAS-acknowledged extract",
    dependencies=[Depends(get_current_payroll_operator)],
)
def create_sg_ir8a_modification(
    report_id: int,
    data: SGIr8aModificationCreateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.create_sg_ir8a_modification(db, current_user.organization_id, report_id, data.method,
                                               reason=data.reason, actor_id=current_user.id)


@payroll_router.get(
    "/singapore/reports/ir8a/{report_id}/modifications",
    summary="List the Revisions / Amendments of an IR8A extract",
    dependencies=[Depends(get_current_payroll_operator)],
)
def list_sg_ir8a_modifications(
    report_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_sg_ir8a_modifications(db, current_user.organization_id, report_id)


@payroll_router.post(
    "/singapore/reports/cpf-ezpay/{report_id}/transition", response_model=GeneratedReportResponse,
    response_model_by_alias=True,
    summary="Advance a CPF EZPay submission (APPROVED / SUBMITTED / ACCEPTED / REJECTED / UNKNOWN)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def transition_sg_cpf_ezpay(
    report_id: int,
    data: SGCpfEzpayTransitionRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.transition_sg_cpf_ezpay(
        db, current_user.organization_id, report_id, data.status, actor_id=current_user.id,
        reference=data.reference, note=data.note, errors=data.errors,
    )


@payroll_router.get(
    "/singapore/reports/cpf-ezpay/{report_id}/file",
    summary="Download an APPROVED CPF EZPay file (audited — contains full CPF account numbers)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def download_sg_cpf_ezpay_file(
    report_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    filename, content = service.get_sg_cpf_ezpay_file(db, current_user.organization_id, report_id, actor_id=current_user.id)
    return StreamingResponse(
        io.BytesIO(content.encode("ascii")),
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


# ── Singapore: payroll-run preflight / exceptions (§11 stages 1 and 4) —
# read-only; BLOCK items refuse approval (enforced in advance_payroll_run_status).

@payroll_router.get(
    "/singapore/runs/{run_id}/preflight",
    summary="Singapore preflight + exceptions for a payroll run (read-only dry run of the engine)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def get_sg_payroll_preflight(
    run_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.sg_payroll_preflight(db, current_user.organization_id, run_id)


@payroll_router.get(
    "/hong-kong/runs/{run_id}/preflight",
    summary="Hong Kong preflight + exceptions for a payroll run (read-only dry run of the engine)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def get_hk_payroll_preflight(
    run_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.hk_payroll_preflight(db, current_user.organization_id, run_id)


@payroll_router.get(
    "/hong-kong/readiness",
    summary="Hong Kong payroll readiness dashboard (employer registrations, pack, worker facts, IRD, eMPF) — read-only",
    dependencies=[Depends(get_current_payroll_operator)],
)
def get_hk_employer_readiness(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return service.hk_employer_readiness(db, current_user.organization_id)


@payroll_router.post(
    "/singapore/employees/{employee_id}/cessation",
    summary="Record a Singapore employee's cessation — a non-citizen's monies go on IR21 hold automatically",
    dependencies=[Depends(get_current_payroll_operator)],
)
def record_sg_cessation(
    employee_id: int,
    data: SGCessationRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.record_sg_cessation(db, current_user.organization_id, employee_id, data.date_of_leaving,
                                       actor_id=current_user.id)


@payroll_router.get(
    "/singapore/pwm-classifications",
    summary="Progressive Wage Model sector / group / job-level choices with the floor in force (Active SG pack)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def list_sg_pwm_classifications(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_sg_pwm_classifications(db)


@payroll_router.post(
    "/singapore/benefit-valuations", response_model=EmployeeBenefitValuationResponse, response_model_by_alias=True,
    summary="Record a Singapore IR8A Appendix 8A benefit value (the organization's own valuation; Draft)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def create_sg_benefit_valuation(
    data: EmployeeBenefitValuationCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.create_sg_benefit_valuation(db, current_user.organization_id, data.employee_id, data.tax_year,
                                               data.benefit_type, data.taxable_value, description=data.description)


@payroll_router.get(
    "/singapore/benefit-valuations", response_model=List[EmployeeBenefitValuationResponse], response_model_by_alias=True,
    summary="List Singapore Appendix 8A benefit valuations",
    dependencies=[Depends(get_current_payroll_operator)],
)
def list_sg_benefit_valuations(
    taxYear: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_sg_benefit_valuations(db, current_user.organization_id, tax_year=taxYear)


@payroll_router.get(
    "/singapore/ais-readiness",
    summary="Singapore AIS year-end readiness — running data-quality metric (SG-042)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def get_sg_ais_readiness(
    year: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.sg_ais_readiness(db, current_user.organization_id, year)


@payroll_router.get(
    "/singapore/compliance-centre",
    summary="Singapore Compliance Centre — status / effective date / evidence / blocker / owner / action per area, plus clocks",
    dependencies=[Depends(get_current_payroll_operator)],
)
def get_sg_compliance_centre(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_sg_compliance_centre(db, current_user.organization_id)


@payroll_router.post(
    "/singapore/employees/{employee_id}/deductions", response_model=UKCourtOrderResponse, response_model_by_alias=True,
    summary="Record a Singapore Employment Act salary deduction (MOM category, consent / evidence, caps enforced)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def create_sg_salary_deduction(
    employee_id: int,
    data: SGSalaryDeductionCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.create_sg_salary_deduction(
        db, current_user.organization_id, employee_id, data.category, data.start_date, evidence_ref=data.evidence_ref,
        evidence_date=data.evidence_date, end_date=data.end_date, amount=data.amount, rate_pct=data.rate_pct,
        total_to_collect=data.total_to_collect, priority=data.priority, created_by_id=current_user.id,
    )


@payroll_router.get(
    "/singapore/employees/{employee_id}/deductions", response_model=list[UKCourtOrderResponse], response_model_by_alias=True,
    summary="List a Singapore employee's salary deductions",
    dependencies=[Depends(get_current_payroll_operator)],
)
def list_sg_salary_deductions(
    employee_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return [o for o in service.list_court_ordered_deductions(db, current_user.organization_id, employee_id)
            if o.jurisdiction == service.SG_DEDUCTION_JURISDICTION]


@payroll_router.post(
    "/singapore/payslips/{payslip_id}/corrections",
    summary="Append-only correction of a finalized Singapore payslip — a linked delta payslip, the original is never changed",
    dependencies=[Depends(get_current_payroll_operator)],
)
def correct_sg_finalized_payslip(
    payslip_id: int,
    data: SGCorrectionRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.correct_sg_finalized_payslip(db, current_user.organization_id, payslip_id, data.reason,
                                                actor_id=current_user.id)


@payroll_router.get(
    "/singapore/payslips/{payslip_id}/corrections",
    summary="The correction chain of a Singapore payslip (before / after / delta, reason, actor, time)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def list_sg_payslip_corrections(
    payslip_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_sg_payslip_corrections(db, current_user.organization_id, payslip_id)


@payroll_router.post(
    "/singapore/disaster-recovery/freeze",
    summary="SG-047: after a restore, freeze every CPF EZPay submission with an uncertain external outcome (UNKNOWN)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def sg_freeze_after_restore(
    data: SGRestoreFreezeRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.sg_freeze_after_restore(db, current_user.organization_id, data.restore_point, actor_id=current_user.id,
                                           restore_date=data.restore_date)


@payroll_router.post(
    "/singapore/disaster-recovery/bank-hold/{run_id}/release",
    summary="SG-047: record the bank reconciliation that releases a post-restore bank-export hold (audited)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def release_sg_bank_export_hold(
    run_id: int,
    data: SGBankHoldReleaseRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.release_sg_bank_export_hold(db, current_user.organization_id, run_id, data.reference,
                                               actor_id=current_user.id)


@payroll_router.get(
    "/singapore/retention-report",
    summary="SG-046: read-only record-retention report against the MOM / IRAS statutory minimums (never deletes)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def sg_retention_report(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.sg_retention_report(db, current_user.organization_id)


# ── Singapore: Employer Registration readiness (SG-027) — own organization only.

@payroll_router.get(
    "/singapore/readiness",
    summary="Singapore employer launch-readiness card (SG-027) — internal evaluation, not an authority approval",
    dependencies=[Depends(get_current_payroll_operator)],
)
def get_sg_employer_readiness(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_sg_employer_readiness(db, current_user.organization_id)


# ── Singapore: IR21 tax clearance — hold / clearance / release. Tenant-
# scoped (the caller's own organization only); lifting a hold needs a
# distinct approver (enforced in service.transition_sg_ir21_case).

@payroll_router.get(
    "/singapore/ir21-cases",
    summary="List this organization's Singapore IR21 tax-clearance cases",
    dependencies=[Depends(get_current_payroll_operator)],
)
def list_sg_ir21_cases(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_sg_ir21_cases(db, current_user.organization_id, status=status)


@payroll_router.post(
    "/singapore/ir21-cases",
    summary="Open a Singapore IR21 case — the employee's monies are withheld from the aware date",
    dependencies=[Depends(get_current_payroll_operator)],
)
def create_sg_ir21_case(
    data: SGIr21CaseCreateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    case = service.create_sg_ir21_case(
        db, current_user.organization_id, data.employee_id, data.trigger_type, data.trigger_date, data.aware_date,
        actor_id=current_user.id,
    )
    return service.serialize_sg_ir21_case(db, case)


@payroll_router.get(
    "/singapore/ir21-cases/{case_id}",
    summary="Get one Singapore IR21 case (own organization only)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def get_sg_ir21_case(
    case_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.serialize_sg_ir21_case(db, service.get_sg_ir21_case(db, current_user.organization_id, case_id))


@payroll_router.post(
    "/singapore/ir21-cases/{case_id}/transition",
    summary="Advance a Singapore IR21 case (FILED / CLEARED / RELEASED / EXEMPT / CANCELLED / EXCEPTION)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def transition_sg_ir21_case(
    case_id: int,
    data: SGIr21CaseTransitionRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    case = service.transition_sg_ir21_case(
        db, current_user.organization_id, case_id, data.status, actor_id=current_user.id,
        filed_date=data.filed_date, filing_reference=data.filing_reference,
        directive_date=data.directive_date, directive_reference=data.directive_reference,
        directive_tax_amount=data.directive_tax_amount, exemption_category=data.exemption_category,
        reason=data.reason,
    )
    return service.serialize_sg_ir21_case(db, case)


# ── Barbados: TAMIS Monthly PAYE return + NIS Earnings Schedule
# generation (Caribbean forms gap-closure, country #4, 2026-09-23).

@payroll_router.post(
    "/barbados/reports/tamis-monthly-paye", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a Barbados TAMIS Monthly PAYE return — employer-wide, sums every finalized payslip in the calendar month",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_bb_tamis_monthly_paye(
    data: GYMonthlyReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_bb_tamis_monthly_paye(
        db, current_user.organization_id, data.report_template_id, data.year, data.month,
        actor_id=current_user.id,
    )


@payroll_router.post(
    "/barbados/reports/nis-earnings-schedule", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a Barbados NIS Earnings Schedule for a calendar month — employer-wide, sums every finalized payslip",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_bb_nis_earnings_schedule(
    data: GYMonthlyReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_bb_nis_earnings_schedule(
        db, current_user.organization_id, data.report_template_id, data.year, data.month,
        actor_id=current_user.id,
    )


# ── Dominican Republic: DGII IR-3 + TSS/SUIR (monthly) + IR-13
# (per-employee, annual) generation (Caribbean forms gap-closure,
# country #5, 2026-09-23).

@payroll_router.post(
    "/do/reports/ir3", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a Dominican Republic DGII IR-3 monthly withholding declaration — employer-wide, sums every finalized payslip in the calendar month",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_do_ir3(
    data: GYMonthlyReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_do_ir3(
        db, current_user.organization_id, data.report_template_id, data.year, data.month,
        actor_id=current_user.id,
    )


@payroll_router.post(
    "/do/reports/tss-suir", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a Dominican Republic TSS/SUIR contribution submission for a calendar month — employer-wide, sums every finalized payslip",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_do_tss_suir(
    data: GYMonthlyReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_do_tss_suir(
        db, current_user.organization_id, data.report_template_id, data.year, data.month,
        actor_id=current_user.id,
    )


@payroll_router.post(
    "/do/reports/ir13", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a Dominican Republic DGII IR-13 annual withholding declaration for one employee — not tied to any single PayrollRun",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_do_ir13(
    data: UKEmployeeReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_uk_employee_report(
        db, current_user.organization_id, data.report_template_id, data.employee_id,
        data.as_of_date, actor_id=current_user.id,
    )


# ── The Bahamas: C10 monthly NIB contribution statement (non-
# hospitality) generation (Caribbean forms gap-closure, country #6,
# 2026-09-23).

@payroll_router.post(
    "/bahamas/reports/c10", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a Bahamas C10 monthly NIB contribution statement (non-hospitality) — employer-wide, sums every finalized payslip in the calendar month",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_bs_c10(
    data: GYMonthlyReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_bs_c10(
        db, current_user.organization_id, data.report_template_id, data.year, data.month,
        actor_id=current_user.id,
    )


# ── Cayman Islands: monthly Pension contribution submission generation
# (Caribbean forms gap-closure, country #7 — the last of the 7,
# 2026-09-23). The Wage/Gratuity Statement needs no dedicated endpoint —
# it uses the fully generic POST /generated-reports above unchanged,
# same as STP/CA/India/UK's own generic-engine report types.

@payroll_router.post(
    "/ky/reports/pension-submission", response_model=GeneratedReportResponse, response_model_by_alias=True,
    summary="Generate a Cayman Islands monthly Pension contribution submission — employer-wide, sums every finalized payslip in the calendar month",
    dependencies=[Depends(get_current_payroll_operator)],
)
def generate_ky_pension_submission(
    data: GYMonthlyReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.generate_ky_pension_submission(
        db, current_user.organization_id, data.report_template_id, data.year, data.month,
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


# ── Hong Kong (ZP-HK-ENG-001) — tenant operational workflows ────────────
# Payroll operators only; always the caller's own organization
# (current_user.organization_id), never an id from the body (HK-021). The
# statutory calculation itself runs inside the normal payroll run; these
# endpoints cover hours evidence, IR56G holds, IRD reporting, eMPF batches,
# Employment Ordinance entitlements and termination. Four-eyes approvals
# are enforced in hk_service (approver != preparer).
from app.modules.payroll import hk_service  # noqa: E402
from app.modules.payroll.schemas import (  # noqa: E402
    HKAnnualReturnRequest, HKAverageWageOverrideRequest, HKAverageWageRequest, HKDepartureChangeRequest,
    HKDepartureRequest, HKEmpfPrepareRequest, HKEmpfTransitionRequest, HKEntitlementRequest, HKIr56gFiledRequest,
    HKCorrectionRequest, HKLegalHoldRequest, HKEmployeeCopyRequest, HKIrdAmendRequest, HKIrdTransitionRequest, HKReasonRequest, HKReleaseRequest, HKSalariesTaxEstimateRequest, HKTerminationRequest,
    HKWorkHoursRequest,
)

_HK_READ = [Depends(get_current_payroll_operator)]
_HK_WRITE = [Depends(get_current_payroll_operator), Depends(require_writeable_workspace())]


@payroll_router.post("/hong-kong/employees/{employee_id}/work-hours", dependencies=_HK_WRITE,
                     summary="Record verified daily hours (append-only; a correction supersedes)")
def hk_record_work_hours(employee_id: int, data: HKWorkHoursRequest, db: Session = Depends(get_db),
                         current_user=Depends(get_current_user)):
    rows = hk_service.record_work_hours(db, current_user.organization_id, employee_id,
                                        [e.model_dump() for e in data.entries], current_user.id, data.reason)
    return [{"id": r.id, "date": r.work_date.isoformat(), "hours": str(r.hours), "source": r.source} for r in rows]


@payroll_router.get("/hong-kong/employees/{employee_id}/continuous-contract", dependencies=_HK_READ,
                    summary="Continuous-contract status on a date (4-18 before / 4-week 17-68 from 18 Jan 2026)")
def hk_continuous_contract(employee_id: int, as_of: date = Query(...), db: Session = Depends(get_db),
                           current_user=Depends(get_current_user)):
    return hk_service.continuous_contract(db, current_user.organization_id, employee_id, as_of)


@payroll_router.get("/hong-kong/tax-clearance", dependencies=_HK_READ, summary="List IR56G tax-clearance cases")
def hk_list_holds(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    from app.modules.payroll.models import HkgTaxClearanceHold

    holds = db.query(HkgTaxClearanceHold).filter(HkgTaxClearanceHold.organization_id == current_user.organization_id).all()
    return [hk_service.serialize_hold(db, h) for h in holds]


@payroll_router.post("/hong-kong/tax-clearance", dependencies=_HK_WRITE, summary="Identify a departure (IR56G case)")
def hk_identify_departure(data: HKDepartureRequest, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    hold = hk_service.identify_departure(db, current_user.organization_id, data.employeeId, data.expectedDepartureDate,
                                         current_user.id, data.identifiedOn, data.returnDate)
    return hk_service.serialize_hold(db, hold)


@payroll_router.post("/hong-kong/tax-clearance/{hold_id}/filed", dependencies=_HK_WRITE,
                     summary="Record the IR56G filing; the legal hold becomes active")
def hk_ir56g_filed(hold_id: int, data: HKIr56gFiledRequest, db: Session = Depends(get_db),
                   current_user=Depends(get_current_user)):
    hold = hk_service.record_ir56g_filed(db, current_user.organization_id, hold_id, data.filedOn, data.filingReference,
                                         current_user.id)
    return hk_service.serialize_hold(db, hold)


@payroll_router.post("/hong-kong/tax-clearance/{hold_id}/release-request", dependencies=_HK_WRITE,
                     summary="Request release of held money (letter of release / statutory period elapsed) with evidence")
def hk_release_request(hold_id: int, data: HKReleaseRequest, db: Session = Depends(get_db),
                       current_user=Depends(get_current_user)):
    hold = hk_service.request_hold_release(db, current_user.organization_id, hold_id, data.basis, data.reference,
                                           data.evidenceRef, current_user.id)
    return hk_service.serialize_hold(db, hold)


@payroll_router.post("/hong-kong/tax-clearance/{hold_id}/release-approve", dependencies=_HK_WRITE,
                     summary="Approve a release (a different operator from the requester)")
def hk_release_approve(hold_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    hold = hk_service.approve_hold_release(db, current_user.organization_id, hold_id, current_user.id)
    return hk_service.serialize_hold(db, hold)


@payroll_router.post("/hong-kong/tax-clearance/{hold_id}/change", dependencies=_HK_WRITE,
                     summary="Departure cancelled / changed: evidence required; an active hold is never silently cleared")
def hk_departure_change(hold_id: int, data: HKDepartureChangeRequest, db: Session = Depends(get_db),
                        current_user=Depends(get_current_user)):
    hold = hk_service.change_departure(db, current_user.organization_id, hold_id, data.reason, data.evidenceRef,
                                       current_user.id, data.newDepartureDate)
    return hk_service.serialize_hold(db, hold)


@payroll_router.post("/hong-kong/tax-clearance/{hold_id}/close", dependencies=_HK_WRITE, summary="Close a case")
def hk_close_hold(hold_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return hk_service.serialize_hold(db, hk_service.close_hold(db, current_user.organization_id, hold_id, current_user.id))


@payroll_router.get("/hong-kong/ird/cases", dependencies=_HK_READ, summary="List IRD reporting cases")
def hk_list_ird_cases(year_of_assessment: Optional[str] = Query(None), db: Session = Depends(get_db),
                      current_user=Depends(get_current_user)):
    from app.modules.payroll.models import HkgIrdReportingCase

    q = db.query(HkgIrdReportingCase).filter(HkgIrdReportingCase.organization_id == current_user.organization_id)
    if year_of_assessment:
        q = q.filter(HkgIrdReportingCase.year_of_assessment == year_of_assessment)
    return [hk_service.serialize_ird_case(c) for c in q.order_by(HkgIrdReportingCase.id).all()]


@payroll_router.get("/hong-kong/ird/cases/{case_id}/history", dependencies=_HK_READ,
                    summary="An IRD case's filing history (filings, rejections with the filed evidence, re-filings)")
def hk_ird_case_history(case_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return hk_service.ird_case_history(db, current_user.organization_id, case_id)


@payroll_router.post("/hong-kong/ird/employees/{employee_id}/event-cases", dependencies=_HK_WRITE,
                     summary="Create due IR56E / IR56F cases from the employee's effective statutory facts")
def hk_ird_event_cases(employee_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    rows = hk_service.create_event_cases(db, current_user.organization_id, employee_id, current_user.id)
    return [hk_service.serialize_ird_case(c) for c in rows]


@payroll_router.post("/hong-kong/ird/annual-return", dependencies=_HK_WRITE,
                     summary="Prepare BIR56A + IR56B for a year of assessment (ending 31 March) from committed payroll")
def hk_ird_annual_return(data: HKAnnualReturnRequest, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return hk_service.generate_annual_return(db, current_user.organization_id, data.yearOfAssessment, current_user.id)


@payroll_router.post("/hong-kong/ird/cases/{case_id}/transition", dependencies=_HK_WRITE,
                     summary="Move an IRD case (validate / record filing / record acknowledgement)")
def hk_ird_transition(case_id: int, data: HKIrdTransitionRequest, db: Session = Depends(get_db),
                      current_user=Depends(get_current_user)):
    submission = {k: getattr(data, k) for k in ("submissionMode", "authorizedSigner", "transactionReference",
                                                "controlListReference", "submittedOn")}
    case = hk_service.transition_ird_case(db, current_user.organization_id, case_id, data.target, current_user.id,
                                          data.filingReference, data.receiptReference, submission=submission)
    return hk_service.serialize_ird_case(case)


@payroll_router.post("/hong-kong/ird/cases/{case_id}/amend", dependencies=_HK_WRITE,
                     summary="Amend a filed case: creates a linked replacement; filed evidence is never overwritten")
def hk_ird_amend(case_id: int, data: HKIrdAmendRequest, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return hk_service.serialize_ird_case(hk_service.amend_ird_case(db, current_user.organization_id, case_id, data.reason,
                                                                   current_user.id, amendment_type=data.amendmentType))


@payroll_router.post("/hong-kong/ird/cases/{case_id}/employee-copy", dependencies=_HK_WRITE,
                     summary="Record that the employee was given their copy of the IR56B / E / F / G (once, with evidence)")
def hk_ird_employee_copy(case_id: int, data: HKEmployeeCopyRequest, db: Session = Depends(get_db),
                         current_user=Depends(get_current_user)):
    return hk_service.serialize_ird_case(hk_service.record_employee_copy_delivered(
        db, current_user.organization_id, case_id, data.evidenceRef, current_user.id))


@payroll_router.post("/hong-kong/payslips/{payslip_id}/corrections", dependencies=_HK_WRITE,
                     summary="Request a linked correction of a COMMITTED Hong Kong payslip (maker; D-14)")
def hk_request_correction(payslip_id: int, data: HKCorrectionRequest, db: Session = Depends(get_db),
                          current_user=Depends(get_current_user)):
    from app.modules.payroll import hk_corrections

    return hk_corrections.serialize(hk_corrections.request_correction(
        db, current_user.organization_id, payslip_id, data.reason, current_user.id))


@payroll_router.get("/hong-kong/corrections", dependencies=_HK_READ, summary="List Hong Kong payroll corrections")
def hk_list_corrections(employee_id: Optional[int] = Query(None), db: Session = Depends(get_db),
                        current_user=Depends(get_current_user)):
    from app.modules.payroll import hk_corrections

    return hk_corrections.list_corrections(db, current_user.organization_id, employee_id)


@payroll_router.post("/hong-kong/corrections/{correction_id}/approve", dependencies=_HK_WRITE,
                     summary="Approve a Hong Kong payroll correction (checker ≠ requester); applies its consequences")
def hk_approve_correction(correction_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    from app.modules.payroll import hk_corrections

    return hk_corrections.serialize(hk_corrections.approve_correction(
        db, current_user.organization_id, correction_id, current_user.id))


@payroll_router.post("/hong-kong/corrections/{correction_id}/reject", dependencies=_HK_WRITE,
                     summary="Reject / withdraw a Hong Kong payroll correction (its record is kept)")
def hk_reject_correction(correction_id: int, data: HKReasonRequest, db: Session = Depends(get_db),
                         current_user=Depends(get_current_user)):
    from app.modules.payroll import hk_corrections

    return hk_corrections.serialize(hk_corrections.reject_correction(
        db, current_user.organization_id, correction_id, data.reason, current_user.id))


@payroll_router.get("/hong-kong/legal-holds", dependencies=_HK_READ, summary="List Hong Kong legal holds")
def hk_list_legal_holds(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    from app.modules.payroll import hk_privacy

    return hk_privacy.list_legal_holds(db, current_user.organization_id)


@payroll_router.post("/hong-kong/legal-holds", dependencies=_HK_WRITE,
                     summary="Place a legal hold on Hong Kong records (organisation-wide or one employee)")
def hk_place_legal_hold(data: HKLegalHoldRequest, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    from app.modules.payroll import hk_privacy

    hk_privacy.place_legal_hold(db, current_user.organization_id, data.employeeId, data.reason, data.reference,
                                current_user.id)
    return hk_privacy.list_legal_holds(db, current_user.organization_id)


@payroll_router.post("/hong-kong/legal-holds/{hold_id}/release", dependencies=_HK_WRITE,
                     summary="Release a legal hold (a different user from the one who placed it)")
def hk_release_legal_hold(hold_id: int, data: HKReasonRequest, db: Session = Depends(get_db),
                          current_user=Depends(get_current_user)):
    from app.modules.payroll import hk_privacy

    hk_privacy.release_legal_hold(db, current_user.organization_id, hold_id, data.reason, current_user.id)
    return hk_privacy.list_legal_holds(db, current_user.organization_id)


@payroll_router.get("/hong-kong/access-events", dependencies=_HK_READ,
                    summary="Hong Kong statutory-data access log (downloads and statutory-profile views)")
def hk_access_events(employee_id: Optional[int] = Query(None), limit: int = Query(200, ge=1, le=1000),
                     db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    from app.modules.payroll import hk_privacy

    return hk_privacy.list_access_events(db, current_user.organization_id, employee_id, limit)


@payroll_router.post("/hong-kong/employees/{employee_id}/average-wage", dependencies=_HK_WRITE,
                     summary="Compute and freeze a 12-month average-wage snapshot from committed payroll")
def hk_average_wage(employee_id: int, data: HKAverageWageRequest, db: Session = Depends(get_db),
                    current_user=Depends(get_current_user)):
    snap = hk_service.calculate_average_wage(db, current_user.organization_id, employee_id, data.benefitType,
                                             data.referenceDate, data.disregarded, current_user.id, data.overtimeConstant)
    return {"id": snap.id, "status": snap.status, **snap.result}


@payroll_router.get("/hong-kong/employees/{employee_id}/average-wage-snapshots", dependencies=_HK_READ,
                    summary="List an employee's average-wage snapshots and their override state")
def hk_average_wage_snapshots(employee_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return hk_service.list_average_wage_snapshots(db, current_user.organization_id, employee_id)


@payroll_router.get("/hong-kong/termination-results", dependencies=_HK_READ,
                    summary="List Hong Kong termination calculations (for four-eyes approval and statements)")
def hk_termination_results(employee_id: Optional[int] = Query(None), db: Session = Depends(get_db),
                           current_user=Depends(get_current_user)):
    return hk_service.list_termination_results(db, current_user.organization_id, employee_id)


@payroll_router.post("/hong-kong/average-wage/{snapshot_id}/override-request", dependencies=_HK_WRITE,
                     summary="Request a controlled average-wage override (reason + evidence)")
def hk_average_override_request(snapshot_id: int, data: HKAverageWageOverrideRequest, db: Session = Depends(get_db),
                                current_user=Depends(get_current_user)):
    snap = hk_service.request_average_wage_override(db, current_user.organization_id, snapshot_id, data.averageDailyWage,
                                                    data.reason, data.evidenceRef, current_user.id)
    return {"id": snap.id, "status": snap.status, "overrideRequested": str(snap.override_average_daily_wage)}


@payroll_router.post("/hong-kong/average-wage/{snapshot_id}/override-approve", dependencies=_HK_WRITE,
                     summary="Approve an average-wage override (different operator)")
def hk_average_override_approve(snapshot_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    snap = hk_service.approve_average_wage_override(db, current_user.organization_id, snapshot_id, current_user.id)
    return {"id": snap.id, "status": snap.status, **hk_service.effective_average(snap)}


@payroll_router.post("/hong-kong/employees/{employee_id}/entitlements", dependencies=_HK_READ,
                     summary="Employment Ordinance entitlement (holiday / annual leave / sickness / maternity / paternity pay)")
def hk_entitlement(employee_id: int, data: HKEntitlementRequest, db: Session = Depends(get_db),
                   current_user=Depends(get_current_user)):
    payload = data.model_dump(exclude_none=True)
    return hk_service.calculate_entitlement(db, current_user.organization_id, employee_id, payload.pop("benefit"), payload)


@payroll_router.post("/hong-kong/employees/{employee_id}/termination", dependencies=_HK_WRITE,
                     summary="Termination calculator: SP/LSP with the 1 May 2025 MPF-offset transition split")
def hk_termination(employee_id: int, data: HKTerminationRequest, db: Session = Depends(get_db),
                   current_user=Depends(get_current_user)):
    row = hk_service.calculate_termination(db, current_user.organization_id, employee_id,
                                           data.model_dump(exclude_none=True, mode="json"), current_user.id)
    return {"id": row.id, "status": row.status, "employeeId": row.employee_id, **row.result}


@payroll_router.post("/hong-kong/termination/{result_id}/approve", dependencies=_HK_WRITE,
                     summary="Approve a termination calculation (different operator)")
def hk_termination_approve(result_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    row = hk_service.approve_termination(db, current_user.organization_id, result_id, current_user.id)
    return {"id": row.id, "status": row.status}


def _hk_empf_view(sub) -> dict:
    return {"id": sub.id, "contributionPeriod": sub.contribution_period, "status": sub.status, "rows": sub.rows,
            "totals": sub.totals, "validationErrors": sub.validation_errors or [],
            "contributionDay": sub.contribution_day.isoformat() if sub.contribution_day else None,
            "submissionReference": sub.submission_reference, "rowOutcomes": sub.row_outcomes,
            "settlementReference": sub.settlement_reference, "payloadHash": sub.payload_hash,
            "transmission": "NOT_CERTIFIED: prepared for the operator's own eMPF submission"}


@payroll_router.post("/hong-kong/empf/submissions", dependencies=_HK_WRITE,
                     summary="Prepare + validate an eMPF remittance batch (no transmission; no certified interface)")
def hk_empf_prepare(data: HKEmpfPrepareRequest, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    sub = hk_service.prepare_empf_submission(db, current_user.organization_id, data.contributionPeriod, current_user.id)
    return _hk_empf_view(sub)


@payroll_router.get("/hong-kong/empf/submissions", dependencies=_HK_READ, summary="List eMPF submissions")
def hk_empf_list(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    from app.modules.payroll.models import HkgEmpfSubmission

    return [_hk_empf_view(s) for s in db.query(HkgEmpfSubmission)
            .filter(HkgEmpfSubmission.organization_id == current_user.organization_id).order_by(HkgEmpfSubmission.id)]


@payroll_router.post("/hong-kong/empf/submissions/{submission_id}/transition", dependencies=_HK_WRITE,
                     summary="Record an eMPF submission / outcome / settlement from the operator's eMPF evidence")
def hk_empf_transition(submission_id: int, data: HKEmpfTransitionRequest, db: Session = Depends(get_db),
                       current_user=Depends(get_current_user)):
    sub = hk_service.transition_empf_submission(db, current_user.organization_id, submission_id, data.target,
                                                current_user.id, data.submissionReference, data.rowOutcomes,
                                                data.settlementReference)
    return _hk_empf_view(sub)


@payroll_router.post("/hong-kong/salaries-tax/estimate", dependencies=_HK_READ,
                     summary="INFORMATIONAL Salaries Tax estimate: never withheld from pay")
def hk_salaries_tax_estimate(data: HKSalariesTaxEstimateRequest, db: Session = Depends(get_db)):
    return hk_service.salaries_tax_estimate(db, data.yearOfAssessment, data.income, data.deductions, data.allowances,
                                             data.deductionClaims, data.elections)


# ── France filing lifecycle (ZP-FR-ENG-001 §10/§13) ─────────────────────
# Org-facing: the employer opens its DSN, follows the four lifecycle signals
# and drives its own outbox. Authority data (PAS rates, AT/MP rate packs,
# effectif, employer profile) is Super Admin-owned — see
# super_admin/router.py /compliance/france/*.

@payroll_router.post(
    "/france/dsn-submissions", response_model=FranceDsnSubmissionResponse, response_model_by_alias=True,
    summary="Open a France DSN P26V01 submission for a period (runs the FR-031 pre-submit validator: clean → VALIDATED, blocked → DRAFT with recorded errors)",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def create_france_dsn_submission(
    data: FranceDsnSubmissionCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.create_france_dsn_submission(db, current_user.organization_id, data, actor_id=current_user.id)


@payroll_router.get(
    "/france/dsn-submissions", response_model=list[FranceDsnSubmissionResponse], response_model_by_alias=True,
    summary="List this organization's France DSN submissions, optionally by lifecycle status",
    dependencies=[Depends(get_current_payroll_operator)],
)
def list_france_dsn_submissions(
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_france_dsn_submissions(db, current_user.organization_id, status)


@payroll_router.put(
    "/france/dsn-submissions/{submission_id}/status",
    response_model=FranceDsnSubmissionResponse, response_model_by_alias=True,
    summary="Transition a France DSN lifecycle state (FR-032); transport/business/payment signals land in separate columns",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def transition_france_dsn_submission(
    submission_id: int,
    data: FranceDsnStatusUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.transition_france_dsn_submission(db, current_user.organization_id, submission_id, data, actor_id=current_user.id)


@payroll_router.post(
    "/france/dsn-outbox", response_model=FranceDsnOutboxItemResponse, response_model_by_alias=True,
    summary="Enqueue a durable idempotent DSN outbox action (FR-033)",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def create_france_dsn_outbox_item(
    data: FranceDsnOutboxCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.create_france_dsn_outbox_item(db, current_user.organization_id, data, actor_id=current_user.id)


@payroll_router.get(
    "/france/dsn-outbox", response_model=list[FranceDsnOutboxItemResponse], response_model_by_alias=True,
    summary="List this organization's France DSN outbox actions",
    dependencies=[Depends(get_current_payroll_operator)],
)
def list_france_dsn_outbox_items(
    submission_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_france_dsn_outbox_items(db, current_user.organization_id, submission_id)


@payroll_router.put(
    "/france/dsn-outbox/{item_id}/status", response_model=FranceDsnOutboxItemResponse, response_model_by_alias=True,
    summary="Record a transport-side outbox acknowledgement (FR-033); UNKNOWN triggers reconciliation, never blind replay",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def transition_france_dsn_outbox_item(
    item_id: int,
    status: str = Query(...),
    last_error: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.transition_france_dsn_outbox_item(
        db, current_user.organization_id, item_id, status, last_error=last_error, actor_id=current_user.id)


# ── Italy (ZP-IT-ENG-001 §17) — employer profile ───────────────────────────
@payroll_router.get(
    "/italy/employer-profile", response_model=Optional[ItalyEmployerProfileResponse], response_model_by_alias=True,
    summary="This organization's Italy employer profile and recomputed readiness (null if not captured yet)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def get_italy_employer_profile(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    from app.modules.payroll import italy_service

    return italy_service.get_employer_profile(db, current_user.organization_id)


@payroll_router.put(
    "/italy/employer-profile", response_model=ItalyEmployerProfileResponse, response_model_by_alias=True,
    summary="Create or edit this organization's Italy employer facts; readiness is recomputed, never set",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def upsert_italy_employer_profile(
    data: ItalyEmployerProfileUpsert,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    from app.modules.payroll import italy_service

    return italy_service.upsert_employer_profile(db, current_user.organization_id, data, actor_id=current_user.id)


# ── Italy filing outbox (§15/§16, IT-044/IT-048) ───────────────────────────
# Queue only. This endpoint does not generate a UniEmens/F24/LUL/CU/770
# document and does not reach INPS/INAIL/Agenzia delle Entrate: it records the
# intent to deliver an already-committed filing, idempotently, so a calculation
# never depends on a government endpoint being up.

@payroll_router.post(
    "/italy/filing-outbox", response_model=ItalyFilingOutboxItemResponse, response_model_by_alias=True,
    summary="Enqueue a durable idempotent Italy filing outbox action (IT-044)",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def create_italy_filing_outbox_item(
    data: ItalyFilingOutboxCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.create_italy_filing_outbox_item(db, current_user.organization_id, data, actor_id=current_user.id)


@payroll_router.get(
    "/italy/filing-outbox", response_model=List[ItalyFilingOutboxItemResponse], response_model_by_alias=True,
    summary="List this organization's Italy filing outbox actions (delivery state only; filing status lives on the StatutoryFiling)",
)
def list_italy_filing_outbox_items(
    statutory_filing_id: Optional[int] = Query(None, alias="statutoryFilingId"),
    action: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_italy_filing_outbox_items(
        db, current_user.organization_id, statutory_filing_id, action)


@payroll_router.post(
    "/italy/filing-outbox/{item_id}/status", response_model=ItalyFilingOutboxItemResponse,
    response_model_by_alias=True,
    summary="Record a transport-side outbox acknowledgement (IT-048); UNKNOWN triggers reconciliation, never blind replay",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def transition_italy_filing_outbox_item(
    item_id: int,
    status: str = Query(...),
    last_error: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.transition_italy_filing_outbox_item(
        db, current_user.organization_id, item_id, status, last_error=last_error, actor_id=current_user.id)


# ── Italy F24 (§16, IT-043/IT-046) ─────────────────────────────────────────
# Two separate resources, and keeping them separate is the point:
#
#   /italy/f24/causales  — the GOVERNED code catalog (Super Admin, IT-043).
#   /italy/f24/lines     — DERIVED payable lines for a committed run.
#
# There is deliberately no endpoint that generates an F24 document or transmits
# one. This phase makes the liability legible and payable-ready; delivery stays
# on the /italy/filing-outbox queue, which is idempotent and reconcilable.
# Nothing here may be wired to an automatic payment path while the causale
# catalog is still empty — an F24 built from guessed codes is a wrong
# instruction, not a rough draft.

@payroll_router.get(
    "/italy/f24/causales", response_model=List[ItalyF24CausaleResponse], response_model_by_alias=True,
    summary="List governed Italy F24 causales (the real codice tributo catalog — ships empty, IT-043)",
)
def list_italy_f24_causales(
    section: Optional[str] = Query(None),
    component_key: Optional[str] = Query(None, alias="componentKey"),
    as_of: Optional[date] = Query(None, alias="asOf"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_italy_f24_causales(
        db, current_user.organization_id, section, component_key, as_of)


@payroll_router.post(
    "/italy/f24/causales", response_model=ItalyF24CausaleResponse, response_model_by_alias=True,
    summary="Record a governed Italy F24 causale for one snapshot component (never invented — IT-043)",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def upsert_italy_f24_causale(
    data: ItalyF24CausaleUpsert,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.upsert_italy_f24_causale(
        db, current_user.organization_id, data, actor_id=current_user.id)


@payroll_router.get(
    "/italy/f24/lines", response_model=List[ItalyF24LineResponse], response_model_by_alias=True,
    summary="List derived Italy F24 payable lines (payment STATE lives on the StatutoryFiling, IT-047)",
)
def list_italy_f24_lines(
    payroll_run_id: Optional[int] = Query(None, alias="payrollRunId"),
    statutory_filing_id: Optional[int] = Query(None, alias="statutoryFilingId"),
    reference_period: Optional[str] = Query(None, alias="referencePeriod"),
    section: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_italy_f24_lines(
        db, current_user.organization_id, payroll_run_id, statutory_filing_id,
        reference_period, section)


@payroll_router.post(
    "/italy/f24/lines/build", response_model=List[ItalyF24LineResponse], response_model_by_alias=True,
    summary="Derive Italy F24 payable lines from one APPROVED-or-later run (idempotent rebuild, IT-046)",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def build_italy_f24_lines(
    data: ItalyF24BuildRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.build_italy_f24_lines(
        db, current_user.organization_id, data, actor_id=current_user.id)


# ── Italy Libro Unico del Lavoro (§20, IT-058/IT-059/IT-060) ───────────────
# The employer-registrated ledger: sequence, inalterability, retention and the
# authorized method (§17G). A correction is a FURTHER entry, never an overwrite,
# so both the original and the correction stay readable — hiding the original
# would defeat the rule that protects it.
#
# No transmission endpoint here by design. The authorized method belongs to the
# employer or their consultant; this records what they registered. Submission
# stays on the /italy/filing-outbox queue.

@payroll_router.get(
    "/italy/lul/entries", response_model=List[ItalyLulEntryResponse], response_model_by_alias=True,
    summary="List this employer's Italy LUL registrations (superseded entries included by default)",
)
def list_italy_lul_entries(
    reference_month: Optional[str] = Query(None, alias="referenceMonth"),
    employee_id: Optional[int] = Query(None, alias="employeeId"),
    payroll_run_id: Optional[int] = Query(None, alias="payrollRunId"),
    entry_type: Optional[str] = Query(None, alias="entryType"),
    include_superseded: bool = Query(True, alias="includeSuperseded"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_italy_lul_entries(
        db, current_user.organization_id, reference_month, employee_id, payroll_run_id,
        entry_type, include_superseded)


@payroll_router.post(
    "/italy/lul/entries/build", response_model=List[ItalyLulEntryResponse], response_model_by_alias=True,
    summary="Register one committed run in the Italy LUL ledger (idempotent; sequence allocated server-side)",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def build_italy_lul_entries(
    data: ItalyLulBuildRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.build_italy_lul_entries(
        db, current_user.organization_id, data, actor_id=current_user.id)


@payroll_router.post(
    "/italy/lul/entries/{entry_id}/correction",
    response_model=ItalyLulEntryResponse, response_model_by_alias=True,
    summary="Register a CORRECTION to a LUL entry — appends, never rewrites the original (IT-058)",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def correct_italy_lul_entry(
    entry_id: int,
    data: ItalyLulCorrectionRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.correct_italy_lul_entry(
        db, current_user.organization_id, entry_id, data, actor_id=current_user.id)


@payroll_router.get(
    "/italy/lul/integrity", response_model=ItalyLulIntegrityResponse, response_model_by_alias=True,
    summary="Verify LUL inalterability: recompute every content hash and report sequence gaps (IT-058)",
)
def verify_italy_lul_integrity(
    reference_month: Optional[str] = Query(None, alias="referenceMonth"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.verify_italy_lul_integrity(
        db, current_user.organization_id, reference_month)


@payroll_router.get(
    "/italy/lul/deadline",
    summary="The §20 next-month registration deadline for a reference month, and whether it was met",
)
def get_italy_lul_deadline(
    reference_month: str = Query(..., alias="referenceMonth"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_italy_lul_deadline(
        db, current_user.organization_id, reference_month)


# ── Italy TFR (§13, IT-037/IT-038/IT-039/IT-040/IT-041) ───────────────────
# The TFR liability ledger: accrual, INPS offset, annual revaluation with
# substitute tax, transfers to pension fund/Tesoreria, and settlement.
# Destination (AZIENDA / FONDO_PENSIONE / FONDO_TESORERIA) is recorded per
# entry (IT-038). Revaluation is on prior-year balances only, with its own
# substitute tax (IT-039). Fondo Tesoreria threshold is prior-year avg headcount
# >= 60 (2026-2027) (IT-040/IT-041).

@payroll_router.post(
    "/italy/tfr/accrual", response_model=List[ItalyTfrLedgerEntryResponse], response_model_by_alias=True,
    summary="Post TFR accruals for one APPROVED-or-later run (idempotent per employee/month)",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def post_italy_tfr_accrual(
    data: ItalyTfrAccrualRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.post_italy_tfr_accrual(
        db, current_user.organization_id, data.payrollRunId, actor_id=current_user.id)


@payroll_router.post(
    "/italy/tfr/revaluation", response_model=List[ItalyTfrLedgerEntryResponse], response_model_by_alias=True,
    summary="Post annual TFR revaluation on prior-year balances (31 Dec) — ISTAT FOI increase required",
    dependencies=[Depends(get_current_payroll_operator), Depends(require_writeable_workspace())],
)
def post_italy_tfr_revaluation(
    data: ItalyTfrRevaluationRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.post_italy_tfr_revaluation(
        db, current_user.organization_id, data.taxYear,
        data.istatFoiIncreasePct, data.months, actor_id=current_user.id)


@payroll_router.get(
    "/italy/tfr/ledger", response_model=List[ItalyTfrLedgerEntryResponse], response_model_by_alias=True,
    summary="List this employer's TFR ledger entries (filter by employee, year, type)",
)
def list_italy_tfr_ledger(
    employee_id: Optional[int] = Query(None, alias="employeeId"),
    tax_year: Optional[int] = Query(None, alias="taxYear"),
    entry_type: Optional[str] = Query(None, alias="entryType"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_italy_tfr_ledger(
        db, current_user.organization_id, employee_id, tax_year, entry_type)


@payroll_router.get(
    "/italy/tfr/balance", response_model=ItalyTfrBalanceResponse, response_model_by_alias=True,
    summary="Current TFR liability balance by destination (AZIENDA / FONDO_PENSIONE / FONDO_TESORERIA)",
)
def get_italy_tfr_balance(
    employee_id: Optional[int] = Query(None, alias="employeeId"),
    as_of_year: Optional[int] = Query(None, alias="asOfYear"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_italy_tfr_balance(
        db, current_user.organization_id, employee_id, as_of_year)


@payroll_router.get(
    "/italy/tfr/idempotency", response_model=ItalyTfrIdempotencyResponse, response_model_by_alias=True,
    summary="Audit check: duplicate idempotency keys in the TFR ledger (should be zero)",
)
def verify_italy_tfr_idempotency(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.verify_italy_tfr_idempotency(
        db, current_user.organization_id)


@payroll_router.get(
    "/france/readiness",
    summary="France launch readiness for this organization (FR §11 gate H + FR-031 dry-run for the open period)",
    dependencies=[Depends(get_current_payroll_operator)],
)
def france_readiness(
    for_period: Optional[date] = Query(None, description="Period start to dry-run, defaults to next month"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_france_readiness(db, current_user.organization_id, for_period=for_period)
