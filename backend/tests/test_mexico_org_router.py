"""Mexico Phase 3 organisation API (/api/payroll/mexico) over HTTP — own-
organisation scoping, tenant isolation, role gates, required `on`, and the
read-only Super Admin employer routes. In-memory SQLite; SYNTHETIC data."""

import pytest

from tests._mx_employer_helpers import (
    GCP_REF, ORG_BASE, SA_BASE, SUPER_ADMIN, employer_payload, enable_mx_onboarding, http, make_org, new_employer,
    principal,
)


@pytest.fixture(autouse=True)
def _mx_onboarding(monkeypatch):
    """These tests exercise the Phase 3 API itself; dormancy is test_mexico_dormancy.py's job."""
    enable_mx_onboarding(monkeypatch)


def _create(c, **over):
    r = c.post(f"{ORG_BASE}/employers", json=employer_payload(**over))
    assert r.status_code == 200, r.text
    return r.json()


def test_super_admin_and_employee_cannot_use_org_routes(db):
    with http(db, SUPER_ADMIN) as c:
        assert c.get(f"{ORG_BASE}/employers").status_code == 403
    t = make_org(db)
    with http(db, principal(t.org.id, role="employee")) as c:
        assert c.get(f"{ORG_BASE}/employers").status_code == 403


def test_operator_reads_admin_writes(db):
    t = make_org(db)
    with http(db, principal(t.org.id)) as c:
        emp = _create(c)
    with http(db, principal(t.org.id, user_id=702, role="payroll_admin")) as c:
        assert c.get(f"{ORG_BASE}/employers").status_code == 200
        assert c.get(f"{ORG_BASE}/employers/{emp['id']}").status_code == 200
        assert c.post(f"{ORG_BASE}/employers", json=employer_payload(rfc="XYZ010101AB1")).status_code == 403
        assert c.post(f"{ORG_BASE}/employers/{emp['id']}/imss-registrations", json={
            "registroPatronal": "Y1234567101", "riskClass": "I", "fraction": "1",
            "effectiveFrom": "2026-01-01"}).status_code == 403


def test_tenant_isolation(db):
    a, b = make_org(db), make_org(db, name="Other", code="OTHER")
    with http(db, principal(a.org.id)) as c:
        emp = _create(c)
        reg = c.post(f"{ORG_BASE}/employers/{emp['id']}/imss-registrations", json={
            "registroPatronal": "Y1234567101", "riskClass": "I", "fraction": "1", "effectiveFrom": "2026-01-01"}).json()
        cred = c.post(f"{ORG_BASE}/employers/{emp['id']}/credentials", json={"kind": "CSD", "secretRef": GCP_REF}).json()
    with http(db, principal(b.org.id, user_id=801)) as c:
        assert c.get(f"{ORG_BASE}/employers").json() == []
        assert c.get(f"{ORG_BASE}/employers/{emp['id']}").status_code == 404
        assert c.post(f"{ORG_BASE}/employers/{emp['id']}/versions",
                      json=employer_payload(effectiveFrom="2026-07-01")).status_code == 404
        assert c.post(f"{ORG_BASE}/imss-registrations/{reg['id']}/risk-premiums", json={
            "determinationYear": 2025, "premiumRatePct": "1", "periodFrom": "2026-03-01",
            "periodTo": "2027-02-28"}).status_code == 404
        assert c.put(f"{ORG_BASE}/credentials/{cred['id']}/revoke").status_code == 404
        assert c.get(f"{ORG_BASE}/readiness", params={"on": "2026-03-01"}).json()["employers"] == []


def test_readiness_requires_on(db):
    t = make_org(db)
    with http(db, principal(t.org.id)) as c:
        _create(c)
        assert c.get(f"{ORG_BASE}/readiness").status_code == 422
        body = c.get(f"{ORG_BASE}/readiness", params={"on": "2026-03-01"}).json()
        assert body["on"] == "2026-03-01" and body["employers"][0]["liveEligible"] is False
        assert {g["gate"] for g in body["gates"]} == {f"G{i}" for i in range(1, 9)}


