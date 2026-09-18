"""
tests/test_step4_dunning_safety.py
--------------------------------------
Step 4 — Wire BillingDunningState, protect in-flight authorized runs
(closes blocker #17, "the safety-critical one").

  1. THE critical test this whole step is built around: an org at dunning
     stage READ_ONLY with one AUTHORIZED run whose pay_date is in the
     future — that run must still be completable, while creating a NEW
     run for that org must be blocked. Get this wrong and a real employee
     doesn't get paid over a billing dispute.
  2. run_dunning_sweep() must not advance an org's stage past
     RESTRICT_EXPANSION while has_in_flight_authorized_run() is True — it
     freezes at the current stage and sets in_flight_run_guard=True
     instead, auditing the pause.
  3. Once no run is in flight, the very same sweep call advances normally.
  4. GET /billing/dunning-status — the tenant-facing banner payload.
  5. GET /super-admin/billing/subscriptions — dunning_stage /
     dunning_in_flight_run_guard fields and the dunning_stage filter.

Hermetic SQLite pattern, same as test_commercial_billing_standard.py.
"""

import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="step4_dunning_test_")
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
os.environ["BILLING_ENFORCEMENT_MODE"] = "off"

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
from app.modules.billing.dunning import run_dunning_sweep  # noqa: E402
from app.modules.billing.entitlements import has_in_flight_authorized_run  # noqa: E402
from app.modules.billing.models import (  # noqa: E402
    BillingAuthority, BillingCommercialAuditEvent, BillingDunningState, BillingSubscription, DunningStage, SubscriptionStatus,
)
from app.modules.organizations.models import Organization  # noqa: E402
from app.modules.payroll.models import PayrollRun, PayrollStatus  # noqa: E402

from sqlalchemy.engine import make_url as _make_url  # noqa: E402

assert _make_url(engine.url).get_backend_name() == "sqlite", (
    f"test_step4_dunning_safety must run on its own sqlite DB, got {engine.url}"
)

Base.metadata.create_all(bind=engine)
initialize_database()

_db = SessionLocal()

_super = User(
    email="step4-super-admin@example.com",
    hashed_password=hash_password("strong-password"),
    role=UserRole.SUPER_ADMIN,
    first_name="Super", last_name="Admin",
    organization_id=None, is_active=True,
)
_db.add(_super)
_db.flush()

_plan = plan_catalog.create_plan(_db, "PROFESSIONAL", "Professional", actor_user_id=_super.id)
_version = plan_catalog.create_plan_version(
    _db, plan_id=_plan.id, feature_set={"features": ["payroll_runs"]}, scale_limits={}, actor_user_id=_super.id,
)
plan_catalog.approve_plan_version(_db, _version.id, actor_user_id=_super.id)
plan_catalog.publish_plan_version(_db, _version.id, published_by_user_id=_super.id)


def _make_org_with_sub(code: str, status: str = SubscriptionStatus.PAST_DUE.value) -> Organization:
    org = Organization(
        organization_name=f"{code} Co", organization_code=code,
        workspace_type="PRODUCTION", billing_classification="COMMERCIAL_ACTIVE", charge_enabled=True,
    )
    _db.add(org)
    _db.flush()
    _db.add(User(
        email=f"{code.lower()}@example.com", hashed_password=hash_password("strong-password"),
        role=UserRole.ORG_ADMIN, first_name="Org", last_name="Admin",
        organization_id=org.id, is_active=True,
    ))
    _db.add(BillingSubscription(
        organization_id=org.id, plan_version_id=_version.id,
        billing_authority=BillingAuthority.STANDALONE.value, status=status,
        current_period_start=datetime.utcnow() - timedelta(days=30),
        current_period_end=datetime.utcnow() - timedelta(days=10),
    ))
    _db.flush()
    return org


# ── Org 1 — THE critical scenario: READ_ONLY + one in-flight AUTHORIZED run ──
_readonly_org = _make_org_with_sub("STEP4READONLY")
_db.add(BillingDunningState(
    organization_id=_readonly_org.id, stage=DunningStage.READ_ONLY.value,
    entered_at=datetime.utcnow() - timedelta(days=25), in_flight_run_guard=False,
))
_readonly_run = PayrollRun(
    organization_id=_readonly_org.id,
    period_label="In-flight authorized run",
    period_start=date.today() - timedelta(days=5),
    period_end=date.today(),
    pay_date=date.today() + timedelta(days=3),
    status=PayrollStatus.AUTHORIZED.value,
)
_db.add(_readonly_run)

# ── Org 2 — sweep must PAUSE advancement while a run is genuinely in flight ──
_paused_org = _make_org_with_sub("STEP4PAUSED")
_db.add(BillingDunningState(
    organization_id=_paused_org.id, stage=DunningStage.RESTRICT_EXPANSION.value,
    entered_at=datetime.utcnow() - timedelta(days=10),  # -> would target RESTRICT_NEW_RUN
))
_paused_run = PayrollRun(
    organization_id=_paused_org.id,
    period_label="In-flight authorized run",
    period_start=date.today() - timedelta(days=5),
    period_end=date.today(),
    pay_date=date.today() + timedelta(days=3),
    status=PayrollStatus.AUTHORIZED.value,
)
_db.add(_paused_run)

# ── Org 3 — control: same elapsed time, no in-flight run -> sweep DOES advance ──
_advance_org = _make_org_with_sub("STEP4ADVANCE")
_db.add(BillingDunningState(
    organization_id=_advance_org.id, stage=DunningStage.RESTRICT_EXPANSION.value,
    entered_at=datetime.utcnow() - timedelta(days=10),
))

