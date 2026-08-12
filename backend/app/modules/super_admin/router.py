"""
modules/super_admin/router.py
-----------------------------
Super Admin endpoints: platform dashboard stats, platform-wide user
management (org admins / payroll admins / employees), admin-initiated
password resets, and PlatformSetting configuration.
"""

import logging
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_super_admin
from app.database import get_db
from app.modules.auth.models import User
from app.modules.auth.schemas import SuccessResponse
from app.modules.organizations.models import Organization
from app.modules.super_admin.schemas import (
    ApplicableOrganization,
    AssignPolicyRequest,
    DashboardChartsResponse,
    DashboardStats,
    FinanceOverviewResponse,
    FinanceSummaryResponse,
    PolicyStatusUpdate,
    ReportsListResponse,
    UpdateCurrencyRequest,
    SettingCreate,
    SettingResponse,
    SettingUpdate,
    StatutoryRateCreate,
    StatutoryRateListResponse,
    StatutoryRateResponse,
    StatutoryRateUpdate,
    SuperAdminUserListResponse,
    SuperAdminUserResponse,
)
from app.modules.payroll.schemas import JurisdictionPackResponse, JurisdictionPackUpsert

logger = logging.getLogger("zoiko_payroll.super_admin")

router = APIRouter(prefix="/super-admin", tags=["Super Admin"])


