"""Mexico Phase 3 — credential references (MX-035, Q9): only gcp-sm://
references; key material refused and never echoed; the PUBLIC .cer is
capped at 16 KB, DER/PEM only (screened before parsing), processed in
memory and never written to disk; certificate bytes are never stored;
audit rows and logs hold no raw reference / RFC / Registro Patronal.
Certificates are generated in memory at test time — none is committed."""

import base64
import json
import logging

import pytest

from tests._mx_employer_helpers import (
    GCP_REF, ORG_BASE, enable_mx_onboarding, http, make_org, new_employer, new_registration, principal,
    self_signed_cert,
)


@pytest.fixture(autouse=True)
def _mx_onboarding(monkeypatch):
    enable_mx_onboarding(monkeypatch)


def _svc():
    from app.modules.payroll import mexico_employer_service

    return mexico_employer_service


def _cred(db, org_id, emp_id, kind="CSD", ref=GCP_REF, reg=None):
    return _svc().create_credential(db, org_id, emp_id, {"kind": kind, "secret_ref": ref,
                                                          "imss_registration_id": reg}, 701)


@pytest.mark.parametrize("ref", [
    "gcp-sm://projects/zoiko-test-project/secrets/mx-csd-key",
    "gcp-sm://projects/123456789/secrets/mx_pac/versions/latest",
])
def test_gcp_secret_manager_references_are_accepted(ref):
    assert _svc().validate_secret_ref(ref) == ref


@pytest.mark.parametrize("ref", [
    "vault://secret/mx/csd", "aws-sm://mx/csd", "azure-kv://mx/csd",          # dropped schemes (Q9)
    "gcp-sm://not-a-valid/path", "gcp-sm://projects/x/secrets/y",              # bad shape
])
def test_other_schemes_and_shapes_are_refused(ref):
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException, match="secretRef refused"):
        _svc().validate_secret_ref(ref)


SECRET_LIKE = [
    "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n-----END PRIVATE KEY-----",  # privacy-scan: allow — SYNTHETIC marker; the test proves it is refused
    "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7VJTUt9Us8cKjMzEfYyjiWA4R4",
    "my pac password 123",
    "gcp-sm://projects/zoiko-test-project/secrets/PRIVATE KEY",
]


@pytest.mark.parametrize("secret", SECRET_LIKE)
def test_key_material_is_refused_and_never_echoed(db, secret, caplog):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.models import PayrollMxCredentialRef, TaxConfigurationAudit

    t = make_org(db)
    emp = new_employer(db, t.org.id)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(BadRequestException) as exc:
        _cred(db, t.org.id, emp["id"], ref=secret)
    assert secret not in exc.value.message and secret[:20] not in exc.value.message
    assert db.query(PayrollMxCredentialRef).count() == 0
    audit = json.dumps([[a.new_value, a.reason] for a in db.query(TaxConfigurationAudit).all()], default=str)
    assert secret[:20] not in audit and secret[:20] not in caplog.text


def test_rotation_keeps_history_and_reference_is_masked_after_creation(db):
    from app.modules.payroll.models import TaxConfigurationAudit

    t = make_org(db)
    emp = new_employer(db, t.org.id)
    first = _cred(db, t.org.id, emp["id"])
    assert first["secretRef"] == GCP_REF                      # once, in the write response
    second = _cred(db, t.org.id, emp["id"], ref=GCP_REF.replace("/versions/1", "/versions/2"))
    listed = _svc().list_credentials(db, t.org.id, emp["id"])
    assert [c["status"] for c in listed] == ["ROTATED", "ACTIVE"] and second["rotatedFromId"] == first["id"]
    assert all("secretRef" not in c and c["secretRefMasked"].startswith("gcp-sm://…") for c in listed)
    audit = json.dumps([a.new_value for a in db.query(TaxConfigurationAudit).all()], default=str)
    assert "zoiko-test-project" not in audit


def test_kind_scoping(db):
    from app.core.exceptions import BadRequestException

    t = make_org(db)
    emp = new_employer(db, t.org.id)
    reg = new_registration(db, t.org.id, emp["id"])
    with pytest.raises(BadRequestException, match="belongs to an IMSS registration"):
        _cred(db, t.org.id, emp["id"], kind="IDSE")
    with pytest.raises(BadRequestException, match="belongs to the legal employer"):
        _cred(db, t.org.id, emp["id"], kind="CSD", reg=reg["id"])
    assert _cred(db, t.org.id, emp["id"], kind="SUA", reg=reg["id"])["imssRegistrationId"] == reg["id"]


# ── certificate screening and parsing ─────────────────────────────────────────

