"""
scripts/seed_italy_canonical_pack.py
------------------------------------
Seeds the canonical (organization_id IS NULL) Italy content as DRAFT: one
IT-PAYROLL-2026 tax JurisdictionPack with every scalar parameter, the INPS
classification matrix, the IRPEF / detrazione / wedge bands and the staged
local-surtax bands from engine/countries/italy_content.py, plus Italy's
jurisdiction_service_registry row as PLANNED.

The row-writing logic lives in italy_service.seed_italy_pack (shared with the
tests); this script only adds the database guard, the registry row and the
audit entry.

Source: ZP-IT-ENG-001 v1.0 Final (repo root,
Zoiko_Payroll_Italy_Engineering_Wireframe_and_Implementation_Specification_v1.0_Final.txt).
Content marked "needs source" in italy_content.py — the local surtax rates, the
INPS CSC code and worker classes, the detrazione floors — is a Draft
placeholder that must be replaced from the MEF / INPS catalogs (IT-012,
IT-043) before gate G1 can pass.

Governance: nothing is ever set Active here, and the registry row is created
only when missing (an existing row is never changed). Re-running refuses to
touch a pack that has left Draft; a Draft pack's rows are replaced wholesale
from the content, so an unchanged re-run produces the same rows.

Usage:
    python -m scripts.seed_italy_canonical_pack
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, initialize_database  # noqa: E402
from app.modules.payroll import italy_service  # noqa: E402
from scripts._local_db_guard import assert_local_database  # noqa: E402

CODE = "IT"
SPEC = "ZP-IT-ENG-001 v1.0 Final"


def _ensure_service_registry_row(db) -> str:
    """Italy's jurisdiction_service_registry row, PLANNED, created only when
    missing — an existing row is never changed (same rule as Sweden)."""
    from app.modules.billing.models import JurisdictionServiceRegistry

    existing = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == CODE).first()
    if existing is not None:
        return existing.availability
    db.add(JurisdictionServiceRegistry(country=CODE, availability="PLANNED",
                                       payment_execution_responsibility="NOT_OFFERED",
                                       filing_responsibility="NOT_OFFERED", remittance_responsibility="NOT_OFFERED"))
    db.flush()
    return "PLANNED"


def seed_italy(db) -> dict:
    from app.modules.payroll.service import record_tax_audit

    pack = italy_service.seed_italy_pack(db)
    availability = _ensure_service_registry_row(db)
    record_tax_audit(
        db, actor_id=None, action="update", entity_type="jurisdiction_pack", entity_id=pack.id,
        jurisdiction_pack_id=pack.id, tax_version=pack.version, legal_reference=SPEC,
        old_value=None, new_value={"status": pack.status, "availability": availability},
        reason=f"Canonical Italy pack {pack.pack_id} v{pack.version} seeded from {SPEC} "
               "(scripts/seed_italy_canonical_pack.py) — Draft.",
        auto_commit=False,
    )
    db.flush()
    return {"pack": pack, "availability": availability}


def main() -> None:
    assert_local_database("seed_italy_canonical_pack")
    initialize_database()
    db = SessionLocal()
    try:
        out = seed_italy(db)
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
