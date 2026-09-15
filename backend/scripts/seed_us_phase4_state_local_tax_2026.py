"""
scripts/seed_us_phase4_state_local_tax_2026.py
--------------------------------------------------
Production-Readiness Plan Phase 4 (2026-09-15) — Louisiana, Maryland
(state + county), and Maine, all independently fetched and extracted
(pypdf) directly from each agency's own official PDF this session, not
transcribed from a secondary source. Oregon is NOT seeded here — its
entire formula is bespoke (engine/countries/us.py's
_calculate_or_annual_tax), not TaxSlab-representable, and needs no DB
rows to function. Kansas is NOT seeded — its DOR site was unreachable
this session; no real figures were ever obtained.

This is NOT a bypass of the governance lifecycle: every pack this script
creates lands in Draft status via service.bulk_import_state_tax_pack
(the SAME function the Super Admin "New State Import" UI calls) — it
still requires a distinct Super Admin to Approve, Publish, and Activate
each one, with every existing publish gate (source evidence, effective
date, golden-test variance) still enforced. This script only removes the
burden of hand-typing ~90 bracket/rate rows across 4 jurisdictions.

Idempotent for the locality datasets (import_locality_dataset creates a
new Draft version each run — re-running creates additional Draft
versions rather than erroring, matching that function's own existing
behavior; harmless, just prunes an old Draft if you don't want it).
bulk_import_state_tax_pack likewise always creates a NEW pack version —
re-running with the same `version` string will raise on the duplicate
(pack_id, version) rather than silently duplicating.

Usage:
    python -m scripts.seed_us_phase4_state_local_tax_2026
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decimal import Decimal

from app.database import SessionLocal
from app.modules.payroll import service
from app.modules.payroll.schemas import LocalityDatasetRateRow


def run():
    db = SessionLocal()
    try:
        # ── Louisiana ─────────────────────────────────────────────────
        # LDR R-1306 (1/26), effective 1/1/2026 — dam.ldr.la.gov/taxforms/1306-1-26.pdf
        print("Seeding Louisiana state tax (flat 3.09%, standard deduction by filing status)...")
        la_pack = service.bulk_import_state_tax_pack(
            db, jurisdiction_state="LA", version="2026.1",
            bracket_rows=[
                {"filingStatus": None, "minAmount": Decimal("0"), "maxAmount": None,
                 "ratePct": Decimal("3.09"), "rateLabel": "3.09%"},
            ],
            standard_deduction_rows=[
                {"filingStatus": "SINGLE", "label": "LA Standard Deduction (Single/MFS)", "flatAmount": Decimal("12875")},
                {"filingStatus": "MFS", "label": "LA Standard Deduction (Single/MFS)", "flatAmount": Decimal("12875")},
                {"filingStatus": "MFJ", "label": "LA Standard Deduction (MFJ/QSS/HOH)", "flatAmount": Decimal("25750")},
                {"filingStatus": "HOH", "label": "LA Standard Deduction (MFJ/QSS/HOH)", "flatAmount": Decimal("25750")},
            ],
        )
        print(f"  LA pack {la_pack.pack_id} v{la_pack.version} (id={la_pack.id}, status={la_pack.status})")

        # ── Maryland (state) ──────────────────────────────────────────
        # Comptroller of Maryland, Central Payroll Bureau memo, 2/4/2026 —
        # marylandcomptroller.gov .../2026-maryland-state-and-local-withholding-information.pdf
        # No separate withholding-formula standard deduction is published
        # alongside this bracket table — none is entered (honest gap, not
        # a guessed figure); brackets apply to MD taxable wages as-is.
        md_single_mfs = [
            (Decimal("1"), Decimal("1000"), Decimal("2.00")),
            (Decimal("1000"), Decimal("2000"), Decimal("3.00")),
            (Decimal("2000"), Decimal("3000"), Decimal("4.00")),
            (Decimal("3000"), Decimal("100000"), Decimal("4.75")),
            (Decimal("100000"), Decimal("125000"), Decimal("5.00")),
            (Decimal("125000"), Decimal("150000"), Decimal("5.25")),
            (Decimal("150000"), Decimal("250000"), Decimal("5.50")),
            (Decimal("250000"), Decimal("500000"), Decimal("5.75")),
            (Decimal("500000"), Decimal("1000000"), Decimal("6.25")),
            (Decimal("1000000"), None, Decimal("6.50")),
        ]
        md_mfj_hoh = [
            (Decimal("1"), Decimal("1000"), Decimal("2.00")),
            (Decimal("1000"), Decimal("2000"), Decimal("3.00")),
            (Decimal("2000"), Decimal("3000"), Decimal("4.00")),
            (Decimal("3000"), Decimal("150000"), Decimal("4.75")),
            (Decimal("150000"), Decimal("175000"), Decimal("5.00")),
            (Decimal("175000"), Decimal("225000"), Decimal("5.25")),
            (Decimal("225000"), Decimal("300000"), Decimal("5.50")),
            (Decimal("300000"), Decimal("600000"), Decimal("5.75")),
            (Decimal("600000"), Decimal("1200000"), Decimal("6.25")),
            (Decimal("1200000"), None, Decimal("6.50")),
        ]
        print("Seeding Maryland state tax (10-bracket, Single/MFS + MFJ/HOH)...")
        md_bracket_rows = []
        for status in ("SINGLE", "MFS"):
            for lo, hi, rate in md_single_mfs:
                md_bracket_rows.append({"filingStatus": status, "minAmount": lo, "maxAmount": hi, "ratePct": rate, "rateLabel": f"{rate}%"})
        for status in ("MFJ", "HOH"):
            for lo, hi, rate in md_mfj_hoh:
                md_bracket_rows.append({"filingStatus": status, "minAmount": lo, "maxAmount": hi, "ratePct": rate, "rateLabel": f"{rate}%"})
        md_pack = service.bulk_import_state_tax_pack(
            db, jurisdiction_state="MD", version="2026.1", bracket_rows=md_bracket_rows,
        )
        print(f"  MD pack {md_pack.pack_id} v{md_pack.version} (id={md_pack.id}, status={md_pack.status}, {len(md_bracket_rows)} bracket rows)")

        # ── Maine ─────────────────────────────────────────────────────
        # Maine Revenue Services, 2026 Percentage Method —
        # maine.gov/revenue/.../26_wh_tab_instr.pdf. Standard deduction is
        # NOT entered as a row here — it is genuinely income-phased-out,
        # handled entirely by engine/countries/us.py's own
        # _me_standard_deduction_for_status (see that function's
        # docstring for why the flat $15,300/$30,600 general figure would
        # be wrong for withholding purposes).
        print("Seeding Maine state tax (3-bracket: 5.80% / 6.75% / 7.15%)...")
        me_pack = service.bulk_import_state_tax_pack(
            db, jurisdiction_state="ME", version="2026.1",
            bracket_rows=[
                {"filingStatus": "SINGLE", "minAmount": Decimal("0"), "maxAmount": Decimal("27400"), "ratePct": Decimal("5.80"), "rateLabel": "5.80%"},
                {"filingStatus": "SINGLE", "minAmount": Decimal("27400"), "maxAmount": Decimal("64850"), "ratePct": Decimal("6.75"), "rateLabel": "6.75%"},
                {"filingStatus": "SINGLE", "minAmount": Decimal("64850"), "maxAmount": None, "ratePct": Decimal("7.15"), "rateLabel": "7.15%"},
                {"filingStatus": "MFJ", "minAmount": Decimal("0"), "maxAmount": Decimal("54850"), "ratePct": Decimal("5.80"), "rateLabel": "5.80%"},
                {"filingStatus": "MFJ", "minAmount": Decimal("54850"), "maxAmount": Decimal("129750"), "ratePct": Decimal("6.75"), "rateLabel": "6.75%"},
                {"filingStatus": "MFJ", "minAmount": Decimal("129750"), "maxAmount": None, "ratePct": Decimal("7.15"), "rateLabel": "7.15%"},
            ],
        )
        print(f"  ME pack {me_pack.pack_id} v{me_pack.version} (id={me_pack.id}, status={me_pack.status})")

        # ── Maryland county tax (Locality Dataset Manager) ──────────────
        # Same source as MD state, Attachment 1. 23 flat counties +
        # Baltimore City, plus Anne Arundel/Frederick's own tiered
        # structure via bracket_schedule (no published base figures for
        # these two — engine does a from-scratch marginal sum).
        print("Seeding Maryland county tax (25 flat + 2 tiered)...")
        md_flat_counties = [
            ("01", "Allegany County", Decimal("3.20")),
            ("03", "Baltimore County", Decimal("3.20")),
            ("04", "Baltimore City", Decimal("3.20")),
            ("05", "Calvert County", Decimal("3.20")),
            ("06", "Caroline County", Decimal("3.20")),
            ("07", "Carroll County", Decimal("3.03")),
            ("08", "Cecil County", Decimal("2.74")),
            ("09", "Charles County", Decimal("3.03")),
            ("10", "Dorchester County", Decimal("3.30")),
            ("12", "Garrett County", Decimal("2.65")),
            ("13", "Harford County", Decimal("3.06")),
            ("14", "Howard County", Decimal("3.20")),
            ("15", "Kent County", Decimal("3.30")),
            ("16", "Montgomery County", Decimal("3.20")),
            ("17", "Prince George's County", Decimal("3.20")),
            ("18", "Queen Anne's County", Decimal("3.20")),
            ("19", "St. Mary's County", Decimal("3.20")),
            ("20", "Somerset County", Decimal("3.20")),
            ("21", "Talbot County", Decimal("2.40")),
            ("22", "Washington County", Decimal("2.95")),
            ("23", "Wicomico County", Decimal("3.20")),
            ("24", "Worcester County", Decimal("2.25")),
            ("**", "Unknown Maryland County (default)", Decimal("3.30")),
        ]
        md_rows = [
            LocalityDatasetRateRow(
                localityCode=code, localityType="COUNTY", localityName=name,
                residentRatePct=rate, nonresidentRatePct=Decimal("7.00"),
            )
            for code, name, rate in md_flat_counties
        ]
        md_rows.append(LocalityDatasetRateRow(
            localityCode="02", localityType="COUNTY", localityName="Anne Arundel County",
            residentRatePct=Decimal("2.70"),  # informational summary only — bracket_schedule below is what actually applies
        ))
        md_rows.append(LocalityDatasetRateRow(
            localityCode="11", localityType="COUNTY", localityName="Frederick County",
            residentRatePct=Decimal("2.25"),
        ))
        md_dataset = service.import_locality_dataset(
            db, country="US", state="MD", version="2026.1",
            rows=[r.model_dump() for r in md_rows],
        )
        # Attach the two tiered schedules directly (import_locality_dataset's
        # own bulk row shape doesn't carry bracket_schedule — set it after
        # creation via the same upsert path the Locality Dataset Manager UI
        # would use for a one-off edit).
        from app.modules.payroll.models import LocalityRate
        aa_row = db.query(LocalityRate).filter(LocalityRate.locality_dataset_id == md_dataset.id, LocalityRate.locality_code == "02").first()
        fr_row = db.query(LocalityRate).filter(LocalityRate.locality_dataset_id == md_dataset.id, LocalityRate.locality_code == "11").first()
        if aa_row:
            aa_row.bracket_schedule = {
                "SINGLE": {"deduction": 0, "brackets": [
                    {"min": 0, "max": 50000, "rate": 2.70}, {"min": 50000, "max": 400000, "rate": 2.94}, {"min": 400000, "max": None, "rate": 3.20},
                ]},
                "MFJ": {"deduction": 0, "brackets": [
                    {"min": 0, "max": 75000, "rate": 2.70}, {"min": 75000, "max": 480000, "rate": 2.94}, {"min": 480000, "max": None, "rate": 3.20},
                ]},
            }
        if fr_row:
            fr_row.bracket_schedule = {
                "SINGLE": {"deduction": 0, "brackets": [
                    {"min": 0, "max": 25000, "rate": 2.25}, {"min": 25000, "max": 50000, "rate": 2.75},
                    {"min": 50000, "max": 150000, "rate": 2.96}, {"min": 150000, "max": None, "rate": 3.20},
                ]},
                "MFJ": {"deduction": 0, "brackets": [
                    {"min": 0, "max": 25000, "rate": 2.25}, {"min": 25000, "max": 100000, "rate": 2.75},
                    {"min": 100000, "max": 250000, "rate": 2.96}, {"min": 250000, "max": None, "rate": 3.20},
                ]},
            }
        db.commit()
        print(f"  MD locality dataset v{md_dataset.version} (id={md_dataset.id}, status={md_dataset.status}, {len(md_rows)} counties)")

        # ── New York City resident tax (Locality Dataset Manager) ───────
        # NYS-50-T-NYC (1/26), page 25-26 — tax.ny.gov/pdf/publications/
        # withholding/nys50_t_nyc.pdf. Rate schedule is IDENTICAL for
        # Single/Married (verified against both pages) — only Table A's
        # deduction differs ($5,000 Single / $5,500 Married). Allowances
        # beyond the base (0) are not modeled — same documented gap as
        # Oregon/Wisconsin's own per-exemption limitation.
        print("Seeding New York City resident tax (6-bracket, real published base figures)...")
        nyc_row = LocalityDatasetRateRow(
            localityCode="NYC", localityType="MUNICIPAL", localityName="New York City",
            residentRatePct=Decimal("4.25"),  # informational summary (top marginal rate) — bracket_schedule below is what actually applies
        )
        nyc_dataset = service.import_locality_dataset(
            db, country="US", state="NY", version="2026.1",
            rows=[nyc_row.model_dump()],
        )
        from app.modules.payroll.models import LocalityRate as _LocalityRate
        nyc_locality = db.query(_LocalityRate).filter(_LocalityRate.locality_dataset_id == nyc_dataset.id, _LocalityRate.locality_code == "NYC").first()
        if nyc_locality:
            nyc_brackets = [
                {"min": 0, "max": 8000, "rate": 2.05, "base": 0},
                {"min": 8000, "max": 8700, "rate": 2.80, "base": 164.00},
                {"min": 8700, "max": 15000, "rate": 3.25, "base": 184.00},
                {"min": 15000, "max": 25000, "rate": 3.95, "base": 388.00},
                {"min": 25000, "max": 60000, "rate": 4.15, "base": 783.00},
                {"min": 60000, "max": None, "rate": 4.25, "base": 2236.00},
            ]
            nyc_locality.bracket_schedule = {
                "SINGLE": {"deduction": 5000, "brackets": nyc_brackets},
                "MFJ": {"deduction": 5500, "brackets": nyc_brackets},
            }
        db.commit()
        print(f"  NYC locality dataset v{nyc_dataset.version} (id={nyc_dataset.id}, status={nyc_dataset.status})")

        print(
            "\nDone. Every pack/dataset above is in Draft status — a Super Admin still needs to "
            "review, link Source Evidence, set an Effective From date, Approve (a different Super "
            "Admin), and Activate each one before any organization's payroll actually uses it. "
            "Oregon needs no DB rows (its formula is fully in engine/countries/us.py). Kansas is "
            "not seeded — no real data was obtained this session."
        )
    finally:
        db.close()


if __name__ == "__main__":
    run()
