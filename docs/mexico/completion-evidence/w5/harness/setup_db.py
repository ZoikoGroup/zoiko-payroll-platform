"""Scratch SQLite database for the Mexico completion W4/W5 browser check.

Usage: python setup_db.py

The REAL Draft packs and report templates, seeded by the same scripts a
deployment would run by hand (seed_mexico_canonical_packs, the Mexico part of
seed_statutory_report_templates), against the saved source manifest. Two Super
Admins and one Netherlands org admin (regression). Users are @example.com with
a test password stored only here. Refuses any database that is not a sqlite
file under the scratchpad."""
import os
import sys
from pathlib import Path

url = os.environ.get("PAYROLL_DATABASE_URL", "")
assert url.startswith("sqlite:///") and "scratchpad" in url, f"refusing non-scratch database: {url!r}"
BACKEND = Path(r"D:\zoiko_payroll_platform\Zoiko-payroll-platform\backend")
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app.database import SessionLocal, engine, initialize_database  # noqa: E402

assert "sqlite" in str(engine.url) and "scratchpad" in str(engine.url), engine.url
initialize_database()

from app.core.security import hash_password  # noqa: E402
from app.modules.auth.models import User, UserRole  # noqa: E402
from app.modules.organizations.models import Organization  # noqa: E402
from app.modules.payroll.models import CompanyComplianceDetails  # noqa: E402
from scripts import seed_mexico_canonical_packs, seed_statutory_report_templates  # noqa: E402

PASSWORD = "BrowserCheck!2026"
db = SessionLocal()
print("packs:", seed_mexico_canonical_packs.seed_mexico(db))
db.commit()
print("templates:", len(seed_statutory_report_templates.seed_mexico(db)))
db.commit()
for email, first in (("sa-a@mxw5.example.com", "Ana"), ("sa-b@mxw5.example.com", "Beto")):
    db.add(User(email=email, hashed_password=hash_password(PASSWORD), role=UserRole.SUPER_ADMIN, first_name=first,
                last_name="Checker", is_active=True, is_verified=True))
nl = Organization(organization_name="NL Regression Org", organization_code="NLREGW5", workspace_type="EVALUATION")
db.add(nl)
db.flush()
db.add(CompanyComplianceDetails(organization_id=nl.id, name="NL Regression Org", jurisdiction_country="NL"))
db.add(User(email="admin@nlw5.example.com", hashed_password=hash_password(PASSWORD), role=UserRole.ORG_ADMIN,
            organization_id=nl.id, first_name="Nora", last_name="Checker", is_active=True, is_verified=True))
db.commit()
db.close()
print("ok")
