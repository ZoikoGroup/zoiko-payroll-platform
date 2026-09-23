"""
scripts/seed_caribbean_canonical_packs.py
-------------------------------------------------
Seeds the canonical (organization_id IS NULL) JurisdictionPack + TaxSlab +
ContributionRate rows for the 7 production-ready Caribbean countries
(Barbados, Cayman Islands, Dominican Republic, Guyana, Jamaica, Bahamas,
Trinidad and Tobago). This is what makes each country's engine module
(engine/countries/<country>.py) DB-driven rather than Python-hardcoded —
every rate/threshold/ceiling/band below is a real row an org's payroll
run and Super Admin's Compliance UI both read the exact same way IN/US/
UK/AU/DE/CA's own canonical rows already work.

Idempotent — deletes and re-inserts each country's canonical rows under
its own Active pack version, never touches org-scoped (organization_id
IS NOT NULL) rows, and never touches any other country's pack.

Component keys here MUST match the resolve_jurisdiction_parameter() keys
each engine/countries/<country>.py module reads — see each module's own
docstring for its exact mapping.

Usage:
    python -m scripts.seed_caribbean_canonical_packs
"""
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, initialize_database
from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab
from scripts._local_db_guard import assert_local_database

TAX_YEAR = "2026"
EFFECTIVE_FROM = date(2026, 1, 1)


def _upsert_pack(db, code: str, currency: str) -> JurisdictionPack:
    pack_id = f"{code}-PAYROLL-2026-V1"
    pack = (
        db.query(JurisdictionPack)
        .filter(JurisdictionPack.pack_id == pack_id, JurisdictionPack.version == "1.0")
        .first()
    )
    if pack is None:
        pack = JurisdictionPack(pack_id=pack_id, jurisdiction_country=code, version="1.0")
        db.add(pack)
    pack.jurisdiction_state = None
    pack.pack_type = "tax"
    pack.status = "Active"
    pack.effective_from = EFFECTIVE_FROM
    pack.effective_to = None
    pack.tax_year = TAX_YEAR
    pack.currency = currency
    pack.compliance_owner = "Super Admin — Caribbean build"
    pack.source_references = "See ZP-<code>-ENG-001 engineering specification"
    db.flush()

    # Clear this pack's own canonical rows so re-running the script never
    # duplicates — org-scoped rows (organization_id IS NOT NULL) and every
    # other country's pack are untouched.
    db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id, TaxSlab.organization_id.is_(None)).delete()
    db.query(ContributionRate).filter(
        ContributionRate.jurisdiction_pack_id == pack.id, ContributionRate.organization_id.is_(None)
    ).delete()
    db.flush()
    return pack


def _add_slab(db, pack, code, min_amount, max_amount, rate_pct, label, rule_type="MARGINAL_RATE",
              flat_amount=None, employer_rate_pct=None, adjustment_amount=None, sort_order=0, filing_status=None):
    db.add(TaxSlab(
        jurisdiction_pack_id=pack.id,
        jurisdiction_country=code,
        organization_id=None,
        min_amount=Decimal(str(min_amount)),
        max_amount=Decimal(str(max_amount)) if max_amount is not None else None,
        rate_pct=Decimal(str(rate_pct)),
        rate_label=label,
        tax_formula=label,
        rule_type=rule_type,
        flat_amount=Decimal(str(flat_amount)) if flat_amount is not None else None,
        # employer_rate_pct is Numeric(6,4) — a real PERCENTAGE column
        # (max ~99.9999) — never use it for a dollar figure. TT_NIS_CLASS
        # uses adjustment_amount (Numeric(10,2)) for its weekly employer
        # dollar amount instead — see shared.py's own docstring.
        employer_rate_pct=Decimal(str(employer_rate_pct)) if employer_rate_pct is not None else None,
        adjustment_amount=Decimal(str(adjustment_amount)) if adjustment_amount is not None else None,
        sort_order=sort_order,
        filing_status=filing_status,
    ))


