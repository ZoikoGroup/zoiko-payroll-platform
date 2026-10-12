"""
tests/test_entitlement_enforcement.py
----------------------------------------
Integration tests for real plan-limit enforcement (billing/entitlements.py
require_entitlement()/require_scope_limit(), now actually wired into
organizations/router.py, payroll/router.py, payroll/enterprise/router.py,
and assist/router.py — previously these were defined but called from
nowhere).

Runs with BILLING_ENFORCEMENT_MODE=enforce so every check in this file
actually raises when a limit is exceeded, matching how the flag will
behave once explicitly flipped in production (default remains "off" —
see test_enforcement_mode_off_and_warn_are_regression_safe below, which
covers the "off"/"warn" behavior this file's other tests don't exercise).

Mirrors test_trial_lifecycle.py's hermetic pattern: env vars set BEFORE
importing app.main, throwaway on-disk SQLite so the global engine +
TestClient lifespan and this file's own SessionLocal share one database.
"""

import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="entitlement_enforcement_test_")
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

from datetime import date, datetime, timedelta  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.config import settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.database import Base, SessionLocal, engine, initialize_database  # noqa: E402
from app.modules.auth.models import User, UserRole  # noqa: E402
from app.modules.billing import plan_catalog  # noqa: E402
from app.modules.billing.feature_keys import (  # noqa: E402
    API_ACCESS, ASSIST, MAX_BWM, MAX_ENTITIES, MAX_JURISDICTIONS, MAX_SCHEDULES,
    MULTI_CURRENCY, MULTI_ENTITY, PAYROLL_RUNS,
)
from app.modules.billing.models import (  # noqa: E402
    BillingAuthority, BillingCommercialAuditEvent, BillingSubscription, SubscriptionStatus,
)
from app.modules.organizations.models import LegalEntity, Organization  # noqa: E402
from app.modules.payroll.enterprise.models import EnterpriseJurisdiction  # noqa: E402
from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayrollStatus  # noqa: E402

from sqlalchemy.engine import make_url as _make_url  # noqa: E402

assert _make_url(engine.url).get_backend_name() == "sqlite", (
    f"test_entitlement_enforcement must run on its own sqlite DB, got {engine.url}"
)

Base.metadata.create_all(bind=engine)
initialize_database()

_db = SessionLocal()

_super = User(
    email="entitlement-super-admin@example.com",
    hashed_password=hash_password("strong-password"),
    role=UserRole.SUPER_ADMIN,
    first_name="Super", last_name="Admin",
    organization_id=None, is_active=True,
)
_db.add(_super)
_db.flush()

CORE_FLAGS = {
    PAYROLL_RUNS: None, MAX_ENTITIES: 1, MAX_JURISDICTIONS: 1, MAX_SCHEDULES: 2, MAX_BWM: 3,
    MULTI_ENTITY: 0, MULTI_CURRENCY: 0, API_ACCESS: 0, ASSIST: 0,
}
PROFESSIONAL_FLAGS = {
    PAYROLL_RUNS: None, MAX_ENTITIES: 3, MAX_JURISDICTIONS: 3, MAX_SCHEDULES: 10, MAX_BWM: 5,
    MULTI_ENTITY: None, MULTI_CURRENCY: None, API_ACCESS: None, ASSIST: None,
}
# MAX_BWM kept deliberately small (3 / 5) for this test file so seeding
# "one under the limit" doesn't mean creating hundreds of PayrollEmployee
# rows — the enforcement logic (current_count + 1 vs. limit_value) is
# identical regardless of the limit's magnitude.


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


_core_version = _publish_plan("CORE", "Core", CORE_FLAGS)
_professional_version = _publish_plan("PROFESSIONAL", "Professional", PROFESSIONAL_FLAGS)


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
    _db.add(
        BillingSubscription(
            organization_id=org.id,
            plan_version_id=version.id,
            billing_authority=BillingAuthority.STANDALONE.value,
            status=SubscriptionStatus.ACTIVE.value,
            current_period_start=datetime.utcnow() - timedelta(days=5),
            current_period_end=datetime.utcnow() + timedelta(days=25),
        )
    )
    _db.commit()
    return org


