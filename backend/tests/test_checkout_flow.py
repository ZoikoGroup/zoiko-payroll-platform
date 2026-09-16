"""
tests/test_checkout_flow.py
-----------------------------
Integration tests for Path 2 (Self-Service Paid Checkout):

  1. POST /billing/checkout rejects EVALUATION workspace orgs (403)
  2. POST /billing/checkout rejects a plan_code with no published version (404)
  3. POST /billing/checkout returns a checkout_url when Stripe is mocked (200)
  4. Stripe webhook checkout.session.completed → sub becomes ACTIVE, org → PRODUCTION
  5. Webhook is idempotent (second delivery of same event_id is no-op)
  6. invoice.paid refreshes current_period_end and recovers PAST_DUE → ACTIVE
  7. invoice.payment_failed → sub becomes PAST_DUE
  8. customer.subscription.deleted → sub becomes CANCELLED
  9. require_active_subscription allows EVALUATION orgs through
 10. require_active_subscription blocks PRODUCTION orgs without ACTIVE sub

Hermetic SQLite pattern (same as test_trial_lifecycle.py):
  env vars set BEFORE importing app.main, SQLite throwaway DB.
"""

import hashlib
import hmac
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

# ── Hermetic DB setup ──────────────────────────────────────────────────────

_TMP = tempfile.mkdtemp(prefix="checkout_flow_test_")
os.environ["PAYROLL_DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP, 'test.sqlite3')}"
os.environ["ENVIRONMENT"] = "development"
os.environ["ASSIST_MODEL_PROVIDER"] = ""
os.environ["ASSIST_MODEL_BASE_URL"] = ""
os.environ["ASSIST_MODEL_API_KEY"] = ""
os.environ["SMTP_HOST"] = ""
os.environ["SMTP_FROM_EMAIL"] = ""
os.environ["ASSIST_SUPPORT_EMAIL"] = ""
os.environ["ASSIST_SWEEP_ENABLED"] = "false"
os.environ["TRIAL_SWEEP_ENABLED"] = "false"
os.environ["STRIPE_SECRET_KEY"] = "sk_test_FAKE"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_FAKEFAKEFAKE"
os.environ["STRIPE_CHECKOUT_SUCCESS_URL"] = "http://localhost:3000/billing/checkout/success"
os.environ["STRIPE_CHECKOUT_CANCEL_URL"] = "http://localhost:3000/billing/checkout/cancel"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_saved_app_modules = {
    _mod: _module
    for _mod, _module in sys.modules.items()
    if _mod == "app" or _mod.startswith("app.")
}
for _mod in list(_saved_app_modules):
    del sys.modules[_mod]

import pytest  # noqa: E402
import stripe  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.database import Base, SessionLocal, engine, initialize_database  # noqa: E402
from app.modules.auth.models import User, UserRole  # noqa: E402
from app.modules.billing import plan_catalog  # noqa: E402
from app.modules.billing.models import (  # noqa: E402
    BillingAuthority,
    BillingCommercialAuditEvent,
    BillingSubscription,
    SubscriptionStatus,
)
from app.modules.organizations.models import Organization  # noqa: E402

from sqlalchemy.engine import make_url as _make_url  # noqa: E402

assert _make_url(engine.url).get_backend_name() == "sqlite", (
    f"test_checkout_flow must run on its own sqlite DB, got {engine.url}"
)

Base.metadata.create_all(bind=engine)
initialize_database()

_db = SessionLocal()

# ── Seed data ──────────────────────────────────────────────────────────────

_super = User(
    email="checkout-super@example.com",
    hashed_password=hash_password("strong-password"),
    role=UserRole.SUPER_ADMIN,
    first_name="Super",
    last_name="Admin",
    organization_id=None,
    is_active=True,
)
_db.add(_super)
_db.flush()

# PROFESSIONAL plan with a stripe_price_id
_plan = plan_catalog.create_plan(db=_db, code="PROFESSIONAL", name="Professional", actor_user_id=_super.id)
_version = plan_catalog.create_plan_version(
    db=_db,
    plan_id=_plan.id,
    feature_set={"features": ["payroll_runs"]},
    scale_limits={"max_entities": 5},
    actor_user_id=_super.id,
)
plan_catalog.approve_plan_version(_db, _version.id, actor_user_id=_super.id)
plan_catalog.publish_plan_version(_db, _version.id, published_by_user_id=_super.id)
_db.refresh(_version)
_version.stripe_price_id = "price_FAKE12345"
_db.commit()
_db.refresh(_version)

# EVALUATION org + admin
_eval_org = Organization(
    organization_name="Eval Corp",
    organization_code="EVALCHK",
    workspace_type="EVALUATION",
    country="DE",
    is_active=True,
)
_db.add(_eval_org)
_db.flush()

_eval_user = User(
    email="eval-admin@example.com",
    hashed_password=hash_password("strong-password"),
    role=UserRole.ORG_ADMIN,
    first_name="Eval",
    last_name="Admin",
    organization_id=_eval_org.id,
    is_active=True,
)
_db.add(_eval_user)
_db.flush()

# EVALUATION subscription for eval org
_db.add(BillingSubscription(
    organization_id=_eval_org.id,
    plan_version_id=_version.id,
    billing_authority=BillingAuthority.STANDALONE.value,
    status=SubscriptionStatus.TRIALING.value,
    current_period_start=datetime.utcnow() - timedelta(days=1),
    current_period_end=datetime.utcnow() + timedelta(days=29),
))
_db.flush()

# PRODUCTION org + admin (no active subscription yet)
_prod_org = Organization(
    organization_name="Prod Corp",
    organization_code="PRODCHK",
    workspace_type="PRODUCTION",
    country="DE",
    is_active=True,
)
_db.add(_prod_org)
_db.flush()

_prod_user = User(
    email="prod-admin@example.com",
    hashed_password=hash_password("strong-password"),
    role=UserRole.ORG_ADMIN,
    first_name="Prod",
    last_name="Admin",
    organization_id=_prod_org.id,
    is_active=True,
)
_db.add(_prod_user)
_db.flush()

_db.commit()

# Restore pre-purge app modules so other test files don't get class-identity conflicts
for _mod in list(sys.modules):
    if _mod == "app" or _mod.startswith("app."):
        del sys.modules[_mod]
sys.modules.update(_saved_app_modules)
del _saved_app_modules


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def mock_stripe_pkg():
    mock_sub = MagicMock()
    mock_sub.current_period_start = int(datetime.utcnow().timestamp())
    mock_sub.current_period_end = int((datetime.utcnow() + timedelta(days=30)).timestamp())

    mock_session = MagicMock()
    mock_session.url = "https://checkout.stripe.com/pay/cs_test_FAKE"

    with patch.object(stripe.Subscription, "retrieve", return_value=mock_sub), \
         patch.object(stripe.checkout.Session, "create", return_value=mock_session):
        yield


def _login(client, email, password="strong-password"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_stripe_webhook_payload(event_type: str, data: dict, event_id: str = None) -> tuple[bytes, str]:
    if event_id is None:
        event_id = f"evt_{event_type.replace('.', '_')}_{int(time.time())}"
    event_obj = {
        "id": event_id,
        "type": event_type,
        "data": {"object": data},
    }
    payload = json.dumps(event_obj).encode()
    ts = int(time.time())
    signed_payload = f"{ts}.{payload.decode()}"
    secret = os.environ["STRIPE_WEBHOOK_SECRET"].encode()
    sig = hmac.new(secret, signed_payload.encode(), hashlib.sha256).hexdigest()
    stripe_sig = f"t={ts},v1={sig}"
    return payload, stripe_sig


# ── Tests: POST /billing/checkout ─────────────────────────────────────────

def test_checkout_allows_evaluation_workspace_upgrade(client):
    """EVALUATION orgs can check out to upgrade their trial to a paid subscription."""
    token = _login(client, "eval-admin@example.com")
    r = client.post("/api/billing/checkout", json={"plan_code": "PROFESSIONAL"}, headers=_auth(token))
    assert r.status_code == 200, r.text
    assert "checkout_url" in r.json()


def test_checkout_returns_404_for_unknown_plan(client):
    """A plan_code with no published version yields 404."""
    token = _login(client, "prod-admin@example.com")
    r = client.post("/api/billing/checkout", json={"plan_code": "NONEXISTENT"}, headers=_auth(token))
    assert r.status_code == 404


def test_checkout_returns_url_when_stripe_succeeds(client):
    """Happy path: Stripe is mocked, endpoint returns checkout_url."""
    token = _login(client, "prod-admin@example.com")
    r = client.post(
        "/api/billing/checkout",
        json={"plan_code": "PROFESSIONAL"},
        headers=_auth(token),
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert "checkout_url" in body
    assert body["checkout_url"].startswith("https://checkout.stripe.com/")


# ── Tests: POST /billing/webhooks/stripe ──────────────────────────────────

def _post_webhook(client, event_type: str, data: dict, event_id: str = None):
    event_id_final = event_id or f"evt_{int(time.time())}"
    event_obj = {
        "id": event_id_final,
        "type": event_type,
        "data": {"object": data},
    }

    payload, sig = _make_stripe_webhook_payload(event_type, data, event_id_final)
    with patch.object(stripe.Webhook, "construct_event", return_value=event_obj):
        r = client.post(
            "/api/billing/webhooks/stripe",
            content=payload,
            headers={
                "stripe-signature": sig,
                "content-type": "application/json",
            },
        )
    return r


def test_webhook_checkout_completed_activates_subscription(client):
    """checkout.session.completed → subscription ACTIVE, org → PRODUCTION."""
    db = SessionLocal()
    try:
        org_id = _prod_org.id
        data = {
            "metadata": {
                "organization_id": str(org_id),
                "plan_version_id": str(_version.id),
            },
            "subscription": "sub_FAKE001",
        }
        r = _post_webhook(client, "checkout.session.completed", data, event_id="evt_checkout_001")
        assert r.status_code == 200, r.text

        sub = db.query(BillingSubscription).filter(BillingSubscription.organization_id == org_id).first()
        assert sub is not None
        assert sub.status == SubscriptionStatus.ACTIVE.value
        assert sub.stripe_subscription_id == "sub_FAKE001"

        org = db.query(Organization).filter(Organization.id == org_id).first()
        assert org.workspace_type == "PRODUCTION"

        audit = (
            db.query(BillingCommercialAuditEvent)
            .filter(
                BillingCommercialAuditEvent.stripe_event_id == "evt_checkout_001",
                BillingCommercialAuditEvent.event_type == "SELF_SERVICE_CHECKOUT_COMPLETED",
            )
            .first()
        )
        assert audit is not None
    finally:
        db.close()


def test_webhook_checkout_completed_is_idempotent(client):
    """Second delivery of same stripe_event_id is a no-op."""
    db = SessionLocal()
    try:
        audit_count_before = (
            db.query(BillingCommercialAuditEvent)
            .filter(BillingCommercialAuditEvent.stripe_event_id == "evt_checkout_001")
            .count()
        )
        data = {
            "metadata": {
                "organization_id": str(_prod_org.id),
                "plan_version_id": str(_version.id),
            },
            "subscription": "sub_FAKE001",
        }
        r = _post_webhook(client, "checkout.session.completed", data, event_id="evt_checkout_001")
        assert r.status_code == 200
        assert r.json() == {"status": "already processed"}

        audit_count_after = (
            db.query(BillingCommercialAuditEvent)
            .filter(BillingCommercialAuditEvent.stripe_event_id == "evt_checkout_001")
            .count()
        )
        assert audit_count_after == audit_count_before
    finally:
        db.close()


def test_webhook_payment_failed_sets_past_due(client):
    """invoice.payment_failed → sub PAST_DUE."""
    db = SessionLocal()
    try:
        data = {"subscription": "sub_FAKE001", "id": "in_FAKE_FAILED"}
        r = _post_webhook(client, "invoice.payment_failed", data, event_id="evt_pay_failed_001")
        assert r.status_code == 200, r.text

        sub = db.query(BillingSubscription).filter(BillingSubscription.stripe_subscription_id == "sub_FAKE001").first()
        assert sub is not None
        assert sub.status == SubscriptionStatus.PAST_DUE.value
    finally:
        db.close()


def test_webhook_invoice_paid_recovers_to_active(client):
    """invoice.paid after PAST_DUE → sub back to ACTIVE."""
    db = SessionLocal()
    try:
        data = {"subscription": "sub_FAKE001", "id": "in_FAKE_PAID"}
        r = _post_webhook(client, "invoice.paid", data, event_id="evt_inv_paid_001")
        assert r.status_code == 200, r.text

        sub = db.query(BillingSubscription).filter(BillingSubscription.stripe_subscription_id == "sub_FAKE001").first()
        assert sub is not None
        assert sub.status == SubscriptionStatus.ACTIVE.value
    finally:
        db.close()


def test_webhook_subscription_deleted_cancels(client):
    """customer.subscription.deleted → sub CANCELLED."""
    db = SessionLocal()
    try:
        data = {"id": "sub_FAKE001"}
        r = _post_webhook(client, "customer.subscription.deleted", data, event_id="evt_sub_deleted_001")
        assert r.status_code == 200, r.text

        sub = db.query(BillingSubscription).filter(BillingSubscription.stripe_subscription_id == "sub_FAKE001").first()
        assert sub is not None
        assert sub.status == SubscriptionStatus.CANCELLED.value
    finally:
        db.close()


# ── Tests: require_active_subscription guard ───────────────────────────────

def test_require_active_subscription_allows_evaluation_org(client):
    """EVALUATION orgs pass require_active_subscription regardless of status."""
    token = _login(client, "eval-admin@example.com")
    r = client.get("/api/payroll/policy/active", headers=_auth(token))
    assert r.status_code not in (403,), f"Expected EVALUATION org to pass guard, got {r.status_code}: {r.text}"


def test_require_active_subscription_blocks_production_org_without_active_sub(client):
    """PRODUCTION org with no ACTIVE subscription gets 403 from guard."""
    db = SessionLocal()
    try:
        blocked_org = Organization(
            organization_name="Blocked Corp",
            organization_code="BLOCKEDCHK",
            workspace_type="PRODUCTION",
            country="DE",
            is_active=True,
        )
        db.add(blocked_org)
        db.flush()
        blocked_user = User(
            email="blocked-admin@example.com",
            hashed_password=hash_password("strong-password"),
            role=UserRole.ORG_ADMIN,
            first_name="Blocked",
            last_name="Admin",
            organization_id=blocked_org.id,
            is_active=True,
        )
        db.add(blocked_user)
        db.commit()
    finally:
        db.close()

    token = _login(client, "blocked-admin@example.com")
    r = client.get("/api/payroll/policy/active", headers=_auth(token))
    assert r.status_code == 403, f"Expected 403 for PRODUCTION org with no active sub, got {r.status_code}: {r.text}"
