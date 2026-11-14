"""
scripts/seed_belgium_canonical_packs.py
---------------------------------------
Belgium (ZP-BE-ENG-001 Phase 3A): writes the Draft BE-PAYROLL-2026 canonical
pack from engine/countries/belgium_content.py:

  * every catalogue key as one "[PENDING G1]" row with EVERY value field empty
    (a spec figure appears only in the label as "spec-proposed: ...");
  * every (obligation, component) earning-classification row as REVIEW, pending;
  * the evidence register S1-S24 as payroll_source_artifacts (title + URL, NO
    checksum: not archived);
  * the PLANNED jurisdiction_service_registry row (create-only).

Idempotent and create-only (an existing Draft pack only gains missing rows; a
pack that has left Draft is refused). Creates NO Joint Committee pack.

Usage (local / isolated database only — enforced by _local_db_guard):
    python -m scripts.seed_belgium_canonical_packs
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, initialize_database  # noqa: E402
from app.modules.payroll import belgium_service  # noqa: E402
from scripts._local_db_guard import assert_local_database  # noqa: E402


def seed_belgium(db) -> dict:
    from app.modules.payroll.service import record_tax_audit

    pack = belgium_service.seed_belgium_pack(db)
    availability = belgium_service.ensure_be_service_registry_row(db)
    record_tax_audit(
        db, actor_id=None, action="update", entity_type="jurisdiction_pack", entity_id=pack.id,
        jurisdiction_pack_id=pack.id, tax_version=pack.version, legal_reference=belgium_service.SPEC,
        old_value=None, new_value={"status": pack.status, "availability": availability},
        reason=f"Canonical Belgium pack {pack.pack_id} v{pack.version} seeded from {belgium_service.SPEC} "
               "(scripts/seed_belgium_canonical_packs.py) — Draft, every row [PENDING G1].",
        auto_commit=False,
    )
    db.flush()
    return {"pack": pack, "availability": availability}


def main() -> None:
    assert_local_database("seed_belgium_canonical_packs")
    initialize_database()
    db = SessionLocal()
    try:
        out = seed_belgium(db)
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
