"""Throwaway SQLite database for the Mexico Phase 2 browser check.
Run with PAYROLL_DATABASE_URL pointing at a scratch sqlite file — refuses anything else."""
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
from scripts.seed_mexico_canonical_packs import seed_mexico  # noqa: E402
from scripts.seed_netherlands_canonical_packs import seed_netherlands  # noqa: E402
from scripts.seed_statutory_report_templates import seed_mexico as seed_mx_templates  # noqa: E402

db = SessionLocal()
for email, first in (("sa-a@mxbrowsercheck.io", "Ana"), ("sa-b@mxbrowsercheck.io", "Beto")):
    if not db.query(User).filter(User.email == email).first():
        db.add(User(email=email, hashed_password=hash_password("BrowserCheck!2026"), role=UserRole.SUPER_ADMIN,
                    organization_id=None, first_name=first, last_name="Checker", is_active=True, is_verified=True))
db.commit()
out = seed_mexico(db, manifest={})          # the REAL content: empty until transcription
seed_mx_templates(db, manifest={})
seed_netherlands(db)                        # regression: an NL workspace with real Draft packs
db.commit()
print("MX packs:", out["national"].pack_id, out["isn"]["CDMX"].pack_id)
db.close()
