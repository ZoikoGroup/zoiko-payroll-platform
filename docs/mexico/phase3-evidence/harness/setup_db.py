"""Throwaway SQLite database for the Mexico Phase 3 browser check.

Run with PAYROLL_DATABASE_URL pointing at a scratch sqlite file — anything
else is refused. Every user is a throwaway @example.com address (RFC 2606
reserved domain) with a throwaway password that exists only in this
scratch file; nothing here touches a shared or production database.

Since Phase 4a the Mexico organisation API is dormant by default: start the
scratch backend with MX_TENANT_ONBOARDING_ENABLED=true to re-run acceptance.py.
"""
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
from scripts.seed_mexico_canonical_packs import seed_mexico  # noqa: E402
from scripts.seed_netherlands_canonical_packs import seed_netherlands  # noqa: E402

PASSWORD = "BrowserCheck!2026"        # throwaway, scratch DB only
db = SessionLocal()


def user(email, first, role, org_id=None):
    if not db.query(User).filter(User.email == email).first():
        db.add(User(email=email, hashed_password=hash_password(PASSWORD), role=role, organization_id=org_id,
                    first_name=first, last_name="Checker", is_active=True, is_verified=True))


def org(name, code, country):
    o = db.query(Organization).filter(Organization.organization_code == code).first()
    if o is None:
        o = Organization(organization_name=name, organization_code=code, workspace_type="EVALUATION")
        db.add(o)
        db.flush()
        db.add(CompanyComplianceDetails(organization_id=o.id, name=name, jurisdiction_country=country))
    return o


user("sa-a@mx.example.com", "Ana", UserRole.SUPER_ADMIN)
mx = org("MX Browser Org", "MXBROWSER", "MX")          # ONE org admin: four-eyes must wait
user("admin@mxorg.example.com", "Olga", UserRole.ORG_ADMIN, mx.id)
user("operator@mxorg.example.com", "Pablo", UserRole.PAYROLL_ADMIN, mx.id)
other = org("MX Other Org", "MXOTHER", "MX")            # tenant isolation
user("admin@mxother.example.com", "Otto", UserRole.ORG_ADMIN, other.id)
nl = org("NL Regression Org", "NLREGRESS", "NL")         # regression: NL tabs unchanged
user("admin@nlorg.example.com", "Nora", UserRole.ORG_ADMIN, nl.id)
hk = org("HK Regression Org", "HKREGRESS", "HK")         # regression: no MX tab
user("admin@hkorg.example.com", "Hana", UserRole.ORG_ADMIN, hk.id)
db.commit()
seed_mexico(db, manifest={})          # the REAL content: empty until transcription
seed_netherlands(db)
db.commit()
print("orgs:", {o.organization_code: o.id for o in (mx, other, nl, hk)})
db.close()

# A throwaway PUBLIC certificate for the upload check: self-signed, generated
# now, written next to the scratch DB (never into the repo). Only the public
# .cer is written; the key exists in memory only and is discarded.
from datetime import datetime, timedelta, timezone  # noqa: E402

from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402

key = ec.generate_private_key(ec.SECP256R1())
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "SYNTHETIC CSD BROWSER CHECK")])
start = datetime(2026, 1, 1, tzinfo=timezone.utc)
cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(0xC0FFEE).not_valid_before(start).not_valid_after(start + timedelta(days=700))
        .sign(key, hashes.SHA256()))
cer = Path(url[len("sqlite:///"):]).parent / "synthetic_csd.cer"
cer.write_bytes(cert.public_bytes(serialization.Encoding.DER))
print("public certificate:", cer)
