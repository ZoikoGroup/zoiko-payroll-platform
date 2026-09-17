"""
modules/billing/admin_router.py
---------------------------------
Zoiko Commercial admin surface — blueprint §7. Mounted with prefix
"/super-admin/billing" (see main.py), authenticated the same way every
other super-admin endpoint is (app.core.dependencies.get_current_super_admin,
same as super_admin/router.py).

Every write endpoint here goes through a plan_catalog.py/entitlements.py
service function that records its own billing_commercial_audit_events row
before committing — audit-first, the same discipline modules/assist already
applies to its own audit table. No route in this file adds an entitlement
check to any OTHER module's router — that wiring is a separate, later task.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_super_admin
from app.core.exceptions import BadRequestException, NotFoundException
from app.database import get_db
from app.modules.billing import entitlements, plan_catalog, trial_lifecycle
from app.modules.billing.models import BillingCommercialAuditEvent, BillingPlanVersion, PlanVersionStatus
from app.modules.billing.schemas import (
    BillingAuditEventListResponse,
    BillingEntitlementFlagCreateRequest,
    BillingEntitlementFlagResponse,
    BillingEntitlementOverrideCreateRequest,
    BillingEntitlementOverrideResponse,
    BillingPlanCreate,
    BillingPlanResponse,
    BillingPlanVersionCreateRequest,
    BillingPlanVersionResponse,
    BillingPlanVersionStatusTransition,
    BillingSubscriptionResponse,
    ConvertTrialRequest,
    TrialExpirySweepResult,
)

router = APIRouter(prefix="/super-admin/billing", tags=["Super Admin Billing"])


# ── Plan catalog ─────────────────────────────────────────────────────────

@router.post("/plans", response_model=BillingPlanResponse)
def create_plan(
    data: BillingPlanCreate,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    return plan_catalog.create_plan(db, data.code, data.name, actor_user_id=current_user.id)


@router.post("/plans/{plan_id}/versions", response_model=BillingPlanVersionResponse)
def create_plan_version(
    plan_id: int,
    data: BillingPlanVersionCreateRequest,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    return plan_catalog.create_plan_version(
        db, plan_id, data.feature_set, data.scale_limits, actor_user_id=current_user.id
    )


@router.put("/plan-versions/{plan_version_id}/status", response_model=BillingPlanVersionResponse)
def transition_plan_version_status(
    plan_version_id: int,
    data: BillingPlanVersionStatusTransition,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    """Three transitions exist: DRAFT->APPROVED, APPROVED->PUBLISHED, and
    PUBLISHED->RETIRED. Anything else (including re-requesting the version's
    current status, or editing a PUBLISHED version) is rejected with 400 —
    checked against the version's actual current status up front so the
    error names the real problem instead of falling through to whichever
    service function happens to run first.
    """
    version = db.query(BillingPlanVersion).filter(BillingPlanVersion.id == plan_version_id).first()
    if version is None:
        raise NotFoundException("Plan version", plan_version_id)

    target = data.status.value if hasattr(data.status, "value") else data.status

    if target == PlanVersionStatus.APPROVED.value:
        return plan_catalog.approve_plan_version(db, plan_version_id, actor_user_id=current_user.id)

    if target == PlanVersionStatus.PUBLISHED.value:
        return plan_catalog.publish_plan_version(db, plan_version_id, published_by_user_id=current_user.id)

    if target == PlanVersionStatus.RETIRED.value:
        return plan_catalog.retire_plan_version(db, plan_version_id, actor_user_id=current_user.id)

    raise BadRequestException(
        f"Unsupported status transition to '{target}'. Only DRAFT->APPROVED, "
        f"APPROVED->PUBLISHED, and PUBLISHED->RETIRED are allowed (current status: {version.status})."
    )


@router.post(
    "/plan-versions/{plan_version_id}/entitlement-flags",
    response_model=BillingEntitlementFlagResponse,
)
def add_entitlement_flag(
    plan_version_id: int,
    data: BillingEntitlementFlagCreateRequest,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    return plan_catalog.add_entitlement_flag(
        db, plan_version_id, data.feature_key, data.limit_value, actor_user_id=current_user.id
    )


# ── Entitlement overrides ────────────────────────────────────────────────

@router.get(
    "/organizations/{organization_id}/entitlement-overrides",
    response_model=List[BillingEntitlementOverrideResponse],
)
def list_entitlement_overrides(
    organization_id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    return entitlements.list_entitlement_overrides(db, organization_id)


@router.post(
    "/organizations/{organization_id}/entitlement-overrides",
    response_model=BillingEntitlementOverrideResponse,
)
def create_entitlement_override(
    organization_id: int,
    data: BillingEntitlementOverrideCreateRequest,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    return entitlements.create_entitlement_override(
        db,
        organization_id=organization_id,
        feature_key=data.feature_key,
        limit_value=data.limit_value,
        granted_by_user_id=current_user.id,
        reason=data.reason,
        expires_at=data.expires_at,
    )


# ── Trial lifecycle (Prompt 5) ────────────────────────────────────────────

@router.post("/trial-expiry-run", response_model=TrialExpirySweepResult)
def run_trial_expiry_sweep(
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    """Day-30 expiry sweep: expire trials into GRACE_READONLY, close orgs
    whose grace window has lapsed (TRIAL_CLOSED → Organization.is_active=False).
    Audit-first, idempotent, and never creates a BillingInvoice row — the same
    path the scheduled job runs on a timer (see billing/scheduler.py). None of
    the state changes here mix realm with the _audit event: the events are
    committed in the same transaction as the transition they record."""
    return trial_lifecycle.run_trial_expiry_sweep(db)


@router.post(
    "/organizations/{organization_id}/convert-trial",
    response_model=BillingSubscriptionResponse,
)
def convert_trial_to_paid(
    organization_id: int,
    data: ConvertTrialRequest,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    """Convert a TRIALING subscription to an ACTIVE paid one — the ONLY path
    that takes a subscription away from TRIALING. Sets workspace_type=PRODUCTION,
    points the subscription at the paid plan version, opens a fresh 30-day
    period, reactivates the org, and audits TRIAL_CONVERTED. No invoice is
    created here (separate, explicit step)."""
    return trial_lifecycle.convert_trial_to_paid(
        db,
        organization_id=organization_id,
        plan_version_id=data.plan_version_id,
        actor_user_id=current_user.id,
    )


# ── Audit log ────────────────────────────────────────────────────────────

@router.get("/audit-events", response_model=BillingAuditEventListResponse)
def list_audit_events(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    organization_id: Optional[int] = Query(None),
    event_type: Optional[str] = Query(None),
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    query = db.query(BillingCommercialAuditEvent)
    if organization_id is not None:
        query = query.filter(BillingCommercialAuditEvent.organization_id == organization_id)
    if event_type:
        query = query.filter(BillingCommercialAuditEvent.event_type == event_type)

    total = query.count()
    events = (
        query.order_by(BillingCommercialAuditEvent.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return BillingAuditEventListResponse(events=events, total=total)
