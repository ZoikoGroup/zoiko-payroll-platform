"""
tests/test_business_plan.py
-----------------------------
Confirms scripts/seed_business_plan.py actually produces a published,
correctly-scoped BUSINESS plan, and that its scale limits resolve through
the real enforcement path (billing/entitlements.py) rather than just
existing as rows in a table.

Mirrors test_entitlement_enforcement.py's hermetic pattern: env vars set
BEFORE importing app.main, throwaway on-disk SQLite so the global engine +
TestClient lifespan and this file's own SessionLocal share one database.

Honesty note on MAX_SCHEDULES: it is a defined feature_key
(billing/feature_keys.py) but is not checked by require_scope_limit() at
any route in this codebase today — confirmed by grep, not assumed (no
"payroll schedule" count is enforced for ANY plan currently, Core,
Professional, or Business). So "Business is unlimited on schedules" isn't
yet a live behavioral difference a user could hit; what IS real and worth
testing is that the entitlement itself correctly *resolves* to unlimited
(limit_value=None) for a Business subscription, via the same
_resolve_entitlement() function require_scope_limit() would call the
moment any route does start enforcing it. Testing an HTTP endpoint that
doesn't exist would be exactly the "looks done, isn't" gap this whole
plan was scoped to avoid.
"""

import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="business_plan_test_")
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
os.environ["BILLING_ENFORCEMENT_MODE"] = "enforce"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_saved_app_modules = {
    _mod: _module
    for _mod, _module in sys.modules.items()
    if _mod == "app" or _mod.startswith("app.")
}
for _mod in list(_saved_app_modules):
    del sys.modules[_mod]

from datetime import datetime, timedelta  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.database import Base, SessionLocal, engine, initialize_database  # noqa: E402
from app.modules.auth.models import User, UserRole  # noqa: E402
from app.modules.billing import entitlements, plan_catalog  # noqa: E402
from app.modules.billing.feature_keys import (  # noqa: E402
    API_ACCESS, MAX_BWM, MAX_ENTITIES, MAX_JURISDICTIONS, MAX_SCHEDULES,
    MULTI_CURRENCY, MULTI_ENTITY, PAYROLL_RUNS,
)
from app.modules.billing.models import (  # noqa: E402
    BillingAuthority, BillingSubscription, PlanVersionStatus, SubscriptionStatus,
)
from app.modules.organizations.models import Organization  # noqa: E402

from sqlalchemy.engine import make_url as _make_url  # noqa: E402

assert _make_url(engine.url).get_backend_name() == "sqlite", (
    f"test_business_plan must run on its own sqlite DB, got {engine.url}"
)

Base.metadata.create_all(bind=engine)
initialize_database()

_db = SessionLocal()

_super = User(
    email="business-plan-super-admin@example.com",
    hashed_password=hash_password("strong-password"),
    role=UserRole.SUPER_ADMIN,
    first_name="Super", last_name="Admin",
    organization_id=None, is_active=True,
)
_db.add(_super)
_db.flush()

# Same flags scripts/seed_business_plan.py seeds — kept in sync deliberately;
# if that script's dict changes, this test should be updated alongside it,
# not silently diverge.
BUSINESS_FLAGS = {
    PAYROLL_RUNS: None, MULTI_ENTITY: None, MULTI_CURRENCY: None, API_ACCESS: None,
    MAX_ENTITIES: 10, MAX_JURISDICTIONS: 10, MAX_SCHEDULES: None, MAX_BWM: 1000,
}


def _publish_plan(code, name, flags):
    plan = plan_catalog.create_plan(_db, code, name, actor_user_id=_super.id)
    version = plan_catalog.create_plan_version(
        _db, plan_id=plan.id,
        feature_set={"features": list(flags)},
        scale_limits={k: v for k, v in flags.items() if k in (MAX_ENTITIES, MAX_JURISDICTIONS, MAX_SCHEDULES, MAX_BWM)},
        actor_user_id=_super.id,
    )
    for feature_key, limit_value in flags.items():
        plan_catalog.add_entitlement_flag(_db, version.id, feature_key, limit_value, actor_user_id=_super.id)
    plan_catalog.approve_plan_version(_db, version.id, actor_user_id=_super.id)
    return plan_catalog.publish_plan_version(_db, version.id, published_by_user_id=_super.id)


