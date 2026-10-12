"""
scripts/fix_ca_federal_h1_h2_packages.py
------------------------------------------
Fixes a real S0-class gap found during a 2026-09-11 gap-analysis re-check
against ZP-TAX-CA-2026-001: the FEDERAL layer never got the real
CA-2026-H1/CA-2026-H2 immutable package pair the document requires
(§4/CA-D02/AC-02) — only two legacy packs existed, neither of them
usable:

  - "CA-PAYROLL-2026-27" (status=Approved, not Active) — wrongly named/
    dated (a pre-ZP-TAX-CA-2026-001 fiscal-year-style label), and
    invisible to resolve_tax_configuration's _find_active_tax_pack
    lookup (which only returns Active packs). Also carries 6 duplicate
    ContributionRate rows and all 5 federal TaxSlab brackets duplicated
    (two separate manual data-entry passes, 2026-08-31 and 2026-09-02,
    neither one detecting the other's existing rows).
  - "CA-FALLBACK-DEFAULTS" (status=Draft) — holds STALE 2024 values for
    cpp_ympe ($71,300, should be $74,600) and ei_mie ($65,700, should be
    $68,900). Harmless only as long as it stays Draft/unreferenced.

Net effect until this script runs: every federal parameter (BPAF, CEA,
lowest_fed_rate, CPP/CPP2/EI thresholds, federal brackets) has been
resolving via app/modules/payroll/hardcoded_defaults.py's Python
fallback constants, not the canonical DB pack — correct only by
coincidence (the fallbacks happen to equal the correct 2026 H1 figures).

This script:
  1. Retires both legacy packs (deletes their ContributionRate/TaxSlab
     rows, sets status="Retired") — same convention already used for
     BC/NL/PE's old single-package packs (populate_ca_provincial_v1.py's
     _retire_single_package_pack).
  2. Creates CA-2026-H1 (2026-01-01..2026-06-30) and CA-2026-H2
     (2026-07-01..2026-12-31) as genuinely separate, Active,
     source-linked packs.
  3. Seeds IDENTICAL correct values into both — ZP-TAX-CA-2026-001 §6
     gives ONE federal parameter table for all of 2026 with no H1/H2
     split (unlike §9's BC/NL/PE provincial overrides, which genuinely
     differ). The two-package structure here satisfies CA-D02's
     versioning/immutability requirement even though the numbers
     themselves don't change between halves.
  4. Also fixes a smaller, previously-flagged gap while rebuilding this
     data anyway: cpp2_rate's employer side was never seeded (only
     employee) — now both sides are 4.00% per §10's own table.

0 CA employees exist on the live DB as of this date (confirmed via a
prior read-only check), so this changes no already-generated payslip.

Idempotent: safe to re-run (upserts by (pack_id, component_key) /
(pack_id, sort_order) rather than duplicating — the exact bug this
script exists to clean up).

Usage:
    python -m scripts.fix_ca_federal_h1_h2_packages
"""

import sys
from pathlib import Path
from decimal import Decimal
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.modules.payroll.models import ContributionRate, TaxSlab, JurisdictionPack, SourceArtifact

COUNTRY = "CA"
TAX_YEAR = "2026"
CURRENCY = "CAD"
SOURCE_TITLE = "ZP-TAX-CA-2026-001 v1.0 — Canada 2026 Statutory Configuration Pack"
SOURCE_AGENCY = "CRA T4127 (122nd/123rd Ed.) / Revenu Québec TP-1015.F-V / provincial authorities"

LEGACY_PACK_IDS = ["CA-PAYROLL-2026-27", "CA-FALLBACK-DEFAULTS"]

