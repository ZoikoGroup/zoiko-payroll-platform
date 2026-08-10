import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
DB = os.path.join(tmp, "smoke_frontend.sqlite3")
os.environ["PAYROLL_DATABASE_URL"] = f"sqlite:///{DB}"
os.environ["ENVIRONMENT"] = "development"

sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from app.main import app
from app.core.security import hash_password
from app.database import Base, engine, SessionLocal
from app.modules.auth.models import User, UserRole
from app.modules.organizations.models import Organization

Base.metadata.create_all(bind=engine)
db = SessionLocal()
db.add(User(
    email="admin@example.com",
    hashed_password=hash_password("strong-password"),
    role=UserRole.SUPER_ADMIN,
    first_name="Platform",
    last_name="Admin",
    is_active=True,
))
db.commit()

c = TestClient(app)
ok = True

def check(label, cond, extra=""):
    global ok
    print(("PASS" if cond else "FAIL"), "-", label, extra)
    if not cond:
        ok = False

r = c.post("/api/auth/login", json={"email": "admin@example.com", "password": "strong-password"})
check("login", r.status_code == 200, str(r.status_code))
data = r.json()
tok = data.get("access_token", "")
check("token present", bool(tok))
check("user role super_admin", data.get("user", {}).get("role") == "super_admin")

h = {"Authorization": f"Bearer {tok}"}

r = c.get("/api/super-admin/dashboard/stats", headers=h)
check("dashboard stats", r.status_code == 200, str(r.status_code))

r = c.get("/api/super-admin/users", headers=h)
check("users list", r.status_code == 200, str(r.status_code))
check("users shape", "users" in r.json() and "total" in r.json())

r = c.get("/api/super-admin/statutory-rates", headers=h)
check("statutory rates list", r.status_code == 200, str(r.status_code))

r = c.get("/api/super-admin/settings", headers=h)
check("settings list", r.status_code == 200, str(r.status_code))

r = c.get("/api/organizations/", headers=h)
check("orgs list", r.status_code == 200, str(r.status_code))
check("orgs shape", "organizations" in r.json() and "total" in r.json())

r = c.get("/api/auth/me", headers=h)
check("me", r.status_code == 200, str(r.status_code))

print("\nALL OK" if ok else "\nSOME FAILED")
sys.exit(0 if ok else 1)
