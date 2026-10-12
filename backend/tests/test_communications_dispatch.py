"""
tests/test_communications_dispatch.py
-------------------------------------
Shared communications infrastructure (modules/communications):

  6.1  idempotency — a duplicate event for a representative operation in
       organizations, payroll and billing produces exactly one "sent"
       communication_events row plus one "skipped_duplicate" row;
  6.2  async — a real mutating endpoint (PATCH /api/organizations/{id}/status,
       i.e. deactivate an organization) returns its HTTP response BEFORE the
       email send runs (genuinely backgrounded, not a synchronous wrapper);
  6.3  retry — transient SMTP failure then success → attempt_count=2 /
       outcome="sent"; permanent failure → attempt_count=1 / outcome="failed",
       no retry. Exercised through the real send_approval_email + smtplib path
       (smtplib itself is faked), not a stub send function.

SMTP is globally neutralized by conftest's `_no_real_smtp`; the retry tests
re-point `_get_smtp_settings` at a fake host and fake `smtplib.SMTP` so the
real socket code path runs against a controllable double.
"""

import smtplib
import socket
import ssl
from types import SimpleNamespace

import pytest

from app.modules.communications import service as comms
from app.modules.communications.models import CommunicationEvent


def _rows(db, **filters):
    q = db.query(CommunicationEvent)
    for key, value in filters.items():
        q = q.filter(getattr(CommunicationEvent, key) == value)
    return q.order_by(CommunicationEvent.id).all()


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    sleeps = []
    monkeypatch.setattr(comms, "_sleep", lambda seconds: sleeps.append(seconds))
    return sleeps


# ── Key format ──────────────────────────────────────────────────────────────

def test_base_key_is_byte_identical_to_auths_historical_format():
    from app.modules.auth import service as auth_service

    assert auth_service._idempotency_key(7, "identity.password_changed", "A@Example.com", "IAM-008") == \
        "7|identity.password_changed|a@example.com|IAM-008|v2"


def test_related_object_and_missing_template_segments():
    key = comms.idempotency_key(3, "payroll.run_approved", "e@x.com", None, "run:42")
    assert key == "3|payroll.run_approved|e@x.com|-|v2|obj:run:42"


def test_repeatable_key_collapses_within_window_and_splits_across_windows():
    from datetime import datetime, timedelta

    t0 = datetime(2026, 9, 25, 10, 0, 0)
    same = comms.repeatable_idempotency_key(1, "e", "a@x.com", None, "org:1", {"is_active": False}, now=t0)
    also_same = comms.repeatable_idempotency_key(
        1, "e", "a@x.com", None, "org:1", {"is_active": False}, now=t0 + timedelta(minutes=5),
    )
    later = comms.repeatable_idempotency_key(
        1, "e", "a@x.com", None, "org:1", {"is_active": False}, now=t0 + timedelta(minutes=25),
    )
    other_change = comms.repeatable_idempotency_key(1, "e", "a@x.com", None, "org:1", {"is_active": True}, now=t0)
    assert same == also_same
    assert same != later
    assert same != other_change


def test_overlong_key_is_hashed_to_column_width():
    key = comms.idempotency_key(1, "e", "x" * 190 + "@example.com", None, "obj")
    assert len(key) <= comms.MAX_KEY_LENGTH


# ── Dispatch core ───────────────────────────────────────────────────────────

def test_dispatch_audits_before_send_and_records_sent(db):
    seen_outcomes = []

    def send(email, db=None):
        # The pending row must already exist when the send runs (audit-first).
        seen_outcomes.extend(r.outcome for r in _rows(db, recipient_email=email))
        return True

    assert comms.dispatch_email("payroll", "t.event", None, "a@x.com", "k1", send, "a@x.com", db=db) is True
    assert seen_outcomes == ["pending"]
    (row,) = _rows(db)
    assert (row.outcome, row.attempt_count, row.module, row.provider_response) == ("sent", 1, "payroll", None)


def test_dispatch_duplicate_key_sends_once(db):
    calls = []

    def send(db=None):
        calls.append(1)
        return True

    assert comms.dispatch_email("billing", "t.event", None, "a@x.com", "dup", send, db=db) is True
    assert comms.dispatch_email("billing", "t.event", None, "a@x.com", "dup", send, db=db) is False
    assert len(calls) == 1
    outcomes = [r.outcome for r in _rows(db)]
    assert outcomes == ["sent", "skipped_duplicate"]
    assert _rows(db, outcome="skipped_duplicate")[0].attempt_count == 0  # never attempted


def test_dispatch_false_return_is_permanent_failure(db, _no_backoff):
    assert comms.dispatch_email("payroll", "t.event", None, "a@x.com", "k", lambda db=None: False, db=db) is False
    (row,) = _rows(db)
    assert (row.outcome, row.attempt_count) == ("failed", 1)
    assert "returned False" in row.provider_response
    assert _no_backoff == []


