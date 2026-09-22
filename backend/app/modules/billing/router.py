"""
modules/billing/router.py
--------------------------
Tenant-facing billing endpoints — blueprint §7's minimal tenant-facing
read API plus Path 2 self-service paid checkout.

Mounted with prefix "/billing" (see main.py):

    GET  /billing/plans               → PUBLISHED plan versions + entitlement flags
    GET  /billing/my-subscription     → current org's subscription + entitlement flags
    GET  /billing/trial-status        → lightweight banner payload (null when none)
    GET  /billing/dunning-status      → lightweight payment-issue banner payload (null when none)
    POST /billing/my-subscription/billing-portal → Stripe Billing Portal URL (update payment method)
    GET  /billing/my-subscription/invoices                    → org's own invoices, newest first
    GET  /billing/my-subscription/invoice-explanation/{id}    → one invoice, per-employee breakdown
    POST /billing/checkout            → create a Stripe Checkout Session (PRODUCTION only)
    POST /billing/webhooks/stripe     → Stripe webhook handler (unauthenticated, signature-verified)

See billing/admin_router.py for the Super Admin CRUD surface.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
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
    BillingAuthority,
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
    BillingStartTrialResponse,
    BillingMySubscriptionResponse,
    BillingPublishedPlanResponse,
    BillingTrialStatusResponse,
    BillingDunningStatusResponse,
    BillingPortalResponse,
)
from app.modules.payroll.engine.tax_resolver import get_jurisdiction_onboarding_block_reason

logger = logging.getLogger("zoiko_payroll.billing.router")

router = APIRouter(prefix="/billing", tags=["Billing"])

# Plan prices live ONLY in billing_price_catalog_items (see plan_catalog.py's
# price helpers + scripts/seed_price_catalog.py). No hardcoded amount may
# exist here — checkout and the plans list both resolve from the catalog.


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
        price_items = plan_catalog.resolve_plan_price_items(db, plan.code)
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
                # Step 7 — monthly price is derived from the PUBLISHED
                # price catalog, never a hardcoded dict; components feed
                # the plan card's per-line breakdown on the frontend.
                monthly_price_usd=sum(
                    (i.unit_amount for i in price_items), Decimal("0.00")
                ),
                price_components=[
                    {
                        "component_type": item.component_type,
                        "currency": item.currency,
                        "unit_amount": item.unit_amount,
                    }
                    for item in price_items
                ],
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


@router.get(
    "/dunning-status",
    response_model=Optional[BillingDunningStatusResponse],
    summary="Lightweight dunning status for the payment-issue banner",
)
def get_dunning_status(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Step 4 / blocker #17 — the org's own BillingDunningState, so the
    tenant-facing banner can state plainly what's restricted right now.
    Returns null (no row, or SUPER_ADMIN with no organization_id at all)
    rather than 404 — the banner should silently not render, not error."""
    from app.modules.billing.models import BillingDunningState

    if current_user.organization_id is None:
        return None

    state = (
        db.query(BillingDunningState)
        .filter(BillingDunningState.organization_id == current_user.organization_id)
        .first()
    )
    if state is None:
        return None

    return BillingDunningStatusResponse(
        stage=state.stage,
        entered_at=state.entered_at,
        in_flight_run_guard=state.in_flight_run_guard,
    )


@router.post(
    "/my-subscription/billing-portal",
    response_model=BillingPortalResponse,
    summary="Create a Stripe Billing Portal session to update payment method",
)
def create_billing_portal_session(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_org_admin),
):
    """Step 4 — the dunning banner's "update payment method" CTA. No
    stripe_customer_id is persisted anywhere in this codebase today
    (checkout creates an implicit Stripe Customer per session); the
    subscription's own stripe_subscription_id is the only durable link
    back to it, so it's looked up live rather than adding a new column
    just for this."""
    subscription = entitlements.get_active_subscription(db, current_user.organization_id)
    if subscription is None or not subscription.stripe_subscription_id:
        raise BadRequestException("No Stripe subscription on file for this organization.")

    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        stripe_sub = stripe.Subscription.retrieve(subscription.stripe_subscription_id)
        portal_session = stripe.billing_portal.Session.create(
            customer=stripe_sub.customer,
            return_url=f"{settings.FRONTEND_URL}/organization-admin/subscription",
        )
    except stripe.error.StripeError as e:
        raise BadRequestException(f"Stripe billing portal error: {str(e)}")

    return BillingPortalResponse(portal_url=portal_session.url)


