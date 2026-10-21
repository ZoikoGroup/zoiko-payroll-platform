"""
tests/privacy/test_support_access.py
------------------------------------
JIT Support Access rules (ZP-PRIV Part D, C01-C08) end to end over HTTP with
real JWTs, plus the database-level guarantees.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from tests.privacy._evidence import record

SA_BASE = "/api/super-admin/support-access"
ORG_BASE = "/api/organization-admin/support-access"


def _request(client, world, who="SP", **over):
    body = {"organizationCode": "PRIVA", "reason": "Investigating a payroll ticket", "ticketReference": "ZT-42",
            "minutes": 15, "scopeType": "diagnostics"}
    body.update(over)
    return client.post(f"{SA_BASE}/request", headers=world.headers(who), json=body)


def _approve(client, world, gid, who="TA", **body):
    return client.post(f"{ORG_BASE}/{gid}/approve", headers=world.headers(who), json=body)


def test_diagnostics_grant_needs_only_the_tenant_and_has_no_worker_scope(client, world):
    gid = _request(client, world).json()["id"]
    assert _approve(client, world, gid).json()["status"] == "active"   # decision 4
    creds = client.get(f"{SA_BASE}/{gid}/credentials", headers=world.headers("SP")).json()
    assert creds["username"].startswith(f"support-{gid}-")
    login = client.post("/api/auth/login", json={"email": creds["username"], "password": creds["password"]})
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/api/payroll/employees", headers=h).status_code == 403
    me = client.get("/api/auth/me", headers=h)
    assert me.status_code == 200 and me.json()["role"] == "support_temp"
    assert client.post("/api/auth/change-password", headers=h,
                       json={"current_password": creds["password"], "new_password": "x" * 12}).status_code == 403


def test_org_admin_of_another_org_gets_404(client, world):
    gid = _request(client, world).json()["id"]
    for path in (f"{ORG_BASE}/{gid}/approve", f"{ORG_BASE}/{gid}/deny", f"{ORG_BASE}/{gid}/revoke"):
        resp = client.post(path, headers=world.headers("TB"), json={"reason": "not mine"})
        assert resp.status_code == 404, (path, resp.text)
    assert client.get(f"{ORG_BASE}/", headers=world.headers("TB")).json()["pending"] == []


def test_self_approval_is_impossible_in_the_service_and_the_database(client, world, db):
    from sqlalchemy.exc import IntegrityError

    from app.modules.support_access.models import SupportAccessGrant

    gid = _request(client, world, who="APP", scopeType="employees", employeeCodes=["A-0001"]).json()["id"]
    resp = client.post(f"{SA_BASE}/{gid}/zoiko-approve", headers=world.headers("APP"))
    assert resp.status_code == 403
    grant = db.query(SupportAccessGrant).get(gid)
    grant.zoiko_approved_by_user_id = grant.requested_by_user_id
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    grant = db.query(SupportAccessGrant).get(gid)
    grant.approved_by_user_id = grant.requested_by_user_id
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_decline_requires_a_reason_shown_to_the_operator(client, world):
    gid = _request(client, world).json()["id"]
    assert client.post(f"{ORG_BASE}/{gid}/deny", headers=world.headers("TA"), json={"reason": " "}).status_code == 400
    ok = client.post(f"{ORG_BASE}/{gid}/deny", headers=world.headers("TA"), json={"reason": "Not needed"})
    assert ok.status_code == 200 and ok.json()["status"] == "denied"
    mine = client.get(f"{SA_BASE}/mine", headers=world.headers("SP")).json()
    assert mine[0]["outcome"] == "Declined: Not needed"


def test_no_active_org_admin_refuses_the_request(client, world, db):
    world.users["TA"].is_active = False
    db.commit()
    resp = _request(client, world)
    assert resp.status_code == 409
    assert "break-glass" in resp.json()["message"]


def test_unanswered_request_lapses_after_60_minutes(client, world, db):
    from app.modules.support_access.models import SupportAccessGrant

    gid = _request(client, world).json()["id"]
    grant = db.query(SupportAccessGrant).get(gid)
    grant.approval_expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    assert client.get(f"{SA_BASE}/active", headers=world.headers("SP")).json()["grant"] is None
    mine = client.get(f"{SA_BASE}/mine", headers=world.headers("SP")).json()
    assert mine[0]["status"] == "expired_unused"
    assert mine[0]["outcome"] == "No one approved it within 60 minutes"
    # The lapsed request no longer blocks a new one.
    assert _request(client, world).status_code == 200


def test_cancel_is_owner_only_and_pending_only(client, world):
    gid = _request(client, world).json()["id"]
    assert client.post(f"{SA_BASE}/{gid}/cancel", headers=world.headers("SA")).status_code == 404
    assert client.post(f"{SA_BASE}/{gid}/cancel", headers=world.headers("SP")).json()["status"] == "cancelled"
    assert client.post(f"{SA_BASE}/{gid}/cancel", headers=world.headers("SP")).status_code == 400


def test_credentials_are_owner_only_active_only_and_audited(client, world, db):
    from app.modules.support_access.models import SupportAccessAuditEvent

    gid = _request(client, world).json()["id"]
    assert client.get(f"{SA_BASE}/{gid}/credentials", headers=world.headers("SP")).status_code == 404  # pending
    _approve(client, world, gid)
    assert client.get(f"{SA_BASE}/{gid}/credentials", headers=world.headers("SA")).status_code == 404  # not owner
    ok = client.get(f"{SA_BASE}/{gid}/credentials", headers=world.headers("SP"))
    assert ok.status_code == 200 and len(ok.json()["password"]) == 16
    assert ok.json()["expiresAt"].endswith("Z")
    viewed = db.query(SupportAccessAuditEvent).filter(SupportAccessAuditEvent.grant_id == gid,
                                                      SupportAccessAuditEvent.event_type == "CREDENTIALS_VIEWED")
    assert viewed.count() == 1
    # The password is never in any other response.
    for path in (f"{SA_BASE}/active", f"{SA_BASE}/mine"):
        assert ok.json()["password"] not in client.get(path, headers=world.headers("SP")).text
    client.post(f"{SA_BASE}/{gid}/exit", headers=world.headers("SP"))
    assert client.get(f"{SA_BASE}/{gid}/credentials", headers=world.headers("SP")).status_code == 404


def test_one_live_grant_per_operator_also_at_database_level(client, world, db):
    from sqlalchemy.exc import IntegrityError

    from app.modules.support_access.models import SupportAccessGrant

    assert _request(client, world).status_code == 200
    second = _request(client, world, organizationCode="PRIVB")
    assert second.status_code == 409
    db.add(SupportAccessGrant(organization_id=world.orgs["B"].id, requested_by_user_id=world.users["SP"].id,
                              reason="x", ticket_reference="y", requested_minutes=5, status="pending_approval",
                              correlation_id="c", scope_type="diagnostics", requested_at=datetime.utcnow()))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_hard_maximum_30_minutes(client, world, db):
    from sqlalchemy.exc import IntegrityError

    from app.modules.support_access.models import SupportAccessGrant

    assert _request(client, world, minutes=60).status_code == 400
    gid = _request(client, world, minutes=30).json()["id"]
    _approve(client, world, gid)
    grant = db.query(SupportAccessGrant).get(gid)
    assert grant.expires_at - grant.activated_at == timedelta(minutes=30)
    grant.expires_at = grant.activated_at + timedelta(minutes=45)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_scope_can_be_narrowed_never_widened_and_codes_never_reach_the_operator(client, world):
    gid = _request(client, world, scopeType="employees", employeeCodes=["A-0001", "A-0002", "NOPE"]).json()["id"]
    pending = client.get(f"{ORG_BASE}/", headers=world.headers("TA")).json()["pending"][0]
    assert pending["resolvedEmployees"]["unresolved"] == ["NOPE"]
    widen = _approve(client, world, gid, employeeIds=[world.employees["B1"].id])
    assert widen.status_code == 400
    narrow = _approve(client, world, gid, employeeIds=[world.employees["A1"].id])
    assert narrow.status_code == 200
    op_view = client.get(f"{SA_BASE}/mine", headers=world.headers("SP")).text
    for leaked in ("A-0001", "A-0002", "Synthetic Worker"):
        assert leaked not in op_view


def test_platform_security_views_are_platform_security_only(client, world):
    for path in (f"{SA_BASE}/live", f"{SA_BASE}/approvals", f"{SA_BASE}/pending-review"):
        for who in ("SA", "SP", "TA"):
            assert client.get(path, headers=world.headers(who)).status_code == 403, (path, who)
        assert client.get(path, headers=world.headers("APP")).status_code == 200


def test_platform_security_revoke_needs_a_reason_and_ends_the_login(client, world):
    gid = _request(client, world).json()["id"]
    _approve(client, world, gid)
    creds = client.get(f"{SA_BASE}/{gid}/credentials", headers=world.headers("SP")).json()
    token = client.post("/api/auth/login", json={"email": creds["username"],
                                                 "password": creds["password"]}).json()["access_token"]
    assert client.post(f"{SA_BASE}/{gid}/revoke", headers=world.headers("APP"), json={"reason": ""}).status_code == 400
    ok = client.post(f"{SA_BASE}/{gid}/revoke", headers=world.headers("APP"), json={"reason": "Incident closed"})
    assert ok.json()["status"] == "revoked" and ok.json()["revokedByTenant"] is False
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_operator_logout_ends_the_live_grant(client, world):
    gid = _request(client, world).json()["id"]
    _approve(client, world, gid)
    assert client.post("/api/auth/logout", headers=world.headers("SP")).status_code == 200
    assert client.get(f"{SA_BASE}/active", headers=world.headers("SP")).json()["grant"] is None
    assert client.get(f"{SA_BASE}/mine", headers=world.headers("SP")).json()[0]["status"] == "exited"


def test_approval_requires_a_recent_step_up(client, world):
    gid = _request(client, world).json()["id"]
    stale = {"Authorization": f"Bearer {world.token('TA', mfa_at=int(datetime.utcnow().timestamp()) - 3600)}"}
    resp = client.post(f"{ORG_BASE}/{gid}/approve", headers=stale, json={})
    assert resp.status_code == 403 and resp.json()["error"] == "STEP_UP_REQUIRED"


def _enroll_totp(db, user):
    import pyotp

    from app.modules.auth import mfa

    secret = mfa.begin_enrollment(db, user)["secret"]
    mfa.confirm_enrollment(db, user, pyotp.TOTP(secret).now())
    return secret


def _fresh(secret, db, user):
    import pyotp

    from app.modules.auth.models import MfaCredential

    import time

    cred = db.query(MfaCredential).filter(MfaCredential.user_id == user.id).first()
    step = int(time.time() // 30)
    if cred.last_used_step is not None and cred.last_used_step >= step:
        # Simulate the authenticator's clock moving on: the server refuses a
        # replayed or earlier step (and only tolerates +-1 step of drift).
        cred.last_used_step = step - 1
        db.commit()
    return pyotp.TOTP(secret).at(step * 30)


def test_break_glass_flow_review_and_lockout(client, world, db):
    from app.modules.support_access.models import SupportAccessAuditEvent

    secret = _enroll_totp(db, world.users["APP"])
    body = {"organizationCode": "PRIVA", "incidentReference": "INC-9", "reason": "Active fraud investigation",
            "acknowledged": True}
    assert client.post(f"{SA_BASE}/break-glass", headers=world.headers("APP"),
                       json={**body, "mfaCode": "000000"}).status_code == 401
    assert client.post(f"{SA_BASE}/break-glass", headers=world.headers("SP"),
                       json={**body, "mfaCode": "000000"}).status_code == 403  # platform_security only
    opened = client.post(f"{SA_BASE}/break-glass", headers=world.headers("APP"),
                         json={**body, "mfaCode": _fresh(secret, db, world.users["APP"])})
    assert opened.status_code == 200, opened.text
    g = opened.json()
    assert g["status"] == "active" and g["isBreakGlass"] and g["scopeType"] == "tenant"
    assert g["allowedFieldClasses"] == ["identifier", "contact"]
    assert (datetime.fromisoformat(g["expiresAt"][:-1]) - datetime.fromisoformat(g["activatedAt"][:-1])
            == timedelta(minutes=30))
    events = {e.event_type for e in db.query(SupportAccessAuditEvent)
              .filter(SupportAccessAuditEvent.grant_id == g["id"]).all()}
    assert {"BREAK_GLASS_OPENED", "GRANTED"} <= events
    assert events & {"TENANT_NOTIFIED", "TENANT_NOTIFICATION_FAILED"}

    # Tenant-wide, read-only, identifier + contact only.
    creds = client.get(f"{SA_BASE}/{g['id']}/credentials", headers=world.headers("APP")).json()
    token = client.post("/api/auth/login", json={"email": creds["username"],
                                                 "password": creds["password"]}).json()["access_token"]
    rows = client.get("/api/payroll/employees", headers={"Authorization": f"Bearer {token}"}).json()
    assert {r["id"] for r in rows} == {world.employees["A1"].id, world.employees["A2"].id}
    assert all("ctc" not in r and "bankAccount" not in r for r in rows)

    client.post(f"{SA_BASE}/{g['id']}/exit", headers=world.headers("APP"))
    # The opener cannot open another until the review is closed...
    again = client.post(f"{SA_BASE}/break-glass", headers=world.headers("APP"),
                        json={**body, "mfaCode": _fresh(secret, db, world.users["APP"])})
    assert again.status_code == 409
    # ...and cannot review their own.
    own = client.post(f"{SA_BASE}/{g['id']}/review", headers=world.headers("APP"),
                      json={"outcome": "justified", "findings": "fine"})
    assert own.status_code == 403
    reviewed = client.post(f"{SA_BASE}/{g['id']}/review", headers=world.headers("PS2"),
                           json={"outcome": "justified", "findings": "Fraud confirmed; access proportionate."})
    assert reviewed.status_code == 200 and reviewed.json()["reviewOutcome"] == "justified"
    record(test_id="D_break_glass_review", role="platform_security", scope=f"break-glass:{g['id']}",
           tenant_ids=world.tenant_ids(), endpoint="POST /api/super-admin/support-access/{id}/review",
           expected_status=200, actual_status=reviewed.status_code, body=reviewed.json())


def test_overdue_break_glass_review_escalates(client, world, db):
    from app.modules.support_access import service
    from app.modules.support_access.models import SupportAccessGrant

    grant = service.open_break_glass(db, world.users["APP"], organization_id=world.orgs["A"].id,
                                     incident_reference="INC-1", reason="r", acknowledged=True)
    db.query(SupportAccessGrant).get(grant.id).review_due_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    out = service.run_sweep(db)
    assert grant.id in out["escalated_reviews"]
    alerts = client.get("/api/super-admin/alerts", headers=world.headers("SA")).json()
    assert any(a["category"] == "security" and "overdue" in a["message"] for a in alerts["alerts"])


def test_sweep_ends_overdue_grants_and_deactivates_accounts(client, world, db):
    from app.modules.auth.models import User
    from app.modules.support_access import service
    from app.modules.support_access.models import SupportAccessGrant

    gid = _request(client, world).json()["id"]
    _approve(client, world, gid)
    grant = db.query(SupportAccessGrant).get(gid)
    past = datetime.utcnow() - timedelta(seconds=1)
    grant.expires_at, grant.activated_at = past, past - timedelta(minutes=15)
    db.commit()
    out = service.run_sweep(db)
    assert gid in out["ended"]
    db.refresh(grant)
    assert grant.status == "expired" and grant.support_password_encrypted is None
    assert db.query(User).get(grant.support_user_id).is_active is False


def test_tenant_audit_tab_shows_named_attribution_and_the_chain_verifies(client, world, db):
    from app.modules.support_access import service

    gid = _request(client, world).json()["id"]
    _approve(client, world, gid)
    events = client.get(f"{ORG_BASE}/audit", headers=world.headers("TA")).json()
    assert {e["eventType"] for e in events} >= {"REQUESTED", "TENANT_APPROVED", "GRANTED"}
    assert all(e["requesterEmail"] == "sp@platform.example" for e in events if e["grantId"] == gid)
    assert client.get(f"{ORG_BASE}/audit", headers=world.headers("TB")).json() == []
    assert service.verify_audit_chain(db)


def test_support_audit_rows_are_append_only(db, world):
    from sqlalchemy.exc import DatabaseError

    from app.modules.support_access import service

    event = service.audit(db, "REQUESTED", None, actor=world.users["SP"], organization_id=world.orgs["A"].id)
    event.reason = "tampered"
    with pytest.raises(DatabaseError):
        db.commit()
    db.rollback()


def test_temporary_accounts_do_not_count_as_platform_users(client, world):
    gid = _request(client, world).json()["id"]
    _approve(client, world, gid)
    stats = client.get("/api/super-admin/dashboard/stats", headers=world.headers("SA")).json()
    assert stats["total_users"] == 8  # the 8 fixture identities, not the temporary login


def test_legacy_assisted_access_token_is_refused(client, world):
    from datetime import timedelta as _td

    from app.core.security import ASSISTED_ACCESS_TOKEN_TYPE, create_access_token

    token = create_access_token({"user_id": world.users["SA"].id, "role": "super_admin",
                                 "organization_id": world.orgs["A"].id, "assisted_access_session_id": 1},
                                expires_delta=_td(minutes=10), token_type=ASSISTED_ACCESS_TOKEN_TYPE)
    resp = client.get("/api/payroll/employees", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert "Support Access" in resp.json()["message"]


def test_support_intent_audit_fails_closed(client, world, monkeypatch):
    """Kept from the retired assisted-access design (G5 F-4): every request a
    temporary support user makes is recorded BEFORE the endpoint runs; if that
    record cannot be written the request is refused (503) and nothing runs."""
    from app.modules.support_access import service

    gid = _request(client, world).json()["id"]
    _approve(client, world, gid)
    creds = client.get(f"{SA_BASE}/{gid}/credentials", headers=world.headers("SP")).json()
    token = client.post("/api/auth/login", json={"email": creds["username"],
                                                 "password": creds["password"]}).json()["access_token"]
    real_audit = service.audit

    def failing(db, event_type, *a, **kw):
        if event_type == "API_CALL":
            raise RuntimeError("audit store down")
        return real_audit(db, event_type, *a, **kw)

    monkeypatch.setattr(service, "audit", failing)
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 503 and resp.json()["error"] == "SUPPORT_AUDIT_UNAVAILABLE"


def test_ticket_number_is_generated_and_reasons_are_offered(client, world):
    import re

    cfg = client.get(f"{SA_BASE}/config", headers=world.headers("SP")).json()
    assert "Payroll calculation discrepancy" in cfg["reasons"] and cfg["reasons"][-1] == "Other"
    r = client.post(f"{SA_BASE}/request", headers=world.headers("SP"), json={
        "organizationCode": "PRIVA", "reason": "Payroll calculation discrepancy", "minutes": 15,
        "scopeType": "diagnostics"})
    assert r.status_code == 200, r.text
    assert re.fullmatch(r"ZSA-\d{8}-[A-Z0-9]{6}", r.json()["ticketReference"])


def test_form_ticket_number_is_issued_shown_and_used_once(client, world):
    shown = client.get(f"{SA_BASE}/ticket-number", headers=world.headers("SP")).json()["ticketReference"]
    first = _request(client, world, ticketReference=shown).json()
    assert first["ticketReference"] == shown
    client.post(f"{SA_BASE}/{first['id']}/cancel", headers=world.headers("SP"))
    again = _request(client, world, ticketReference=shown).json()   # stale tab re-sends it
    assert again["ticketReference"] != shown
    assert client.get(f"{SA_BASE}/ticket-number", headers=world.headers("TA")).status_code == 403