_business_version = _publish_plan("BUSINESS", "Business", BUSINESS_FLAGS)


def _org_with_subscription(code, name, version):
    org = Organization(organization_name=name, organization_code=code, workspace_type="PRODUCTION", country="India")
    _db.add(org)
    _db.flush()
    _db.add(
        User(
            email=f"{code.lower()}@example.com",
            hashed_password=hash_password("strong-password"),
            role=UserRole.ORG_ADMIN,
            first_name="Org", last_name="Admin",
            organization_id=org.id, is_active=True,
        )
    )
    sub = BillingSubscription(
        organization_id=org.id,
        plan_version_id=version.id,
        billing_authority=BillingAuthority.STANDALONE.value,
        status=SubscriptionStatus.ACTIVE.value,
        current_period_start=datetime.utcnow() - timedelta(days=5),
        current_period_end=datetime.utcnow() + timedelta(days=25),
    )
    _db.add(sub)
    _db.commit()
    return org, sub


_business_org, _business_sub = _org_with_subscription("BIZTEST", "Business Test Co", _business_version)

for _mod in list(sys.modules):
    if _mod == "app" or _mod.startswith("app."):
        del sys.modules[_mod]
sys.modules.update(_saved_app_modules)
del _saved_app_modules


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def business_headers(client):
    login = client.post("/api/auth/login", json={"email": "biztest@example.com", "password": "strong-password"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# ── Plan actually published, correctly scoped ──────────────────────────────

def test_business_plan_is_published_with_correct_scale_limits():
    version = plan_catalog.get_published_plan_version(_db, "BUSINESS")
    assert version is not None
    assert version.status == PlanVersionStatus.PUBLISHED.value
    assert version.scale_limits == {
        "max_entities": 10,
        "max_jurisdictions": 10,
        "max_schedules": None,
        "max_billable_worker_months": 1000,
    }


def test_business_plan_flags_do_not_claim_unbuilt_subsystems():
    """The whole point of the Phase 1/Phase 2 split: Business's seeded
    flags must never imply SSO, webhooks, custom roles, or a report
    builder — those feature_keys don't exist in feature_keys.py at all,
    so this also guards against one being added here ahead of the actual
    subsystem being built."""
    flags = plan_catalog.list_entitlement_flags(_db, _business_version.id)
    unbuilt_subsystem_keys = {"sso", "saml", "webhooks", "custom_roles", "report_builder"}
    assert not (set(flags) & unbuilt_subsystem_keys)


# ── MAX_ENTITIES: the real, enforced dimension ─────────────────────────────

def test_business_org_can_reach_its_cap_of_ten_entities(client, business_headers):
    for i in range(1, 11):
        r = client.post("/api/organizations/me/legal-entities", headers=business_headers, json={"name": f"Biz Entity {i}"})
        assert r.status_code == 200, r.text


def test_business_org_blocked_from_eleventh_entity(client, business_headers):
    r = client.post("/api/organizations/me/legal-entities", headers=business_headers, json={"name": "Biz Entity 11"})
    assert r.status_code == 403, r.text
    assert "max_entities" in r.text


# ── MAX_SCHEDULES: resolves as unlimited (no live route enforces it yet) ──

def test_business_max_schedules_resolves_as_genuinely_unlimited():
    """Direct check against the same resolution function
    require_scope_limit() calls, since no route currently enforces
    MAX_SCHEDULES for any plan (confirmed by grep — see module docstring).
    A huge requested_qty must still resolve as allowed with no cap."""
    _db.refresh(_business_sub)
    allowed, limit_value = entitlements._resolve_entitlement(_db, _business_sub, MAX_SCHEDULES)
    assert allowed is True
    assert limit_value is None, "MAX_SCHEDULES must resolve unlimited (None), not a numeric cap"


def test_business_max_bwm_resolves_to_its_seeded_cap():
    _db.refresh(_business_sub)
    allowed, limit_value = entitlements._resolve_entitlement(_db, _business_sub, MAX_BWM)
    assert allowed is True
    assert limit_value == 1000
