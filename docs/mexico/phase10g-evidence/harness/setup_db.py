"""Scratch SQLite database for the Mexico Phase 10g (no-new-organisations switch) browser check.

Usage: python setup_db.py init <mode> | gen2 <mode>   (gen2 = generate the Jun 16-30 run, as the operator would)

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


from app.modules.auth.models import User  # noqa: E402

STEP = sys.argv[1] if len(sys.argv) > 1 else "init"
MODE = sys.argv[2] if len(sys.argv) > 2 else "on"
if STEP == "init":
    initialize_database()
db = SessionLocal()
patches.apply(MODE)
if STEP == "commit3":
    from app.modules.payroll import service as _svc
    from app.modules.payroll.models import PayrollEmployee, PayrollRun

    run3 = db.query(PayrollRun).filter(PayrollRun.period_label == "Jul 1-15, 2026").one()
    emps = [e.id for e in db.query(PayrollEmployee).filter(PayrollEmployee.country_code == "MX")]
    admin1 = db.query(User).filter(User.email == "admin1@mx10g.example.com").one()
    _svc.generate_payslips_for_run(db, run3, run3.organization_id, emps)
    for _ in range(2):
        _svc.advance_payroll_run_status(db, run3.id, admin1.id, run3.organization_id)
    db.refresh(run3)
    print("committed run", run3.id, run3.status, (run3.mx_approval_fingerprint or {}).get("pilot"))
    db.close()
    sys.exit(0)
if STEP == "gen2":
    from app.modules.payroll import service as _svc
    from app.modules.payroll.models import PayrollEmployee, PayrollRun

    run2 = db.query(PayrollRun).filter(PayrollRun.period_label == "Jun 16-30, 2026").one()
    emp = db.query(PayrollEmployee).filter(PayrollEmployee.country_code == "MX").first()
    _svc.generate_payslips_for_run(db, run2, run2.organization_id, [emp.id])
    print("generated run", run2.id)
    db.close()
    sys.exit(0)
from app.core.security import hash_password  # noqa: E402
from app.modules.auth.models import User, UserRole  # noqa: E402
from app.modules.organizations.models import Organization  # noqa: E402
from app.modules.payroll import service  # noqa: E402
from app.modules.payroll.models import CompanyComplianceDetails, PayrollMxIsnRegistration  # noqa: E402
from tests import _mx_run_helpers as rh  # noqa: E402

w = rh.world(db, _Patch(), code="MXB10G")
w.org.workspace_type = "EVALUATION"            # the billing guard admits evaluation workspaces
for i, u in enumerate(w.users):
    u.email = f"admin{i}@mx10g.example.com"
    u.hashed_password = hash_password(PASSWORD)
db.add(User(email="sa-a@mx10g.example.com", hashed_password=hash_password(PASSWORD), role=UserRole.SUPER_ADMIN,
            first_name="Ana", last_name="Checker", is_active=True, is_verified=True))
db.add(User(email="sa-b@mx10g.example.com", hashed_password=hash_password(PASSWORD), role=UserRole.SUPER_ADMIN,
            first_name="Beto", last_name="Reviewer", is_active=True, is_verified=True))
nl = Organization(organization_name="NL Regression Org", organization_code="NLREG10G", workspace_type="EVALUATION")
db.add(nl)
db.flush()
db.add(CompanyComplianceDetails(organization_id=nl.id, name="NL Regression Org", jurisdiction_country="NL"))
db.add(User(email="admin@nl10g.example.com", hashed_password=hash_password(PASSWORD), role=UserRole.ORG_ADMIN,
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
# A second worker, and the Jun 16-30 run of both committed (fiscal year 2026).
from tests._mx_employer_helpers import new_mx_employee, save_mx_profile  # noqa: E402
from decimal import Decimal  # noqa: E402

e2 = new_mx_employee(db, w.org.id, code="MXB10G-2", email="emp2.mxb10g@example.com", rfc="WXYZ010101AB1",
                     curp="WXYZ010101HDFXYZ01", nss="10987654321")
e2.name = "Segunda Sintética"
db.commit()
save_mx_profile(db, e2, w.org.id, effective_from=date(2026, 1, 1), mx_daily_salary=Decimal("500"),
                mx_seniority_date=date(2024, 3, 1), mx_salary_type="FIXED", mx_pay_frequency_code="04",
                mx_establishment_id=w.workplace.establishment["id"], mx_imss_registration_id=w.registration.id)
from app.modules.payroll.models import PayrollRun as _R  # noqa: E402

run2 = _R(organization_id=w.org.id, period_label="Jun 16-30, 2026", period_start=date(2026, 6, 16),
          period_end=date(2026, 6, 30), pay_date=date(2026, 6, 30), status="Draft", created_by=w.users[0].id,
          attendance_override_reason="SYNTHETIC browser check — no attendance records in the scratch DB",
          attendance_override_by=w.users[0].id, attendance_override_at=datetime.utcnow())
db.add(run2)
db.commit()
service.generate_payslips_for_run(db, run2, w.org.id, [w.employee.id, e2.id])
for _ in range(2):
    service.advance_payroll_run_status(db, run2.id, w.users[1].id, w.org.id)
db.refresh(run2)
assert run2.status == "Approved", run2.status
# SYNTHETIC CLABEs (18 digits) for both workers.
for _emp, _clabe in ((w.employee, "002180700012345678"), (e2, "012180001234567897")):
    _f = dict(_emp.compliance_fields or {})
    _f["clabe"] = _clabe
    _emp.compliance_fields = _f
db.commit()
# The synthetic packs cover 2026; a PTU of 2026 is paid in 2027.
from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab  # noqa: E402

for model in (JurisdictionPack, ContributionRate, TaxSlab):
    for row in db.query(model).filter(model.effective_to == date(2026, 12, 31)):
        row.effective_to = date(2027, 12, 31)
db.commit()
# An open ordinary run in 2027 to apply the 2026 adjustment in.
jan = _R(organization_id=w.org.id, period_label="Jan 1-15, 2027", period_start=date(2027, 1, 1),
         period_end=date(2027, 1, 15), pay_date=date(2027, 1, 15), status="Draft", created_by=w.users[0].id,
         attendance_override_reason="SYNTHETIC browser check — no attendance records in the scratch DB",
         attendance_override_by=w.users[0].id, attendance_override_at=datetime.utcnow())
db.add(jan)
db.commit()
# The Jul 1-15 run, still Draft: committed in the pilot by the commit3 step.
jul = _R(organization_id=w.org.id, period_label="Jul 1-15, 2026", period_start=date(2026, 7, 1),
         period_end=date(2026, 7, 15), pay_date=date(2026, 7, 15), status="Draft", created_by=w.users[0].id,
         attendance_override_reason="SYNTHETIC browser check — no attendance records in the scratch DB",
         attendance_override_by=w.users[0].id, attendance_override_at=datetime.utcnow())
db.add(jul)
# D2 pre-pilot evidence, SYNTHETIC: G1 G2 G4 G5 G7, Q9 and hosting, each uploaded by one Super
# Admin and reviewed by the other (the readiness view must show every pilot precondition met).
from app.modules.payroll.models import SourceArtifact  # noqa: E402

sa_a = db.query(User).filter(User.email == "sa-a@mx10g.example.com").one()
sa_b = db.query(User).filter(User.email == "sa-b@mx10g.example.com").one()
for tag in ("MX-GATE-G1", "MX-GATE-G2", "MX-GATE-G4", "MX-GATE-G5", "MX-GATE-G7", "MX-DECISION-Q9",
            "MX-DECISION-HOSTING"):
    db.add(SourceArtifact(agency="Zoiko (SYNTHETIC browser check)", title=f"{tag} evidence (SYNTHETIC)",
                          form_number=tag, created_by_id=sa_a.id, reviewer_id=sa_b.id,
                          reviewer_approved_at=datetime.utcnow(), file_path="evidence/synthetic.pdf"))
db.commit()
# ── Phase 10f: general availability, an APPROVED pilot grant, a pilot run, and a live org ──
from datetime import timedelta as _td  # noqa: E402

from app.modules.billing.models import JurisdictionServiceRegistry  # noqa: E402
from app.modules.payroll.models import PayrollMxPilotGrant  # noqa: E402

db.add(JurisdictionServiceRegistry(country="MX", availability="AVAILABLE"))     # SYNTHETIC GA (scratch DB only)
_now = datetime.utcnow()
db.add(PayrollMxPilotGrant(organization_id=w.org.id, status="APPROVED", reason="SYNTHETIC: G8 parallel run",
                           expires_at=_now + _td(days=60), proposed_by_id=sa_a.id, approved_by_id=sa_b.id,
                           approved_at=_now))
db.commit()
service.generate_payslips_for_run(db, jul, w.org.id, [w.employee.id, e2.id])
for _ in range(2):
    service.advance_payroll_run_status(db, jul.id, w.users[1].id, w.org.id)
db.refresh(jul)
assert jul.status == "Approved" and (jul.mx_approval_fingerprint or {}).get("pilot") is True, jul.mx_approval_fingerprint
# The live organisation of the SAME employer: PRODUCTION, an active subscription, its own employer profile (same RFC).
from app.modules.billing import plan_catalog  # noqa: E402
from app.modules.billing.models import BillingAuthority, BillingSubscription, SubscriptionStatus  # noqa: E402
from app.modules.payroll.models import PayrollMxEmployerProfile  # noqa: E402
from tests._mx_employer_helpers import new_employer  # noqa: E402

live = Organization(organization_name="MX Live Org (SYNTHETIC)", organization_code="MXL10G", workspace_type="PRODUCTION")
db.add(live)
db.flush()
db.add(CompanyComplianceDetails(organization_id=live.id, name="MX Live Org (SYNTHETIC)", jurisdiction_country="MX"))
for i in range(2):
    db.add(User(email=f"admin{i}@live10g.example.com", hashed_password=hash_password(PASSWORD), role=UserRole.ORG_ADMIN,
                organization_id=live.id, first_name="Live", last_name=f"Admin{i}", is_active=True, is_verified=True))
db.commit()
_plan = plan_catalog.create_plan(db, "MX10G", "SYNTHETIC browser-check plan", actor_user_id=sa_a.id)
_ver = plan_catalog.create_plan_version(db, plan_id=_plan.id, feature_set={"features": []}, scale_limits={},
                                        actor_user_id=sa_a.id)
plan_catalog.approve_plan_version(db, _ver.id, actor_user_id=sa_a.id)
_ver = plan_catalog.publish_plan_version(db, _ver.id, published_by_user_id=sa_a.id)
db.add(BillingSubscription(organization_id=live.id, plan_version_id=_ver.id,
                           billing_authority=BillingAuthority.STANDALONE.value, status=SubscriptionStatus.ACTIVE.value,
                           current_period_start=_now - _td(days=5), current_period_end=_now + _td(days=25)))
db.commit()
_rfc = db.query(PayrollMxEmployerProfile).filter(PayrollMxEmployerProfile.organization_id == w.org.id).first().rfc
_live_admin = db.query(User).filter(User.email == "admin0@live10g.example.com").one()
new_employer(db, live.id, actor=_live_admin.id, rfc=_rfc)
print("live org", live.id)
# A newcomer organisation (not Mexican yet) with one admin, and a SECOND pilot candidate (EVALUATION,
# Mexican) with a proposed grant, so a pilot approval can be tried while new organisations are paused.
newcomer = Organization(organization_name="Newcomer Org (SYNTHETIC)", organization_code="NEW10G",
                        workspace_type="EVALUATION", country="India")
db.add(newcomer)
db.flush()
db.add(User(email="admin@new10g.example.com", hashed_password=hash_password(PASSWORD), role=UserRole.ORG_ADMIN,
            organization_id=newcomer.id, first_name="New", last_name="Comer", is_active=True, is_verified=True))
cand = Organization(organization_name="Pilot Candidate (SYNTHETIC)", organization_code="CAND10G", workspace_type="EVALUATION")
db.add(cand)
db.flush()
db.add(CompanyComplianceDetails(organization_id=cand.id, name="Pilot Candidate (SYNTHETIC)", jurisdiction_country="MX"))
db.add(PayrollMxPilotGrant(organization_id=cand.id, status="PROPOSED", reason="SYNTHETIC: second pilot",
                           expires_at=_now + _td(days=30), proposed_by_id=sa_a.id))
db.commit()
print("newcomer org", newcomer.id, "candidate", cand.id)
print("ids:", {"mx_org": w.org.id, "run": w.run.id, "employee": w.employee.id, "registration": w.registration.id,
               "nl_org": nl.id})
db.close()