_core_org = _org_with_subscription("ENTCORE", "Entitlement Core Co", _core_version)
_pro_org = _org_with_subscription("ENTPRO", "Entitlement Professional Co", _professional_version)

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
def core_headers(client):
    return _headers(client, "ENTCORE")


@pytest.fixture(scope="module")
def pro_headers(client):
    return _headers(client, "ENTPRO")


# ── Legal entities (MAX_ENTITIES + MULTI_ENTITY) ───────────────────────────

def test_core_org_can_create_its_first_legal_entity(client, core_headers):
    r = client.post("/api/organizations/me/legal-entities", headers=core_headers, json={"name": "Core HQ"})
    assert r.status_code == 200, r.text


def test_core_org_blocked_from_second_legal_entity(client, core_headers):
    # Core's plan has BOTH multi_entity=0 and max_entities=1 — the route
    # checks MULTI_ENTITY first once count>=1, so either a "not entitled"
    # or an "over limit" 403 is a correct block here; what matters is that
    # a 2nd entity is blocked at all.
    r = client.post("/api/organizations/me/legal-entities", headers=core_headers, json={"name": "Core Branch 2"})
    assert r.status_code == 403, r.text
    assert "multi_entity" in r.text or "max_entities" in r.text


def test_professional_org_can_reach_its_cap_of_three_entities(client, pro_headers):
    for name in ["Pro Entity 1", "Pro Entity 2", "Pro Entity 3"]:
        r = client.post("/api/organizations/me/legal-entities", headers=pro_headers, json={"name": name})
        assert r.status_code == 200, r.text


def test_professional_org_blocked_from_fourth_legal_entity(client, pro_headers):
    r = client.post("/api/organizations/me/legal-entities", headers=pro_headers, json={"name": "Pro Entity 4"})
    assert r.status_code == 403, r.text


# ── Jurisdictions (MAX_JURISDICTIONS) ──────────────────────────────────────

def test_core_org_can_add_its_first_jurisdiction(client, core_headers):
    r = client.post("/api/payroll/enterprise/jurisdictions", headers=core_headers, json={"countryCode": "IN"})
    assert r.status_code == 200, r.text


def test_core_org_blocked_from_second_jurisdiction(client, core_headers):
    r = client.post("/api/payroll/enterprise/jurisdictions", headers=core_headers, json={"countryCode": "US"})
    assert r.status_code == 403, r.text


def test_professional_org_can_reach_its_cap_of_three_jurisdictions(client, pro_headers):
    for country in ["IN", "US", "UK"]:
        r = client.post("/api/payroll/enterprise/jurisdictions", headers=pro_headers, json={"countryCode": country})
        assert r.status_code == 200, r.text


def test_professional_org_blocked_from_fourth_jurisdiction(client, pro_headers):
    r = client.post("/api/payroll/enterprise/jurisdictions", headers=pro_headers, json={"countryCode": "AU"})
    assert r.status_code == 403, r.text


# ── Billable worker-months (MAX_BWM) ────────────────────────────────────────

def _seed_active_employees(org_id, count, start_at=0):
    for i in range(start_at, start_at + count):
        _db.add(
            PayrollEmployee(
                organization_id=org_id,
                employee_code=f"E{i}",
                name=f"Employee {i}",
                status="Active",
            )
        )
    _db.commit()


def test_core_org_blocked_at_bwm_limit_boundary(client, core_headers):
    # CORE_FLAGS caps max_billable_worker_months at 3 — pre-seed 3 directly
    # (bypassing the API for speed) so the API call under test is exactly
    # the (limit+1)th, the boundary the enforcement check must catch.
    _seed_active_employees(_core_org.id, 3)
    r = client.post("/api/payroll/employees", headers=core_headers, json={"employee_code": "E-OVER", "name": "One Too Many"})
    assert r.status_code == 403, r.text
    assert "max_billable_worker_months" in r.text


