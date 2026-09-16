"""
modules/billing/router.py
--------------------------
Tenant-facing billing endpoints — blueprint §7's minimal tenant-facing
read API plus Path 2 self-service paid checkout.

Mounted with prefix "/billing" (see main.py):

    GET  /billing/plans               → PUBLISHED plan versions + entitlement flags
    GET  /billing/my-subscription     → current org's subscription + entitlement flags
    GET  /billing/trial-status        → lightweight banner payload (null when none)
    POST /billing/checkout            → create a Stripe Checkout Session (PRODUCTION only)
    POST /billing/webhooks/stripe     → Stripe webhook handler (unauthenticated, signature-verified)

See billing/admin_router.py for the Super Admin CRUD surface.
"""

import logging
import uuid
from datetime import datetime
from typing import List, Optional

import stripe
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.core.dependencies import get_current_org_admin, get_current_user
from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.database import get_db
from app.modules.billing import entitlements, plan_catalog
from app.modules.billing.models import (
    BillingCommercialAuditEvent,
    BillingPlan,
    BillingPlanVersion,
    BillingSubscription,
    SubscriptionStatus,
)
from app.modules.billing.schemas import (
    BillingCheckoutRequest,
    BillingCheckoutResponse,
    BillingMySubscriptionResponse,
    BillingPublishedPlanResponse,
    BillingTrialStatusResponse,
)
from app.modules.payroll.engine.tax_resolver import get_jurisdiction_onboarding_block_reason

logger = logging.getLogger("zoiko_payroll.billing.router")

router = APIRouter(prefix="/billing", tags=["Billing"])

# Plan prices in cents — shared by checkout price creation and plans list.
PLAN_PRICES_CENTS = {"CORE": 0, "PROFESSIONAL": 5000, "BUSINESS": 15000, "ENTERPRISE": 50000}


# ── Read-only tenant endpoints ─────────────────────────────────────────────

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
                monthly_price_usd=PLAN_PRICES_CENTS.get(plan.code, 5000) / 100.0,
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