def test_der_and_pem_certificates_are_parsed():
    der, cert, _key = self_signed_cert()
    pem, _c, _k = self_signed_cert(pem=True)
    meta = _svc().parse_certificate(der)
    assert meta["certificate_serial"] == "1234abcd" and len(meta["fingerprint_sha256"]) == 64
    assert meta["valid_to"].year == 2027 and "SYNTHETIC CSD TEST" in meta["subject_summary"]
    assert _svc().parse_certificate(pem)["certificate_serial"] == "1234abcd"


def _private_key_pem_and_der():
    from cryptography.hazmat.primitives import serialization

    _b, _c, key = self_signed_cert()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    der = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    return pem, der


def _pkcs12():
    from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12

    _b, cert, key = self_signed_cert()
    return pkcs12.serialize_key_and_certificates(b"syn", key, cert, None, BestAvailableEncryption(b"x"))


def test_everything_else_is_rejected_before_parsing(monkeypatch):
    from cryptography import x509

    from app.core.exceptions import BadRequestException

    calls = []
    monkeypatch.setattr(x509, "load_der_x509_certificate", lambda *a, **k: calls.append("der"))
    monkeypatch.setattr(x509, "load_pem_x509_certificate", lambda *a, **k: calls.append("pem"))
    pem_key, der_key = _private_key_pem_and_der()
    cert_pem, _c, _k = self_signed_cert(pem=True)
    for bad in (b"", b"hello world", pem_key, der_key, _pkcs12(), cert_pem + pem_key, cert_pem + cert_pem,
                b"\x30" + b"\x00" * 10, b"%PDF-1.7 not a certificate"):
        with pytest.raises(BadRequestException):
            _svc().parse_certificate(bad)
    assert calls == []                                      # the parser was never reached


def test_size_cap_is_16_kb():
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException, match="larger than 16 KB"):
        _svc().screen_certificate_bytes(b"\x30" + b"\x00" * (16 * 1024))


def _forbid_disk(monkeypatch):
    """Any temp file, or any file opened for writing, during the request fails the test."""
    import builtins
    import io
    import os
    import tempfile

    def boom(*a, **k):
        raise AssertionError("certificate upload touched the disk")

    for name in ("TemporaryFile", "NamedTemporaryFile", "SpooledTemporaryFile", "mkstemp", "mkdtemp"):
        monkeypatch.setattr(tempfile, name, boom)
    real_open = builtins.open

    def guarded_open(file, mode="r", *a, **k):
        if any(ch in str(mode) for ch in "wax+"):
            boom()
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(io, "open", guarded_open)
    real_os_open = os.open

    def guarded_os_open(path, flags, *a, **k):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT):
            boom()
        return real_os_open(path, flags, *a, **k)

    monkeypatch.setattr(os, "open", guarded_os_open)


def test_upload_over_http_is_in_memory_and_bytes_are_not_stored(db, monkeypatch):
    from app.modules.payroll.models import PayrollMxCredentialRef

    t = make_org(db)
    emp = new_employer(db, t.org.id)
    cred = _cred(db, t.org.id, emp["id"])
    der, _c, _k = self_signed_cert()
    with http(db, principal(t.org.id)) as c:
        _forbid_disk(monkeypatch)
        r = c.post(f"{ORG_BASE}/credentials/{cred['id']}/certificate", content=der,
                   headers={"Content-Type": "application/octet-stream"})
        monkeypatch.undo()
    assert r.status_code == 200, r.text
    assert r.json()["certificateSerial"] == "1234abcd"
    row = db.get(PayrollMxCredentialRef, cred["id"])
    stored = json.dumps({col.name: str(getattr(row, col.name)) for col in row.__table__.columns})
    assert der.hex()[:40] not in stored and base64.b64encode(der).decode()[:40] not in stored


def _http_middleware_layers():
    from starlette.middleware.base import BaseHTTPMiddleware

    from app.main import app

    return sum(1 for m in app.user_middleware if m.cls is BaseHTTPMiddleware)


