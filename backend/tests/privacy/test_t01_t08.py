"""
tests/privacy/test_t01_t08.py
-----------------------------
ZP-PRIV-VERIFY-001 negative tests T01-T08 against the real app with real
JWTs (fixtures in tests/privacy/conftest.py). Each writes an evidence JSON
(tests/privacy/evidence/<test id>.json) via _evidence.record.
"""

from __future__ import annotations

import json

from tests.privacy._evidence import record

IDENTIFYING = ("Synthetic Worker", "A-0001", "A-0002", "B-0001", "GB00SYNTH", "SYNTHPAN", "worker.example")


def _no_identity(body) -> bool:
    text = json.dumps(body, default=str)
    return not any(token in text for token in IDENTIFYING)


def _denial_rows(db, role, route):
    from app.modules.auth.models import AuthzDecisionEvent

    return (db.query(AuthzDecisionEvent)
            .filter(AuthzDecisionEvent.principal_role == role, AuthzDecisionEvent.route_template == route)
            .all())


def _decision_id(resp):
    try:
        return (resp.json().get("trace") or {}).get("decisionId")
    except Exception:  # noqa: BLE001
        return None


# ── T01 ─────────────────────────────────────────────────────────────────────

def test_t01_super_admin_gets_registry_and_headcount_only(client, world):
    h = world.headers("SA")
    orgs = client.get("/api/super-admin/reports/organizations", headers=h)
    totals = client.get("/api/super-admin/reports/employees", headers=h)
    assert orgs.status_code == 200, orgs.text
    assert totals.status_code == 200, totals.text
    assert _no_identity(orgs.json()) and _no_identity(totals.json())
    codes = {row["organizationCode"] for row in orgs.json()["items"]}
    assert {"PRIVA", "PRIVB"} <= codes
    # Every per-tenant workforce cell here is below k=5 -> suppressed.
    for row in totals.json()["items"]:
        assert row["employeeCount"] == "<5, hidden"
        assert set(row) <= {"organizationName", "organizationCode", "jurisdictionCountry", "status",
                            "employmentType", "employeeCount"}
    record(test_id="T01", role="super_admin", scope="platform", tenant_ids=world.tenant_ids(),
           endpoint="GET /api/super-admin/reports/employees", expected_status=200,
           actual_status=totals.status_code, body=totals.json(),
           note="tenant registry + k-suppressed workforce totals; no worker identity")


# ── T02 ─────────────────────────────────────────────────────────────────────

def test_t02_super_admin_denied_employee_list_profile_and_payslips(client, world, db):
    h = world.headers("SA")
    a1 = world.employees["A1"].id
    cases = [
        ("/api/payroll/employees", "/api/payroll/employees"),
        (f"/api/payroll/employees/{a1}", "/api/payroll/employees/{employee_id}"),
        ("/api/payroll/payslips", "/api/payroll/payslips"),
        (f"/api/super-admin/compliance/netherlands/vcr?employee_id={a1}",
         "/api/super-admin/compliance/netherlands/vcr"),
    ]
    for url, template in cases:
        resp = client.get(url, headers=h)
        assert resp.status_code in (403, 404), (url, resp.status_code, resp.text)
        assert _no_identity(resp.json()), url
        assert _denial_rows(db, "super_admin", template), f"no denial audit row for {template}"
        record(test_id=f"T02{template.replace('/', '_')}", role="super_admin", scope="platform",
               tenant_ids=world.tenant_ids(), endpoint=f"GET {template}", expected_status=403,
               actual_status=resp.status_code, body=resp.json(), decision_id=_decision_id(resp),
               security_event_id=_denial_rows(db, "super_admin", template)[-1].decision_id)


# ── T03 ─────────────────────────────────────────────────────────────────────

