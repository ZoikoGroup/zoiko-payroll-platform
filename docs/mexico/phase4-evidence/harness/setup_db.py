"""Scratch SQLite database for the Mexico Phase 4 browser check.

Refuses any database that is not a sqlite file under the scratchpad. Users
are @example.com addresses with a test password stored only in this file.
Mexican fixtures are created here with the Mexico flag switched on for this
process only; the backend is started separately, once with the flag off and
once with it on.
"""
import os
import sys
from pathlib import Path

url = os.environ.get("PAYROLL_DATABASE_URL", "")
assert url.startswith("sqlite:///") and "scratchpad" in url, f"refusing non-scratch database: {url!r}"
BACKEND = Path(r"D:\zoiko_payroll_platform\Zoiko-payroll-platform\backend")
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))
os.chdir(BACKEND)

from app.config import settings  # noqa: E402
from app.database import SessionLocal, engine, initialize_database  # noqa: E402

assert "sqlite" in str(engine.url) and "scratchpad" in str(engine.url), engine.url
settings.MX_TENANT_ONBOARDING_ENABLED = True
initialize_database()

from app.core.security import hash_password  # noqa: E402
from app.modules.auth.models import User, UserRole  # noqa: E402
from app.modules.organizations.models import Organization  # noqa: E402
from app.modules.payroll.models import CompanyComplianceDetails, ComplianceDocument  # noqa: E402
from scripts.seed_mexico_canonical_packs import seed_mexico  # noqa: E402
from tests._mx_employer_helpers import mx_workplace, new_mx_employee  # noqa: E402

PASSWORD = "BrowserCheck!2026"
db = SessionLocal()


def user(email, first, role, org_id=None):
    db.add(User(email=email, hashed_password=hash_password(PASSWORD), role=role, organization_id=org_id,
                first_name=first, last_name="Checker", is_active=True, is_verified=True))


def org(name, code, country):
    o = Organization(organization_name=name, organization_code=code, workspace_type="EVALUATION")
    db.add(o)
    db.flush()
    if country:
        db.add(CompanyComplianceDetails(organization_id=o.id, name=name, jurisdiction_country=country))
    return o


user("sa-a@mx.example.com", "Ana", UserRole.SUPER_ADMIN)
mx = org("MX Browser Org", "MXBROWSER", "MX")
user("admin@mxorg.example.com", "Olga", UserRole.ORG_ADMIN, mx.id)
blank = org("New Org Without Jurisdiction", "NEWORG", None)
user("admin@neworg.example.com", "Nico", UserRole.ORG_ADMIN, blank.id)
nl = org("NL Regression Org", "NLREGRESS", "NL")
user("admin@nlorg.example.com", "Nora", UserRole.ORG_ADMIN, nl.id)
db.commit()
seed_mexico(db, manifest={})
db.commit()

place = mx_workplace(db, mx.id)
emp = new_mx_employee(db, mx.id)
doc = ComplianceDocument(organization_id=mx.id, title="Synthetic INFONAVIT notice", file_path="synthetic.pdf",
                         file_name="synthetic.pdf", country="MX")
db.add(doc)
db.commit()
print("ids:", {"mx_org": mx.id, "employee": emp.id, "establishment": place.establishment["id"],
               "registration": place.registration["id"], "evidence_doc": doc.id})
db.close()
