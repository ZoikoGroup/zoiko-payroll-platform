"""
modules/billing/notifications.py
--------------------------------
Subscription billing emails, all routed through the shared communications
dispatcher (audit row in communication_events, idempotency, retry with
backoff on transient SMTP failures):

    BIL-001  billing.payment_succeeded   receipt: amount, currency, plan, transaction ID, date
    BIL-002  billing.invoice_issued      the invoice (PDF attached when Stripe's copy downloads)
    BIL-003  billing.payment_failed      failure notice with a retry link
    BIL-004  billing.renewal_upcoming    Stripe invoice.upcoming reminder

Keys are derived from the Stripe invoice id, so the webhook and the
success-page reconciliation (POST /billing/checkout/confirm) can both call
notify_invoice_paid for the same invoice and the customer still gets one
email of each kind. A deliberate resend passes a nonce, which makes a new key.

Amounts are always in the currency Stripe charged, never the organization's
payroll currency.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable, List, Optional

from sqlalchemy.orm import Session

from app.modules.communications.service import idempotency_key, queue_email

logger = logging.getLogger("zoiko_payroll.billing")

MODULE = "billing"
EVENT_PAYMENT_SUCCEEDED, TPL_PAYMENT_SUCCEEDED = "billing.payment_succeeded", "BIL-001"
EVENT_INVOICE_ISSUED, TPL_INVOICE_ISSUED = "billing.invoice_issued", "BIL-002"
EVENT_PAYMENT_FAILED, TPL_PAYMENT_FAILED = "billing.payment_failed", "BIL-003"
EVENT_RENEWAL_UPCOMING, TPL_RENEWAL_UPCOMING = "billing.renewal_upcoming", "BIL-004"

# Events shown in the billing email log (org admin + Super Admin), with the
# organization-created welcome emails the same customer expects to see.
BILLING_LOG_EVENTS = (
    EVENT_PAYMENT_SUCCEEDED, EVENT_INVOICE_ISSUED, EVENT_PAYMENT_FAILED, EVENT_RENEWAL_UPCOMING,
    "commercial.organization_created", "commercial.evaluation_created",
)

# Stripe amounts are in the currency's minor unit; these have none.
_ZERO_DECIMAL = {"BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA", "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF"}


def _get(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    try:
        return obj[key]
    except (KeyError, TypeError, IndexError):
        return getattr(obj, key, default)


def to_dict(stripe_obj) -> dict:
    if stripe_obj is None:
        return {}
    if isinstance(stripe_obj, dict) and not hasattr(stripe_obj, "to_dict"):
        return stripe_obj
    return stripe_obj.to_dict() if hasattr(stripe_obj, "to_dict") else dict(stripe_obj)


def format_amount(minor_units, currency: str) -> str:
    """'USD 499.00' / 'INR 41,500.00' / 'JPY 5,000' from Stripe minor units."""
    code = (currency or "").upper()
    value = Decimal(int(minor_units or 0))
    if code in _ZERO_DECIMAL:
        return f"{code} {value:,.0f}"
    return f"{code} {value / 100:,.2f}"


def _fmt_ts(ts, with_time: bool = True) -> str:
    if not ts:
        return ""
    dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    return dt.strftime("%d %b %Y %H:%M") if with_time else dt.strftime("%d %b %Y")


def _transaction_id(invoice: dict) -> str:
    """Charge / payment-intent id across Stripe API versions (the flat
    fields were removed in 2025 versions in favour of invoice.payments)."""
    for key in ("charge", "payment_intent"):
        val = invoice.get(key)
        if isinstance(val, dict):
            val = val.get("id")
        if val:
            return str(val)
    payments = (invoice.get("payments") or {}).get("data") or []
    for p in payments:
        payment = (p or {}).get("payment") or {}
        val = payment.get("payment_intent") or payment.get("charge")
        if isinstance(val, dict):
            val = val.get("id")
        if val:
            return str(val)
    return ""


def _period_label(invoice: dict) -> str:
    lines = ((invoice.get("lines") or {}).get("data")) or []
    period = (lines[0] or {}).get("period") if lines else None
    start = (period or {}).get("start") or invoice.get("period_start")
    end = (period or {}).get("end") or invoice.get("period_end")
    if start and end and start != end:
        return f"{_fmt_ts(start, False)} - {_fmt_ts(end, False)}"
    return ""


def invoice_facts(invoice) -> dict:
    """Plain values from a Stripe Invoice (object or dict) — safe to hand to
    a send that runs after the request session is closed."""
    inv = to_dict(invoice)
    paid_at = ((inv.get("status_transitions") or {}).get("paid_at")) or inv.get("created")
    return {
        "stripe_invoice_id": inv.get("id") or "",
        "number": inv.get("number") or inv.get("id") or "",
        "currency": (inv.get("currency") or "").upper(),
        "amount_paid": int(inv.get("amount_paid") or 0),
        "amount_due": int(inv.get("amount_due") or 0),
        "total": int(inv.get("total") or 0),
        "status": inv.get("status") or "",
        "hosted_invoice_url": inv.get("hosted_invoice_url") or "",
        "invoice_pdf": inv.get("invoice_pdf") or "",
        "created": inv.get("created"),
        "paid_at": paid_at,
        "attempt_count": int(inv.get("attempt_count") or 0),
        "next_payment_attempt": inv.get("next_payment_attempt"),
        "customer_email": inv.get("customer_email") or "",
        "transaction_id": _transaction_id(inv),
        "period_label": _period_label(inv),
        "failure_reason": ((inv.get("last_finalization_error") or {}).get("message") or ""),
        "subscription_id": _subscription_id(inv),
    }


def _subscription_id(inv: dict) -> Optional[str]:
    flat = inv.get("subscription")
    if isinstance(flat, dict):
        flat = flat.get("id")
    if flat:
        return flat
    return (((inv.get("parent") or {}).get("subscription_details") or {}).get("subscription"))


def organization_name(db: Session, organization_id: int) -> str:
    from app.modules.organizations.models import Organization

    org = db.query(Organization).filter(Organization.id == organization_id).first()
    return (org.organization_name if org else None) or "your organization"


def plan_name_for_org(db: Session, organization_id: int) -> str:
    from app.modules.billing.entitlements import get_active_subscription
    from app.modules.billing.models import BillingPlan, BillingPlanVersion, BillingSubscription

    sub = get_active_subscription(db, organization_id) or (
        db.query(BillingSubscription).filter(BillingSubscription.organization_id == organization_id).first()
    )
    if sub is not None and sub.plan_version_id:
        version = db.query(BillingPlanVersion).filter(BillingPlanVersion.id == sub.plan_version_id).first()
        plan = db.query(BillingPlan).filter(BillingPlan.id == version.plan_id).first() if version else None
        if plan is not None:
            return plan.name
    return "subscription"


def billing_recipients(db: Session, organization_id: int, fallback_email: str = "") -> List[str]:
    """Active Org Admins first, then the organization's own contact address,
    then the email Stripe has for the customer — de-duplicated."""
    from app.modules.auth.models import User, UserRole
    from app.modules.organizations.models import Organization

    seen, out = set(), []

    def _add(addr):
        addr = (addr or "").strip()
        if addr and addr.lower() not in seen:
            seen.add(addr.lower())
            out.append(addr)

    admins = (
        db.query(User)
        .filter(User.organization_id == organization_id, User.role == UserRole.ORG_ADMIN, User.is_active.is_(True))
        .order_by(User.id.asc())
        .all()
    )
    for u in admins:
        _add(u.email)
    if not out:
        org = db.query(Organization).filter(Organization.id == organization_id).first()
        _add(org.email if org else None)
    if not out:
        _add(fallback_email)
    return out


def _key(organization_id, event, recipient, template_id, obj, nonce=None):
    return idempotency_key(organization_id, event, recipient, template_id, obj + (f":resend:{nonce}" if nonce else ""))


def notify_invoice_paid(
    db: Session, organization_id: int, invoice, *, plan_name: Optional[str] = None,
    kinds: Iterable[str] = ("receipt", "invoice"), recipients: Optional[List[str]] = None,
    resend_nonce: Optional[str] = None, actor_user_id=None,
) -> int:
    """Queue the receipt (BIL-001) and the invoice (BIL-002) for a paid
    invoice. A $0 invoice (a deferred-start subscription's trial record) is
    not a payment: no email. Returns the number of sends queued/attempted."""
    from app.services.email_service import send_invoice_email, send_payment_succeeded_email

    f = invoice if isinstance(invoice, dict) and "stripe_invoice_id" in invoice else invoice_facts(invoice)
    if not f["stripe_invoice_id"] or f["amount_paid"] <= 0:
        return 0
    org_name = organization_name(db, organization_id)
    plan = plan_name or plan_name_for_org(db, organization_id)
    amount = format_amount(f["amount_paid"], f["currency"])
    to = recipients or billing_recipients(db, organization_id, f["customer_email"])
    obj = f"inv:{f['stripe_invoice_id']}"
    count = 0
    for rcpt in to:
        if "receipt" in kinds:
            queue_email(
                MODULE, EVENT_PAYMENT_SUCCEEDED, TPL_PAYMENT_SUCCEEDED, rcpt,
                _key(organization_id, EVENT_PAYMENT_SUCCEEDED, rcpt, TPL_PAYMENT_SUCCEEDED, obj, resend_nonce),
                send_payment_succeeded_email,
                send_kwargs=dict(
                    email=rcpt, organization_name=org_name, plan_name=plan, amount_display=amount,
                    transaction_id=f["transaction_id"], paid_at=f"{_fmt_ts(f['paid_at'])} UTC",
                    invoice_number=f["number"], receipt_url=f["hosted_invoice_url"], organization_id=organization_id,
                ),
                organization_id=organization_id, actor_user_id=actor_user_id, db=db,
            )
            count += 1
        if "invoice" in kinds:
            queue_email(
                MODULE, EVENT_INVOICE_ISSUED, TPL_INVOICE_ISSUED, rcpt,
                _key(organization_id, EVENT_INVOICE_ISSUED, rcpt, TPL_INVOICE_ISSUED, obj, resend_nonce),
                send_invoice_email,
                send_kwargs=dict(
                    email=rcpt, organization_name=org_name, plan_name=plan, invoice_number=f["number"],
                    amount_display=amount, issued_at=f"{_fmt_ts(f['created'])} UTC", status_label="paid",
                    period_label=f["period_label"], invoice_pdf_url=f["invoice_pdf"],
                    hosted_invoice_url=f["hosted_invoice_url"], organization_id=organization_id,
                ),
                organization_id=organization_id, actor_user_id=actor_user_id, db=db,
            )
            count += 1
    return count


def notify_payment_failed(
    db: Session, organization_id: int, invoice, *, plan_name: Optional[str] = None,
    recipients: Optional[List[str]] = None, resend_nonce: Optional[str] = None, actor_user_id=None,
) -> int:
    """BIL-003. One email per failed attempt (Stripe retries on a schedule;
    each failure is news), keyed on the invoice + attempt number."""
    from app.services.email_service import send_payment_failed_email

    f = invoice if isinstance(invoice, dict) and "stripe_invoice_id" in invoice else invoice_facts(invoice)
    if not f["stripe_invoice_id"]:
        return 0
    org_name = organization_name(db, organization_id)
    plan = plan_name or plan_name_for_org(db, organization_id)
    amount = format_amount(f["amount_due"] or f["total"], f["currency"])
    to = recipients or billing_recipients(db, organization_id, f["customer_email"])
    obj = f"inv:{f['stripe_invoice_id']}:attempt:{f['attempt_count']}"
    for rcpt in to:
        queue_email(
            MODULE, EVENT_PAYMENT_FAILED, TPL_PAYMENT_FAILED, rcpt,
            _key(organization_id, EVENT_PAYMENT_FAILED, rcpt, TPL_PAYMENT_FAILED, obj, resend_nonce),
            send_payment_failed_email,
            send_kwargs=dict(
                email=rcpt, organization_name=org_name, plan_name=plan, amount_display=amount,
                invoice_number=f["number"], failure_reason=f["failure_reason"],
                retry_url=f["hosted_invoice_url"],
                next_attempt=_fmt_ts(f["next_payment_attempt"], False),
                organization_id=organization_id,
            ),
            organization_id=organization_id, actor_user_id=actor_user_id, db=db,
        )
    return len(to)


def notify_upcoming_renewal(db: Session, organization_id: int, invoice, *, plan_name: Optional[str] = None) -> int:
    """BIL-004 from Stripe's invoice.upcoming (sent ahead of each renewal
    when 'Upcoming renewal events' is enabled in Stripe's billing settings).
    The upcoming invoice has no id yet: keyed on subscription + renewal date."""
    from app.services.email_service import send_subscription_renewal_reminder_email

    f = invoice_facts(invoice)
    inv = to_dict(invoice)
    renewal_ts = f["next_payment_attempt"] or inv.get("period_end") or inv.get("due_date")
    if not renewal_ts:
        return 0
    org_name = organization_name(db, organization_id)
    plan = plan_name or plan_name_for_org(db, organization_id)
    amount = format_amount(f["amount_due"] or f["total"], f["currency"])
    renewal_date = _fmt_ts(renewal_ts, False)
    to = billing_recipients(db, organization_id, f["customer_email"])
    obj = f"sub:{f['subscription_id'] or 'unknown'}:renewal:{renewal_date}"
    for rcpt in to:
        queue_email(
            MODULE, EVENT_RENEWAL_UPCOMING, TPL_RENEWAL_UPCOMING, rcpt,
            _key(organization_id, EVENT_RENEWAL_UPCOMING, rcpt, TPL_RENEWAL_UPCOMING, obj),
            send_subscription_renewal_reminder_email,
            send_kwargs=dict(
                email=rcpt, organization_name=org_name, plan_name=plan, amount_display=amount,
                renewal_date=renewal_date, organization_id=organization_id,
            ),
            organization_id=organization_id, db=db,
        )
    return len(to)


def safe_notify(fn, *args, **kwargs) -> int:
    """Billing state changes must never fail (or make Stripe retry a webhook)
    because an email could not be queued — log and carry on."""
    try:
        return fn(*args, **kwargs) or 0
    except Exception:  # noqa: BLE001
        logger.exception("[billing-email] %s failed", getattr(fn, "__name__", "notify"))
        return 0


def email_log(db: Session, organization_id: Optional[int] = None, *, limit: int = 100,
              events: Optional[Iterable[str]] = None, outcome: Optional[str] = None) -> List[dict]:
    """communication_events rows for the billing email log UI."""
    from app.modules.communications.models import CommunicationEvent

    q = db.query(CommunicationEvent).filter(CommunicationEvent.event_type.in_(list(events or BILLING_LOG_EVENTS)))
    if organization_id is not None:
        q = q.filter(CommunicationEvent.organization_id == organization_id)
    if outcome:
        q = q.filter(CommunicationEvent.outcome == outcome)
    rows = q.order_by(CommunicationEvent.created_at.desc(), CommunicationEvent.id.desc()).limit(max(1, min(limit, 500))).all()
    return [
        {
            "id": r.id,
            "organizationId": r.organization_id,
            "eventType": r.event_type,
            "templateId": r.template_id,
            "recipient": r.recipient_email,
            "outcome": r.outcome,
            "attempts": r.attempt_count,
            "error": r.provider_response,
            "createdAt": r.created_at.isoformat() + "Z" if r.created_at else None,
        }
        for r in rows
    ]


# ── Resend / download (Subscription & Billing + Super Admin) ────────────────

def _stripe_invoice_for(row) -> dict:
    """The live Stripe invoice behind a BillingInvoice row ({} when there is
    none or Stripe is unreachable)."""
    if not getattr(row, "stripe_invoice_id", None):
        return {}
    import stripe

    from app.config import settings

    if not settings.STRIPE_SECRET_KEY:
        return {}
    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        return to_dict(stripe.Invoice.retrieve(row.stripe_invoice_id))
    except Exception:  # noqa: BLE001
        logger.warning("[billing-email] could not read Stripe invoice %s", row.stripe_invoice_id, exc_info=True)
        return {}


def facts_for_invoice_row(row) -> dict:
    """invoice_facts from Stripe when reachable, else from the local ledger
    row (no PDF link then — the email says so by linking the billing page)."""
    live = _stripe_invoice_for(row)
    if live:
        return invoice_facts(live)
    minor = int(Decimal(str(row.total or 0)) * (1 if (row.currency or "").upper() in _ZERO_DECIMAL else 100))
    ts = int(row.issued_at.replace(tzinfo=timezone.utc).timestamp()) if row.issued_at else None
    return {
        "stripe_invoice_id": row.stripe_invoice_id or f"local-{row.id}", "number": f"INV-{row.id:06d}",
        "currency": (row.currency or "").upper(), "amount_paid": minor if row.status == "PAID" else 0,
        "amount_due": minor, "total": minor, "status": (row.status or "").lower(), "hosted_invoice_url": "",
        "invoice_pdf": "", "created": ts, "paid_at": ts, "attempt_count": 0, "next_payment_attempt": None,
        "customer_email": "", "transaction_id": "", "period_label": "", "failure_reason": "", "subscription_id": None,
    }


def invoice_links(row) -> dict:
    live = _stripe_invoice_for(row)
    return {"pdfUrl": live.get("invoice_pdf") or None, "hostedUrl": live.get("hosted_invoice_url") or None,
            "number": live.get("number") or None}


def resend_invoice_emails(db: Session, row, *, kinds=("receipt", "invoice"), actor_user_id=None,
                          recipients: Optional[List[str]] = None) -> List[dict]:
    """Deliberate resend from the UI: sends NOW (inline, so the caller gets
    the real outcome) under fresh idempotency keys, and returns the email
    log rows it produced."""
    import uuid

    from app.modules.communications.models import CommunicationEvent
    from app.modules.communications.service import dispatch_inline

    facts = facts_for_invoice_row(row)
    nonce = uuid.uuid4().hex[:12]
    started = datetime.utcnow()
    with dispatch_inline():
        if row.status == "PAID":
            facts["amount_paid"] = facts["amount_paid"] or facts["total"]
            notify_invoice_paid(db, row.organization_id, facts, kinds=kinds, recipients=recipients,
                                resend_nonce=nonce, actor_user_id=actor_user_id)
        else:
            notify_payment_failed(db, row.organization_id, facts, recipients=recipients,
                                  resend_nonce=nonce, actor_user_id=actor_user_id)
    rows = (
        db.query(CommunicationEvent)
        .filter(CommunicationEvent.organization_id == row.organization_id,
                CommunicationEvent.idempotency_key.like(f"%resend:{nonce}%"),
                CommunicationEvent.created_at >= started.replace(microsecond=0))
        .all()
    )
    return [{"recipient": r.recipient_email, "eventType": r.event_type, "outcome": r.outcome,
             "error": r.provider_response} for r in rows]