def test_t03_super_admin_denied_salary_bank_tax_and_exports(client, world, db):
    from app.modules.payroll.models import GeneratedReport

    h = world.headers("SA")
    a1 = world.employees["A1"].id
    before = db.query(GeneratedReport).count()
    cases = [
        ("GET", f"/api/payroll/employees/{a1}/statutory-profile"),
        ("GET", "/api/payroll/runs/1/bank-transfer-file"),
        ("GET", "/api/payroll/payslips/1/download"),
        ("GET", "/api/super-admin/india/salary-tds-declarations?organizationId=%d" % world.orgs["A"].id),
        ("GET", "/api/super-admin/compliance/france/pas-rates?organizationId=%d" % world.orgs["A"].id),
    ]
    for method, url in cases:
        resp = client.request(method, url, headers=h)
        assert resp.status_code in (403, 404), (url, resp.status_code, resp.text)
        assert _no_identity(resp.json())
        record(test_id=f"T03{url.split('?')[0].replace('/', '_')}", role="super_admin", scope="platform",
               tenant_ids=world.tenant_ids(), endpoint=f"{method} {url.split('?')[0]}",
               expected_status=403, actual_status=resp.status_code, body=resp.json(),
               decision_id=_decision_id(resp))
    # The old employee CSV export now carries counts only.
    export = client.get("/api/super-admin/reports/export?type=employees", headers=h)
    assert export.status_code == 200
    assert not any(token in export.text for token in IDENTIFYING)
    assert db.query(GeneratedReport).count() == before, "no file was queued or stored"


# ── T04 ─────────────────────────────────────────────────────────────────────

def test_t04_changing_tenant_or_worker_ids_reveals_no_existence(client, world):
    h = world.headers("TA")
    other_tenant = client.get(f"/api/payroll/employees/{world.employees['B1'].id}", headers=h)
    missing = client.get("/api/payroll/employees/987654321", headers=h)
    assert other_tenant.status_code == missing.status_code == 404
    strip = lambda r: {k: v for k, v in r.json().items() if k != "trace"}  # noqa: E731
    assert strip(other_tenant) == strip(missing)
    # Naming another tenant (query string or header) never changes the tenant:
    # the request is refused with the same 404 body and audited.
    smuggled = client.get(f"/api/payroll/employees?organization_id={world.orgs['B'].id}", headers=h)
    assert smuggled.status_code == 404 and strip(smuggled) == strip(missing)
    header = client.get("/api/payroll/employees", headers={**h, "X-Organization-Id": str(world.orgs["B"].id)})
    assert header.status_code == 404
    own = client.get(f"/api/payroll/employees?organization_id={world.orgs['A'].id}", headers=h)
    assert {e["id"] for e in own.json()} == {world.employees["A1"].id, world.employees["A2"].id}
    record(test_id="T04", role="org_admin", scope="tenant:A", tenant_ids=world.tenant_ids(),
           endpoint="GET /api/payroll/employees/{employee_id}", expected_status=404,
           actual_status=other_tenant.status_code, body=strip(other_tenant),
           note="another tenant's id and a non-existent id return identical bodies")


# ── T05 ─────────────────────────────────────────────────────────────────────

def test_t05_tenant_admin_cannot_read_other_tenant_and_employee_only_self(client, world):
    ta = client.get(f"/api/payroll/employees/{world.employees['B1'].id}", headers=world.headers("TA"))
    assert ta.status_code == 404
    ea_other = client.get(f"/api/payroll/employees/{world.employees['A2'].id}", headers=world.headers("EA"))
    assert ea_other.status_code in (403, 404)
    ea_list = client.get("/api/payroll/employees", headers=world.headers("EA"))
    assert ea_list.status_code == 403
    ea_self = client.get(f"/api/payroll/employees/{world.employees['A1'].id}", headers=world.headers("EA"))
    assert ea_self.status_code == 200
    # Scoped payroll admin (entity A-E1) sees A1 only.
    pa_list = client.get("/api/payroll/employees", headers=world.headers("PA"))
    assert pa_list.status_code == 200
    assert [e["id"] for e in pa_list.json()] == [world.employees["A1"].id]
    pa_other = client.get(f"/api/payroll/employees/{world.employees['A2'].id}", headers=world.headers("PA"))
    assert pa_other.status_code == 404
    for tid, role, resp, endpoint in (
        ("T05_TA_B1", "org_admin", ta, "GET /api/payroll/employees/{B1}"),
        ("T05_EA_A2", "employee", ea_other, "GET /api/payroll/employees/{A2}"),
        ("T05_PA_A2", "payroll_admin(entity A-E1)", pa_other, "GET /api/payroll/employees/{A2}"),
    ):
        record(test_id=tid, role=role, scope="tenant:A", tenant_ids=world.tenant_ids(), endpoint=endpoint,
               expected_status=404, actual_status=resp.status_code, body=resp.json(),
               decision_id=_decision_id(resp))


