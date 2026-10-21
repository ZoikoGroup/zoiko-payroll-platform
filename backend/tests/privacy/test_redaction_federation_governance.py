"""
tests/privacy/test_redaction_federation_governance.py
-----------------------------------------------------
D03/D04 log + Sentry redaction under forced errors, D05 Zoiko One federation
(fake IdP), F02 data region and F03 legal hold / retention / DSAR.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import pytest

from tests.privacy._evidence import EVIDENCE_DIR, record

SECRET_VALUES = ("GB29NWBK60161331926819", "ABCDE1234F", "QQ123456C", "jane.worker@example.com",
                 "123-45-6789", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJlLXZhbHVl")


# ── Logs ─────────────────────────────────────────────────────────────────────

class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(self.format(record))


@pytest.fixture()
def captured_logs():
    from app.core.correlation import CorrelationLogFilter
    from app.core.redaction import RedactingLogFilter

    handler = _Capture()
    handler.setFormatter(logging.Formatter("%(levelname)s [%(correlation_id)s] %(message)s %(extra_bank)s"))
    handler.addFilter(CorrelationLogFilter())
    handler.addFilter(RedactingLogFilter())
    root = logging.getLogger()
    root.addHandler(handler)
    yield handler
    root.removeHandler(handler)


@pytest.mark.parametrize("area", ["payroll_run", "bank_export", "payslip", "employee_import"])
def test_forced_errors_leave_no_sensitive_values_in_logs(captured_logs, area):
    log = logging.getLogger(f"zoiko_payroll.{area}")
    try:
        raise ValueError(f"{area} failed for jane.worker@example.com account GB29NWBK60161331926819 "
                         f"PAN ABCDE1234F NINO QQ123456C SSN 123-45-6789")
    except ValueError:
        log.exception("Unhandled error in %s for %s", area, "jane.worker@example.com",
                      extra={"extra_bank": "GB29NWBK60161331926819", "ctc": 98000, "bank_account": "12345678"})
    text = "\n".join(captured_logs.lines)
    assert text and "ValueError" in text
    for value in SECRET_VALUES + ("98000",):
        assert value not in text, value
    sample = EVIDENCE_DIR / f"D03_log_sample_{area}.txt"
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    sample.write_text(text, encoding="utf-8")


def test_sentry_before_send_scrubs_body_headers_frames_and_breadcrumbs():
    from app.core.redaction import REDACTED, sentry_before_send

    event = {
        "request": {"data": {"name": "Jane", "bank_account": "12345678", "note": "IBAN GB29NWBK60161331926819"},
                    "headers": {"Authorization": "Bearer abc.def.ghi", "User-Agent": "x"},
                    "cookies": {"session": "s"}, "query_string": "email=jane.worker@example.com"},
        "extra": {"salary": 98000, "pan": "ABCDE1234F"},
        "user": {"id": 7, "email": "jane.worker@example.com", "ip_address": "10.0.0.1"},
        "exception": {"values": [{"value": "failed for jane.worker@example.com SSN 123-45-6789",
                                  "stacktrace": {"frames": [{"vars": {"iban": "GB29NWBK60161331926819",
                                                                      "employee": "x"}}]}}]},
        "breadcrumbs": {"values": [{"message": "PAN ABCDE1234F", "data": {"bank": "12345678"}}]},
    }
    out = sentry_before_send(event)
    blob = json.dumps(out)
    for value in SECRET_VALUES + ("98000", "12345678"):
        assert value not in blob, value
    assert out["request"]["headers"]["Authorization"] == REDACTED and out["user"] == {"id": 7}
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "D04_sentry_sample.json").write_text(json.dumps(out, indent=2), encoding="utf-8")


def test_sentry_is_configured_without_pii_bodies_or_locals():
    src = (Path(__file__).resolve().parents[2] / "app" / "main.py").read_text(encoding="utf-8")
    assert "send_default_pii=False" in src and 'max_request_body_size="never"' in src
    assert "include_local_variables=False" in src and "before_send=sentry_before_send" in src


def test_sensitive_change_notice_carries_no_values(db, world):
    from app.modules.payroll.service import _sensitive_field_changes, _snapshot_sensitive_fields

    emp = world.employees["A1"]
    snap = _snapshot_sensitive_fields(emp)
    emp.bank_account, emp.ctc, emp.pan = "GB99NEWACCOUNT00012345", 120000, "ZZZZZ9999Z"
    changes = _sensitive_field_changes(emp, snap)
    blob = json.dumps(changes)
    for value in ("GB99NEWACCOUNT00012345", "GB00SYNTH12345678", "120000", "60000", "ZZZZZ9999Z", "SYNTHPAN01"):
        assert value not in blob, value
    assert "2345" in blob  # last-4 of the new account only


# ── Federation (fake IdP) ────────────────────────────────────────────────────

@pytest.fixture()
def idp(monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from app.config import settings

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()).decode()
    public_pem = key.public_key().public_bytes(serialization.Encoding.PEM,
                                               serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    monkeypatch.setattr(settings, "FEDERATION_ISSUER", "https://idp.zoiko-one.test")
    monkeypatch.setattr(settings, "FEDERATION_PUBLIC_KEY_PEM", public_pem)

    def mint(**over):
        from jose import jwt

        now = int(time.time())
        claims = {"iss": "https://idp.zoiko-one.test", "aud": "zoiko-payroll", "sub": "z1-user-1",
                  "email": "pa@tenant-a.example", "tenant_id": "z1-tenant-a", "payroll_org": "PRIVA",
                  "products": ["payroll"], "iat": now, "exp": now + 120}
        claims.update(over)
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, private_pem, algorithm="RS256")

    return mint


def test_federation_valid_claims_yield_only_the_users_own_tenant_session(client, world, idp):
    r = client.post("/api/auth/federation/exchange", json={"token": idp()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["email"] == "pa@tenant-a.example" and body["user"]["organization_id"] == world.orgs["A"].id
    me = client.get("/api/payroll/employees", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert [e["id"] for e in me.json()] == [world.employees["A1"].id]  # still the user's own scope


@pytest.mark.parametrize("label, over", [
    ("global_admin_claim", {"roles": ["global_admin"]}),
    ("wildcard_tenant", {"tenant_id": "*"}),
    ("no_payroll_entitlement", {"products": ["crm"]}),
    ("other_product_audience", {"aud": "zoiko-crm"}),
    ("wrong_issuer", {"iss": "https://evil.example"}),
    ("expired", {"iat": int(time.time()) - 900, "exp": int(time.time()) - 600}),
    ("too_long_lived", {"exp": int(time.time()) + 86400}),
    ("missing_org", {"payroll_org": None}),
    ("cross_tenant", {"payroll_org": "PRIVB"}),
    ("platform_role", {"email": "sa@platform.example"}),
    ("unknown_user", {"email": "nobody@tenant-a.example"}),
    ("entity_scope_widening", {"entity_ids": [999]}),
])
def test_federation_refuses_over_broad_forged_or_cross_product_claims(client, world, idp, label, over):
    r = client.post("/api/auth/federation/exchange", json={"token": idp(**over)})
    assert r.status_code == 401, (label, r.text)
    assert "access_token" not in r.text
    record(test_id=f"D05_federation_{label}", role="federated", scope="fake IdP", tenant_ids=world.tenant_ids(),
           endpoint="POST /api/auth/federation/exchange", expected_status=401, actual_status=r.status_code,
           body=r.json(), note="integration pending: fake IdP")


def test_federation_forged_signature_is_refused(client, world, idp):
    token = idp()
    head, payload, sig = token.split(".")
    assert client.post("/api/auth/federation/exchange",
                       json={"token": f"{head}.{payload}.{sig[::-1]}"}).status_code == 401


def test_federation_disabled_until_configured(client, world):
    assert client.post("/api/auth/federation/exchange", json={"token": "x.y.z"}).status_code == 401


def test_federated_privileged_user_still_needs_mfa_unless_idp_asserts_it(client, world, idp):
    r = client.post("/api/auth/federation/exchange", json={"token": idp(email="ta@tenant-a.example")})
    assert r.status_code == 200 and r.json().get("mfa_enrollment_required") is True
    r = client.post("/api/auth/federation/exchange", json={"token": idp(email="ta@tenant-a.example", amr=["pwd", "mfa"])})
    assert r.json()["access_token"]


# ── Data region and legal hold ───────────────────────────────────────────────

def test_cross_region_privileged_retrieval_is_blocked(client, world, db):
    world.orgs["A"].data_region = "US"  # this deployment is EU
    db.commit()
    r = client.post("/api/super-admin/support-access/request", headers=world.headers("SP"), json={
        "organizationCode": "PRIVA", "reason": "r", "ticketReference": "T", "minutes": 5, "scopeType": "diagnostics"})
    assert r.status_code == 403 and r.json()["error"] == "DATA_REGION_POLICY"
    from app.modules.security import governance

    with pytest.raises(governance.RegionPolicyViolation):
        governance.assert_region(world.orgs["B"], "backup", target_region="US")
    governance.assert_region(world.orgs["B"], "backup", target_region="EU")


def test_legal_hold_blocks_every_deletion_path_and_needs_four_eyes(client, world, db):
    from app.modules.auth.models import User, UserRole

    ta2 = User(email="ta2@tenant-a.example", hashed_password="x", role=UserRole.ORG_ADMIN,
               organization_id=world.orgs["A"].id, first_name="T", last_name="A2", is_active=True)
    db.add(ta2)
    db.commit()
    world.users["TA2"] = ta2
    hold = client.post("/api/organization-admin/legal-holds", headers=world.headers("TA"),
                       json={"employeeId": world.employees["A2"].id, "reason": "Litigation", "reference": "L-1"}).json()
    r = client.delete(f"/api/payroll/employees/{world.employees['A2'].id}", headers=world.headers("TA"))
    assert r.status_code == 409 and r.json()["error"] == "LEGAL_HOLD"
    bulk = client.post("/api/payroll/employees/bulk-delete", headers=world.headers("TA"),
                       json={"employee_ids": [world.employees["A2"].id]})
    if bulk.status_code == 200:
        assert bulk.json()["failed"] and "legal hold" in bulk.json()["failed"][0]["reason"].lower()
    own = client.post(f"/api/organization-admin/legal-holds/{hold['id']}/release", headers=world.headers("TA"),
                      json={"reason": "done"})
    assert own.status_code == 403
    other = client.post(f"/api/organization-admin/legal-holds/{hold['id']}/release", headers=world.headers("TA2"),
                        json={"reason": "Case closed"})
    assert other.status_code == 200 and other.json()["status"] == "RELEASED"


def test_retention_candidates_respect_holds_and_dsar_lifecycle(client, world, db):
    from datetime import date

    from app.modules.security import governance

    world.employees["A1"].date_of_leaving = date(2015, 1, 1)
    world.employees["A2"].date_of_leaving = date(2015, 1, 1)
    db.commit()
    governance.place_hold(db, world.users["TA"], employee_id=world.employees["A2"].id, reason="hold", reference=None)
    ids = {c["employeeId"] for c in governance.retention_candidates(db, date(2026, 10, 19))}
    assert world.employees["A1"].id in ids and world.employees["A2"].id not in ids
    req = client.post("/api/organization-admin/data-access-requests", headers=world.headers("TA"),
                      json={"requestType": "access", "employeeId": world.employees["A1"].id}).json()
    assert req["status"] == "received" and req["dueAt"].endswith("Z")
    assert client.post("/api/organization-admin/data-access-requests", headers=world.headers("TA"),
                       json={"requestType": "access", "employeeId": world.employees["B1"].id}).status_code == 404
    done = client.post(f"/api/organization-admin/data-access-requests/{req['id']}/complete",
                       headers=world.headers("TA"), json={"outcome": "Export sent to the employee"}).json()
    assert done["status"] == "completed"
    gov = client.get("/api/organization-admin/data-governance", headers=world.headers("TA")).json()
    assert gov["dataRegion"] == "EU" and gov["retention"]["workerDataYearsAfterLeaving"] == 7
