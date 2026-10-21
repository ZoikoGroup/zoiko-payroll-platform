"""F-10: outbound delivery fails closed in test and local modes.

A local scratch backend reads backend/.env (real SMTP credentials) and once
delivered real break-glass notices. These tests pin the guard at the send
point (app/core/outbound.py + email_service.send_approval_email) and the
run-wide SMTP tripwire in conftest.py. App modules are imported lazily
(collection-order DB-binding hazard)."""
import ast
import logging
import pathlib
import sys

import pytest

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
REAL = {"host": "smtp.mailhost.example.com", "port": "465", "username": "real-user", "password": "real-secret",
        "from_email": "no-reply@payroll.zoiko.example", "use_tls": "true"}


def _attempts() -> list:
    mod = next(m for m in list(sys.modules.values()) if hasattr(m, "REAL_DELIVERY_ATTEMPTS") and hasattr(m, "_SmtpTripwire"))
    return mod.REAL_DELIVERY_ATTEMPTS


class _Recorder:
    calls: list = []

    def __init__(self, host="", port=0, *args, **kwargs):
        self.entry = {"host": host, "port": port, "login": False, "starttls": False, "sent_to": None}
        _Recorder.calls.append(self.entry)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, **kwargs):
        self.entry["starttls"] = True

    def login(self, user, password):
        self.entry["login"] = True

    def sendmail(self, from_addr, to_addr, message):
        self.entry["sent_to"] = to_addr


@pytest.fixture()
def recorder(monkeypatch):
    import smtplib
    from app.services import email_service

    _Recorder.calls = []
    monkeypatch.setattr(smtplib, "SMTP", _Recorder)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _Recorder)
    monkeypatch.setattr(email_service, "_get_smtp_settings", lambda db=None: dict(REAL))
    return _Recorder.calls


def _send():
    from app.services import email_service

    return email_service.send_approval_email("someone@recipient.example.com", "guard_test", {"subject": "F-10 guard"},
                                             template_body="<p>guard</p>")


@pytest.mark.parametrize("env_name,debug,under_pytest,expected", [
    ("", True, False, "local"),            # local backend/.env today: DEBUG=true, no ENVIRONMENT
    ("development", False, False, "local"),
    ("dev", False, False, "local"),
    ("local", False, False, "local"),
    ("test", False, False, "test"),
    ("ci", False, False, "test"),
    ("production", True, True, "test"),    # a pytest run is always test mode
    ("production", True, False, "production"),
    ("staging", False, False, "production"),
    ("", False, False, "production"),      # .env.production.example: DEBUG=false, ENVIRONMENT unset
])
def test_delivery_mode_classification(env_name, debug, under_pytest, expected):
    from app.core import outbound

    assert outbound.classify(env_name, debug, under_pytest) == expected


def test_a_test_run_is_test_mode_and_blocks_real_delivery():
    from app.core import outbound

    assert outbound.delivery_mode() == outbound.TEST
    assert outbound.real_delivery_allowed("email") is False
    assert outbound.smtp_target(dict(REAL)) is None


def test_real_looking_smtp_settings_are_never_contacted_in_test_or_local_mode(recorder, caplog, monkeypatch,
                                                                              raw_log_messages):
    from app.core import outbound

    for mode in (outbound.TEST, outbound.LOCAL):
        monkeypatch.setattr(outbound, "delivery_mode", lambda m=mode: m)
        with caplog.at_level(logging.WARNING, logger="zoiko_payroll"):
            assert _send() is True
    assert recorder == []
    assert sum("[outbound] BLOCKED email to someone@recipient.example.com" in r.getMessage() for r in caplog.records) == 2


def test_sandbox_opt_in_only_reaches_the_sandbox_never_the_configured_server(recorder, monkeypatch):
    from app.config import settings
    from app.core import outbound

    monkeypatch.setattr(outbound, "delivery_mode", lambda: outbound.LOCAL)
    monkeypatch.setattr(settings, "LOCAL_MAIL_SANDBOX_ENABLED", True)
    monkeypatch.setattr(settings, "LOCAL_MAIL_SANDBOX_HOST", "127.0.0.1")
    monkeypatch.setattr(settings, "LOCAL_MAIL_SANDBOX_PORT", 1025)
    assert _send() is True
    assert recorder == [{"host": "127.0.0.1", "port": 1025, "login": False, "starttls": False,
                         "sent_to": "someone@recipient.example.com"}]


def test_production_like_mode_uses_the_configured_server(recorder, monkeypatch):
    from app.core import outbound

    monkeypatch.setattr(outbound, "delivery_mode", lambda: outbound.PRODUCTION_LIKE)
    assert _send() is True
    assert [(c["host"], c["port"], c["login"]) for c in recorder] == [("smtp.mailhost.example.com", 465, True)]


def test_the_run_wide_tripwire_fails_an_unfaked_smtp_attempt():
    import smtplib
    from tests.conftest import RealDeliveryAttempted

    before = len(_attempts())
    for cls in (smtplib.SMTP, smtplib.SMTP_SSL):
        with pytest.raises(RealDeliveryAttempted):
            cls("smtp.mailhost.example.com", 465)
    attempts = _attempts()
    assert len(attempts) == before + 2
    del attempts[before:]          # this test's own deliberate attempts must not fail the session


def _calls(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            yield node.func.value.id, node.func.attr


def test_only_the_guarded_chokepoint_opens_an_smtp_connection_and_no_sms_or_webhook_client_exists():
    smtp_openers, clients = [], []
    for path in APP.rglob("*.py"):
        src = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(src)
        rel = path.relative_to(APP).as_posix()
        if any(mod == "smtplib" and attr in ("SMTP", "SMTP_SSL") for mod, attr in _calls(tree)):
            smtp_openers.append(rel)
            assert "outbound.smtp_target(" in src, f"{rel} opens SMTP without the F-10 guard"
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            for n in names:
                if n.split(".")[0] in {"twilio", "sendgrid", "vonage", "plivo", "requests", "httpx", "aiohttp", "aiosmtplib"}:
                    clients.append(f"{rel}: {n}")
    assert smtp_openers == ["services/email_service.py"]
    # A new SMS / webhook / HTTP sender must route through app/core/outbound.py first; update this test with it.
    assert clients == []