# ── T06 ─────────────────────────────────────────────────────────────────────

def test_t06_support_without_an_approved_grant_is_denied(client, world):
    for who in ("SP", "APP", "SA"):
        resp = client.get("/api/payroll/employees", headers=world.headers(who))
        assert resp.status_code == 403, (who, resp.text)
        assert _no_identity(resp.json())
    # A pending (unapproved) grant gives nothing either.
    req = client.post("/api/super-admin/support-access/request", headers=world.headers("SP"), json={
        "organizationCode": "PRIVA", "reason": "Ticket triage", "ticketReference": "ZT-1",
        "minutes": 15, "scopeType": "employees", "employeeCodes": ["A-0001"]})
    assert req.status_code == 200, req.text
    assert req.json()["status"] == "pending_approval"
    assert "A-0001" not in req.text, "codes are never echoed back to the operator"
    resp = client.get("/api/payroll/employees", headers=world.headers("SP"))
    assert resp.status_code == 403
    record(test_id="T06", role="support_operator", scope="platform (pending grant)",
           tenant_ids=world.tenant_ids(), endpoint="GET /api/payroll/employees", expected_status=403,
           actual_status=resp.status_code, body=resp.json(), decision_id=_decision_id(resp))


# ── T07 / T08 helpers ───────────────────────────────────────────────────────

def _grant_for_a1(client, world, fields=("identifier", "contact")):
    sp = world.headers("SP")
    req = client.post("/api/super-admin/support-access/request", headers=sp, json={
        "organizationCode": "PRIVA", "reason": "Customer cannot see A1's address", "ticketReference": "ZT-7",
        "minutes": 15, "scopeType": "employees", "employeeCodes": ["A-0001"]})
    assert req.status_code == 200, req.text
    gid = req.json()["id"]
    pending = client.get("/api/organization-admin/support-access/", headers=world.headers("TA"))
    resolved = pending.json()["pending"][0]["resolvedEmployees"]["resolved"]
    assert [r["employeeCode"] for r in resolved] == ["A-0001"]
    ok = client.post(f"/api/organization-admin/support-access/{gid}/approve", headers=world.headers("TA"),
                     json={"fieldClasses": list(fields), "employeeIds": [world.employees["A1"].id]})
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "pending_approval", "still waiting for the independent Zoiko approval"
    z = client.post(f"/api/super-admin/support-access/{gid}/zoiko-approve", headers=world.headers("APP"))
    assert z.status_code == 200, z.text
    assert z.json()["status"] == "active"
    creds = client.get(f"/api/super-admin/support-access/{gid}/credentials", headers=sp)
    assert creds.status_code == 200, creds.text
    return gid, creds.json()


def _temp_login(client, creds):
    r = client.post("/api/auth/login", json={"email": creds["username"], "password": creds["password"]})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


# ── T07 ─────────────────────────────────────────────────────────────────────

