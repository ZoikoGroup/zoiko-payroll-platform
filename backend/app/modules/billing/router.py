"""
modules/billing/router.py
--------------------------
Tenant-facing, read-only billing endpoints — blueprint §7's minimal
tenant-facing read API. Mounted with prefix "/billing" (see main.py):

    GET /billing/plans           → PUBLISHED plan versions + entitlement flags
    GET /billing/my-subscription → current org's subscription + entitlement flags

No create/update/checkout endpoints here — see billing/admin_router.py for
the Super Admin CRUD surface. Entitlement checks are NOT wired into any
router outside app/modules/billing/ in this task; that wiring is a
separate, later task.
"""

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.core.exceptions import NotFoundException
from app.database import get_db
from app.modules.billing import entitlements, plan_catalog
from app.modules.billing.models import BillingPlan
from app.modules.billing.schemas import (
    BillingMySubscriptionResponse,
    BillingPublishedPlanResponse,
)

router = APIRouter(prefix="/billing", tags=["Billing"])


@router.get("/plans", response_model=List[BillingPublishedPlanResponse])
def list_published_plans(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """One entry per plan (CORE/PROFESSIONAL/BUSINESS/ENTERPRISE) that
    currently has a PUBLISHED version. A plan with no PUBLISHED version yet
    (e.g. still DRAFT/APPROVED) is simply omitted, not returned as null/empty —
    there is nothing publishable to show a tenant for it yet."""
    results = []
    for plan in db.query(BillingPlan).order_by(BillingPlan.id).all():
        version = plan_catalog.get_published_plan_version(db, plan.code)
        if version is None:
            continue
        results.append(
            BillingPublishedPlanResponse(
                plan_id=plan.id,
                code=plan.code,
                name=plan.name,
                plan_version_id=version.id,
                version=version.version,
                published_at=version.published_at,
                feature_set=version.feature_set,
                scale_limits=version.scale_limits,
                entitlement_flags=plan_catalog.list_entitlement_flags(db, version.id),
            )
        )
    return results


@router.get("/my-subscription", response_model=BillingMySubscriptionResponse)
def get_my_subscription(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """The caller's own organization's subscription + resolved entitlement
    flags. 404 when the org has no subscription row at all — e.g. before
    any commercial relationship has been set up for it."""
    subscription = entitlements.get_active_subscription(db, current_user.organization_id)
    if subscription is None:
        raise NotFoundException("Subscription")

    return BillingMySubscriptionResponse(
        subscription=subscription,
        entitlement_flags=plan_catalog.list_entitlement_flags(db, subscription.plan_version_id),
    )
