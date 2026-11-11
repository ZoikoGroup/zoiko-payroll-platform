"""
tests/test_bulk_employees.py
-----------------------------
Coverage for the bulk employee import/update endpoints
(POST /payroll/employees/bulk, /payroll/employees/bulk-update).

Promoted 2026-09-18 (platform infrastructure fix plan, Tier 1.5) from a
standalone root-level script (`_test_bulk_employees.py`). The org is set
to workspace_type EVALUATION so require_active_subscription's production
gate (added after the original script was written) doesn't need a real
Subscription row -- same pattern test_germany_elster.py already uses.
"""

import os
import sys
import tempfile

import sqlalchemy as sa

tmp = tempfile.mkdtemp()
DB = os.path.join(tmp, "test_bulk_employees.sqlite3")
os.environ["PAYROLL_DATABASE_URL"] = f"sqlite:///{DB}"
os.environ["ENVIRONMENT"] = "development"

_saved_app_modules = {
    key: mod for key, mod in sys.modules.items()
    if key == "app" or key.startswith("app.")
}
for key in list(_saved_app_modules):
    del sys.modules[key]

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.core.dependencies import (
    get_current_user,
    get_current_payroll_operator,
    get_current_org_scoped_principal,
)  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402


@sa.event.listens_for(engine, "connect")
def _register_pg_advisory_lock(dbapi_connection, connection_record):
    # code_generation.py runs `SELECT pg_advisory_xact_lock(:org_key)` (a
    # PostgreSQL-only advisory lock). Stub it out as a no-op on SQLite so
    # this test can exercise the real flow against a temp database.
    dbapi_connection.create_function("pg_advisory_xact_lock", 1, lambda key: 1)


engine.dispose()
Base.metadata.create_all(bind=engine)

db = SessionLocal()
org = __import__("app.modules.organizations.models", fromlist=["Organization"]).Organization(
    organization_name="Zoiko Test Org",
    organization_code="ZTST",
    is_active=True,
    workspace_type="EVALUATION",
)
db.add(org)
db.flush()

user = __import__("app.modules.auth.models", fromlist=["User"]).User(
    email="bulk-admin@zoiko-dev.example.com",
    hashed_password="x",
    role="org_admin",
    organization_id=org.id,
    first_name="Bulk",
    last_name="Admin",
)
db.add(user)

compliance = __import__("app.modules.payroll.models", fromlist=["CompanyComplianceDetails"]).CompanyComplianceDetails(
    organization_id=org.id,
    name="Zoiko Test Org",
    jurisdiction_country="IN",
    jurisdiction_state="KA",
)
db.add(compliance)
db.commit()


class FakeOrgAdmin:
    id = user.id
    email = user.email
    role = "org_admin"
    organization_id = org.id


app.dependency_overrides[get_current_user] = lambda: FakeOrgAdmin()
app.dependency_overrides[get_current_payroll_operator] = lambda: FakeOrgAdmin()
# The PDP (ZP-PRIV A04) resolves the principal through this dependency too.
app.dependency_overrides[get_current_org_scoped_principal] = lambda: FakeOrgAdmin()

client = TestClient(app)

# Restore pre-purge app modules so other test files don't bind to this
# file's private app/engine objects (same pattern test_checkout_flow.py
# uses) -- this file's own names above already hold direct references to
# its own objects, so this only affects modules imported AFTER this point.
for key in list(sys.modules):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]
sys.modules.update(_saved_app_modules)
del _saved_app_modules


def employee(email, name, **extra):
    row = {
        "name": name,
        "email": email,
        "department": "Engineering",
        "designation": "Engineer",
        "employmentType": "full_time",
        "status": "active",
        "countryCode": "IN",
        "panNumber": extra.pop("panNumber", None),
    }
    row.update(extra)
    return row


