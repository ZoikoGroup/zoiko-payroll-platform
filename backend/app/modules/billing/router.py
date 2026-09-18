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
from datetime import datetime, timedelta
from decimal import Decimal
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
    BillingCancelRequest,
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
):
    """One entry per plan (CORE/PROFESSIONAL/BUSINESS/ENTERPRISE) that
    currently has a PUBLISHED version. A plan with no PUBLISHED version yet
    (e.g. still DRAFT/APPROVED) is simply omitted, not returned as null/empty —
    there is nothing publishable to show a tenant for it yet.

    Deliberately unauthenticated (no get_current_user dependency): this is
    read-only, non-sensitive plan-catalog/pricing data — the same kind of
    thing a public pricing page shows — and RegisterPage.jsx's plan picker
    needs to render it before an account/JWT exists at all. PlanSelectionPage
    (post-login) keeps working unchanged; it just no longer requires the
    token this endpoint never actually used for anything but access control.
    """
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

    # Part 2 — Service Commencement Date is the ONLY trigger for recurring
    # charges, never "checkout completed". Defaults to immediate (now) for
    # self-service Core/Professional; may be negotiated future-dated.
    # Carried through Stripe metadata so the checkout.session.completed
    # webhook (which is where Organization.service_commencement_at is
    # actually SET — see stripe_webhook below) can read it back.
    commencement = body.service_commencement_at or datetime.utcnow()

    session_kwargs = dict(
        mode="subscription",
        client_reference_id=str(organization_id),
        line_items=[{
            "price": stripe_price_id,
            "quantity": 1,
        }],
        metadata={
            "organization_id": str(organization_id),
            "plan_version_id": str(version.id),
            "service_commencement_at": commencement.isoformat(),
        },
        success_url=settings.STRIPE_CHECKOUT_SUCCESS_URL,
        cancel_url=settings.STRIPE_CHECKOUT_CANCEL_URL,
        idempotency_key=idempotency_key,
        # Part 5 — jurisdiction-aware SaaS indirect tax (sales tax/VAT on
        # the Zoiko invoice itself), delegated entirely to Stripe Tax
        # rather than hand-rolling a rate table. This is Zoiko-subscription
        # tax only — see BillingInvoice.tax_amount's own docstring for why
        # this must never be conflated with payroll tax.
        automatic_tax={"enabled": True},
        tax_id_collection={"enabled": True},
        billing_address_collection="required",
    )

    # Stripe rejects a billing_cycle_anchor that isn't strictly in the
    # future — only set one for a genuinely negotiated delayed start, and
    # let an immediate/near-immediate commencement use Stripe's own default
    # (bill now) rather than risk a rejected anchor a few seconds in the past.
    if commencement > datetime.utcnow() + timedelta(minutes=5):
        session_kwargs["subscription_data"] = {"billing_cycle_anchor": int(commencement.timestamp())}

    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        session = stripe.checkout.Session.create(**session_kwargs)
    except stripe.error.StripeError as e:
        raise BadRequestException(f"Stripe Checkout error: {str(e)}")

    return BillingCheckoutResponse(checkout_url=session.url)


