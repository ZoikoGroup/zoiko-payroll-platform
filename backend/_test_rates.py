import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
DB = os.path.join(tmp, "test_rates.sqlite3")
os.environ["PAYROLL_DATABASE_URL"] = f"sqlite:///{DB}"
os.environ["ENVIRONMENT"] = "development"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from app.main import app
from app.core.dependencies import get_current_super_admin
from app.database import Base, engine

Base.metadata.create_all(bind=engine)


class FakeSuperAdmin:
    id = 1
    email = "sa@zoiko.dev"
    role = "super_admin"
    organization_id = None


app.dependency_overrides[get_current_super_admin] = lambda: FakeSuperAdmin()

client = TestClient(app)

r = client.get("/api/super-admin/statutory-rates")
assert r.status_code == 200, r.text
assert r.json() == {"rates": [], "total": 0}, r.json()

payload = {
    "jurisdiction_country": "IN",
    "component_key": "pf",
    "label": "Provident Fund",
    "employee_share": "12%",
    "employer_share": "12%",
    "total": "24%",
    "employee_rate_pct": 0.12,
    "employer_rate_pct": 0.12,
}
r = client.post("/api/super-admin/statutory-rates", json=payload)
assert r.status_code == 200, r.text
rate = r.json()
assert rate["id"] and rate["label"] == "Provident Fund", rate

r = client.post("/api/super-admin/statutory-rates", json=payload)
assert r.status_code == 409, r.text

r = client.put(f"/api/super-admin/statutory-rates/{rate['id']}", json={"employee_rate_pct": 0.125, "label": "PF v2"})
assert r.status_code == 200, r.text
assert r.json()["employee_rate_pct"] == "0.1250", r.json()

r = client.get("/api/super-admin/statutory-rates?country=IN")
assert r.status_code == 200 and r.json()["total"] == 1, r.json()

r = client.get("/api/super-admin/statutory-rates?country=US")
assert r.status_code == 200 and r.json()["total"] == 0, r.json()

r = client.delete(f"/api/super-admin/statutory-rates/{rate['id']}")
assert r.status_code == 200, r.text

r = client.get("/api/super-admin/statutory-rates")
assert r.json()["total"] == 0, r.json()

r = client.delete(f"/api/super-admin/statutory-rates/{rate['id']}")
assert r.status_code == 404, r.text

print("RESULT: PASS - statutory rates CRUD ok")
