"""
scripts/seed_france_canonical_packs.py
-----------------------------------------
Seeds the canonical (organization_id IS NULL) France JurisdictionPacks
FR-2026-H1 (1 Jan – 30 Apr 2026) and FR-2026-H2 (1 May – 31 Dec 2026, the
PAS neutral-grid boundary, FR-009) with every ContributionRate row
engine/countries/france.py reads — rates AND the PASS/SMIC/RGDU/CSG/PAS
parameters (ZP-FR-ENG-001 FR-003). The rows come from ONE catalog,
app/modules/payroll/engine/countries/france_content.py, which the France
golden tests also run on.

Packs are created as **Draft**: nothing here goes live. A Super Admin
reviews/edits the rows in Super Admin → Compliance → France → Tax
Configuration, then approves and activates each pack (gate G1 — the rows
flagged PENDING_G1 in the catalog need a French payroll specialist's
sign-off first).

Insert-only and idempotent: an existing pack is never re-statused, and an
existing (component_key, effective_from) row is never overwritten, so a
re-run can never undo a Super Admin's edits. Org-scoped rows and every
other country are untouched.

Usage (a local/isolated DB only — see _local_db_guard):
    python -m scripts.seed_france_canonical_packs
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, initialize_database
from app.modules.payroll.engine.countries.france_content import (
    FR_2026_H1, FR_2026_H2, SOURCE_REFERENCES,
)
from app.modules.payroll.models import JurisdictionPack
from app.modules.payroll.service import seed_france_pack_rows
from scripts._local_db_guard import assert_local_database

COUNTRY = "FR"
VERSION = "1.0"


def _ensure_pack(db, pack_code: str, effective_from, effective_to) -> JurisdictionPack:
    pack = (
        db.query(JurisdictionPack)
        .filter(JurisdictionPack.pack_id == pack_code, JurisdictionPack.version == VERSION)
        .first()
    )
    if pack is not None:
        return pack  # never re-status or re-date an existing pack
    pack = JurisdictionPack(
        pack_id=pack_code,
        jurisdiction_country=COUNTRY,
        jurisdiction_state=None,
        pack_type="tax",
        version=VERSION,
        status="Draft",
        effective_from=effective_from,
        effective_to=effective_to,
        tax_year="2026",
        currency="EUR",
        regulatory_authority="Urssaf / DGFiP / Agirc-Arrco",
        compliance_category="Payroll tax & social contributions",
        compliance_owner="Super Admin — France",
        source_references=SOURCE_REFERENCES,
        change_summary="Initial France 2026 statutory content (seeded Draft; G1 sign-off required before activation).",
    )
    db.add(pack)
    db.flush()
    return pack


def _seed_pack_rows(db, pack: JurisdictionPack, window_from=None, window_to=None) -> int:
    """Insert-only fill from the catalog — the SAME function the Super
    Admin "Load 2026 statutory defaults" action uses (the pack's own
    effective window decides which dated rows apply)."""
    return len(seed_france_pack_rows(db, pack))


def main() -> None:
    assert_local_database("seed_france_canonical_packs")
    initialize_database()
    db = SessionLocal()
    try:
        for pack_code, window_from, window_to in (FR_2026_H1, FR_2026_H2):
            pack = _ensure_pack(db, pack_code, window_from, window_to)
            added = _seed_pack_rows(db, pack, window_from, window_to)
            db.commit()
            print(f"{pack_code} v{VERSION} [{pack.status}]: {added} row(s) added")
        print("Done. Review, approve and activate the packs in Super Admin → Compliance → France.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
