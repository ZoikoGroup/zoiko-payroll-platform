"""Belgium (ZP-BE-ENG-001) Block I1: does the pre-Belgium code work on a database that keeps the Belgian schema?

Scripted check (not part of the default test run: it needs the git history of the pre-Belgium commit).

    python -m scripts.be_rollback_orm_check --workdir <empty scratch dir> [--old-commit 6081174]

1. Exports the pre-Belgium code (main at alembic head f3a9c1d7e2b4, default commit 6081174) with `git archive`.
2. Builds two throwaway SQLite databases:
   CONTROL  = the old code's own schema (create_all), stamped f3a9c1d7e2b4;
   BELGIAN  = the current schema (create_all, 19 payroll_be_* tables + 2 nullable columns), stamped 8a1f5ef9fa5d,
              plus the Draft BE-PAYROLL-2026 pack (what exists after the first post-deploy step).
3. Runs the SAME basic payroll operations with the OLD code against both (organisation, compliance details,
   employees, run, payslip generation, status changes, payslip read / list / PDF, employee update / delete) for an
   existing country (IN), and compares the outcomes.
4. Runs the deploy pipeline's own steps with the OLD code against BELGIAN: `alembic upgrade head`,
   `scripts.check_schema_drift`, and `scripts/deploy_migrate.sh`, and reports what they do.
Only SQLite files under --workdir are touched.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import pathlib
import subprocess
import sys
import tarfile

HERE = pathlib.Path(__file__).resolve().parents[1]           # backend/
REPO = HERE.parent

OPS = r'''
import json, sys, traceback
from datetime import date
out = {}
def step(name, fn):
    try:
        value = fn()
        out[name] = ["ok", value]
    except Exception as exc:  # noqa: BLE001
        out[name] = ["error", f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"]
from app.database import SessionLocal
from app.core import code_generation                      # SQLite seam: no PostgreSQL advisory lock (as in tests)
_n = iter(range(1, 100000))
code_generation.generate_business_code = lambda db, org, prefix, *a, **k: f"RB{prefix}{next(_n):05d}"
from app.modules.organizations.models import Organization
from app.modules.auth.models import User, UserRole
from app.modules.payroll import service
from app.modules.payroll.models import CompanyComplianceDetails, PayrollEmployee, PayrollRun, PayslipItem
db = SessionLocal()
state = {}
def setup():
    org = Organization(organization_name="Rollback Check Ltd", organization_code="RBCHK", workspace_type="EVALUATION",
                       is_active=True)
    db.add(org); db.flush()
    db.add(CompanyComplianceDetails(organization_id=org.id, name="Rollback Check Ltd", jurisdiction_country="IN"))
    users = [User(email=f"u{i}@rollback.example", hashed_password="x", role=UserRole.ORG_ADMIN, organization_id=org.id,
                  first_name="U", last_name=str(i), is_active=True, is_verified=True) for i in (1, 2)]
    db.add_all(users); db.flush()
    emps = [PayrollEmployee(organization_id=org.id, employee_code=f"IN-{i}", name=f"Synthetic {i}", country_code="IN",
                            ctc=600000, basic=25000, hra=10000, compliance_fields={}) for i in (1, 2)]
    db.add_all(emps); db.commit()
    state.update(org=org.id, users=[u.id for u in users], emps=[e.id for e in emps])
    return len(emps)
step("setup org + 2 IN employees", setup)
def run():
    r = PayrollRun(organization_id=state["org"], period_label="Sep 2026", period_start=date(2026, 9, 1),
                   period_end=date(2026, 9, 30), pay_date=date(2026, 9, 30), created_by=state["users"][0])
    db.add(r); db.commit(); state["run"] = r.id
    return "Draft"
step("create run", run)
def generate():
    r = db.get(PayrollRun, state["run"])
    service.generate_payslips_for_run(db, r, state["org"])
    db.commit()
    return db.query(PayslipItem).filter_by(payroll_run_id=r.id).count()
step("generate payslips", generate)
def advance():
    service.advance_payroll_run_status(db, state["run"], state["users"][0], state["org"])
    db.commit()
    return str(db.get(PayrollRun, state["run"]).status)
step("advance run status", advance)
def read():
    items = db.query(PayslipItem).filter_by(payroll_run_id=state["run"]).all()
    state["items"] = [i.id for i in items]
    data = service.get_payslip_by_id(db, items[0].id, state["org"])[0] if items else None
    return sorted(k for k in (data or {}) if k in ("netPay", "employee", "country"))
step("read payslip", read)
step("list payslips", lambda: len(service.list_payslips(db, state["org"])))
step("payslip PDF", lambda: service.generate_payslip_pdf_bytes(db, state["items"][0], state["org"])[:4].decode()
     if state.get("items") else "no payslip")
def update():
    e = db.get(PayrollEmployee, state["emps"][1]); e.name = "Synthetic renamed"; db.commit(); return e.name
step("update employee", update)
def payslip_update():
    i = db.get(PayslipItem, state["items"][0]); i.notes = "rollback check"; db.commit(); return i.notes
step("update payslip", payslip_update) if state.get("items") else None
db.close()
print("OPS-RESULT " + json.dumps(out, sort_keys=True))
'''

PREP_BELGIAN = r'''
import app.main  # registers every model
from app.database import Base, engine, SessionLocal
Base.metadata.create_all(engine)
from scripts.seed_belgium_canonical_packs import seed_belgium
db = SessionLocal(); seed_belgium(db); db.commit(); db.close()
'''
PREP_CONTROL = r'''
import app.main
from app.database import Base, engine
Base.metadata.create_all(engine)
'''


def sh(args, cwd, env, stdin=None, check=True):
    done = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, input=stdin)
    if check and done.returncode != 0:
        raise SystemExit(f"FAILED {' '.join(map(str, args))}:\n{done.stdout[-2000:]}\n{done.stderr[-3000:]}")
    return done


def env_for(db: pathlib.Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("ZP_TEST_POSTGRES_URL", "DATABASE_URL")}
    env.update(PAYROLL_DATABASE_URL=f"sqlite:///{db.as_posix()}", ENVIRONMENT="development",
               ASSIST_SWEEP_ENABLED="false", TRIAL_SWEEP_ENABLED="false", SMTP_HOST="", SMTP_FROM_EMAIL="")
    return env


def ops(old_backend, db):
    done = sh([sys.executable, "-c", OPS], old_backend, env_for(db), check=False)
    line = next((ln for ln in done.stdout.splitlines() if ln.startswith("OPS-RESULT ")), None)
    if not line:
        raise SystemExit(f"ops crashed:\n{done.stdout[-2000:]}\n{done.stderr[-3000:]}")
    return json.loads(line[len("OPS-RESULT "):])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--old-commit", default="6081174")
    ap.add_argument("--shim-source", default="HEAD", help="commit holding the Belgian files (the merge)")
    a = ap.parse_args()
    work = pathlib.Path(a.workdir).resolve()
    work.mkdir(parents=True, exist_ok=True)
    old = work / "old"
    if not (old / "backend").exists():
        tar = subprocess.run(["git", "archive", "--format=tar", a.old_commit, "backend", "scripts"], cwd=REPO,
                             capture_output=True, check=True).stdout
        with tarfile.open(fileobj=io.BytesIO(tar)) as t:
            t.extractall(old)
    old_backend = old / "backend"
    heads = sh([sys.executable, "-m", "alembic", "heads"], old_backend, env_for(work / "x.db")).stdout.split()
    print(f"pre-Belgium code {a.old_commit}: alembic head {heads[0]}")

    control, belgian = work / "control.db", work / "belgian.db"
    for f in (control, belgian):
        f.unlink(missing_ok=True)
    sh([sys.executable, "-c", PREP_CONTROL], old_backend, env_for(control))
    sh([sys.executable, "-m", "alembic", "stamp", "head"], old_backend, env_for(control))
    sh([sys.executable, "-c", PREP_BELGIAN], HERE, env_for(belgian))
    sh([sys.executable, "-m", "alembic", "stamp", "head"], HERE, env_for(belgian))
    import sqlite3
    con = sqlite3.connect(belgian)
    be_tables = con.execute("select count(*) from sqlite_master where type='table' and name like 'payroll_be_%'").fetchone()[0]
    version = con.execute("select version_num from alembic_version").fetchone()[0]
    packs = con.execute("select pack_id, status from payroll_jurisdiction_packs where jurisdiction_country='BE'").fetchall()
    con.close()
    print(f"BELGIAN db: alembic {version}, {be_tables} payroll_be_* tables, BE packs {packs}")
    import shutil
    shutil.copyfile(belgian, work / "belgian_pristine.db")          # untouched copy for the shim run

    r_control, r_belgian = ops(old_backend, control), ops(old_backend, belgian)
    print("\nbasic payroll operations with the pre-Belgium code (CONTROL | BELGIAN):")
    same = True
    for name in r_control:
        c, b = r_control[name], r_belgian.get(name)
        same &= c == b
        print(f"  {name:28s} {c[0]:5s} {str(c[1])[:40]:40s} | {b[0] if b else '-':5s} {str(b[1] if b else '')[:40]}")
    print(f"ORM COMPATIBLE: {same}")

    print("\ndeploy pipeline steps with the pre-Belgium code against BELGIAN:")
    up = sh([sys.executable, "-m", "alembic", "upgrade", "head"], old_backend, env_for(belgian), check=False)
    print(f"  alembic upgrade head: exit {up.returncode}: "
          f"{(up.stderr.strip().splitlines() or [''])[-1][:160]}")
    drift = sh([sys.executable, "-m", "scripts.check_schema_drift"], old_backend, env_for(belgian), check=False)
    print(f"  check_schema_drift: exit {drift.returncode}")
    for line in drift.stdout.splitlines():
        if line.strip().startswith("-"):
            print(f"    {line.strip()}")
    bash = os.environ.get("ZP_BASH", "bash")
    pyd = str(pathlib.Path(sys.executable).parent)
    env = env_for(belgian)
    env["PATH"] = os.pathsep.join([pyd, str(pathlib.Path(pyd) / "Scripts"), env.get("PATH", "")])
    dm = sh([bash, str(old / "scripts" / "deploy_migrate.sh")], old_backend, env, check=False)
    tail = [ln for ln in (dm.stdout + dm.stderr).splitlines() if ln.strip()]
    print(f"  deploy_migrate.sh: exit {dm.returncode}")
    for line in tail[-8:]:
        print(f"    {line[:170]}")
    # 5. the same revert PLUS scripts/belgium_rollback_shim.py (built by the tool itself)
    import shutil
    sys.path.insert(0, str(HERE / "scripts"))
    import belgium_rollback_shim as shim
    shim_root = work / "shim"
    if shim_root.exists():
        shutil.rmtree(shim_root)
    shutil.copytree(old, shim_root)
    actions = shim.apply(REPO, shim_root, a.shim_source, None, dry_run=False)
    print()
    print(f"revert + rollback shim ({len(actions)} actions from {a.shim_source}):")
    shim_backend = shim_root / "backend"
    belgian2 = work / "belgian_shim.db"
    shutil.copyfile(work / "belgian_pristine.db", belgian2)
    heads2 = sh([sys.executable, "-m", "alembic", "heads"], shim_backend, env_for(work / "y.db")).stdout.split()
    env2 = env_for(belgian2)
    env2["PATH"] = env["PATH"]
    dm2 = sh([bash, str(shim_root / "scripts" / "deploy_migrate.sh")], shim_backend, env2, check=False)
    print(f"  alembic head: {heads2[0]}; deploy_migrate.sh: exit {dm2.returncode}")
    for line in [ln for ln in (dm2.stdout + dm2.stderr).splitlines() if ln.startswith(("==>", "!!"))][-5:]:
        print(f"    {line[:170]}")
    drift2 = sh([sys.executable, "-m", "scripts.check_schema_drift"], shim_backend, env2, check=False)
    print(f"  check_schema_drift: exit {drift2.returncode} ({drift2.stdout.strip().splitlines()[-1][:80]})")
    r_shim = ops(shim_backend, belgian2)
    shim_same = all(r_shim.get(k) == v for k, v in r_control.items())
    for k, v in r_control.items():
        if r_shim.get(k) != v:
            print(f"    differs: {k}: {v} | {r_shim.get(k)}")
    print(f"  basic payroll operations identical to CONTROL: {shim_same}")
    pins = sh([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *[t.replace("backend/", "", 1)
               for t in shim.PIN_TESTS]], shim_backend, env_for(work / "pins.db"), check=False)
    summary = (pins.stdout.strip().splitlines() or [""])[-1]
    print(f"  pin tests in the shim tree: exit {pins.returncode}: {summary}")
    ok = same and shim_same and dm2.returncode == 0 and drift2.returncode == 0 and pins.returncode == 0
    print(json.dumps({"ormCompatible": same, "plainRevert": {"upgradeExit": up.returncode, "driftExit":
                      drift.returncode, "deployMigrateExit": dm.returncode},
                      "revertWithShim": {"deployMigrateExit": dm2.returncode, "driftExit": drift2.returncode,
                                         "opsIdentical": shim_same, "pinTestsExit": pins.returncode}}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
