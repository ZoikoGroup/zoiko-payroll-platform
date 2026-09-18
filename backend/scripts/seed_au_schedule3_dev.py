"""
scripts/seed_au_schedule3_dev.py
------------------------------------------
LOCAL DEV / VERIFICATION SCRIPT ONLY — see the production-readiness fix
plan's AU phase (2026-09-18). This does NOT touch, and is not meant to
represent, any real/staging/production database — it exists solely to
prove Schedule 3 (NAT 1023 entertainer withholding) resolves correctly
end-to-end against real DB-backed TaxSlab rows (jurisdiction_pack ->
tax_resolver -> engine), rather than only ever being exercised via
in-memory Python Slab() objects the way every existing AU test does.

Real AU canonical data (Schedule 1/8/etc.) has never been entered into
ANY local/dev database in this repo — confirmed by grepping scripts/ for
every AU rule_type and finding zero seed scripts. The comments on
TaxSlab.filing_status ("found via LIVE data entry... 2026-09-17") show
real AU data was entered directly through the Super Admin UI against a
real environment instead. This script does not attempt to reproduce that
whole dataset; it seeds ONLY the AU_SCHEDULE3_COEFFICIENT
SCHEDULE3_THRESHOLD_CLAIMED family — the one Schedule 3 coefficient table
this codebase already trusts as real, ATO-verified data (it's the exact
table tests/test_engine_standard.py's
_AU_SCHEDULE3_THRESHOLD_CLAIMED_SLABS uses, cross-validated there against
Schedule 1 Scale 4's own rate as an internal-consistency check).

Idempotent: safe to re-run (upserts by (pack_id, rule_type, filing_status,
min_amount) rather than duplicating).

Usage:
    python -m scripts.seed_au_schedule3_dev
"""

import sys
from pathlib import Path
from decimal import Decimal
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.modules.payroll.models import TaxSlab, JurisdictionPack

PACK_ID = "AU-SCHEDULE3-DEV-TEST-V1"
COUNTRY = "AU"
RULE_TYPE = "AU_SCHEDULE3_COEFFICIENT"
FAMILY = "SCHEDULE3_THRESHOLD_CLAIMED"

# (min, max, rate_pct "a", flat_amount "b") — identical to
# tests/test_engine_standard.py's _AU_SCHEDULE3_THRESHOLD_CLAIMED_SLABS.
_ROWS = [
    (Decimal("0"), Decimal("452"), Decimal("0"), Decimal("0")),
    (Decimal("452"), Decimal("673"), Decimal("0.1200"), Decimal("54.3462")),
    (Decimal("673"), Decimal("841"), Decimal("0.2000"), Decimal("108.2135")),
    (Decimal("841"), Decimal("901"), Decimal("0.1360"), Decimal("54.3473")),
    (Decimal("901"), Decimal("1081"), Decimal("0.1432"), Decimal("60.8377")),
    (Decimal("1081"), Decimal("1602"), Decimal("0.2582"), Decimal("185.1935")),
    (Decimal("1602"), Decimal("3245"), Decimal("0.2560"), Decimal("181.7319")),
    (Decimal("3245"), Decimal("4567"), Decimal("0.3120"), Decimal("363.4627")),
    (Decimal("4567"), None, Decimal("0.3760"), Decimal("655.7704")),
]


def run():
    db = SessionLocal()
    try:
        pack = db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == PACK_ID).first()
        if pack is None:
            pack = JurisdictionPack(
                pack_id=PACK_ID, jurisdiction_country=COUNTRY, pack_type="tax",
                version="1.0", status="Active",
                effective_from=date(2026, 1, 1), effective_to=None,
                compliance_owner="Dev/Verification", engineering_owner="Dev/Verification",
                regulatory_authority="ATO (NAT 1023)",
                change_summary="Local dev-only: AU Schedule 3 entertainer coefficient verification pack.",
            )
            db.add(pack)
            db.flush()
        else:
            pack.status = "Active"

        for min_amount, max_amount, rate_pct, flat_amount in _ROWS:
            row = (
                db.query(TaxSlab)
                .filter(
                    TaxSlab.jurisdiction_pack_id == pack.id,
                    TaxSlab.rule_type == RULE_TYPE,
                    TaxSlab.filing_status == FAMILY,
                    TaxSlab.min_amount == min_amount,
                )
                .first()
            )
            if row is None:
                row = TaxSlab(
                    jurisdiction_pack_id=pack.id, jurisdiction_country=COUNTRY,
                    rule_type=RULE_TYPE, filing_status=FAMILY,
                    min_amount=min_amount, rate_label="Schedule 3 coefficient",
                    tax_formula="y = a*x - b",
                )
                db.add(row)
            row.max_amount = max_amount
            row.rate_pct = rate_pct
            row.flat_amount = flat_amount

        db.commit()
        print(f"Seeded {len(_ROWS)} AU_SCHEDULE3_COEFFICIENT rows onto pack {PACK_ID} (id={pack.id}, status=Active).")
    finally:
        db.close()


if __name__ == "__main__":
    run()
