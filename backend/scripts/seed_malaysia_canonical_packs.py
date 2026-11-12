"""
scripts/seed_malaysia_canonical_packs.py
-----------------------------------------
Seeds the canonical (organization_id IS NULL) Malaysia content as DRAFT: one
MY-PAYROLL-2026 tax JurisdictionPack with every scalar parameter (national
and one row per labour territory) and every earning-class row from
engine/countries/malaysia_content.py, plus Malaysia's
jurisdiction_service_registry row as PLANNED.

Source: ZP-MY-ENG-001 v1.0. Every row is written UNSIGNED ([PENDING G1]);
contribution schedules and public holidays are NOT seeded — they are loaded
from the official documents through the statutory workbook.

Governance: nothing is ever set Active here, and the registry row is created
only when missing. Re-running refuses to touch a pack that has left Draft.
The local-database guard refuses any non-local target. In production use the
Super Admin "create draft pack" action instead. Run only with explicit
approval.

Usage:
    python -m scripts.seed_malaysia_canonical_packs
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._local_db_guard import assert_local_database  # noqa: E402

SPEC = "ZP-MY-ENG-001 v1.0"


def seed_malaysia(db) -> dict:
    from app.modules.payroll import malaysia_service
    from app.modules.payroll.service import record_tax_audit

    pack = malaysia_service.seed_malaysia_pack(db)
    availability = malaysia_service.ensure_my_service_registry_row(db)
    record_tax_audit(
        db, actor_id=None, action="update", entity_type="jurisdiction_pack", entity_id=pack.id,
        jurisdiction_pack_id=pack.id, tax_version=pack.version, legal_reference=SPEC,
        old_value=None, new_value={"status": pack.status, "availability": availability},
        reason=f"Canonical Malaysia pack {pack.pack_id} v{pack.version} seeded from {SPEC} "
               "(scripts/seed_malaysia_canonical_packs.py) — Draft, every row unsigned.",
        auto_commit=False,
    )
    db.flush()
    return {"pack": pack, "availability": availability}


def main() -> None:
    assert_local_database("seed_malaysia_canonical_packs")
    from app.database import SessionLocal, initialize_database

    initialize_database()
    db = SessionLocal()
    try:
        out = seed_malaysia(db)
        db.commit()
        pack = out["pack"]
        print(f"Seeded {pack.pack_id} v{pack.version} (id={pack.id}) as {pack.status}; "
              f"service availability={out['availability']}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
