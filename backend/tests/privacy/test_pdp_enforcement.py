"""
tests/privacy/test_pdp_enforcement.py
-------------------------------------
ZP-PRIV A04: the PDP is wired in front of every route and fails closed.

These run against the real app (install_route_policies already ran at import)
with the auth dependency overridden to a concrete principal, so they exercise
the actual dependency ordering: the injected policy dependency sits at index 0,
before the router-level gates and the endpoint's own gate.

Denial contract checked here:
  * 403 for "role/action not permitted", 404 for "object outside scope";
  * the body never carries the reason code (audit-only), only trace.decisionId;
  * every denial writes an append-only authz_decision_events row.
"""

from __future__ import annotations

import pytest

# A worker-class GET route reachable by tenant operators (not super_admin).
WORKER_PATH = "/api/payroll/employees/{employee_id}"
WORKER_URL = "/api/payroll/employees/987654"
# A platform-class GET route that only super_admin may use.
PLATFORM_URL = "/api/organizations/"


def _user(db, role, organization_id=None):
    from app.core.security import hash_password
    from app.modules.auth.models import User, UserRole

    user = User(
        email=f"{role}-{organization_id}@example.com",
        hashed_password=hash_password("a-strong-password-1"),
        role=getattr(UserRole, role.upper()),
        organization_id=organization_id,
        first_name="Test",
        last_name="User",
        phone="",
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def client(db):
    from fastapi.testclient import TestClient

    from app.core.dependencies import (
        get_current_org_scoped_principal,
        get_current_user,
    )
    from app.database import get_db
    from app.main import app

    holder = {"principal": None}
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_org_scoped_principal] = lambda: holder["principal"]
    app.dependency_overrides[get_current_user] = lambda: holder["principal"]
    test_client = TestClient(app)
    test_client.holder = holder
    try:
        yield test_client
    finally:
        app.dependency_overrides.clear()


def _denials(db):
    from app.modules.auth.models import AuthzDecisionEvent

    return db.query(AuthzDecisionEvent).all()


def test_worker_route_is_registered_for_tenant_operators():
    """Guard the fixture route against registry drift."""
    from app.core.authz.policy import load_registry

    policy = load_registry()[("GET", WORKER_PATH)]
    assert policy.data_class == "worker"
    assert "org_admin" in policy.principals
    assert "super_admin" not in policy.principals


def test_pdp_allows_a_self_route_for_a_normal_user(client, db, organization):
    client.holder["principal"] = _user(db, "org_admin", organization.id)
    response = client.get("/api/auth/me")
    assert response.status_code == 200, response.text
    assert response.json()["email"].startswith("org_admin")


def test_pdp_denies_super_admin_on_a_worker_route(client, db, organization):
    client.holder["principal"] = _user(db, "super_admin", None)
    response = client.get(WORKER_URL)
    assert response.status_code == 403, response.text
    body = response.json()
    assert body["error"] == "ACCESS_DENIED"
    assert body["trace"]["decisionId"]
    assert "ROLE_NOT_PERMITTED" not in response.text

    rows = _denials(db)
    assert len(rows) == 1
    assert rows[0].reason_code == "ROLE_NOT_PERMITTED"
    assert rows[0].principal_role == "super_admin"
    assert rows[0].status_code == 403


def test_pdp_denies_org_admin_on_a_platform_route(client, db, organization):
    client.holder["principal"] = _user(db, "org_admin", organization.id)
    response = client.get(PLATFORM_URL)
    assert response.status_code == 403, response.text
    assert _denials(db)[0].reason_code == "ROLE_NOT_PERMITTED"


def test_pdp_object_out_of_scope_is_404_and_indistinguishable(client, db, organization):
    client.holder["principal"] = _user(db, "org_admin", organization.id)
    response = client.get(WORKER_URL)  # no such employee in any org
    assert response.status_code == 404, response.text
    body = response.json()
    assert body["error"] == "NOT_FOUND"
    assert body["message"] == "Resource not found."
    assert "ACCESS_DENIED_OUT_OF_SCOPE" not in response.text
    assert _denials(db)[0].reason_code == "ACCESS_DENIED_OUT_OF_SCOPE"
    assert _denials(db)[0].status_code == 404


def test_pdp_crash_denies_and_is_audited(client, db, organization, monkeypatch):
    from app.core.authz import policy as P

    def boom(*args, **kwargs):
        raise RuntimeError("injected PDP failure")

    monkeypatch.setattr(P, "_evaluate", boom)
    client.holder["principal"] = _user(db, "org_admin", organization.id)
    response = client.get(WORKER_URL)
    assert response.status_code == 403, response.text
    assert _denials(db)[0].reason_code == "PDP_ERROR"


def test_public_route_needs_no_principal(client):
    response = client.get("/api/billing/plans")
    assert response.status_code not in (401, 403), response.text
