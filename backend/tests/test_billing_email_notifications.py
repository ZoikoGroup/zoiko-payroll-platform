"""
tests/test_billing_email_notifications.py
-----------------------------------------
Issue: an organization created + paid for a plan and received no email.

  * register_enterprise's welcome email ran as a background task over live
    ORM objects that were expired + detached by then -> DetachedInstanceError,
    swallowed -> no email. Regression: run the task after the request
    session is closed, the way FastAPI does.
  * Billing emails (receipt, invoice with PDF, payment failed, renewal) did
    not exist. They go through the shared dispatcher (audit row, retry,
    idempotency) and are wired to the Stripe webhook and to the success-page
    confirmation.
  * Mock / blocked sends were logged as "sent"; they are now "not_delivered".
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.modules.billing import notifications as bn
from app.modules.communications.models import CommunicationEvent


def _rows(db, **filters):
    q = db.query(CommunicationEvent)
    for key, value in filters.items():
        q = q.filter(getattr(CommunicationEvent, key) == value)
    return q.order_by(CommunicationEvent.id).all()


@pytest.fixture()
def org_admin(db, organization):
    from app.core.security import hash_password
    from app.modules.auth.models import User, UserRole

    organization.organization_name = "Nikhil"
    organization.email = "billing@nikhil.test"
    user = User(
        email="aila@nikhil.test", hashed_password=hash_password("x-Strong-pass-1"), role=UserRole.ORG_ADMIN,
        organization_id=organization.id, first_name="Aila", last_name="Goud", is_active=True,
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture()
def captured(monkeypatch):
    """Capture what send_approval_email would deliver (template, recipient,
    context, attachments); the real rendering path still runs before it."""
    from app.services import email_service

    sent = []
    real = email_service.send_approval_email

    def _capture(email, template_name, context, **kwargs):
        sent.append(SimpleNamespace(email=email, template=template_name, context=context,
                                    attachments=kwargs.get("attachments")))
        return real(email, template_name, context, **kwargs)

    monkeypatch.setattr(email_service, "send_approval_email", _capture)
    monkeypatch.setattr(email_service, "fetch_invoice_pdf", lambda url: b"%PDF-1.4 fake" if url else None)
    return sent


PAID_INVOICE = {
    "id": "in_1NIKHIL", "number": "ZP-0001", "currency": "usd", "amount_paid": 49900, "amount_due": 49900,
    "total": 49900, "status": "paid", "created": 1795651200,
    "status_transitions": {"paid_at": 1795651260},
    "hosted_invoice_url": "https://invoice.stripe.com/i/acct/test_hosted",
    "invoice_pdf": "https://pay.stripe.com/invoice/acct/test/pdf",
    "customer_email": "aila@nikhil.test", "charge": "ch_3NIKHIL",
    "lines": {"data": [{"period": {"start": 1795651200, "end": 1798243200}}]},
    "parent": {"subscription_details": {"subscription": "sub_NIKHIL"}},
}


# ── Facts / formatting ─────────────────────────────────────────────────────

def test_invoice_facts_and_amount_formatting():
    f = bn.invoice_facts(PAID_INVOICE)
    assert (f["stripe_invoice_id"], f["number"], f["transaction_id"], f["subscription_id"]) == (
        "in_1NIKHIL", "ZP-0001", "ch_3NIKHIL", "sub_NIKHIL")
    assert bn.format_amount(49900, "usd") == "USD 499.00"
    assert bn.format_amount(4150000, "INR") == "INR 41,500.00"
    assert bn.format_amount(5000, "jpy") == "JPY 5,000"
    # 2025+ Stripe API: the transaction lives under invoice.payments.
    newer = {"id": "in_2", "payments": {"data": [{"payment": {"payment_intent": "pi_123"}}]}}
    assert bn.invoice_facts(newer)["transaction_id"] == "pi_123"


# ── BIL-001 + BIL-002 ──────────────────────────────────────────────────────

def test_paid_invoice_sends_receipt_and_invoice_with_pdf_once(db, organization, org_admin, captured):
    assert bn.notify_invoice_paid(db, organization.id, PAID_INVOICE, plan_name="Business") == 2

    templates = {c.template: c for c in captured}
    receipt = templates["payment_succeeded.html"]
    assert receipt.email == "aila@nikhil.test"
    panel = receipt.context["details_panel"]
    for expected in ("USD 499.00", "Business", "ch_3NIKHIL", "ZP-0001", "Nikhil"):
        assert expected in panel
    invoice = templates["invoice_issued.html"]
    assert invoice.attachments == [("ZP-0001.pdf", b"%PDF-1.4 fake")]
    assert invoice.context["cta_url"] == PAID_INVOICE["hosted_invoice_url"]

    rows = _rows(db, organization_id=organization.id)
    assert sorted((r.event_type, r.template_id, r.module) for r in rows) == [
        ("billing.invoice_issued", "BIL-002", "billing"), ("billing.payment_succeeded", "BIL-001", "billing")]
    # No SMTP host in tests: the log says so instead of claiming "sent".
    assert {r.outcome for r in rows} == {"not_delivered"}
    assert all("NOT DELIVERED" in r.provider_response for r in rows)

    # Webhook + success page both reconcile the same invoice: no second email.
    captured.clear()
    bn.notify_invoice_paid(db, organization.id, PAID_INVOICE, plan_name="Business")
    assert captured == []
    assert len(_rows(db, organization_id=organization.id, outcome="skipped_duplicate")) == 2


def test_zero_amount_trial_invoice_sends_nothing(db, organization, org_admin, captured):
    assert bn.notify_invoice_paid(db, organization.id, {**PAID_INVOICE, "amount_paid": 0}) == 0
    assert captured == [] and _rows(db) == []


def test_invoice_without_downloadable_pdf_still_sends_with_link(db, organization, org_admin, captured, monkeypatch):
    from app.services import email_service

    monkeypatch.setattr(email_service, "fetch_invoice_pdf", lambda url: None)
    bn.notify_invoice_paid(db, organization.id, PAID_INVOICE, kinds=("invoice",))
    (invoice,) = captured
    assert invoice.attachments is None
    assert invoice.context["invoice_pdf_url"] == PAID_INVOICE["invoice_pdf"]


# ── BIL-003 / BIL-004 ──────────────────────────────────────────────────────

def test_payment_failed_has_retry_link_and_notifies_each_attempt(db, organization, org_admin, captured):
    failed = {**PAID_INVOICE, "status": "open", "amount_paid": 0, "attempt_count": 1,
              "next_payment_attempt": 1795910400}
    bn.notify_payment_failed(db, organization.id, failed, plan_name="Business")
    (mail,) = captured
    assert mail.template == "payment_failed.html"
    assert mail.context["cta_url"] == PAID_INVOICE["hosted_invoice_url"]
    assert mail.context["cta_label"] == "Retry payment"
    assert "USD 499.00" in mail.context["details_panel"]

    bn.notify_payment_failed(db, organization.id, {**failed, "attempt_count": 2}, plan_name="Business")
    assert len(captured) == 2  # a later failed retry is news


def test_upcoming_renewal_reminder(db, organization, org_admin, captured):
    upcoming = {"amount_due": 49900, "currency": "usd", "next_payment_attempt": 1798243200,
                "subscription": "sub_NIKHIL"}
    assert bn.notify_upcoming_renewal(db, organization.id, upcoming, plan_name="Business") == 1
    (mail,) = captured
    assert mail.template == "subscription_renewal_reminder.html"
    assert mail.context["renewal_date"] == "26 Dec 2026"


def test_recipients_fall_back_to_org_email_then_stripe_customer(db, organization):
    organization.email = None
    db.commit()
    assert bn.billing_recipients(db, organization.id, "payer@stripe.test") == ["payer@stripe.test"]
    organization.email = "billing@nikhil.test"
    db.commit()
    assert bn.billing_recipients(db, organization.id, "payer@stripe.test") == ["billing@nikhil.test"]


# ── Resend ─────────────────────────────────────────────────────────────────

def test_resend_sends_again_under_new_keys_and_reports_outcomes(db, organization, org_admin, captured):
    from datetime import datetime
    from decimal import Decimal

    from app.modules.billing.models import BillingInvoice

    bn.notify_invoice_paid(db, organization.id, PAID_INVOICE)
    row = BillingInvoice(organization_id=organization.id, stripe_invoice_id="in_1NIKHIL", status="PAID",
                         total=Decimal("499.00"), tax_amount=Decimal("0"), currency="USD",
                         issued_at=datetime(2026, 11, 26))
    db.add(row)
    db.commit()
    captured.clear()

    with patch.object(bn, "_stripe_invoice_for", return_value=PAID_INVOICE):
        results = bn.resend_invoice_emails(db, row, kinds=("invoice",))
    assert [c.template for c in captured] == ["invoice_issued.html"]
    assert [(r["recipient"], r["eventType"], r["outcome"]) for r in results] == [
        ("aila@nikhil.test", "billing.invoice_issued", "not_delivered")]


def test_resend_without_stripe_uses_the_local_ledger(db, organization, org_admin, captured):
    from datetime import datetime
    from decimal import Decimal

    from app.modules.billing.models import BillingInvoice

    row = BillingInvoice(organization_id=organization.id, stripe_invoice_id=None, status="PAID",
                         total=Decimal("499.00"), tax_amount=Decimal("0"), currency="USD",
                         issued_at=datetime(2026, 11, 26))
    db.add(row)
    db.commit()
    bn.resend_invoice_emails(db, row, kinds=("receipt",))
    (mail,) = captured
    assert "USD 499.00" in mail.context["details_panel"]


# ── Stripe webhook wiring ──────────────────────────────────────────────────

def _subscription(db, organization):
    from datetime import datetime, timedelta

    from app.modules.billing.models import (
        BillingPlan, BillingPlanVersion, BillingSubscription, PlanVersionStatus,
    )

    plan = BillingPlan(code="BUSINESS", name="Business")
    db.add(plan)
    db.flush()
    version = BillingPlanVersion(plan_id=plan.id, version=1, status=PlanVersionStatus.PUBLISHED.value)
    db.add(version)
    db.flush()
    sub = BillingSubscription(organization_id=organization.id, plan_version_id=version.id, status="ACTIVE",
                              current_period_start=datetime.utcnow(),
                              current_period_end=datetime.utcnow() + timedelta(days=30),
                              stripe_subscription_id="sub_NIKHIL")
    db.add(sub)
    db.commit()
    return sub


def _post_webhook(db, event_type, data, event_id):
    import stripe
    from fastapi.testclient import TestClient

    from app.database import get_db
    from app.main import app

    event = {"id": event_id, "type": event_type, "data": {"object": data}}
    stripe_sub = {"items": {"data": [{"current_period_end": 1798243200}]}}
    app.dependency_overrides[get_db] = lambda: db
    try:
        with patch.object(stripe.Webhook, "construct_event", return_value=event), \
             patch.object(stripe.Subscription, "retrieve", return_value=stripe_sub), \
             patch.object(stripe.Invoice, "retrieve", side_effect=stripe.error.StripeError("offline")):
            return TestClient(app).post("/api/billing/webhooks/stripe", content=b"{}",
                                        headers={"stripe-signature": "t=1,v1=x"})
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_webhook_invoice_paid_sends_receipt_and_invoice(db, organization, org_admin, captured):
    _subscription(db, organization)
    r = _post_webhook(db, "invoice.paid", PAID_INVOICE, "evt_paid_nikhil")
    assert r.status_code == 200, r.text
    assert sorted(c.template for c in captured) == ["invoice_issued.html", "payment_succeeded.html"]
    assert "Business" in captured[0].context["details_panel"]


def test_webhook_payment_failed_and_upcoming_send(db, organization, org_admin, captured):
    _subscription(db, organization)
    failed = {**PAID_INVOICE, "status": "open", "amount_paid": 0, "attempt_count": 1}
    assert _post_webhook(db, "invoice.payment_failed", failed, "evt_fail_nikhil").status_code == 200
    upcoming = {"amount_due": 49900, "currency": "usd", "next_payment_attempt": 1798243200,
                "subscription": "sub_NIKHIL"}
    assert _post_webhook(db, "invoice.upcoming", upcoming, "evt_up_nikhil").status_code == 200
    assert [c.template for c in captured] == ["payment_failed.html", "subscription_renewal_reminder.html"]


def test_org_admin_email_log_endpoint(db, organization, org_admin, captured):
    from app.modules.billing import router as billing_router

    bn.notify_invoice_paid(db, organization.id, PAID_INVOICE)
    body = billing_router.get_my_billing_email_log(limit=50, db=db, current_user=org_admin)
    assert {e["eventType"] for e in body["emails"]} == {"billing.payment_succeeded", "billing.invoice_issued"}
    assert all(e["recipient"] == "aila@nikhil.test" and e["outcome"] == "not_delivered" for e in body["emails"])


def test_delivery_problems_name_the_misconfiguration():
    from app.services.email_service import email_delivery_problems

    problems = " ".join(email_delivery_problems())
    assert "SMTP_HOST is not set" in problems          # conftest blanks the host
    assert "Outbound email is blocked" in problems     # pytest = test mode


# ── Welcome email after the request session is closed ─────────────────────

@pytest.mark.parametrize("mfa_enforcement", ["off", "enforce"])
def test_register_enterprise_welcome_email_survives_closed_request_session(db, monkeypatch, mfa_enforcement):
    """FastAPI runs BackgroundTasks after get_db has closed the session.
    With MFA_ENFORCEMENT=off — the production default (config.py) —
    registration issues the session directly and that commit expires every
    ORM object, so the old closure's org.id raised DetachedInstanceError ->
    no welcome email. conftest runs the suite with "enforce", which skips that
    commit and hid the bug; both modes are pinned here."""
    from fastapi import BackgroundTasks

    from app.modules.auth import service
    from app.modules.auth.schemas import RegisterRequest
    from app.services import email_service

    from decimal import Decimal

    from app.modules.payroll.models import ContributionRate, JurisdictionPack

    pack = JurisdictionPack(pack_id="IN-BILLMAIL", jurisdiction_country="IN", pack_type="tax", version="1.0",
                            status="Active")
    db.add(pack)
    db.commit()
    db.add(ContributionRate(
        organization_id=None, jurisdiction_country="IN", jurisdiction_pack_id=pack.id, component_key="pf",
        label="PF", employee_share="-", employer_share="-", total="-", employee_rate_pct=Decimal("12.00"),
    ))
    db.commit()

    from app.config import settings
    from app.modules.auth import mfa

    monkeypatch.setattr(settings, "MFA_ENFORCEMENT", mfa_enforcement)
    assert mfa.enforcement_on() is (mfa_enforcement == "enforce")

    sent = []
    monkeypatch.setattr(email_service, "send_organization_created_email", lambda **kw: sent.append(kw) or True)

    tasks = BackgroundTasks()
    service.register_enterprise(
        db,
        RegisterRequest(organization="Nikhil", name="Aila Nikhil Goud", email="aila@example.com",
                        password="a-strong-password-1", country="IN", terms_accepted=True),
        background_tasks=tasks,
    )
    assert sent == []          # deferred, not inline
    db.close()                 # what get_db does before background tasks run
    asyncio.run(tasks())

    assert len(sent) == 1
    assert (sent[0]["email"], sent[0]["organization_name"]) == ("aila@example.com", "Nikhil")
    (row,) = _rows(db, event_type="commercial.organization_created")
    assert row.recipient_email == "aila@example.com"
