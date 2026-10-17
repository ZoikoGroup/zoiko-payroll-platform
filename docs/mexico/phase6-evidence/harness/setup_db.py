"""Scratch SQLite database for the Mexico Phase 6 browser check.

Refuses any database that is not a sqlite file under the scratchpad. Users
are @example.com addresses with a test password stored only in this file.
Everything Mexican is SYNTHETIC (tests/_mx_run_helpers.py): a test-only Active
national pack + CDMX ISN pack, employer / registration / ACTIVE premium,
an ACTIVE labour policy WITHOUT a salary-days convention (so the first
generation blocks), one Mexican employee and a generated Draft run.
"""
import os
import sys
from pathlib import Path

url = os.environ.get("PAYROLL_DATABASE_URL", "")
assert url.startswith("sqlite:///") and "scratchpad" in url, f"refusing non-scratch database: {url!r}"
BACKEND = Path(r"D:\zoiko_payroll_platform\Zoiko-payroll-platform\backend")
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app.config import settings  # noqa: E402
from app.database import SessionLocal, engine, initialize_database  # noqa: E402

assert "sqlite" in str(engine.url) and "scratchpad" in str(engine.url), engine.url
initialize_database()

from app.core.security import hash_password  # noqa: E402
from app.modules.auth.models import User, UserRole  # noqa: E402
from app.modules.organizations.models import Organization  # noqa: E402
from app.modules.payroll.models import CompanyComplianceDetails  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import patches  # noqa: E402

PASSWORD = "BrowserCheck!2026"


class _Patch:                      # what pytest's monkeypatch does, for this one process
    def setattr(self, target, name, value):
        setattr(target, name, value)


db = SessionLocal()
patches.apply(flag_on=True)
from tests import _mx_run_helpers as rh  # noqa: E402

w = rh.world(db, _Patch(), convention=None, code="MXB6")
w.org.workspace_type = "EVALUATION"            # the billing guard admits evaluation workspaces
for i, u in enumerate(w.users):
    u.email = f"admin{i}@mx6.example.com"
    u.hashed_password = hash_password(PASSWORD)
db.add(User(email="sa-a@mx6.example.com", hashed_password=hash_password(PASSWORD), role=UserRole.SUPER_ADMIN,
            first_name="Ana", last_name="Checker", is_active=True, is_verified=True))
nl = Organization(organization_name="NL Regression Org", organization_code="NLREG6", workspace_type="EVALUATION")
db.add(nl)
db.flush()
db.add(CompanyComplianceDetails(organization_id=nl.id, name="NL Regression Org", jurisdiction_country="NL"))
db.add(User(email="admin@nl6.example.com", hashed_password=hash_password(PASSWORD), role=UserRole.ORG_ADMIN,
            organization_id=nl.id, first_name="Nora", last_name="Checker", is_active=True, is_verified=True))
db.commit()
from datetime import datetime  # noqa: E402

# The shared attendance gate (no attendance records exist for the synthetic
# employee) — recorded with the gate's own admin override, as an operator would.
w.run.attendance_override_reason = "SYNTHETIC browser check — no attendance records in the scratch DB"
w.run.attendance_override_by = w.users[0].id
w.run.attendance_override_at = datetime.utcnow()
db.commit()
rh.generate(db, w)
print("ids:", {"mx_org": w.org.id, "run": w.run.id, "employee": w.employee.id, "registration": w.registration.id,
               "employer": w.registration.employer_profile_id, "policy": w.policy.id})
db.close()