def test_professional_org_allows_bwm_up_to_its_higher_cap(client, pro_headers):
    # PROFESSIONAL_FLAGS caps at 5 — pre-seed 4 so the API call under test
    # is exactly the 5th (still within the cap) and must succeed.
    _seed_active_employees(_pro_org.id, 4)
    r = client.post("/api/payroll/employees", headers=pro_headers, json={"employee_code": "E-5", "name": "Fifth Employee"})
    assert r.status_code == 200, r.text


def test_professional_org_blocked_at_its_own_bwm_boundary(client, pro_headers):
    r = client.post("/api/payroll/employees", headers=pro_headers, json={"employee_code": "E-6", "name": "Sixth Employee"})
    assert r.status_code == 403, r.text


# ── Assist entitlement (ASSIST) ─────────────────────────────────────────────

def test_core_org_blocked_from_assist(client, core_headers):
    r = client.get("/api/assist/capabilities", headers=core_headers)
    assert r.status_code == 403, r.text


def test_professional_org_can_use_assist(client, pro_headers):
    r = client.get("/api/assist/capabilities", headers=pro_headers)
    assert r.status_code == 200, r.text


# ── Multi-currency (MULTI_CURRENCY) ─────────────────────────────────────────

def test_core_org_blocked_from_currency_override(client, core_headers):
    r = client.put("/api/organizations/me", headers=core_headers, json={"currency": "EUR"})
    assert r.status_code == 403, r.text


def test_professional_org_can_set_currency_override(client, pro_headers):
    r = client.put("/api/organizations/me", headers=pro_headers, json={"currency": "EUR"})
    assert r.status_code == 200, r.text
    # OrganizationResponse doesn't echo `currency` back (pre-existing schema
    # gap, unrelated to entitlements) — confirm the write landed via the DB.
    _db.refresh(_pro_org)
    assert _pro_org.currency == "EUR"


def test_org_update_without_touching_currency_is_never_gated(client, core_headers):
    """A Core org must still be able to update ordinary fields — the
    MULTI_CURRENCY gate only fires when `currency` is actually present in
    the request body, never on unrelated PUT /me calls."""
    r = client.put("/api/organizations/me", headers=core_headers, json={"city": "Bengaluru"})
    assert r.status_code == 200, r.text


# ── is_run_in_flight precedence (P4 guard) ──────────────────────────────────

def test_in_flight_run_bypasses_an_unrelated_limit_even_when_over(client, core_headers):
    """Core org is already at its max_entities cap (from the tests above).
    An approved-but-unpaid PayrollRun for that org must still let a new
    legal-entity request through — is_run_in_flight takes priority over
    every entitlement/scope-limit check, exactly as documented in
    entitlements.py, and this precedence must not regress."""
    run = PayrollRun(
        organization_id=_core_org.id,
        period_label="In-flight test period",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        pay_date=date(2026, 2, 1),
        status=PayrollStatus.APPROVED.value,
    )
    _db.add(run)
    _db.commit()

    try:
        r = client.post("/api/organizations/me/legal-entities", headers=core_headers, json={"name": "Mid-Run Entity"})
        assert r.status_code == 200, r.text
    finally:
        _db.delete(run)
        _db.commit()

    # With the in-flight run cleared, the same request must go back to
    # being blocked — the bypass is scoped to "while a run is in flight",
    # not a permanent unlock.
    r = client.post("/api/organizations/me/legal-entities", headers=core_headers, json={"name": "Mid-Run Entity 2"})
    assert r.status_code == 403, r.text


# ── BILLING_ENFORCEMENT_MODE regression safety ("off" / "warn") ────────────