def test_t07_grant_for_a1_read_only_denies_a2_tenant_b_writes_and_exports(client, world, db):
    from app.modules.support_access.models import SupportAccessAuditEvent

    gid, creds = _grant_for_a1(client, world)
    token = _temp_login(client, creds)
    h = {"Authorization": f"Bearer {token}"}
    a1, a2, b1 = (world.employees[k].id for k in ("A1", "A2", "B1"))

    listing = client.get("/api/payroll/employees", headers=h)
    assert listing.status_code == 200, listing.text
    assert [e["id"] for e in listing.json()] == [a1]
    one = client.get(f"/api/payroll/employees/{a1}", headers=h)
    assert one.status_code == 200
    rec = one.json()
    assert rec["name"] == "Synthetic Worker A1" and rec["email"] == "a1@worker.example"
    for hidden in ("ctc", "basic", "bankAccount", "pan", "taxCode"):
        assert hidden not in rec, f"{hidden} must not leave the API for a support user"

    denied = {
        "A2": client.get(f"/api/payroll/employees/{a2}", headers=h),
        "B1": client.get(f"/api/payroll/employees/{b1}", headers=h),
        "write": client.put(f"/api/payroll/employees/{a1}", headers=h, json={"name": "changed"}),
        "export": client.get("/api/payroll/payslips/1/download", headers=h),
        "payslips": client.get("/api/payroll/payslips", headers=h),
    }
    assert denied["A2"].status_code == 404
    assert denied["B1"].status_code == 404
    assert denied["write"].status_code == 403
    assert denied["export"].status_code == 403
    assert denied["payslips"].status_code == 403
    events = {e.event_type for e in db.query(SupportAccessAuditEvent)
              .filter(SupportAccessAuditEvent.grant_id == gid).all()}
    assert {"ACCESS_DENIED_OUT_OF_SCOPE", "EXPORT_ATTEMPT_DENIED", "API_CALL", "CREDENTIALS_VIEWED",
            "GRANTED", "TENANT_APPROVED", "ZOIKO_APPROVED", "REQUESTED"} <= events
    for key, resp in denied.items():
        record(test_id=f"T07_{key}", role="support_temp", scope=f"grant:{gid}:employees[A1]:identifier+contact",
               tenant_ids=world.tenant_ids(), endpoint=f"{resp.request.method} {resp.request.url.path}",
               expected_status=404 if key in ("A2", "B1") else 403, actual_status=resp.status_code,
               body=resp.json(), decision_id=_decision_id(resp))


# ── T08 ─────────────────────────────────────────────────────────────────────

def test_t08_revocation_then_replay_of_the_old_token_is_denied_immediately(client, world):
    gid, creds = _grant_for_a1(client, world)
    token = _temp_login(client, creds)
    h = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/payroll/employees", headers=h).status_code == 200
    rv = client.post(f"/api/organization-admin/support-access/{gid}/revoke", headers=world.headers("TA"),
                     json={"reason": "Ticket resolved"})
    assert rv.status_code == 200 and rv.json()["status"] == "revoked"
    replay = client.get("/api/payroll/employees", headers=h)
    relogin = client.post("/api/auth/login", json={"email": creds["username"], "password": creds["password"]})
    assert replay.status_code == 401
    assert relogin.status_code == 401
    record(test_id="T08_revoke", role="support_temp", scope=f"grant:{gid} (revoked)",
           tenant_ids=world.tenant_ids(), endpoint="GET /api/payroll/employees", expected_status=401,
           actual_status=replay.status_code, body=replay.json(),
           note="old token replayed after tenant revocation, before any sweep")


def test_t08_expiry_then_replay_is_denied_before_the_sweep(client, world, db):
    from datetime import datetime, timedelta

    from app.modules.support_access.models import SupportAccessGrant

    gid, creds = _grant_for_a1(client, world)
    token = _temp_login(client, creds)
    h = {"Authorization": f"Bearer {token}"}
    grant = db.query(SupportAccessGrant).get(gid)
    from app.modules.auth.models import User

    user = db.query(User).get(grant.support_user_id)
    past = datetime.utcnow() - timedelta(seconds=1)
    grant.expires_at = past
    grant.activated_at = past - timedelta(minutes=15)
    user.access_expires_at = past
    db.commit()
    replay = client.get("/api/payroll/employees", headers=h)
    relogin = client.post("/api/auth/login", json={"email": creds["username"], "password": creds["password"]})
    assert replay.status_code == 401
    assert "temporary support access has ended" in replay.json()["message"]
    assert relogin.status_code == 401
    active = client.get("/api/super-admin/support-access/active", headers=world.headers("SP"))
    assert active.json()["grant"] is None, "lazy expiry: the operator's active grant is gone"
    record(test_id="T08_expiry", role="support_temp", scope=f"grant:{gid} (expired)",
           tenant_ids=world.tenant_ids(), endpoint="GET /api/payroll/employees", expected_status=401,
           actual_status=replay.status_code, body=replay.json())