# (component_key, sort_order, label, employee_share, employer_share, total,
#  employee_rate_pct, employer_rate_pct, flat_amount)
_RATE_ROWS = [
    ("cpp", 1, "Canada Pension Plan (CPP)", "5.95%", "5.95%", "11.9%", Decimal("5.95"), Decimal("5.95"), None),
    ("ei", 2, "Employment Insurance (EI)", "1.63%", "2.282%", "3.912%", Decimal("1.63"), Decimal("2.282"), None),
    ("income-tax", 3, "Federal Income Tax", "As per income slab", "—", "As per slab", None, None, None),
    ("basic_personal_amt", 4, "Basic Personal Amount", "—", "—", "C$16,452", None, None, Decimal("16452.00")),
    ("cpp_ympe", 5, "CPP Year's Maximum Pensionable Earnings (YMPE)", "—", "—", "C$74,600", None, None, Decimal("74600.00")),
    ("cpp_basic_exemption", 6, "CPP Basic Exemption Amount", "—", "—", "C$3,500", None, None, Decimal("3500.00")),
    ("ei_mie", 7, "EI Maximum Insurable Earnings", "—", "—", "C$68,900", None, None, Decimal("68900.00")),
    ("cpp2_yampe", 8, "CPP2 Year's Additional Maximum Pensionable Earnings (YAMPE)", "—", "—", "C$85,000", None, None, Decimal("85000.00")),
    # Employer side now seeded too (§10: CPP2 is 4.00% each side) — the
    # legacy rows only ever had the employee side, a previously-flagged
    # gap that falls back correctly to a hardcoded default, fixed here.
    ("cpp2_rate", 9, "CPP2 Rate", "4%", "4%", "4%", Decimal("4.00"), Decimal("4.00"), None),
    ("bpaf_min", 10, "Federal Basic Personal Amount — Minimum (tapered)", "—", "—", "C$14,829", None, None, Decimal("14829.00")),
    ("bpaf_ni_thresh_lo", 11, "BPAF Taper — Net Income Threshold (Low)", "—", "—", "C$181,440", None, None, Decimal("181440.00")),
    ("bpaf_ni_thresh_hi", 12, "BPAF Taper — Net Income Threshold (High)", "—", "—", "C$258,482", None, None, Decimal("258482.00")),
    ("cea", 13, "Canada Employment Amount (credit)", "—", "—", "C$1,501", None, None, Decimal("1501.00")),
    ("lowest_fed_rate", 14, "Lowest Federal Rate (credit conversion)", "—", "—", "14%", Decimal("14.00"), None, None),
    ("qc_fed_abatement", 15, "Quebec Federal Abatement", "—", "—", "16.5%", Decimal("16.50"), None, None),
    ("beyond_prov_surtax", 16, "Beyond-Province Surtax Factor", "—", "—", "48% of T3", Decimal("48.00"), None, None),
    ("lsvcc_credit_rate", 17, "Labour-Sponsored Fund Credit Rate", "—", "—", "15%", Decimal("15.00"), None, None),
    ("lsvcc_credit_max", 18, "Labour-Sponsored Fund Credit Max", "—", "—", "C$750", None, None, Decimal("750.00")),
]

# (sort_order, min, max, rate_pct, rate_label, tax_formula)
_SLAB_ROWS = [
    (1, "0", "58523", "14.00", "14%", "14% of income"),
    (2, "58523", "117045", "20.50", "20.5%", "C$8,193 + 20.5% above C$58,523"),
    (3, "117045", "181440", "26.00", "26%", "C$20,190 + 26% above C$117,045"),
    (4, "181440", "258482", "29.00", "29%", "C$36,933 + 29% above C$181,440"),
    (5, "258482", None, "33.00", "33%", "C$59,275 + 33% above C$258,482"),
]


def _get_or_create_source(db) -> SourceArtifact:
    existing = (
        db.query(SourceArtifact)
        .filter(SourceArtifact.agency == SOURCE_AGENCY, SourceArtifact.title == SOURCE_TITLE)
        .first()
    )
    if existing:
        return existing
    artifact = SourceArtifact(agency=SOURCE_AGENCY, title=SOURCE_TITLE)
    db.add(artifact)
    db.flush()
    return artifact


def _retire_legacy_pack(db, pack_id: str):
    pack = db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == pack_id).first()
    if pack is None:
        print(f"  [skip] {pack_id} does not exist")
        return
    rate_count = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).count()
    slab_count = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id).count()
    db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).delete()
    db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id).delete()
    pack.status = "Retired"
    print(f"  [retired] {pack_id} (id={pack.id}) — removed {rate_count} rate rows, {slab_count} slab rows")


