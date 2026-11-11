"""
scripts/backfill_organization_jurisdictions.py
------------------------------------------------
Seeds the country entitlement ledger (organization_jurisdictions, created by
alembic revision b4d6f8a0c2e3) for every existing organization. Run once
right after that migration, and again just before switching
BILLING_ENFORCEMENT_MODE from "warn" to "enforce" to pick up countries
added while the switch was "off".

Per organization (billing.jurisdiction_entitlement.backfill_organization):
  1. primary = effective org country (CompanyComplianceDetails.
     jurisdiction_country, else Organization.country)
  2. + every distinct PayrollEmployee.country_code in use
  3. + every EnterpriseJurisdiction.country_code
  4. rows beyond the plan's max_jurisdictions -> OVER_LIMIT (nothing is
     deleted, nothing is refused); orgs with no subscription have no limit

Idempotent: only missing rows are added, and the limit reconcile is
deterministic, so a second run reports zero rows created.

Usage:
    python -m scripts.backfill_organization_jurisdictions [--dry-run]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def run(db, dry_run: bool = False) -> dict:
    from app.modules.billing.jurisdiction_entitlement import backfill_organization
    from app.modules.organizations.models import Organization

    summary = {"orgs_processed": 0, "rows_created": 0, "orgs_over_limit": [], "orgs_unresolved": []}
    for org_id, name in db.query(Organization.id, Organization.organization_name).order_by(Organization.id).all():
        result = backfill_organization(db, org_id)
        summary["orgs_processed"] += 1
        summary["rows_created"] += len(result["created"])
        if result["over_limit"]:
            summary["orgs_over_limit"].append({"id": org_id, "name": name, "over_limit": result["over_limit"]})
        if result["unresolved"]:
            summary["orgs_unresolved"].append({"id": org_id, "name": name})
    if dry_run:
        db.rollback()
    else:
        db.commit()
    return summary


def print_summary(summary: dict, dry_run: bool = False) -> None:
    print(f"Country entitlement backfill{' (dry run, rolled back)' if dry_run else ''}")
    print(f"  orgs processed:              {summary['orgs_processed']}")
    print(f"  rows created:                {summary['rows_created']}")
    print(f"  orgs flagged OVER_LIMIT:     {len(summary['orgs_over_limit'])}")
    for org in summary["orgs_over_limit"]:
        print(f"    - #{org['id']} {org['name']}: {', '.join(org['over_limit'])}")
    print(f"  orgs with no resolvable country: {len(summary['orgs_unresolved'])}")
    for org in summary["orgs_unresolved"]:
        print(f"    - #{org['id']} {org['name']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--dry-run", action="store_true", help="compute and report, then roll back")
    args = parser.parse_args()

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        print_summary(run(db, dry_run=args.dry_run), dry_run=args.dry_run)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
