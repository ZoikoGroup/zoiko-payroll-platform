"""Mexico final mile X5 (gap C3): the CSD custody seam. The signer reads the
certificate's public facts through the provider and checks custody before it
asks for a signature; the private key is never returned; production has no
provider and still refuses; expiry alerts list expired / expiring CSDs for the
Super Admin. SYNTHETIC certificates generated in memory."""

import base64
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.modules.payroll import mexico_cfdi_builder as B
from app.modules.payroll import mexico_csd_custody as C
from tests._mx_fake_csd import FakeCustody, synthetic_sealer

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _cred(fake, **over):
    base = dict(kind="CSD", status="ACTIVE", secret_ref="fake-sm://projects/syn/secrets/csd", fingerprint_sha256=fake.fingerprint())
    return SimpleNamespace(**{**base, **over})


def _signer(monkeypatch, fake):
    monkeypatch.setitem(C._PROVIDERS, "fake-sm", lambda: fake)
    return C.CustodySigner(sealer=synthetic_sealer, now=lambda: NOW)


def test_production_has_no_provider_and_the_active_signer_still_refuses():
    assert C._PROVIDERS == {}
    with pytest.raises(C.MXRefuse) as e:
        C.provider_for("gcp-sm://projects/x/secrets/y")
    assert e.value.key == "MX_CSD_PROVIDER_NOT_CONFIGURED"
    assert isinstance(B.active_signer(), B.GcpSmSigner) and B.active_signer().blocked().key == "MX_CSD_SIGNING_BLOCKED"
    assert C.CustodySigner().blocked().key == "MX_CSD_SEALER_NOT_BUILT"                  # no sealer: refuses too
    app = Path(__file__).resolve().parents[1] / "app"
    assert not [p for p in app.rglob("*.py") if "_mx_fake_csd" in p.read_text(encoding="utf-8")]


def test_a_custodied_csd_signs_and_the_signature_verifies_with_the_public_certificate(monkeypatch):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec

    fake = FakeCustody()
    payload = b"<cfdi:Comprobante Folio='SYN-1'/>"
    sealed, serial = _signer(monkeypatch, fake).sign(payload, _cred(fake))
    assert serial == "1234ABCD" and fake.signed == [payload]
    sig = base64.b64decode(sealed.split(b"SYNTHETIC-SELLO ")[1].split(b" ")[0])
    fake.public_key().verify(sig, payload, ec.ECDSA(hashes.SHA256()))                    # raises if wrong
    assert not any(hasattr(C.CsdSignature, f) or f in C.CsdFacts.__dataclass_fields__ for f in ("key", "private_key"))
    assert not [m for m in dir(C.CsdCustodyProvider) if "key" in m.lower()]               # the interface never offers it


@pytest.mark.parametrize("make,cred_over,code", [
    (lambda: FakeCustody(not_before=datetime(2025, 1, 1, tzinfo=timezone.utc), days=30), {}, "MX_CSD_EXPIRED"),
    (lambda: FakeCustody(not_before=datetime(2026, 7, 1, tzinfo=timezone.utc)), {}, "MX_CSD_EXPIRED"),   # not yet valid
    (lambda: FakeCustody(status=C.REVOKED), {}, "MX_CSD_NOT_ACTIVE"),
    (lambda: FakeCustody(), {"fingerprint_sha256": "0" * 64}, "MX_CSD_FINGERPRINT_MISMATCH"),
    (lambda: FakeCustody(), {"status": "ROTATED"}, "MX_CSD_NOT_ACTIVE"),
    (lambda: FakeCustody(), {"kind": "PAC"}, "MX_CSD_NOT_ACTIVE"),
])
def test_custody_is_checked_before_any_signature(monkeypatch, make, cred_over, code):
    fake = make()
    with pytest.raises(C.MXRefuse) as e:
        _signer(monkeypatch, fake).sign(b"<x/>", _cred(fake, **cred_over))
    assert e.value.key == code and fake.signed == []                                       # nothing was signed


def test_expiry_alerts_list_expired_expiring_and_missing_csds_only(db):
    from app.modules.payroll.models import PayrollMxCredentialRef as R
    from tests._mx_employer_helpers import make_org, new_employer

    o = make_org(db, code="MXCSDX")
    emp = new_employer(db, o.org.id)
    profile_id = emp["id"] if isinstance(emp, dict) else emp.id
    on = date(2026, 6, 1)
    rows = {"expired": on - timedelta(days=1), "expiring": on + timedelta(days=10), "fine": on + timedelta(days=200),
            "missing": None}
    made = {}
    for i, (label, end) in enumerate(rows.items()):
        r = R(organization_id=o.org.id, employer_profile_id=profile_id, imss_registration_id=None,
              kind="CSD", secret_ref=f"gcp-sm://projects/syn/secrets/csd-{label}", fingerprint_sha256=f"{i:x}" * 64,
              certificate_serial=f"SYN{i}", valid_to=datetime.combine(end, datetime.min.time()) if end else None,
              status="ACTIVE" if label == "fine" else "ROTATED")
        db.add(r)
        db.flush()
        made[label] = r
    for label in ("expired", "expiring", "missing"):        # one ACTIVE at a time per (profile, kind): rotate the rest
        for r in made.values():
            r.status = "ROTATED"
        db.flush()
        made[label].status = "ACTIVE"
        db.commit()
        alerts = C.csd_expiry_alerts(db, on)
        assert [a["level"] for a in alerts] == [label.upper() if label != "expiring" else "EXPIRING"], label
        a = alerts[0]
        assert a["organizationId"] == o.org.id and "secret" not in str(a).lower() and "gcp-sm" not in str(a)
        assert a["fingerprint"].endswith("…") and len(a["fingerprint"]) == 13
    for r in made.values():
        r.status = "ROTATED"
    db.flush()
    made["fine"].status = "ACTIVE"
    db.commit()
    assert C.csd_expiry_alerts(db, on) == []                                                  # outside the window
    assert C.csd_expiry_alerts(db, on, organization_id=o.org.id + 999) == []


def test_the_super_admin_expiry_route(db):
    from tests._mx_employer_helpers import SA_BASE, SUPER_ADMIN, http, principal

    with http(db, SUPER_ADMIN) as c:
        r = c.get(f"{SA_BASE}/csd-expiry?on=2026-06-01")
        assert r.status_code == 200 and r.json() == {"on": "2026-06-01", "warningDays": 30, "alerts": []}
    with http(db, principal(1)) as c:
        assert c.get(f"{SA_BASE}/csd-expiry?on=2026-06-01").status_code in (401, 403)