@router.get(
    "/trial-status",
    response_model=Optional[BillingTrialStatusResponse],
    summary="Lightweight subscription status for the trial banner",
)
def get_trial_status(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """The org's subscription fields the frontend trial banner needs (status
    + period bounds + plan code). Returns null rather than 404 when there is
    no subscription row — the banner should silently not render, not fail."""
    subscription = entitlements.get_active_subscription(db, current_user.organization_id)
    if subscription is None:
        return None

    plan_code = None
    if subscription.plan_version_id is not None:
        plan_version = (
            db.query(BillingPlanVersion)
            .filter(BillingPlanVersion.id == subscription.plan_version_id)
            .first()
        )
        if plan_version is not None:
            plan = (
                db.query(BillingPlan)
                .filter(BillingPlan.id == plan_version.plan_id)
                .first()
            )
            if plan is not None:
                plan_code = plan.code

    return BillingTrialStatusResponse(
        status=subscription.status,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        plan_code=plan_code,
    )


def _ensure_stripe_price(db: Session, version: BillingPlanVersion, plan: BillingPlan) -> str:
    """Ensure version has a stripe_price_id; create product and price on-the-fly if missing."""
    if version.stripe_price_id:
        return version.stripe_price_id

    if not settings.STRIPE_SECRET_KEY:
        raise BadRequestException("Stripe is not configured. STRIPE_SECRET_KEY is missing.")

    amount = PLAN_PRICES_CENTS.get(plan.code, 5000)
    product_name = f"{plan.name} v{version.version}"

    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        product = stripe.Product.create(name=product_name)
        price = stripe.Price.create(
            product=product.id,
            unit_amount=amount,
            currency="usd",
            recurring={"interval": "month"},
        )
        version.stripe_price_id = price.id
        db.commit()
        db.refresh(version)
        return price.id
    except stripe.error.StripeError as e:
        raise BadRequestException(f"Failed to create Stripe price for plan: {str(e)}")


# ── Self-service checkout (Path 2) ─────────────────────────────────────────

@router.post("/checkout", response_model=BillingCheckoutResponse)
def create_checkout_session(
    body: BillingCheckoutRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_org_admin),
):
    """Create a Stripe Checkout Session for the caller's organization.

    Allows both EVALUATION (trial) workspaces upgrading to paid PRODUCTION
    and active PRODUCTION workspaces subscribing or renewing.
    """
    from app.modules.organizations.models import Organization

    organization_id = current_user.organization_id
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if org is None:
        raise NotFoundException("Organization", organization_id)

    # Check 1: Plan must exist and have a published version
    plan = db.query(BillingPlan).filter(BillingPlan.code == body.plan_code).first()
    if plan is None:
        raise NotFoundException("Billing Plan", body.plan_code)

    version = plan_catalog.get_published_plan_version(db, body.plan_code)
    if version is None:
        raise NotFoundException("Published Plan Version for code", body.plan_code)

    # Ensure Stripe price exists (creates on-the-fly if missing)
    stripe_price_id = _ensure_stripe_price(db, version, plan)

    # Check 2: Jurisdiction onboarding block check
    block_reason = get_jurisdiction_onboarding_block_reason(db, org.country)
    if block_reason:
        raise BadRequestException(f"Jurisdiction onboarding blocked: {block_reason}")

    # Check 3: Prevent duplicate checkout if ALREADY on an ACTIVE paid subscription for a different plan
    active_sub = entitlements.get_active_subscription(db, organization_id)
    if active_sub and active_sub.status == SubscriptionStatus.ACTIVE.value:
        if active_sub.plan_version_id:
            sub_plan_version = (
                db.query(BillingPlanVersion)
                .filter(BillingPlanVersion.id == active_sub.plan_version_id)
                .first()
            )
            if sub_plan_version and sub_plan_version.plan_id != plan.id:
                raise ForbiddenException(
                    "Organization already has an active paid subscription for a different plan. "
                    "Contact support to change plans."
                )

    # Nonce prevents duplicate Checkout Sessions from double-clicks
    idempotency_key = f"checkout:{organization_id}:{version.id}:{uuid.uuid4()}"

    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            client_reference_id=str(organization_id),
            line_items=[{
                "price": stripe_price_id,
                "quantity": 1,
            }],
            metadata={
                "organization_id": str(organization_id),
                "plan_version_id": str(version.id),
            },
            success_url=settings.STRIPE_CHECKOUT_SUCCESS_URL,
            cancel_url=settings.STRIPE_CHECKOUT_CANCEL_URL,
            idempotency_key=idempotency_key,
        )
    except stripe.error.StripeError as e:
        raise BadRequestException(f"Stripe Checkout error: {str(e)}")

    return BillingCheckoutResponse(checkout_url=session.url)


# ── Stripe webhook handler ─────────────────────────────────────────────────

