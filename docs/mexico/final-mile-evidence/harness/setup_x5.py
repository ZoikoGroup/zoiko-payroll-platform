"""Mexico final mile X5 browser check: adds SYNTHETIC CSD credential references
to the X4 scratch database (run setup_x4.py first). One ACTIVE CSD of the
Mexican org expiring in 10 days (an EXPIRING alert), and an ACTIVE PAC
reference (never an alert). Public metadata only; the secret_ref points
nowhere. Refuses any database that is not a sqlite file under the scratchpad."""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

url = os.environ.get("PAYROLL_DATABASE_URL", "")
assert url.startswith("sqlite:///") and "scratchpad" in url, f"refusing non-scratch database: {url!r}"
BACKEND = Path(r"D:\zoiko_payroll_platform\Zoiko-payroll-platform\backend")
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app.database import SessionLocal, engine  # noqa: E402

assert "sqlite" in str(engine.url) and "scratchpad" in str(engine.url), engine.url
from app.modules.payroll.models import PayrollMxCredentialRef, PayrollMxEmployerProfile  # noqa: E402

db = SessionLocal()
profile = db.query(PayrollMxEmployerProfile).order_by(PayrollMxEmployerProfile.id).first()
now = datetime.now(timezone.utc)
for kind, days, serial in (("CSD", 10, "SYN00000000000000001"), ("PAC", 3, "SYN-PAC-REF")):
    db.add(PayrollMxCredentialRef(organization_id=profile.organization_id, employer_profile_id=profile.id, kind=kind,
                                  secret_ref=f"gcp-sm://projects/synthetic/secrets/{kind.lower()}-x5",
                                  certificate_serial=serial, fingerprint_sha256="ab" * 32,
                                  subject_summary="SYNTHETIC CSD TEST", valid_from=now - timedelta(days=355),
                                  valid_to=now + timedelta(days=days), status="ACTIVE"))
db.commit()
print("credentials added for org", profile.organization_id)
db.close()
