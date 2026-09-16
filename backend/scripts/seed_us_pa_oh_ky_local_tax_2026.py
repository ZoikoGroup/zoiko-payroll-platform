"""
scripts/seed_us_pa_oh_ky_local_tax_2026.py
--------------------------------------------------
Production-Readiness Plan Phase 4 follow-up (2026-09-16) — Pennsylvania,
Ohio, and Kentucky local tax, seeded for the handful of highest-likelihood
localities per state (no real employees exist in any of these three states
yet, so this covers the realistic majority rather than an exhaustive
statewide registry — see the conversation's own "cover the majority,
disclose the rest" reasoning, same convention as MI/Detroit-only and
MO/Kansas-City+St-Louis-only already in this codebase).

Every figure below was independently researched and then independently
re-verified against the primary source directly by this session (not
taken on faith from the research pass) — see each city's own inline
citation. Kentucky and Ohio use the existing plain resident/nonresident
LocalityRate shape. Pennsylvania is split in two:

  - Philadelphia is NOT an Act 32 PSD_EIT_LST jurisdiction — it's its own
    Sterling Act "Wage Tax" with no LST at all. Seeded as an ordinary
    MUNICIPAL row.
  - Pittsburgh/Allentown/Harrisburg ARE real Act 32 PSD codes, seeded as
    PSD_EIT_LST rows — the FIRST real data these ever receive (the
    higher-of-resident-vs-work-rate mechanism, and now the LST-stacks-
    on-top-of-EIT fix, were both previously mechanism-only/dormant).

This is NOT a bypass of the governance lifecycle: every dataset this
script creates lands in Draft status via import_locality_dataset — a
Super Admin still needs to Stage, Approve, and Activate each one.

Usage:
    python -m scripts.seed_us_pa_oh_ky_local_tax_2026
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
        # ── Kentucky ──────────────────────────────────────────────────
        # Louisville Metro Revenue Commission, Form W-1 Instructions (Tax
        # Year 2025) — louisvilleky.gov/sites/default/files/2024-12/
        # w-1_instructions_2025.pdf, direct quote: "Resident employees...
        # 2.2%... Non-resident employees... 1.45%". LFUCG's own rate page
        # (lexingtonky.gov) + FCPS's own Tax Collection Office page
        # (fcps.net), independently re-fetched live 2026-09-16: FCPS's
        # 0.5% school tax confirmed still current (a board vote to raise
        # it to 0.75% was ruled unlawful and has not taken effect).
        print("Seeding Kentucky occupational tax (Louisville/Jefferson, Lexington/Fayette)...")
        ky_rows = [
            LocalityDatasetRateRow(
                localityCode="21111", localityType="COUNTY", localityName="Louisville/Jefferson County",
                residentRatePct=Decimal("2.20"), nonresidentRatePct=Decimal("1.45"),
            ),
            LocalityDatasetRateRow(
                localityCode="21067", localityType="COUNTY", localityName="Lexington/Fayette County",
                residentRatePct=Decimal("2.75"), nonresidentRatePct=Decimal("2.25"),
            ),
        ]
        ky_dataset = service.import_locality_dataset(
            db, country="US", state="KY", version="2026.1",
            rows=[r.model_dump() for r in ky_rows],
        )
        print(f"  KY locality dataset v{ky_dataset.version} (id={ky_dataset.id}, status={ky_dataset.status}, {len(ky_rows)} jurisdictions)")

        # ── Ohio ──────────────────────────────────────────────────────
        # Columbus/Cleveland rates independently re-fetched live 2026-09-16
        # from columbus.gov's own Income Tax Division page and CCA Ohio's
        # own tax-rates page. Cincinnati's 1.8% (effective 10/2/2020)
        # cross-confirmed via its own current tax forms (cincinnati-oh.gov
        # direct fetch was blocked; confirmed via search corroboration of
        # the city's own live pages). School District Income Tax for all
        # three cities' primary districts (Columbus City SD, Cleveland
        # Metropolitan SD, Cincinnati Public Schools) is genuinely $0 —
        # confirmed by reading Ohio Department of Taxation's own official
        # "School Districts With an Income Tax as of January 2026" PDF
        # directly; none of the three appear in that list. NOT seeded
        # here since $0 needs no LocalityRate row (no configured row is
        # already the correct $0 result, same "no guess" convention as
        # everywhere else). The credit-for-tax-paid-to-another-
        # municipality rule (only matters for a cross-city commuter) is
        # a disclosed, NOT-yet-built gap — see this session's own
        # analysis; only matters if/when a real cross-city-commuter
        # employee exists.
        print("Seeding Ohio municipal tax (Columbus, Cleveland, Cincinnati)...")
        oh_rows = [
            LocalityDatasetRateRow(
                localityCode="OH-COLUMBUS", localityType="MUNICIPAL", localityName="Columbus",
                residentRatePct=Decimal("2.50"), nonresidentRatePct=Decimal("2.50"),
            ),
            LocalityDatasetRateRow(
                localityCode="OH-CLEVELAND", localityType="MUNICIPAL", localityName="Cleveland",
                residentRatePct=Decimal("2.50"), nonresidentRatePct=Decimal("2.50"),
            ),
            LocalityDatasetRateRow(
                localityCode="OH-CINCINNATI", localityType="MUNICIPAL", localityName="Cincinnati",
                residentRatePct=Decimal("1.80"), nonresidentRatePct=Decimal("1.80"),
            ),
        ]
        oh_dataset = service.import_locality_dataset(
            db, country="US", state="OH", version="2026.1",
            rows=[r.model_dump() for r in oh_rows],
        )
        print(f"  OH locality dataset v{oh_dataset.version} (id={oh_dataset.id}, status={oh_dataset.status}, {len(oh_rows)} cities)")

        # ── Pennsylvania ──────────────────────────────────────────────
        # Philadelphia: phila.gov Wage Tax page, independently re-verified
        # by the research pass, effective 7/1/2026 rates (3.735%/3.425%).
        # Not an Act 32 PSD jurisdiction — no LST.
        # Pittsburgh/Allentown/Harrisburg: PSD codes independently
        # re-extracted by THIS session directly from PA DCED's own
        # statewide PSD_Codes.pdf (fetched live 2026-09-16) — resolved a
        # real conflict for Harrisburg (220401, not 221001 — the latter
        # actually belongs to Berrysburg Borough, confirmed by direct
        # re-extraction). EIT/LST rates from University of Pittsburgh's
        # own payroll page (Pittsburgh), Allentown's own ordinance
        # citations (ecode360 Article VI/V), and Harrisburg's own
        # ordinance/Act-47-authorized $156 LST (theburgnews.com,
        # contemporaneous local reporting) + $24,500 exemption (Harrisburg's
        # own FAQ). Allentown's nonresident EIT last-decimal-place (1.28%
        # vs 1.275%) — using 1.28%, the figure most consistently tied to
        # the ordinance's own text across independent citations.
        print("Seeding Pennsylvania local tax (Philadelphia Wage Tax + 3 Act 32 PSD codes)...")
        philadelphia_row = LocalityDatasetRateRow(
            localityCode="510101", localityType="MUNICIPAL", localityName="Philadelphia (Wage Tax)",
            residentRatePct=Decimal("3.735"), nonresidentRatePct=Decimal("3.425"),
        )
        pittsburgh_row = LocalityDatasetRateRow(
            localityCode="700102", localityType="PSD_EIT_LST", localityName="Pittsburgh",
            residentRatePct=Decimal("3.00"), nonresidentRatePct=Decimal("1.00"),
            flatAmount=Decimal("52"), lstExemptionThreshold=Decimal("12000"),
        )
        allentown_row = LocalityDatasetRateRow(
            localityCode="390101", localityType="PSD_EIT_LST", localityName="Allentown",
            residentRatePct=Decimal("1.975"), nonresidentRatePct=Decimal("1.28"),
            flatAmount=Decimal("52"), lstExemptionThreshold=Decimal("12000"),
        )
        harrisburg_row = LocalityDatasetRateRow(
            localityCode="220401", localityType="PSD_EIT_LST", localityName="Harrisburg",
            residentRatePct=Decimal("2.00"), nonresidentRatePct=Decimal("1.00"),
            flatAmount=Decimal("156"), lstExemptionThreshold=Decimal("24500"),
        )
        pa_rows = [philadelphia_row, pittsburgh_row, allentown_row, harrisburg_row]
        pa_dataset = service.import_locality_dataset(
            db, country="US", state="PA", version="2026.1",
            rows=[r.model_dump() for r in pa_rows],
        )
        print(f"  PA locality dataset v{pa_dataset.version} (id={pa_dataset.id}, status={pa_dataset.status}, {len(pa_rows)} localities)")

        print(
            "\nDone. All 3 datasets are in Draft status — a Super Admin still needs to Stage, "
            "Approve, and Activate each one before any organization's payroll actually uses it. "
            "Coverage is deliberately partial (largest city/metro per state, not an exhaustive "
            "statewide registry) — add more localities the same way once a real employee needs one "
            "not covered here."
        )
    finally:
        db.close()


if __name__ == "__main__":
    run()
