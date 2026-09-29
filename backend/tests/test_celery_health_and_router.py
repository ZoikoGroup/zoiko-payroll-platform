"""
tests/test_celery_health_and_router.py
--------------------------------------
Test suite for Phase 2.1:
- GET /api/health/celery health probe contract
- POST /api/payroll/runs/{run_id}/generate-payslips synchronous & asynchronous chord dispatch
- Validation error on non-DRAFT runs
"""

from datetime import date
from decimal import Decimal
import pytest
from starlette.testclient import TestClient

from app.config import settings
from app.core.security import create_access_token
from app.core.celery_app import celery_app
from app.main import app
from app.modules.payroll import service
from app.modules.payroll.models import (
    ContributionRate,
    EmployeeStatus,
    PayrollEmployee,
    PayrollRun,
    PayrollStatus,
    TaxSlab,
)
from app.modules.auth.models import User, UserRole

client = TestClient(app)


@pytest.fixture(autouse=True)
def _test_db_for_requests(db):
    """Route the app's own get_db to the test session.

    Without this, every request below goes through app.database, which is
    the real configured Postgres — not the in-memory test DB the fixtures
    seed — so auth would look users up (and payslip generation would write)
    against a live database.
    """
    from app.database import get_db

    app.dependency_overrides[get_db] = lambda: db
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def _sqlite_advisory_lock(db):
    """code_generation.py takes `pg_advisory_xact_lock` (Postgres-only) when
    numbering payslips; register a no-op of the same name on the in-memory
    SQLite connection, as test_bulk_employees.py does."""
    db.connection().connection.dbapi_connection.create_function("pg_advisory_xact_lock", 1, lambda key: 1)
    yield


def _token_for(user):
    return create_access_token({
        "sub": user.email, "role": user.role if isinstance(user.role, str) else user.role.value,
        "user_id": user.id, "organization_id": user.organization_id,
    })


@pytest.fixture(autouse=True)
def _eager_celery(db, monkeypatch):
    """Run Celery tasks locally against an in-memory result backend."""
    from app.tasks import payroll_tasks
    monkeypatch.setitem(celery_app.conf, "result_backend", "cache+memory://")
    monkeypatch.setitem(celery_app.conf, "task_always_eager", True)
    monkeypatch.setitem(celery_app.conf, "task_eager_propagates", True)
    monkeypatch.setattr(payroll_tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    yield


@pytest.fixture()
def seeded_run(db, organization):
    """Seed an organization, operator user, active employee, and draft run."""
    org_id = organization.id
    # A production workspace needs a billing subscription to pass the
    # router's commercial-relationship gate; an evaluation workspace does
    # not. Billing is not what these tests are about.
    organization.workspace_type = "EVALUATION"

    # Create operator user
    user = User(
        email="operator@zoiko.test",
        first_name="Test",
        last_name="Operator",
        hashed_password="pw",
        organization_id=org_id,
        role=UserRole.PAYROLL_ADMIN.value,
        is_active=True,
    )
    emp = PayrollEmployee(
        organization_id=org_id,
        employee_code="EMP101",
        name="John Doe",
        country_code="US",
        work_state="CA",
        status=EmployeeStatus.ACTIVE.value,
        ctc=Decimal("120000"),
    )
    run = PayrollRun(
        organization_id=org_id,
        period_label="Test Run",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        pay_date=date(2026, 2, 1),
        status=PayrollStatus.DRAFT.value,
    )
    db.add_all([user, emp, run])
    db.commit()
    db.refresh(user)
    db.refresh(emp)
    db.refresh(run)

    return {"user": user, "emp": emp, "run": run, "org_id": org_id}


def test_celery_health_unconfigured(monkeypatch):
    """When REDIS_URL is empty, /api/health/celery reports unconfigured."""
    monkeypatch.setattr(settings, "REDIS_URL", "")

    resp = client.get("/api/health/celery")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "unconfigured"
    assert "Celery disabled" in data["message"]
    assert data["broker"] == "unconfigured"
    assert data["worker_count"] == 0


def test_celery_health_healthy(monkeypatch):
    """When Redis is reachable and worker ping responds, health reports healthy."""
    monkeypatch.setattr(settings, "REDIS_URL", "redis://localhost:6379/0")

    class FakeClient:
        def ping(self):
            return True

    monkeypatch.setattr("app.core.cache.get_redis_client", lambda: FakeClient())

    class FakeInspect:
        def ping(self):
            return {"worker1@zoiko": {"ok": "pong"}}

    monkeypatch.setattr(celery_app.control, "inspect", lambda timeout=1.0: FakeInspect())

    resp = client.get("/api/health/celery")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["broker"] == "connected"
    assert "worker1@zoiko" in data["workers"]
    assert data["worker_count"] == 1


def test_celery_health_degraded_when_no_workers(monkeypatch):
    """When Redis is reachable but no workers are active, status is degraded."""
    monkeypatch.setattr(settings, "REDIS_URL", "redis://localhost:6379/0")

    class FakeClient:
        def ping(self):
            return True

    monkeypatch.setattr("app.core.cache.get_redis_client", lambda: FakeClient())

    class FakeInspect:
        def ping(self):
            return {}

    monkeypatch.setattr(celery_app.control, "inspect", lambda timeout=1.0: FakeInspect())

    resp = client.get("/api/health/celery")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["broker"] == "connected"
    assert data["worker_count"] == 0


def test_generate_payslips_synchronous(db, seeded_run):
    """POST /runs/{run_id}/generate-payslips executes synchronously by default."""
    token = _token_for(seeded_run["user"])
    run_id = seeded_run["run"].id

    resp = client.post(
        f"/api/payroll/runs/{run_id}/generate-payslips",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == run_id
    assert data["status"] == "Draft"
    assert data["employees"] == 1  # PayrollRunResponse serializes employee_count as "employees"


def test_generate_payslips_async_queued(monkeypatch, db, seeded_run):
    """POST /runs/{run_id}/generate-payslips?async_dispatch=true queues Celery task."""
    monkeypatch.setattr(settings, "REDIS_URL", "redis://localhost:6379/0")
    token = _token_for(seeded_run["user"])
    run_id = seeded_run["run"].id

    resp = client.post(
        f"/api/payroll/runs/{run_id}/generate-payslips?async_dispatch=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["runId"] == run_id
    assert data["status"] == "QUEUED"
    assert "taskId" in data


def test_generate_payslips_rejects_non_draft_run(db, seeded_run):
    """POST /runs/{run_id}/generate-payslips returns 400 if run is not DRAFT."""
    run = seeded_run["run"]
    run.status = PayrollStatus.APPROVED.value
    db.commit()

    token = _token_for(seeded_run["user"])

    resp = client.post(
        f"/api/payroll/runs/{run.id}/generate-payslips",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert "DRAFT" in resp.json()["detail"]
