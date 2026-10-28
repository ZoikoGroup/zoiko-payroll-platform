"""Scratch SQLite database for the Mexico final mile X4 (parallel payroll) browser check.

Usage: python setup_x4.py

Synthetic world (tests/_mx_run_helpers.py): a Mexican org with two admins and
one COMMITTED (Approved) run (Jun 1-15, 2026) of one employee; SYNTHETIC general
availability (scratch only) so the organisation API is open while the server
runs with the onboarding flag on (serve_x4.py on); an NL org admin; a Super
Admin; the decision register. Writes the legacy CSV the check uploads
(x4_legacy.csv, SYNTHETIC, employee code only). Users are @example.com with a
test password stored only here. Refuses any database that is not a sqlite file
under the scratchpad."""
import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

url = os.environ.get("PAYROLL_DATABASE_URL", "")
assert url.startswith("sqlite:///") and "scratchpad" in url, f"refusing non-scratch database: {url!r}"
HERE = Path(__file__).resolve().parent
BACKEND = Path(r"D:\zoiko_payroll_platform\Zoiko-payroll-platform\backend")
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))
os.chdir(BACKEND)

from app.database import SessionLocal, engine, initialize_database  # noqa: E402

assert "sqlite" in str(engine.url) and "scratchpad" in str(engine.url), engine.url
import x4_patches  # noqa: E402

initialize_database()
x4_patches.apply("on")
PASSWORD = "BrowserCheck!2026"


class _Patch:                      # what pytest's monkeypatch does, for this one process
    def setattr(self, target, name, value):
        setattr(target, name, value)


from app.core.security import hash_password  # noqa: E402
from app.modules.auth.models import User, UserRole  # noqa: E402
from app.modules.billing.models import JurisdictionServiceRegistry  # noqa: E402
from app.modules.organizations.models import Organization  # noqa: E402
from app.modules.payroll import mexico_decision_service, mexico_parallel_service, service  # noqa: E402
from app.modules.payroll.models import CompanyComplianceDetails, PayslipItem  # noqa: E402
from tests import _mx_run_helpers as rh  # noqa: E402

db = SessionLocal()
w = rh.world(db, _Patch(), code="MXFMX4")
w.org.workspace_type = "EVALUATION"            # the billing guard admits evaluation workspaces
for i, u in enumerate(w.users):
    u.email = f"admin{i}@mxfm4.example.com"
    u.hashed_password = hash_password(PASSWORD)
db.add(User(email="sa-a@mxfm4.example.com", hashed_password=hash_password(PASSWORD), role=UserRole.SUPER_ADMIN,
            first_name="Ana", last_name="Checker", is_active=True, is_verified=True))
nl = Organization(organization_name="NL Regression Org", organization_code="NLREGX4", workspace_type="EVALUATION")
db.add(nl)
db.flush()
db.add(CompanyComplianceDetails(organization_id=nl.id, name="NL Regression Org", jurisdiction_country="NL"))
db.add(User(email="admin@nlfm4.example.com", hashed_password=hash_password(PASSWORD), role=UserRole.ORG_ADMIN,
            organization_id=nl.id, first_name="Nora", last_name="Checker", is_active=True, is_verified=True))
db.add(JurisdictionServiceRegistry(country="MX", availability="AVAILABLE"))     # SYNTHETIC GA (scratch DB only)
w.run.attendance_override_reason = "SYNTHETIC browser check — no attendance records in the scratch DB"
w.run.attendance_override_by, w.run.attendance_override_at = w.users[0].id, datetime.utcnow()
db.commit()
service.generate_payslips_for_run(db, w.run, w.org.id, [w.employee.id])
for _ in range(2):
    service.advance_payroll_run_status(db, w.run.id, w.users[1].id, w.org.id)
db.refresh(w.run)
assert w.run.status == "Approved" and (w.run.mx_approval_fingerprint or {}).get("committedAt"), w.run.status
print("decisions:", len(mexico_decision_service.seed_decisions(db)["added"]))
db.commit()
item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == w.run.id).one()
z = mexico_parallel_service.zoiko_amounts(item)
# The legacy file: net 12.50 lower (one difference), ISR and IMSS equal, plus an employee Zoiko never paid.
(HERE / "x4_legacy.csv").write_text(
    "Code,Net,ISR,IMSS EE\n"
    f"{w.employee.employee_code},{z['net'] - Decimal('12.50')},{z['isr_withheld']},{z['imss_employee']}\n"
    "LEGACY-ONLY-1,1000.00,0.00,0.00\n", encoding="utf-8")
ids = {"mx_org": w.org.id, "run": w.run.id, "employee_code": w.employee.employee_code, "nl_org": nl.id,
       "identifiers": [v for k, v in (w.employee.compliance_fields or {}).items()
                       if k in ("rfc", "curp", "nss", "clabe") and v]}
# The synthetic identifiers (for the acceptance leak scan) stay beside the scratch DB, never in the repo.
Path(url[len("sqlite:///"):]).with_name("x4_ids.json").write_text(json.dumps(ids), encoding="utf-8")
print("ids:", {k: v for k, v in ids.items() if k != "identifiers"})
db.close()
