"""
scripts/populate_au_source_evidence_v1.py
---------------------------------------------
Australia counterpart to scripts/populate_in_source_evidence_v1.py /
populate_ca_source_evidence_v1.py / populate_us_source_evidence_v1.py —
Australia 2026-27 statutory build (ZP-TAX-AU-2026-27-001), Phase 0.

Seeds one SourceArtifact per §31's own Authoritative Source Register
(AU-SRC-001..007 federal, AU-SRC-101..110 state/territory payroll tax),
keyed by the document's own AU-SRC-xxx IDs rather than an invented
abbreviation, so a later audit can trace a row straight back to the spec.

NAT 1004 (AU-SRC-002) and NAT 3539 (AU-SRC-003) carry the document's own
published SHA-256 checksums in `checksum_sha256` — the exact field the
Active-pack promotion gate (per §2's SOURCE LOCK) can require. Sources
with no exact day given in §31 ("2026-27", "Current", "May 2026") are
left with publication_date=None rather than a guessed day — same
disclosed-omission convention the CA/US/India scripts already use for
sources the document itself doesn't fully date.

Idempotent: get-or-creates every SourceArtifact by (agency, title); safe
to re-run. Does NOT link any ContributionRate/TaxSlab/JurisdictionPack
row yet — Phase 1+'s canonical AU pack rows don't exist until those
phases run, at which point their own row-level source_document_id
linking follows the same pattern this script's IN/CA/US counterparts use.

Usage:
    python -m scripts.populate_au_source_evidence_v1

IMPORTANT (per this project's own established convention): this script
is written and self-reviewed (static-parse-checked) only in this
session. It has NEVER been executed against any database, live or test —
running any script that imports app.database/app.config requires
explicit go-ahead, every time, per this project's standing rule. Do not
run it without asking first.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.modules.payroll.models import SourceArtifact

# AU-SRC-xxx -> (agency, title, source_url, form_number, publication_date, checksum_sha256)
# Verbatim from ZP-TAX-AU-2026-27-001 §31's own Authoritative Source Register.
_SOURCES = {
    "AU-SRC-001": (
        "Australian Taxation Office",
        "2026 PAYG withholding tax tables",
        "https://softwaredevelopers.ato.gov.au/PAYGWTaxtables",
        None, date(2026, 5, 19), None,
    ),
    "AU-SRC-002": (
        "Australian Taxation Office",
        "NAT 1004 XLSX — local evidence copy",
        None, "NAT 1004", date(2026, 7, 1),
        "b0e239f33fc127bcebab0af7b4560440c597bbc2eec600f84b73b3240d46eee0",
    ),
    "AU-SRC-003": (
        "Australian Taxation Office",
        "NAT 3539 XLSX — local evidence copy",
        None, "NAT 3539", date(2026, 7, 1),
        "c966b4b4825499d2959d04d874bac23457bdcf57c37c3b88483b4fe4073d2433",
    ),
    "AU-SRC-004": (
        "Federal Register of Legislation",
        "Income Tax Rates Act 1986 — compilation effective 1 Jul 2026",
        "https://www.legislation.gov.au/C2004A03348/2026-07-01/2026-07-01/text/original/epub/OEBPS/document_1/document_1.html",
        None, date(2026, 7, 1), None,
    ),
    "AU-SRC-005": (
        "Australian Taxation Office",
        "ATO Software Developers — Payday Super",
        "https://softwaredevelopers.ato.gov.au/PaydaySuper",
        None, date(2026, 7, 1), None,
    ),
    "AU-SRC-006": (
        "Australian Taxation Office",
        "Key superannuation rates and thresholds",
        "https://www.ato.gov.au/rates/key-superannuation-rates-and-thresholds",
        None, None, None,
    ),
    "AU-SRC-007": (
        "Australian Taxation Office",
        "Contributions Standard v3 User Guide",
        "https://softwaredevelopers.ato.gov.au/sites/default/files/2026-03/ContributionsUserGuide_v3.0-0.2.pdf",
        None, date(2026, 7, 1), None,
    ),
    "AU-SRC-101": (
        "Revenue NSW",
        "Payroll tax thresholds and rates",
        "https://www.revenue.nsw.gov.au/taxes-duties-levies-royalties/payroll-tax/lodge-and-pay-returns/thresholds-and-rates",
        None, date(2026, 7, 1), None,
    ),
    "AU-SRC-102": (
        "State Revenue Office Victoria",
        "Payroll tax current rates",
        "https://www.sro.vic.gov.au/about-us/rates-and-statistics/current-rates/payroll-tax-current-rates",
        None, date(2026, 7, 1), None,
    ),
    "AU-SRC-103": (
        "Queensland Revenue Office",
        "Payroll tax rates and thresholds",
        "https://qro.qld.gov.au/payroll-tax/calculate/rates-thresholds/",
        None, None, None,
    ),
    "AU-SRC-104": (
        "Queensland Revenue Office",
        "Payroll tax deductions",
        "https://qro.qld.gov.au/payroll-tax/calculate/deductions/",
        None, None, None,
    ),
    "AU-SRC-110": (
        "Queensland Revenue Office",
        "Calculating mental health levy",
        "https://qro.qld.gov.au/payroll-tax/mental-health-levy/calculating/",
        None, None, None,
    ),
    "AU-SRC-105": (
        "WA Government",
        "Payroll Tax Employer Guide: Calculation",
        "https://www.wa.gov.au/government/multi-step-guides/payroll-tax-employer-guide/calculation-payroll-tax-employer-guide",
        None, date(2026, 6, 2), None,
    ),
    "AU-SRC-106": (
        "RevenueSA",
        "2026-27 Guide to Legislation: Payroll Tax",
        "https://www.revenuesa.sa.gov.au/__data/assets/pdf_file/0014/1422203/2026-27-Guide-to-Legislation-payroll-tax.pdf",
        None, date(2026, 7, 6), None,
    ),
    "AU-SRC-107": (
        "Tasmanian State Revenue Office",
        "Rates and thresholds",
        "https://www.sro.tas.gov.au/payroll-tax/rates-thresholds",
        None, date(2026, 7, 1), None,
    ),
    "AU-SRC-108": (
        "ACT Revenue Office",
        "About payroll tax",
        "https://www.revenue.act.gov.au/business-taxes-and-levies/payroll-tax/about-payroll-tax",
        None, date(2026, 7, 1), None,
    ),
    "AU-SRC-109": (
        "NT Treasury",
        "Payroll Tax Guide for NT Employers and Businesses",
        "https://treasury.nt.gov.au/pms/tro/information/payroll-tax-guide-for-nt-employers-and-businesses.pdf",
        None, None, None,
    ),
}

# §31's own note: "before production activation... re-check every P1
# source." No source here is treated as reviewer-approved by this script
# alone — approval remains a genuine Super Admin action, per AU-D12/§20.
_NOT_YET_REVIEWED = set(_SOURCES.keys())


def _get_or_create_source(db, agency, title, url, form_number, pub_date, checksum) -> SourceArtifact:
    existing = db.query(SourceArtifact).filter(SourceArtifact.agency == agency, SourceArtifact.title == title).first()
    if existing:
        existing.source_url = url
        existing.form_number = form_number
        existing.publication_date = pub_date
        existing.checksum_sha256 = checksum
        return existing
    artifact = SourceArtifact(
        agency=agency, title=title, source_url=url,
        form_number=form_number, publication_date=pub_date, checksum_sha256=checksum,
    )
    db.add(artifact)
    db.flush()
    return artifact


def run():
    db = SessionLocal()
    try:
        sources = {
            key: _get_or_create_source(db, agency, title, url, form_number, pub_date, checksum)
            for key, (agency, title, url, form_number, pub_date, checksum) in _SOURCES.items()
        }
        db.commit()
        print(f"--- {len(sources)} SourceArtifact rows ready (ZP-TAX-AU-2026-27-001 §31) ---")
        for key, s in sources.items():
            hash_flag = " [SHA-256 stored]" if s.checksum_sha256 else ""
            print(f"  {key} -> id={s.id} {s.agency} / {s.title}{hash_flag}")
        print()
        print("DONE. Every row above is UNREVIEWED — reviewer approval (SourceArtifact.reviewer_approved_at) "
              "remains a genuine Super Admin action, never set by this script.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
