"""
scripts/populate_ca_source_evidence_v1.py
---------------------------------------------
Closes a gap found during the 2026-09-11 gap-analysis re-check against
ZP-TAX-CA-2026-001: §27's Source Evidence Register lists 11 distinct
official sources (2 CRA T4127 editions, CRA's POE guidance, 2 Revenu
Québec publications, and 6 provincial/territorial authority pages), but
every CA JurisdictionPack was linked to ONE shared SourceArtifact row
generically titled after the whole document — real evidence tracking
(AC-27), just at a much coarser granularity than the document specifies.
The schema already supports this at row level (ContributionRate/TaxSlab
both have their own source_document_id, added specifically "per rule,
not just per-pack" — see models.py) — this script actually populates it.

Creates one SourceArtifact per §27 entry (agency/title/source_url, no
publication_date since the document doesn't give one per source), then:
  1. Points each JurisdictionPack's own source_document_id at its PRIMARY
     source per §2's authority table (P1: CRA T4127 for federal/non-
     Quebec provincial/CPP/EI; Revenu Québec TP-1015.F-V for Quebec;
     BC/NL/PE's H1 pack -> 122nd Edition, H2 pack -> 123rd Edition, per
     §4's own "CRA T4127 123rd Edition" H2 binding-source column).
  2. Overrides specific ROW-level source_document_id for the levy/
     territorial-tax component keys that the document's own §2 table
     attributes to a DIFFERENT authority than the pack's default (Ontario
     EHT, BC EHT, Manitoba HE Levy, NL HAPSET, NWT/Nunavut payroll tax) —
     the exact case row-level source_document_id exists to handle.

Idempotent: get-or-creates every SourceArtifact by (agency, title); safe
to re-run.

Usage:
    python -m scripts.populate_ca_source_evidence_v1
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.modules.payroll.models import ContributionRate, TaxSlab, JurisdictionPack, SourceArtifact

COUNTRY = "CA"

# (agency, title, source_url) — verbatim from §27's own table.
_SOURCES = {
    "CRA_122ND": (
        "CRA",
        "T4127 Payroll Deductions Formulas, 122nd Edition, effective Jan 1, 2026",
        "https://www.canada.ca/en/revenue-agency/services/forms-publications/payroll/t4127-payroll-deductions-formulas/t4127-jan.html",
    ),
    "CRA_123RD": (
        "CRA",
        "T4127 Payroll Deductions Formulas, 123rd Edition, effective Jul 1, 2026",
        "https://www.canada.ca/en/revenue-agency/services/forms-publications/payroll/t4127-payroll-deductions-formulas/t4127-jul.html",
    ),
    "CRA_POE": (
        "CRA",
        "Determine the province of employment (POE)",
        "https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/payroll/set-up-new-employee/determine-province-employment.html",
    ),
    "RQ_TP1015": (
        "Revenu Québec",
        "TP-1015.F-V Formulas to Calculate Source Deductions and Contributions, 2026-01",
        "https://www.revenuquebec.ca/en/online-services/forms-and-publications/current-details/tp-1015-f-v/",
    ),
    "RQ_CHANGES_2026": (
        "Revenu Québec",
        "Employers: Principal Changes for 2026",
        "https://www.revenuquebec.ca/en/businesses/source-deductions-and-employer-contributions/employers-principal-changes-for-2026/",
    ),
    "ON_EHT": (
        "Ontario",
        "Employer Health Tax (EHT)",
        "https://www.ontario.ca/document/employer-health-tax-eht",
    ),
    "BC_EHT": (
        "British Columbia",
        "Employer Health Tax overview",
        "https://www2.gov.bc.ca/gov/content/taxes/employer-health-tax/employer-health-tax-overview",
    ),
    "MB_LEVY": (
        "Manitoba",
        "Health and Post-Secondary Education Tax Levy",
        "https://www.gov.mb.ca/finance/taxation/taxes/payroll.html",
    ),
    "NL_HAPSET": (
        "Newfoundland and Labrador",
        "Health and Post Secondary Education Tax",
        "https://www.gov.nl.ca/fin/tax-programs-incentives/business/education/",
    ),
    "NT_PAYROLL": (
        "Northwest Territories",
        "Payroll Tax for Employees/Employers",
        "https://www.fin.gov.nt.ca/en/services/licences-taxes-et-droits/payroll-tax-employees",
    ),
    "NU_PAYROLL": (
        "Nunavut",
        "Payroll Tax Act / current remittance and employer guidance",
        "https://www.gov.nu.ca/en/finance",
    ),
}

# Pack pack_id -> source key (§2's authority table + §4's H1/H2 binding-source column).
_PACK_SOURCE = {
    "CA-2026-H1": "CRA_122ND", "CA-2026-H2": "CRA_123RD",
    "CA-AB-2026-V1": "CRA_122ND", "CA-NB-2026-V1": "CRA_122ND", "CA-NS-2026-V1": "CRA_122ND",
    "CA-SK-2026-V1": "CRA_122ND", "CA-YT-2026-V1": "CRA_122ND",
    "CA-MB-2026-V1": "CRA_122ND", "CA-ON-2026-V1": "CRA_122ND",
    "CA-NT-2026-V1": "CRA_122ND", "CA-NU-2026-V1": "CRA_122ND",
    "CA-BC-2026-H1": "CRA_122ND", "CA-BC-2026-H2": "CRA_123RD",
    "CA-NL-2026-H1": "CRA_122ND", "CA-NL-2026-H2": "CRA_123RD",
    "CA-PE-2026-H1": "CRA_122ND", "CA-PE-2026-H2": "CRA_123RD",
    "CA-QC-2026-V1": "RQ_TP1015",
}

# component_key PREFIX -> source key, for rows whose real authority differs
# from their pack's own default (§2/§15's employer-levy/territorial-tax
# attribution) — only these specific rows get a row-level override.
_ROW_SOURCE_PREFIXES = {
    "on_eht": "ON_EHT",
    "bc_eht": "BC_EHT",
    "mb_he_levy": "MB_LEVY",
    "nl_hapset": "NL_HAPSET",
    "nwt_payroll_tax": "NT_PAYROLL",
    "nu_payroll_tax": "NU_PAYROLL",
}

# TaxSlab rule_type -> source key — Ontario EHT's 9 rate bands (§16) are a
# genuine TaxSlab-based rate-TABLE lookup (_on_eht_rate_for_total), not a
# ContributionRate row like every other levy here, so they need their own
# mapping distinct from _ROW_SOURCE_PREFIXES above.
_SLAB_RULE_TYPE_SOURCE = {
    "ON_EHT_BAND": "ON_EHT",
}


def _get_or_create_source(db, agency: str, title: str, url: str) -> SourceArtifact:
    existing = db.query(SourceArtifact).filter(SourceArtifact.agency == agency, SourceArtifact.title == title).first()
    if existing:
        existing.source_url = url
        return existing
    artifact = SourceArtifact(agency=agency, title=title, source_url=url)
    db.add(artifact)
    db.flush()
    return artifact


def run():
    db = SessionLocal()
    try:
        sources = {key: _get_or_create_source(db, agency, title, url) for key, (agency, title, url) in _SOURCES.items()}
        db.flush()
        print(f"--- {len(sources)} SourceArtifact rows ready ---")
        for key, s in sources.items():
            print(f"  {key} -> id={s.id} {s.agency} / {s.title}")

        print()
        print("--- Re-linking JurisdictionPack.source_document_id ---")
        packs = db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == COUNTRY).all()
        relinked = 0
        for pack in packs:
            source_key = _PACK_SOURCE.get(pack.pack_id)
            if not source_key:
                continue
            pack.source_document_id = sources[source_key].id
            relinked += 1
        print(f"  Relinked {relinked} packs.")

        print()
        print("--- Setting row-level source_document_id for levy/territorial-tax rows ---")
        overridden = 0
        rows = db.query(ContributionRate).filter(
            ContributionRate.jurisdiction_country == COUNTRY, ContributionRate.organization_id.is_(None),
        ).all()
        for row in rows:
            for prefix, source_key in _ROW_SOURCE_PREFIXES.items():
                if row.component_key.startswith(prefix):
                    row.source_document_id = sources[source_key].id
                    overridden += 1
                    break
        print(f"  Overrode {overridden} rate rows.")

        print()
        print("--- Setting row-level source_document_id for TaxSlab levy-band rows ---")
        slab_overridden = 0
        slab_rows = db.query(TaxSlab).filter(
            TaxSlab.jurisdiction_country == COUNTRY, TaxSlab.organization_id.is_(None),
        ).all()
        for row in slab_rows:
            source_key = _SLAB_RULE_TYPE_SOURCE.get(row.rule_type)
            if source_key:
                row.source_document_id = sources[source_key].id
                slab_overridden += 1
        print(f"  Overrode {slab_overridden} slab rows.")

        db.commit()
        print()
        print("DONE.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