def test_enforcement_mode_off_and_warn_are_regression_safe(client, core_headers):
    """Confirms the rollout switch itself: "off" behaves exactly like
    before these dependencies were wired into any route (no behavior
    change), and "warn" runs the real check but only audits — it never
    raises. Both are read at call time from `settings`, so this test can
    flip them without re-importing the app."""
    audit_count_before = _db.query(BillingCommercialAuditEvent).filter(
        BillingCommercialAuditEvent.event_type == "ENTITLEMENT_WOULD_HAVE_BLOCKED"
    ).count()

    settings.BILLING_ENFORCEMENT_MODE = "off"
    try:
        r = client.post("/api/organizations/me/legal-entities", headers=core_headers, json={"name": "Off Mode Entity"})
        assert r.status_code == 200, r.text
    finally:
        settings.BILLING_ENFORCEMENT_MODE = "enforce"

    settings.BILLING_ENFORCEMENT_MODE = "warn"
    try:
        r = client.post("/api/organizations/me/legal-entities", headers=core_headers, json={"name": "Warn Mode Entity"})
        assert r.status_code == 200, r.text
    finally:
        settings.BILLING_ENFORCEMENT_MODE = "enforce"

    audit_count_after = _db.query(BillingCommercialAuditEvent).filter(
        BillingCommercialAuditEvent.event_type == "ENTITLEMENT_WOULD_HAVE_BLOCKED"
    ).count()
    assert audit_count_after > audit_count_before, "warn mode must audit the would-be block"


# ── Plan-version migration (Part 1) ─────────────────────────────────────────

def test_migration_moves_subscriptions_and_matches_target_flags():
    """Standalone check of migrate_plan_versions_v2's actual behavior,
    against a fresh pair of "old-shaped" plan versions seeded in this same
    hermetic DB — independent of the real dev-DB migration already run
    manually (see scripts/migrate_plan_versions_v2.py's own idempotent
    re-run check)."""
    from scripts import migrate_plan_versions_v2 as migration

    old_professional_flags = {PAYROLL_RUNS: None, MULTI_ENTITY: None, MULTI_CURRENCY: None, API_ACCESS: None, MAX_ENTITIES: 1}
    old_version = _publish_plan("PROFESSIONAL_MIGTEST", "Professional (old shape)", old_professional_flags)

    org = Organization(organization_name="Migration Test Co", organization_code="MIGTEST", workspace_type="PRODUCTION")
    _db.add(org)
    _db.flush()
    sub = BillingSubscription(
        organization_id=org.id,
        plan_version_id=old_version.id,
        billing_authority=BillingAuthority.STANDALONE.value,
        status=SubscriptionStatus.ACTIVE.value,
        current_period_start=datetime.utcnow() - timedelta(days=5),
        current_period_end=datetime.utcnow() + timedelta(days=25),
    )
    _db.add(sub)
    _db.commit()

    migration.TARGET_FLAGS["PROFESSIONAL_MIGTEST"] = migration.TARGET_FLAGS["PROFESSIONAL"]
    migration._migrate_plan(_db, "PROFESSIONAL_MIGTEST", _super.id)

    _db.refresh(sub)
    _db.refresh(old_version)
    assert old_version.status == "RETIRED"
    assert sub.plan_version_id != old_version.id

    new_flags = plan_catalog.list_entitlement_flags(_db, sub.plan_version_id)
    assert new_flags == migration.TARGET_FLAGS["PROFESSIONAL"]

    migrated_event = (
        _db.query(BillingCommercialAuditEvent)
        .filter(
            BillingCommercialAuditEvent.organization_id == org.id,
            BillingCommercialAuditEvent.event_type == "PLAN_VERSION_MIGRATED",
        )
        .first()
    )
    assert migrated_event is not None
    assert migrated_event.payload["old_plan_version_id"] == old_version.id
    assert migrated_event.payload["new_plan_version_id"] == sub.plan_version_id
