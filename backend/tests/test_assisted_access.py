"""
tests/test_assisted_access.py
-----------------------------
Privileged (assisted) access into a tenant — consent by default, emergency
break-glass with a second Super Admin (launch readiness G5, findings F-3 /
F-7). Every user here is TEST-ONLY data.

App modules are imported inside the tests (never at module scope) so this file
cannot bind the app's global engine during collection.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest


def _user(db, email, role, org_id=None):
    from app.modules.auth.models import User

    u = User(email=email, hashed_password="x", role=role, organization_id=org_id, first_name="T", last_name="User",
             is_active=True)
    db.add(u)
    db.commit()
    return u


@pytest.fixture()
def people(db, organization):
    from app.modules.auth.models import UserRole
    from app.modules.organizations.models import Organization

    other = Organization(organization_name="Other Org", organization_code="OTHERORG")
    db.add(other)
    db.commit()
    return SimpleNamespace(
        org=organization, other=other,
        sa1=_user(db, "sa1@zoikotest.example.com", UserRole.SUPER_ADMIN), sa2=_user(db, "sa2@zoikotest.example.com", UserRole.SUPER_ADMIN),
        admin=_user(db, "admin@zoikotest.example.com", UserRole.ORG_ADMIN, organization.id),
        other_admin=_user(db, "other@zoikotest.example.com", UserRole.ORG_ADMIN, other.id),
        payroll=_user(db, "payroll@zoikotest.example.com", UserRole.PAYROLL_ADMIN, organization.id),
    )


def _events(db, session_id):
    from app.modules.assisted_access.models import AssistedAccessAuditEvent

    return [e.event_type for e in db.query(AssistedAccessAuditEvent)
            .filter(AssistedAccessAuditEvent.assisted_access_session_id == session_id)
            .order_by(AssistedAccessAuditEvent.id)]


def _resolve(db, token):
    from app.core.dependencies import _resolve_assisted_principal

    return _resolve_assisted_principal(token, db)


def test_consent_is_required_before_any_token_and_refusals_are_audited(db, people):
    from app.core.exceptions import UnauthorizedException
    from app.modules.assisted_access import service as svc
    from app.modules.assisted_access.models import AssistedAccessAuditEvent

    with pytest.raises(ValueError, match="reason"):
        svc.request_assisted_access(db, organization_id=people.org.id, requested_by=people.sa1, reason="  ")
    s = svc.request_assisted_access(db, organization_id=people.org.id, requested_by=people.sa1, reason="TEST: ticket 42")
    assert s.approval_status == "PENDING" and s.access_mode == "CONSENT" and s.activated_at is None
    assert svc.get_active_sessions_for_org(db, people.org.id) == []                 # a request is not access
    with pytest.raises(svc.AssistedAccessRefused, match="PENDING"):
        svc.activate_assisted_access(db, s, requested_by=people.sa1)                # no approval yet
    for wrong in (people.sa2, people.other_admin, people.payroll,
                  SimpleNamespace(id=people.sa1.id, role="assisted_access", organization_id=people.org.id, is_active=True)):
        with pytest.raises(svc.AssistedAccessRefused, match="organisation admin"):
            svc.approve_assisted_access(db, s, approver=wrong)
    svc.approve_assisted_access(db, s, approver=people.admin, decision_reason="TEST ok")
    assert s.approval_status == "APPROVED" and s.approved_by_user_id == people.admin.id
    with pytest.raises(svc.AssistedAccessRefused, match="requested access"):
        svc.activate_assisted_access(db, s, requested_by=people.sa2)                # only the requester
    s, token = svc.activate_assisted_access(db, s, requested_by=people.sa1)
    principal = _resolve(db, token)
    assert principal.organization_id == people.org.id and principal.id == people.sa1.id
    assert svc.get_active_sessions_for_org(db, people.org.id)[0].id == s.id
    ev = _events(db, s.id)
    assert ev[0] == "ASSISTED_ACCESS_REQUESTED" and ev.count("ASSISTED_ACCESS_REFUSED") == 6
    assert ev[-3:] == ["ASSISTED_ACCESS_APPROVED", "ASSISTED_ACCESS_REFUSED", "ASSISTED_ACCESS_STARTED"]
    refused = (db.query(AssistedAccessAuditEvent).filter(AssistedAccessAuditEvent.event_type == "ASSISTED_ACCESS_REFUSED")
               .order_by(AssistedAccessAuditEvent.id).all())
    assert {r.payload["attempted"] for r in refused} == {"activate", "approve"}
    svc.end_assisted_access(db, s, actor_user_id=people.sa1.id)
    with pytest.raises(UnauthorizedException):
        _resolve(db, token)


def test_a_pending_or_rejected_request_never_yields_a_usable_token(db, people):
    from app.core.exceptions import UnauthorizedException
    from app.core.security import ASSISTED_ACCESS_TOKEN_TYPE, create_access_token
    from app.modules.assisted_access import service as svc

    s = svc.request_assisted_access(db, organization_id=people.org.id, requested_by=people.sa1, reason="TEST")
    forged = create_access_token({"sub": people.sa1.email, "user_id": people.sa1.id, "role": "super_admin",
                                  "organization_id": people.org.id, "assisted_access_session_id": s.id},
                                 expires_delta=timedelta(minutes=5), token_type=ASSISTED_ACCESS_TOKEN_TYPE)
    with pytest.raises(UnauthorizedException, match="not been approved"):
        _resolve(db, forged)
    with pytest.raises(ValueError, match="reason"):
        svc.reject_assisted_access(db, s, actor=people.admin, reason="")
    svc.reject_assisted_access(db, s, actor=people.admin, reason="TEST: not needed")
    assert s.approval_status == "REJECTED" and s.ended_reason == "REJECTED"
    with pytest.raises(svc.AssistedAccessRefused):
        svc.approve_assisted_access(db, s, approver=people.admin)
    with pytest.raises(UnauthorizedException):
        _resolve(db, forged)


def test_an_unapproved_request_lapses_after_the_approval_window(db, people):
    from app.modules.assisted_access import service as svc

    s = svc.request_assisted_access(db, organization_id=people.org.id, requested_by=people.sa1, reason="TEST")
    s.request_expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    with pytest.raises(svc.AssistedAccessRefused, match="approval window"):
        svc.approve_assisted_access(db, s, approver=people.admin)
    assert s.approval_status == "EXPIRED" and "ASSISTED_ACCESS_REQUEST_EXPIRED" in _events(db, s.id)
    t = svc.request_assisted_access(db, organization_id=people.org.id, requested_by=people.sa1, reason="TEST 2")
    svc.approve_assisted_access(db, t, approver=people.admin)
    t.request_expires_at = datetime.utcnow() - timedelta(minutes=1)                 # approved, never activated
    db.commit()
    result = svc.run_expiry_sweep(db)
    db.refresh(t)
    assert t.id in result["requestsExpired"] and t.approval_status == "EXPIRED"
    with pytest.raises(svc.AssistedAccessRefused):
        svc.activate_assisted_access(db, t, requested_by=people.sa1)


def test_break_glass_needs_a_second_super_admin_is_time_limited_and_notifies_the_tenant(db, people, monkeypatch):
    from app.config import settings
    from app.modules.assisted_access import service as svc
    from app.modules.communications import service as comms

    sent = []
    monkeypatch.setattr(comms, "dispatch_email", lambda *a, **k: sent.append((a[3], k.get("recipient_user_id"))) or True)
    with pytest.raises(ValueError, match="reason"):
        svc.request_assisted_access(db, organization_id=people.org.id, requested_by=people.sa1, reason="", mode="BREAK_GLASS")
    s = svc.request_assisted_access(db, organization_id=people.org.id, requested_by=people.sa1,
                                    reason="TEST: payroll run stuck, P1", mode="BREAK_GLASS", duration_minutes=999)
    assert s.requested_minutes == settings.ASSISTED_ACCESS_BREAK_GLASS_MINUTES == 60     # capped, default 60
    with pytest.raises(svc.AssistedAccessRefused, match="requester"):
        svc.approve_assisted_access(db, s, approver=people.sa1)                    # cannot self-approve
    with pytest.raises(svc.AssistedAccessRefused, match="second Super Admin"):
        svc.approve_assisted_access(db, s, approver=people.admin)                  # tenant cannot approve break-glass
    assert sent == [] and s.activated_at is None
    svc.approve_assisted_access(db, s, approver=people.sa2, decision_reason="TEST: confirmed P1")
    assert s.approval_status == "APPROVED" and s.activated_at is not None
    assert s.expires_at - s.started_at == timedelta(minutes=60)
    assert sent == [("admin@zoikotest.example.com", people.admin.id)] and s.tenant_notified_at is not None
    ev = _events(db, s.id)
    assert ev.count("ASSISTED_ACCESS_REFUSED") == 2
    assert ev[-3:] == ["ASSISTED_ACCESS_APPROVED", "ASSISTED_ACCESS_STARTED", "ASSISTED_ACCESS_TENANT_NOTIFIED"]
    assert _resolve(db, s._issued_token).organization_id == people.org.id


def test_sessions_created_before_consent_existed_keep_working(db, people):
    from app.core.security import ASSISTED_ACCESS_TOKEN_TYPE, create_access_token
    from app.modules.assisted_access import service as svc
    from app.modules.assisted_access.models import AssistedAccessSession

    now = datetime.utcnow()
    legacy = AssistedAccessSession(organization_id=people.org.id, requested_by_user_id=people.sa1.id, reason="legacy",
                                   started_at=now, expires_at=now + timedelta(minutes=30))
    db.add(legacy)
    db.commit()
    assert legacy.approval_status == "APPROVED" and legacy.access_mode == "CONSENT"
    token = create_access_token({"sub": people.sa1.email, "user_id": people.sa1.id, "role": "super_admin",
                                "organization_id": people.org.id, "assisted_access_session_id": legacy.id},
                               expires_delta=timedelta(minutes=30), token_type=ASSISTED_ACCESS_TOKEN_TYPE)
    assert _resolve(db, token).organization_id == people.org.id
    assert [s.id for s in svc.get_active_sessions_for_org(db, people.org.id)] == [legacy.id]


def test_org_admins_and_other_tenants_cannot_drive_the_privileged_endpoints_over_http(db, people):
    from fastapi.testclient import TestClient

    from app.core.dependencies import get_current_org_scoped_principal, get_current_user
    from app.database import get_db
    from app.main import app

    def client(principal):
        app.dependency_overrides.update({get_db: lambda: db, get_current_user: lambda: principal,
                                         get_current_org_scoped_principal: lambda: principal})
        return TestClient(app)

    saved = dict(app.dependency_overrides)
    try:
        c = client(people.admin)
        assert c.post(f"/api/super-admin/assisted-access/{people.org.id}/request",
                      json={"reason": "x"}).status_code == 403                     # org admin cannot request
        assert c.post(f"/api/super-admin/assisted-access/{people.org.id}/start", json={"reason": "x"}).status_code == 403
        c = client(people.sa1)
        r = c.post(f"/api/super-admin/assisted-access/{people.org.id}/request", json={"reason": "TEST"})
        sid = r.json()["session_id"]
        assert r.status_code == 200 and "token" not in r.json() and r.json()["approval_status"] == "PENDING"
        assert c.post(f"/api/super-admin/assisted-access/{sid}/activate").status_code == 403
        assert c.post(f"/api/organization-admin/assisted-access/requests/{sid}/approve", json={}).status_code in (403, 404)
        c = client(people.other_admin)                                             # another tenant's admin
        assert c.post(f"/api/organization-admin/assisted-access/requests/{sid}/approve", json={}).status_code == 404
        c = client(people.admin)
        assert [x["session_id"] for x in c.get("/api/organization-admin/assisted-access/requests").json()["requests"]] == [sid]
        assert c.post(f"/api/organization-admin/assisted-access/requests/{sid}/approve", json={}).status_code == 200
        assert c.get("/api/organization-admin/assisted-access/status").json()["active"] is False   # not activated yet
        c = client(people.sa1)
        r = c.post(f"/api/super-admin/assisted-access/{sid}/activate")
        assert r.status_code == 200 and r.json()["token"]
        c = client(people.admin)
        assert c.get("/api/organization-admin/assisted-access/status").json()["active"] is True
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)



@pytest.mark.parametrize("failure", ["not_delivered", "raises", "no_org_admin"])
def test_break_glass_notification_failure_is_audited_alerted_and_keeps_the_session(db, people, monkeypatch, failure):
    """If the tenant cannot be notified, the break-glass session stays active and auditable, a
    TENANT_NOTIFICATION_FAILED event records why, tenant_notified_at stays empty, and the Super Admin
    Alerts feed shows a high-severity security alert. TEST-ONLY users."""
    from app.modules.assisted_access import service as svc
    from app.modules.communications import service as comms
    from app.modules.super_admin import command_center_router

    def boom(*a, **k):
        raise RuntimeError("SMTP down (TEST)")

    monkeypatch.setattr(comms, "dispatch_email", boom if failure == "raises" else (lambda *a, **k: False))
    if failure == "no_org_admin":
        people.admin.is_active = False
        db.commit()
    s = svc.request_assisted_access(db, organization_id=people.org.id, requested_by=people.sa1,
                                    reason="TEST-ONLY: P1", mode="BREAK_GLASS")
    svc.approve_assisted_access(db, s, approver=people.sa2)
    assert s.activated_at is not None and s.tenant_notified_at is None
    assert _resolve(db, s._issued_token).organization_id == people.org.id                 # still usable and audited
    ev = _events(db, s.id)
    assert "ASSISTED_ACCESS_TENANT_NOTIFICATION_FAILED" in ev and "ASSISTED_ACCESS_TENANT_NOTIFIED" not in ev
    alerts = command_center_router.list_alerts(db=db, _admin=people.sa1)["alerts"]
    mine = [a for a in alerts if a["category"] == "security" and f"#{s.id}" in a["message"]]
    assert len(mine) == 1 and mine[0]["severity"] == "high" and "notification FAILED" in mine[0]["message"]


def test_a_delivered_break_glass_notice_raises_no_alert(db, people, monkeypatch):
    from app.modules.assisted_access import service as svc
    from app.modules.communications import service as comms
    from app.modules.super_admin import command_center_router

    monkeypatch.setattr(comms, "dispatch_email", lambda *a, **k: True)
    s = svc.request_assisted_access(db, organization_id=people.org.id, requested_by=people.sa1,
                                    reason="TEST-ONLY", mode="BREAK_GLASS")
    svc.approve_assisted_access(db, s, approver=people.sa2)
    assert s.tenant_notified_at is not None
    alerts = command_center_router.list_alerts(db=db, _admin=people.sa1)["alerts"]
    assert not [a for a in alerts if a["category"] == "security"]
