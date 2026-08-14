"""Smoke test for the bulk employee import endpoints
(POST /payroll/employees/bulk, /payroll/employees/bulk-update).

Runs against a throwaway SQLite database with a real Organization +
org_admin User + Compliance Details row so the router-level
require_active_subscription("payroll") gate passes legitimately.

Run:  python _test_bulk_employees.py
"""

import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
DB = os.path.join(tmp, "test_bulk_employees.sqlite3")
os.environ["PAYROLL_DATABASE_URL"] = f"sqlite:///{DB}"
os.environ["ENVIRONMENT"] = "development"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
import sqlalchemy as sa
from app.main import app
from app.core.dependencies import get_current_user, get_current_payroll_operator
from app.database import Base, SessionLocal, engine


@sa.event.listens_for(engine, "connect")
def _register_pg_advisory_lock(dbapi_connection, connection_record):
    # code_generation.py runs `SELECT pg_advisory_xact_lock(:org_key)` (a
    # PostgreSQL-only advisory lock). Stub it out as a no-op on SQLite so the
    # smoke test can exercise the real flow against a temp database.
    dbapi_connection.create_function("pg_advisory_xact_lock", 1, lambda key: 1)


engine.dispose()
Base.metadata.create_all(bind=engine)

db = SessionLocal()
org = __import__("app.modules.organizations.models", fromlist=["Organization"]).Organization(
    organization_name="Zoiko Test Org",
    organization_code="ZTST",
    is_active=True,
)
db.add(org)
db.flush()

user = __import__("app.modules.auth.models", fromlist=["User"]).User(
    email="bulk-admin@zoiko.dev",
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

client = TestClient(app)


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


# ── 1. Bulk create: 2 valid + 1 duplicate-email within the batch ──────
payload = {
    "employees": [
        employee("asha@zoiko.dev", "Asha Rao", panNumber="AASPR0001A"),
        employee("bharat@zoiko.dev", "Bharat Menon", panNumber="ABCPR0002B"),
        employee("asha@zoiko.dev", "Asha Duplicate", panNumber="AASPR0003C"),
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
assert created["asha@zoiko.dev"]["countryCode"] == "IN", body
asha_id = created["asha@zoiko.dev"]["id"]
bharat_id = created["bharat@zoiko.dev"]["id"]
print("bulk create ok: 2 created, 1 in-batch duplicate rejected")

# ── 2. Re-submitting the same rows must fail as duplicates ─────────────
r = client.post("/api/payroll/employees/bulk", json=payload)
assert r.status_code == 200, r.text
body = r.json()
assert body["created"] == 0, body
assert len(body["failed"]) == 3, body
assert all("already exists" in f["reason"] for f in body["failed"]), body
print("bulk create ok: existing emails rejected as duplicates")

# ── 3. Missing name/email fails fast ───────────────────────────────────
r = client.post(
    "/api/payroll/employees/bulk",
    json={"employees": [{"name": "", "email": "", "countryCode": "IN"}]},
)
assert r.status_code == 200, r.text
body = r.json()
assert body["created"] == 0 and len(body["failed"]) == 1, body
assert "name and email are required" in body["failed"][0]["reason"], body
print("bulk create ok: blank name/email rejected")

# ── 4. Jurisdiction validation failure (US missing required SSN) ───────
r = client.post(
    "/api/payroll/employees/bulk",
    json={"employees": [employee("us@zoiko.dev", "US Person", countryCode="US")]},
)
assert r.status_code == 200, r.text
body = r.json()
assert body["created"] == 0 and len(body["failed"]) == 1, body
assert "ssn is required" in body["failed"][0]["reason"], body
print("bulk create ok: US row without SSN rejected by jurisdiction strategy")

# ── 5. PAN duplicate across rows is caught ─────────────────────────────
r = client.post(
    "/api/payroll/employees/bulk",
    json={
        "employees": [
            employee("pan1@zoiko.dev", "PAN One", panNumber="ABCDE1234F"),
            employee("pan2@zoiko.dev", "PAN Two", panNumber="ABCDE1234F"),
        ]
    },
)
assert r.status_code == 200, r.text
body = r.json()
assert body["created"] == 1 and len(body["failed"]) == 1, body
assert "already exists" in body["failed"][0]["reason"], body
print("bulk create ok: duplicate PAN rejected")

# ── 6. List reflects the new rows ──────────────────────────────────────
r = client.get("/api/payroll/employees")
assert r.status_code == 200, r.text
emails = {e["email"] for e in r.json()}
assert {"asha@zoiko.dev", "bharat@zoiko.dev", "pan1@zoiko.dev"} <= emails, emails
print("list ok: created employees visible")

# ── 7. Bulk update: change department + designation ────────────────────
r = client.post(
    "/api/payroll/employees/bulk-update",
    json={
        "employees": [
            {
                "id": asha_id,
                "name": "Asha Rao",
                "email": "asha@zoiko.dev",
                "department": "Design",
                "designation": "Senior Engineer",
            },
            {"id": 999999, "name": "Ghost", "email": "ghost@zoiko.dev", "department": "Ops"},
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
print("bulk update ok: targeted employee updated, missing id reported")

# ── 8. Single employee fetch by id still consistent ────────────────────
r = client.get(f"/api/payroll/employees/{bharat_id}")
assert r.status_code == 200 and r.json()["email"] == "bharat@zoiko.dev", r.text

db.close()
engine.dispose()
try:
    os.remove(DB)
except OSError:
    pass  # Windows keeps the temp file locked briefly; the temp dir is discarded anyway
print("RESULT: PASS - bulk employee import/update ok")
