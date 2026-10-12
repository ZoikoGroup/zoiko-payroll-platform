"""
scripts/link_us_phase4_source_evidence.py
--------------------------------------------
Follow-up to seed_us_phase4_state_local_tax_2026.py — links each of the 5
Draft packs/datasets it created to a real SourceArtifact (the actual
government PDF this session fetched and verified against), and sets an
Effective From date. Both are pure data-entry/administrative facts (the
document's own stated effective date), not a judgment call — this does
NOT Approve or Activate anything; that step still requires a distinct
Super Admin, deliberately left undone by this script.

Idempotent: get-or-create by (agency, title) for artifacts; re-running
just re-links the same rows.

Usage:
    python -m scripts.link_us_phase4_source_evidence
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date

from app.database import SessionLocal
from app.modules.payroll.models import JurisdictionPack, LocalityDataset, SourceArtifact

EFFECTIVE_FROM = date(2026, 1, 1)


def _get_or_create_source(db, agency, title, form_number, source_url, publication_date):
    existing = db.query(SourceArtifact).filter(SourceArtifact.agency == agency, SourceArtifact.title == title).first()
    if existing:
        return existing
    row = SourceArtifact(
        agency=agency, title=title, form_number=form_number,
        source_url=source_url, publication_date=publication_date,
    )
    db.add(row)
    db.flush()
    return row


def run():
    db = SessionLocal()
    try:
        la_source = _get_or_create_source(
            db, "Louisiana Department of Revenue", "Louisiana Withholding Tables and Formulas",
            "R-1306 (1/26)", "https://dam.ldr.la.gov/taxforms/1306-1-26.pdf", EFFECTIVE_FROM,
        )
        md_source = _get_or_create_source(
            db, "Comptroller of Maryland", "2026 Maryland State and Local Income Tax Withholding Information",
            None, "https://www.marylandcomptroller.gov/content/dam/mdcomp/md/state-payroll/memos/2026/2026-maryland-state-and-local-withholding-information.pdf",
            date(2026, 2, 4),
        )
        me_source = _get_or_create_source(
            db, "Maine Revenue Services", "Maine Income Tax Withholding — Percentage Method — 2026",
            None, "https://www.maine.gov/revenue/sites/maine.gov.revenue/files/inline-files/26_wh_tab_instr.pdf", EFFECTIVE_FROM,
        )
        nyc_source = _get_or_create_source(
            db, "NYS Department of Taxation and Finance", "NYS-50-T-NYC — New York City Withholding Tax Tables and Methods",
            "NYS-50-T-NYC (1/26)", "https://www.tax.ny.gov/pdf/publications/withholding/nys50_t_nyc.pdf", EFFECTIVE_FROM,
        )
        db.commit()

        la_pack = db.query(JurisdictionPack).filter(JurisdictionPack.id == 116).first()
        md_pack = db.query(JurisdictionPack).filter(JurisdictionPack.id == 117).first()
        me_pack = db.query(JurisdictionPack).filter(JurisdictionPack.id == 118).first()
        md_locality = db.query(LocalityDataset).filter(LocalityDataset.id == 6).first()
        nyc_locality = db.query(LocalityDataset).filter(LocalityDataset.id == 7).first()

        for pack, source, label in (
            (la_pack, la_source, "LA pack"), (md_pack, md_source, "MD state pack"), (me_pack, me_source, "ME pack"),
        ):
            if pack:
                pack.source_document_id = source.id
                pack.effective_from = EFFECTIVE_FROM
                print(f"  {label} (id={pack.id}) linked to source #{source.id}, effective {EFFECTIVE_FROM}")

        for dataset, source, label in (
            (md_locality, md_source, "MD county dataset"), (nyc_locality, nyc_source, "NYC dataset"),
        ):
            if dataset:
                dataset.source_document_id = source.id
                dataset.effective_from = EFFECTIVE_FROM
                print(f"  {label} (id={dataset.id}) linked to source #{source.id}, effective {EFFECTIVE_FROM}")

        db.commit()
        print("\nDone. Source evidence + effective dates set. Approve/Publish/Activate is deliberately NOT done by this script — needs a distinct Super Admin.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