@router.post("/webhooks/stripe", include_in_schema=False)
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Unauthenticated endpoint — authentication is the Stripe signature.

    Handles:
      checkout.session.completed  → create/update sub to ACTIVE (only path to ACTIVE)
      invoice.paid                → renew current_period_end
      invoice.payment_failed      → set sub to PAST_DUE
      customer.subscription.deleted → set sub to CANCELLED

    Every processed event records a BillingCommercialAuditEvent with
    stripe_event_id set; duplicate delivery is detected by querying that
    column before doing any work.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        raise BadRequestException("Invalid webhook signature")

    event_dict = event.to_dict() if hasattr(event, "to_dict") else (event if isinstance(event, dict) else {})
    event_id = event_dict.get("id")
    event_type = event_dict.get("type")

    # Idempotency — reject replays we already processed
    if (
        db.query(BillingCommercialAuditEvent)
        .filter(BillingCommercialAuditEvent.stripe_event_id == event_id)
        .first()
    ):
        return {"status": "already processed"}

    data_object = (event_dict.get("data") or {}).get("object") or {}

    if event_type == "checkout.session.completed":
        org_id_str = (data_object.get("metadata") or {}).get("organization_id")
        version_id_str = (data_object.get("metadata") or {}).get("plan_version_id")

        if org_id_str and version_id_str:
            org_id = int(org_id_str)
            version_id = int(version_id_str)
            stripe_sub_id = data_object.get("subscription")

            stripe_sub = stripe.Subscription.retrieve(stripe_sub_id)
            period_start = datetime.fromtimestamp(stripe_sub.current_period_start)
            period_end = datetime.fromtimestamp(stripe_sub.current_period_end)

            sub = (
                db.query(BillingSubscription)
                .filter(BillingSubscription.organization_id == org_id)
                .first()
            )
            if not sub:
                sub = BillingSubscription(
                    organization_id=org_id,
                    plan_version_id=version_id,
                    status=SubscriptionStatus.ACTIVE.value,
                    current_period_start=period_start,
                    current_period_end=period_end,
                    stripe_subscription_id=stripe_sub_id,
                )
                db.add(sub)
            else:
                # This is the ONLY place status → ACTIVE is written outside of
                # convert_trial_to_paid (which is the Super Admin path).
                sub.plan_version_id = version_id
                sub.status = SubscriptionStatus.ACTIVE.value
                sub.current_period_start = period_start
                sub.current_period_end = period_end
                sub.stripe_subscription_id = stripe_sub_id

            # Flip workspace to PRODUCTION on successful payment
            from app.modules.organizations.models import Organization
            org = db.query(Organization).filter(Organization.id == org_id).first()
            if org:
                org.workspace_type = "PRODUCTION"
                if not org.is_active:
                    org.is_active = True

            db.add(BillingCommercialAuditEvent(
                organization_id=org_id,
                event_type="SELF_SERVICE_CHECKOUT_COMPLETED",
                payload={"stripe_subscription_id": stripe_sub_id, "plan_version_id": version_id},
                stripe_event_id=event_id,
            ))
            db.commit()

    elif event_type == "invoice.paid":
        stripe_sub_id = data_object.get("subscription")
        sub = (
            db.query(BillingSubscription)
            .filter(BillingSubscription.stripe_subscription_id == stripe_sub_id)
            .first()
        )
        if sub:
            stripe_sub = stripe.Subscription.retrieve(stripe_sub_id)
            sub.current_period_end = datetime.fromtimestamp(stripe_sub.current_period_end)
            sub.status = SubscriptionStatus.ACTIVE.value  # recover from PAST_DUE on payment
            db.add(BillingCommercialAuditEvent(
                organization_id=sub.organization_id,
                event_type="SUBSCRIPTION_RENEWED",
                payload={"stripe_invoice_id": data_object.get("id")},
                stripe_event_id=event_id,
            ))
            db.commit()

    elif event_type == "invoice.payment_failed":
        stripe_sub_id = data_object.get("subscription")
        sub = (
            db.query(BillingSubscription)
            .filter(BillingSubscription.stripe_subscription_id == stripe_sub_id)
            .first()
        )
        if sub:
            sub.status = SubscriptionStatus.PAST_DUE.value
            db.add(BillingCommercialAuditEvent(
                organization_id=sub.organization_id,
                event_type="PAYMENT_FAILED",
                payload={"stripe_invoice_id": data_object.get("id")},
                stripe_event_id=event_id,
            ))
            db.commit()

    elif event_type == "customer.subscription.deleted":
        stripe_sub_id = data_object.get("id")
        sub = (
            db.query(BillingSubscription)
            .filter(BillingSubscription.stripe_subscription_id == stripe_sub_id)
            .first()
        )
        if sub:
            sub.status = SubscriptionStatus.CANCELLED.value
            db.add(BillingCommercialAuditEvent(
                organization_id=sub.organization_id,
                event_type="SUBSCRIPTION_CANCELLED",
                payload={},
                stripe_event_id=event_id,
            ))
            db.commit()

    else:
        # Record unhandled event types so we can audit them but don't crash
        db.add(BillingCommercialAuditEvent(
            event_type=f"UNHANDLED_STRIPE_{event_type.upper().replace('.', '_')}",
            payload={"event_type": event_type},
            stripe_event_id=event_id,
        ))
        db.commit()
        logger.info("Stripe webhook: unhandled event type=%s id=%s", event_type, event_id)

    return {"status": "success"}
