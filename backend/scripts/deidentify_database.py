"""
scripts/deidentify_database.py
------------------------------
De-identify a RESTORED COPY of a database before any non-production use
(ZP-PRIV D09). Never run against production - it refuses when ENVIRONMENT is
production and requires an explicit confirmation flag.

What it does (idempotent, safe to re-run):

1. every string column whose name is a personal / secret field (email, phone,
   address, bank, IBAN, tax and national identifiers, date of birth, names,
   passwords and tokens) in every table is replaced by a deterministic
   synthetic value (``deid-<table>-<id>``), NULL when nullable;
2. JSON columns of worker-level tables (snapshots, compliance / custom
   fields) are emptied;
3. user passwords become unusable, MFA secrets and refresh tokens are
   deleted, so no production credential works on the copy;
4. audit tables are emptied with the transaction-local purge flag (their
   append-only triggers otherwise refuse);
5. ``data_deidentified_at`` is stamped, which is what lets a non-production
   deployment start on this copy (core/nonprod_guard.py).

    PAYROLL_DATABASE_URL=<restored copy> python -m scripts.deidentify_database --confirm-nonprod-copy
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_PERSONAL = re.compile(
    r"(^|_)(email|phone|mobile|address(_line\d)?|address_\w+|postcode|bank_\w+|bank|iban|ifsc|routing|swift|"
    r"account_(no|number)|pan|uan|nino|ni_number|ssn|bsn|tfn|hkid|nric|iqama|aadhaar|passport|national_id|"
    r"tax_code|tax_id|date_of_birth|dob|first_name|last_name|full_name|name|employee_name|display_name|"
    r"hashed_password|password\w*|secret\w*|token\w*|ip|user_agent)($|_)",
    re.IGNORECASE,
)
_KEEP = {"organization_name", "plan_name", "jurisdiction_name", "bank_name", "event_type", "token_type",
         "name_key", "file_name", "filename", "rule_name", "table_name", "template_name"}
_CREDENTIAL_TABLES = ("auth_mfa_credentials", "auth_mfa_recovery_codes", "auth_refresh_tokens")


def plan(metadata) -> dict:
    from sqlalchemy import JSON, String, Text

    from app.core.audit_immutability import AUDIT_TABLES
    from app.core.authz.callgraph import worker_tables

    workers = worker_tables(metadata)
    out = {"strings": {}, "json": {}, "audit": [t for t in AUDIT_TABLES if t in metadata.tables],
           "credentials": [t for t in _CREDENTIAL_TABLES if t in metadata.tables]}
    for name, table in metadata.tables.items():
        if name in out["audit"] or name in out["credentials"]:
            continue
        cols = [c.name for c in table.columns
                if isinstance(c.type, (String, Text)) and not c.primary_key and not c.foreign_keys
                and c.name not in _KEEP and _PERSONAL.search(c.name)]
        if cols:
            out["strings"][name] = cols
        if name in workers:
            jcols = [c.name for c in table.columns if isinstance(c.type, JSON)]
            if jcols:
                out["json"][name] = jcols
    return out


def run(engine, metadata) -> dict:
    from sqlalchemy import String, cast, literal, update

    from app.core import nonprod_guard

    actions = plan(metadata)
    counts = {}
    with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            conn.exec_driver_sql("SELECT set_config('app.rls_mode', 'system', true)")
            conn.exec_driver_sql("SELECT set_config('zoiko.audit_purge', 'on', true)")
        for name, cols in actions["strings"].items():
            table = metadata.tables[name]
            values = {}
            pk = next(iter(table.primary_key.columns), None)
            for col in cols:
                column = table.c[col]
                if col == "hashed_password":
                    values[col] = "!deidentified-unusable"
                elif column.nullable:
                    values[col] = None
                elif "email" in col and pk is not None:
                    values[col] = literal(f"deid-{name}-") + cast(pk, String) + literal("@deidentified.example")
                elif pk is not None:
                    values[col] = literal(f"deid-{name}-") + cast(pk, String)
                else:
                    values[col] = "deidentified"
            counts[name] = conn.execute(update(table).values(**values)).rowcount
        for name, cols in actions["json"].items():
            table = metadata.tables[name]
            conn.execute(update(table).values(**{c: (None if table.c[c].nullable else {}) for c in cols}))
        sqlite = conn.dialect.name == "sqlite"
        if sqlite and actions["audit"]:  # SQLite twin of the transaction-local purge flag
            conn.exec_driver_sql("INSERT INTO zoiko_audit_purge_flag (reason) VALUES ('deidentify')")
        for name in actions["credentials"] + actions["audit"]:
            conn.execute(metadata.tables[name].delete())
        if sqlite and actions["audit"]:
            conn.exec_driver_sql("DELETE FROM zoiko_audit_purge_flag")
    from sqlalchemy.orm import Session

    with Session(bind=engine) as db:
        stamp = nonprod_guard.mark_deidentified(db)
    return {"deidentifiedAt": stamp, "tablesScrubbed": len(counts), "rowsTouched": sum(c or 0 for c in counts.values()),
            "jsonColumnsEmptied": sum(len(v) for v in actions["json"].values()),
            "auditTablesEmptied": actions["audit"], "credentialTablesEmptied": actions["credentials"]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="De-identify a restored non-production database copy.")
    parser.add_argument("--confirm-nonprod-copy", action="store_true",
                        help="required: confirms the target is a restored copy, never production")
    parser.add_argument("--plan", action="store_true", help="print what would change and exit")
    args = parser.parse_args(argv)

    from app.core import nonprod_guard

    if nonprod_guard.is_production():
        print("REFUSING: ENVIRONMENT is production. De-identification only runs on a non-production copy.",
              file=sys.stderr)
        return 2
    from app.database import Base, engine

    if args.plan:
        print(json.dumps(plan(Base.metadata), indent=2, sort_keys=True))
        return 0
    if not args.confirm_nonprod_copy:
        print("REFUSING: pass --confirm-nonprod-copy to confirm the target is a restored non-production copy.",
              file=sys.stderr)
        return 2
    print(json.dumps(run(engine, Base.metadata), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