def _add_rate(db, pack, code, component_key, label, employee_rate_pct=None, employer_rate_pct=None,
              flat_amount=None, sort_order=0):
    employee_dec = Decimal(str(employee_rate_pct)) if employee_rate_pct is not None else None
    employer_dec = Decimal(str(employer_rate_pct)) if employer_rate_pct is not None else None

    def _display(pct):
        return f"{pct}%" if pct is not None else "—"

    def _display_amount(amount):
        return str(amount) if amount is not None else "—"

    employee_share = _display(employee_dec) if flat_amount is None else _display_amount(flat_amount)
    employer_share = _display(employer_dec) if flat_amount is None else "—"
    total = employee_share if flat_amount is not None else _display(
        (employee_dec or Decimal("0")) + (employer_dec or Decimal("0"))
    )
    db.add(ContributionRate(
        jurisdiction_pack_id=pack.id,
        jurisdiction_country=code,
        organization_id=None,
        component_key=component_key,
        label=label,
        employee_share=employee_share,
        employer_share=employer_share,
        total=total,
        employee_rate_pct=employee_dec,
        employer_rate_pct=employer_dec,
        flat_amount=Decimal(str(flat_amount)) if flat_amount is not None else None,
        sort_order=sort_order,
    ))


def seed_barbados(db):
    pack = _upsert_pack(db, "BB", "BBD")
    _add_slab(db, pack, "BB", 0, 50000, 11.5, "11.5%", sort_order=1)
    _add_slab(db, pack, "BB", 50000, None, 27.5, "27.5%", sort_order=2)
    _add_rate(db, pack, "BB", "bb_personal_allowance", "Personal Allowance (annual)", flat_amount=25000)
    # NOTE: employee_rate_pct/employer_rate_pct store a FRACTION (e.g.
    # 0.1100 for 11%), NOT a percentage number — see ContributionRate's
    # own column comment in payroll/models.py ("e.g. 0.1200 for 12%").
    # TaxSlab.rate_pct (used by _add_slab above) is the opposite
    # convention (5.0000 for 5%) — do not mix the two conventions up.
    _add_rate(db, pack, "BB", "bb_nis", "NIS (code R)", employee_rate_pct=0.1100, employer_rate_pct=0.1275)
    _add_rate(db, pack, "BB", "bb_nis_ceiling_weekly", "NIS Weekly Ceiling", flat_amount=1238)
    _add_rate(db, pack, "BB", "bb_nis_ceiling_monthly", "NIS Monthly Ceiling", flat_amount=5360)
    _add_rate(db, pack, "BB", "bb_resilience_regeneration", "Resilience & Regeneration Levy",
              employee_rate_pct=0.0025, employer_rate_pct=0.0025)


def seed_cayman_islands(db):
    pack = _upsert_pack(db, "KY", "KYD")
    _add_rate(db, pack, "KY", "ky_pension_annual_cap", "Mandatory Pension Annual Cap", flat_amount=87000)
    _add_rate(db, pack, "KY", "ky_pension", "Mandatory Pension", employee_rate_pct=0.05, employer_rate_pct=0.05)


def seed_dominican_republic(db):
    pack = _upsert_pack(db, "DO", "DOP")
    _add_slab(db, pack, "DO", 416220, 624329, 15, "15%", sort_order=1)
    _add_slab(db, pack, "DO", 624329, 867123, 20, "20%", sort_order=2)
    _add_slab(db, pack, "DO", 867123, None, 25, "25%", sort_order=3)
    _add_rate(db, pack, "DO", "do_sfs_ceiling", "SFS Ceiling", flat_amount=232230)
    _add_rate(db, pack, "DO", "do_sfs", "SFS (health)", employee_rate_pct=0.0304, employer_rate_pct=0.0709)
    _add_rate(db, pack, "DO", "do_pension_ceiling", "Pension (SVDS) Ceiling", flat_amount=464460)
    _add_rate(db, pack, "DO", "do_pension", "Pension (SVDS)", employee_rate_pct=0.0287, employer_rate_pct=0.0710)
    _add_rate(db, pack, "DO", "do_srl_ceiling", "Occupational Risk (SRL) Ceiling", flat_amount=92892)
    _add_rate(db, pack, "DO", "do_srl", "Occupational Risk (SRL) — risk type I default", employer_rate_pct=0.0110)
    _add_rate(db, pack, "DO", "do_infotep", "INFOTEP", employer_rate_pct=0.0100)


