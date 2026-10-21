"""
scripts/migrate_privacy_rollout.py
----------------------------------
Apply the ZP-PRIV migrations (a7c3e91f2b60 .. e1a3c5e7f9b2) to the database in
PAYROLL_DATABASE_URL without breaking app instances that still run the
previous code.

Why the extra step: migration d7f9b1c3e5a6 turns on FORCE ROW LEVEL SECURITY.
The new code sets ``app.rls_mode`` on every transaction; the previous code
never does, and would then see no worker rows. Running the migration with
ZP_RLS_UNSET_MODE=system stores 'system' as the mode for a connection that
sets none (table zoiko_rls_settings), so old code keeps working unchanged
while new code still sets its mode per transaction.

Steps:
  1. preflight (read-only): revision, prerequisites, no half-applied tables
  2. alembic upgrade head with ZP_RLS_UNSET_MODE=system (one transaction:
     every migration or none)
  3. verify: revision is e1a3c5e7f9b2 and worker rows are still visible
     to a connection that sets no mode (the old-code path)

    cd backend && python -m scripts.migrate_privacy_rollout              # preflight only
    cd backend && python -m scripts.migrate_privacy_rollout --apply      # do it

Rollback: ``alembic downgrade f5c1a8d3e9b2``. Once every instance runs the
new code: ``UPDATE zoiko_rls_settings SET unset_mode = ''`` (strict).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

FROM_REV, TO_REV = "f5c1a8d3e9b2", "e1a3c5e7f9b2"
NEEDED = ("users", "organizations", "legal_entities", "payroll_employees", "payslip_items", "platform_settings")
CREATED = ("authz_decision_events", "pay_groups", "user_scope_assignments", "auth_mfa_credentials",
           "auth_refresh_tokens", "support_access_grants", "support_access_audit_events", "security_events",
           "alert_rules", "machine_clients", "zoiko_rls_settings")


def preflight(engine) -> dict:
    from sqlalchemy import inspect, text

    tables = set(inspect(engine).get_table_names())
    with engine.connect() as c:
        rev = c.execute(text("SELECT version_num FROM alembic_version")).scalar()
        user = c.execute(text("SELECT current_user")).scalar()
        workers = c.execute(text("SELECT count(*) FROM payroll_employees")).scalar()
    return {"host": engine.url.host, "database": engine.url.database, "revision": rev, "user": user,
            "workerRows": workers, "missingPrerequisites": [t for t in NEEDED if t not in tables],
            "alreadyPresent": [t for t in CREATED if t in tables]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Apply the ZP-PRIV migrations safely.")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    from sqlalchemy import text

    from app.database import engine

    pf = preflight(engine)
    print("preflight:", pf)
    if pf["revision"] == TO_REV:
        print("Already at", TO_REV)
        return 0
    if pf["revision"] != FROM_REV or pf["missingPrerequisites"] or pf["alreadyPresent"]:
        print(f"STOP: expected revision {FROM_REV}, all prerequisites, and none of the new tables.")
        return 2
    if not args.apply:
        print("Preflight OK. Re-run with --apply to migrate.")
        return 0

    proc = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=str(BACKEND),
                          env={**os.environ, "ZP_RLS_UNSET_MODE": "system"})
    if proc.returncode != 0:
        print("STOP: alembic upgrade failed (the migration transaction was rolled back).")
        return 1
    engine.dispose()
    with engine.connect() as c:  # a plain connection = how the previous code connects
        rev = c.execute(text("SELECT version_num FROM alembic_version")).scalar()
        rows = c.execute(text("SELECT count(*) FROM payroll_employees")).scalar()
        mode = c.execute(text("SELECT zoiko_rls_mode()")).scalar()
    print({"revision": rev, "workerRowsVisibleToOldCode": rows, "unsetMode": mode})
    if rev != TO_REV or rows != pf["workerRows"]:
        print("CHECK FAILED: revision or visible worker rows differ from before.")
        return 1
    print("OK: migrated; existing app instances still see all rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
