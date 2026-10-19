"""Scratch SQLite database for the Mexico Phase 7 browser check.

Usage: python setup_db.py init | release | replace
  init    — synthetic world (tests/_mx_run_helpers.py): Mexican org with two
            admins, three COMMITTED (Approved) runs of one employee (Jun 1-15,
            Jun 16-30, Jul 1-15), employer PAC = MOCK / SANDBOX with an ACTIVE
            synthetic CSD ref (a gcp-sm:// ref + fingerprint only); NO schema
            release yet, so the CFDI preflight blocks. Plus an NL org + Super Admin.
  release — add the SYNTHETIC Active CFDI schema release + c_MotivoCancelacion
            rows SYN1 (needs related UUID) / SYN2 (does not).
  replace — stand-in for the Phase 9 correction run: a replacement CFDI for the
            Jun 1-15 document, generated against the Jul 1-15 run.
Refuses any database that is not a sqlite file under the scratchpad."""
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
STEP = sys.argv[1]


class _Patch:                      # what pytest's monkeypatch does, for this one process
    def setattr(self, target, name, value):
        setattr(target, name, value)


if STEP == "init":
    initialize_database()
db = SessionLocal()
patches.apply(flag_on=True)
from app.modules.payroll.models import PayrollRun  # noqa: E402
from tests import _mx_cfdi_helpers as ch  # noqa: E402
from tests import _mx_run_helpers as rh  # noqa: E402

if STEP == "init":
    from app.core.security import hash_password
    from app.modules.auth.models import User, UserRole
    from app.modules.organizations.models import Organization
    from app.modules.payroll import service
    from app.modules.payroll.models import CompanyComplianceDetails

    w = rh.world(db, _Patch(), code="MXB7")
    w.org.workspace_type = "EVALUATION"            # the billing guard admits evaluation workspaces
    for i, u in enumerate(w.users):
        u.email = f"admin{i}@mx7.example.com"
        u.hashed_password = hash_password(PASSWORD)
    db.add(User(email="sa-a@mx7.example.com", hashed_password=hash_password(PASSWORD), role=UserRole.SUPER_ADMIN,
                first_name="Ana", last_name="Checker", is_active=True, is_verified=True))
    nl = Organization(organization_name="NL Regression Org", organization_code="NLREG7", workspace_type="EVALUATION")
    db.add(nl)
    db.flush()
    db.add(CompanyComplianceDetails(organization_id=nl.id, name="NL Regression Org", jurisdiction_country="NL"))
    db.add(User(email="admin@nl7.example.com", hashed_password=hash_password(PASSWORD), role=UserRole.ORG_ADMIN,
                organization_id=nl.id, first_name="Nora", last_name="Checker", is_active=True, is_verified=True))
    db.commit()
    runs = [w.run]
    for label, start, end in (("Jun 16-30, 2026", date(2026, 6, 16), date(2026, 6, 30)),
                              ("Jul 1-15, 2026", date(2026, 7, 1), date(2026, 7, 15))):
        r = PayrollRun(organization_id=w.org.id, period_label=label, period_start=start, period_end=end,
                       pay_date=end, status="Draft", created_by=w.users[0].id)
        db.add(r)
        runs.append(r)
    db.commit()
    for r in runs:
        # The shared attendance gate (no attendance records for the synthetic
        # employee) — recorded with the gate's own admin override.
        r.attendance_override_reason = "SYNTHETIC browser check — no attendance records in the scratch DB"
        r.attendance_override_by, r.attendance_override_at = w.users[0].id, datetime.utcnow()
        db.commit()
        service.generate_payslips_for_run(db, r, w.org.id, [w.employee.id])
        for _ in range(2):
            service.advance_payroll_run_status(db, r.id, w.users[1].id, w.org.id)
        db.refresh(r)
        assert r.status == "Approved", (r.id, r.status)
    ch.employer_ready(db, w)
    print("ids:", {"mx_org": w.org.id, "runs": [r.id for r in runs], "employee": w.employee.id, "nl_org": nl.id})
elif STEP == "release":
    ch.schema_release(db)
    print("synthetic schema release added")
elif STEP == "replace":
    from app.modules.payroll import mexico_cfdi_service as S
    from app.modules.payroll.models import PayrollMxCfdiDocument as D

    run1 = db.query(PayrollRun).filter(PayrollRun.period_label == "Jun 1-15, 2026").one()
    run3 = db.query(PayrollRun).filter(PayrollRun.period_label == "Jul 1-15, 2026").one()
    original = db.query(D).filter(D.payroll_run_id == run1.id, D.status == "STAMPED").one()
    (item3,) = rh.mx_items(db, run3)
    repl = S.create_replacement(db, original, run3, item3, run3.created_by)
    print("replacement:", repl.id, repl.status, "replaces", repl.replaces_uuid)
db.close()
