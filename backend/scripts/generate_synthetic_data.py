"""
scripts/generate_synthetic_data.py
----------------------------------
Seed synthetic tenants and workers into a LOCAL non-production database
(ZP-PRIV D09). Every identity value comes from app/core/synthetic.py:
reserved-domain emails and identifiers that fail real checksums.

Idempotent: tenants are keyed by code SYN001..SYNnnn and workers by
employee code; re-running only adds what is missing. Refuses to run when
ENVIRONMENT is production or the database is not local
(scripts/_local_db_guard.py).

    PAYROLL_DATABASE_URL=sqlite:///./synthetic.sqlite3 python -m scripts.generate_synthetic_data --tenants 3 --workers 25
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def seed(db, tenants: int, workers: int) -> dict:
    from app.core import synthetic
    from app.modules.organizations.models import Organization
    from app.modules.payroll.models import PayrollEmployee

    created_orgs = created_workers = 0
    for t in range(1, tenants + 1):
        code = f"SYN{t:03d}"
        org = db.query(Organization).filter(Organization.organization_code == code).first()
        if org is None:
            org = Organization(organization_name=f"Synthetic Tenant {t}", organization_code=code,
                               workspace_type="EVALUATION", is_active=True)
            db.add(org)
            db.flush()
            created_orgs += 1
        from app.core.authz import tenant_context

        with tenant_context.tenant_session(db, org.id):
            existing = {c for (c,) in db.query(PayrollEmployee.employee_code)
                        .filter(PayrollEmployee.organization_id == org.id).all()}
            for w in range(1, workers + 1):
                emp_code = f"{code}-{w:04d}"
                if emp_code in existing:
                    continue
                n = t * 10000 + w
                p = synthetic.person(n, code)
                db.add(PayrollEmployee(organization_id=org.id, employee_code=emp_code, name=p["name"],
                                       email=p["email"], phone=p["phone"], bank_account=p["bank_account"],
                                       pan=p["pan"], tax_code=p["tax_code"], address_line1=p["address_line1"],
                                       ctc=30000 + (n % 50) * 1000, basic=15000, hra=0))
                created_workers += 1
    db.commit()
    return {"tenantsCreated": created_orgs, "workersCreated": created_workers}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Seed synthetic tenants and workers (non-production only).")
    parser.add_argument("--tenants", type=int, default=2)
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args(argv)

    from app.core import nonprod_guard

    if nonprod_guard.is_production():
        print("REFUSING: ENVIRONMENT is production.", file=sys.stderr)
        return 2
    from scripts._local_db_guard import assert_local_database

    assert_local_database("generate_synthetic_data")
    from app.database import SessionLocal, initialize_database

    initialize_database()
    db = SessionLocal()
    try:
        print(json.dumps(seed(db, args.tenants, args.workers)))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
