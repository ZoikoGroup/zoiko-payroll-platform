"""Scratch SQLite database for the Mexico Phase 8 browser check.

Synthetic world (tests/_mx_run_helpers.py): a Mexican org with two admins,
one COMMITTED (Approved) run (Jun 1-15, 2026) of one employee (synthetic NSS
from the test helpers), its IMSS registration and an OPEN CDMX ISN
registration; an NL org; a Super Admin. Users are @example.com with a test
password stored only here. Refuses any database that is not a sqlite file
under the scratchpad."""
import os
import sys
from datetime import date, datetime
from pathlib import Path

url = os.environ.get("PAYROLL_DATABASE_URL", "")
assert url.startswith("sqlite:///") and "scratchpad" in url, f"refusing non-scratch database: {url!r}"
BACKEND = Path(r"D:\zoiko_payroll_platform\Zoiko-payroll-platform\backend")
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app.database import SessionLocal, engine, initialize_database  # noqa: E402

assert "sqlite" in str(engine.url) and "scratchpad" in str(engine.url), engine.url
sys.path.insert(0, str(Path(__file__).resolve().parent))
import patches  # noqa: E402

PASSWORD = "BrowserCheck!2026"


class _Patch:                      # what pytest's monkeypatch does, for this one process
    def setattr(self, target, name, value):
        setattr(target, name, value)


initialize_database()
db = SessionLocal()
patches.apply(flag_on=True)
from app.core.security import hash_password  # noqa: E402
from app.modules.auth.models import User, UserRole  # noqa: E402
from app.modules.organizations.models import Organization  # noqa: E402
from app.modules.payroll import service  # noqa: E402
from app.modules.payroll.models import CompanyComplianceDetails, PayrollMxIsnRegistration  # noqa: E402
from tests import _mx_run_helpers as rh  # noqa: E402

w = rh.world(db, _Patch(), code="MXB8")
w.org.workspace_type = "EVALUATION"            # the billing guard admits evaluation workspaces
for i, u in enumerate(w.users):
    u.email = f"admin{i}@mx8.example.com"
    u.hashed_password = hash_password(PASSWORD)
db.add(User(email="sa-a@mx8.example.com", hashed_password=hash_password(PASSWORD), role=UserRole.SUPER_ADMIN,
            first_name="Ana", last_name="Checker", is_active=True, is_verified=True))
nl = Organization(organization_name="NL Regression Org", organization_code="NLREG8", workspace_type="EVALUATION")
db.add(nl)
db.flush()
db.add(CompanyComplianceDetails(organization_id=nl.id, name="NL Regression Org", jurisdiction_country="NL"))
db.add(User(email="admin@nl8.example.com", hashed_password=hash_password(PASSWORD), role=UserRole.ORG_ADMIN,
            organization_id=nl.id, first_name="Nora", last_name="Checker", is_active=True, is_verified=True))
db.add(PayrollMxIsnRegistration(organization_id=w.org.id, employer_profile_id=w.registration.employer_profile_id,
                                state_code="CDMX", local_account_number="SYN-ISN-001", jurisdiction_pack_id=w.isn.id,
                                effective_from=date(2026, 1, 1), status="OPEN"))
db.commit()
# The shared attendance gate (no attendance records for the synthetic employee) —
# recorded with the gate's own admin override, as an operator would.
w.run.attendance_override_reason = "SYNTHETIC browser check — no attendance records in the scratch DB"
w.run.attendance_override_by, w.run.attendance_override_at = w.users[0].id, datetime.utcnow()
db.commit()
service.generate_payslips_for_run(db, w.run, w.org.id, [w.employee.id])
for _ in range(2):
    service.advance_payroll_run_status(db, w.run.id, w.users[1].id, w.org.id)
db.refresh(w.run)
assert w.run.status == "Approved", w.run.status
print("ids:", {"mx_org": w.org.id, "run": w.run.id, "employee": w.employee.id, "registration": w.registration.id,
               "nl_org": nl.id})
db.close()
