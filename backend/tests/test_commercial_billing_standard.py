"""
tests/test_commercial_billing_standard.py
----------------------------------------------
Integration tests for the Commercial Billing & Subscription Operating
Standard's safety-critical and foundational pieces:

  - Part 1: is_billable()/is_service_commenced() defaults (blockers #12, #13)
  - Part 9: the dunning guard — THE most important test in this whole
    initiative per its own spec: "get it wrong and a real customer's
    employees don't get paid over a billing dispute."
  - Part 12: Enterprise Order Form entitlement resolution (no plan version
    at all, by design)

Mirrors test_entitlement_enforcement.py's hermetic pattern: env vars set
BEFORE importing app.main, throwaway on-disk SQLite so the global engine +
TestClient lifespan and this file's own SessionLocal share one database.
"""

import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="commercial_billing_test_")
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
os.environ["DUNNING_SWEEP_ENABLED"] = "false"
os.environ["BILLING_ENFORCEMENT_MODE"] = "off"  # dunning guard is independent of this switch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_saved_app_modules = {
    _mod: _module
    for _mod, _module in sys.modules.items()
    if _mod == "app" or _mod.startswith("app.")
}
for _mod in list(_saved_app_modules):
    del sys.modules[_mod]

from datetime import date, datetime, timedelta  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.database import Base, SessionLocal, engine, initialize_database  # noqa: E402
from app.modules.auth.models import User, UserRole  # noqa: E402
from app.modules.billing import plan_catalog  # noqa: E402
from app.modules.billing.dunning import get_or_create_dunning_state  # noqa: E402
from app.modules.billing.entitlements import is_billable, is_service_commenced, has_in_flight_authorized_run  # noqa: E402
from app.modules.billing.models import (  # noqa: E402
    BillingAuthority, BillingDunningState, BillingSubscription, DunningStage, EnterpriseOrderForm, SubscriptionStatus,
)
from app.modules.organizations.models import Organization  # noqa: E402
from app.modules.payroll.models import PayrollRun, PayrollStatus  # noqa: E402

from sqlalchemy.engine import make_url as _make_url  # noqa: E402

assert _make_url(engine.url).get_backend_name() == "sqlite", (
    f"test_commercial_billing_standard must run on its own sqlite DB, got {engine.url}"
)

Base.metadata.create_all(bind=engine)
initialize_database()

_db = SessionLocal()

_super = User(
    email="commercial-super-admin@example.com",
    hashed_password=hash_password("strong-password"),
    role=UserRole.SUPER_ADMIN,
    first_name="Super", last_name="Admin",
    organization_id=None, is_active=True,
)
_db.add(_super)
_db.flush()

# ── Org with a PAST_DUE subscription, RESTRICT_NEW_RUN dunning stage, and
# one AUTHORIZED run with a future pay_date — the exact scenario Part 9's
# own spec names as "the single most important test in this entire prompt."
_dunning_org = Organization(
    organization_name="Dunning Test Co", organization_code="DUNNINGTEST",
    workspace_type="PRODUCTION", billing_classification="COMMERCIAL_ACTIVE", charge_enabled=True,
)
_db.add(_dunning_org)
_db.flush()
_db.add(
    User(
        email="dunningtest@example.com",
        hashed_password=hash_password("strong-password"),
        role=UserRole.ORG_ADMIN,
        first_name="Org", last_name="Admin",
        organization_id=_dunning_org.id, is_active=True,
    )
)
_dunning_plan = plan_catalog.create_plan(_db, "PROFESSIONAL", "Professional", actor_user_id=_super.id)
_dunning_version = plan_catalog.create_plan_version(
    _db, plan_id=_dunning_plan.id, feature_set={"features": ["payroll_runs"]}, scale_limits={}, actor_user_id=_super.id,
)
plan_catalog.approve_plan_version(_db, _dunning_version.id, actor_user_id=_super.id)
plan_catalog.publish_plan_version(_db, _dunning_version.id, published_by_user_id=_super.id)
_db.add(
    BillingSubscription(
        organization_id=_dunning_org.id,
        plan_version_id=_dunning_version.id,
        billing_authority=BillingAuthority.STANDALONE.value,
        status=SubscriptionStatus.PAST_DUE.value,
        current_period_start=datetime.utcnow() - timedelta(days=30),
        current_period_end=datetime.utcnow() - timedelta(days=10),
    )
)
_authorized_run = PayrollRun(
    organization_id=_dunning_org.id,
    period_label="In-flight authorized run",
    period_start=date.today() - timedelta(days=5),
    period_end=date.today(),
    pay_date=date.today() + timedelta(days=3),  # in the future — genuinely in flight
    status=PayrollStatus.AUTHORIZED.value,
)
_db.add(_authorized_run)
_db.flush()
_dunning_state = BillingDunningState(
    organization_id=_dunning_org.id,
    stage=DunningStage.RESTRICT_NEW_RUN.value,
    entered_at=datetime.utcnow() - timedelta(days=10),
)
_db.add(_dunning_state)
_db.commit()