def _raw_asgi_upload(db, org_id, credential_id, *, total, chunk=64 * 1024, declare_length):
    """Drive the REAL app (all middleware) at the ASGI level with a streamed
    body of `total` bytes, counting how many chunks the app actually pulls —
    TestClient would buffer the whole body before calling the app, so it
    cannot prove early refusal."""
    import asyncio

    from app.main import app
    from tests.test_hong_kong_governance import _http as _hk_http

    pulled = {"chunks": 0, "bytes": 0, "before_response": None}
    remaining = {"n": total}
    responded = {"yes": False}
    finished = asyncio.Event()

    async def receive():
        # Like a real server: once the app has started its response (or the
        # body is exhausted) the next receive is a disconnect — so `pulled`
        # counts only what the app read BEFORE answering.
        if responded["yes"] or remaining["n"] <= 0:
            await finished.wait()                          # the client hangs up only after the full response
            return {"type": "http.disconnect"}
        await asyncio.sleep(0.002)                         # chunks arrive at network pace, not instantly
        part = min(chunk, remaining["n"])
        remaining["n"] -= part
        pulled["chunks"] += 1
        pulled["bytes"] += part
        return {"type": "http.request", "body": b"\x30" * part, "more_body": remaining["n"] > 0}

    sent = []

    async def send(message):
        if message["type"] == "http.response.start":
            responded["yes"] = True
            pulled["before_response"] = pulled["chunks"]
        if message["type"] == "http.response.body" and not message.get("more_body"):
            finished.set()
        sent.append(message)

    headers = [(b"content-type", b"application/octet-stream"), (b"host", b"testserver")]
    if declare_length:
        headers.append((b"content-length", str(total).encode()))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
             "scheme": "http", "path": f"{ORG_BASE}/credentials/{credential_id}/certificate",
             "raw_path": f"{ORG_BASE}/credentials/{credential_id}/certificate".encode(), "query_string": b"",
             "headers": headers, "client": ("127.0.0.1", 1), "server": ("testserver", 80)}
    async def run():
        await asyncio.wait_for(app(scope, receive, send), timeout=30)

    with _hk_http(db, principal(org_id)):                 # same dependency overrides (auth, DB)
        asyncio.run(run())
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    return status, pulled, b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")


@pytest.mark.parametrize("declare_length", [True, False])
def test_a_10_mb_body_is_refused_without_reading_it_all(db, declare_length):
    """Correction 2 follow-up: the 16 KB cap stops reading at 16 KB + 1 byte.
    With a Content-Length header the request is refused before ANY body
    chunk is read; with a streamed (chunked) body it is refused after the
    first chunk that crosses 16 KB — never after reading all 10 MB."""
    t = make_org(db)
    emp = new_employer(db, t.org.id)
    cred = _cred(db, t.org.id, emp["id"])
    total = 10 * 1024 * 1024
    status, pulled, body = _raw_asgi_upload(db, t.org.id, cred["id"], total=total, declare_length=declare_length)
    assert status == 400 and b"larger than 16 KB" in body
    # What was read before answering: the route itself reads nothing with a
    # declared length and one 64 KB chunk (of 160) when streamed. Each of the
    # app's BaseHTTPMiddleware layers can pull at most one more chunk while it
    # listens for a disconnect (discarded, never accumulated).
    assert pulled["before_response"] <= _http_middleware_layers() + (0 if declare_length else 1)
    # Starlette's BaseHTTPMiddleware (the app's audit middleware) listens for
    # a disconnect while the 400 is written and discards any chunk that
    # arrives meanwhile — it never accumulates them, and it stops with the
    # response. The 10 MB body is never read in full.
    assert pulled["chunks"] < 160 and pulled["bytes"] < total


def test_a_body_of_exactly_16_kb_plus_one_byte_is_refused_while_streaming(db):
    t = make_org(db)
    emp = new_employer(db, t.org.id)
    cred = _cred(db, t.org.id, emp["id"])
    status, pulled, body = _raw_asgi_upload(db, t.org.id, cred["id"], total=16 * 1024 + 1, chunk=1024,
                                            declare_length=False)
    assert status == 400 and b"larger than 16 KB" in body
    assert pulled["bytes"] == 16 * 1024 + 1                   # stopped at the first byte over the cap


def test_upload_rejections_over_http(db):
    t = make_org(db)
    emp = new_employer(db, t.org.id)
    cred = _cred(db, t.org.id, emp["id"])
    pem_key, _der_key = _private_key_pem_and_der()
    url = f"{ORG_BASE}/credentials/{cred['id']}/certificate"
    with http(db, principal(t.org.id)) as c:
        assert c.post(url, content=b"x" * (16 * 1024 + 1),
                      headers={"Content-Type": "application/octet-stream"}).status_code == 400
        r = c.post(url, content=pem_key, headers={"Content-Type": "application/octet-stream"})
        assert r.status_code == 400 and "PRIVATE KEY" not in r.text
        assert c.post(url, files={"file": ("a.cer", b"x")}).status_code == 400          # multipart is not accepted
    with http(db, principal(t.org.id, user_id=702, role="payroll_admin")) as c:
        der, _c, _k = self_signed_cert()
        assert c.post(url, content=der, headers={"Content-Type": "application/octet-stream"}).status_code == 403
