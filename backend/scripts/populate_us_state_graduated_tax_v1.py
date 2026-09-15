"""
scripts/populate_us_state_graduated_tax_v1.py
--------------------------------------------------
Gap-closure Level 2, 2026-09-12. Seeds
hardcoded_defaults._US_STATE_GRADUATED_TAX_RATES (CA, DC, DE, HI) — real,
multi-bracket, per-filing-status state PIT withholding tables, from a
genuinely primary-sourced batch (see that dict's own module comment for
the full list of documented simplifications: no per-employee allowance/
dependent-count field exists anywhere in this engine, so credits/
allowances that depend on one are not applied; CA's Low Income Exemption
cliff isn't implemented; a couple of filing-status figures are mapped
approximately where the source data didn't split as finely as this
engine's SINGLE/MFJ/MFS/HOH vocabulary does).

Deliberately a separate script from populate_us_state_tax_v1.py (flat-
rate states only) — a graduated state needs one TaxSlab row PER BRACKET
PER FILING STATUS, not the single FLAT_RATE row that script's own loop
assumes.

Idempotent: safe to re-run (upserts TaxSlab rows by
(jurisdiction_state, filing_status, sort_order) and ContributionRate rows
by (jurisdiction_state, filing_status) rather than duplicating).

Usage:
    python -m scripts.populate_us_state_graduated_tax_v1
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.modules.payroll.models import TaxSlab, ContributionRate, JurisdictionPack, SourceArtifact
from app.modules.payroll.hardcoded_defaults import _US_STATE_GRADUATED_TAX_RATES

COUNTRY = "US"
TAX_YEAR = "2026"
CURRENCY = "USD"


def _get_or_create_pack(db, state: str, change_summary: str) -> JurisdictionPack:
    pack = (
        db.query(JurisdictionPack)
        .filter(JurisdictionPack.pack_type == "tax", JurisdictionPack.jurisdiction_country == COUNTRY,
                JurisdictionPack.jurisdiction_state == state)
        .first()
    )
    if pack is None:
        pack = JurisdictionPack(
            pack_id=f"US-{state}-2026-V1", jurisdiction_country=COUNTRY, jurisdiction_state=state,
            pack_type="tax", version="1.0", status="Active", tax_year=TAX_YEAR, currency=CURRENCY,
            regulatory_authority="ZP-TAX-US-2026-001", change_summary=change_summary,
        )
        db.add(pack)
        db.flush()
    else:
        pack.change_summary = change_summary
        if pack.status != "Active":
            pack.status = "Active"
    return pack


def _get_or_create_source(db, agency: str, title: str) -> SourceArtifact:
    existing = db.query(SourceArtifact).filter(SourceArtifact.agency == agency, SourceArtifact.title == title).first()
    if existing:
        return existing
    artifact = SourceArtifact(agency=agency, title=title)
    db.add(artifact)
    db.flush()
    return artifact


def main():
    db = SessionLocal()
    try:
        for state, d in _US_STATE_GRADUATED_TAX_RATES.items():
            pack = _get_or_create_pack(
                db, state,
                change_summary=f"Graduated state withholding per primary-source batch — {d['source_title']}.",
            )
            source = _get_or_create_source(db, d["agency"], d["source_title"])
            pack.source_document_id = source.id

            slab_count = 0
            for filing_status, brackets in d["brackets_by_filing_status"].items():
                for sort_order, (min_amount, max_amount, rate_pct) in enumerate(brackets, start=1):
                    existing = (
                        db.query(TaxSlab)
                        .filter(
                            TaxSlab.organization_id.is_(None), TaxSlab.jurisdiction_country == COUNTRY,
                            TaxSlab.jurisdiction_state == state, TaxSlab.filing_status == filing_status,
                            TaxSlab.sort_order == sort_order,
                        )
                        .first()
                    )
                    ceiling_label = f"{max_amount}" if max_amount is not None else "and above"
                    fields = dict(
                        min_amount=min_amount, max_amount=max_amount, rate_pct=rate_pct,
                        rate_label=f"{rate_pct}%", tax_formula=f"{rate_pct}% from {min_amount} to {ceiling_label}",
                        rule_type="MARGINAL_RATE", filing_status=filing_status, sort_order=sort_order,
                        jurisdiction_pack_id=pack.id,
                    )
                    if existing:
                        for k, v in fields.items():
                            setattr(existing, k, v)
                    else:
                        db.add(TaxSlab(
                            organization_id=None, jurisdiction_country=COUNTRY, jurisdiction_state=state, **fields,
                        ))
                    slab_count += 1

            rate_count = 0
            for filing_status, amount in d["standard_deduction_by_filing_status"].items():
                existing_rate = (
                    db.query(ContributionRate)
                    .filter(
                        ContributionRate.organization_id.is_(None), ContributionRate.jurisdiction_country == COUNTRY,
                        ContributionRate.jurisdiction_state == state,
                        ContributionRate.component_key == "state_standard_deduction",
                        ContributionRate.filing_status == filing_status,
                    )
                    .first()
                )
                label = "State Standard Deduction" + (f" ({filing_status})" if filing_status else "")
                rate_fields = dict(
                    component_key="state_standard_deduction", label=label,
                    employee_share="—", employer_share="—", total=f"${amount:,.2f}",
                    flat_amount=amount, filing_status=filing_status, sort_order=1,
                    jurisdiction_pack_id=pack.id,
                )
                if existing_rate:
                    for k, v in rate_fields.items():
                        setattr(existing_rate, k, v)
                else:
                    db.add(ContributionRate(
                        organization_id=None, jurisdiction_country=COUNTRY, jurisdiction_state=state, **rate_fields,
                    ))
                rate_count += 1

            db.commit()
            print(f"{state}: pack {pack.pack_id} -> {slab_count} tax slab(s), {rate_count} standard-deduction rate(s)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
