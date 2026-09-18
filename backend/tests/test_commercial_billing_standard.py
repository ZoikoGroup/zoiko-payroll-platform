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
from app.modules.billing.entitlements import (  # noqa: E402
    is_billable, is_service_commenced, has_in_flight_authorized_run,
    resolve_commercial_route, apply_zoiko_one_bundle_route, assert_no_overlapping_billable_ownership,
)
from app.modules.billing.enterprise_order_form import record_order_form  # noqa: E402
from app.core.exceptions import ForbiddenException  # noqa: E402
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


# ── Step 2 — commercial_route / billing_authority ledger (§12) ─────────────

def test_resolve_commercial_route_sets_org_and_subscription_together():
    """resolve_commercial_route is the one place both fields are ever set —
    calling it must leave them agreeing, on an org that already has a
    subscription (so the "stamp the subscription too" branch runs)."""
    org = Organization(organization_name="Route Test Co", organization_code="ROUTETEST", workspace_type="PRODUCTION")
    _db.add(org)
    _db.flush()
    sub = BillingSubscription(
        organization_id=org.id,
        plan_version_id=_dunning_version.id,
        billing_authority=BillingAuthority.STANDALONE.value,
        status=SubscriptionStatus.ACTIVE.value,
        current_period_start=datetime.utcnow(),
        current_period_end=datetime.utcnow() + timedelta(days=30),
    )
    _db.add(sub)
    _db.commit()

    resolve_commercial_route(_db, org, BillingAuthority.ZOIKO_ONE_BUNDLE.value)
    _db.commit()
    _db.refresh(org)
    _db.refresh(sub)

    assert org.commercial_route == BillingAuthority.ZOIKO_ONE_BUNDLE.value
    assert sub.billing_authority == BillingAuthority.ZOIKO_ONE_BUNDLE.value


def test_resolve_commercial_route_rejects_unrecognized_value():
    org = Organization(organization_name="x", organization_code="x")
    with pytest.raises(ValueError):
        resolve_commercial_route(_db, org, "NOT_A_REAL_ROUTE")


def test_apply_zoiko_one_bundle_route_stub_delegates_correctly():
    """The stub has no real caller yet, but must resolve to
    ZOIKO_ONE_BUNDLE exactly like a real entry point calling
    resolve_commercial_route directly would."""
    org = Organization(organization_name="Bundle Stub Co", organization_code="BUNDLESTUB", workspace_type="PRODUCTION")
    _db.add(org)
    _db.commit()

    apply_zoiko_one_bundle_route(_db, org)
    _db.commit()
    _db.refresh(org)
    assert org.commercial_route == BillingAuthority.ZOIKO_ONE_BUNDLE.value


def test_second_subscription_for_same_org_violates_unique_constraint():
    """The existing BillingSubscription.organization_id unique constraint
    must still hold — a second row for the same org is a real integrity
    error, not silently accepted."""
    from sqlalchemy.exc import IntegrityError

    org = Organization(organization_name="Dup Sub Co", organization_code="DUPSUB", workspace_type="PRODUCTION")
    _db.add(org)
    _db.flush()
    _db.add(BillingSubscription(
        organization_id=org.id, plan_version_id=_dunning_version.id,
        billing_authority=BillingAuthority.STANDALONE.value, status=SubscriptionStatus.ACTIVE.value,
        current_period_start=datetime.utcnow(), current_period_end=datetime.utcnow() + timedelta(days=30),
    ))
    _db.commit()

    _db.add(BillingSubscription(
        organization_id=org.id, plan_version_id=_dunning_version.id,
        billing_authority=BillingAuthority.STANDALONE.value, status=SubscriptionStatus.ACTIVE.value,
        current_period_start=datetime.utcnow(), current_period_end=datetime.utcnow() + timedelta(days=30),
    ))
    with pytest.raises(IntegrityError):
        _db.commit()
    _db.rollback()


def test_record_order_form_rejected_for_org_with_existing_standalone_subscription():
    """§12's core rule: an org already on a STANDALONE subscription must
    never have an Enterprise Order Form silently recorded on top of it —
    that would overlap two commercial routes without an explicit migration."""
    org = Organization(
        organization_name="Already Standalone Co", organization_code="ALREADYSA", workspace_type="PRODUCTION",
    )
    _db.add(org)
    _db.flush()
    _db.add(BillingSubscription(
        organization_id=org.id, plan_version_id=_dunning_version.id,
        billing_authority=BillingAuthority.STANDALONE.value, status=SubscriptionStatus.ACTIVE.value,
        current_period_start=datetime.utcnow(), current_period_end=datetime.utcnow() + timedelta(days=30),
    ))
    _db.commit()

    with pytest.raises(ForbiddenException):
        record_order_form(
            _db, organization_id=org.id, contract_reference="OF-REJECT-001",
            negotiated_scale_limits={"max_entities": 5}, negotiated_price_terms={"annual_usd": 50000},
            term_start=date.today(), term_end=None, signed_by_user_id=_super.id,
        )

    # The rejection must not have mutated anything.
    _db.refresh(org)
    assert org.commercial_route != BillingAuthority.ENTERPRISE_ORDER_FORM.value
    assert db_no_order_form_exists(org.id)


def db_no_order_form_exists(organization_id: int) -> bool:
    return _db.query(EnterpriseOrderForm).filter(EnterpriseOrderForm.organization_id == organization_id).first() is None


def test_record_order_form_succeeds_for_a_fresh_org():
    """Sanity check that the guard above doesn't over-block the legitimate
    case: a fresh org with no prior subscription at all. Also proves Step 1's
    ledger fields get stamped in the same transaction: commercial_route =
    ENTERPRISE_ORDER_FORM, billing_classification advances
    NON_CHARGEABLE -> COMMERCIAL_ACTIVE, charge_enabled flips True, and
    service_commencement_at takes the contract's term_start, not "now"."""
    org = Organization(organization_name="Fresh Enterprise Co", organization_code="FRESHENT", workspace_type="PRODUCTION")
    _db.add(org)
    _db.commit()

    order_form = record_order_form(
        _db, organization_id=org.id, contract_reference="OF-OK-001",
        negotiated_scale_limits={"max_entities": 5}, negotiated_price_terms={"annual_usd": 50000},
        term_start=date(2026, 10, 1), term_end=None, signed_by_user_id=_super.id,
    )
    assert order_form.id is not None

    _db.refresh(org)
    assert org.commercial_route == BillingAuthority.ENTERPRISE_ORDER_FORM.value
    assert org.billing_classification == "COMMERCIAL_ACTIVE"
    assert org.charge_enabled is True
    assert org.service_commencement_at == datetime(2026, 10, 1)
    sub = _db.query(BillingSubscription).filter(BillingSubscription.organization_id == org.id).first()
    assert sub.billing_authority == BillingAuthority.ENTERPRISE_ORDER_FORM.value