def _ensure_stripe_price(db: Session, version: BillingPlanVersion, plan: BillingPlan) -> str:
    """Ensure version has a stripe_price_id; create product and price on-the-fly if missing."""
    if version.stripe_price_id:
        return version.stripe_price_id

    if not settings.STRIPE_SECRET_KEY:
        raise BadRequestException("Stripe is not configured. STRIPE_SECRET_KEY is missing.")

    # Step 7 — the amount comes from the PUBLISHED price catalog. No
    # hardcoded fallback exists: a plan without a published price has no
    # defensible amount to charge, so checkout fails closed instead of
    # inventing one.
    amount = plan_catalog.resolve_plan_monthly_price_cents(db, plan.code)
    if amount is None:
        raise BadRequestException(
            f"No published price exists in the catalog for plan {plan.code}. "
            "Run scripts/seed_price_catalog.py (or publish a price) before offering checkout."
        )
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

def _missing_checkout_config() -> list[str]:
    return [
        name for name, value in [
            ("STRIPE_SECRET_KEY", settings.STRIPE_SECRET_KEY),
            ("STRIPE_CHECKOUT_SUCCESS_URL", settings.STRIPE_CHECKOUT_SUCCESS_URL),
            ("STRIPE_CHECKOUT_CANCEL_URL", settings.STRIPE_CHECKOUT_CANCEL_URL),
        ] if not value
    ]


def _require_checkout_config() -> None:
    """Fail closed with a clear, actionable message before any Stripe call,
    instead of letting an empty STRIPE_SECRET_KEY surface as an opaque
    Stripe SDK auth error, or an empty success_url/cancel_url get sent to
    Stripe as-is — which can leave a customer stranded after paying with no
    way back into the app. Shared by both callers of this endpoint: a fresh
    NON_CHARGEABLE org's first checkout, and an EVALUATION org converting
    via TrialBanner -> /billing/plans -> here."""
    missing = _missing_checkout_config()
    if missing:
        raise BadRequestException(
            f"Checkout is not configured: missing {', '.join(missing)}. "
            "Set these environment variables before offering checkout."
        )


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

    _require_checkout_config()

    organization_id = current_user.organization_id
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if org is None:
        raise NotFoundException("Organization", organization_id)

    # §12 — an Enterprise-governed org (or any org whose commercial route
    # already disagrees with STANDALONE) must never be allowed into
    # self-service checkout at all; that would silently overlap two
    # commercial routes. Checked unconditionally, before the auto-promotion
    # below, since an already-COMMERCIAL_ACTIVE Enterprise org would
    # otherwise sail straight through the is_billable() check further down.
    entitlements.assert_no_overlapping_billable_ownership(db, organization_id, BillingAuthority.STANDALONE.value)

    # Part 1 (§A1) — a NON_CHARGEABLE org attempting its first self-service
    # checkout is exactly how a STANDALONE org is supposed to become
    # billable, so auto-promote here rather than gating on a state nothing
    # has set yet (checkout.session.completed re-affirms this idempotently
    # below; this is the actual first flip).
    if org.billing_classification == "NON_CHARGEABLE":
        org.billing_classification = "COMMERCIAL_ACTIVE"
        org.charge_enabled = True
        entitlements.resolve_commercial_route(db, org, BillingAuthority.STANDALONE.value)
        db.commit()

    if not entitlements.is_billable(org):
        raise ForbiddenException(
            "This organization is not eligible for billing "
            f"(billing_classification={org.billing_classification})."
        )

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
    # Normalize to naive-UTC, this codebase's datetime.utcnow()-based
    # convention throughout — a browser-originated request always sends a
    # timezone-AWARE ISO string (JS Date.toISOString() always appends "Z"),
    # which Pydantic parses as tz-aware, while the comparison below is
    # naive; mixing the two raises TypeError. Without this normalization,
    # PlanReviewPage's checkout call fails outright.
    if commencement.tzinfo is not None:
        commencement = commencement.astimezone(timezone.utc).replace(tzinfo=None)

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
        tax_id_collection={"enabled": True},
        billing_address_collection="required",
    )
    if settings.STRIPE_AUTOMATIC_TAX_ENABLED:
        session_kwargs["automatic_tax"] = {"enabled": True}

    # Stripe rejects a billing_cycle_anchor that isn't strictly in the
    # future — only set one for a genuinely negotiated delayed start, and
    # let an immediate/near-immediate commencement use Stripe's own default
    # (bill now) rather than risk a rejected anchor a few seconds in the past.
    if commencement > datetime.utcnow() + timedelta(minutes=5):
        # commencement is naive-UTC at this point (normalized above) — a
        # bare .timestamp() on a naive datetime is interpreted as LOCAL
        # time by Python, silently shifting the anchor by the server's own
        # UTC offset (confirmed: off by 5.5h on a server in IST). Attaching
        # UTC tzinfo explicitly before converting is what actually makes
        # this the UTC epoch Stripe expects.
        anchor_epoch = int(commencement.replace(tzinfo=timezone.utc).timestamp())
        session_kwargs["subscription_data"] = {"billing_cycle_anchor": anchor_epoch}

    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        session = stripe.checkout.Session.create(**session_kwargs)
    except stripe.error.StripeError as e:
        raise BadRequestException(f"Stripe Checkout error: {str(e)}")

    return BillingCheckoutResponse(checkout_url=session.url)


