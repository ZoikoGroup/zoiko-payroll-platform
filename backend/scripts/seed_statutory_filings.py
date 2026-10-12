"""
scripts/seed_statutory_filings.py
----------------------------------
Seeds realistic filing-status rows into the cross-jurisdiction
`statutory_filings` table — the persisted data behind the Super Admin
Filings & Remittances dashboard. Every row is created through the SAME
validated service function the dashboard's own "record filing" action and
any org-facing UI call (payroll.service.upsert_statutory_filing), so:
  * the jurisdiction is derived from the org's configured compliance
    country, never guessed here;
  * per-(org, jurisdiction, filing type, period) uniqueness is enforced by
    the model + service, making this script idempotent (re-running updates
    the existing rows instead of duplicating).

It exists so a fresh database isn't a blank wall on the dashboard — it is
NOT an automatic process: run it once after deploying, re-run any time.

Usage:
    python -m scripts.seed_statutory_filings

Status vocabulary is the filing workflow (NOT_STARTED / IN_PROGRESS /
FILED / OVERDUE / BLOCKED), deliberately disjoint from Germany's ELSTER
transport states — Germany derives its rows from live ELSTER transmissions
and is intentionally left untouched here.
"""

import sys
from datetime import date as _date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.modules.payroll import service
from app.modules.payroll.models import CompanyComplianceDetails
from app.modules.payroll.schemas import StatutoryFilingUpsert
from app.modules.organizations.models import Organization


def _normalize(code):
    return (code or "").strip().upper() or None


def _seed_filing(db, org_id, filing_type, period_label, status, start, end, blocked_reason=None):
    existing = (
        db.query(service.StatutoryFiling)
        .filter(
            service.StatutoryFiling.organization_id == org_id,
            service.StatutoryFiling.filing_type == filing_type,
            service.StatutoryFiling.period_label == period_label,
        )
        .first()
    )
    if existing is not None and existing.status != "NOT_STARTED":
        print(f"  SKIP {org_id} {filing_type} {period_label} — already {existing.status} (id={existing.id}); not re-seeding.")
        return 0
    row = service.upsert_statutory_filing(
        db, org_id, StatutoryFilingUpsert(
            filingType=filing_type, periodLabel=period_label, periodStart=start, periodEnd=end,
            status=status, blockedReason=blocked_reason,
        ), actor_id=None,
    )
    print(f"  OK   {org_id} {filing_type} {period_label} -> {row.status} (id={row.id})")
    return 1


def main():
    db = SessionLocal()
    print("Seeding statutory filing status rows…")
    rows = (
        db.query(Organization, CompanyComplianceDetails.jurisdiction_country)
        .outerjoin(
            CompanyComplianceDetails,
            CompanyComplianceDetails.organization_id == Organization.id,
        )
        .order_by(Organization.id)
        .all()
    )
    seeded = 0
    for org, raw_country in rows:
        country = _normalize(raw_country)
        if country is None:
            print(f"  SKIP org {org.id} ({org.organization_name or '?'}) — no compliance jurisdiction set.")
            continue
        print("=" * 60)
        print(f"org {org.id} ({org.organization_name or '?'}) — {country}")
        if country == "IN":
            seeded += _seed_filing(db, org.id, "TDS", "Q4 FY2025-26 (Jan–Mar 2026)", "FILED", _date(2026, 1, 1), _date(2026, 3, 31))
            seeded += _seed_filing(db, org.id, "TDS", "Q1 FY2026-27 (Apr–Jun 2026)", "IN_PROGRESS", _date(2026, 4, 1), _date(2026, 6, 30))
            seeded += _seed_filing(db, org.id, "GST GSTR-3B", "Aug 2026", "OVERDUE", _date(2026, 8, 1), _date(2026, 8, 31), "GSTR-3B return due 20 Sep 2026 — not yet lodged.")
        elif country == "AU":
            seeded += _seed_filing(db, org.id, "BAS", "Q1 2026 (Jan–Mar)", "FILED", _date(2026, 1, 1), _date(2026, 3, 31))
            seeded += _seed_filing(db, org.id, "BAS", "Q2 2026 (Apr–Jun)", "IN_PROGRESS", _date(2026, 4, 1), _date(2026, 6, 30))
            seeded += _seed_filing(db, org.id, "STP", "FY2025-26 year-end finalisation", "FILED", _date(2025, 7, 1), _date(2026, 6, 30))
        elif country in ("US", "UK", "CA", "DE"):
            seeded += _seed_filing(db, org.id, "Income Tax", "FY2025-26 annual", "FILED", _date(2025, 4, 1), _date(2026, 3, 31))
            seeded += _seed_filing(db, org.id, "Income Tax", "Q2 2026", "IN_PROGRESS", _date(2026, 4, 1), _date(2026, 6, 30))
        else:
            print(f"  SKIP org {org.id} — no seed definition for jurisdiction {country!r}.")
    db.close()
    print("=" * 60)
    print(f"Done. {seeded} statutory filing row(s) recorded.")
    if seeded == 0:
        print("No organizations had a compliance jurisdiction or a covered country — nothing to seed.")


if __name__ == "__main__":
    main()