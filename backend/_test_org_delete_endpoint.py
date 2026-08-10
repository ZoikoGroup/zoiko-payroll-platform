import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
DB = os.path.join(tmp, "test_org_delete_api.sqlite3")
os.environ["PAYROLL_DATABASE_URL"] = f"sqlite:///{DB}"
os.environ["ENVIRONMENT"] = "development"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from fastapi.testclient import TestClient
from app.main import app
from app.core.dependencies import get_current_super_admin
from app.database import Base, engine, SessionLocal

Base.metadata.create_all(bind=engine)


class FakeSuperAdmin:
    id = 1
    email = "sa@zoiko.dev"
    role = "super_admin"
    organization_id = None


app.dependency_overrides[get_current_super_admin] = lambda: FakeSuperAdmin()

client = TestClient(app)
db = SessionLocal()

# Create org through the real API.
r = client.post("/api/organizations/", json={"organization_name": "Acme Widgets"})
assert r.status_code == 200, r.text
oid = r.json()["id"]

# Seed a few org-scoped rows directly.
db.execute(text("INSERT INTO payroll_employees (organization_id, employee_code, name, status, employment_type) "
                "VALUES (:o,:c,:n,:s,:et)"), {"o": oid, "c": "E1", "n": "One", "s": "active", "et": "full_time"})
db.execute(text("INSERT INTO payroll_policies (organization_id, name, status, effective_date, is_default, calculation_mode, bank_export_format, enterprise_status) "
                "VALUES (:o,:n,:s,:e,:d,:m,:b,:es)"),
           {"o": oid, "n": "P", "s": "active", "e": "2026-01-01", "d": 1, "m": "standard", "b": "csv", "es": "not_configured"})
db.commit()

# Delete through the real endpoint.
r = client.delete(f"/api/organizations/{oid}")
assert r.status_code == 200, r.text
assert "deleted" in r.json()["message"], r.json()

# Nothing left.
for t in ["organizations", "payroll_employees", "payroll_policies"]:
    n = db.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()
    assert n == 0, f"{t} still has {n} rows"

# Second delete -> 404.
r = client.delete(f"/api/organizations/{oid}")
assert r.status_code == 404, r.text

print("RESULT: PASS - org delete endpoint ok")
db.close()