@router.get("/dashboard/stats", response_model=DashboardStats)
def dashboard_stats(current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    from app.modules.payroll.models import PayrollEmployee, PayrollRun

    total_orgs = db.query(Organization).count()
    active_orgs = db.query(Organization).filter(Organization.is_active == True).count()
    total_users = db.query(User).count()

    recent_orgs = (
        db.query(Organization)
        .order_by(Organization.created_at.desc())
        .limit(5)
        .all()
    )

    return DashboardStats(
        total_organizations=total_orgs,
        active_organizations=active_orgs,
        total_users=total_users,
        super_admins=db.query(User).filter(User.role == "super_admin").count(),
        org_admins=db.query(User).filter(User.role == "org_admin").count(),
        payroll_admins=db.query(User).filter(User.role == "payroll_admin").count(),
        total_payroll_employees=db.query(PayrollEmployee).count(),
        total_payroll_runs=db.query(PayrollRun).count(),
        recent_organizations=[
            {
                "id": o.id,
                "organization_name": o.organization_name,
                "organization_code": o.organization_code,
                "is_active": o.is_active,
                "created_at": o.created_at,
            }
            for o in recent_orgs
        ],
    )


@router.get("/users", response_model=SuperAdminUserListResponse)
def list_platform_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    search: str = Query(""),
    role: str = Query(""),
    organization_id: int = Query(None),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    query = db.query(User, Organization).outerjoin(
        Organization, Organization.id == User.organization_id
    )
    if search:
        like = f"%{search}%"
        query = query.filter(
            (User.email.ilike(like))
            | (User.first_name.ilike(like))
            | (User.last_name.ilike(like))
            | (Organization.organization_name.ilike(like))
        )
    if role:
        query = query.filter(User.role == role)
    if organization_id:
        query = query.filter(User.organization_id == organization_id)

    total = query.count()
    rows = query.order_by(User.created_at.desc()).offset(skip).limit(limit).all()

    users = [
        SuperAdminUserResponse(
            id=u.id,
            email=u.email,
            role=u.role,
            organization_id=u.organization_id,
            organization_name=o.organization_name if o else None,
            organization_code=o.organization_code if o else None,
            first_name=u.first_name,
            last_name=u.last_name,
            is_active=u.is_active,
            created_at=u.created_at,
        )
        for u, o in rows
    ]
    return SuperAdminUserListResponse(users=users, total=total)


@router.put("/users/{user_id}/status", response_model=SuccessResponse)
def set_user_status(
    user_id: int,
    is_active: bool,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.core.exceptions import BadRequestException, NotFoundException

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise NotFoundException("User", "id")
    if user.id == current_user.id and not is_active:
        raise BadRequestException("You cannot deactivate your own account.")
    user.is_active = is_active
    db.commit()
    return {"message": "User status updated."}


@router.put("/users/{user_id}/reset-password", response_model=SuccessResponse)
def admin_reset_password(
    user_id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    """Force a password reset: email the user a single-use reset link."""
    from app.core.exceptions import NotFoundException
    from app.modules.auth import service as auth_service
    from app.modules.auth.models import SecurityActionPurpose

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise NotFoundException("User", "id")

    raw_token, _ = auth_service._issue_action_token(
        db, user.email, user.organization_id, SecurityActionPurpose.RESET
    )
    link = auth_service._action_link(SecurityActionPurpose.RESET, raw_token)
    auth_service._send_reset_email(db, user, link)
    db.commit()
    logger.info("Super Admin %s reset password for %s", current_user.email, user.email)
    return {"message": "Password reset link sent to the user."}


# ── Platform settings ───────────────────────────────────────────────────────

@router.get("/settings", response_model=list[SettingResponse])
def list_settings(current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    from app.modules.super_admin.models import PlatformSetting

    return db.query(PlatformSetting).order_by(PlatformSetting.key).all()


@router.put("/settings/{key}", response_model=SettingResponse)
def update_setting(
    key: str,
    data: SettingUpdate,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.core.exceptions import NotFoundException
    from app.modules.super_admin.models import PlatformSetting

    setting = db.query(PlatformSetting).filter(PlatformSetting.key == key).first()
    if setting is None:
        setting = PlatformSetting(key=key)
        db.add(setting)
    if data.value is not None:
        setting.value = data.value
    if data.description is not None:
        setting.description = data.description
    if data.is_public is not None:
        setting.is_public = data.is_public
    db.commit()
    db.refresh(setting)
    return setting


# ── Global statutory rate table ────────────────────────────────────────────
# Platform-wide default statutory contribution rates keyed by jurisdiction
# country. Orgs start from these defaults on first Compliance setup; their
# own org-scoped ContributionRate rows can diverge afterwards.

@router.get("/statutory-rates", response_model=StatutoryRateListResponse)
def list_statutory_rates(
    country: str = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.super_admin.models import GlobalStatutoryRate

    query = db.query(GlobalStatutoryRate)
    if country:
        query = query.filter(GlobalStatutoryRate.jurisdiction_country == country)
    if start_date:
        query = query.filter(GlobalStatutoryRate.updated_at >= start_date)
    if end_date:
        query = query.filter(GlobalStatutoryRate.updated_at <= end_date)
    rates = query.order_by(
        GlobalStatutoryRate.jurisdiction_country,
        GlobalStatutoryRate.sort_order,
        GlobalStatutoryRate.component_key,
    ).all()
    return StatutoryRateListResponse(rates=rates, total=len(rates))


@router.post("/statutory-rates", response_model=StatutoryRateResponse)
def create_statutory_rate(
    data: StatutoryRateCreate,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.core.exceptions import AlreadyExistsException
    from app.modules.super_admin.models import GlobalStatutoryRate

    existing = (
        db.query(GlobalStatutoryRate)
        .filter(
            GlobalStatutoryRate.jurisdiction_country == data.jurisdiction_country,
            GlobalStatutoryRate.component_key == data.component_key,
        )
        .first()
    )
    if existing:
        raise AlreadyExistsException("Statutory rate", "jurisdiction_country + component_key")

    rate = GlobalStatutoryRate(**data.model_dump())
    db.add(rate)
    db.commit()
    db.refresh(rate)
    logger.info("Super Admin %s created statutory rate %s/%s", current_user.email, data.jurisdiction_country, data.component_key)
    return rate


@router.put("/statutory-rates/{rate_id}", response_model=StatutoryRateResponse)
def update_statutory_rate(
    rate_id: int,
    data: StatutoryRateUpdate,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.core.exceptions import NotFoundException
    from app.modules.super_admin.models import GlobalStatutoryRate

    rate = db.query(GlobalStatutoryRate).filter(GlobalStatutoryRate.id == rate_id).first()
    if rate is None:
        raise NotFoundException("Statutory rate", "id")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(rate, field, value)
    db.commit()
    db.refresh(rate)
    return rate


@router.delete("/statutory-rates/{rate_id}", response_model=SuccessResponse)
def delete_statutory_rate(
    rate_id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.core.exceptions import NotFoundException
    from app.modules.super_admin.models import GlobalStatutoryRate

    rate = db.query(GlobalStatutoryRate).filter(GlobalStatutoryRate.id == rate_id).first()
    if rate is None:
        raise NotFoundException("Statutory rate", "id")
    db.delete(rate)
    db.commit()
    return {"message": "Statutory rate deleted."}


@router.get(
    "/statutory-rates/organization-rates",
    summary="Every organization's actual, currently-configured contribution rates (not the platform defaults)",
)
def list_organization_contribution_rates(
    country: Optional[str] = Query(None),
    organization_id: Optional[int] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.super_admin import service as sa_service

    return sa_service.list_contribution_rates(
        db, country=country, organization_id=organization_id, start_date=start_date, end_date=end_date,
    )


# ── Compliance ───────────────────────────────────────────────────────────────
# Reuses app.modules.payroll's JurisdictionPack model/schemas and service
# functions directly — the org-scoped endpoint at
# PUT /api/payroll/compliance/jurisdiction-packs already exposes
# service.upsert_jurisdiction_pack to a payroll operator; these routes
# expose the SAME service functions to Super Admin under a cross-org,
# Super-Admin-only path. No parallel model or business logic exists here.

@router.get("/compliance/jurisdictions", summary="Countries/states the app supports or already has configured")
def list_compliance_jurisdictions(current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    from app.modules.super_admin import service as sa_service

    return sa_service.list_known_jurisdictions(db)


@router.get(
    "/compliance/configurations",
    summary="Every organization's actual, currently-configured compliance setup (not the policy templates)",
)
def list_compliance_configurations(
    country: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.super_admin import service as sa_service

    return sa_service.list_compliance_configurations(db, country=country, search=search)


@router.get(
    "/compliance/policies", response_model=List[JurisdictionPackResponse], response_model_by_alias=True,
    summary="Cross-jurisdiction compliance policy list (latest version per policy)",
)
def list_compliance_policies(
    country: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.list_all_jurisdiction_packs(db, country=country, state=state, status=status, search=search)


@router.put(
    "/compliance/policies", response_model=JurisdictionPackResponse, response_model_by_alias=True,
    summary="Create a policy, or a new version of an existing policy (identity/metadata never overwritten across versions)",
)
def upsert_compliance_policy(
    payload: JurisdictionPackUpsert,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.upsert_jurisdiction_pack(db, payload, actor_id=current_user.id)


@router.get(
    "/compliance/policies/{pack_id}/versions", response_model=List[JurisdictionPackResponse], response_model_by_alias=True,
    summary="Full version history for one policy, oldest first",
)
def get_compliance_policy_versions(
    pack_id: str,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.get_jurisdiction_pack_versions(db, pack_id)


@router.put(
    "/compliance/policies/{id}/status", response_model=JurisdictionPackResponse, response_model_by_alias=True,
    summary="Activate/deactivate/retire a specific policy version",
)
def set_compliance_policy_status(
    id: int,
    payload: PolicyStatusUpdate,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.set_jurisdiction_pack_status(db, id, payload.status, actor_id=current_user.id)


@router.get(
    "/compliance/policies/{id}/organizations", response_model=List[ApplicableOrganization],
    summary="Organizations currently assigned to this policy version",
)
def get_compliance_policy_organizations(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.get_pack_applicable_organizations(db, id)


@router.post(
    "/compliance/policies/{id}/assign", response_model=SuccessResponse,
    summary="Assign this policy version as the active compliance pack for the given organizations",
)
def assign_compliance_policy(
    id: int,
    payload: AssignPolicyRequest,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    count = payroll_service.assign_pack_to_organizations(db, id, payload.organizationIds, actor_id=current_user.id)
    return {"message": f"Policy applied to {count} organization(s)."}


# ── Finance ────────────────────────────────────────────────────────────────
# Cross-org view over the existing PayrollRun/PayslipItem data — does not
# replace or duplicate an org's own Payroll module, which remains the
# system of record for its own runs.

@router.get("/finance/overview", response_model=FinanceOverviewResponse, summary="Cross-org payroll run listing")
def finance_overview(
    organization_id: Optional[int] = Query(None),
    country: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.super_admin import service as sa_service

    return sa_service.finance_overview(
        db, organization_id=organization_id, country=country, status=status,
        start_date=start_date, end_date=end_date, skip=skip, limit=limit,
    )


@router.get("/finance/summary", response_model=FinanceSummaryResponse, summary="Financial totals grouped by jurisdiction (currency-safe)")
def finance_summary(
    organization_id: Optional[int] = Query(None),
    country: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.super_admin import service as sa_service

    return sa_service.finance_summary(db, organization_id=organization_id, country=country, start_date=start_date, end_date=end_date)


@router.get(
    "/finance/organization-currencies",
    summary="Every organization plus its jurisdiction and any explicit currency override",
)
def list_organization_currencies(current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    from app.modules.super_admin import service as sa_service

    return sa_service.list_organization_currencies(db)


@router.put(
    "/finance/organizations/{organization_id}/currency",
    summary="Set (or clear) an organization's explicit currency override",
)
def update_organization_currency(
    organization_id: int,
    payload: UpdateCurrencyRequest,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.super_admin import service as sa_service

    org = sa_service.update_organization_currency(db, organization_id, payload.currency)
    return {"id": org.id, "organizationName": org.organization_name, "currency": org.currency}


# ── Reports ────────────────────────────────────────────────────────────────
# "Payroll" and "Compliance" report categories reuse /finance/overview and
# /compliance/policies directly from the frontend — no separate endpoint
# is defined for them here to avoid two code paths returning the same data.

@router.get("/reports/organizations", response_model=ReportsListResponse, summary="Cross-org report: identity + employee/run counts")
def reports_organizations(
    search: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.super_admin import service as sa_service

    return sa_service.reports_organizations(db, search=search, country=country, status=status, skip=skip, limit=limit)


@router.get("/reports/employees", response_model=ReportsListResponse, summary="Cross-org employee report")
def reports_employees(
    organization_id: Optional[int] = Query(None),
    country: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.super_admin import service as sa_service

    return sa_service.reports_employees(
        db, organization_id=organization_id, country=country, status=status, search=search, skip=skip, limit=limit,
    )


_REPORT_EXPORT_COLUMNS = {
    "organizations": [
        ("organizationName", "Organization"), ("organizationCode", "Code"), ("country", "Country"),
        ("jurisdictionCountry", "Jurisdiction"), ("isActive", "Active"),
        ("employeeCount", "Employees"), ("payrollRunCount", "Payroll Runs"),
    ],
    "employees": [
        ("employeeCode", "Employee Code"), ("name", "Name"), ("department", "Department"),
        ("designation", "Designation"), ("status", "Status"), ("employmentType", "Employment Type"),
        ("organizationName", "Organization"), ("jurisdictionCountry", "Jurisdiction"),
    ],
    "payroll": [
        ("organizationName", "Organization"), ("jurisdictionCountry", "Jurisdiction"), ("periodLabel", "Period"),
        ("payDate", "Pay Date"), ("status", "Status"), ("grossPay", "Gross Pay"), ("netPay", "Net Pay"),
        ("totalDeductions", "Deductions"), ("employerCost", "Employer Cost"),
    ],
    "compliance": [
        ("packId", "Policy"), ("jurisdictionCountry", "Country"), ("jurisdictionState", "State"),
        ("version", "Version"), ("status", "Status"), ("complianceCategory", "Category"),
        ("effectiveFrom", "Effective From"), ("effectiveTo", "Effective To"),
    ],
}


@router.get("/reports/export", summary="Export a report category as CSV")
def export_report(
    type: str = Query(..., pattern="^(organizations|employees|payroll|compliance)$"),
    organization_id: Optional[int] = Query(None),
    country: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service
    from app.modules.super_admin import service as sa_service

    if type == "organizations":
        rows = sa_service.reports_organizations(db, search=search, country=country, status=status, limit=10000)["items"]
    elif type == "employees":
        rows = sa_service.reports_employees(db, organization_id=organization_id, country=country, status=status, search=search, limit=10000)["items"]
    elif type == "payroll":
        rows = sa_service.finance_overview(
            db, organization_id=organization_id, country=country, status=status,
            start_date=start_date, end_date=end_date, limit=10000,
        )["items"]
    else:  # compliance
        packs = payroll_service.list_all_jurisdiction_packs(db, country=country, status=status)
        rows = [
            {
                "packId": p.pack_id, "jurisdictionCountry": p.jurisdiction_country, "jurisdictionState": p.jurisdiction_state,
                "version": p.version, "status": p.status, "complianceCategory": p.compliance_category,
                "effectiveFrom": p.effective_from, "effectiveTo": p.effective_to,
            }
            for p in packs
        ]

    csv_bytes = sa_service.rows_to_csv_bytes(_REPORT_EXPORT_COLUMNS[type], rows)
    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{type}-report.csv"'},
    )


# ── Dashboard charts ─────────────────────────────────────────────────────────

@router.get("/dashboard/charts", response_model=DashboardChartsResponse, summary="Chart data for the enhanced Super Admin dashboard")
def dashboard_charts(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.super_admin import service as sa_service

    return sa_service.dashboard_charts(db, start_date=start_date, end_date=end_date)
