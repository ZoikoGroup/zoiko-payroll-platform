"""
scripts/report_paused_countries.py
----------------------------------
READ-ONLY report of every country still paused (organization_jurisdictions
.status = 'OVER_LIMIT') by the earlier "downgrade pauses the extra
countries" rule. The current rule never pauses or reactivates anything
automatically, so these rows keep their state until someone reviews them;
re-adding the country under Compliance > Countries reactivates it like any
other add (within the plan's limit).

For each paused country it reports the organization, the country, when it
was paused and why: the most recent JURISDICTION_LIMIT_RECONCILED event
(plan change, trial conversion, override expiry, ...) or
JURISDICTION_LEDGER_BACKFILLED event that named it, with the limit at that
time — plus the org's current plan, limit, active countries and how many
employees are in the paused country.

Strictly read-only: the session's transaction is made read-only at the
database level before the first query (PostgreSQL SET TRANSACTION READ ONLY,
SQLite PRAGMA query_only), so any write — by this script or by a helper it
calls — is refused by the database itself; it never commits and always ends
with a rollback. tests/test_report_paused_countries.py records every SQL
statement it issues and asserts there is no INSERT/UPDATE/DELETE or commit.

Usage (never writes; runs against whatever PAYROLL_DATABASE_URL points at):
    python -m scripts.report_paused_countries            # table
    python -m scripts.report_paused_countries --csv out.csv
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PAUSE_EVENTS = ("JURISDICTION_LIMIT_RECONCILED", "JURISDICTION_LEDGER_BACKFILLED")
COLUMNS = ["organization_id", "organization_name", "country_code", "country", "paused_at", "paused_by_event",
           "pause_reason", "limit_at_pause", "current_plan", "current_limit", "active_countries",
           "employees_in_country", "row_activated_at"]


def make_read_only(db) -> str:
    """Make db's current transaction read-only at the database level, before
    any other statement. Returns the dialect name; refuses unknown dialects
    rather than running without the guarantee."""
    from sqlalchemy import text

    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        db.execute(text("SET TRANSACTION READ ONLY"))
    elif dialect == "sqlite":
        db.execute(text("PRAGMA query_only = ON"))
    else:
        raise RuntimeError(f"report_paused_countries: no read-only mode for dialect {dialect!r}; refusing to run")
    return dialect


def _pause_event(events, country_code):
    """The latest pause event whose payload named this country."""
    for ev in events:  # newest first
        named = (ev.payload or {}).get("over_limit") or []
        if country_code in named:
            return ev
    return None


def collect(db) -> list[dict]:
    from app.modules.billing.entitlements import _current_plan_code, get_active_subscription
    from app.modules.billing.jurisdiction_entitlement import (
        ACTIVE, OVER_LIMIT, country_name, employee_country_counts, resolve_country_limit,
    )
    from app.modules.billing.models import BillingCommercialAuditEvent, OrganizationJurisdiction
    from app.modules.organizations.models import Organization

    paused = (
        db.query(OrganizationJurisdiction)
        .filter(OrganizationJurisdiction.status == OVER_LIMIT)
        .order_by(OrganizationJurisdiction.organization_id, OrganizationJurisdiction.country_code)
        .all()
    )
    out = []
    for org_id in sorted({r.organization_id for r in paused}):
        org = db.query(Organization).filter(Organization.id == org_id).first()
        events = (
            db.query(BillingCommercialAuditEvent)
            .filter(BillingCommercialAuditEvent.organization_id == org_id,
                    BillingCommercialAuditEvent.event_type.in_(PAUSE_EVENTS))
            .order_by(BillingCommercialAuditEvent.created_at.desc(), BillingCommercialAuditEvent.id.desc())
            .all()
        )
        active = [r.country_code for r in db.query(OrganizationJurisdiction).filter(
            OrganizationJurisdiction.organization_id == org_id, OrganizationJurisdiction.status == ACTIVE).all()]
        counts = employee_country_counts(db, org_id)
        for row in (r for r in paused if r.organization_id == org_id):
            ev = _pause_event(events, row.country_code)
            payload = (ev.payload or {}) if ev else {}
            out.append({
                "organization_id": org_id,
                "organization_name": org.organization_name if org else None,
                "country_code": row.country_code,
                "country": country_name(row.country_code),
                "paused_at": ev.created_at.isoformat() if ev else None,
                "paused_by_event": ev.event_type if ev else None,
                "pause_reason": payload.get("reason") or ("backfill" if ev and ev.event_type.endswith("BACKFILLED")
                                                          else "unknown (no audit event names this country)"),
                "limit_at_pause": payload.get("limit_value"),
                "current_plan": _current_plan_code(db, get_active_subscription(db, org_id)),
                "current_limit": resolve_country_limit(db, org_id),
                "active_countries": ", ".join(active),
                "employees_in_country": int(counts.get(row.country_code, 0)),
                "row_activated_at": row.activated_at.isoformat() if row.activated_at else None,
            })
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--csv", help="write the report to this CSV file")
    args = parser.parse_args(argv)

    from app.database import SessionLocal

    db = SessionLocal()
    dialect = None
    try:
        dialect = make_read_only(db)
        rows = collect(db)
    finally:
        db.rollback()  # never commit; ends the read-only transaction
        if dialect == "sqlite":
            from sqlalchemy import text

            # query_only is connection-scoped on SQLite: don't hand a
            # read-only connection back to the pool.
            db.execute(text("PRAGMA query_only = OFF"))
        db.close()

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        print(f"{len(rows)} paused countries written to {args.csv}")
        return 0
    print(f"Paused countries (OVER_LIMIT, earlier rule): {len(rows)}")
    for r in rows:
        print(f"  org #{r['organization_id']} {r['organization_name']}: {r['country']} ({r['country_code']}) — "
              f"paused {r['paused_at'] or '?'} by {r['paused_by_event'] or '?'} ({r['pause_reason']}, "
              f"limit then {r['limit_at_pause']}); now plan {r['current_plan']} limit {r['current_limit']}, "
              f"active {r['active_countries'] or '-'}, {r['employees_in_country']} employee(s) there")
    return 0


if __name__ == "__main__":
    sys.exit(main())