def seed_guyana(db):
    pack = _upsert_pack(db, "GY", "GYD")
    # Bands are period (monthly)-denominated directly — see
    # engine/countries/guyana.py's own docstring for why.
    _add_slab(db, pack, "GY", 0, 280000, 25, "25%", sort_order=1)
    _add_slab(db, pack, "GY", 280000, None, 35, "35%", sort_order=2)
    _add_rate(db, pack, "GY", "gy_personal_allowance", "Personal Deduction (monthly minimum)", flat_amount=140000)
    _add_rate(db, pack, "GY", "gy_nis", "NIS", employee_rate_pct=0.056, employer_rate_pct=0.084)
    _add_rate(db, pack, "GY", "gy_nis_ceiling_monthly", "NIS Monthly Ceiling", flat_amount=280000)
    _add_rate(db, pack, "GY", "gy_nis_ceiling_weekly", "NIS Weekly Ceiling", flat_amount=64615)


def seed_jamaica(db):
    pack = _upsert_pack(db, "JM", "JMD")
    _add_slab(db, pack, "JM", 0, 6000000, 25, "25%", sort_order=1)
    _add_slab(db, pack, "JM", 6000000, None, 30, "30%", sort_order=2)
    _add_rate(db, pack, "JM", "jm_personal_allowance", "Personal Allowance (annual, Apr-Dec rate)", flat_amount=1902360)
    _add_rate(db, pack, "JM", "jm_nis", "NIS", employee_rate_pct=0.03, employer_rate_pct=0.03)
    _add_rate(db, pack, "JM", "jm_nht", "NHT", employee_rate_pct=0.02, employer_rate_pct=0.03)
    _add_rate(db, pack, "JM", "jm_education_tax", "Education Tax", employee_rate_pct=0.0225, employer_rate_pct=0.035)
    _add_rate(db, pack, "JM", "jm_heart_threshold", "HEART Threshold (monthly emoluments)", flat_amount=14444)
    _add_rate(db, pack, "JM", "jm_heart", "HEART (employer)", employer_rate_pct=0.03)


def seed_bahamas(db):
    pack = _upsert_pack(db, "BS", "BSD")
    _add_rate(db, pack, "BS", "bs_nib", "NIB", employee_rate_pct=0.0465, employer_rate_pct=0.0665)
    _add_rate(db, pack, "BS", "bs_nib_ceiling_weekly", "NIB Weekly Ceiling", flat_amount=830)
    _add_rate(db, pack, "BS", "bs_nib_ceiling_monthly", "NIB Monthly Ceiling", flat_amount=3597)