@pytest.mark.parametrize("exc,transient", [
    (ConnectionRefusedError(111, "refused"), True),
    (socket.timeout("timed out"), True),
    (smtplib.SMTPServerDisconnected("gone"), True),
    (smtplib.SMTPConnectError(421, b"busy"), True),
    (smtplib.SMTPSenderRefused(451, b"try later", "from@x.com"), True),
    (smtplib.SMTPRecipientsRefused({"a@x.com": (450, b"mailbox busy")}), True),
    (smtplib.SMTPRecipientsRefused({"a@x.com": (550, b"no such user")}), False),
    (smtplib.SMTPAuthenticationError(535, b"bad credentials"), False),
    (smtplib.SMTPDataError(554, b"rejected"), False),
    (ssl.SSLError("handshake failure"), False),
    (ValueError("template bug"), False),
])
def test_transient_classification(exc, transient):
    assert comms.is_transient_send_error(exc) is transient


# ── 6.3 Retry through the real send_approval_email → smtplib path ──────────

class _FakeSMTP:
    """Stands in for smtplib.SMTP. `plan` is a shared list of outcomes, one
    consumed per connection: an exception instance to raise, or "ok"."""

    plan = []
    delivered = []

    def __init__(self, host, port, timeout=None):
        outcome = _FakeSMTP.plan.pop(0)
        self._login_error = None
        if isinstance(outcome, smtplib.SMTPAuthenticationError):
            self._login_error = outcome  # fails at login, like a real bad password
        elif isinstance(outcome, BaseException):
            raise outcome

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        pass

    def login(self, username, password):
        if self._login_error:
            raise self._login_error

    def sendmail(self, from_addr, to_addr, message):
        _FakeSMTP.delivered.append(to_addr)


@pytest.fixture()
def real_smtp_path(monkeypatch):
    from app.services import email_service

    monkeypatch.setattr(email_service, "_get_smtp_settings", lambda db=None: {
        "host": "smtp.test.invalid", "port": 587, "username": "u", "password": "p",
        "from_email": "noreply@test.invalid", "use_tls": "true",
    })
    monkeypatch.setattr(email_service.smtplib, "SMTP", _FakeSMTP)
    _FakeSMTP.plan = []
    _FakeSMTP.delivered = []
    return _FakeSMTP


def _dispatch_report(db, key):
    from app.services.email_service import send_report_generated_email

    return comms.dispatch_email(
        "payroll", "payroll.report_generated", None, "admin@org.test", key,
        send_report_generated_email, "admin@org.test", "Payroll Register", "Sep 2026", 99,
        db=db,
    )


def test_transient_failure_then_success_retries(db, real_smtp_path, _no_backoff):
    real_smtp_path.plan = [ConnectionRefusedError(111, "Connection refused"), "ok"]
    assert _dispatch_report(db, "retry-ok") is True
    (row,) = _rows(db)
    assert (row.outcome, row.attempt_count, row.provider_response) == ("sent", 2, None)
    assert real_smtp_path.delivered == ["admin@org.test"]
    assert _no_backoff == [comms.RETRY_BACKOFF_SECONDS[0]]


def test_permanent_failure_is_not_retried(db, real_smtp_path, _no_backoff):
    real_smtp_path.plan = [smtplib.SMTPAuthenticationError(535, b"5.7.8 authentication failed"), "ok"]
    assert _dispatch_report(db, "perm") is False
    (row,) = _rows(db)
    assert (row.outcome, row.attempt_count) == ("failed", 1)
    assert row.provider_response.startswith("SMTPAuthenticationError")
    assert real_smtp_path.delivered == []
    assert _no_backoff == []
    assert len(real_smtp_path.plan) == 1  # the second connection was never attempted


def test_transient_failures_exhaust_attempts(db, real_smtp_path, _no_backoff):
    real_smtp_path.plan = [socket.timeout("timed out")] * comms.MAX_ATTEMPTS
    assert _dispatch_report(db, "exhaust") is False
    (row,) = _rows(db)
    assert (row.outcome, row.attempt_count) == ("failed", comms.MAX_ATTEMPTS)
    assert "timed out" in row.provider_response
    assert _no_backoff == list(comms.RETRY_BACKOFF_SECONDS)


def test_direct_callers_keep_bool_contract(real_smtp_path):
    """Outside dispatch_email, send_approval_email still swallows the error."""
    from app.services.email_service import send_report_generated_email

    real_smtp_path.plan = [ConnectionRefusedError(111, "Connection refused")]
    assert send_report_generated_email("admin@org.test", "R", "P", 1) is False


# ── 6.1 Idempotency per module (real call sites) ───────────────────────────

class _Actor:
    id = 1
    email = "sa@zoiko.dev"


def test_organizations_duplicate_deactivate_sends_once(db, organization, monkeypatch):
    from app.modules.organizations import router as org_router
    from app.services import email_service

    sent = []
    real = email_service.send_organization_suspended_email
    monkeypatch.setattr(
        email_service, "send_organization_suspended_email",
        lambda *a, **kw: sent.append(a[0]) or real(*a, **kw),
    )
    organization.email = "admin@testorg.test"
    db.commit()

    org_router.update_organization_status(organization.id, False, current_user=_Actor(), db=db)
    org_router.update_organization_status(organization.id, False, current_user=_Actor(), db=db)  # retried request

    assert sent == ["admin@testorg.test"]
    rows = _rows(db, event_type="organizations.status_changed")
    assert [r.outcome for r in rows] == ["sent", "skipped_duplicate"]
    assert {r.module for r in rows} == {"organizations"}
    assert rows[0].organization_id == organization.id and rows[0].actor_user_id == _Actor.id


