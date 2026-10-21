"""
tests/privacy/test_security_events.py
-------------------------------------
Unified security events, correlation ids, tamper evidence and alerting
(ZP-PRIV E01-E05). Real Postgres tamper tests are in test_postgres_guards.py.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from tests.privacy._evidence import record

PERSONAL = ("Synthetic Worker", "worker.example", "A-0001", "GB00SYNTH", "SYNTHPAN")


def test_correlation_id_flows_from_header_to_response_decision_and_security_event(client, world, db):
    from app.modules.auth.models import AuthzDecisionEvent
    from app.modules.security.models import SecurityEvent

    cid = "acceptance-corr-0001"
    resp = client.get(f"/api/payroll/employees/{world.employees['A1'].id}",
                      headers={**world.headers("SA"), "X-Correlation-ID": cid})
    assert resp.status_code == 403
    assert resp.headers["X-Correlation-ID"] == cid
    decision_id = resp.json()["trace"]["decisionId"]
    event = db.query(SecurityEvent).filter(SecurityEvent.correlation_id == cid).one()
    assert event.event_type == "PDP_DENY" and event.result == "deny"
    assert event.decision_trace_id == decision_id and event.actor_role == "super_admin"
    assert event.target_type == "employee:worker"
    assert db.query(AuthzDecisionEvent).filter(AuthzDecisionEvent.decision_id == decision_id).count() == 1
    # A malformed incoming id is replaced, never trusted into the logs.
    bad = client.get("/api/auth/me", headers={**world.headers("TA"), "X-Correlation-ID": "x;drop table"})
    assert bad.headers["X-Correlation-ID"] != "x;drop table"


def test_every_security_event_is_free_of_personal_data(client, world, db):
    from app.modules.security.models import SecurityEvent

    client.get(f"/api/payroll/employees/{world.employees['A1'].id}", headers=world.headers("SA"))
    client.get("/api/payroll/employees", headers=world.headers("SP"))
    client.post("/api/auth/login", json={"email": "ta@tenant-a.example", "password": "wrong"})
    for e in db.query(SecurityEvent).all():
        blob = json.dumps({c.name: str(getattr(e, c.name)) for c in SecurityEvent.__table__.columns})
        assert not any(p in blob for p in PERSONAL), blob


def test_grant_events_mfa_failures_and_credential_resets_emit(client, world, db):
    from app.modules.security.models import SecurityEvent

    req = client.post("/api/super-admin/support-access/request", headers=world.headers("SP"), json={
        "organizationCode": "PRIVA", "reason": "r", "ticketReference": "T-9", "minutes": 5,
        "scopeType": "diagnostics"}).json()
    client.post(f"/api/organization-admin/support-access/{req['id']}/approve", headers=world.headers("TA"), json={})
    # Tenant A has a live, tenant-approved grant -> a reset there is allowed;
    # tenant B has none -> refused. Both are security events.
    assert client.put(f"/api/super-admin/users/{world.users['PA'].id}/reset-password",
                      headers=world.headers("SA")).status_code == 200
    assert client.put(f"/api/super-admin/users/{world.users['TB'].id}/reset-password",
                      headers=world.headers("SA")).status_code == 403
    resets = db.query(SecurityEvent).filter(SecurityEvent.event_type == "CREDENTIAL_RESET").all()
    assert {r.result for r in resets} == {"allow", "deny"}
    types = {e.event_type for e in db.query(SecurityEvent).all()}
    assert {"SUPPORT_REQUESTED", "SUPPORT_TENANT_APPROVED", "SUPPORT_GRANTED"} <= types
    assert "CREDENTIAL_RESET" in types
    grant_events = db.query(SecurityEvent).filter(SecurityEvent.grant_id == req["id"]).all()
    assert all(e.on_behalf_of_user_id == world.users["SP"].id for e in grant_events)


def test_hash_chain_detects_tampering(db, world, client):
    from app.modules.security import events

    client.get(f"/api/payroll/employees/{world.employees['A1'].id}", headers=world.headers("SA"))
    client.get("/api/payroll/employees", headers=world.headers("SP"))
    assert events.verify_chain(db)["ok"] is True
    # SQLite triggers refuse UPDATE outright; simulate an attacker who bypassed
    # them (drop trigger) and edited a row: verification still catches it.
    from sqlalchemy import text

    db.execute(text("DROP TRIGGER IF EXISTS security_events_no_update"))
    db.execute(text("UPDATE security_events SET reason_code = 'ALLOW' WHERE id = (SELECT MIN(id) FROM security_events)"))
    db.commit()
    result = events.verify_chain(db)
    assert result["ok"] is False and result["broken_at"] is not None
    record(test_id="E02_tamper_detected", role="attacker", scope="security_events", tenant_ids=None,
           endpoint="UPDATE security_events", expected_status=0, actual_status=0, note=str(result))


def test_security_event_rows_are_append_only(db, world):
    from sqlalchemy.exc import DatabaseError

    from app.modules.security import events

    row = events.emit(db, "TEST_EVENT", result="allow")
    for statement in ("UPDATE security_events SET result = 'deny' WHERE id = :i",
                      "DELETE FROM security_events WHERE id = :i"):
        from sqlalchemy import text

        with pytest.raises(DatabaseError):
            db.execute(text(statement), {"i": row.id})
            db.commit()
        db.rollback()


def test_anchoring_writes_the_chain_head_to_the_external_sink(db, world):
    from app.modules.security import events

    events.emit(db, "TEST_EVENT", result="allow")
    sink = events.FakeSink()
    anchor = events.anchor(db, sink)
    key, body = sink.objects[0]
    payload = json.loads(body)
    assert payload["last_row_hash"] == anchor.last_row_hash and anchor.sink_receipt.startswith("fake://")


def test_audit_purge_on_org_hard_delete_defaults_off():
    from app.config import settings

    assert settings.AUDIT_PURGE_ON_ORG_HARD_DELETE is False and settings.AUDIT_RETENTION_YEARS == 7


def test_audit_readers_are_restricted(client, world):
    for who, status in (("SA", 200), ("APP", 200), ("SP", 403), ("TA", 403)):
        assert client.get("/api/super-admin/security-events", headers=world.headers(who)).status_code == status, who
    own = client.get("/api/organization-admin/security-events", headers=world.headers("TA"))
    assert own.status_code == 200
    assert all(e["organizationId"] == world.orgs["A"].id for e in own.json()["items"])


# ── Alerting ────────────────────────────────────────────────────────────────

@pytest.fixture()
def clock():
    from app.modules.security import alerts

    t = {"now": datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)}
    alerts.set_clock(lambda: t["now"])
    yield t
    alerts.set_clock(None)


def _alerts(db, key):
    from app.modules.security.models import AlertEvent

    return db.query(AlertEvent).filter(AlertEvent.rule_key == key).all()


def test_every_rule_fires_dedupes_and_never_carries_personal_data(db, world, client, clock):
    from app.modules.security import alerts, events

    # cross-tenant: Super Admin probing worker data
    for _ in range(3):
        client.get(f"/api/payroll/employees/{world.employees['A1'].id}", headers=world.headers("SA"))
    assert len(_alerts(db, "cross_tenant_access")) == 1 and _alerts(db, "cross_tenant_access")[0].count == 3
    # enumeration: 25 distinct employee targets
    for i in range(25):
        events.emit(db, "PRIVILEGED_READ", result="allow", actor_user_id=777, actor_role="support_temp",
                    target_type="employee:worker", target_id=f"employee:{1000 + i}")
    assert len(_alerts(db, "employee_enumeration")) == 1
    # large export
    events.emit(db, "EXPORT_COMPLETED", result="allow", actor_user_id=5, target_type="route:worker",
                target_id="GET /x|0:20000000")
    assert len(_alerts(db, "large_export")) == 1
    # unscheduled elevation: a grant at 02:00 UTC and any break-glass
    clock["now"] = datetime(2026, 10, 19, 2, 0, tzinfo=timezone.utc)
    events.emit(db, "SUPPORT_GRANTED", result="allow", grant_id=41, ticket_reference="T-1")
    events.emit(db, "SUPPORT_BREAK_GLASS_OPENED", result="allow", grant_id=42, ticket_reference="INC-1")
    assert len(_alerts(db, "unscheduled_elevation")) == 2
    # MFA failures: 5 in the window
    for _ in range(5):
        events.emit(db, "MFA_FAILED", result="deny", actor_user_id=9)
    assert len(_alerts(db, "mfa_failures")) == 1
    events.emit(db, "SUPPORT_BREAK_GLASS_REVIEW_OVERDUE", result="allow", grant_id=42)
    assert len(_alerts(db, "overdue_break_glass_review")) == 1
    events.emit(db, "MACHINE_CLIENT_NEW_NETWORK", result="allow", target_id="client:3")
    assert len(_alerts(db, "machine_client_new_network")) == 1
    alerts.raise_alert(db, "failed_audit_write", dedupe_key="X", summary="A security event could not be written")
    assert len(_alerts(db, "failed_audit_write")) == 1
    # A new dedupe window opens a new alert; inside the window it only counts.
    clock["now"] += timedelta(minutes=16)
    client.get(f"/api/payroll/employees/{world.employees['A1'].id}", headers=world.headers("SA"))
    assert len(_alerts(db, "cross_tenant_access")) == 2
    from app.modules.security.models import AlertEvent

    for a in db.query(AlertEvent).all():
        assert not any(p in a.summary for p in PERSONAL), a.summary
        assert a.delivery_receipt and "console" in a.delivery_receipt
    assert {a.rule_key for a in db.query(AlertEvent).all()} == set(alerts.RULES_BY_KEY)


def test_failed_audit_write_raises_the_alert(db, world, monkeypatch):
    from app.modules.security import events
    from app.modules.security.models import SecurityEvent

    def boom(*a, **kw):
        raise RuntimeError("store down")

    monkeypatch.setattr(SecurityEvent, "__init__", boom)
    assert events.emit(db, "PDP_DENY", result="deny") is None
    assert len(_alerts(db, "failed_audit_write")) == 1


def test_alert_api_ack_and_test_fire(client, world, db):
    r = client.post("/api/super-admin/alert-rules/large_export/test-fire", headers=world.headers("APP"))
    assert r.status_code == 200 and "console" in r.json()["deliveryReceipt"]
    assert client.post("/api/super-admin/alert-rules/large_export/test-fire", headers=world.headers("SA")).status_code == 403
    events = client.get("/api/super-admin/alert-events", headers=world.headers("SA")).json()
    ack = client.post(f"/api/super-admin/alert-events/{events[0]['id']}/acknowledge", headers=world.headers("APP"))
    assert ack.json()["status"] == "acknowledged"
    rules = client.get("/api/super-admin/alert-rules", headers=world.headers("APP")).json()
    assert {r["key"] for r in rules} >= {"cross_tenant_access", "employee_enumeration", "large_export"}


def test_alert_rules_are_exported(tmp_path):
    from app.modules.security import alerts

    path = tmp_path / "alert_rules.json"
    alerts.export_rules(path)
    data = json.loads(path.read_text())
    assert {r["key"] for r in data["rules"]} == set(alerts.RULES_BY_KEY)
    assert data["dedupe_window_seconds"] == 900


def test_privileged_inventory(client, world, db):
    inv = client.get("/api/super-admin/privileged-inventory", headers=world.headers("APP")).json()
    roles = {h["role"] for h in inv["humans"]}
    assert {"super_admin", "support_operator", "platform_security", "org_admin"} <= roles
    tenant_rows = [h for h in inv["humans"] if h["plane"] == "tenant"]
    assert all(h["account"] is None for h in tenant_rows)  # no tenant personal data
    assert inv["summary"]["withoutMfa"] >= 1
