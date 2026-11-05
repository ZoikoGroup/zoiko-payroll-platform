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
    assert clients == ["core/google_oauth.py: httpx"]
    oauth_boundary = (APP / "core" / "google_oauth.py").read_text(encoding="utf-8")
    assert "https://oauth2.googleapis.com/token" in oauth_boundary
    assert "https://www.googleapis.com/oauth2/v2/userinfo" in oauth_boundary
    assert "follow_redirects=False" in oauth_boundary
    assert "trust_env=False" in oauth_boundary
    assert "httpx.Timeout(20.0)" in oauth_boundary


def test_google_oauth_outbound_boundary_rejects_non_google_endpoints(monkeypatch):
    from app.core import google_oauth

    requests = []

    class Client:
        def __init__(self, **kwargs):
            requests.append(("client", kwargs))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, data):
            requests.append(("post", url, data))
            return object()

        def get(self, url, headers):
            requests.append(("get", url, headers))
            return object()

    monkeypatch.setattr(google_oauth.httpx, "Client", Client)
    google_oauth.exchange_code(google_oauth.TOKEN_ENDPOINT, {"code": "code"})
    google_oauth.fetch_userinfo(google_oauth.USERINFO_ENDPOINT, "access-token")
    client_options = requests[0][1]
    assert client_options["timeout"].connect == 20.0
    assert client_options["timeout"].read == 20.0
    assert client_options["follow_redirects"] is False
    assert client_options["trust_env"] is False
    assert requests[1][1] == google_oauth.TOKEN_ENDPOINT
    assert requests[3][1] == google_oauth.USERINFO_ENDPOINT

    with pytest.raises(ValueError, match="not allowlisted"):
        google_oauth.exchange_code("https://attacker.example/token", {"code": "code"})
    with pytest.raises(ValueError, match="not allowlisted"):
        google_oauth.fetch_userinfo("https://attacker.example/userinfo", "access-token")