# ── Enterprise Order Form org — no plan version at all, by design.
_enterprise_org = Organization(
    organization_name="Enterprise OF Co", organization_code="ENTOF",
    workspace_type="PRODUCTION", billing_classification="COMMERCIAL_ACTIVE", charge_enabled=True,
    commercial_route=BillingAuthority.ENTERPRISE_ORDER_FORM.value,
)
_db.add(_enterprise_org)
_db.flush()
_db.add(EnterpriseOrderForm(
    organization_id=_enterprise_org.id,
    contract_reference="OF-TEST-001",
    negotiated_scale_limits={"max_entities": 10, "multi_entity": None, "api_access": 0},
    negotiated_price_terms={"annual_usd": 100000},
    term_start=date.today() - timedelta(days=30),
))
_enterprise_sub = BillingSubscription(
    organization_id=_enterprise_org.id,
    plan_version_id=None,
    billing_authority=BillingAuthority.ENTERPRISE_ORDER_FORM.value,
    status=SubscriptionStatus.ACTIVE.value,
    current_period_start=datetime.utcnow() - timedelta(days=30),
    current_period_end=datetime.utcnow() + timedelta(days=335),
)
_db.add(_enterprise_sub)
_db.commit()

for _mod in list(sys.modules):
    if _mod == "app" or _mod.startswith("app."):
        del sys.modules[_mod]
sys.modules.update(_saved_app_modules)
del _saved_app_modules


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _headers(client, org_code):
    login = client.post("/api/auth/login", json={"email": f"{org_code.lower()}@example.com", "password": "strong-password"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture(scope="module")
def dunning_headers(client):
    return _headers(client, "dunningtest")


# ── Part 1 — commercial ledger defaults ────────────────────────────────────

def test_is_billable_false_by_default():
    org = Organization(organization_name="x", organization_code="x", billing_classification="NON_CHARGEABLE", charge_enabled=False)
    assert is_billable(org) is False


def test_is_billable_true_only_when_both_conditions_hold():
    org = Organization(organization_name="x", organization_code="x", billing_classification="COMMERCIAL_ACTIVE", charge_enabled=True)
    assert is_billable(org) is True

    half = Organization(organization_name="x", organization_code="x", billing_classification="COMMERCIAL_ACTIVE", charge_enabled=False)
    assert is_billable(half) is False


def test_is_service_commenced_requires_past_date():
    org = Organization(organization_name="x", organization_code="x", service_commencement_at=None)
    assert is_service_commenced(org) is False

    org.service_commencement_at = datetime.utcnow() + timedelta(days=5)
    assert is_service_commenced(org) is False

    org.service_commencement_at = datetime.utcnow() - timedelta(days=1)
    assert is_service_commenced(org) is True


# ── Part 9 — THE critical dunning test ─────────────────────────────────────

def test_dunning_blocks_new_run_creation(client, dunning_headers):
    r = client.post(
        "/api/payroll/runs",
        headers=dunning_headers,
        json={"periodLabel": "New run attempt", "periodStart": "2026-01-01", "periodEnd": "2026-01-31", "payDate": "2026-02-01"},
    )
    assert r.status_code == 403, r.text
    assert "restricted" in r.text.lower()


def test_dunning_does_not_block_completing_the_in_flight_authorized_run(client, dunning_headers):
    """The one test this whole initiative is built around: an org
    RESTRICTED by dunning must still be able to advance its already-
    AUTHORIZED, not-yet-paid run to completion."""
    assert has_in_flight_authorized_run(_db, _dunning_org.id) is True

    r = client.put(f"/api/payroll/runs/{_authorized_run.id}/approve", headers=dunning_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == PayrollStatus.PAID.value


def test_invoice_paid_resets_dunning_state():
    from app.modules.billing.dunning import reset_dunning

    state = get_or_create_dunning_state(_db, _dunning_org.id)
    assert state.stage == DunningStage.RESTRICT_NEW_RUN.value

    reset_dunning(_db, _dunning_org.id)
    _db.commit()
    _db.refresh(state)
    assert state.stage == DunningStage.RETRY.value
    assert state.in_flight_run_guard is False


# ── Part 12 — Enterprise Order Form entitlement resolution ──────────────────

def test_enterprise_order_form_resolves_entitlements_without_a_plan_version():
    from app.modules.billing.entitlements import get_active_subscription, entitlement_allows, _resolve_entitlement

    sub = get_active_subscription(_db, _enterprise_org.id)
    assert sub.plan_version_id is None

    assert entitlement_allows(_db, sub, "multi_entity") is True  # limit_value None -> on
    assert entitlement_allows(_db, sub, "api_access") is False  # limit_value 0 -> explicitly off

    allowed, limit_value = _resolve_entitlement(_db, sub, "max_entities")
    assert allowed is True
    assert limit_value == 10
