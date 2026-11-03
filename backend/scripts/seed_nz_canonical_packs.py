"""
scripts/seed_nz_canonical_packs.py
----------------------------------
Seeds the canonical (organization_id IS NULL) New Zealand content as DRAFT:
one NZ-PAYROLL-2026-27 tax JurisdictionPack with every scalar parameter, the
PAYE and ESCT bands, the tax-code catalogue and every earning-class row from
engine/countries/new_zealand_content.py; the empty NZ-ELA-2028 staging pack
(Employment Leave Act 2026, never activatable before 6 August 2028); and New
Zealand's jurisdiction_service_registry row as PLANNED.

Source: ZP-NZ-ENG-001 v1.0 — the implementation specification. Every value
is traceable to SOURCE_REFERENCES S1–S10 in new_zealand_content.py and every
row is PENDING G1. The authority tables the specification does not reproduce
(IRD PAYE method, secondary/ND rates, IETC, child-support variation codes,
lump-sum method, official examples, public holidays) write no rows.

Governance: nothing is ever set Active here, and the registry row is created
only when missing (an existing row is never changed). Re-running refuses to
touch a pack that has left Draft; a Draft pack's rows are replaced wholesale
from the content. The local-database guard refuses any non-local target.

Usage:
    python -m scripts.seed_nz_canonical_packs
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, initialize_database  # noqa: E402
from app.modules.payroll import new_zealand_service  # noqa: E402
from scripts._local_db_guard import assert_local_database  # noqa: E402

CODE = "NZ"
SPEC = "ZP-NZ-ENG-001 v1.0"


def _ensure_service_registry_row(db) -> str:
    """New Zealand's jurisdiction_service_registry row, PLANNED, created only
    when missing — an existing row is never changed."""
    from app.modules.billing.models import JurisdictionServiceRegistry

    existing = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == CODE).first()
    if existing is not None:
        return existing.availability
    db.add(JurisdictionServiceRegistry(country=CODE, availability="PLANNED",
                                       payment_execution_responsibility="NOT_OFFERED",
                                       filing_responsibility="NOT_OFFERED", remittance_responsibility="NOT_OFFERED"))
    db.flush()
    return "PLANNED"


def seed_new_zealand(db) -> dict:
    from app.modules.payroll.service import record_tax_audit

    pack = new_zealand_service.seed_nz_pack(db)
    availability = _ensure_service_registry_row(db)
    record_tax_audit(
        db, actor_id=None, action="update", entity_type="jurisdiction_pack", entity_id=pack.id,
        jurisdiction_pack_id=pack.id, tax_version=pack.version, legal_reference=SPEC,
        old_value=None, new_value={"status": pack.status, "availability": availability},
        reason=f"Canonical New Zealand pack {pack.pack_id} v{pack.version} seeded from {SPEC} "
               "(scripts/seed_nz_canonical_packs.py) — Draft.",
        auto_commit=False,
    )
    db.flush()
    return {"pack": pack, "availability": availability}


def main() -> None:
    assert_local_database("seed_nz_canonical_packs")
    initialize_database()
    db = SessionLocal()
    try:
        out = seed_new_zealand(db)
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