# ── Org 4 — no dunning row at all, for the dunning-status endpoint's null case ──
_clean_org = _make_org_with_sub("STEP4CLEAN", status=SubscriptionStatus.ACTIVE.value)

_db.commit()

for _mod in list(sys.modules):
    if _mod == "app" or _mod.startswith("app."):
        del sys.modules[_mod]
sys.modules.update(_saved_app_modules)
del _saved_app_modules


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _headers(client, email):
    login = client.post("/api/auth/login", json={"email": email, "password": "strong-password"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture(scope="module")
def readonly_headers(client):
    return _headers(client, "step4readonly@example.com")


@pytest.fixture(scope="module")
def super_admin_headers(client):
    return _headers(client, "step4-super-admin@example.com")


# ── THE critical test ────────────────────────────────────────────────────

def test_readonly_org_can_still_complete_its_in_flight_authorized_run(client, readonly_headers):
    assert has_in_flight_authorized_run(_db, _readonly_org.id) is True

    r = client.put(f"/api/payroll/runs/{_readonly_run.id}/approve", headers=readonly_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == PayrollStatus.PAID.value


def test_readonly_org_cannot_create_a_new_run(client, readonly_headers):
    r = client.post(
        "/api/payroll/runs",
        headers=readonly_headers,
        json={"periodLabel": "New run attempt", "periodStart": "2026-01-01", "periodEnd": "2026-01-31", "payDate": "2026-02-01"},
    )
    assert r.status_code == 403, r.text
    assert "restricted" in r.text.lower()


# ── Sweep pause / resume behavior ───────────────────────────────────────

def test_sweep_pauses_advancement_while_run_is_in_flight():
    """One sweep call scans every PAST_DUE org together, so this same call
    also covers the no-run control case (_advance_org) below — asserted
    together since they're necessarily the same run_dunning_sweep() call."""
    result = run_dunning_sweep(_db)
    assert _paused_org.id in result["scanned"]
    assert not any(a["organization_id"] == _paused_org.id for a in result["advanced"])

    state = _db.query(BillingDunningState).filter(BillingDunningState.organization_id == _paused_org.id).first()
    assert state.stage == DunningStage.RESTRICT_EXPANSION.value, "must not advance past RESTRICT_EXPANSION while a run is in flight"
    assert state.in_flight_run_guard is True

    audit = (
        _db.query(BillingCommercialAuditEvent)
        .filter(
            BillingCommercialAuditEvent.organization_id == _paused_org.id,
            BillingCommercialAuditEvent.event_type == "DUNNING_STAGE_ADVANCE_PAUSED_IN_FLIGHT_RUN",
        )
        .first()
    )
    assert audit is not None, "the pause must be audited, not silently dropped"

    # Control: same elapsed time, no in-flight run -> this same sweep call
    # advances it normally, proving the freeze above is guard-specific.
    assert any(a["organization_id"] == _advance_org.id and a["stage"] == DunningStage.RESTRICT_NEW_RUN.value for a in result["advanced"])
    advance_state = _db.query(BillingDunningState).filter(BillingDunningState.organization_id == _advance_org.id).first()
    assert advance_state.stage == DunningStage.RESTRICT_NEW_RUN.value
    assert advance_state.in_flight_run_guard is False


def test_sweep_resumes_advancing_once_the_in_flight_run_clears():
    """The freeze lifts the moment the guard condition clears — not stuck forever."""
    _paused_run.status = PayrollStatus.PAID.value
    _paused_run.pay_date = date.today() - timedelta(days=1)
    _db.add(_paused_run)
    _db.commit()

    assert has_in_flight_authorized_run(_db, _paused_org.id) is False

    result = run_dunning_sweep(_db)
    assert any(a["organization_id"] == _paused_org.id and a["stage"] == DunningStage.RESTRICT_NEW_RUN.value for a in result["advanced"])

    state = _db.query(BillingDunningState).filter(BillingDunningState.organization_id == _paused_org.id).first()
    assert state.stage == DunningStage.RESTRICT_NEW_RUN.value
    assert state.in_flight_run_guard is False


# ── GET /billing/dunning-status ─────────────────────────────────────────

def test_dunning_status_returns_null_when_no_dunning_row(client):
    headers = _headers(client, "step4clean@example.com")
    r = client.get("/api/billing/dunning-status", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() is None


def test_dunning_status_returns_stage_for_readonly_org(client, readonly_headers):
    r = client.get("/api/billing/dunning-status", headers=readonly_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stage"] == DunningStage.READ_ONLY.value


# ── GET /super-admin/billing/subscriptions ──────────────────────────────

def test_super_admin_subscriptions_list_includes_dunning_fields(client, super_admin_headers):
    r = client.get("/api/super-admin/billing/subscriptions", headers=super_admin_headers)
    assert r.status_code == 200, r.text
    rows = {row["organization_id"]: row for row in r.json()["subscriptions"]}

    assert rows[_readonly_org.id]["dunning_stage"] == DunningStage.READ_ONLY.value
    assert rows[_clean_org.id]["dunning_stage"] is None


def test_super_admin_subscriptions_dunning_stage_filter(client, super_admin_headers):
    r = client.get(
        "/api/super-admin/billing/subscriptions",
        headers=super_admin_headers,
        params={"dunning_stage": DunningStage.READ_ONLY.value},
    )
    assert r.status_code == 200, r.text
    org_ids = {row["organization_id"] for row in r.json()["subscriptions"]}
    assert _readonly_org.id in org_ids
    assert _clean_org.id not in org_ids
