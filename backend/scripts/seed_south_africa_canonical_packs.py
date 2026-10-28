"""
scripts/seed_south_africa_canonical_packs.py
---------------------------------------------
Seeds the canonical (organization_id IS NULL) South Africa content as
DRAFT: one ZA-PAYROLL-2027 tax JurisdictionPack with every scalar
parameter, every PAYE band, every ETI band and every earning-class row from
engine/countries/south_africa_content.py, plus South Africa's
jurisdiction_service_registry row as PLANNED.

Source: ZP-ZA-ENG-001 v1.0 — the implementation specification.
Every value is traceable to SOURCE_REFERENCES S1–S14 in
south_africa_content.py. String scalars (MONTHLY, HALF_UP, 25.3.0,
PENDING_G1) live in ContributionRate.text_value, never flat_amount.

Governance: nothing is ever set Active here, and the registry row is
created only when missing (an existing row is never changed). Re-running
refuses to touch a pack that has left Draft; a Draft pack's rows are
replaced wholesale from the content, so an unchanged re-run produces the
same rows. The local-database guard refuses any non-local target.

Usage:
    python -m scripts.seed_south_africa_canonical_packs
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, initialize_database  # noqa: E402
from app.modules.payroll import south_africa_service  # noqa: E402
from scripts._local_db_guard import assert_local_database  # noqa: E402

CODE = "ZA"
SPEC = "ZP-ZA-ENG-001 v1.0"


def _ensure_service_registry_row(db) -> str:
    """South Africa's jurisdiction_service_registry row, PLANNED, created
    only when missing — an existing row is never changed."""
    from app.modules.billing.models import JurisdictionServiceRegistry

    existing = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == CODE).first()
    if existing is not None:
        return existing.availability
    db.add(JurisdictionServiceRegistry(country=CODE, availability="PLANNED",
                                       payment_execution_responsibility="NOT_OFFERED",
                                       filing_responsibility="NOT_OFFERED", remittance_responsibility="NOT_OFFERED"))
    db.flush()
    return "PLANNED"


def seed_south_africa(db) -> dict:
    from app.modules.payroll.service import record_tax_audit

    pack = south_africa_service.seed_south_africa_pack(db)
    availability = _ensure_service_registry_row(db)
    record_tax_audit(
        db, actor_id=None, action="update", entity_type="jurisdiction_pack", entity_id=pack.id,
        jurisdiction_pack_id=pack.id, tax_version=pack.version, legal_reference=SPEC,
        old_value=None, new_value={"status": pack.status, "availability": availability},
        reason=f"Canonical South Africa pack {pack.pack_id} v{pack.version} seeded from {SPEC} "
               "(scripts/seed_south_africa_canonical_packs.py) — Draft.",
        auto_commit=False,
    )
    db.flush()
    return {"pack": pack, "availability": availability}


def main() -> None:
    assert_local_database("seed_south_africa_canonical_packs")
    initialize_database()
    db = SessionLocal()
    try:
        out = seed_south_africa(db)
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
