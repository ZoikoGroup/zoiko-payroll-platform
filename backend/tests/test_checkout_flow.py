"""
tests/test_checkout_flow.py
-----------------------------
Integration tests for Path 2 (Self-Service Paid Checkout):

    1. POST /billing/checkout allows EVALUATION workspace upgrades
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
from datetime import date, datetime, timedelta
from decimal import Decimal
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
os.environ["STRIPE_AUTOMATIC_TAX_ENABLED"] = "true"

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
    BillingDunningState,
    BillingPriceCatalogItem,
    BillingSubscription,
    BillingSubscriptionItem,
    CatalogItemStatus,
    DunningStage,
    EnterpriseOrderForm,
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

# Step 7 — a PUBLISHED price-catalog row for PROFESSIONAL, the only plan the
# checkout tests buy. GET /billing/plans and the webhook's subscription-item
# wiring both resolve the price from billing_price_catalog_items.
_catalog_item = BillingPriceCatalogItem(
    catalog_version="2026-STANDALONE",
    component_type="PROFESSIONAL",
    currency="USD",
    unit_amount=Decimal("50.00"),
    status=CatalogItemStatus.PUBLISHED.value,
)
_db.add(_catalog_item)
_db.commit()
_db.refresh(_catalog_item)

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

# LEGACY-classified org — Part 1's is_billable() gate must refuse checkout
# for this classification even though it's a PRODUCTION workspace with a
# real country, distinct from the NON_CHARGEABLE default which checkout's
# own auto-promotion is supposed to let through.
_legacy_org = Organization(
    organization_name="Legacy Corp",
    organization_code="LEGACYCHK",
    workspace_type="PRODUCTION",
    country="DE",
    is_active=True,
    billing_classification="LEGACY",
    charge_enabled=False,
)
_db.add(_legacy_org)
_db.flush()
_legacy_user = User(
    email="legacy-admin@example.com",
    hashed_password=hash_password("strong-password"),
    role=UserRole.ORG_ADMIN,
    first_name="Legacy",
    last_name="Admin",
    organization_id=_legacy_org.id,
    is_active=True,
)
_db.add(_legacy_user)
_db.flush()

# Fresh, untouched NON_CHARGEABLE org, dedicated to the auto-promotion test
# below — _prod_org gets mutated by earlier tests in this file (each one
# calls checkout for it), so it can't be relied on to still be
# NON_CHARGEABLE by the time that test runs.
_fresh_org = Organization(
    organization_name="Fresh Corp",
    organization_code="FRESHCHK",
    workspace_type="PRODUCTION",
    country="DE",
    is_active=True,
)
_db.add(_fresh_org)
_db.flush()
_fresh_user = User(
    email="fresh-admin@example.com",
    hashed_password=hash_password("strong-password"),
    role=UserRole.ORG_ADMIN,
    first_name="Fresh",
    last_name="Admin",
    organization_id=_fresh_org.id,
    is_active=True,
)
_db.add(_fresh_user)
_db.flush()

# Enterprise Order Form org — Step 6 / Part 12's overlapping-ownership rule
# in the OTHER direction from test_record_order_form_rejected...: an org
# whose billing is already governed by a recorded Order Form must be
# refused self-service checkout, never silently handed a second route.
_enterprise_chk_org = Organization(
    organization_name="Enterprise Chk Corp",
    organization_code="ENTCHK",
    workspace_type="PRODUCTION",
    country="DE",
    is_active=True,
    billing_classification="COMMERCIAL_ACTIVE",
    charge_enabled=True,
    commercial_route=BillingAuthority.ENTERPRISE_ORDER_FORM.value,
)
_db.add(_enterprise_chk_org)
_db.flush()
_db.add(EnterpriseOrderForm(
    organization_id=_enterprise_chk_org.id,
    contract_reference="OF-CHK-001",
    negotiated_scale_limits={"max_entities": 25},
    negotiated_price_terms={"annual_usd": 250000},
    term_start=date.today(),
    signed_by=_super.id,
))
_db.add(BillingSubscription(
    organization_id=_enterprise_chk_org.id,
    plan_version_id=None,
    billing_authority=BillingAuthority.ENTERPRISE_ORDER_FORM.value,
    status=SubscriptionStatus.ACTIVE.value,
    current_period_start=datetime.utcnow() - timedelta(days=10),
    current_period_end=datetime.utcnow() + timedelta(days=355),
))
_db.flush()
_enterprise_chk_user = User(
    email="enterprise-admin@example.com",
    hashed_password=hash_password("strong-password"),
    role=UserRole.ORG_ADMIN,
    first_name="Enterprise",
    last_name="Admin",
    organization_id=_enterprise_chk_org.id,
    is_active=True,
)
_db.add(_enterprise_chk_user)
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
    # Real Stripe API versions (2025-06-30+) no longer put current_period_end
    # on the Subscription object itself — only on each subscription item.
    # __getitem__ must match that shape since router.py reads it that way.
    mock_sub.__getitem__.side_effect = lambda key: {
        "items": {"data": [{"current_period_end": mock_sub.current_period_end}]},
    }[key]

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

    # Step 5 / blockers #8/#9 — jurisdiction-aware SaaS tax must be
    # delegated to Stripe Tax on every checkout session, not bolted on
    # only sometimes.
    call_kwargs = stripe.checkout.Session.create.call_args.kwargs
    assert call_kwargs["automatic_tax"] == {"enabled": True}
    assert call_kwargs["tax_id_collection"] == {"enabled": True}
    assert call_kwargs["billing_address_collection"] == "required"


def test_checkout_auto_promotes_non_chargeable_org_to_commercial_active(client):
    """Part 1 (§A1) — _fresh_org starts NON_CHARGEABLE (the schema
    default). A successful checkout call must auto-promote it to
    COMMERCIAL_ACTIVE/charge_enabled=True/commercial_route=STANDALONE —
    this IS the bootstrap path, not a separate manual step."""
    db = SessionLocal()
    try:
        org = db.query(Organization).filter(Organization.id == _fresh_org.id).first()
        assert org.billing_classification == "NON_CHARGEABLE"
        assert org.charge_enabled is False
    finally:
        db.close()

    token = _login(client, "fresh-admin@example.com")
    r = client.post("/api/billing/checkout", json={"plan_code": "PROFESSIONAL"}, headers=_auth(token))
    assert r.status_code == 200, r.text

    db = SessionLocal()
    try:
        org = db.query(Organization).filter(Organization.id == _fresh_org.id).first()
        assert org.billing_classification == "COMMERCIAL_ACTIVE"
        assert org.charge_enabled is True
        assert org.commercial_route == "STANDALONE"
    finally:
        db.close()


def test_checkout_refuses_legacy_classified_org(client):
    """Part 1 (§A1) — is_billable() must fail closed for a LEGACY org even
    though nothing else about it (PRODUCTION workspace, real country) would
    otherwise block checkout. LEGACY must never be silently auto-promoted
    the way a fresh NON_CHARGEABLE org is."""
    token = _login(client, "legacy-admin@example.com")
    r = client.post("/api/billing/checkout", json={"plan_code": "PROFESSIONAL"}, headers=_auth(token))
    assert r.status_code == 403, r.text
    assert "not eligible for billing" in r.text.lower()

    db = SessionLocal()
    try:
        org = db.query(Organization).filter(Organization.id == _legacy_org.id).first()
        assert org.billing_classification == "LEGACY", "refused checkout must never mutate the org's classification"
        assert org.charge_enabled is False
    finally:
        db.close()


def test_checkout_refuses_org_with_enterprise_order_form(client):
    """Step 6 / Part 12 — the overlapping-ownership rule in the OTHER
    direction from record_order_form's own guard: an org whose billing is
    already governed by a recorded Enterprise Order Form must be refused
    self-service checkout. It's already COMMERCIAL_ACTIVE/charge_enabled
    (Step 1's fields, stamped by record_order_form), so it would sail
    straight through the is_billable() gate — the §12 route-overlap check
    must catch it before that happens."""
    db = SessionLocal()
    try:
        org = db.query(Organization).filter(Organization.id == _enterprise_chk_org.id).first()
        assert org.commercial_route == BillingAuthority.ENTERPRISE_ORDER_FORM.value
        assert org.billing_classification == "COMMERCIAL_ACTIVE"
        assert org.charge_enabled is True
    finally:
        db.close()

    token = _login(client, "enterprise-admin@example.com")
    r = client.post("/api/billing/checkout", json={"plan_code": "PROFESSIONAL"}, headers=_auth(token))
    assert r.status_code == 403, r.text
    assert "enterprise order form" in r.text.lower()

    db = SessionLocal()
    try:
        org = db.query(Organization).filter(Organization.id == _enterprise_chk_org.id).first()
        assert org.commercial_route == BillingAuthority.ENTERPRISE_ORDER_FORM.value
        assert org.billing_classification == "COMMERCIAL_ACTIVE"
        assert org.charge_enabled is True, "rejected checkout must leave the Order Form org's ledger untouched"
        sub = db.query(BillingSubscription).filter(BillingSubscription.organization_id == org.id).first()
        assert sub.billing_authority == BillingAuthority.ENTERPRISE_ORDER_FORM.value
        assert sub.plan_version_id is None
    finally:
        db.close()


# ── Tests: GET /billing/plans (Step 7 — catalog-driven pricing) ─────────────

def test_plans_list_resolves_prices_from_catalog(client):
    """Step 7 — /billing/plans is unauthenticated and must derive
    monthly_price_usd from billing_price_catalog_items (plus the per-line
    price_components breakdown), never from a hardcoded dict."""
    r = client.get("/api/billing/plans")
    assert r.status_code == 200, r.text

    prof = next((p for p in r.json() if p["code"] == "PROFESSIONAL"), None)
    assert prof is not None, "PROFESSIONAL has a published version and must appear"
    assert prof["monthly_price_usd"] == 50.0

    components = prof["price_components"]
    assert isinstance(components, list) and len(components) == 1
    assert components[0]["component_type"] == "PROFESSIONAL"
    assert components[0]["currency"] == "USD"
    assert float(components[0]["unit_amount"]) == 50.0


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

        # Step 7 — the sub's base price is pinned to the PUBLISHED price
        # catalog via BillingSubscriptionItem.unit_price_catalog_ref.
        item = (
            db.query(BillingSubscriptionItem)
            .filter(BillingSubscriptionItem.subscription_id == sub.id)
            .first()
        )
        assert item is not None
        assert item.component_type == "RECURRING_BASE"
        assert item.quantity == 1
        assert item.unit_price_catalog_ref == _catalog_item.id

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

        # Step 4 / blocker #17 — payment_failed must upsert a
        # BillingDunningState row, not just flip subscription.status.
        dunning_state = db.query(BillingDunningState).filter(BillingDunningState.organization_id == sub.organization_id).first()
        assert dunning_state is not None
        assert dunning_state.stage == DunningStage.RETRY.value
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