@router.post("/start-trial", response_model=BillingStartTrialResponse)
def start_trial(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_org_admin),
):
    """Convert the caller's already-registered PRODUCTION org into a 30-day
    Professional Evaluation — no Stripe, no card. Reached from
    PlanReviewPage.jsx's "Start Trial" button, shown on Core and
    Professional's review pages only (Business has no trial path — those
    buyers pay directly, enforced by that page simply never rendering the
    button, since this endpoint takes no plan_code to check server-side).

    Deliberately always PROFESSIONAL, matching register_trial's own single
    trial product (see its docstring) — this app has no per-plan trial
    concept, so this does not honor whatever plan_code the customer was
    reviewing; it's the same evaluation /register-trial already offers,
    just reachable after a real registration instead of only before one.

    Idempotent: an org already in EVALUATION is a no-op success (a second
    click/page reload must not error). An org that already has ANY
    BillingSubscription (trialing, active, or otherwise) is refused — this
    must never overwrite an existing commercial relationship.
    """
    from app.modules.organizations.models import Organization

    organization_id = current_user.organization_id
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if org is None:
        raise NotFoundException("Organization", organization_id)

    existing_sub = (
        db.query(BillingSubscription)
        .filter(BillingSubscription.organization_id == organization_id)
        .first()
    )

    if org.workspace_type == "EVALUATION" and existing_sub is not None:
        return BillingStartTrialResponse(
            workspace_type=org.workspace_type,
            trial_ends_at=existing_sub.current_period_end,
        )

    if existing_sub is not None:
        raise ForbiddenException(
            "This organization already has a commercial relationship — trial conversion is not available."
        )

    plan_version = plan_catalog.get_published_plan_version(db, "PROFESSIONAL")
    if plan_version is None:
        raise BadRequestException(
            "The Professional plan is not available for evaluation yet — please try again later."
        )

    org.workspace_type = "EVALUATION"
    org.billing_onboarding_status = "TRIALING"

    trial_start = datetime.utcnow()
    trial_end = trial_start + timedelta(days=30)
    subscription = BillingSubscription(
        organization_id=org.id,
        plan_version_id=plan_version.id,
        billing_authority=BillingAuthority.STANDALONE.value,
        status=SubscriptionStatus.TRIALING.value,
        current_period_start=trial_start,
        current_period_end=trial_end,
    )
    db.add(subscription)
    db.add(
        BillingCommercialAuditEvent(
            organization_id=org.id,
            actor_user_id=current_user.id,
            event_type="TRIAL_SUBSCRIPTION_CREATED",
            payload={
                "plan_code": "PROFESSIONAL",
                "plan_version_id": plan_version.id,
                "trial_days": 30,
                "current_period_end": trial_end.isoformat(),
                "source": "plan_review_page",
            },
        )
    )
    db.commit()

    logger.info("Org %s converted to trial via PlanReviewPage by %s", org.organization_code, current_user.email)

    return BillingStartTrialResponse(workspace_type="EVALUATION", trial_ends_at=trial_end)


