"""
modules/organizations/router.py
-------------------------------
Organization endpoints.

  - Super Admin: list all orgs, create orgs, suspend/reactivate.
  - Org-scoped admins (org_admin / payroll_admin): read/update their own
    organization profile.

Registration of a brand-new org happens through /auth/register (public),
which creates the Organization + first org_admin in one transaction.
"""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.exceptions import NotFoundException, ForbiddenException
from app.modules.auth.schemas import SuccessResponse
from app.core.dependencies import (
    get_current_super_admin,
    get_current_org_admin,
    get_current_payroll_operator,
    get_current_user,
    get_super_admin_organization_id,
)
from app.modules.organizations.schemas import (
    OrganizationBase,
    OrganizationUpdate,
    OrganizationResponse,
    OrganizationListResponse,
    OrganizationDashboardStats,
    OrganizationDetail,
    DepartmentHeadcount,
    RecentEmployee,
)

logger = logging.getLogger("zoiko_payroll.organizations")

router = APIRouter(prefix="/organizations", tags=["Organizations"])


# ── Org-scoped (own organization only) ──────────────────────────────────────

@router.get("/me", response_model=OrganizationResponse)
def get_my_organization(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.core.dependencies import get_organization_id
    org_id = get_organization_id(current_user)
    from app.modules.organizations.models import Organization
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if org is None:
        raise NotFoundException("Organization", "id")
    return org


@router.put("/me", response_model=OrganizationResponse)
def update_my_organization(
    data: OrganizationUpdate,
    current_user=Depends(get_current_org_admin),
    db: Session = Depends(get_db),
):
    from app.core.dependencies import get_organization_id
    org_id = get_organization_id(current_user)
    from app.modules.organizations.models import Organization
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if org is None:
        raise NotFoundException("Organization", "id")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(org, field, value)
    db.commit()
    db.refresh(org)
    return org


@router.get("/me/dashboard-stats", response_model=OrganizationDashboardStats)
def get_my_organization_dashboard_stats(
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    """Org-scoped KPIs for the Organization Admin / HR Admin dashboard —
    computed from the payroll module's own tables (this standalone platform
    has no separate departments/designations/assets modules, so headcount by
    department/designation is derived from PayrollEmployee.department /
    .designation instead)."""
    from app.core.dependencies import get_organization_id
    from app.modules.auth.models import User, UserRole
    from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayrollLeaveRequest

    org_id = get_organization_id(current_user)

    employees = db.query(PayrollEmployee).filter(PayrollEmployee.organization_id == org_id).all()
    total_employees = len(employees)
    active_employees = sum(1 for e in employees if e.status == "Active")

    dept_counts = {}
    for e in employees:
        if e.department:
            dept_counts[e.department] = dept_counts.get(e.department, 0) + 1
    department_headcount = [
        DepartmentHeadcount(
            name=name, count=count,
            pct=round(count / total_employees * 100) if total_employees else 0,
        )
        for name, count in sorted(dept_counts.items(), key=lambda kv: kv[1], reverse=True)
    ]
    designations = len({e.designation for e in employees if e.designation})

    hr_admins = (
        db.query(User)
        .filter(User.organization_id == org_id, User.role == UserRole.PAYROLL_ADMIN)
        .count()
    )
    pending_leave_requests = (
        db.query(PayrollLeaveRequest)
        .filter(PayrollLeaveRequest.organization_id == org_id, PayrollLeaveRequest.status == "pending")
        .count()
    )
    pending_approvals = (
        db.query(PayrollRun)
        .filter(PayrollRun.organization_id == org_id, PayrollRun.status == "Review")
        .count()
    )
    latest_run = (
        db.query(PayrollRun)
        .filter(PayrollRun.organization_id == org_id)
        .order_by(PayrollRun.created_at.desc())
        .first()
    )
    monthly_payroll = float(latest_run.total_net) if latest_run and latest_run.total_net is not None else None

    recent_employees = [
        RecentEmployee(
            name=e.name,
            initials="".join(w[0] for w in e.name.split()[:2]).upper() or "U",
            dept=e.department,
            designation=e.designation,
            status=e.status,
            statusColor="teal" if e.status == "Active" else "amber" if e.status == "On Leave" else "off",
        )
        for e in sorted(employees, key=lambda e: e.id, reverse=True)[:5]
    ]

    return OrganizationDashboardStats(
        total_employees=total_employees,
        active_employees=active_employees,
        departments=len(dept_counts),
        designations=designations,
        hr_admins=hr_admins,
        pending_leave_requests=pending_leave_requests,
        pending_approvals=pending_approvals,
        monthly_payroll=monthly_payroll,
        assets=0,
        department_headcount=department_headcount,
        recent_employees=recent_employees,
    )


@router.get("/me/detail", response_model=OrganizationDetail)
def get_my_organization_detail(
    current_user=Depends(get_current_payroll_operator),
    db: Session = Depends(get_db),
):
    """Richer org profile for the "My Organization" page — extends the plain
    /me record with computed workforce counts and the org_admin's identity,
    since this standalone platform has no subscription/billing module to
    source plan/seat data from."""
    from app.core.dependencies import get_organization_id
    from app.modules.organizations.models import Organization
    from app.modules.auth.models import User, UserRole
    from app.modules.payroll.models import PayrollEmployee

    org_id = get_organization_id(current_user)
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if org is None:
        raise NotFoundException("Organization", "id")

    admin = (
        db.query(User)
        .filter(User.organization_id == org_id, User.role == UserRole.ORG_ADMIN)
        .order_by(User.created_at.asc())
        .first()
    )
    total_employees = db.query(PayrollEmployee).filter(PayrollEmployee.organization_id == org_id).count()
    active_employees = (
        db.query(PayrollEmployee)
        .filter(PayrollEmployee.organization_id == org_id, PayrollEmployee.status == "Active")
        .count()
    )
    hr_admins = (
        db.query(User)
        .filter(User.organization_id == org_id, User.role == UserRole.PAYROLL_ADMIN)
        .count()
    )

    return OrganizationDetail(
        id=org.id,
        name=org.organization_name,
        code=org.organization_code,
        status="active" if org.is_active else "deactivated",
        admin_name=f"{admin.first_name} {admin.last_name}".strip() if admin else None,
        admin_email=admin.email if admin else None,
        industry=org.industry,
        address=org.address,
        created_at=org.created_at,
        total_employees=total_employees,
        active_employees=active_employees,
        hr_admins=hr_admins,
    )


# ── Super Admin only ────────────────────────────────────────────────────────

@router.get("/", response_model=OrganizationListResponse)
def list_organizations(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    search: str = Query("", description="Search by name or code"),
    include_inactive: bool = Query(True),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.organizations.models import Organization

    query = db.query(Organization)
    if search:
        like = f"%{search}%"
        query = query.filter(
            (Organization.organization_name.ilike(like))
            | (Organization.organization_code.ilike(like))
        )
    if not include_inactive:
        query = query.filter(Organization.is_active == True)
    total = query.count()
    orgs = (
        query.order_by(Organization.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return OrganizationListResponse(organizations=orgs, total=total)


@router.get("/{organization_id}", response_model=OrganizationResponse)
def get_organization(
    organization_id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.organizations.models import Organization
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if org is None:
        raise NotFoundException("Organization", "id")
    return org


@router.put("/{organization_id}", response_model=OrganizationResponse)
def update_organization(
    organization_id: int,
    data: OrganizationUpdate,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.organizations.models import Organization
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if org is None:
        raise NotFoundException("Organization", "id")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(org, field, value)
    db.commit()
    db.refresh(org)
    logger.info("Super Admin %s updated organization %s", current_user.email, org.organization_code)
    return org


@router.post("/", response_model=OrganizationResponse)
def create_organization(
    data: OrganizationBase,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.core.code_generation import generate_organization_code
    from app.modules.organizations.models import Organization

    code = generate_organization_code(data.organization_name, db)
    org = Organization(
        organization_name=data.organization_name,
        organization_code=code,
        industry=data.industry,
        address=data.address,
        email=data.email,
        phone=data.phone,
        tax_no=data.tax_no,
        registration_number=data.registration_number,
        is_active=True,
        created_by_user_id=current_user.id,
    )
    db.add(org)
    db.commit()
    db.refresh(org)
    logger.info("Super Admin %s created organization %s (%s)", current_user.email, org.organization_name, code)
    return org


@router.patch("/{organization_id}/status", response_model=OrganizationResponse)
def update_organization_status(
    organization_id: int,
    is_active: bool,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.organizations.models import Organization
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if org is None:
        raise NotFoundException("Organization", "id")
    org.is_active = is_active
    db.commit()
    db.refresh(org)
    logger.info(
        "Super Admin %s set organization %s is_active=%s",
        current_user.email, org.organization_code, is_active,
    )
    return org


@router.delete("/{organization_id}", response_model=SuccessResponse)
def delete_organization(
    organization_id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    """Hard-delete an organization and ALL of its data.

    Every payroll/org-scoped table is deleted in dependency order inside one
    transaction (PostgreSQL enforces the FKs, so order matters). Global
    tables that are NOT org-scoped (platform_settings, platform_statutory_rates,
    payroll_jurisdiction_packs) are untouched. Super Admin only.
    """
    from app.modules.organizations.models import Organization

    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if org is None:
        raise NotFoundException("Organization", "id")

    org_name = org.organization_name
    org_code = org.organization_code

    # Child → parent order. Org-scoped rows only. Three tables (inbound
    # attachments, policy sub-rules) carry no organization_id column — they
    # are scoped transitively via message_id / policy_id and get deleted
    # through an IN-subquery against their parent. Those subqueries MUST run
    # before their parent table is deleted, or the parent rows are gone and
    # the subquery selects nothing (orphans on FK-disabled SQLite, FK
    # violation on Postgres).
    from sqlalchemy import text

    _org_direct = [
        "payroll_email_settings",
        "payroll_update_form_submissions",
        "payroll_update_form_sends",
        "payroll_update_forms",
        "payroll_custom_field_definitions",
        "payroll_activity_log",
        "payroll_leave_requests",
        "payroll_leave_allocations",
        "payroll_compliance_documents",
        "payroll_tax_slabs",
        "payroll_contribution_rates",
        "payroll_company_compliance",
        "payroll_holidays",
        "payroll_enterprise_jurisdictions",
        "payslip_items",
        "payroll_attendance_records",
        "payroll_runs",
        "payroll_employees",
    ]
    _org_via_parent = [
        ("payroll_inbound_attachments", "message_id", "payroll_inbound_messages"),
        ("payroll_policy_integrations", "policy_id", "payroll_policies"),
        ("payroll_policy_overtime_rules", "policy_id", "payroll_policies"),
        ("payroll_policy_leave_rules", "policy_id", "payroll_policies"),
        ("payroll_policy_employee_categories", "policy_id", "payroll_policies"),
    ]

    # Inbound attachments reference inbound messages — must go first, before
    # the messages themselves are removed. Policy sub-rules must be removed
    # before payroll_policies. So the via-parent deletes run BEFORE any
    # parent-table row is deleted; payroll_policies is removed in the
    # second, explicit pass below.
    for table, fk_column, parent in _org_via_parent:
        db.execute(
            text(
                f'DELETE FROM "{table}" WHERE "{fk_column}" IN '
                f'(SELECT id FROM "{parent}" WHERE organization_id = :org_id)'
            ),
            {"org_id": organization_id},
        )
    for table in _org_direct:
        db.execute(
            text(f'DELETE FROM "{table}" WHERE organization_id = :org_id'),
            {"org_id": organization_id},
        )
    db.execute(
        text('DELETE FROM "payroll_inbound_messages" WHERE organization_id = :org_id'),
        {"org_id": organization_id},
    )
    db.execute(
        text('DELETE FROM "payroll_policies" WHERE organization_id = :org_id'),
        {"org_id": organization_id},
    )

    # Login users + their action tokens (users has ondelete CASCADE from org).
    db.execute(
        text('DELETE FROM "security_action_tokens" WHERE organization_id = :org_id'),
        {"org_id": organization_id},
    )
    db.execute(
        text('DELETE FROM "users" WHERE organization_id = :org_id'),
        {"org_id": organization_id},
    )

    db.delete(org)
    db.commit()
    logger.info(
        "Super Admin %s hard-deleted organization %s (%s) and all its data",
        current_user.email, org_name, org_code,
    )
    return {"message": f"Organization '{org_name}' and all of its data deleted."}
