"""
scripts/seed_poland_canonical_packs.py
---------------------------------------
Seeds the canonical (organization_id IS NULL) Poland content as DRAFT: one
PL-PAYROLL-2026 tax JurisdictionPack with every scalar parameter, the PIT
scale and every earning-class row from engine/countries/poland_content.py,
plus Poland's jurisdiction_service_registry row as PLANNED.

Source: ZP-PL-ENG-001 v1.0 — the implementation specification. Every value
is traceable to SOURCE_REFERENCES S1–S12 in poland_content.py. String
scalars (MONTHLY, UMOWA_O_PRACE, PENDING_G1, END_JANUARY, ...) live in
ContributionRate.text_value, never flat_amount.

Governance: nothing is ever set Active here, and the registry row is created
only when missing (an existing row is never changed). Re-running refuses to
touch a pack that has left Draft; a Draft pack's rows are replaced wholesale
from the content, so an unchanged re-run produces the same rows. The
local-database guard refuses any non-local target. Run only with explicit
approval.

Usage:
    python -m scripts.seed_poland_canonical_packs
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, initialize_database  # noqa: E402
from app.modules.payroll import poland_service  # noqa: E402
from scripts._local_db_guard import assert_local_database  # noqa: E402

CODE = "PL"
SPEC = "ZP-PL-ENG-001 v1.0"


def _ensure_service_registry_row(db) -> str:
    """Poland's jurisdiction_service_registry row, PLANNED, created only when
    missing — an existing row is never changed."""
    from app.modules.billing.models import JurisdictionServiceRegistry

    existing = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == CODE).first()
    if existing is not None:
        return existing.availability
    db.add(JurisdictionServiceRegistry(country=CODE, availability="PLANNED",
                                       payment_execution_responsibility="NOT_OFFERED",
                                       filing_responsibility="NOT_OFFERED", remittance_responsibility="NOT_OFFERED"))
    db.flush()
    return "PLANNED"


def seed_poland(db) -> dict:
    from app.modules.payroll.service import record_tax_audit

    pack = poland_service.seed_poland_pack(db)
    availability = _ensure_service_registry_row(db)
    record_tax_audit(
        db, actor_id=None, action="update", entity_type="jurisdiction_pack", entity_id=pack.id,
        jurisdiction_pack_id=pack.id, tax_version=pack.version, legal_reference=SPEC,
        old_value=None, new_value={"status": pack.status, "availability": availability},
        reason=f"Canonical Poland pack {pack.pack_id} v{pack.version} seeded from {SPEC} "
               "(scripts/seed_poland_canonical_packs.py) — Draft.",
        auto_commit=False,
    )
    db.flush()
    return {"pack": pack, "availability": availability}


def main() -> None:
    assert_local_database("seed_poland_canonical_packs")
    initialize_database()
    db = SessionLocal()
    try:
        out = seed_poland(db)
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