def _infer_component_type(price) -> str:
    """Maps a Stripe Price to a BillingSubscriptionItem-style
    component_type. No fixed vocabulary exists for this column anywhere in
    the codebase (a free-text String(50)) — this establishes the two real
    values in use: RECURRING_BASE (the flat monthly plan price
    _ensure_stripe_price creates) and BWM (a metered/usage-based billable-
    worker-month line). Every checkout price today is flat-rate — no
    metered BWM Stripe Price is ever created yet — so in practice every
    line currently resolves to RECURRING_BASE; the metered branch is real,
    checked logic for the day a BWM-priced Stripe Price exists, not dead
    code guarding against nothing.

    Takes the Price object itself (not the invoice line) — current Stripe
    API versions no longer nest an expandable `price` object directly on
    the invoice line; the line only carries a price *id* under
    `pricing.price_details.price`, so the caller retrieves the Price
    separately and passes it in here.
    """
    recurring = getattr(price, "recurring", None) if price else None
    usage_type = getattr(recurring, "usage_type", None) if recurring else None
    if usage_type == "metered":
        return "BWM"
    return "RECURRING_BASE"


def _sync_subscription_price_item(db: Session, sub: BillingSubscription, plan_code: str) -> None:
    """Step 7 — pin a subscription's flat base price to the PUBLISHED price
    catalog by (re)writing its RECURRING_BASE component item.

    checkout.session.completed is the only place a STANDALONE sub is created
    or re-pointed at a plan, so keeping exactly one RECURRING_BASE item per
    sub (delete-then-insert) stays correct across initial subscribe and any
    future replan/renew flows. A plan with no published catalog price leaves
    the sub without an item rather than breaking the webhook — the catalog-
    reference invariant only holds when the referenced row actually exists.
    """
    from app.modules.billing.models import BillingSubscriptionItem

    base_item = plan_catalog.get_published_base_catalog_item(db, plan_code)
    if base_item is None:
        return

    existing = (
        db.query(BillingSubscriptionItem)
        .filter(
            BillingSubscriptionItem.subscription_id == sub.id,
            BillingSubscriptionItem.component_type == "RECURRING_BASE",
        )
        .all()
    )
    for row in existing:
        db.delete(row)
    db.add(
        BillingSubscriptionItem(
            subscription_id=sub.id,
            component_type="RECURRING_BASE",
            unit_price_catalog_ref=base_item.id,
            quantity=1,
        )
    )


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

    # Stripe removed the flat `invoice.tax` field in current API versions —
    # tax now only shows up as the gap between total and total_excluding_tax
    # (or, equivalently, summing total_taxes[].amount). Deriving it from the
    # totals is robust to either shape and to tax being entirely absent.
    total_excluding_tax = getattr(stripe_invoice, "total_excluding_tax", None)
    tax_cents = (stripe_invoice.total - total_excluding_tax) if total_excluding_tax is not None else 0

    invoice = BillingInvoice(
        organization_id=sub.organization_id,
        subscription_id=sub.id,
        stripe_invoice_id=stripe_invoice.id,
        status=status,
        total=Decimal(stripe_invoice.total) / 100,
        tax_amount=Decimal(tax_cents) / 100,
        currency=stripe_invoice.currency.upper(),
        issued_at=datetime.fromtimestamp(stripe_invoice.created),
    )
    db.add(invoice)
    db.flush()

    for line in stripe_invoice.lines.data:
        # Current API versions nest only a price *id* on the line
        # (pricing.price_details.price) rather than an expandable Price
        # object — retrieve it separately to inspect recurring.usage_type.
        pricing = getattr(line, "pricing", None)
        price_details = getattr(pricing, "price_details", None) if pricing else None
        price_id = getattr(price_details, "price", None) if price_details else None
        price = None
        if price_id:
            try:
                price = stripe.Price.retrieve(price_id)
            except stripe.error.StripeError:
                logger.exception("[invoice] Failed to retrieve Stripe price %s", price_id)

        quantity = line.quantity or 1
        db.add(BillingInvoiceLine(
            invoice_id=invoice.id,
            description=line.description or "Subscription charge",
            component_type=_infer_component_type(price),
            quantity=quantity,
            unit_amount=Decimal(line.amount) / quantity / 100,
            line_total=Decimal(line.amount) / 100,
        ))


def _update_invoice_status_from_stripe_event(db: Session, stripe_invoice_id: Optional[str], status: str) -> None:
    """Keep the local invoice ledger aligned with non-payment Stripe events."""
    if not stripe_invoice_id:
        return
    from app.modules.billing.models import BillingInvoice

    invoice = db.query(BillingInvoice).filter(BillingInvoice.stripe_invoice_id == stripe_invoice_id).first()
    if invoice is not None:
        invoice.status = status


