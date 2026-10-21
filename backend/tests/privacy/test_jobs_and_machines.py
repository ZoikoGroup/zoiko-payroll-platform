"""
tests/privacy/test_jobs_and_machines.py
---------------------------------------
Machine clients and webhooks (D06) and background-job re-authorization
(D08). T10: a service account changing its tenant claim, or a stale task
retry, is denied outside its bound scope.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tests.privacy._evidence import record

ORG = "/api/organization-admin"


def _create_client(client, world, scopes=("employees:read",), days=30):
    r = client.post(f"{ORG}/api-clients", headers=world.headers("TA"),
                    json={"name": "HRIS sync", "scopes": list(scopes), "expiresInDays": days})
    assert r.status_code == 200, r.text
    return r.json()


def test_machine_client_secret_shown_once_and_stored_hashed(client, world, db):
    from app.modules.security.models import MachineClient

    created = _create_client(client, world)
    cred = created["credential"]
    assert cred.startswith("zpmc_")
    row = db.query(MachineClient).get(created["id"])
    assert cred.split(".", 1)[1] not in (row.secret_hash or "")
    listed = client.get(f"{ORG}/api-clients", headers=world.headers("TA")).text
    assert cred.split(".", 1)[1] not in listed and "credential" not in listed
    sa = client.get("/api/super-admin/machine-clients", headers=world.headers("SA")).json()
    assert sa and "credential" not in str(sa) and "scopes" not in sa[0]


def test_machine_client_reads_only_its_scope_inside_its_tenant(client, world):
    cred = _create_client(client, world)["credential"]
    h = {"Authorization": f"Bearer {cred}"}
    rows = client.get("/api/payroll/employees", headers=h)
    assert rows.status_code == 200
    assert {r["id"] for r in rows.json()} == {world.employees["A1"].id, world.employees["A2"].id}
    assert all("ctc" not in r and "bankAccountNumber" not in r for r in rows.json())
    assert client.get("/api/payroll/payslips", headers=h).status_code == 403          # no scope
    assert client.put(f"/api/payroll/employees/{world.employees['A1'].id}", headers=h,
                      json={"name": "x"}).status_code == 403                          # read-only
    assert client.get(f"/api/payroll/employees/{world.employees['B1'].id}", headers=h).status_code == 404


def test_t10_machine_client_naming_another_tenant_is_denied(client, world, db):
    from app.modules.security.models import SecurityEvent

    cred = _create_client(client, world)["credential"]
    h = {"Authorization": f"Bearer {cred}"}
    for resp in (
        client.get(f"/api/payroll/employees?organization_id={world.orgs['B'].id}", headers=h),
        client.get("/api/payroll/employees", headers={**h, "X-Tenant-Id": str(world.orgs["B"].id)}),
    ):
        assert resp.status_code == 404
    denied = db.query(SecurityEvent).filter(SecurityEvent.actor_role == "machine_client",
                                            SecurityEvent.result == "deny").count()
    assert denied >= 2
    record(test_id="T10_machine_tenant_claim", role="machine_client", scope="tenant:A employees:read",
           tenant_ids=world.tenant_ids(), endpoint="GET /api/payroll/employees?organization_id=<B>",
           expected_status=404, actual_status=404, note="tenant claim change refused and audited")


def test_rotation_expiry_and_revocation_take_effect_immediately(client, world, db):
    from app.modules.security.models import MachineClient

    created = _create_client(client, world)
    old = created["credential"]
    stepped = world.headers("TA")
    new = client.post(f"{ORG}/api-clients/{created['id']}/rotate", headers=stepped).json()["credential"]
    assert client.get("/api/payroll/employees", headers={"Authorization": f"Bearer {old}"}).status_code == 401
    assert client.get("/api/payroll/employees", headers={"Authorization": f"Bearer {new}"}).status_code == 200
    row = db.query(MachineClient).get(created["id"])
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert client.get("/api/payroll/employees", headers={"Authorization": f"Bearer {new}"}).status_code == 401
    row.expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    db.commit()
    client.post(f"{ORG}/api-clients/{created['id']}/revoke", headers=stepped)
    assert client.get("/api/payroll/employees", headers={"Authorization": f"Bearer {new}"}).status_code == 401


def test_scopes_are_least_privilege_no_wildcards(client, world):
    for scopes in (["*"], ["employees:*"], ["employees:write"], []):
        r = client.post(f"{ORG}/api-clients", headers=world.headers("TA"),
                        json={"name": "x", "scopes": scopes, "expiresInDays": 30})
        assert r.status_code == 400, scopes
    assert client.post(f"{ORG}/api-clients", headers=world.headers("TA"),
                       json={"name": "x", "scopes": ["employees:read"], "expiresInDays": 400}).status_code == 400


def test_issuing_a_credential_needs_step_up(client, world):
    stale = {"Authorization": f"Bearer {world.token('TA', mfa_at=int(datetime.now().timestamp()) - 3600)}"}
    r = client.post(f"{ORG}/api-clients", headers=stale, json={"name": "x", "scopes": ["employees:read"],
                                                               "expiresInDays": 30})
    assert r.status_code == 403 and r.json()["error"] == "STEP_UP_REQUIRED"


def test_machine_client_new_network_alert(db, world, client):
    from app.modules.security import machine_clients as mc
    from app.modules.security.models import AlertEvent

    cred = _create_client(client, world)["credential"]
    mc.resolve(db, cred, "10.0.0.5")
    mc.resolve(db, cred, "10.0.0.9")          # same /24: no alert
    assert db.query(AlertEvent).filter(AlertEvent.rule_key == "machine_client_new_network").count() == 0
    mc.resolve(db, cred, "192.168.77.4")      # new network
    assert db.query(AlertEvent).filter(AlertEvent.rule_key == "machine_client_new_network").count() == 1


def test_webhooks_are_signed_replay_protected_and_tenant_pinned(client, world, db):
    from app.core.exceptions import BadRequestException
    from app.modules.security import machine_clients as mc
    from app.modules.security.models import WebhookEndpoint

    created = client.post(f"{ORG}/webhooks", headers=world.headers("TA"),
                          json={"url": "https://hooks.example.test/zoiko", "events": ["payroll_run.paid"]}).json()
    secret = created["signingSecret"]
    endpoint = db.query(WebhookEndpoint).get(created["id"])
    delivery = mc.build_delivery(db, endpoint, "payroll_run.paid", {"organizationId": world.orgs["A"].id, "runId": 7})
    seen: set = set()
    headers, body = delivery["headers"], delivery["body"]
    assert mc.verify(secret, headers["Zoiko-Signature"], headers["Zoiko-Event-Id"], body, seen_event_ids=seen)
    assert not mc.verify(secret, headers["Zoiko-Signature"], headers["Zoiko-Event-Id"], body, seen_event_ids=seen)
    assert not mc.verify(secret, headers["Zoiko-Signature"], "other-id", body, seen_event_ids=set())
    assert not mc.verify(secret, headers["Zoiko-Signature"], headers["Zoiko-Event-Id"], body + b"x", seen_event_ids=set())
    late = datetime.now(timezone.utc) + timedelta(minutes=10)
    assert not mc.verify(secret, headers["Zoiko-Signature"], headers["Zoiko-Event-Id"], body,
                         seen_event_ids=set(), now=late)
    with pytest.raises(BadRequestException):
        mc.build_delivery(db, endpoint, "payroll_run.paid", {"organizationId": world.orgs["B"].id})
    assert client.post(f"{ORG}/webhooks", headers=world.headers("TA"),
                       json={"url": "http://insecure.example", "events": ["payroll_run.paid"]}).status_code == 400


# ── Background jobs (D08) ───────────────────────────────────────────────────

def _ctx(world, who="TA"):
    return {"principal_user_id": world.users[who].id, "organization_id": world.users[who].organization_id,
            "correlation_id": "corr-test-0001"}


def test_job_runs_under_the_requesters_tenant_scope(db, world):
    from app.core.job_auth import authorized_job
    from app.modules.payroll.models import PayrollEmployee

    with authorized_job(db, _ctx(world, "PA"), task_name="t", organization_id=world.orgs["A"].id) as auth:
        assert auth["employee_ids"] == frozenset({world.employees["A1"].id})
        assert [e.id for e in db.query(PayrollEmployee).all()] == [world.employees["A1"].id]
    with authorized_job(db, _ctx(world, "TA"), task_name="t", organization_id=world.orgs["A"].id):
        assert {e.organization_id for e in db.query(PayrollEmployee).all()} == {world.orgs["A"].id}


@pytest.mark.parametrize("mutation, reason", [
    ("deactivate", "PRINCIPAL_INACTIVE"),
    ("demote", "ROLE_NO_LONGER_PERMITTED"),
    ("tenant_swap", "TENANT_SWAP"),
    ("suspend", "TENANT_SUSPENDED"),
    ("no_context", "MISSING_PRINCIPAL_CONTEXT"),
])
def test_t10_job_replay_after_change_is_denied_and_audited(db, world, mutation, reason):
    from app.core.job_auth import JobAuthorizationError, authorized_job
    from app.modules.auth.models import UserRole
    from app.modules.security.models import SecurityEvent

    ctx = _ctx(world, "TA")
    org_id = world.orgs["A"].id
    if mutation == "deactivate":
        world.users["TA"].is_active = False
    elif mutation == "demote":
        world.users["TA"].role = UserRole.EMPLOYEE
    elif mutation == "tenant_swap":
        org_id = world.orgs["B"].id
    elif mutation == "suspend":
        world.orgs["A"].is_active = False
    elif mutation == "no_context":
        ctx = None
    db.commit()
    with pytest.raises(JobAuthorizationError):
        with authorized_job(db, ctx, task_name="generate_payslips_for_run_task", organization_id=org_id):
            pass
    ev = db.query(SecurityEvent).filter(SecurityEvent.event_type == "JOB_DENIED").order_by(SecurityEvent.id.desc()).first()
    assert ev is not None and ev.reason_code == reason
    record(test_id=f"T10_job_{mutation}", role="job", scope=f"requester:{world.users['TA'].id}",
           tenant_ids=world.tenant_ids(), endpoint="celery:generate_payslips_for_run_task",
           expected_status=0, actual_status=0, security_event_id=ev.id, correlation_id=ev.correlation_id,
           note=f"stale retry / replay refused: {reason}")


def test_celery_payslip_task_refuses_a_stale_retry(db, world, monkeypatch):
    from app.core.job_auth import JobAuthorizationError
    from app.tasks import payroll_tasks

    monkeypatch.setattr(payroll_tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    ctx = _ctx(world, "TA")
    world.users["TA"].is_active = False
    db.commit()
    with pytest.raises(JobAuthorizationError):
        payroll_tasks.generate_payslips_for_run_task.apply(
            args=[999, world.orgs["A"].id], kwargs={"job_ctx": ctx}, throw=True).get()
    out = payroll_tasks.generate_payslip_for_employee_task.apply(
        args=[999, world.orgs["A"].id, world.employees["A1"].id], kwargs={"job_ctx": ctx}).get()
    assert out["error"] == "not authorized" and out["reason"] == "PRINCIPAL_INACTIVE"


def test_finalize_callback_and_unenqueued_tasks_refuse_stale_context(db, world, monkeypatch):
    from app.core.job_auth import JobAuthorizationError
    from app.tasks import attendance_tasks, employee_tasks, payroll_tasks
    from app.modules.security.models import SecurityEvent

    for module in (payroll_tasks, employee_tasks, attendance_tasks):
        monkeypatch.setattr(module, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    with pytest.raises(JobAuthorizationError):
        payroll_tasks.finalize_payroll_run_task.apply(
            args=[[], 999, world.orgs["A"].id, 0], kwargs={"job_ctx": None}, throw=True).get()
    ctx = _ctx(world, "TA")
    world.users["TA"].is_active = False
    db.commit()
    out = employee_tasks.bulk_delete_employees_task.apply(
        args=[world.orgs["A"].id, [world.employees["A1"].id]], kwargs={"job_ctx": ctx}).get()
    assert out == {"error": "not authorized", "reason": "PRINCIPAL_INACTIVE"}
    swapped = attendance_tasks.bulk_upload_attendance_task.apply(
        args=[world.orgs["A"].id, "", "x.xlsx"], kwargs={"job_ctx": _ctx(world, "TB")}).get()
    assert swapped == {"error": "not authorized", "reason": "TENANT_SWAP"}
    assert db.query(SecurityEvent).filter(SecurityEvent.event_type == "JOB_DENIED",
                                          SecurityEvent.target_id == "bulk_delete_employees_task").count() >= 1
    from app.modules.payroll.models import PayrollEmployee

    assert db.query(PayrollEmployee).get(world.employees["A1"].id) is not None  # nothing deleted
