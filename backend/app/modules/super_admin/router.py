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
    LocalityRateResponse, LocalityRateUpsert,
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


@router.delete(
    "/compliance/policies/{id}", response_model=SuccessResponse,
    summary="Permanently delete a policy/tax pack version — only allowed with no assigned organizations and no payroll history",
)
def hard_delete_compliance_policy(
    id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.payroll import service as payroll_service

    result = payroll_service.hard_delete_jurisdiction_pack(db, id)
    return {"message": f"{result['packId']} v{result['version']} permanently deleted."}


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
