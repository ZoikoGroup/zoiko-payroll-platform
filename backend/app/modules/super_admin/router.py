"""
modules/super_admin/router.py
-----------------------------
Super Admin endpoints: platform dashboard stats, platform-wide user
management (org admins / payroll admins / employees), admin-initiated
password resets, and PlatformSetting configuration.
"""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_super_admin
from app.database import get_db
from app.modules.auth.models import User
from app.modules.auth.schemas import SuccessResponse
from app.modules.organizations.models import Organization
from app.modules.super_admin.schemas import (
    DashboardStats,
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
        employees=db.query(User).filter(User.role == "employee").count(),
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
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.super_admin.models import GlobalStatutoryRate

    query = db.query(GlobalStatutoryRate)
    if country:
        query = query.filter(GlobalStatutoryRate.jurisdiction_country == country)
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