def test_organizations_reactivate_after_suspend_is_a_distinct_notice(db, organization):
    from app.modules.organizations import router as org_router

    organization.email = "admin@testorg.test"
    db.commit()
    org_router.update_organization_status(organization.id, False, current_user=_Actor(), db=db)
    org_router.update_organization_status(organization.id, True, current_user=_Actor(), db=db)
    rows = _rows(db, event_type="organizations.status_changed")
    assert [r.outcome for r in rows] == ["sent", "sent"]


def test_payroll_duplicate_employee_created_event_sends_once(db, organization, monkeypatch):
    from app.modules.payroll import service as payroll_service
    from app.services import email_service

    sent = []
    monkeypatch.setattr(email_service, "send_employee_created_email", lambda *a, **kw: sent.append(a[0]) or True)
    employee = SimpleNamespace(
        id=501, email="jane@testorg.test", name="Jane", employee_code="EMP-501",
        department="Ops", designation="Analyst", date_of_joining=None,
    )
    payroll_service._notify_employee_created(db, employee, organization.id)
    payroll_service._notify_employee_created(db, employee, organization.id)

    assert sent == ["jane@testorg.test"]
    rows = _rows(db, event_type="payroll.employee_created")
    assert [r.outcome for r in rows] == ["sent", "skipped_duplicate"]
    assert rows[0].module == "payroll"
    assert "obj:employee:501" in rows[0].idempotency_key


def test_billing_duplicate_override_granted_sends_once(db, organization, monkeypatch):
    from app.modules.billing import entitlements
    from app.services import email_service

    organization.email = "billing@testorg.test"
    db.commit()
    sent = []
    monkeypatch.setattr(
        email_service, "send_entitlement_override_granted_email", lambda *a, **kw: sent.append(a[0]) or True,
    )
    override = SimpleNamespace(
        id=77, feature_key="assist_seats", limit_value=10, reason="pilot", expires_at=None, granted_by_user_id=1,
    )
    entitlements._notify_entitlement_override_granted(db, override, organization.id)
    entitlements._notify_entitlement_override_granted(db, override, organization.id)

    assert sent == ["billing@testorg.test"]
    rows = _rows(db, event_type="billing.entitlement_override_granted")
    assert [r.outcome for r in rows] == ["sent", "skipped_duplicate"]
    assert rows[0].module == "billing" and rows[0].actor_user_id == 1


def test_auth_sends_are_mirrored_into_communication_events(db, organization):
    from app.core.security import hash_password
    from app.modules.auth import service as auth_service
    from app.modules.auth.models import User, UserRole

    user = User(
        email="owner@testorg.test", hashed_password=hash_password("OldPass1!"), role=UserRole.ORG_ADMIN,
        organization_id=organization.id, first_name="Owner", last_name="One", is_active=True,
    )
    db.add(user)
    db.commit()
    auth_service.change_password(db, user.id, "OldPass1!", "NewPass2!")

    (auth_row,) = db.query(auth_service.AuthEmailEvent).all()
    (comm_row,) = _rows(db, module="auth")
    assert auth_row.outcome == comm_row.outcome == "sent"
    assert auth_row.idempotency_key == comm_row.idempotency_key
    assert comm_row.template_id == "IAM-008"


# ── 6.2 Async: the HTTP response is sent before the email ──────────────────

def test_deactivate_organization_response_precedes_email_send(db, organization, monkeypatch):
    from fastapi.testclient import TestClient

    from app.core.dependencies import get_current_super_admin
    from app.database import get_db
    from app.main import app
    from app.services import email_service

    organization.email = "admin@testorg.test"
    db.commit()

    timeline = []
    monkeypatch.setattr(
        email_service, "send_organization_suspended_email",
        lambda *a, **kw: timeline.append("email_sent") or True,
    )

    async def recording_app(scope, receive, send):
        async def _send(message):
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                timeline.append("response_sent")
        await app(scope, receive, _send)

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_super_admin] = lambda: _Actor()
    try:
        response = TestClient(recording_app).patch(f"/api/organizations/{organization.id}/status?is_active=false")
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_super_admin, None)

    assert response.status_code == 200, response.text
    assert timeline == ["response_sent", "email_sent"]
    db.expire_all()
    (row,) = _rows(db, event_type="organizations.status_changed")
    assert row.outcome == "sent"


def test_queue_email_runs_inline_without_a_request(db):
    calls = []
    result = comms.queue_email(
        "payroll", "t.inline", None, "a@x.com", "inline-key", lambda db=None: calls.append(1) or True, db=db,
    )
    assert result is True and calls == [1]
