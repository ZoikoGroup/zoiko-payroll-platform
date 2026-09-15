"""
tests/test_trial_lifecycle.py
-------------------------------
Integration tests for the Prompt 5 trial lifecycle:

  1. Expired TRIALING sub (current_period_end in the past, grace NULL) →
     sweep stamps grace_period_ends_at and the org's WRITE endpoints turn
     403 while GET endpoints stay 200 (require_writeable_workspace).
  2. Past grace_period_ends_at → sweep sets Organization.is_active=False
     (CLOSED) and idempotently does NOT re-audit on a second run.
  3. A trial sweep NEVER creates a BillingInvoice row — invoicing stays a
     separate, opt-in step.
  4. Convert-trial is the only TRIALING→ACTIVE path: workspace_type becomes
     PRODUCTION, subscription pinned to the paid plan version, TRIAL_CONVERTED
     audited, no invoice.

Mirrors test_assist.py's hermetic pattern: env vars set BEFORE importing
app.main, SQLite throwaway DB on disk so the global engine + TestClient
lifespan and this file's own SessionLocal share one database.
"""

import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="trial_lifecycle_test_")
os.environ["PAYROLL_DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP, 'test.sqlite3')}"
os.environ["ENVIRONMENT"] = "development"
os.environ["ASSIST_MODEL_PROVIDER"] = ""
os.environ["ASSIST_MODEL_BASE_URL"] = ""
os.environ["ASSIST_MODEL_API_KEY"] = ""
os.environ["SMTP_HOST"] = ""
os.environ["SMTP_FROM_EMAIL"] = ""
os.environ["ASSIST_SUPPORT_EMAIL"] = ""
# No background threads during tests — lifespan starts both sweep schedulers.
os.environ["ASSIST_SWEEP_ENABLED"] = "false"
os.environ["TRIAL_SWEEP_ENABLED"] = "false"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.database import Base, SessionLocal, engine, initialize_database  # noqa: E402
from app.modules.auth.models import User, UserRole  # noqa: E402
from app.modules.billing import plan_catalog  # noqa: E402
from app.modules.billing.models import (  # noqa: E402
    BillingAuthority,
    BillingCommercialAuditEvent,
    BillingInvoice,
    BillingSubscription,
    SubscriptionStatus,
)
from app.modules.organizations.models import Organization  # noqa: E402

Base.metadata.create_all(bind=engine)
initialize_database()

_db = SessionLocal()

# ── Seed: super admin (audits/converts), plan versions, two trial orgs ────

_super = User(
    email="trial-super-admin@example.com",
    hashed_password=hash_password("strong-password"),
    role=UserRole.SUPER_ADMIN,
    first_name="Super",
    last_name="Admin",
    organization_id=None,
    is_active=True,
)
_db.add(_super)
_db.flush()

_plan = plan_catalog.create_plan(db=_db, code="PROFESSIONAL", name="Professional", actor_user_id=_super.id)
_version = plan_catalog.create_plan_version(
    db=_db,
    plan_id=_plan.id,
    feature_set={"features": ["payroll_runs", "multi_entity"]},
    scale_limits={"max_entities": 1},
    actor_user_id=_super.id,
)
plan_catalog.approve_plan_version(_db, _version.id, actor_user_id=_super.id)
plan_catalog.publish_plan_version(_db, _version.id, published_by_user_id=_super.id)
_db.refresh(_version)


def _trial_org(code, name, period_end):
    org = Organization(
        organization_name=name,
        organization_code=code,
        workspace_type="EVALUATION",
    )
    _db.add(org)
    _db.flush()
    _db.add(
        User(
            email=f"{code.lower()}@example.com",
            hashed_password=hash_password("strong-password"),
            role=UserRole.PAYROLL_ADMIN,
            first_name="Trial",
            last_name="User",
            organization_id=org.id,
            is_active=True,
        )
    )
    start = period_end - timedelta(days=30)
    _db.add(
        BillingSubscription(
            organization_id=org.id,
            plan_version_id=_version.id,
            billing_authority=BillingAuthority.STANDALONE.value,
            status=SubscriptionStatus.TRIALING.value,
            current_period_start=start,
            current_period_end=period_end,
        )
    )
    _db.flush()
    return org


_now = datetime.utcnow()
_grace_org = _trial_org("EVALGRACE", "Eval Grace", _now - timedelta(days=1))          # expired, grace not yet stamped
_db.commit()


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def super_headers(client):
    login = client.post("/api/auth/login", json={"email": "trial-super-admin@example.com", "password": "strong-password"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _org_headers(client, org):
    login = client.post(
        "/api/auth/login",
        json={"email": f"{org.organization_code.lower()}@example.com", "password": "strong-password"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _run_sweep(client, super_headers):
    return client.post("/api/super-admin/billing/trial-expiry-run", headers=super_headers)


def test_sweep_stamps_grace_and_write_guard_blocks(client, super_headers):
    before_count = _db.query(BillingInvoice).count()
    sub = _db.query(BillingSubscription).filter(BillingSubscription.organization_id == _grace_org.id).first()

    r = _run_sweep(client, super_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert _grace_org.id in body["grace_started"]

    _db.refresh(sub)
    assert sub.grace_period_ends_at is not None

    headers = _org_headers(client, _grace_org)
    write = client.post("/api/payroll/leave-requests", headers=headers, json={
        "employee_id": 1,
        "leave_type": "annual",
        "start_date": "2026-10-01",
        "end_date": "2026-10-03",
        "reason": "grace-guard check",
    })
    assert write.status_code == 403, write.text
    read = client.get("/api/payroll/employees", headers=headers)
    assert read.status_code == 200, read.text

    after_count = _db.query(BillingInvoice).count()
    assert after_count == before_count, "sweep must never create a BillingInvoice row"


def test_sweep_closes_org_past_grace_and_is_idempotent(client, super_headers):
    now = datetime.utcnow()
    org = Organization(
        organization_name="Eval Closed B",
        organization_code="EVALCLOSEDB",
        workspace_type="EVALUATION",
    )
    _db.add(org)
    _db.flush()
    _db.add(
        BillingSubscription(
            organization_id=org.id,
            plan_version_id=_version.id,
            billing_authority=BillingAuthority.STANDALONE.value,
            status=SubscriptionStatus.TRIALING.value,
            current_period_start=now - timedelta(days=40),
            current_period_end=now - timedelta(days=15),
            grace_period_ends_at=now - timedelta(days=2),
        )
    )
    _db.add(
        User(
            email="evalclosedb@example.com",
            hashed_password=hash_password("strong-password"),
            role=UserRole.PAYROLL_ADMIN,
            first_name="Trial",
            last_name="User",
            organization_id=org.id,
            is_active=True,
        )
    )
    _db.commit()
    sub = _db.query(BillingSubscription).filter(BillingSubscription.organization_id == org.id).first()
    assert org.is_active is True

    first = _run_sweep(client, super_headers)
    assert first.status_code == 200, first.text
    assert org.id in first.json()["closed"]

    _db.refresh(org)
    assert org.is_active is False
    _db.refresh(sub)
    assert sub.status == SubscriptionStatus.TRIALING.value, "sweep must never move status away from TRIALING"

    second = _run_sweep(client, super_headers)
    assert second.status_code == 200, second.text
    assert org.id not in second.json()["closed"], "CLOSED must not be re-audited on a second run"
    assert org.id not in second.json()["grace_started"]

    closed_audits = (
        _db.query(BillingCommercialAuditEvent)
        .filter(
            BillingCommercialAuditEvent.organization_id == org.id,
            BillingCommercialAuditEvent.event_type == "TRIAL_CLOSED",
        )
        .count()
    )
    assert closed_audits == 1

    # A CLOSED org's users can no longer log in at all (Organization.is_active
    # == False → login rejects it), which is the strongest form of the guard.
    # 429 = auth rate limiter across the shared suite; both prove no session.
    login = client.post("/api/auth/login", json={"email": "evalclosedb@example.com", "password": "strong-password"})
    assert login.status_code in (401, 429), login.text


def test_sweep_never_creates_any_invoice_rows(client, super_headers, _generate=_db.query(BillingInvoice).count()):
    r = _run_sweep(client, super_headers)
    assert r.status_code == 200, r.text
    assert _db.query(BillingInvoice).count() == _generate


def test_convert_trial_is_only_path_to_active(client, super_headers):
    sub = _db.query(BillingSubscription).filter(BillingSubscription.organization_id == _grace_org.id).first()
    org = _db.query(Organization).filter(Organization.id == _grace_org.id).first()

    r = client.post(
        f"/api/super-admin/billing/organizations/{_grace_org.id}/convert-trial",
        headers=super_headers,
        json={"plan_version_id": _version.id},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == SubscriptionStatus.ACTIVE.value
    assert body["plan_version_id"] == _version.id

    _db.refresh(sub)
    _db.refresh(org)
    assert sub.status == SubscriptionStatus.ACTIVE.value
    assert sub.grace_period_ends_at is None, "converted subscription must not carry a stale grace stamp"
    assert org.workspace_type == "PRODUCTION"
    assert org.is_active is True

    converted = (
        _db.query(BillingCommercialAuditEvent)
        .filter(
            BillingCommercialAuditEvent.organization_id == _grace_org.id,
            BillingCommercialAuditEvent.event_type == "TRIAL_CONVERTED",
        )
        .first()
    )
    assert converted is not None and converted.payload["plan_version_id"] == _version.id
    assert _db.query(BillingInvoice).filter(
        BillingInvoice.organization_id == _grace_org.id
    ).first() is None, "conversion must not create an invoice"


def test_convert_rejects_non_trialing_subscription(client, super_headers):
    # _grace_org is already ACTIVE from the previous test — a second
    # convert-trial must 400, not silently "convert" again.
    r = client.post(
        f"/api/super-admin/billing/organizations/{_grace_org.id}/convert-trial",
        headers=super_headers,
        json={"plan_version_id": _version.id},
    )
    assert r.status_code == 400, r.text


def test_resolve_stage_pure_derivation():
    """Unit-level sanity for the guard's stage math, mirroring what
    require_writeable_workspace consumes per request."""
    from app.modules.billing.trial_lifecycle import resolve_trial_stage

    future_end = datetime.utcnow() + timedelta(days=10)
    active_sub = BillingSubscription(
        organization_id=1,
        plan_version_id=_version.id,
        billing_authority=BillingAuthority.STANDALONE.value,
        status=SubscriptionStatus.TRIALING.value,
        current_period_start=datetime.utcnow() - timedelta(days=20),
        current_period_end=future_end,
    )
    assert resolve_trial_stage(active_sub) == "ACTIVE"

    expired_ungraced = BillingSubscription(
        organization_id=1,
        plan_version_id=_version.id,
        billing_authority=BillingAuthority.STANDALONE.value,
        status=SubscriptionStatus.TRIALING.value,
        current_period_start=datetime.utcnow() - timedelta(days=40),
        current_period_end=datetime.utcnow() - timedelta(days=1),
    )
    assert resolve_trial_stage(expired_ungraced) == "GRACE_READONLY"

    expired_ongrace = BillingSubscription(
        organization_id=1,
        plan_version_id=_version.id,
        billing_authority=BillingAuthority.STANDALONE.value,
        status=SubscriptionStatus.TRIALING.value,
        current_period_start=datetime.utcnow() - timedelta(days=40),
        current_period_end=datetime.utcnow() - timedelta(days=1),
        grace_period_ends_at=datetime.utcnow() + timedelta(days=6),
    )
    assert resolve_trial_stage(expired_ongrace) == "GRACE_READONLY"

    expired_past_grace = BillingSubscription(
        organization_id=1,
        plan_version_id=_version.id,
        billing_authority=BillingAuthority.STANDALONE.value,
        status=SubscriptionStatus.TRIALING.value,
        current_period_start=datetime.utcnow() - timedelta(days=40),
        current_period_end=datetime.utcnow() - timedelta(days=15),
        grace_period_ends_at=datetime.utcnow() - timedelta(days=2),
    )
    assert resolve_trial_stage(expired_past_grace) == "CLOSED"

    converted = BillingSubscription(
        organization_id=1,
        plan_version_id=_version.id,
        billing_authority=BillingAuthority.STANDALONE.value,
        status=SubscriptionStatus.ACTIVE.value,
        current_period_start=datetime.utcnow(),
        current_period_end=future_end,
    )
    assert resolve_trial_stage(converted) is None

    assert resolve_trial_stage(None) is None