def _stripe_period_timestamp(subscription, item, field):
    value = item.get(field)
    if value is None:
        value = getattr(subscription, field, None)
    if value is None:
        raise BadRequestException(
            f"Stripe subscription is missing required field: {field}"
        )
    return value


def _subscription_period(subscription_object: dict) -> tuple[Optional[datetime], Optional[datetime]]:
    item = ((subscription_object.get("items") or {}).get("data") or [{}])[0]
    start = item.get("current_period_start") or subscription_object.get("current_period_start")
    end = item.get("current_period_end") or subscription_object.get("current_period_end")
    return (
        datetime.fromtimestamp(start) if start else None,
        datetime.fromtimestamp(end) if end else None,
    )


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
            sub_item = stripe_sub["items"]["data"][0]
            period_start_ts = _stripe_period_timestamp(
                stripe_sub, sub_item, "current_period_start"
            )
            period_end_ts = _stripe_period_timestamp(
                stripe_sub, sub_item, "current_period_end"
            )
            period_start = datetime.utcfromtimestamp(period_start_ts)
            period_end = datetime.utcfromtimestamp(period_end_ts)

            # A deferred service_commencement_at (PlanReviewPage's "delayed
            # billing" checkout) means checkout completing here is NOT the
            # same moment as actually being charged — Stripe won't bill
            # until the commencement date. Until then this org must read as
            # evaluation (workspace_type=EVALUATION, status=TRIALING), the
            # same shape the real trial already uses — not "normal" — and
            # only the invoice.paid handler below (the real charge
            # succeeding) is allowed to flip it to PRODUCTION/ACTIVE. An
            # immediate checkout (no deferral, e.g. Core's $0 signup) keeps
            # the original behavior: normal access right away.
            commencement_dt = None
            if commencement_str:
                try:
                    commencement_dt = datetime.fromisoformat(commencement_str)
                except ValueError:
                    commencement_dt = None
            is_deferred = commencement_dt is not None and commencement_dt > datetime.utcnow() + timedelta(minutes=5)
            pending_status = SubscriptionStatus.TRIALING.value if is_deferred else SubscriptionStatus.ACTIVE.value

            sub = (
                db.query(BillingSubscription)
                .filter(BillingSubscription.organization_id == org_id)
                .first()
            )
            if not sub:
                sub = BillingSubscription(
                    organization_id=org_id,
                    plan_version_id=version_id,
                    status=pending_status,
                    current_period_start=period_start,
                    current_period_end=period_end,
                    stripe_subscription_id=stripe_sub_id,
                )
                db.add(sub)
            else:
                # This is the ONLY place status is written outside of
                # convert_trial_to_paid (which is the Super Admin path) and
                # invoice.paid (the real-charge conversion, below).
                sub.plan_version_id = version_id
                sub.status = pending_status
                sub.current_period_start = period_start
                sub.current_period_end = period_end
                sub.stripe_subscription_id = stripe_sub_id

            # Materialize sub.id now — billing_subscription_items has no
            # ORM relationship() for SQLAlchemy to auto-order inserts by
            # dependency, so the item's subscription_id FK below would
            # otherwise flush as NULL (NOT NULL violation).
            db.flush()

            # Step 7 — pin the sub's flat base price to the PUBLISHED price
            # catalog (Enterprise Order Form orgs have no plan_version, so
            # plan_code resolves to None and no item is written for them).
            version_row = db.query(BillingPlanVersion).filter(BillingPlanVersion.id == version_id).first()
            plan_code = None
            if version_row is not None:
                plan_row = db.query(BillingPlan).filter(BillingPlan.id == version_row.plan_id).first()
                if plan_row is not None:
                    plan_code = plan_row.code
            if plan_code is not None:
                _sync_subscription_price_item(db, sub, plan_code)

            # Deferred commencement -> stay/become EVALUATION until
            # invoice.paid confirms the real charge; immediate checkout ->
            # PRODUCTION right away, same as before this change.
            from app.modules.organizations.models import Organization
            org = db.query(Organization).filter(Organization.id == org_id).first()
            if org:
                org.workspace_type = "EVALUATION" if is_deferred else "PRODUCTION"
                sub_items = (stripe_sub.get("items") or {}).get("data") or []
                sub_item = sub_items[0] if sub_items else {}
                period_end_ts = _stripe_period_timestamp(
                    stripe_sub, sub_item, "current_period_end"
                )
                # future replan/upgrade flows may reuse this handler) must
                # never push a negotiated commencement date forward.
                if org.service_commencement_at is None and commencement_str:
                    try:
                        org.service_commencement_at = datetime.fromisoformat(commencement_str)
                    except ValueError:
                        org.service_commencement_at = datetime.utcnow()

                # Part 1 (§A1) — this webhook is the actual authority for a
                # STANDALONE org becoming billable on the self-service path
                # (create_checkout_session's own auto-promotion, above,
                # already does this idempotently for the common case; this
                # re-affirms it here too so it holds even if a subscription
                # somehow reaches ACTIVE via a path that skipped that step).
                if org.commercial_route != BillingAuthority.ENTERPRISE_ORDER_FORM.value:
                    org.billing_classification = "COMMERCIAL_ACTIVE"
                    org.charge_enabled = True
                    # §12 — resolve_commercial_route also stamps sub.billing_authority
                    # to match explicitly (previously it only ever got STANDALONE by
                    # column default, never an explicit assignment).
                    entitlements.resolve_commercial_route(db, org, org.commercial_route or BillingAuthority.STANDALONE.value)

            db.add(BillingCommercialAuditEvent(
                organization_id=org_id,
                event_type="SELF_SERVICE_CHECKOUT_COMPLETED",
                payload={"stripe_subscription_id": stripe_sub_id, "plan_version_id": version_id},
                stripe_event_id=event_id,
            ))
            db.commit()

    elif event_type == "customer.subscription.updated":
        stripe_sub_id = data_object.get("id")
        sub = db.query(BillingSubscription).filter(
            BillingSubscription.stripe_subscription_id == stripe_sub_id
        ).first()
        if sub:
            status_map = {
                "active": SubscriptionStatus.ACTIVE.value,
                "trialing": SubscriptionStatus.TRIALING.value,
                "past_due": SubscriptionStatus.PAST_DUE.value,
                "unpaid": SubscriptionStatus.PAST_DUE.value,
                "canceled": SubscriptionStatus.CANCELLED.value,
                "incomplete_expired": SubscriptionStatus.CANCELLED.value,
            }
            sub.status = status_map.get(data_object.get("status"), sub.status)
            period_start, period_end = _subscription_period(data_object)
            if period_start:
                sub.current_period_start = period_start
            if period_end:
                sub.current_period_end = period_end
            price_id = (((data_object.get("items") or {}).get("data") or [{}])[0].get("price") or {})
            price_id = price_id.get("id") if isinstance(price_id, dict) else price_id
            version = db.query(BillingPlanVersion).filter(
                BillingPlanVersion.stripe_price_id == price_id
            ).first() if price_id else None
            if version:
                sub.plan_version_id = version.id
                plan = db.query(BillingPlan).filter(BillingPlan.id == version.plan_id).first()
                if plan:
                    _sync_subscription_price_item(db, sub, plan.code)
            from app.modules.organizations.models import Organization
            org = db.query(Organization).filter(Organization.id == sub.organization_id).first()
            if org:
                org.billing_onboarding_status = {
                    SubscriptionStatus.ACTIVE.value: "ACTIVE",
                    SubscriptionStatus.TRIALING.value: "TRIALING",
                    SubscriptionStatus.PAST_DUE.value: "PAST_DUE",
                    SubscriptionStatus.CANCELLED.value: "CANCELLED",
                }.get(sub.status, org.billing_onboarding_status)
            db.add(BillingCommercialAuditEvent(
                organization_id=sub.organization_id,
                event_type="SUBSCRIPTION_UPDATED",
                payload={"stripe_status": data_object.get("status"), "plan_version_id": sub.plan_version_id},
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
            # Stripe moved current_period_end off the Subscription object
            # itself and onto each subscription item (API versions
            # 2025-06-30+/current SDK) — reading stripe_sub.current_period_end
            # directly raises AttributeError against a real Stripe response.
            period_end_ts = stripe_sub["items"]["data"][0]["current_period_end"]
            # utcfromtimestamp, not fromtimestamp — see checkout.session.completed
            # above for why a naive fromtimestamp() silently shifts this by
            # the server's own local UTC offset.
            sub.current_period_end = datetime.utcfromtimestamp(period_end_ts)
            sub.status = SubscriptionStatus.ACTIVE.value  # recover from PAST_DUE on payment
            from app.modules.organizations.models import Organization
            org = db.query(Organization).filter(Organization.id == sub.organization_id).first()
            if org:
                # The real charge succeeding is what "only after payment do
                # you get the normal account" actually means — a deferred
                # checkout parked the org in EVALUATION at
                # checkout.session.completed; this is the one event allowed
                # to move it to PRODUCTION. A no-op for an org that was
                # already PRODUCTION (immediate checkout, or a later
                # renewal's invoice.paid).
                org.workspace_type = "PRODUCTION"
                org.billing_onboarding_status = "ACTIVE"
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
            from app.modules.organizations.models import Organization
            org = db.query(Organization).filter(Organization.id == sub.organization_id).first()
            if org:
                org.billing_onboarding_status = "PAST_DUE"
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

    elif event_type in {"charge.refunded", "refund.created"}:
        stripe_invoice_id = data_object.get("invoice")
        if stripe_invoice_id:
            from app.modules.billing.models import BillingInvoice
            invoice = db.query(BillingInvoice).filter(
                BillingInvoice.stripe_invoice_id == stripe_invoice_id
            ).first()
            if invoice:
                refunded_cents = data_object.get("amount") or data_object.get("amount_refunded") or 0
                invoice.status = "REFUNDED" if refunded_cents >= int(invoice.total * 100) else "PARTIALLY_REFUNDED"
                db.add(BillingCommercialAuditEvent(
                    organization_id=invoice.organization_id,
                    event_type="REFUND_RECONCILED",
                    payload={"stripe_invoice_id": stripe_invoice_id, "status": invoice.status},
                    stripe_event_id=event_id,
                ))
        db.commit()

    elif event_type in {"charge.dispute.created", "charge.dispute.closed"}:
        stripe_invoice_id = data_object.get("invoice")
        dispute_status = "DISPUTED" if event_type.endswith("created") else (
            "DISPUTE_WON" if data_object.get("status") == "won" else "DISPUTE_LOST"
        )
        _update_invoice_status_from_stripe_event(db, stripe_invoice_id, dispute_status)
        db.add(BillingCommercialAuditEvent(
            event_type="PAYMENT_DISPUTE_UPDATED",
            payload={"stripe_invoice_id": stripe_invoice_id, "dispute_status": data_object.get("status")},
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
            from app.modules.organizations.models import Organization
            org = db.query(Organization).filter(Organization.id == sub.organization_id).first()
            if org:
                org.billing_onboarding_status = "CANCELLED"
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


# ── Invoices & invoice explanation (Step 3 / Part 7) ────────────────────

@router.get("/my-subscription/invoices")
def list_my_invoices(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """The caller's own invoices, newest first — feeds the Subscription
    page's Invoices tab. total/tax_amount/currency/status only; the full
    per-employee breakdown is a separate call
    (GET .../invoice-explanation/{invoice_id}) so this list stays cheap."""
    from app.modules.billing.models import BillingInvoice

    invoices = (
        db.query(BillingInvoice)
        .filter(BillingInvoice.organization_id == current_user.organization_id)
        .order_by(BillingInvoice.issued_at.desc())
        .all()
    )
    return {
        "invoices": [
            {
                "id": inv.id,
                "stripe_invoice_id": inv.stripe_invoice_id,
                "status": inv.status,
                "total": inv.total,
                "tax_amount": inv.tax_amount,
                "currency": inv.currency,
                "issued_at": inv.issued_at,
            }
            for inv in invoices
        ],
    }


@router.get("/my-subscription/invoice-explanation/{invoice_id}")
def get_my_invoice_explanation(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """A specific invoice of the caller's own org, explained: which
    employees it billed for, and who was excluded (and why), per Part 7."""
    from app.modules.billing.models import BillingInvoice
    from app.modules.billing.invoice_explanation import build_invoice_explanation

    invoice = (
        db.query(BillingInvoice)
        .filter(BillingInvoice.id == invoice_id, BillingInvoice.organization_id == current_user.organization_id)
        .first()
    )
    if invoice is None:
        raise NotFoundException("Invoice", invoice_id)
    return build_invoice_explanation(db, invoice)


@router.get("/my-subscription/invoice-explanation")
def get_my_latest_invoice_explanation(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Convenience alias for the caller's most recent invoice — kept
    alongside the explicit {invoice_id} route above rather than replaced,
    since it's a real, already-used shortcut (no invoice id needed for the
    common "what did my last bill cover" question)."""
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
