"""
scripts/seed_mexico_canonical_packs_v1_1.py
-------------------------------------------
Seeds MX-PAYROLL-2026 **v1.1** as a new DRAFT version of the canonical
(organization_id IS NULL) Mexico federal pack, next to v1.0, which is left
exactly as it is.

What v1.1 adds, both transcribed into engine/countries/mexico_content.py:
  * ``mx_rounding_rule = HALF_UP:0.01`` — owner decision D-01, option A
    (docs/mexico/D01_ROUNDING_DECISION_BRIEF.md), citing S30 (CFDI 4.0 Guía de
    llenado Q37/Q39). One of MX_REQUIRED_TEXT_KEYS: pack approval refused v1.0
    ("the content lacks required parameters: mx_rounding_rule").
  * ``mx_ceav_lowest_band_min_wage_ref = GENERAL`` — owner decision D-03,
    citing S11. Read for every SBC: without it every calculation blocks
    (MX_CONTENT_MISSING).
Every other row is the same content v1.0 was seeded from.

How: the same row builder as scripts/seed_mexico_canonical_packs.py, so v1.1
is exactly the current content — what the approval check compares a pack
against (every expected row, no extras). v1.1 records v1.0 as its
previous_version_id, the link Super Admin's "new version" makes.

Governance (unchanged from the v1.0 seed):
  * DRAFT only — nothing is approved or activated here; v1.1 goes live only
    through Mexico's four-eyes approval and activation gates (G1–G8, sources).
  * Re-running rewrites v1.1's rows while it is still Draft, and refuses once
    it has entered review/approval.
  * v1.0 and the CDMX ISN pack are not touched.
  * The same strict guard: ZOIKO_ALLOW_NONLOCAL_DB_WRITES=I_UNDERSTAND plus an
    interactive CONFIRM after the target database is printed.

Usage:
    python -m scripts.seed_mexico_canonical_packs_v1_1
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, initialize_database  # noqa: E402
from app.modules.payroll.engine.countries import mexico_content as content  # noqa: E402
from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab  # noqa: E402
from scripts.seed_mexico_canonical_packs import (  # noqa: E402
    CODE, MAIN_PACK_ID, SPEC, _cited_sources, _require_confirmed_target, _seed_national_pack, _upsert_sources,
    load_manifest,
)

TAG = "seed_mexico_canonical_packs_v1_1"
VERSION = "1.1"
PREVIOUS_VERSION = "1.0"
CHANGE_SUMMARY = (
    f"v1.1 — adds mx_rounding_rule = HALF_UP:0.01 (owner decision D-01, option A; S30 Guía de llenado "
    f"Q37/Q39) and mx_ceav_lowest_band_min_wage_ref = GENERAL (owner decision D-03; S11). Otherwise the "
    f"v1.0 {SPEC} federal core, transcribed only from docs/mexico/sources/. "
    "Every row needs_g1 — Draft pending the gate G1 statutory review."
)


def _decision_row(key: str, decision: str):
    rows = [r for r in content.MX_SCALAR_CONTENT if r.key == key and r.text_value]
    if len(rows) != 1:
        raise SystemExit(f"mexico_content has no single {key} row — v1.1 exists to carry it ({decision}); "
                         "transcribe it before seeding v1.1")
    return rows[0]


def seed_mexico_v1_1(db, manifest: dict = None) -> dict:
    from app.modules.payroll.engine.jurisdictions.mexico import rounding
    from app.modules.payroll.service import record_tax_audit

    row = _decision_row("mx_rounding_rule", "D-01")
    rounding.parse(row.text_value)  # the engine must accept it (MODE:QUANTUM)
    ceav_ref = _decision_row("mx_ceav_lowest_band_min_wage_ref", "D-03")

    previous = (db.query(JurisdictionPack)
                .filter(JurisdictionPack.pack_id == MAIN_PACK_ID, JurisdictionPack.version == PREVIOUS_VERSION,
                        JurisdictionPack.jurisdiction_country == CODE)
                .first())
    if previous is None:
        raise SystemExit(f"{MAIN_PACK_ID} v{PREVIOUS_VERSION} is not in this database — run "
                         "scripts/seed_mexico_canonical_packs.py first (v1.1 is a new version of it)")

    manifest = load_manifest() if manifest is None else manifest
    source_ids = _upsert_sources(db, manifest, _cited_sources())
    pack = _seed_national_pack(db, source_ids, version=VERSION, previous=previous, change_summary=CHANGE_SUMMARY)
    db.flush()  # the session does not autoflush: count the rows just added

    rates =db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).count()
    slabs = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id).count()
    record_tax_audit(
        db, actor_id=None, action="seed", entity_type="jurisdiction_pack", entity_id=pack.id,
        jurisdiction_pack_id=pack.id, tax_version=pack.version, legal_reference=SPEC,
        old_value={"previousVersion": previous.version, "previousId": previous.id},
        new_value={"status": pack.status, "contribution_rates": str(rates), "tax_slabs": str(slabs),
                   "mx_rounding_rule": row.text_value, "mx_ceav_lowest_band_min_wage_ref": ceav_ref.text_value},
        reason=f"Canonical Mexico pack {pack.pack_id} v{pack.version} seeded from {SPEC} "
               "(scripts/seed_mexico_canonical_packs_v1_1.py) — Draft, needs_g1; adds mx_rounding_rule (D-01) and "
               "mx_ceav_lowest_band_min_wage_ref (D-03).",
        auto_commit=False,
    )
    db.flush()
    return {"pack": pack, "previous": previous, "rates": rates, "slabs": slabs, "rounding": row.text_value,
            "ceav_ref": ceav_ref.text_value}


def main() -> None:
    _require_confirmed_target(TAG)
    initialize_database()
    db = SessionLocal()
    try:
        out = seed_mexico_v1_1(db)
        db.commit()
        pack = out["pack"]
        print(f"Seeded {pack.pack_id} v{pack.version} as Draft ({out['rates']} ContributionRate rows, "
              f"{out['slabs']} TaxSlab rows) — previous version v{out['previous'].version} left unchanged; "
              f"mx_rounding_rule={out['rounding']}, mx_ceav_lowest_band_min_wage_ref={out['ceav_ref']}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
