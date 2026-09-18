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

import stripe

from app.config import settings
from app.core.dependencies import get_current_super_admin
from app.core.exceptions import BadRequestException, NotFoundException
from app.database import get_db
from app.modules.billing import entitlements, plan_catalog, trial_lifecycle
from app.modules.billing.enterprise_order_form import record_order_form
from app.modules.billing.models import (
    BillingCommercialAuditEvent,
    BillingCreditNote,
    BillingInvoice,
    BillingPlanVersion,
    PlanVersionStatus,
)
from app.modules.billing.schemas import (
    BillingAuditEventListResponse,
    BillingCreditNoteIssueRequest,
    BillingCreditNoteResponse,
    BillingEntitlementFlagCreateRequest,
    BillingEntitlementFlagResponse,
    BillingEntitlementOverrideCreateRequest,
    BillingEntitlementOverrideResponse,
    BillingPlanCreate,
    BillingPlanResponse,
    BillingPlanVersionCreateRequest,
    BillingPlanVersionResponse,
    BillingPlanVersionStatusTransition,
    BillingRefundRequest,
    BillingSubscriptionResponse,
    ConvertTrialRequest,
    EnterpriseOrderFormCreate,
    EnterpriseOrderFormDetailResponse,
    EnterpriseOrderFormListResponse,
    EnterpriseOrderFormResponse,
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


# ── Invoice explanation & BWM reconciliation (Part 7) ────────────────────

@router.get("/organizations/{organization_id}/invoices/{invoice_id}/explanation")
def get_invoice_explanation(
    organization_id: int,
    invoice_id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    from app.modules.billing.invoice_explanation import build_invoice_explanation

    invoice = (
        db.query(BillingInvoice)
        .filter(BillingInvoice.id == invoice_id, BillingInvoice.organization_id == organization_id)
        .first()
    )
    if invoice is None:
        raise NotFoundException("Invoice", invoice_id)
    return build_invoice_explanation(db, invoice)


# Step 3: the Finance-facing BWM/invoice discrepancy check now lives on the
# existing Super Admin Exceptions & Reconciliation page
# (GET /super-admin/compliance/exceptions, super_admin/command_center_router.py)
# instead of here — one home for "two systems that don't otherwise talk to
# each other disagree", not a second, separate reconciliation view.


# ── Enterprise Order Form (Part 12 / Step 6) ──────────────────────────────

@router.post(
    "/organizations/{organization_id}/order-form",
    response_model=EnterpriseOrderFormResponse,
)
def create_enterprise_order_form(
    organization_id: int,
    data: EnterpriseOrderFormCreate,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    """Records a signed Enterprise Order Form — the ONE path that directly
    sets an org billable by human decision. Enterprise is explicitly never
    self-service, so there is no public checkout UI for this.

    Side effects, all in the same transaction (billing/enterprise_order_form.py):
      - Organization.commercial_route = ENTERPRISE_ORDER_FORM,
        billing_classification = COMMERCIAL_ACTIVE, charge_enabled = True
      - a matching BillingSubscription with billing_authority =
        ENTERPRISE_ORDER_FORM and plan_version_id = None (Enterprise scale
        limits come from this row's negotiated_scale_limits, never a
        BillingPlanVersion)
    Refuses an org that already has a subscription/Order Form under a
    DIFFERENT commercial route (no overlapping billable ownership)."""
    return record_order_form(
        db,
        organization_id=organization_id,
        contract_reference=data.contract_reference,
        negotiated_scale_limits=data.negotiated_scale_limits,
        negotiated_price_terms=data.negotiated_price_terms,
        term_start=data.term_start,
        term_end=data.term_end,
        signed_by_user_id=current_user.id,
    )


@router.get("/order-forms", response_model=EnterpriseOrderFormListResponse)
def list_enterprise_order_forms(
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    """Every recorded Enterprise Order Form, newest first (one per org —
    organization_id is unique on the table itself). Cross-tenant read for
    the Order Forms section of the Super Admin Command Center."""
    from app.modules.organizations.models import Organization
    from app.modules.billing.models import EnterpriseOrderForm

    rows = (
        db.query(EnterpriseOrderForm, Organization)
        .join(Organization, Organization.id == EnterpriseOrderForm.organization_id)
        .order_by(EnterpriseOrderForm.created_at.desc())
        .all()
    )
    items = [
        EnterpriseOrderFormDetailResponse(
            id=form.id,
            organization_id=form.organization_id,
            organization_name=org.organization_name,
            contract_reference=form.contract_reference,
            negotiated_scale_limits=form.negotiated_scale_limits,
            negotiated_price_terms=form.negotiated_price_terms,
            term_start=form.term_start,
            term_end=form.term_end,
            signed_by=form.signed_by,
            created_at=form.created_at,
        )
        for form, org in rows
    ]
    return EnterpriseOrderFormListResponse(order_forms=items, total=len(items))


@router.get(
    "/organizations/{organization_id}/order-form",
    response_model=EnterpriseOrderFormDetailResponse,
)
def get_enterprise_order_form(
    organization_id: int,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    """One org's signed Order Form (404 when the org has none on file)."""
    from app.modules.organizations.models import Organization
    from app.modules.billing.models import EnterpriseOrderForm

    row = (
        db.query(EnterpriseOrderForm, Organization)
        .join(Organization, Organization.id == EnterpriseOrderForm.organization_id)
        .filter(EnterpriseOrderForm.organization_id == organization_id)
        .first()
    )
    if row is None:
        raise NotFoundException("Enterprise Order Form", organization_id)
    form, org = row
    return EnterpriseOrderFormDetailResponse(
        id=form.id,
        organization_id=form.organization_id,
        organization_name=org.organization_name,
        contract_reference=form.contract_reference,
        negotiated_scale_limits=form.negotiated_scale_limits,
        negotiated_price_terms=form.negotiated_price_terms,
        term_start=form.term_start,
        term_end=form.term_end,
        signed_by=form.signed_by,
        created_at=form.created_at,
    )


# ── Refunds & credit notes (Part 8) ──────────────────────────────────────

@router.post("/organizations/{organization_id}/refund")
def issue_refund(
    organization_id: int,
    data: BillingRefundRequest,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    """Calls the real Stripe refund API — never just edits a local total.
    Writes a BillingCommercialAuditEvent for every refund issued, append-
    only, same discipline as every other commercial audit trail here."""
    invoice = (
        db.query(BillingInvoice)
        .filter(BillingInvoice.organization_id == organization_id, BillingInvoice.stripe_invoice_id == data.stripe_invoice_id)
        .first()
    )
    if invoice is None:
        raise NotFoundException("Invoice", data.stripe_invoice_id)

    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        stripe_invoice = stripe.Invoice.retrieve(data.stripe_invoice_id)
        payment_intent = stripe_invoice.payment_intent
        if not payment_intent:
            raise BadRequestException("This invoice has no associated payment to refund.")
        refund = stripe.Refund.create(
            payment_intent=payment_intent,
            amount=data.amount_cents,
            reason="requested_by_customer",
        )
    except stripe.error.StripeError as e:
        raise BadRequestException(f"Stripe refund error: {str(e)}")

    db.add(BillingCommercialAuditEvent(
        organization_id=organization_id,
        actor_user_id=current_user.id,
        event_type="REFUND_ISSUED",
        payload={
            "stripe_invoice_id": data.stripe_invoice_id,
            "stripe_refund_id": refund.id,
            "amount_cents": data.amount_cents or refund.amount,
            "reason": data.reason,
        },
    ))
    db.commit()
    return {"success": True, "stripe_refund_id": refund.id}


@router.post("/organizations/{organization_id}/credit-note", response_model=BillingCreditNoteResponse)
def issue_credit_note(
    organization_id: int,
    data: BillingCreditNoteIssueRequest,
    current_user=Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    """Calls the real Stripe credit-note API and records our own
    BillingCreditNote row (invoice_id keyed to our internal BillingInvoice,
    not the Stripe invoice id the request body carries)."""
    invoice = (
        db.query(BillingInvoice)
        .filter(BillingInvoice.organization_id == organization_id, BillingInvoice.stripe_invoice_id == data.stripe_invoice_id)
        .first()
    )
    if invoice is None:
        raise NotFoundException("Invoice", data.stripe_invoice_id)

    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        credit_note = stripe.CreditNote.create(
            invoice=data.stripe_invoice_id,
            lines=[{"type": "custom_line_item", "description": data.reason, "unit_amount": data.amount_cents, "quantity": 1}],
        )
    except stripe.error.StripeError as e:
        raise BadRequestException(f"Stripe credit note error: {str(e)}")

    note = BillingCreditNote(
        invoice_id=invoice.id,
        reason=data.reason,
        amount=data.amount_cents / 100,
        approved_by_user_id=current_user.id,
    )
    db.add(note)
    db.add(BillingCommercialAuditEvent(
        organization_id=organization_id,
        actor_user_id=current_user.id,
        event_type="CREDIT_NOTE_ISSUED",
        payload={"stripe_invoice_id": data.stripe_invoice_id, "stripe_credit_note_id": credit_note.id, "amount_cents": data.amount_cents},
    ))
    db.commit()
    db.refresh(note)
    return note
