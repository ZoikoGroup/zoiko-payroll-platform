"""
modules/billing/trial_lifecycle.py
------------------------------------
Sales-cycle default: every new organization starts as an EVALUATION
workspace whose BillingSubscription.status is TRIALING for a fixed trial
window (current_period_start→current_period_end). No billing tables exist
for a converted org — conversion is an explicit super-admin action, never
automatic.

This module owns the derived trial lifecycle state and its two mutations:

    ACTIVE          → status == TRIALING and current_period_end in the future
    GRACE_READONLY  → status == TRIALING and current_period_end in the past
                      but still within the grace window
                      (grace_period_ends_at == NULL counts: the sweep sets it
                      the first time it observes expiry, and the org is
                      already read-only from the moment the trial ends)
    CLOSED          → past grace_period_ends_at → Organization.is_active=False
                      (reuses the existing suspension flag; there is NO
                      parallel "closed" flag on Organization)

Design rules (mirroring the blueprint's entitlement discipline):
  - resolve_trial_stage() is a pure function of one subscription row — no
    separate status drift; an org that was converted (status=ACTIVE) simply
    stops being a trial (return None).
  - run_trial_expiry_sweep() never changes BillingSubscription.status.
    TRIALING → ACTIVE happens ONLY in convert_trial_to_paid(), and nothing
    else in the app changes a subscription away from TRIALING.
  - Audit-first: every transition records a BillingCommercialAuditEvent row
    (TRIAL_GRACE_STARTED / TRIAL_CLOSED / TRIAL_CONVERTED) committed in the
    same transaction as the state change, exactly like entitlements.py does.
  - The sweep must never create a BillingInvoice row (invoicing is a
    separate, opt-in step after conversion).
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from app.config import settings
from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.billing.models import (
    BillingCommercialAuditEvent,
    BillingPlanVersion,
    BillingSubscription,
    SubscriptionStatus,
)

logger = logging.getLogger("zoiko_payroll.billing.trial_lifecycle")


TRIAL_STAGE_ACTIVE = "ACTIVE"
TRIAL_STAGE_GRACE_READONLY = "GRACE_READONLY"
TRIAL_STAGE_CLOSED = "CLOSED"


def _now() -> datetime:
    return datetime.utcnow()


def resolve_trial_stage(subscription: Optional[BillingSubscription]) -> Optional[str]:
    """Pure derivation of an org's trial stage from one subscription row.

    Returns None for a non-trial org (no subscription, or a subscription
    that already left TRIALING via conversion). Works purely off
    current_period_end / grace_period_ends_at and the clock — no new
    Organization column, no status writes.
    """
    if subscription is None or subscription.status != SubscriptionStatus.TRIALING.value:
        return None

    now = _now()
    if subscription.current_period_end > now:
        return TRIAL_STAGE_ACTIVE

    grace_end = subscription.grace_period_ends_at
    if grace_end is not None and grace_end <= now:
        return TRIAL_STAGE_CLOSED

    return TRIAL_STAGE_GRACE_READONLY


def _audit(db, organization_id, actor_user_id, event_type, check_id: str, payload: dict) -> None:
    db.add(
        BillingCommercialAuditEvent(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            event_type=event_type,
            payload={**payload, "check_id": check_id},
        )
    )


def run_trial_expiry_sweep(db) -> dict:
    """Day-30 (grace) sweep over every TRIALING subscription.

    Idempotent: repeated runs re-observe the same rows but only transition
    (and only audit) an org that isn't already in the target state, so
    re-running never double-records a TRIAL_CLOSED event.
    """
    from app.modules.organizations.models import Organization

    result = {"scanned": 0, "grace_started": [], "closed": []}
    subscriptions = (
        db.query(BillingSubscription)
        .filter(BillingSubscription.status == SubscriptionStatus.TRIALING.value)
        .all()
    )
    result["scanned"] = len(subscriptions)

    for sub in subscriptions:
        org_id = sub.organization_id
        check_id = f"trial-{org_id}-sub-{sub.id}"
        stage = resolve_trial_stage(sub)

        if stage == TRIAL_STAGE_GRACE_READONLY and sub.grace_period_ends_at is None:
            sub.grace_period_ends_at = sub.current_period_end + timedelta(
                days=settings.TRIAL_GRACE_PERIOD_DAYS
            )
            _audit(
                db,
                org_id,
                None,
                "TRIAL_GRACE_STARTED",
                check_id,
                {
                    "trial_period_end": sub.current_period_end.isoformat(),
                    "grace_period_ends_at": sub.grace_period_ends_at.isoformat(),
                    "grace_days": settings.TRIAL_GRACE_PERIOD_DAYS,
                },
            )
            db.commit()
            logger.info("[trial-sweep] org=%s entered GRACE_READONLY", org_id)
            result["grace_started"].append(org_id)

        elif stage == TRIAL_STAGE_CLOSED:
            org = db.query(Organization).filter(Organization.id == org_id).first()
            if org is not None and org.is_active:
                org.is_active = False
                _audit(
                    db,
                    org_id,
                    None,
                    "TRIAL_CLOSED",
                    check_id,
                    {
                        "grace_period_ends_at": sub.grace_period_ends_at.isoformat(),
                        "closed_at": _now().isoformat(),
                    },
                )
                db.commit()
                logger.info("[trial-sweep] org=%s CLOSED (is_active=False)", org_id)
                result["closed"].append(org_id)

    return result


def convert_trial_to_paid(
    db,
    organization_id: int,
    plan_version_id: int,
    actor_user_id: int,
) -> BillingSubscription:
    """Manual, explicit conversion of a TRIALING subscription to a paid one.

    The ONLY code path that moves a subscription from TRIALING → ACTIVE.
    Sets the org's workspace to PRODUCTION, points the subscription at the
    paid plan version, opens a fresh billing period, reactivates the org
    (undoing a sweep-applied CLOSED), and records TRIAL_CONVERTED. Does not
    create an invoice — invoicing stays a separate step.
    """
    from app.modules.organizations.models import Organization

    subscription = (
        db.query(BillingSubscription)
        .filter(
            BillingSubscription.organization_id == organization_id,
            BillingSubscription.status == SubscriptionStatus.TRIALING.value,
        )
        .first()
    )
    if subscription is None:
        raise BadRequestException(
            "No TRIALING subscription for this organization; only a trial can be converted."
        )

    version = (
        db.query(BillingPlanVersion)
        .filter(BillingPlanVersion.id == plan_version_id)
        .first()
    )
    if version is None:
        raise NotFoundException("Plan version", plan_version_id)

    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if org is None:
        raise NotFoundException("Organization", organization_id)

    now = _now()
    subscription.status = SubscriptionStatus.ACTIVE.value
    subscription.plan_version_id = plan_version_id
    subscription.current_period_start = now
    subscription.current_period_end = now + timedelta(days=30)
    subscription.grace_period_ends_at = None

    org.workspace_type = "PRODUCTION"
    org.billing_onboarding_status = "ACTIVE"
    if not org.is_active:
        org.is_active = True

    _audit(
        db,
        organization_id,
        actor_user_id,
        "TRIAL_CONVERTED",
        f"trial-{organization_id}-sub-{subscription.id}",
        {
            "plan_version_id": plan_version_id,
            "converted_at": now.isoformat(),
            "billing_authority": subscription.billing_authority,
        },
    )
    db.commit()
    db.refresh(subscription)
    return subscription