def _write_invoice_from_stripe(db: Session, sub: BillingSubscription, stripe_invoice_id: Optional[str], status: str) -> None:
    """Part 6 — populate BillingInvoice/BillingInvoiceLine, previously
    fully modeled and never populated by anything. Idempotent on
    stripe_invoice_id (a replayed webhook must never create a duplicate
    invoice row) and fails closed per Part 1/2: an org that isn't
    is_billable() or hasn't is_service_commenced() gets no invoice row at
    all, even if Stripe itself somehow generated one.

    tax_amount here is Zoiko SUBSCRIPTION tax only (sales tax/VAT Stripe
    Tax calculated on the Zoiko invoice, from Part 5's automatic_tax) — see
    BillingInvoice.tax_amount's own column comment. This must never be
    confused with, summed with, or displayed alongside any payroll-tax
    figure computed elsewhere in this codebase (the country tax engines).
    """
    if not stripe_invoice_id:
        return

    from app.modules.organizations.models import Organization
    from app.modules.billing.models import BillingInvoice, BillingInvoiceLine
    from app.modules.billing.entitlements import is_billable, is_service_commenced

    org = db.query(Organization).filter(Organization.id == sub.organization_id).first()
    if org is None or not is_billable(org) or not is_service_commenced(org):
        logger.info(
            "[invoice] Skipping invoice write for organization_id=%s (not billable or not yet commenced).",
            sub.organization_id,
        )
        return

    existing = db.query(BillingInvoice).filter(BillingInvoice.stripe_invoice_id == stripe_invoice_id).first()
    if existing is not None:
        return

    try:
        stripe_invoice = stripe.Invoice.retrieve(stripe_invoice_id)
    except stripe.error.StripeError:
        logger.exception("[invoice] Failed to retrieve Stripe invoice %s", stripe_invoice_id)
        return

    invoice = BillingInvoice(
        organization_id=sub.organization_id,
        subscription_id=sub.id,
        stripe_invoice_id=stripe_invoice.id,
        status=status,
        total=Decimal(stripe_invoice.total) / 100,
        tax_amount=Decimal(stripe_invoice.tax or 0) / 100,
        currency=stripe_invoice.currency.upper(),
        issued_at=datetime.fromtimestamp(stripe_invoice.created),
    )
    db.add(invoice)
    db.flush()

    for line in stripe_invoice.lines.data:
        db.add(BillingInvoiceLine(
            invoice_id=invoice.id,
            description=line.description or "Subscription charge",
            component_type="RECURRING_BASE",
            quantity=line.quantity or 1,
            unit_amount=Decimal(line.price.unit_amount) / 100 if line.price and line.price.unit_amount is not None else Decimal(0),
            line_total=Decimal(line.amount) / 100,
        ))


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
        commencement_str = (data_object.get("metadata") or {}).get("service_commencement_at")

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
                # Part 2 — checkout completing is NEVER itself sufficient to
                # start recurring charges; service_commencement_at (carried
                # through metadata from POST /billing/checkout) is the only
                # trigger. Only set once — a later renewal's
                # checkout.session.completed (there isn't one today, but
                # future replan/upgrade flows may reuse this handler) must
                # never push a negotiated commencement date forward.
                if org.service_commencement_at is None and commencement_str:
                    try:
                        org.service_commencement_at = datetime.fromisoformat(commencement_str)
                    except ValueError:
                        org.service_commencement_at = datetime.utcnow()

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

            # Part 9 — recovery must reset dunning state immediately,
            # regardless of current stage.
            from app.modules.billing.dunning import reset_dunning
            reset_dunning(db, sub.organization_id)

            # Part 6 — populate BillingInvoice/BillingInvoiceLine, gated by
            # is_billable()/is_service_commenced() (Parts 1/2) so a non-
            # chargeable or not-yet-commenced org never gets a real
            # invoice row even if Stripe somehow invoiced it.
            _write_invoice_from_stripe(db, sub, data_object.get("id"), status="PAID")

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

            # Part 9 — start the dunning clock the moment PAST_DUE is first
            # observed, rather than waiting for the next scheduled sweep.
            from app.modules.billing.dunning import get_or_create_dunning_state
            get_or_create_dunning_state(db, sub.organization_id)

            # Part 6 — Finance gets a record of failed attempts too, not
            # just successes (still gated by is_billable/is_service_commenced).
            _write_invoice_from_stripe(db, sub, data_object.get("id"), status="FAILED")

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


# ── Cancellation (Part 8) ────────────────────────────────────────────────

@router.post("/cancel")
def cancel_my_subscription(
    body: BillingCancelRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_org_admin),
):
    """Tenant-facing, org admin only. Cancels at period end
    (cancel_at_period_end=True) — the customer keeps access through what
    they already paid for. The actual status flip to CANCELLED still only
    happens via the customer.subscription.deleted webhook, preserving
    "webhook is the only path to a status change" — this endpoint only
    records the request and tells Stripe not to renew.
    """
    sub = entitlements.get_active_subscription(db, current_user.organization_id)
    if sub is None or not sub.stripe_subscription_id:
        raise NotFoundException("Subscription")

    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        stripe.Subscription.modify(sub.stripe_subscription_id, cancel_at_period_end=True)
    except stripe.error.StripeError as e:
        raise BadRequestException(f"Stripe cancellation error: {str(e)}")

    sub.cancel_requested_at = datetime.utcnow()
    db.add(sub)
    db.add(BillingCommercialAuditEvent(
        organization_id=current_user.organization_id,
        actor_user_id=current_user.id,
        event_type="CANCELLATION_REQUESTED",
        payload={"stripe_subscription_id": sub.stripe_subscription_id, "effective_at_period_end": sub.current_period_end.isoformat()},
    ))
    db.commit()
    return {
        "success": True,
        "message": "Cancellation scheduled. You'll retain access until the end of your current billing period.",
        "access_until": sub.current_period_end,
    }


# ── Invoice explanation (Part 7) ────────────────────────────────────────

@router.get("/my-subscription/invoice-explanation")
def get_my_latest_invoice_explanation(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """The caller's own most recent invoice, explained: which employees it
    billed for, and who was excluded (and why), per Part 7."""
    from app.modules.billing.models import BillingInvoice
    from app.modules.billing.invoice_explanation import build_invoice_explanation

    invoice = (
        db.query(BillingInvoice)
        .filter(BillingInvoice.organization_id == current_user.organization_id)
        .order_by(BillingInvoice.issued_at.desc())
        .first()
    )
    if invoice is None:
        raise NotFoundException("Invoice")
    return build_invoice_explanation(db, invoice)
