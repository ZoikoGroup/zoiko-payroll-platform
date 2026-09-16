"""
scripts/seed_us_phase4_kansas_2026.py
--------------------------------------------------
Kansas — Production-Readiness Plan Phase 4, closed out 2026-09-16. Real
KW-100 (Rev. 10-24) text independently verified this session: every one
of the source's 16 published per-pay-period bracket rows checks out
arithmetically (bracket-width * 5.2% == the published base-tax figure for
every row), and the Monthly table x12 cross-validates the annualized
structure below to within a few cents/dollars of rounding — see
hardcoded_defaults._US_KS_WITHHOLDING_PARAMS's own docstring.

Only the BRACKET rates (5.2% / 5.58%) are entered here — real, DB-editable
TaxSlab rows via the same bulk_import_state_tax_pack the Super Admin "New
State Import" UI uses. The personal-exemption/HOH/dependent-allowance
layer is NOT representable as a flat TaxSlab standard-deduction row (it
depends on a per-employee dependent count) — that's handled entirely by
engine/countries/us.py's _ks_personal_exemption_for_status, same division
of labor as Maine's income-phased-out deduction.

KW-100's own bracket table groups "SINGLE person (including Head of
Household)" as one bracket set and "MARRIED person" as the other; the
exemption-amount section separately groups "single, head of household, or
married filing separate" at the same $9,160 figure. Married Filing
Separate is therefore entered against the SINGLE bracket set here (the
natural reading of KW-100's own grouping — a separate filer is not
"MARRIED" for either the exemption or the bracket table), not against MFJ.

This is NOT a bypass of the governance lifecycle — the pack lands in
Draft status via bulk_import_state_tax_pack, same as every other Phase 4
pack; a distinct Super Admin still has to Approve, Publish, and Activate
it, with every publish gate (source evidence, effective date, golden-test
variance) still enforced.

Usage:
    python -m scripts.seed_us_phase4_kansas_2026
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decimal import Decimal

from app.database import SessionLocal
from app.modules.payroll import service


def run():
    db = SessionLocal()
    try:
        # KW-100 (Rev. 10-24), Table 6 (Semi-Annual) figures — cross-
        # validated against Monthly x12 as the cleanest annual-equivalent
        # reference (see hardcoded_defaults.py's own comment for why the
        # Quarterly/Semi-Annual/Annual tables don't scale linearly against
        # Weekly-Monthly, and why that's irrelevant here since Zoiko only
        # ever runs Weekly/Biweekly/Semi-monthly/Monthly payroll).
        single_hoh_mfs = [
            (Decimal("0"), Decimal("3605"), Decimal("0")),
            (Decimal("3605"), Decimal("26605"), Decimal("5.2")),
            (Decimal("26605"), None, Decimal("5.58")),
        ]
        mfj = [
            (Decimal("0"), Decimal("8240"), Decimal("0")),
            (Decimal("8240"), Decimal("54240"), Decimal("5.2")),
            (Decimal("54240"), None, Decimal("5.58")),
        ]
        print("Seeding Kansas state tax (2-bracket: 5.2% / 5.58%, embedded zero-band, personal exemption handled in-engine)...")
        bracket_rows = []
        for status in ("SINGLE", "HOH", "MFS"):
            for lo, hi, rate in single_hoh_mfs:
                bracket_rows.append({"filingStatus": status, "minAmount": lo, "maxAmount": hi, "ratePct": rate, "rateLabel": f"{rate}%"})
        for lo, hi, rate in mfj:
            bracket_rows.append({"filingStatus": "MFJ", "minAmount": lo, "maxAmount": hi, "ratePct": rate, "rateLabel": f"{rate}%"})
        ks_pack = service.bulk_import_state_tax_pack(
            db, jurisdiction_state="KS", version="2026.1", bracket_rows=bracket_rows,
        )
        print(f"  KS pack {ks_pack.pack_id} v{ks_pack.version} (id={ks_pack.id}, status={ks_pack.status}, {len(bracket_rows)} bracket rows)")

        print(
            "\nDone. Pack is in Draft status — a Super Admin still needs to review, link Source "
            "Evidence, set an Effective From date, Approve (a different Super Admin), and Activate "
            "it before any organization's payroll actually uses it. Note: employees with a Kansas "
            "work state also need their K-4 dependent count entered (ks_k4_dependents) for the "
            "personal-exemption layer to be correct — 0/unset dependents is assumed until then, "
            "never a guessed higher count."
        )
    finally:
        db.close()


if __name__ == "__main__":
    run()
