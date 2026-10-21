"""
tests/privacy/test_nonprod_data.py
----------------------------------
ZP-PRIV D09: synthetic values fail real checksums, the restore guard blocks
production data in non-production, de-identification scrubs a copy and
unlocks it, and the CI scan flags real-looking identifiers.
"""

from __future__ import annotations

import pytest

from tests.privacy._evidence import record


def test_synthetic_identities_fail_every_real_checksum():
    from app.core import synthetic as s

    for n in range(1, 400):
        assert not s.iban_valid(s.iban(n)), s.iban(n)
        assert not s.bsn_valid(s.bsn(n)), s.bsn(n)
        assert not s.ssn_valid(s.ssn(n))
        assert not s.nino_valid(s.nino(n))
        assert not s.pan_valid(s.pan(n))
        assert s.email_is_reserved(s.email(n, "SYN001"))
        assert s.phone(n).startswith("+447700900")
    # ...while the validators accept real-shaped values (published examples).
    assert s.iban_valid("GB82WEST12345698765432") and s.iban_valid("NL91ABNA0417164300")  # privacy-scan: allow
    assert s.bsn_valid("111222333") and s.luhn_valid("4111111111111111")
    assert s.nino_valid("AB123456C") and s.pan_valid("ABCPE1234F") and s.ssn_valid("123-45-6789")  # privacy-scan: allow


def test_restore_guard_blocks_production_data_in_nonprod():
    from app.core import nonprod_guard as g

    with pytest.raises(g.NonProductionDataError):
        g.assert_safe_restore("production", "staging", deidentified=False)
    g.assert_safe_restore("production", "staging", deidentified=True)
    g.assert_safe_restore("production", "production", deidentified=False)
    g.assert_safe_restore("synthetic", "staging", deidentified=False)


def test_startup_guard_marks_production_and_refuses_unscrubbed_copies(db):
    from app.core import nonprod_guard as g

    assert g.enforce(db, env="staging") == "ok"           # fresh synthetic database
    assert g.enforce(db, env="production") == "marked"     # production stamps its data
    assert g.enforce(db, env="production") == "production"
    with pytest.raises(g.NonProductionDataError):
        g.enforce(db, env="staging")                        # restored copy, not de-identified
    assert g.enforce(db, env="development") == "warned"    # local diagnosis only
    g.mark_deidentified(db)
    assert g.enforce(db, env="staging") == "ok"


def test_deidentification_scrubs_identities_credentials_and_unlocks_the_copy(db, world):
    from app.core import nonprod_guard as g
    from app.database import Base
    from app.modules.auth.models import User
    from app.modules.payroll.models import PayrollEmployee
    from scripts import deidentify_database

    g.enforce(db, env="production")
    plan = deidentify_database.plan(Base.metadata)
    assert {"email", "phone", "bank_account", "pan", "name"} <= set(plan["strings"]["payroll_employees"])
    assert "hashed_password" in plan["strings"]["users"] and "organization_name" not in plan["strings"].get(
        "organizations", [])
    out = deidentify_database.run(db.get_bind(), Base.metadata)
    db.expire_all()
    assert out["deidentifiedAt"].endswith("Z")
    blob = " ".join(f"{e.name}|{e.email}|{e.bank_account}|{e.pan}|{e.phone}|{e.address_line1}"
                    for e in db.query(PayrollEmployee).all())
    for value in ("Synthetic Worker", "worker.example", "GB00SYNTH", "SYNTHPAN", "+440000000000", "Synthetic Street"):
        assert value not in blob, value
    assert all(u.hashed_password == "!deidentified-unusable" for u in db.query(User).all())
    assert all("@deidentified.example" in u.email or "deid-" in u.email for u in db.query(User).all())
    from sqlalchemy import text

    assert db.execute(text("SELECT count(*) FROM security_events")).scalar() == 0
    assert db.execute(text("SELECT count(*) FROM zoiko_audit_purge_flag")).scalar() == 0  # flag never left on
    assert g.enforce(db, env="staging") == "ok"
    record(test_id="D09_deidentification", role="restore operator", scope="non-production copy", tenant_ids=None,
           endpoint="scripts/deidentify_database.py", expected_status=0, actual_status=0,
           note=f"{out['tablesScrubbed']} tables scrubbed; credentials and audit emptied; guard unlocked")


def test_deidentify_refuses_production_and_needs_confirmation(monkeypatch):
    from scripts import deidentify_database

    monkeypatch.setenv("ENVIRONMENT", "production")
    assert deidentify_database.main(["--confirm-nonprod-copy"]) == 2
    monkeypatch.setenv("ENVIRONMENT", "staging")
    assert deidentify_database.main([]) == 2


def test_synthetic_generator_is_idempotent_and_tenant_scoped(db):
    from app.core import synthetic
    from app.modules.payroll.models import PayrollEmployee
    from scripts.generate_synthetic_data import seed

    assert seed(db, 2, 5) == {"tenantsCreated": 2, "workersCreated": 10}
    assert seed(db, 2, 5) == {"tenantsCreated": 0, "workersCreated": 0}
    rows = db.query(PayrollEmployee).all()
    assert len(rows) == 10
    assert all(synthetic.email_is_reserved(e.email) and not synthetic.iban_valid(e.bank_account) for e in rows)


def test_scanner_flags_real_identifiers_and_ignores_synthetic_ones():
    from app.core import synthetic
    from scripts.scan_test_data import scan_text

    real = "\n".join(["iban = 'GB82WEST12345698765432'", "card 4000123412341234", "bsn: 111222333",  # privacy-scan: allow
                      "nino AB123456C", "pan ABCPE1234F", "contact jane.doe@gmail.com", "whsec_" + "a" * 24,  # privacy-scan: allow
                      "-----BEGIN PRIVATE KEY-----"])  # privacy-scan: allow
    kinds = {f["kind"] for f in scan_text(real, "x.py")}
    assert kinds == {"iban", "card", "bsn", "nino", "pan", "email", "secret"}
    fake = "\n".join([synthetic.iban(7), synthetic.bsn(7) + " bsn", synthetic.nino(7), synthetic.pan(7),
                      synthetic.email(7), "4242424242424242"])
    assert scan_text(fake, "y.py") == []
    assert all("jane" not in str(f) for f in scan_text(real, "x.py"))  # values are never stored


def test_repository_scan_has_no_new_findings():
    from scripts.scan_test_data import main

    assert main([]) == 0
