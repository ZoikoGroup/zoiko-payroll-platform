"""
scripts/seed_jurisdiction_service_registry.py
-------------------------------------------------
Seeds jurisdiction_service_registry for the two jurisdictions this
codebase has real statutory engines for today: Germany and the US.
Idempotent — updates in place if a row already exists, never duplicates.

Usage:
    python -m scripts.seed_jurisdiction_service_registry
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, initialize_database
from app.modules.billing.models import JurisdictionServiceRegistry

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


def main() -> None:
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