def test_bulk_employee_import_and_update_lifecycle():
    # ── 1. Bulk create: 2 valid + 1 duplicate-email within the batch ──
    payload = {
        "employees": [
            employee("asha@zoiko-dev.example.com", "Asha Rao", panNumber="AASPR0001A"),
            employee("bharat@zoiko-dev.example.com", "Bharat Menon", panNumber="ABCPR0002B"),
            employee("asha@zoiko-dev.example.com", "Asha Duplicate", panNumber="AASPR0003C"),
        ]
    }
    r = client.post("/api/payroll/employees/bulk", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 2, body
    assert len(body["failed"]) == 1, body
    assert "already exists" in body["failed"][0]["reason"], body
    assert len(body["employees"]) == 2, body
    created = {e["email"]: e for e in body["employees"]}
    assert created["asha@zoiko-dev.example.com"]["countryCode"] == "IN", body
    asha_id = created["asha@zoiko-dev.example.com"]["id"]
    bharat_id = created["bharat@zoiko-dev.example.com"]["id"]

    # ── 2. Re-submitting the same rows must fail as duplicates ────────
    r = client.post("/api/payroll/employees/bulk", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 0, body
    assert len(body["failed"]) == 3, body
    assert all("already exists" in f["reason"] for f in body["failed"]), body

    # ── 3. Missing name/email fails fast ───────────────────────────────
    r = client.post(
        "/api/payroll/employees/bulk",
        json={"employees": [{"name": "", "email": "", "countryCode": "IN"}]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 0 and len(body["failed"]) == 1, body
    assert "name and email are required" in body["failed"][0]["reason"], body

    # ── 4. Jurisdiction validation failure (US missing required SSN) ──
    r = client.post(
        "/api/payroll/employees/bulk",
        json={"employees": [employee("us@zoiko-dev.example.com", "US Person", countryCode="US")]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 0 and len(body["failed"]) == 1, body
    assert "ssn is required" in body["failed"][0]["reason"], body

    # ── 5. PAN duplicate across rows is caught ──────────────────────────
    r = client.post(
        "/api/payroll/employees/bulk",
        json={
            "employees": [
                employee("pan1@zoiko-dev.example.com", "PAN One", panNumber="ABCDE1234F"),
                employee("pan2@zoiko-dev.example.com", "PAN Two", panNumber="ABCDE1234F"),
            ]
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 1 and len(body["failed"]) == 1, body
    assert "already exists" in body["failed"][0]["reason"], body

    # ── 6. List reflects the new rows ───────────────────────────────────
    r = client.get("/api/payroll/employees")
    assert r.status_code == 200, r.text
    emails = {e["email"] for e in r.json()}
    assert {"asha@zoiko-dev.example.com", "bharat@zoiko-dev.example.com", "pan1@zoiko-dev.example.com"} <= emails, emails

    # ── 7. Bulk update: change department + designation ─────────────────
    r = client.post(
        "/api/payroll/employees/bulk-update",
        json={
            "employees": [
                {
                    "id": asha_id,
                    "name": "Asha Rao",
                    "email": "asha@zoiko-dev.example.com",
                    "department": "Design",
                    "designation": "Senior Engineer",
                },
                {"id": 999999, "name": "Ghost", "email": "ghost@zoiko-dev.example.com", "department": "Ops"},
            ]
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated"] == 1, body
    assert len(body["failed"]) == 1, body
    assert "no employee found" in body["failed"][0]["reason"].lower(), body

    r = client.get(f"/api/payroll/employees/{asha_id}")
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["department"] == "Design", updated
    assert updated["designation"] == "Senior Engineer", updated
    assert updated["id"] == asha_id, updated

    # ── 8. Single employee fetch by id still consistent ──────────────────
    r = client.get(f"/api/payroll/employees/{bharat_id}")
    assert r.status_code == 200 and r.json()["email"] == "bharat@zoiko-dev.example.com", r.text


def test_per_country_import_takes_the_import_country_and_refuses_other_countries():
    """Employees are imported one country at a time: rows with no country
    take the import's country; a row for another country is refused (it
    belongs in that country's own import)."""
    rows = [
        employee("in-blank@zoiko-dev.example.com", "Blank Country", countryCode=None),
        employee("in-explicit@zoiko-dev.example.com", "Explicit India", countryCode="India"),
        employee("us-row@zoiko-dev.example.com", "US Row", countryCode="US",
                 complianceFields={"ssn": "123-45-6789", "flsa_status": "Exempt", "state_tax_jurisdiction": "CA"}),
    ]
    r = client.post("/api/payroll/employees/bulk", json={"employees": rows, "countryCode": "IN"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 2, body
    assert {e["countryCode"] for e in body["employees"]} == {"IN"}, body
    assert len(body["failed"]) == 1, body
    assert body["failed"][0]["row"]["email"] == "us-row@zoiko-dev.example.com"
    assert "Import it with the US template" in body["failed"][0]["reason"], body

    r = client.post("/api/payroll/employees/bulk", json={"employees": rows[:1], "countryCode": "ZZ"})
    assert r.status_code == 400, r.text


def test_import_accepts_the_values_people_type_in_spreadsheets():
    """"No"/"Yes", any capitalisation, "N/A" in optional fields and a W-4
    year are read as the field's own values — and stored in canonical form."""
    row = employee("taylor.morgan@zoiko-dev.example.com", "Taylor Morgan", countryCode="US", complianceFields={
        "ssn": "123-45-6788", "flsa_status": "Non-exempt", "w4_filing_status": "Married filing jointly",
        "w4_step2_checkbox": "No", "w4_form_vintage": "2024", "is_nonresident_alien": "No",
        "ct_withholding_code": "N/A", "nj_rate_table": "N/A", "reciprocity_certificate_on_file": "No",
        "reciprocity_certificate_expiry": "N/A", "residency_certification_on_file": "No",
        "residency_certification_date": "N/A", "state_tax_jurisdiction": "ny",
    })
    r = client.post("/api/payroll/employees/bulk", json={"employees": [row], "countryCode": "US"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 1 and not body["failed"], body
    cf = body["employees"][0]["complianceFields"]
    assert cf["flsa_status"] == "Non-Exempt"
    assert cf["w4_filing_status"] == "Married Filing Jointly"
    assert cf["w4_step2_checkbox"] == "false" and cf["is_nonresident_alien"] == "false"
    assert cf["w4_form_vintage"] == "2020 or later (current form)"
    assert cf["state_tax_jurisdiction"] == "NY"
    assert "ct_withholding_code" not in cf and "reciprocity_certificate_expiry" not in cf

    # A genuinely wrong value is still refused, with the reason.
    bad = employee("bad.flsa@zoiko-dev.example.com", "Bad Flsa", countryCode="US", complianceFields={
        "ssn": "123-45-6787", "flsa_status": "Salaried", "state_tax_jurisdiction": "CA"})
    r = client.post("/api/payroll/employees/bulk", json={"employees": [bad], "countryCode": "US"})
    assert r.json()["created"] == 0 and "flsa_status" in r.json()["failed"][0]["reason"]