def seed_trinidad_and_tobago(db):
    pack = _upsert_pack(db, "TT", "TTD")
    _add_slab(db, pack, "TT", 0, 1000000, 25, "25%", sort_order=1)
    _add_slab(db, pack, "TT", 1000000, None, 30, "30%", sort_order=2)
    _add_rate(db, pack, "TT", "tt_personal_allowance", "Personal Allowance (annual)", flat_amount=90000)
    _add_rate(db, pack, "TT", "tt_health_surcharge_high", "Health Surcharge — high rate (weekly)", flat_amount=8.25)
    _add_rate(db, pack, "TT", "tt_health_surcharge_low", "Health Surcharge — low rate (weekly)", flat_amount=4.80)
    _add_rate(db, pack, "TT", "tt_hs_monthly_threshold", "Health Surcharge monthly threshold", flat_amount=469.99)
    _add_rate(db, pack, "TT", "tt_hs_weekly_threshold", "Health Surcharge weekly threshold", flat_amount=109)

    # 16-class fixed NIS table (rule_type="TT_NIS_CLASS" — see
    # engine/countries/shared.py's docstring for the column-reuse
    # convention: flat_amount = weekly employee amount, adjustment_amount
    # (repurposed as a plain dollar figure — NOT employer_rate_pct, whose
    # Numeric(6,4) column overflows on a $339.00 Class-XVI employer
    # figure) = weekly employer amount. filing_status ("MONTHLY"/"WEEKLY", repurposed — see
    # engine/countries/trinidad_and_tobago.py's docstring) tags which
    # earnings-band boundary set a row belongs to; the two sets use
    # genuinely different min/max numbers for the SAME 16 dollar-amount
    # classes (NIBTT's own table gives both a weekly and monthly earnings
    # range per class).
    nis_classes_monthly = [
        (0, 1472.99, 14.60, 29.20),          # Class I (monthly floor set to 0, not 867, to catch every low earner)
        (1473, 1949.99, 21.30, 42.60),       # II
        (1950, 2642.99, 28.60, 57.20),       # III
        (2643, 3292.99, 37.00, 74.00),       # IV
        (3293, 4029.99, 45.60, 91.20),       # V
        (4030, 4852.99, 55.40, 110.80),      # VI
        (4853, 5632.99, 65.30, 130.60),      # VII
        (5633, 6456.99, 75.30, 150.60),      # VIII
        (6457, 7409.99, 86.40, 172.80),      # IX
        (7410, 8276.99, 97.70, 195.40),      # X
        (8277, 9272.99, 109.40, 218.80),     # XI
        (9273, 10312.99, 122.00, 244.00),    # XII
        (10313, 11396.99, 135.30, 270.60),   # XIII
        (11397, 12652.99, 149.90, 299.80),   # XIV
        (12653, 13599.99, 163.60, 327.20),   # XV
        (13600, None, 169.50, 339.00),       # XVI
    ]
    nis_classes_weekly = [
        (0, 339.99, 14.60, 29.20),           # Class I (weekly floor set to 0, not 200, to catch every low earner)
        (340, 449.99, 21.30, 42.60),         # II
        (450, 609.99, 28.60, 57.20),         # III
        (610, 759.99, 37.00, 74.00),         # IV
        (760, 929.99, 45.60, 91.20),         # V
        (930, 1119.99, 55.40, 110.80),       # VI
        (1120, 1299.99, 65.30, 130.60),      # VII
        (1300, 1489.99, 75.30, 150.60),      # VIII
        (1490, 1709.99, 86.40, 172.80),      # IX
        (1710, 1909.99, 97.70, 195.40),      # X
        (1910, 2139.99, 109.40, 218.80),     # XI
        (2140, 2379.99, 122.00, 244.00),     # XII
        (2380, 2629.99, 135.30, 270.60),     # XIII
        (2630, 2919.99, 149.90, 299.80),     # XIV
        (2920, 3137.99, 163.60, 327.20),     # XV
        (3138, None, 169.50, 339.00),        # XVI
    ]
    for i, (lo, hi, emp_weekly, empr_weekly) in enumerate(nis_classes_monthly, start=1):
        _add_slab(
            db, pack, "TT", lo, hi, rate_pct=0, label=f"NIS Class {i}", rule_type="TT_NIS_CLASS",
            flat_amount=emp_weekly, adjustment_amount=empr_weekly, sort_order=100 + i, filing_status="MONTHLY",
        )
    for i, (lo, hi, emp_weekly, empr_weekly) in enumerate(nis_classes_weekly, start=1):
        _add_slab(
            db, pack, "TT", lo, hi, rate_pct=0, label=f"NIS Class {i}", rule_type="TT_NIS_CLASS",
            flat_amount=emp_weekly, adjustment_amount=empr_weekly, sort_order=200 + i, filing_status="WEEKLY",
        )


SEEDERS = [
    seed_barbados,
    seed_cayman_islands,
    seed_dominican_republic,
    seed_guyana,
    seed_jamaica,
    seed_bahamas,
    seed_trinidad_and_tobago,
]


def main() -> None:
    assert_local_database("seed_caribbean_canonical_packs")
    initialize_database()
    db = SessionLocal()
    try:
        for seeder in SEEDERS:
            seeder(db)
            db.commit()
            print(f"seeded {seeder.__name__}")
        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
