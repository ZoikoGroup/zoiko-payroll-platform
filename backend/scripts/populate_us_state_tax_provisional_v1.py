"""
scripts/populate_us_state_tax_provisional_v1.py
----------------------------------------------------
Gap-closure Level 2, 2026-09-12. Seeds
hardcoded_defaults._US_STATE_TAX_RATES_PROVISIONAL (GA/ID/MS/NC/UT) as
real, Active JurisdictionPack/TaxSlab rows — but, unlike
populate_us_state_tax_v1.py's own states, these five are DELIBERATELY
KEPT OUT of shared._US_STATE_TAX_ENABLED_STATES. See that dict's own
module comment in hardcoded_defaults.py for exactly why: their numbers
come from a separate internal tracking sheet whose own source citation
doesn't hold up against ZP-TAX-US-2026-001's actual §4 Matrix content for
these five states, so they are seeded for Super Admin visibility/review
only, not switched on for real payroll until a human confirms each
figure against that state's own official withholding publication.

Deliberately kept as its own script, separate from
populate_us_state_tax_v1.py, so the two trust tiers (verified vs.
provisional) are never accidentally re-run or edited together.

Idempotent: safe to re-run (updates existing rows by
(jurisdiction_state, sort_order) rather than duplicating).

Usage:
    python -m scripts.populate_us_state_tax_provisional_v1
"""
import sys
from pathlib import Path
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.modules.payroll.models import TaxSlab, JurisdictionPack, SourceArtifact
from app.modules.payroll.hardcoded_defaults import _US_STATE_TAX_RATES_PROVISIONAL

COUNTRY = "US"
TAX_YEAR = "2026"
CURRENCY = "USD"


def _get_or_create_pack(db, state: str, change_summary: str) -> JurisdictionPack:
    pack = (
        db.query(JurisdictionPack)
        .filter(
            JurisdictionPack.pack_type == "tax",
            JurisdictionPack.jurisdiction_country == COUNTRY,
            JurisdictionPack.jurisdiction_state == state,
        )
        .first()
    )
    if pack is None:
        pack = JurisdictionPack(
            pack_id=f"US-{state}-2026-V1", jurisdiction_country=COUNTRY, jurisdiction_state=state,
            pack_type="tax", version="1.0", status="Active", tax_year=TAX_YEAR, currency=CURRENCY,
            regulatory_authority="ZP-TAX-US-2026-001", change_summary=change_summary,
        )
        db.add(pack)
        db.flush()
    else:
        pack.change_summary = change_summary
    return pack


def _get_or_create_source(db, agency: str, title: str) -> SourceArtifact:
    existing = db.query(SourceArtifact).filter(SourceArtifact.agency == agency, SourceArtifact.title == title).first()
    if existing:
        return existing
    artifact = SourceArtifact(agency=agency, title=title)
    db.add(artifact)
    db.flush()
    return artifact


def main():
    db = SessionLocal()
    try:
        count = 0
        for state, d in _US_STATE_TAX_RATES_PROVISIONAL.items():
            pack = _get_or_create_pack(
                db, state,
                change_summary=(
                    f"PROVISIONAL/UNVERIFIED — {d['source_title']}. Seeded for Super Admin visibility only; "
                    f"NOT enabled in shared._US_STATE_TAX_ENABLED_STATES. Do not enable without confirming this "
                    f"rate against {state}'s own official DOR withholding publication."
                ),
            )
            source = _get_or_create_source(db, d["agency"], d["source_title"])
            pack.source_document_id = source.id

            existing_slab = (
                db.query(TaxSlab)
                .filter(
                    TaxSlab.organization_id.is_(None), TaxSlab.jurisdiction_country == COUNTRY,
                    TaxSlab.jurisdiction_state == state, TaxSlab.sort_order == 1,
                )
                .first()
            )
            slab_fields = dict(
                min_amount=Decimal("0"), max_amount=None, rate_pct=d["rate_pct"],
                rate_label=f"{d['rate_pct']}% (PROVISIONAL)",
                tax_formula=f"Flat {d['rate_pct']}% — PROVISIONAL, unverified against a primary source",
                rule_type="FLAT_RATE", sort_order=1, jurisdiction_pack_id=pack.id,
            )
            if existing_slab:
                for k, v in slab_fields.items():
                    setattr(existing_slab, k, v)
            else:
                db.add(TaxSlab(organization_id=None, jurisdiction_country=COUNTRY, jurisdiction_state=state, **slab_fields))
            count += 1

        db.commit()
        print(f"Seeded {count} provisional state(s): {', '.join(_US_STATE_TAX_RATES_PROVISIONAL.keys())}")
        print("None of these are in shared._US_STATE_TAX_ENABLED_STATES — zero live-payroll effect until confirmed and explicitly enabled.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
