"""
scripts/seed_uae_canonical_pack.py
----------------------------------
United Arab Emirates (ZP-AE-ENG-001): seeds the canonical pack
AE-PAYROLL-2026 v1.0 (organization_id IS NULL rows) from
engine/countries/uae_content.py.

The pack is created as **Draft**: a Super Admin reviews the values in
Compliance → United Arab Emirates and activates it with the normal Activate
action. Registration for the UAE opens only once the pack is Active.

Idempotent: re-running replaces this pack's own canonical rows only while it is
still Draft; an Approved / Active pack is never touched (change values through
the Super Admin page or a new version instead). Org-scoped rows and every
other country's packs are never touched.

Usage (local / isolated database only — enforced by _local_db_guard):
    python -m scripts.seed_uae_canonical_pack
"""
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.modules.payroll.engine.countries import uae_content as C  # noqa: E402

AE = "AE"


def _pct_label(value) -> str:
    return f"{(Decimal(value) * 100).normalize():f}%" if value is not None else "—"


def seed_uae_pack(db):
    """Create or refresh the Draft AE pack; returns the pack. Refuses to touch a
    pack that is no longer Draft."""
    from app.modules.payroll.models import ContributionRate, JurisdictionPack

    pack = (db.query(JurisdictionPack)
            .filter(JurisdictionPack.pack_id == C.PACK_ID, JurisdictionPack.version == "1.0").first())
    if pack is not None and pack.status != "Draft":
        raise SystemExit(f"{C.PACK_ID} v1.0 is {pack.status}; it is never re-seeded. Use the Super Admin page "
                         "or a new version to change values.")
    if pack is None:
        pack = JurisdictionPack(pack_id=C.PACK_ID, jurisdiction_country=AE, version="1.0", status="Draft")
        db.add(pack)
    pack.pack_type = "tax"
    pack.jurisdiction_state = None
    pack.effective_from = C.EFFECTIVE_FROM
    pack.effective_to = None
    pack.tax_year = "2026"
    pack.currency = C.CURRENCY
    pack.regulatory_authority = C.REGULATORY_AUTHORITY
    pack.compliance_category = "Payroll pension, end of service and labour law"
    pack.source_references = C.SOURCE_REFERENCES
    pack.change_summary = "Initial United Arab Emirates 2026 pack from ZP-AE-ENG-001 v1.0"
    db.flush()

    db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                      ContributionRate.organization_id.is_(None)).delete()
    for order, (key, label, employee, employer, flat, text, row_from, source) in enumerate(C.RATES, start=1):
        has_pct = employee is not None or employer is not None
        db.add(ContributionRate(
            jurisdiction_pack_id=pack.id, jurisdiction_country=AE, organization_id=None,
            component_key=key, label=f"{label} ({source})",
            employee_share=_pct_label(employee) if has_pct else (flat or text or "—"),
            employer_share=_pct_label(employer) if has_pct else "—",
            total=(_pct_label(str(Decimal(employee or 0) + Decimal(employer or 0))) if has_pct
                   else (flat or text or "—")),
            employee_rate_pct=Decimal(employee) if employee is not None else None,
            employer_rate_pct=Decimal(employer) if employer is not None else None,
            flat_amount=Decimal(flat) if flat is not None else None,
            text_value=text,
            effective_from=row_from,
            sort_order=order,
        ))
    db.flush()
    return pack


def main() -> None:
    from app.database import SessionLocal, initialize_database
    from scripts._local_db_guard import assert_local_database

    assert_local_database("seed_uae_canonical_pack")
    initialize_database()
    db = SessionLocal()
    try:
        pack = seed_uae_pack(db)
        db.commit()
        print(f"{C.PACK_ID} v1.0: {pack.status}, {len(C.RATES)} rates")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
