"""
scripts/fix_us_federal_stale_taxslabs.py
-------------------------------------------
One-off data-integrity fix (ZP-TAX-US-2026-001 §3.2 gap-closure, 2026-09-12):
the canonical (organization_id IS NULL) US federal TaxSlab rows for the
"no filing status recorded" fallback (filing_status IS NULL) contain 15
rows where there should be 8 -- an untracked, unreproducible set of 7
stale/wrong bracket rows (no 0% band, different thresholds entirely;
matches no version of ZP-TAX-US-2026-001 and isn't produced by any
current seed script) sitting alongside the 8 correct 2026 Single/MFS-
matching rows already seeded by hardcoded_defaults.py's
_TAX_SLABS_BY_COUNTRY["US"] (sort_order 1-8).

Because both sets share the same sort_order values, engine/countries/
shared.py's _calculate_annual_tax would sum ALL 15 rows together for any
employee with no w4_filing_status set -- badly wrong federal withholding.
Zero organizations have synced a copy of these canonical rows yet (verified
before writing this script), so no live payslip is affected today, but the
first US org to onboarch would be.

Deletes ONLY the 7 identified stale rows by primary key, after re-
verifying each one still matches the exact stale (min_amount, max_amount,
rate_pct) signature identified at authoring time -- refuses to delete
anything that doesn't match, in case the data has already changed.

Idempotent: safe to re-run (no-ops once the stale rows are gone).

Usage:
    python -m scripts.fix_us_federal_stale_taxslabs
"""
import sys
from pathlib import Path
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.modules.payroll.models import TaxSlab

# (id, min_amount, max_amount, rate_pct) -- the exact stale rows identified
# by inspection; used as a signature so this script refuses to delete
# anything that has since changed.
_STALE_SIGNATURE = {
    27: (Decimal("0"), Decimal("11925"), Decimal("10.00")),
    28: (Decimal("11925"), Decimal("48475"), Decimal("12.00")),
    29: (Decimal("48475"), Decimal("103350"), Decimal("22.00")),
    30: (Decimal("103350"), Decimal("197300"), Decimal("24.00")),
    31: (Decimal("197300"), Decimal("250525"), Decimal("32.00")),
    32: (Decimal("250525"), Decimal("626350"), Decimal("35.00")),
    33: (Decimal("626350"), None, Decimal("37.00")),
}


def main():
    db = SessionLocal()
    try:
        rows = db.query(TaxSlab).filter(TaxSlab.id.in_(_STALE_SIGNATURE.keys())).all()
        if not rows:
            print("No stale rows found by ID -- already cleaned up, or never present. No-op.")
            return

        to_delete = []
        for r in rows:
            expected = _STALE_SIGNATURE[r.id]
            actual = (r.min_amount, r.max_amount, r.rate_pct)
            if actual != expected:
                print(f"REFUSING to delete id={r.id}: signature mismatch (expected {expected}, got {actual}). "
                      f"Data has changed since this script was authored -- investigate manually.")
                continue
            if r.organization_id is not None or r.jurisdiction_country != "US" \
                    or r.jurisdiction_state is not None or r.filing_status is not None:
                print(f"REFUSING to delete id={r.id}: scope mismatch (org={r.organization_id}, "
                      f"country={r.jurisdiction_country}, state={r.jurisdiction_state}, "
                      f"filing_status={r.filing_status}). Investigate manually.")
                continue
            to_delete.append(r)

        for r in to_delete:
            print(f"Deleting stale TaxSlab id={r.id}: {r.min_amount}-{r.max_amount} @ {r.rate_pct}%")
            db.delete(r)
        db.commit()
        print(f"Deleted {len(to_delete)} stale row(s).")

        remaining = (
            db.query(TaxSlab)
            .filter(TaxSlab.jurisdiction_country == "US", TaxSlab.jurisdiction_state.is_(None), TaxSlab.filing_status.is_(None))
            .order_by(TaxSlab.min_amount)
            .all()
        )
        print(f"Remaining canonical US federal rows with no filing_status: {len(remaining)} (expect 8)")
        for r in remaining:
            print(f"  id={r.id} sort={r.sort_order} {r.min_amount}-{r.max_amount} @ {r.rate_pct}%")
    finally:
        db.close()


if __name__ == "__main__":
    main()
