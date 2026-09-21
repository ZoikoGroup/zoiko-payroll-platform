"""
scripts/seed_jurisdiction_service_registry.py
-------------------------------------------------
Seeds jurisdiction_service_registry for:
  - the jurisdictions this codebase has real statutory engines for
    (Germany, US, and — 2026-09-21 — the 7 Caribbean production
    countries), marked AVAILABLE;
  - every other Caribbean jurisdiction (see app.core.caribbean_regions),
    marked PLANNED so the existing tax_resolver.get_jurisdiction_
    onboarding_block_reason gate blocks onboarding into them with a
    clean message — no new backend gating code, reusing exactly the
    mechanism DE/US already prove out.
Idempotent — updates in place if a row already exists, never duplicates.

Usage:
    python -m scripts.seed_jurisdiction_service_registry
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.caribbean_regions import CARIBBEAN_JURISDICTIONS, STATUS_ACTIVE, STATUS_COMING_SOON
from app.database import SessionLocal, initialize_database
from app.modules.billing.models import JurisdictionServiceRegistry
from scripts._local_db_guard import assert_local_database

ROWS = [
    {
        "country": "DE",
        "availability": "AVAILABLE",
        "payment_execution_responsibility": "CUSTOMER",
        "filing_responsibility": "ZOIKO",
        "remittance_responsibility": "CUSTOMER",
    },
    {
        "country": "US",
        "availability": "AVAILABLE",
        "payment_execution_responsibility": "CUSTOMER",
        "filing_responsibility": "ZOIKO",
        "remittance_responsibility": "CUSTOMER",
    },
]

# Every Caribbean code (7 ACTIVE + ~25 COMING_SOON) gets a row here too —
# ACTIVE ones as AVAILABLE (employer funds/files/remits itself, same
# responsibility shape as DE/US above until a partner/managed model is
# separately approved), COMING_SOON ones as PLANNED. Derived from the one
# Caribbean master list, never hand-duplicated, so a status change there
# is reflected here by construction.
for _code, (_name, _classification, _status) in CARIBBEAN_JURISDICTIONS.items():
    ROWS.append({
        "country": _code,
        "availability": "AVAILABLE" if _status == STATUS_ACTIVE else "PLANNED",
        "payment_execution_responsibility": "CUSTOMER" if _status == STATUS_ACTIVE else "NOT_OFFERED",
        "filing_responsibility": "ZOIKO" if _status == STATUS_ACTIVE else "NOT_OFFERED",
        "remittance_responsibility": "CUSTOMER" if _status == STATUS_ACTIVE else "NOT_OFFERED",
    })


def main() -> None:
    assert_local_database("seed_jurisdiction_service_registry")
    initialize_database()
    db = SessionLocal()
    try:
        for row in ROWS:
            existing = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == row["country"]).first()
            if existing is None:
                db.add(JurisdictionServiceRegistry(**row))
                print(f"created {row['country']}")
            else:
                for key, value in row.items():
                    setattr(existing, key, value)
                db.add(existing)
                print(f"updated {row['country']}")
        db.commit()
        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
