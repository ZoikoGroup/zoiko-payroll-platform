"""READ-ONLY: would each existing tax pack's tax year pass the tax-year rule if
its tax year or dates were edited?

Reads every tax pack (SELECT only) and applies the same rule the pack
create / edit applies (backend/app/modules/payroll/tax_year_rules.py). It
writes, updates or deletes NOTHING: on PostgreSQL the transaction is set READ
ONLY, and the session is always rolled back. Existing records are never
refused or altered by the rule itself — this only shows which ones a future
edit of their tax year or dates would ask to correct.

Run from the backend directory (uses the configured database; prefer a
read-only role):
    cd backend && python ../scripts/readonly/check_pack_tax_years.py
"""
from __future__ import annotations

import os
import sys

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "backend")
sys.path.insert(0, os.path.abspath(BACKEND))


def report(db) -> list:
    """[(country, pack id, version, status, tax year, from, to, refusal or None)] — reads only."""
    from app.modules.payroll.models import JurisdictionPack
    from app.modules.payroll.tax_year_rules import tax_year_date_refusal

    packs = (db.query(JurisdictionPack).filter(JurisdictionPack.pack_type == "tax")
             .order_by(JurisdictionPack.jurisdiction_country, JurisdictionPack.pack_id, JurisdictionPack.version).all())
    return [(p.jurisdiction_country, p.pack_id, p.version, p.status, p.tax_year, p.effective_from, p.effective_to,
             tax_year_date_refusal(p.tax_year, p.effective_from, p.effective_to)) for p in packs]


def main() -> int:
    from sqlalchemy import text

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SET TRANSACTION READ ONLY"))
        rows = report(db)
    finally:
        db.rollback()
        db.close()
    print(f"{'country':7} {'pack':30} {'ver':6} {'status':10} {'tax year':11} {'from':11} {'to':11} verdict")
    for country, pack, version, status, tax_year, start, end, refusal in rows:
        verdict = "PASS" if refusal is None else f"WOULD ASK TO CORRECT: {refusal}"
        print(f"{country:7} {pack[:30]:30} {version:6} {status:10} {str(tax_year):11} {str(start):11} {str(end):11} "
              f"{verdict}")
    flagged = [r for r in rows if r[7]]
    print(f"\n{len(rows)} tax packs, {len({r[0] for r in rows})} countries; "
          f"{len(flagged)} would be asked to correct their tax year on a date / tax-year edit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