def _get_or_create_federal_half_pack(db, half: str, effective_from, effective_to, source: SourceArtifact) -> JurisdictionPack:
    pack_id = f"CA-2026-{half}"
    pack = db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == pack_id).first()
    change_summary = (
        f"Federal 2026 income tax / CPP / CPP2 / EI parameters per {SOURCE_TITLE} §6/§10/§11 "
        f"({'122nd Edition' if half == 'H1' else '123rd Edition'})."
    )
    if pack is None:
        pack = JurisdictionPack(
            pack_id=pack_id, jurisdiction_country=COUNTRY, jurisdiction_state=None,
            pack_type="tax", version="1.0", status="Active", tax_year=TAX_YEAR, currency=CURRENCY,
            regulatory_authority="ZP-TAX-CA-2026-001", change_summary=change_summary,
            effective_from=effective_from, effective_to=effective_to, source_document_id=source.id,
        )
        db.add(pack)
        db.flush()
        print(f"  [created] {pack_id} (id={pack.id})")
    else:
        pack.change_summary = change_summary
        pack.effective_from = effective_from
        pack.effective_to = effective_to
        pack.source_document_id = source.id
        pack.status = "Active"
        print(f"  [updated] {pack_id} (id={pack.id})")
    return pack


def _upsert_federal_rate(db, pack_id: int, component_key: str, sort_order: int, label: str,
                          employee_share: str, employer_share: str, total: str,
                          employee_rate_pct, employer_rate_pct, flat_amount):
    existing = (
        db.query(ContributionRate)
        .filter(
            ContributionRate.organization_id.is_(None), ContributionRate.jurisdiction_country == COUNTRY,
            ContributionRate.jurisdiction_state.is_(None), ContributionRate.component_key == component_key,
            ContributionRate.filing_status.is_(None), ContributionRate.jurisdiction_pack_id == pack_id,
        )
        .first()
    )
    fields = dict(
        component_key=component_key, sort_order=sort_order, label=label,
        employee_share=employee_share, employer_share=employer_share, total=total,
        employee_rate_pct=employee_rate_pct, employer_rate_pct=employer_rate_pct, flat_amount=flat_amount,
        jurisdiction_pack_id=pack_id,
    )
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
    else:
        db.add(ContributionRate(organization_id=None, jurisdiction_country=COUNTRY, jurisdiction_state=None, **fields))


def _upsert_federal_slab(db, pack_id: int, sort_order: int, min_amount, max_amount, rate_pct, rate_label, tax_formula):
    existing = (
        db.query(TaxSlab)
        .filter(
            TaxSlab.organization_id.is_(None), TaxSlab.jurisdiction_country == COUNTRY,
            TaxSlab.jurisdiction_state.is_(None), TaxSlab.sort_order == sort_order,
            TaxSlab.jurisdiction_pack_id == pack_id,
        )
        .first()
    )
    fields = dict(
        min_amount=Decimal(min_amount), max_amount=Decimal(max_amount) if max_amount is not None else None,
        rate_pct=Decimal(rate_pct), rate_label=rate_label, tax_formula=tax_formula,
        rule_type="MARGINAL_RATE", sort_order=sort_order, jurisdiction_pack_id=pack_id,
    )
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
    else:
        db.add(TaxSlab(organization_id=None, jurisdiction_country=COUNTRY, jurisdiction_state=None, **fields))


def run():
    db = SessionLocal()
    try:
        print("--- Retiring legacy federal packs ---")
        for pack_id in LEGACY_PACK_IDS:
            _retire_legacy_pack(db, pack_id)
        db.commit()

        print()
        print("--- Creating/updating CA-2026-H1 / CA-2026-H2 federal packs ---")
        source = _get_or_create_source(db)
        db.flush()

        h1 = _get_or_create_federal_half_pack(db, "H1", date(2026, 1, 1), date(2026, 6, 30), source)
        h2 = _get_or_create_federal_half_pack(db, "H2", date(2026, 7, 1), date(2026, 12, 31), source)
        db.flush()

        for pack in (h1, h2):
            for key, sort_order, label, emp_share, empr_share, total, emp_pct, empr_pct, flat in _RATE_ROWS:
                _upsert_federal_rate(db, pack.id, key, sort_order, label, emp_share, empr_share, total, emp_pct, empr_pct, flat)
            for sort_order, lo, hi, rate, rate_label, formula in _SLAB_ROWS:
                _upsert_federal_slab(db, pack.id, sort_order, lo, hi, rate, rate_label, formula)
        db.commit()
        print(f"  Seeded {len(_RATE_ROWS)} rate rows + {len(_SLAB_ROWS)} slab rows into each of CA-2026-H1 and CA-2026-H2.")
        print()
        print("DONE.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
