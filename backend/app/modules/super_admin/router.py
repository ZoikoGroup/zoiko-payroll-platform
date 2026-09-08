"""
modules/super_admin/router.py
-----------------------------
Super Admin endpoints: platform dashboard stats, platform-wide user
management (org admins / payroll admins / employees), admin-initiated
password resets, and PlatformSetting configuration.
"""

import logging
import os
import uuid
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core import object_storage
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
    SuperAdminUserListResponse,
    SuperAdminUserResponse,
)
from app.modules.payroll.schemas import (
    JurisdictionPackResponse, JurisdictionPackUpsert,
    CanonicalTaxSlabResponse, CanonicalTaxSlabUpsert,
    CanonicalContributionRateResponse, CanonicalContributionRateUpsert,
    TaxConfigurationAuditResponse, ActiveTaxConfigurationResponse,
    EmployerTaxProfileResponse, EmployerTaxProfileUpsert,
    ReciprocityRuleResponse, ReciprocityRuleUpsert,
    SourceArtifactResponse, SourceArtifactCreate,
    PapAlgorithmAssetResponse,
    GermanyPapReleaseResponse, GermanyPapReleaseGateStatusResponse,
    GermanyPapReleaseSourceFinalityUpdate, GermanyPapReleaseLicensingUpdate,
    GermanyPapReleaseGoldenVectorUpdate, GermanyPapReleaseNotesUpdate,
    GermanyPapReleaseRejectRequest, GermanyPapReleaseRollbackRequest,
    GermanyHealthFundResponse, GermanyHealthFundCreate, GermanyHealthFundU1TariffResponse,
    GermanyAccidentInsuranceProfileResponse, GermanyAccidentInsuranceProfileCreate,
    GermanyHealthFundU1TariffCreate,
    GermanyContributionCeilingResponse, GermanyContributionCeilingCreate,
    GermanyPvConfigurationResponse, GermanyPvConfigurationCreate,
    GermanyEarningTaxabilityRuleResponse, GermanyEarningTaxabilityRuleCreate,
    GermanyOvertimePremiumCategoryResponse, GermanyOvertimePremiumCategoryCreate,
    GermanyOvertimeGrundlohnCapResponse, GermanyOvertimeGrundlohnCapCreate,
    GermanyChurchTaxExceptionResponse, GermanyChurchTaxExceptionCreate,
    LocalityRateResponse, LocalityRateUpsert,
    ReportTemplateResponse, ReportTemplateUpsert, ReportTemplateStatusUpdate,
    ReportTemplateComponentResponse, ReportTemplateComponentUpsert,
    ReportTemplateFieldResponse, ReportTemplateFieldUpsert,
    AvailableComponentItem, AvailableDataFieldItem,
    FilingCalendarResponse, FilingCalendarUpsert, FilingCalendarStatusUpdate,
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

    raw_token, expires_at = auth_service._issue_action_token(
        db, user.email, user.organization_id, SecurityActionPurpose.RESET
    )
    link = auth_service._action_link(SecurityActionPurpose.RESET, raw_token)
    auth_service._send_reset_email(
        db, user, link,
        expires_at_local=auth_service._format_expiry_local(expires_at),
        reference_id=auth_service._reference_id(raw_token),
    )
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


# The old "Global statutory rate table" endpoints (seed-defaults, list,
# create, update, delete against GlobalStatutoryRate) were removed here —
# that table was never read by the live payroll engine (see its former
# model docstring). The Statutory Rates page now reads canonical tax-pack
# data directly via GET /compliance/active-tax-configuration below;
# editing happens on the Compliance page. list_organization_contribution_rates
# right below is unaffected — it always read the real, live ContributionRate
# table and still does.

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
#
# DEPRECATION NOTICE (Phase 9 cleanup inventory, see
# backend/scripts/HIERARCHY_V2_CLEANUP_INVENTORY.md): this whole
# JurisdictionPack/ContributionRate/TaxSlab surface is what the
# app/modules/payroll/hierarchy/* (Tax/TaxVersion/TaxRule) engine is meant
# to eventually replace for organizations cut over to it. NOT deprecated
# functionally here — every real organization's live payroll still runs on
# this exact code path (zero orgs are on the hierarchy engine yet). Keep
# fully working until the inventory doc's per-org cutover is actually done.

@router.get("/compliance/jurisdictions", summary="Countries/states the app supports or already has configured")
def list_compliance_jurisdictions(current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    from app.modules.super_admin import service as sa_service

    return sa_service.list_known_jurisdictions(db)


@router.get(
    "/compliance/engine-fallback-defaults",
    summary="Read-only: every hardcoded fallback value the payroll engine uses when no canonical/org rate exists",
)
def get_engine_fallback_defaults(current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    from app.modules.payroll.engine.fallback_registry import get_engine_fallback_inventory

    return get_engine_fallback_inventory()


@router.get(
    "/compliance/readiness",
    summary="Read-only: which organizations are actually ready for fail-fast validation, per jurisdiction — the audit that was missing before India's brief enablement attempt broke 35 tests",
)
def get_jurisdiction_readiness(current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    from app.modules.payroll import service as payroll_service

    rows = []
    orgs = db.query(Organization).filter(Organization.is_active == True).all()  # noqa: E712
    for org in orgs:
        country = payroll_service._resolve_org_country(db, org.id)
        if not country:
            rows.append({
                "organizationId": org.id, "organizationName": org.organization_name,
                "country": None, "ready": False, "missingKeys": [], "missingSlabs": False,
                "reason": "No jurisdiction configured for this organization yet.",
            })
            continue
        readiness = payroll_service.check_jurisdiction_readiness(db, org.id, country)
        rows.append({
            "organizationId": org.id, "organizationName": org.organization_name,
            **readiness,
        })
    return {"organizations": rows}


@router.get(
    "/compliance/jurisdiction-summary",
    summary="One row per jurisdiction with real counts (tax/policy packs, statutory rates, orgs) — powers the jurisdiction card grid",
)
def get_jurisdiction_summary(current_user=Depends(get_current_super_admin), db: Session = Depends(get_db)):
    from app.modules.super_admin import service as sa_service

    return sa_service.get_jurisdiction_summary(db)


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
    packType: Optional[str] = Query(None, description="Filter to 'tax' or 'policy' packs"),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.list_all_jurisdiction_packs(
        db, country=country, state=state, status=status, search=search, pack_type=packType,
    )


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


@router.put(
    "/compliance/policies/{id}/approve", response_model=JurisdictionPackResponse, response_model_by_alias=True,
    summary="Record the calling Super Admin as this pack's approver (maker-checker: must differ from the last editor before Active)",
)
def approve_compliance_policy(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.set_jurisdiction_pack_approver(db, id, actor_id=current_user.id)


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


@router.get(
    "/compliance/policies/{id}/eligible-organizations", response_model=List[ApplicableOrganization],
    summary="Organizations whose own jurisdiction matches this pack's, for the Assign picker",
)
def get_compliance_policy_eligible_organizations(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.get_organizations_eligible_for_pack(db, id)


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

    result = payroll_service.assign_pack_to_organizations(db, id, payload.organizationIds, actor_id=current_user.id)
    if result["isTax"]:
        return {
            "message": f"Tax applied to {result['updated']} organization(s) — "
                       f"rates synced for {result['ratesSynced']} of them."
        }
    return {
        "message": f"Policy applied to {result['updated']} organization(s) — "
                   f"locked fields synced for {result['ratesSynced']} of them."
    }


# Hard-delete route intentionally removed (Production-Grade Refactor:
# Remove Hardcoded Payroll Fallbacks, Enforce Active Compliance Packs).
# Production compliance packs should never be permanently destroyed —
# use PUT /compliance/policies/{id}/status to Deactivate/Retire instead,
# which every resolver already treats as unresolvable (status=="Active" is
# the only status every pack-lookup function filters on). The underlying
# service function (payroll/service.py's hard_delete_jurisdiction_pack)
# is kept, unexposed, for one-off maintenance use only — see its own
# docstring before reintroducing a route to it.


# ── Report Templates (jurisdiction-wide, Super Admin-authored statutory
# report blueprints — separate from JurisdictionPack, since a report
# template has no rates/slabs/org-assignment) ────────────────────────────
# Reuses app.modules.payroll's ReportTemplate model/schemas/service
# functions directly, exactly like the /compliance/policies/* block above
# reuses JurisdictionPack — no parallel model or business logic here.

@router.get(
    "/report-templates", response_model=List[ReportTemplateResponse], response_model_by_alias=True,
    summary="Cross-jurisdiction report template list (latest version per template)",
)
def list_report_templates(
    country: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    reportingYear: Optional[str] = Query(None),
    reportType: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.list_report_templates(
        db, country=country, state=state, reporting_year=reportingYear, report_type=reportType,
        status=status, search=search,
    )


@router.get(
    "/report-templates/available-components", response_model=List[AvailableComponentItem],
    summary="Components a report of this type may have — never a generic unrelated dropdown",
)
def get_available_report_components(
    reportType: str = Query(...),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.get_available_report_components(reportType)


@router.get(
    "/report-templates/available-data-fields", response_model=List[AvailableDataFieldItem],
    summary="Real, already-computed data fields a template field may map to for this jurisdiction — never free-typed",
)
def get_available_report_data_fields(
    jurisdictionCountry: str = Query(...),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.get_available_report_data_fields(jurisdictionCountry)


# NOTE: the filing-calendar list route (a literal "filing-calendar" path
# segment) is registered here, BEFORE "/report-templates/{id}" below —
# FastAPI/Starlette matches routes in registration order, and an {id}
# route registered first would swallow "filing-calendar" as an attempted
# integer id, producing a 422 instead of ever reaching this handler
# (found and fixed during the Super Admin stabilization audit). See the
# "Statutory Filing Calendar" section further down for the rest of this
# resource's endpoints (PUT/status), which don't collide with {id}.
@router.get(
    "/report-templates/filing-calendar", response_model=List[FilingCalendarResponse], response_model_by_alias=True,
    summary="List statutory filing-calendar entries",
)
def list_filing_calendar_entries(
    country: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    reportType: Optional[str] = Query(None),
    reportingYear: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.list_filing_calendar(
        db, country=country, state=state, report_type=reportType, reporting_year=reportingYear, status=status,
    )


@router.get(
    "/report-templates/{id}", response_model=ReportTemplateResponse, response_model_by_alias=True,
    summary="Full template detail with nested components and fields",
)
def get_report_template_detail(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.get_report_template_detail(db, id)


@router.put(
    "/report-templates", response_model=ReportTemplateResponse, response_model_by_alias=True,
    summary="Create a report template, or a new version of an existing one",
)
def upsert_report_template(
    payload: ReportTemplateUpsert,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.upsert_report_template(db, payload, actor_id=current_user.id)


@router.get(
    "/report-templates/by-key/{template_key}/versions", response_model=List[ReportTemplateResponse], response_model_by_alias=True,
    summary="Full version history for one report template, oldest first",
)
def get_report_template_versions(
    template_key: str,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.get_report_template_versions(db, template_key)


@router.put(
    "/report-templates/{id}/status", response_model=ReportTemplateResponse, response_model_by_alias=True,
    summary="Advance/supersede a report template's lifecycle status",
)
def set_report_template_status(
    id: int,
    payload: ReportTemplateStatusUpdate,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.set_report_template_status(db, id, payload.status, actor_id=current_user.id)


@router.put(
    "/report-templates/{id}/approve", response_model=ReportTemplateResponse, response_model_by_alias=True,
    summary="Record the calling Super Admin as this template's approver (maker-checker: must differ from the last editor before Published/Active)",
)
def approve_report_template(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.set_report_template_approver(db, id, actor_id=current_user.id)


@router.get(
    "/report-templates/{id}/audit", response_model=List[TaxConfigurationAuditResponse], response_model_by_alias=True,
    summary="Audit trail for one report template",
)
def get_report_template_audit(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.get_report_template_audit(db, id)


@router.delete(
    "/report-templates/{id}", response_model=SuccessResponse,
    summary="Permanently delete a report template — only allowed with no generated-report history and not Published/Active",
)
def hard_delete_report_template(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    result = payroll_service.hard_delete_report_template(db, id)
    return {"message": f"{result['templateKey']} v{result['version']} permanently deleted."}


@router.put(
    "/report-templates/{template_id}/components", response_model=ReportTemplateComponentResponse, response_model_by_alias=True,
    summary="Add or update a component on a report template",
)
def upsert_report_template_component(
    template_id: int,
    payload: ReportTemplateComponentUpsert,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.upsert_report_component(db, template_id, payload, actor_id=current_user.id)


@router.delete(
    "/report-templates/components/{component_id}", response_model=SuccessResponse,
    summary="Remove a component (and its fields) from a report template",
)
def delete_report_template_component(
    component_id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    payroll_service.delete_report_component(db, component_id, actor_id=current_user.id)
    return {"message": "Component deleted."}


@router.put(
    "/report-templates/components/{component_id}/fields", response_model=ReportTemplateFieldResponse, response_model_by_alias=True,
    summary="Add or update a field on a report template component (source_column validated against the real-data allow-list)",
)
def upsert_report_template_field(
    component_id: int,
    payload: ReportTemplateFieldUpsert,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.upsert_report_field(db, component_id, payload, actor_id=current_user.id)


@router.delete(
    "/report-templates/fields/{field_id}", response_model=SuccessResponse,
    summary="Remove a field from a report template component",
)
def delete_report_template_field(
    field_id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    payroll_service.delete_report_field(db, field_id, actor_id=current_user.id)
    return {"message": "Field deleted."}


# ── Statutory Filing Calendar (jurisdiction-wide; Super Admin-authored) ──
# A genuinely new asset — Organizations read this to know when a report is
# actually due (e.g. India Form 138's Q1-Q4 dates); never hardcoded
# client-side. The GET list route lives earlier in this file (before
# "/report-templates/{id}") to avoid the route-ordering collision fixed
# during the Super Admin stabilization audit — only the PUT routes remain
# here.

@router.put(
    "/report-templates/filing-calendar", response_model=FilingCalendarResponse, response_model_by_alias=True,
    summary="Create or correct a filing-calendar entry (a correction is a new version, never an edit of a published due date)",
)
def upsert_filing_calendar_entry(
    payload: FilingCalendarUpsert,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.upsert_filing_calendar_entry(db, payload, actor_id=current_user.id)


@router.put(
    "/report-templates/filing-calendar/{id}/status", response_model=FilingCalendarResponse, response_model_by_alias=True,
    summary="Advance/supersede a filing-calendar entry's lifecycle status",
)
def set_filing_calendar_entry_status(
    id: int,
    payload: FilingCalendarStatusUpdate,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.set_filing_calendar_status(db, id, payload.status, actor_id=current_user.id)


# ── Canonical Tax Configuration (government-mandated values; Super Admin-only) ──
# organization_id IS NULL rows on payroll_tax_slabs/payroll_contribution_rates —
# the single source of truth these tax packs' rules resolve to. Org-scoped
# rows (what the engine actually reads) are populated FROM these via
# sync_org_rates_from_canonical (Milestone 2) — not duplicated tables.

@router.get(
    "/compliance/tax-configuration/slabs", response_model=List[CanonicalTaxSlabResponse], response_model_by_alias=True,
    summary="List canonical tax slabs for a pack or country",
)
def list_canonical_tax_slabs(
    jurisdictionPackId: Optional[int] = Query(None),
    country: Optional[str] = Query(None),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.list_canonical_tax_slabs(db, jurisdiction_pack_id=jurisdictionPackId, country=country)


@router.put(
    "/compliance/tax-configuration/slabs", response_model=CanonicalTaxSlabResponse, response_model_by_alias=True,
    summary="Create or update a canonical tax slab row (Super Admin only)",
)
def upsert_canonical_tax_slab(
    payload: CanonicalTaxSlabUpsert,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.upsert_canonical_tax_slab(db, payload, actor_id=current_user.id)


@router.delete(
    "/compliance/tax-configuration/slabs/{id}", response_model=SuccessResponse,
    summary="Permanently delete a canonical tax slab row (Super Admin only)",
)
def delete_canonical_tax_slab(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    payroll_service.delete_canonical_tax_slab(db, id, actor_id=current_user.id)
    return {"message": "Tax slab deleted."}


@router.get(
    "/compliance/tax-configuration/contribution-rates", response_model=List[CanonicalContributionRateResponse], response_model_by_alias=True,
    summary="List canonical contribution rates for a pack or country",
)
def list_canonical_contribution_rates(
    jurisdictionPackId: Optional[int] = Query(None),
    country: Optional[str] = Query(None),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.list_canonical_contribution_rates(db, jurisdiction_pack_id=jurisdictionPackId, country=country)


@router.put(
    "/compliance/tax-configuration/contribution-rates", response_model=CanonicalContributionRateResponse, response_model_by_alias=True,
    summary="Create or update a canonical contribution rate row (Super Admin only)",
)
def upsert_canonical_contribution_rate(
    payload: CanonicalContributionRateUpsert,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.upsert_canonical_contribution_rate(db, payload, actor_id=current_user.id)


@router.delete(
    "/compliance/tax-configuration/contribution-rates/{id}", response_model=SuccessResponse,
    summary="Permanently delete a canonical contribution rate row (Super Admin only)",
)
def delete_canonical_contribution_rate(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    payroll_service.delete_canonical_contribution_rate(db, id, actor_id=current_user.id)
    return {"message": "Contribution rate deleted."}


@router.get(
    "/compliance/tax-configuration/audit", response_model=List[TaxConfigurationAuditResponse], response_model_by_alias=True,
    summary="Audit trail for canonical tax configuration changes",
)
def list_tax_configuration_audit(
    jurisdictionPackId: Optional[int] = Query(None),
    entityType: Optional[str] = Query(None),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.list_tax_configuration_audit(db, jurisdiction_pack_id=jurisdictionPackId, entity_type=entityType)


@router.get(
    "/compliance/active-tax-configuration", response_model=ActiveTaxConfigurationResponse, response_model_by_alias=True,
    summary="Read-only: the canonical rates/slabs from whichever tax pack is currently Active for this jurisdiction",
)
def get_active_tax_configuration(
    country: str = Query(...),
    state: Optional[str] = Query(None),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.get_active_tax_configuration_for_display(db, country, state=state)


# ── US: Employer-Specific Tax Profiles (SUI and similar) ─────────────────
# Tenant-specific, agency-assigned rates — NOT canonical ContributionRate
# data (see EmployerTaxProfile's model docstring). Managed here (Super
# Admin / Tax Ops), not by the org itself, since entering these requires
# the agency's rate notice as evidence — the same reasoning the standard's
# §11.1 "SUI Employer Rates" Super Admin module is built around.

@router.get(
    "/compliance/employer-tax-profiles", response_model=List[EmployerTaxProfileResponse], response_model_by_alias=True,
    summary="List employer-specific tax profiles (SUI and similar), optionally filtered",
)
def list_employer_tax_profiles(
    organizationId: Optional[int] = Query(None),
    jurisdictionId: Optional[str] = Query(None),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.list_employer_tax_profiles(db, organization_id=organizationId, jurisdiction_id=jurisdictionId)


@router.put(
    "/compliance/employer-tax-profiles", response_model=EmployerTaxProfileResponse, response_model_by_alias=True,
    summary="Create or update an employer-specific tax profile (Super Admin only)",
)
def upsert_employer_tax_profile(
    payload: EmployerTaxProfileUpsert,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.upsert_employer_tax_profile(db, payload, actor_id=current_user.id)


@router.delete(
    "/compliance/employer-tax-profiles/{id}", response_model=SuccessResponse,
    summary="Permanently delete an employer-specific tax profile (Super Admin only)",
)
def delete_employer_tax_profile(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    payroll_service.delete_employer_tax_profile(db, id, actor_id=current_user.id)
    return {"message": "Employer tax profile deleted."}


# ── Germany: Accident Insurance Profile maker-checker (Phase 8AJ, 2nd pass)
# Separate from EmployerTaxProfile above — see
# models.GermanyAccidentInsuranceProfile's own docstring. Same
# Super-Admin-only security tier; organization-scoped (unlike every
# other Germany registry, all global) because accident insurance is
# carrier/employer-specific (spec DE-D06).

@router.get(
    "/compliance/germany/accident-insurance-profiles",
    response_model=List[GermanyAccidentInsuranceProfileResponse], response_model_by_alias=True,
    summary="List Germany accident-insurance profiles, optionally filtered by organization",
)
def list_germany_accident_insurance_profiles(
    organizationId: Optional[int] = Query(None),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.list_germany_accident_insurance_profiles(db, organization_id=organizationId)


@router.get(
    "/compliance/germany/accident-insurance-profiles/{id}",
    response_model=GermanyAccidentInsuranceProfileResponse, response_model_by_alias=True,
    summary="Get a single Germany accident-insurance profile",
)
def get_germany_accident_insurance_profile(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.get_germany_accident_insurance_profile_by_id(db, id)


@router.post(
    "/compliance/germany/accident-insurance-profiles",
    response_model=GermanyAccidentInsuranceProfileResponse, response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    summary="Record a new DRAFT Germany accident-insurance profile version for one organization",
)
def create_germany_accident_insurance_profile(
    payload: GermanyAccidentInsuranceProfileCreate,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.create_germany_accident_insurance_profile_record(db, payload, actor_id=current_user.id)


@router.put(
    "/compliance/germany/accident-insurance-profiles/{id}/approve",
    response_model=GermanyAccidentInsuranceProfileResponse, response_model_by_alias=True,
    summary="Record that the calling Super Admin approves this accident-insurance profile",
)
def approve_germany_accident_insurance_profile(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.set_germany_accident_insurance_profile_approver(db, id, actor_id=current_user.id)


@router.put(
    "/compliance/germany/accident-insurance-profiles/{id}/status",
    response_model=GermanyAccidentInsuranceProfileResponse, response_model_by_alias=True,
    summary="Advance a Germany accident-insurance profile's lifecycle status",
)
def set_germany_accident_insurance_profile_status(
    id: int,
    status_value: str = Query(..., alias="status"),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.set_germany_accident_insurance_profile_status(db, id, status_value, actor_id=current_user.id)


# ── US: Cross-State Reciprocity ───────────────────────────────────────────

@router.get(
    "/compliance/reciprocity-rules", response_model=List[ReciprocityRuleResponse], response_model_by_alias=True,
    summary="List all cross-state reciprocity agreements",
)
def list_reciprocity_rules(
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.list_reciprocity_rules(db)


@router.put(
    "/compliance/reciprocity-rules", response_model=ReciprocityRuleResponse, response_model_by_alias=True,
    summary="Create or update a cross-state reciprocity agreement (Super Admin only)",
)
def upsert_reciprocity_rule(
    payload: ReciprocityRuleUpsert,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.upsert_reciprocity_rule(db, payload, actor_id=current_user.id)


@router.delete(
    "/compliance/reciprocity-rules/{id}", response_model=SuccessResponse,
    summary="Permanently delete a cross-state reciprocity agreement (Super Admin only)",
)
def delete_reciprocity_rule(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    payroll_service.delete_reciprocity_rule(db, id, actor_id=current_user.id)
    return {"message": "Reciprocity rule deleted."}


# ── US: Locality (county/municipal/school-district) Tax Rates ────────────
# Manually-entered, same pattern as Employer Tax Profiles above (no
# licensed geocoding provider is wired up — Tax Ops types in a real
# published rate against a known locality code, evidenced optionally by a
# SourceArtifact). See service.py's get_locality_rate.

@router.get(
    "/compliance/locality-rates", response_model=List[LocalityRateResponse], response_model_by_alias=True,
    summary="List locality tax rates for a country/state",
)
def list_locality_rates(
    country: str = Query("US"),
    state: str = Query(...),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.list_locality_rates(db, country, state)


@router.put(
    "/compliance/locality-rates", response_model=LocalityRateResponse, response_model_by_alias=True,
    summary="Create or update a locality tax rate (Super Admin only)",
)
def upsert_locality_rate(
    payload: LocalityRateUpsert,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.upsert_locality_rate(db, payload, actor_id=current_user.id)


@router.delete(
    "/compliance/locality-rates/{id}", response_model=SuccessResponse,
    summary="Permanently delete a locality tax rate (Super Admin only)",
)
def delete_locality_rate(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    payroll_service.delete_locality_rate(db, id, actor_id=current_user.id)
    return {"message": "Locality rate deleted."}


# ── Source Evidence (ZP-TAX-US-2026-001 §14) ──────────────────────────────
# Platform-wide, not US-only — one row per official publication a
# statutory value was taken from.

@router.get(
    "/compliance/source-artifacts", response_model=List[SourceArtifactResponse], response_model_by_alias=True,
    summary="List all source evidence artifacts",
)
def list_source_artifacts(
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.list_source_artifacts(db)


@router.post(
    "/compliance/source-artifacts", response_model=SourceArtifactResponse, response_model_by_alias=True,
    summary="Record a new source evidence artifact (Super Admin only)",
)
def create_source_artifact(
    payload: SourceArtifactCreate,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.create_source_artifact(db, payload, actor_id=current_user.id)


@router.put(
    "/compliance/source-artifacts/{id}/review", response_model=SourceArtifactResponse, response_model_by_alias=True,
    summary="Record that the calling Super Admin has reviewed this source artifact",
)
def review_source_artifact(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.mark_source_artifact_reviewed(db, id, reviewer_id=current_user.id)


# ── Germany: BMF PAP Algorithm Asset (ZP-TAX-DE-2026-001 §5, §17, §18) ────
# Container/evidence/lifecycle only — see models.PapAlgorithmAsset and
# service.py's PAP functions. Every endpoint here is Super-Admin-only:
# this is canonical Germany statutory configuration, a different security
# domain from tenant-owned employee data (Phase 2) — no tenant payroll
# operator role can reach any endpoint in this section.

@router.get(
    "/compliance/germany/pap-assets", response_model=List[PapAlgorithmAssetResponse], response_model_by_alias=True,
    summary="List Germany BMF PAP algorithm assets",
)
def list_pap_assets(
    tax_year: Optional[str] = Query(None, alias="taxYear"),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.list_pap_assets(db, jurisdiction_country="DE", tax_year=tax_year)


@router.get(
    "/compliance/germany/pap-assets/resolve", response_model=Optional[PapAlgorithmAssetResponse],
    response_model_by_alias=True, summary="Resolve the PUBLISHED PAP asset applicable on a payroll date",
)
def resolve_pap_asset(
    payroll_date: date = Query(..., alias="payrollDate"),
    tax_year: Optional[str] = Query(None, alias="taxYear"),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.resolve_germany_pap_asset(db, payroll_date, jurisdiction_country="DE", tax_year=tax_year)


@router.get(
    "/compliance/germany/pap-assets/{id}", response_model=PapAlgorithmAssetResponse, response_model_by_alias=True,
    summary="Get a single Germany PAP algorithm asset",
)
def get_pap_asset(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.get_pap_asset_by_id(db, id)


@router.post(
    "/compliance/germany/pap-assets", response_model=PapAlgorithmAssetResponse, response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a new DRAFT Germany PAP algorithm asset (raw source content + metadata)",
)
async def ingest_pap_asset(
    tax_year: str = Form(..., alias="taxYear"),
    pap_version: str = Form(..., alias="papVersion"),
    effective_from: date = Form(..., alias="effectiveFrom"),
    effective_to: Optional[date] = Form(None, alias="effectiveTo"),
    source_agency: str = Form(..., alias="sourceAgency"),
    source_title: str = Form(..., alias="sourceTitle"),
    source_url: Optional[str] = Form(None, alias="sourceUrl"),
    source_publication_date: Optional[date] = Form(None, alias="sourcePublicationDate"),
    file: UploadFile = File(..., description="The official BMF PAP source file/content"),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    contents = await file.read()
    ext = os.path.splitext(file.filename or "")[1] or ".bin"
    unique_name = f"{uuid.uuid4().hex}{ext}"
    stored_path = object_storage.save_upload(
        subdir="germany_pap_assets", filename=unique_name, data=contents,
    )
    return payroll_service.ingest_pap_asset(
        db, jurisdiction_country="DE", tax_year=tax_year, pap_version=pap_version,
        effective_from=effective_from, effective_to=effective_to,
        source_content=contents, source_agency=source_agency, source_title=source_title,
        source_url=source_url, source_publication_date=source_publication_date,
        source_content_path=stored_path, actor_id=current_user.id,
    )


@router.put(
    "/compliance/germany/pap-assets/{id}/approve", response_model=PapAlgorithmAssetResponse,
    response_model_by_alias=True, summary="Record that the calling Super Admin approves this PAP asset",
)
def approve_pap_asset(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.set_pap_asset_approver(db, id, actor_id=current_user.id)


@router.put(
    "/compliance/germany/pap-assets/{id}/status", response_model=PapAlgorithmAssetResponse,
    response_model_by_alias=True, summary="Advance a Germany PAP asset's lifecycle status",
)
def set_pap_asset_status(
    id: int,
    status_value: str = Query(..., alias="status"),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.set_pap_asset_status(db, id, status_value, actor_id=current_user.id)


# ── Germany: BMF PAP Production Release Governance (Phase 8G-1) ──────────
# Internal release/activation governance, entirely separate from the PAP
# asset lifecycle above (see models.GermanyPapRelease's own docstring).
# Every endpoint here is Super-Admin-only, same security domain as the
# PAP asset section — no tenant payroll operator role can reach any
# endpoint in this section, and none of these endpoints can activate
# Germany PAP in production: activate_pap_release only flips this
# governance row's own status and never touches resolve_pap_executor().

@router.get(
    "/compliance/germany/pap-releases", response_model=List[GermanyPapReleaseResponse], response_model_by_alias=True,
    summary="List Germany PAP production-release governance records",
)
def list_pap_releases(
    tax_year: Optional[str] = Query(None, alias="taxYear"),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.list_pap_releases(db, jurisdiction_country="DE", tax_year=tax_year)


@router.get(
    "/compliance/germany/pap-releases/{id}", response_model=GermanyPapReleaseResponse, response_model_by_alias=True,
    summary="Get a single Germany PAP release governance record",
)
def get_pap_release(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.get_pap_release_by_id(db, id)


@router.get(
    "/compliance/germany/pap-releases/{id}/gate-status", response_model=GermanyPapReleaseGateStatusResponse,
    response_model_by_alias=True, summary="Preview the compound production gate for a release (read-only)",
)
def get_pap_release_gate_status(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    result = payroll_service.evaluate_pap_release_gate(db, id)
    return {
        "releaseId": id, "gates": result.gates,
        "failedGates": list(result.failed_gates), "isActivationEligible": result.is_activation_eligible,
    }


@router.post(
    "/compliance/germany/pap-assets/{pap_asset_id}/release", response_model=GermanyPapReleaseResponse,
    response_model_by_alias=True, status_code=status.HTTP_201_CREATED,
    summary="Start a production release/activation-governance attempt for a PAP asset",
)
def create_pap_release(
    pap_asset_id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.create_pap_release(db, pap_asset_id, actor_id=current_user.id)


@router.put(
    "/compliance/germany/pap-releases/{id}/source-identity", response_model=GermanyPapReleaseResponse,
    response_model_by_alias=True, summary="Record source-identity verification evidence",
)
def record_pap_release_source_identity(
    id: int,
    body: GermanyPapReleaseNotesUpdate,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.record_pap_release_source_identity(db, id, actor_id=current_user.id, notes=body.notes)


@router.put(
    "/compliance/germany/pap-releases/{id}/source-hash", response_model=GermanyPapReleaseResponse,
    response_model_by_alias=True, summary="Record independent re-verification of the bound source hash",
)
def record_pap_release_source_hash(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.record_pap_release_source_hash_verification(db, id, actor_id=current_user.id)


@router.put(
    "/compliance/germany/pap-releases/{id}/source-finality", response_model=GermanyPapReleaseResponse,
    response_model_by_alias=True, summary="Record source-finality evidence (independent of PAP_SOURCE_FINALITY)",
)
def record_pap_release_source_finality(
    id: int,
    body: GermanyPapReleaseSourceFinalityUpdate,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.record_pap_release_source_finality(
        db, id, actor_id=current_user.id, status=body.status,
        authority=body.authority, reference=body.reference, notes=body.notes,
    )


@router.put(
    "/compliance/germany/pap-releases/{id}/licensing", response_model=GermanyPapReleaseResponse,
    response_model_by_alias=True, summary="Record licensing/commercial-use authorization evidence",
)
def record_pap_release_licensing(
    id: int,
    body: GermanyPapReleaseLicensingUpdate,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.record_pap_release_licensing(
        db, id, actor_id=current_user.id, status=body.status, authority=body.authority, reference=body.reference,
        authorization_date=body.authorizationDate, effective_date=body.effectiveDate, expiry_date=body.expiryDate,
        evidence_location=body.evidenceLocation, evidence_hash=body.evidenceHash, notes=body.notes,
    )


@router.put(
    "/compliance/germany/pap-releases/{id}/golden-vectors", response_model=GermanyPapReleaseResponse,
    response_model_by_alias=True, summary="Record golden-vector certification bound to this release's exact hash",
)
def record_pap_release_golden_vectors(
    id: int,
    body: GermanyPapReleaseGoldenVectorUpdate,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.record_pap_release_golden_vectors(
        db, id, actor_id=current_user.id, source_sha256=body.sourceSha256, notes=body.notes,
    )


@router.put(
    "/compliance/germany/pap-releases/{id}/security-certification", response_model=GermanyPapReleaseResponse,
    response_model_by_alias=True, summary="Record security certification",
)
def record_pap_release_security_certification(
    id: int,
    body: GermanyPapReleaseNotesUpdate,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.record_pap_release_security_certification(db, id, actor_id=current_user.id, notes=body.notes)


@router.put(
    "/compliance/germany/pap-releases/{id}/ready", response_model=GermanyPapReleaseResponse,
    response_model_by_alias=True, summary="Mark a release ready for an independent checker",
)
def mark_pap_release_ready(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.mark_pap_release_ready(db, id, actor_id=current_user.id)


@router.put(
    "/compliance/germany/pap-releases/{id}/approve", response_model=GermanyPapReleaseResponse,
    response_model_by_alias=True, summary="Approve a release (maker-checker: must differ from preparer)",
)
def approve_pap_release(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.approve_pap_release(db, id, actor_id=current_user.id)


@router.put(
    "/compliance/germany/pap-releases/{id}/reject", response_model=GermanyPapReleaseResponse,
    response_model_by_alias=True, summary="Reject a release back to NOT_READY",
)
def reject_pap_release(
    id: int,
    body: GermanyPapReleaseRejectRequest,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.reject_pap_release(db, id, actor_id=current_user.id, reason=body.reason)


@router.post(
    "/compliance/germany/pap-releases/{id}/activate", response_model=GermanyPapReleaseResponse,
    response_model_by_alias=True,
    summary="Activate a release — requires every compound gate satisfied AND a distinct activator",
)
def activate_pap_release(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.activate_pap_release(db, id, actor_id=current_user.id)


@router.post(
    "/compliance/germany/pap-releases/{id}/rollback/request", response_model=GermanyPapReleaseResponse,
    response_model_by_alias=True, summary="Request rollback of an ACTIVE release (maker-checker step 1 of 2)",
)
def request_pap_rollback(
    id: int,
    body: GermanyPapReleaseRollbackRequest,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.request_pap_rollback(db, id, actor_id=current_user.id, reason=body.reason)


@router.post(
    "/compliance/germany/pap-releases/{id}/rollback/reject", response_model=GermanyPapReleaseResponse,
    response_model_by_alias=True, summary="Reject a requested rollback — the release remains ACTIVE",
)
def reject_pap_rollback(
    id: int,
    body: GermanyPapReleaseRejectRequest,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.reject_pap_rollback(db, id, actor_id=current_user.id, reason=body.reason)


@router.post(
    "/compliance/germany/pap-releases/{id}/rollback/approve", response_model=GermanyPapReleaseResponse,
    response_model_by_alias=True,
    summary="Approve a requested rollback (maker-checker step 2 of 2, distinct from requester); optionally restore a prior activated release",
)
def approve_pap_rollback(
    id: int,
    body: GermanyPapReleaseRollbackRequest,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    rolled_back, restored = payroll_service.approve_pap_rollback(
        db, id, actor_id=current_user.id, target_release_id=body.targetReleaseId,
    )
    return rolled_back


# ── Germany: Krankenkasse (Health Fund) Registry (ZP-TAX-DE-2026-001 §11) ─
# Configuration/registry only — see models.GermanyHealthFund and
# service.py's health-fund functions. Every endpoint here is Super-Admin-
# only, same security domain as the PAP asset section above (canonical
# Germany statutory configuration, not tenant-owned data) — no tenant
# payroll operator role can reach any endpoint in this section.

@router.get(
    "/compliance/germany/health-funds", response_model=List[GermanyHealthFundResponse], response_model_by_alias=True,
    summary="List Germany health-fund registry records",
)
def list_health_funds(
    health_fund_id: Optional[str] = Query(None, alias="healthFundId"),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.list_health_funds(db, health_fund_id=health_fund_id)


@router.get(
    "/compliance/germany/health-funds/{health_fund_id}/resolve", response_model=Optional[GermanyHealthFundResponse],
    response_model_by_alias=True, summary="Resolve the PUBLISHED rate for one fund applicable on a date",
)
def resolve_health_fund(
    health_fund_id: str,
    as_of: Optional[date] = Query(None, alias="as_of"),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.resolve_germany_health_fund(db, health_fund_id, as_of=as_of)


# ── Germany: U1 Tariff (Sickness Reimbursement) (Phase 8W) ────────────
# Configuration/registry only — see models.GermanyHealthFundU1Tariff and
# service.py's U1 tariff functions. Every endpoint here is Super-Admin-only,
# same security domain as the PAP asset / health-fund sections above.
#
# NOTE: the list route below (a literal "u1-tariffs" path segment) MUST be
# registered before "/compliance/germany/health-funds/{id}" further down —
# FastAPI/Starlette matches routes in registration order, and an {id}
# route registered first would swallow "u1-tariffs" as an attempted
# integer id, producing a 422 instead of ever reaching this handler
# (found and fixed during the Super Admin stabilization audit).

@router.get(
    "/compliance/germany/health-funds/u1-tariffs", response_model=List[GermanyHealthFundU1TariffResponse],
    response_model_by_alias=True, summary="List Germany health-fund U1 tariff records",
)
def list_u1_tariffs(
    health_fund_id: Optional[str] = Query(None, alias="healthFundId"),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.list_u1_tariffs(db, health_fund_id=health_fund_id)


@router.get(
    "/compliance/germany/health-funds/{id}", response_model=GermanyHealthFundResponse, response_model_by_alias=True,
    summary="Get a single Germany health-fund registry record",
)
def get_health_fund(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.get_health_fund_by_id(db, id)


@router.post(
    "/compliance/germany/health-funds", response_model=GermanyHealthFundResponse, response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    summary="Record a new DRAFT Germany health-fund rate version",
)
def create_health_fund(
    payload: GermanyHealthFundCreate,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.create_health_fund_record(db, payload, actor_id=current_user.id)


@router.put(
    "/compliance/germany/health-funds/{id}/approve", response_model=GermanyHealthFundResponse,
    response_model_by_alias=True, summary="Record that the calling Super Admin approves this health-fund record",
)
def approve_health_fund(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.set_health_fund_approver(db, id, actor_id=current_user.id)


@router.put(
    "/compliance/germany/health-funds/{id}/status", response_model=GermanyHealthFundResponse,
    response_model_by_alias=True, summary="Advance a Germany health-fund record's lifecycle status",
)
def set_health_fund_status(
    id: int,
    status_value: str = Query(..., alias="status"),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.set_health_fund_status(db, id, status_value, actor_id=current_user.id)


@router.get(
    "/compliance/germany/health-funds/u1-tariffs/{id}", response_model=GermanyHealthFundU1TariffResponse,
    response_model_by_alias=True, summary="Get a single Germany health-fund U1 tariff record",
)
def get_u1_tariff(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.get_u1_tariff_by_id(db, id)


@router.post(
    "/compliance/germany/health-funds/u1-tariffs", response_model=GermanyHealthFundU1TariffResponse,
    response_model_by_alias=True, status_code=status.HTTP_201_CREATED,
    summary="Record a new DRAFT Germany health-fund U1 tariff version",
)
def create_u1_tariff(
    payload: GermanyHealthFundU1TariffCreate,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.create_u1_tariff_record(db, payload, actor_id=current_user.id)


@router.put(
    "/compliance/germany/health-funds/u1-tariffs/{id}/approve", response_model=GermanyHealthFundU1TariffResponse,
    response_model_by_alias=True, summary="Record that the calling Super Admin approves this U1 tariff record",
)
def approve_u1_tariff(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.set_u1_tariff_approver(db, id, actor_id=current_user.id)


@router.put(
    "/compliance/germany/health-funds/u1-tariffs/{id}/status", response_model=GermanyHealthFundU1TariffResponse,
    response_model_by_alias=True, summary="Advance a Germany U1 tariff record's lifecycle status",
)
def set_u1_tariff_status(
    id: int,
    status_value: str = Query(..., alias="status"),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.set_u1_tariff_status(db, id, status_value, actor_id=current_user.id)


# ── Germany: Contribution Ceiling Configuration (ZP-TAX-DE-2026-001 §9) ──
# Configuration/registry only — see models.GermanyContributionCeiling and
# service.py's contribution-ceiling functions. Every endpoint here is
# Super-Admin-only, same security domain as the PAP asset / health-fund
# sections above.

@router.get(
    "/compliance/germany/contribution-ceilings", response_model=List[GermanyContributionCeilingResponse],
    response_model_by_alias=True, summary="List Germany contribution ceiling configuration records",
)
def list_contribution_ceilings(
    branch: Optional[str] = Query(None),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.list_contribution_ceilings(db, branch=branch)


@router.get(
    "/compliance/germany/contribution-ceilings/resolve", response_model=Optional[GermanyContributionCeilingResponse],
    response_model_by_alias=True, summary="Resolve the PUBLISHED ceiling for one branch applicable on a date",
)
def resolve_contribution_ceiling(
    branch: str = Query(...),
    as_of: Optional[date] = Query(None),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.resolve_germany_contribution_ceiling(db, branch, as_of=as_of)


@router.get(
    "/compliance/germany/contribution-ceilings/{id}", response_model=GermanyContributionCeilingResponse,
    response_model_by_alias=True, summary="Get a single Germany contribution ceiling record",
)
def get_contribution_ceiling(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.get_contribution_ceiling_by_id(db, id)


@router.post(
    "/compliance/germany/contribution-ceilings", response_model=GermanyContributionCeilingResponse,
    response_model_by_alias=True, status_code=status.HTTP_201_CREATED,
    summary="Record a new DRAFT Germany contribution ceiling version",
)
def create_contribution_ceiling(
    payload: GermanyContributionCeilingCreate,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.create_contribution_ceiling_record(db, payload, actor_id=current_user.id)


@router.put(
    "/compliance/germany/contribution-ceilings/{id}/approve", response_model=GermanyContributionCeilingResponse,
    response_model_by_alias=True,
    summary="Record that the calling Super Admin approves this contribution ceiling record",
)
def approve_contribution_ceiling(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.set_contribution_ceiling_approver(db, id, actor_id=current_user.id)


@router.put(
    "/compliance/germany/contribution-ceilings/{id}/status", response_model=GermanyContributionCeilingResponse,
    response_model_by_alias=True, summary="Advance a Germany contribution ceiling record's lifecycle status",
)
def set_contribution_ceiling_status(
    id: int,
    status_value: str = Query(..., alias="status"),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.set_contribution_ceiling_status(db, id, status_value, actor_id=current_user.id)


# ── Germany: PV (Long-Term Care Insurance) Child/Saxony Configuration ────
# Configuration/registry only — see models.GermanyPvConfiguration and
# service.py's PV configuration functions. Every endpoint here is
# Super-Admin-only, same security domain as the PAP asset / health-fund /
# contribution-ceiling sections above.

@router.get(
    "/compliance/germany/pv-configurations", response_model=List[GermanyPvConfigurationResponse],
    response_model_by_alias=True, summary="List Germany PV configuration records",
)
def list_pv_configurations(
    child_category: Optional[str] = Query(None, alias="childCategory"),
    is_saxony: Optional[bool] = Query(None, alias="isSaxony"),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.list_pv_configurations(db, child_category=child_category, is_saxony=is_saxony)


@router.get(
    "/compliance/germany/pv-configurations/resolve", response_model=Optional[GermanyPvConfigurationResponse],
    response_model_by_alias=True, summary="Resolve the PUBLISHED PV configuration for a child category and Saxony status",
)
def resolve_pv_configuration(
    child_category: str = Query(..., alias="childCategory"),
    is_saxony: bool = Query(..., alias="isSaxony"),
    as_of: Optional[date] = Query(None),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.resolve_germany_pv_configuration(db, child_category, is_saxony, as_of=as_of)


@router.get(
    "/compliance/germany/pv-configurations/{id}", response_model=GermanyPvConfigurationResponse,
    response_model_by_alias=True, summary="Get a single Germany PV configuration record",
)
def get_pv_configuration(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.get_pv_configuration_by_id(db, id)


@router.post(
    "/compliance/germany/pv-configurations", response_model=GermanyPvConfigurationResponse,
    response_model_by_alias=True, status_code=status.HTTP_201_CREATED,
    summary="Record a new DRAFT Germany PV configuration version",
)
def create_pv_configuration(
    payload: GermanyPvConfigurationCreate,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.create_pv_configuration_record(db, payload, actor_id=current_user.id)


@router.put(
    "/compliance/germany/pv-configurations/{id}/approve", response_model=GermanyPvConfigurationResponse,
    response_model_by_alias=True,
    summary="Record that the calling Super Admin approves this PV configuration record",
)
def approve_pv_configuration(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.set_pv_configuration_approver(db, id, actor_id=current_user.id)


@router.put(
    "/compliance/germany/pv-configurations/{id}/status", response_model=GermanyPvConfigurationResponse,
    response_model_by_alias=True, summary="Advance a Germany PV configuration record's lifecycle status",
)
def set_pv_configuration_status(
    id: int,
    status_value: str = Query(..., alias="status"),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.set_pv_configuration_status(db, id, status_value, actor_id=current_user.id)


# ── Germany: Earning/Deduction Taxability (ZP-TAX-DE-2026-001 §15, Phase 8T) ─
# Configuration/registry only — see models.GermanyEarningTaxabilityRule and
# service.py's earning-taxability functions. Every endpoint here is
# Super-Admin-only, same security domain as every other Germany registry
# section above.

@router.get(
    "/compliance/germany/earning-taxability-rules", response_model=List[GermanyEarningTaxabilityRuleResponse],
    response_model_by_alias=True, summary="List Germany earning/deduction taxability rules",
)
def list_earning_taxability_rules(
    earning_type: Optional[str] = Query(None, alias="earningType"),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.list_earning_taxability_rules(db, earning_type=earning_type)


@router.get(
    "/compliance/germany/earning-taxability-rules/resolve", response_model=Optional[GermanyEarningTaxabilityRuleResponse],
    response_model_by_alias=True, summary="Resolve the PUBLISHED taxability rule for one earning type",
)
def resolve_earning_taxability_rule(
    earning_type: str = Query(..., alias="earningType"),
    as_of: Optional[date] = Query(None),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.resolve_germany_earning_taxability_rule(db, earning_type, as_of=as_of)


@router.get(
    "/compliance/germany/earning-taxability-rules/{id}", response_model=GermanyEarningTaxabilityRuleResponse,
    response_model_by_alias=True, summary="Get a single Germany earning taxability rule",
)
def get_earning_taxability_rule(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.get_earning_taxability_rule_by_id(db, id)


@router.post(
    "/compliance/germany/earning-taxability-rules", response_model=GermanyEarningTaxabilityRuleResponse,
    response_model_by_alias=True, status_code=status.HTTP_201_CREATED,
    summary="Record a new DRAFT Germany earning taxability rule version",
)
def create_earning_taxability_rule(
    payload: GermanyEarningTaxabilityRuleCreate,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.create_earning_taxability_rule(db, payload, actor_id=current_user.id)


@router.put(
    "/compliance/germany/earning-taxability-rules/{id}/approve", response_model=GermanyEarningTaxabilityRuleResponse,
    response_model_by_alias=True,
    summary="Record that the calling Super Admin approves this earning taxability rule",
)
def approve_earning_taxability_rule(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.set_earning_taxability_rule_approver(db, id, actor_id=current_user.id)


@router.put(
    "/compliance/germany/earning-taxability-rules/{id}/status", response_model=GermanyEarningTaxabilityRuleResponse,
    response_model_by_alias=True, summary="Advance a Germany earning taxability rule's lifecycle status",
)
def set_earning_taxability_rule_status(
    id: int,
    status_value: str = Query(..., alias="status"),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.set_earning_taxability_rule_status(db, id, status_value, actor_id=current_user.id)


# ── Germany: Overtime/Shift-Premium Statutory Registries (Phase 8AD) ─────
# Configuration/registry only — see models.GermanyOvertimePremiumCategory /
# GermanyOvertimeGrundlohnCap and service.py's overtime-registry functions.
# Every endpoint here is Super-Admin-only, same security domain as every
# other Germany registry section above. GLOBAL statutory configuration —
# no organization_id anywhere on either table; tenant payroll operators
# have no route that can reach these functions.

@router.get(
    "/compliance/germany/overtime-premium-categories", response_model=List[GermanyOvertimePremiumCategoryResponse],
    response_model_by_alias=True, summary="List Germany overtime premium-category configuration records",
)
def list_overtime_premium_categories(
    category_code: Optional[str] = Query(None, alias="categoryCode"),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.list_overtime_premium_categories(db, category_code=category_code)


@router.get(
    "/compliance/germany/overtime-premium-categories/resolve", response_model=Optional[GermanyOvertimePremiumCategoryResponse],
    response_model_by_alias=True, summary="Resolve the PUBLISHED premium-category record applicable on a date",
)
def resolve_overtime_premium_category(
    category_code: str = Query(..., alias="categoryCode"),
    as_of: Optional[date] = Query(None),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.resolve_germany_overtime_premium_category(db, category_code, as_of=as_of)


@router.get(
    "/compliance/germany/overtime-premium-categories/{id}", response_model=GermanyOvertimePremiumCategoryResponse,
    response_model_by_alias=True, summary="Get a single Germany overtime premium-category record",
)
def get_overtime_premium_category(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.get_overtime_premium_category_by_id(db, id)


@router.post(
    "/compliance/germany/overtime-premium-categories", response_model=GermanyOvertimePremiumCategoryResponse,
    response_model_by_alias=True, status_code=status.HTTP_201_CREATED,
    summary="Record a new DRAFT Germany overtime premium-category version",
)
def create_overtime_premium_category(
    payload: GermanyOvertimePremiumCategoryCreate,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.create_overtime_premium_category_record(db, payload, actor_id=current_user.id)


@router.put(
    "/compliance/germany/overtime-premium-categories/{id}/approve", response_model=GermanyOvertimePremiumCategoryResponse,
    response_model_by_alias=True,
    summary="Record that the calling Super Admin approves this overtime premium-category record",
)
def approve_overtime_premium_category(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.set_overtime_premium_category_approver(db, id, actor_id=current_user.id)


@router.put(
    "/compliance/germany/overtime-premium-categories/{id}/status", response_model=GermanyOvertimePremiumCategoryResponse,
    response_model_by_alias=True, summary="Advance a Germany overtime premium-category record's lifecycle status",
)
def set_overtime_premium_category_status(
    id: int,
    status_value: str = Query(..., alias="status"),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.set_overtime_premium_category_status(db, id, status_value, actor_id=current_user.id)


@router.get(
    "/compliance/germany/overtime-grundlohn-caps", response_model=List[GermanyOvertimeGrundlohnCapResponse],
    response_model_by_alias=True, summary="List Germany overtime Grundlohn-cap configuration records",
)
def list_overtime_grundlohn_caps(
    dimension: Optional[str] = Query(None),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.list_overtime_grundlohn_caps(db, dimension=dimension)


@router.get(
    "/compliance/germany/overtime-grundlohn-caps/resolve", response_model=Optional[GermanyOvertimeGrundlohnCapResponse],
    response_model_by_alias=True, summary="Resolve the PUBLISHED Grundlohn cap applicable on a date",
)
def resolve_overtime_grundlohn_cap(
    dimension: str = Query(...),
    as_of: Optional[date] = Query(None),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.resolve_germany_overtime_grundlohn_cap(db, dimension, as_of=as_of)


@router.get(
    "/compliance/germany/overtime-grundlohn-caps/{id}", response_model=GermanyOvertimeGrundlohnCapResponse,
    response_model_by_alias=True, summary="Get a single Germany overtime Grundlohn-cap record",
)
def get_overtime_grundlohn_cap(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.get_overtime_grundlohn_cap_by_id(db, id)


@router.post(
    "/compliance/germany/overtime-grundlohn-caps", response_model=GermanyOvertimeGrundlohnCapResponse,
    response_model_by_alias=True, status_code=status.HTTP_201_CREATED,
    summary="Record a new DRAFT Germany overtime Grundlohn-cap version",
)
def create_overtime_grundlohn_cap(
    payload: GermanyOvertimeGrundlohnCapCreate,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.create_overtime_grundlohn_cap_record(db, payload, actor_id=current_user.id)


@router.put(
    "/compliance/germany/overtime-grundlohn-caps/{id}/approve", response_model=GermanyOvertimeGrundlohnCapResponse,
    response_model_by_alias=True,
    summary="Record that the calling Super Admin approves this overtime Grundlohn-cap record",
)
def approve_overtime_grundlohn_cap(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.set_overtime_grundlohn_cap_approver(db, id, actor_id=current_user.id)


@router.put(
    "/compliance/germany/overtime-grundlohn-caps/{id}/status", response_model=GermanyOvertimeGrundlohnCapResponse,
    response_model_by_alias=True, summary="Advance a Germany overtime Grundlohn-cap record's lifecycle status",
)
def set_overtime_grundlohn_cap_status(
    id: int,
    status_value: str = Query(..., alias="status"),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.set_overtime_grundlohn_cap_status(db, id, status_value, actor_id=current_user.id)


# ── Germany: Church tax (Kirchensteuer) Land matrix (Phase 8O) ───────────
# Read-only — see service.get_church_tax_matrix's own docstring for why
# this is NOT a DRAFT/APPROVED/PUBLISHED registry like the sections above.

@router.get(
    "/compliance/germany/church-tax", summary="Read-only Germany church-tax (Kirchensteuer) Land matrix",
)
def get_church_tax_matrix(
    current_user=Depends(get_current_super_admin),
):
    from app.modules.payroll import service as payroll_service

    return payroll_service.get_church_tax_matrix()


# ── Germany: Church Tax Exceptions (Phase 8AM) ─────────────────────────────
# Full DRAFT/VERIFIED/APPROVED/PUBLISHED/SUPERSEDED lifecycle with
# maker-checker, source evidence, and effective dating — mirrors
# GermanyHealthFund's global (non-org-scoped) pattern.

@router.get(
    "/compliance/germany/church-tax-exceptions",
    response_model=List[GermanyChurchTaxExceptionResponse],
    summary="List Germany church-tax exceptions (sub-Land overrides)",
)
def list_germany_church_tax_exceptions(
    land_code: Optional[str] = Query(None),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service
    return payroll_service.list_germany_church_tax_exceptions(db, land_code=land_code)


@router.post(
    "/compliance/germany/church-tax-exceptions",
    response_model=GermanyChurchTaxExceptionResponse,
    summary="Create a new DRAFT church-tax exception version",
)
def create_germany_church_tax_exception(
    payload: GermanyChurchTaxExceptionCreate,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service
    return payroll_service.create_germany_church_tax_exception_record(
        db, payload, actor_id=current_user.id
    )


@router.post(
    "/compliance/germany/church-tax-exceptions/{id}/approve",
    response_model=GermanyChurchTaxExceptionResponse,
    summary="Set approver (auto-advances VERIFIED -> APPROVED)",
)
def approve_germany_church_tax_exception(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service
    return payroll_service.set_germany_church_tax_exception_approver(db, id, actor_id=current_user.id)


@router.put(
    "/compliance/germany/church-tax-exceptions/{id}/status",
    response_model=GermanyChurchTaxExceptionResponse,
    summary="Advance lifecycle status (DRAFT->VERIFIED->APPROVED->PUBLISHED->SUPERSEDED)",
)
def set_germany_church_tax_exception_status(
    id: int,
    status: str = Query(..., pattern="^(DRAFT|VERIFIED|APPROVED|PUBLISHED|SUPERSEDED)$"),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service
    return payroll_service.set_germany_church_tax_exception_status(db, id, status, actor_id=current_user.id)


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
