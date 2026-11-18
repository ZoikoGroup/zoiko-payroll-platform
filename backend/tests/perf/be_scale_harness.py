"""Belgium (ZP-BE-ENG-001) Block I2: scale harness for the Belgian code paths (local SQLite, synthetic DEMO data).

Run directly to print a measurement table (each run uses its own throwaway SQLite file):

    python -m tests.perf.be_scale_harness --employees 500 --db <scratch>/be_scale_500.db [--memory]

Steps measured (wall seconds, SQL statements, statements per payslip, optional Python peak memory via tracemalloc):
preview, generate, approve (Review -> Approved: four-eyes, ledger), payslip view x50 (the JSON the payslip screen
renders), payslip PDF x50, DmfA quarter build, Belcotax 281.10 build, parallel import (N rows; 2,000 at N=2,000).

Synthetic only: a DEMO organisation, the BE-DEMO-2026 pack (non-production), employees DEMO-00001.., two synthetic
users created in the throwaway database for four-eyes (never in any real database).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import tracemalloc
from datetime import date
from decimal import Decimal

PAY_DATE = date(2026, 9, 30)


def configure(db_path: pathlib.Path):
    os.environ["PAYROLL_DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ.pop("ZP_TEST_POSTGRES_URL", None)
    os.environ.setdefault("ENVIRONMENT", "development")


class Meter:
    def __init__(self, engine, memory: bool):
        from sqlalchemy import event

        self.count = 0
        self.memory = memory
        self.rows = []

        self.kinds = {}
        self.top = {} if os.environ.get("BE_SCALE_TOP") else None

        @event.listens_for(engine, "before_cursor_execute")
        def _count(_conn, _cursor, statement, *_a, **_k):
            self.count += 1
            kind = statement.lstrip().split(" ", 1)[0].upper()
            self.kinds[kind] = self.kinds.get(kind, 0) + 1
            if self.top is not None and kind == "SELECT":
                import re as _re

                m = _re.search(r"FROM\s+([a-z_]+)", statement)
                key = m.group(1) if m else statement[:60]
                self.top[key] = self.top.get(key, 0) + 1

    def run(self, name, fn, per=None):
        start_count = self.count
        start_kinds = dict(self.kinds)
        if self.memory:
            tracemalloc.start()
        t0 = time.perf_counter()
        value = fn()
        wall = time.perf_counter() - t0
        peak = None
        if self.memory:
            peak = tracemalloc.get_traced_memory()[1] / (1024 * 1024)
            tracemalloc.stop()
        queries = self.count - start_count
        kinds = {k: v - start_kinds.get(k, 0) for k, v in self.kinds.items() if v - start_kinds.get(k, 0)}
        self.rows.append({"step": name, "seconds": round(wall, 3), "queries": queries,
                          "perItem": round(queries / per, 2) if per else None,
                          "peakMiB": round(peak, 1) if peak is not None else None, "kinds": kinds})
        print(f"  ... {name}: {wall:.2f}s, {queries} statements", flush=True)
        if self.top is not None:
            for key, count in sorted(self.top.items(), key=lambda kv: -kv[1])[:12]:
                print(f"        {count:6d}  {key}")
            self.top.clear()
        return value


def build(n: int, memory: bool = False, bulk_ack: bool = False) -> dict:
    from app.config import settings
    from app.core import code_generation
    from app.database import Base, SessionLocal, engine
    import app.main  # noqa: F401  (registers every model)

    counter = iter(range(1, 10_000_000))                 # SQLite seam: no PostgreSQL advisory lock (as in tests)
    code_generation.generate_business_code = lambda db, org, prefix, *a, **k: f"P{prefix}{next(counter):07d}"
    settings.BE_DEMO_PACKS_ENABLED = True
    Base.metadata.create_all(engine)

    from app.modules.auth.models import User, UserRole
    from app.modules.organizations.models import Organization
    from app.modules.payroll import belgium_demo, belgium_filing as bf, belgium_parallel as bp
    from app.modules.payroll import belgium_service as be, service
    from app.modules.payroll.models import CompanyComplianceDetails, PayrollEmployee, PayrollRun, PayslipItem

    db = SessionLocal()
    org = Organization(organization_name="DEMO Scale BV", organization_code=f"BESCALE{n}", workspace_type="EVALUATION",
                       is_active=True)
    db.add(org)
    db.flush()
    settings.BE_DEMO_ORG_IDS = str(org.id)
    db.add(CompanyComplianceDetails(organization_id=org.id, name=org.organization_name, jurisdiction_country="BE",
                                    settlement_acc=belgium_demo.DEMO_IBAN_EMPLOYER))
    users = [User(email=f"scale{i}@demo.example", hashed_password="x", role=UserRole.ORG_ADMIN,
                  organization_id=org.id, first_name="Scale", last_name=str(i), is_active=True, is_verified=True)
             for i in (1, 2)]
    db.add_all(users)
    db.commit()
    a, b = users[0].id, users[1].id
    belgium_demo.be_seed_demo_pack(db, a)
    db.commit()

    def two_step(record, approve, *args):
        row = record(*args)
        db.flush()
        return approve(db, org.id, row.id, b)

    t_setup = time.perf_counter()
    reg = two_step(be.record_be_employer_registration, be.approve_be_employer_registration, db, org.id,
                   {"effective_from": "2026-01-01", "legal_name": "DEMO scale employer", "enterprise_number": "0999999999",
                    "employer_category_code": "000", "onss_special_160_status": "NOT_APPLICABLE",
                    "special_160_evidence_ref": "DEMO", "withholding_declaration_frequency": "MONTHLY"}, a, "DEMO")
    be.verify_be_employer_registration(db, org.id, reg.id, b, "VERIFIED", "DEMO")
    for name in ("basic", "hra", "special_allowance"):
        two_step(be.record_be_component_mapping, be.approve_be_component_mapping, db, org.id,
                 {"platform_component_source": "PLATFORM_FIELD", "platform_component_key": name,
                  "be_component": "SALARY", "effective_from": "2026-01-01"}, a, "DEMO mapping")
    ids = []
    for i in range(1, n + 1):
        manual = i % 2 == 0
        salary = Decimal(3400 if manual else 3800) + Decimal(i % 7) * 25
        emp = PayrollEmployee(organization_id=org.id, employee_code=f"DEMO-{i:05d}", name=f"DEMO worker {i}",
                              country_code="BE", employment_type="Full-time", pay_frequency="Monthly", ctc=salary,
                              basic=salary, hra=Decimal("0"), date_of_joining=date(2025, 1, 1),
                              compliance_fields={"iban": belgium_demo.DEMO_IBAN_MANUAL if manual
                                                 else belgium_demo.DEMO_IBAN_WHITE})
        db.add(emp)
        db.flush()
        two_step(be.record_be_worker_profile, be.approve_be_worker_profile, db, org.id, emp.id,
                 {"effective_from": "2026-01-01", "worker_category": "MANUAL" if manual else "EMPLOYEE",
                  "onss_worker_code": "015" if manual else "495", "residency": "RESIDENT", "pay_basis": "SALARIED"},
                 a, "DEMO hire")
        two_step(be.record_be_work_schedule, be.approve_be_work_schedule, db, org.id, emp.id,
                 {"effective_from": "2026-01-01", "regime": "EFFECTIVE", "weekly_hours": "38"}, a, "DEMO hire")
        two_step(be.record_be_employment_classification, be.approve_be_employment_classification, db, org.id,
                 emp.id, {"effective_from": "2026-01-01", "employment_line": "MAIN", "joint_committee": "200",
                          "function_class": "B", "seniority_months": 0, "contract_type": "INDEFINITE",
                          "contract_start_date": "2025-01-01"}, a, "DEMO hire")
        ids.append(emp.id)
        if i % 250 == 0:
            db.commit()
    db.commit()
    setup_seconds = time.perf_counter() - t_setup
    print(f"  ... setup {n} employees: {setup_seconds:.1f}s", flush=True)

    meter = Meter(engine, memory)
    meter.run("preview", lambda: service.preview_payroll_run(
        db, org.id, ids, "BE", period_start=PAY_DATE.replace(day=1), period_end=PAY_DATE, pay_date=PAY_DATE), per=n)
    run = PayrollRun(organization_id=org.id, period_label="DEMO Sep 2026", period_start=PAY_DATE.replace(day=1),
                     period_end=PAY_DATE, pay_date=PAY_DATE, created_by=a)
    db.add(run)
    db.commit()

    def generate():
        service.generate_payslips_for_run(db, run, org.id)
        db.commit()
    meter.run("generate", generate, per=n)
    service.advance_payroll_run_status(db, run.id, a, org.id)                 # Draft -> Review
    db.commit()
    pending = meter.run("preflight", lambda: [p for p in be.be_run_preflight(db, run)
                                              if p.get("exception") and p["severity"] == "BLOCK"], per=n)

    def acknowledge():
        if bulk_ack:                                   # Block J3: one batched request for every pending exception
            be.acknowledge_be_run_exceptions(db, org.id, run.id, {
                "items": [{"employeeId": p["employeeId"], "code": p["code"]} for p in pending], "reason": "DEMO"}, a)
        else:
            for p in pending:
                be.acknowledge_be_run_exception(db, org.id, run.id, {"employeeId": p["employeeId"],
                                                                     "code": p["code"], "reason": "DEMO"}, a)
        db.commit()
        return len(pending)
    meter.run("acknowledge exceptions", acknowledge, per=max(len(pending), 1))

    def approve():
        service.advance_payroll_run_status(db, run.id, b, org.id)             # Review -> Approved (ledger)
        db.commit()
    meter.run("approve", approve, per=n)
    db.refresh(run)
    items = [i.id for i in db.query(PayslipItem.id).filter_by(payroll_run_id=run.id).order_by(PayslipItem.id)]
    sample = items[:50]
    meter.run("payslip view x50", lambda: [service.get_payslip_by_id(db, i, org.id) for i in sample], per=len(sample))
    meter.run("payslip PDF x50", lambda: [service.generate_payslip_pdf_bytes(db, i, org.id) for i in sample],
              per=len(sample))

    def dmfa():
        out = bf.build_be_dmfa(db, org.id, bf.quarter_key(PAY_DATE), None, a)
        db.commit()
        return out
    meter.run("DmfA quarter build", dmfa, per=n)

    def belcotax():
        out = bf.build_be_belcotax(db, org.id, PAY_DATE.year, None, a, today=date(PAY_DATE.year + 1, 1, 15))
        db.commit()
        return out
    meter.run("Belcotax 281.10 build", belcotax, per=n)

    rows = max(n, 2000) if n >= 2000 else n
    codes = [f"DEMO-{i:05d}" for i in range(1, rows + 1)]
    csv_text = "code,gross,net\n" + "".join(f"{c},1,1\n" for c in codes)

    def parallel():
        out = bp.import_be_parallel(db, org.id, {"runId": run.id, "sourceName": "DEMO incumbent", "csv": csv_text,
                                                 "columnMap": {"employeeCode": "code", "gross": "gross",
                                                               "net": "net"}, "reason": "DEMO scale"}, a)
        db.commit()
        return out
    meter.run(f"parallel import {rows} rows", parallel, per=rows)
    db.close()
    peak_process = None
    try:                                                   # whole-process peak working set / RSS (no slowdown)
        import psutil

        info = psutil.Process().memory_info()
        peak = getattr(info, "peak_wset", None) or getattr(info, "rss", None)
        peak_process = round(peak / (1024 * 1024), 1) if peak else None
    except Exception:  # noqa: BLE001 — optional
        pass
    return {"employees": n, "setupSeconds": round(setup_seconds, 1), "processPeakMiB": peak_process,
            "steps": meter.rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--employees", type=int, required=True)
    ap.add_argument("--db", required=True, help="a NEW throwaway SQLite file (deleted first)")
    ap.add_argument("--memory", action="store_true", help="also record Python peak memory (slower)")
    ap.add_argument("--bulk-ack", action="store_true", help="acknowledge every exception in one bulk request (J3)")
    a = ap.parse_args()
    path = pathlib.Path(a.db).resolve()
    if path.suffix != ".db":
        raise SystemExit("Refused: --db must be a throwaway .db file.")
    path.unlink(missing_ok=True)
    configure(path)
    out = build(a.employees, memory=a.memory, bulk_ack=a.bulk_ack)
    print(f"{'step':28s} {'seconds':>9s} {'queries':>9s} {'q/item':>8s} {'peak MiB':>9s}")
    for r in out["steps"]:
        print(f"{r['step']:28s} {r['seconds']:9.3f} {r['queries']:9d} {str(r['perItem']):>8s} {str(r['peakMiB']):>9s}")
    print(f"process peak memory: {out['processPeakMiB']} MiB")
    print("BE-SCALE " + json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