def test_unknown_fields_are_refused_and_never_echoed_on_the_credential_route(db):
    from app.modules.payroll.models import PayrollMxCredentialRef

    t = make_org(db)
    with http(db, principal(t.org.id)) as c:
        emp = _create(c)
        url = f"{ORG_BASE}/employers/{emp['id']}/credentials"
        for body in ({"kind": "PAC", "secretRef": GCP_REF, "password": "should-never-be-accepted"},
                     {"kind": "PAC", "secretRef": {"privateKey": "should-never-be-accepted"}},
                     {"kind": "PAC", "secretRef": "-----BEGIN PRIVATE KEY-----should-never-be-accepted"}):
            r = c.post(url, json=body)
            assert r.status_code == 400 and "should-never-be-accepted" not in r.text, r.text
        assert "password: extra_forbidden" in c.post(url, json={"kind": "PAC", "secretRef": GCP_REF,
                                                                "password": "x"}).json()["message"]
    assert db.query(PayrollMxCredentialRef).count() == 0


def test_super_admin_employer_routes_are_read_only_and_masked(db):
    t = make_org(db)
    with http(db, principal(t.org.id)) as c:
        emp = _create(c)
    with http(db, SUPER_ADMIN) as c:
        listed = c.get(f"{SA_BASE}/employers", params={"organization_id": t.org.id}).json()
        assert listed[0]["rfc"].endswith("AB1") and "ABC010101" not in listed[0]["rfc"]
        detail = c.get(f"{SA_BASE}/employers/{emp['id']}", params={"organization_id": t.org.id}).json()
        assert detail["versions"][0]["rfc"] != "ABC010101AB1"
        assert c.get(f"{SA_BASE}/employer-readiness", params={"organization_id": t.org.id}).status_code == 422
        ready = c.get(f"{SA_BASE}/employer-readiness", params={"organization_id": t.org.id, "on": "2026-03-01"})
        assert ready.status_code == 200 and ready.json()["employers"][0]["liveEligible"] is False
        assert c.get(f"{SA_BASE}/employer-readiness/summary", params={"on": "2026-03-01"}).status_code == 200
        assert c.get(f"{SA_BASE}/employers", params={"organization_id": 99999}).status_code == 404
        sa_paths = {r.path for r in __import__("app.main", fromlist=["app"]).app.routes
                    if getattr(r, "path", "").startswith(SA_BASE + "/employer")}
        for path in sa_paths:
            methods = {m for r in __import__("app.main", fromlist=["app"]).app.routes
                       if getattr(r, "path", "") == path for m in r.methods}
            assert methods <= {"GET", "HEAD"}, path
    with http(db, principal(t.org.id)) as c:
        assert c.get(f"{SA_BASE}/employers", params={"organization_id": t.org.id}).status_code == 403


def test_super_admin_org_picker_lists_orgs_with_a_mexico_employer_or_jurisdiction(db):
    with_employer = make_org(db, country=None)                       # employer row, no MX jurisdiction
    by_jurisdiction = make_org(db, name="Jur", code="JUR")             # MX jurisdiction, no employer
    make_org(db, name="NL org", code="NLORG", country="NL")            # unrelated
    new_employer(db, with_employer.org.id)
    with http(db, SUPER_ADMIN) as c:
        ids = {o["id"] for o in c.get(f"{SA_BASE}/organizations").json()}
    assert ids == {with_employer.org.id, by_jurisdiction.org.id}


@pytest.mark.parametrize("path", ["/employers", "/readiness?on=2026-03-01", "/collective-agreements"])
def test_reads_respond_for_an_org_with_no_employer(db, path):
    t = make_org(db)
    with http(db, principal(t.org.id)) as c:
        assert c.get(f"{ORG_BASE}{path}").status_code == 200
