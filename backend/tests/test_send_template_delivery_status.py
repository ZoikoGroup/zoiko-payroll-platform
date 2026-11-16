"""
tests/test_send_template_delivery_status.py
-------------------------------------------
QA bug: "'Send template' in Employees does not send the email, and the
failure gives the sender no feedback". send_form reported "sent" whenever
the email helper returned True — including when no SMTP host is configured
(the message is only mock-logged) or outbound mail is blocked (local/test
mode). It also replaced real SMTP errors with a generic reason and left a
live token on sends nobody received, and built the link from raw
FRONTEND_URL instead of the shared email base URL.

Now each recipient gets the real outcome:
  * "sent"          - handed to an SMTP server;
  * "not_delivered" - mock-logged / blocked / caught by the local sandbox,
                       with the reason;
  * "failed"        - sending raised; the provider's error is the reason.
A send row whose email did not go out is retired (expired) immediately.
"""

import smtplib

import pytest

from app.core import outbound
from app.modules.payroll.forms import service as forms_service
from app.modules.payroll.models import FormSendStatus, PayrollEmployee, PayrollUpdateFormSend
from app.services import email_service


@pytest.fixture()
def employee(db, organization):
    emp = PayrollEmployee(organization_id=organization.id, employee_code="ST-1",
                          name="Priya Nair", email="priya@example.com")
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


@pytest.fixture()
def form(db, organization):
    return forms_service.create_form(db, organization.id, "Bank Details Update",
                                     [{"key": "bank_name", "label": "Bank name", "type": "text"}])


@pytest.fixture()
def smtp_configured(monkeypatch):
    monkeypatch.setattr(email_service, "_get_smtp_settings", lambda db=None: {
        "host": "smtp.example.com", "port": "587", "username": "u", "password": "p",
        "from_email": "payroll@example.com", "use_tls": "true",
    })


class _FakeSMTP:
    sent = []
    fail_with = None

    def __init__(self, host, port, timeout=None, **kw):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        if _FakeSMTP.fail_with:
            raise _FakeSMTP.fail_with

    def sendmail(self, frm, to, body):
        _FakeSMTP.sent.append(to)


@pytest.fixture()
def real_delivery(monkeypatch, smtp_configured):
    _FakeSMTP.sent = []
    _FakeSMTP.fail_with = None
    monkeypatch.setattr(outbound, "smtp_target", lambda smtp: smtp)
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    return _FakeSMTP


def _send_row(db, form, employee):
    return db.query(PayrollUpdateFormSend).filter_by(form_id=form.id, employee_id=employee.id).one()


def test_real_smtp_send_is_reported_sent(db, organization, form, employee, real_delivery):
    (res,) = forms_service.send_form(db, organization.id, form.id, [employee.id])["results"]
    assert res == {"employeeId": employee.id, "email": "priya@example.com", "status": "sent"}
    assert real_delivery.sent == ["priya@example.com"]
    assert _send_row(db, form, employee).status == FormSendStatus.SENT.value


def test_no_smtp_host_is_not_delivered_and_link_retired(db, organization, form, employee, monkeypatch):
    monkeypatch.setattr(email_service, "_get_smtp_settings", lambda db=None: {
        "host": "", "port": "587", "username": "", "password": "", "from_email": "x@example.com", "use_tls": "true",
    })
    (res,) = forms_service.send_form(db, organization.id, form.id, [employee.id])["results"]
    assert res["status"] == "not_delivered"
    assert "no SMTP host" in res["reason"]
    assert _send_row(db, form, employee).status == FormSendStatus.EXPIRED.value


def test_outbound_blocked_is_not_delivered(db, organization, form, employee, smtp_configured):
    # Under pytest outbound.smtp_target() blocks real delivery (test mode).
    (res,) = forms_service.send_form(db, organization.id, form.id, [employee.id])["results"]
    assert res["status"] == "not_delivered"
    assert "local/test mode" in res["reason"]


def test_local_mail_sandbox_is_not_delivered(db, organization, form, employee, smtp_configured, monkeypatch):
    monkeypatch.setattr(outbound, "smtp_target", lambda smtp: {**smtp, "host": "localhost", "port": "1025",
                                                               "sandbox": True})
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    (res,) = forms_service.send_form(db, organization.id, form.id, [employee.id])["results"]
    assert res["status"] == "not_delivered"
    assert "local mail sandbox" in res["reason"]


def test_smtp_error_is_failed_with_provider_reason(db, organization, form, employee, real_delivery, monkeypatch):
    from app.modules.communications import service as comms

    monkeypatch.setattr(comms, "_sleep", lambda s: None)
    real_delivery.fail_with = smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")
    (res,) = forms_service.send_form(db, organization.id, form.id, [employee.id])["results"]
    assert res["status"] == "failed"
    assert "SMTPAuthenticationError" in res["reason"] and "not accepted" in res["reason"]
    assert _send_row(db, form, employee).status == FormSendStatus.EXPIRED.value


def test_link_uses_shared_email_base_url(db, organization, form, employee, real_delivery, monkeypatch):
    links = []
    real = forms_service.send_update_form_invite_email

    def spy(email, name, form_name, link, *a, **kw):
        links.append(link)
        return real(email, name, form_name, link, *a, **kw)

    monkeypatch.setattr(forms_service, "send_update_form_invite_email", spy)
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://app.example.com/")
    forms_service.send_form(db, organization.id, form.id, [employee.id])
    token = _send_row(db, form, employee).token
    assert links == [f"https://app.example.com/forms/fill/{token}"]


def test_missing_email_still_fails_without_creating_a_send(db, organization, form):
    emp = PayrollEmployee(organization_id=organization.id, employee_code="ST-2", name="No Email")
    db.add(emp)
    db.commit()
    (res,) = forms_service.send_form(db, organization.id, form.id, [emp.id])["results"]
    assert res == {"employeeId": emp.id, "status": "failed", "reason": "Employee has no email on file."}
