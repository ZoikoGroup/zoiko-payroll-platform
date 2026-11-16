"""
tests/test_duplicate_slab_rows.py
---------------------------------
Exact-copy TaxSlab rows (A3, 2026-11-16).

The read-only production audit of 2026-11-14 found 47 exact copies of
tax-slab rows in the Active UK pack (#24). Pack sync copied canonical slabs
one-for-one into every org, and the UK NI band and income-tax bracket sums add
every row in, so a copied band was charged twice. Both places now keep one
row of any identical group; rows that differ in any field are all kept.
"""

import copy
from decimal import Decimal

from app.modules.payroll import service
from app.modules.payroll.engine.countries.uk import (
    _calculate_ni_from_bands, _drop_identical_slabs, _resolve_ni_bands, _resolve_ni_bands_by_frequency,
)
from app.modules.payroll.models import JurisdictionPack, TaxSlab
from tests.test_engine_jurisdiction_upgrade import _NI_CAT_A_BANDS, UK_RATES, UK_SLABS, Slab, calc


def _copies(rows, times=3):
    return [copy.copy(r) for r in rows for _ in range(times)]


# ── engine: UK NI bands and income-tax brackets ─────────────────────────────

def test_identical_rows_are_dropped_and_distinct_rows_kept():
    a = Slab(Decimal("0"), Decimal("100"), Decimal("10"))
    b = Slab(Decimal("0"), Decimal("100"), Decimal("12"))  # differs in rate only
    kept = _drop_identical_slabs([a, copy.copy(a), b, copy.copy(a)])
    assert kept == [a, b]


def test_copied_ni_bands_are_counted_once():
    bands = _resolve_ni_bands(_copies(_NI_CAT_A_BANDS), "A")
    assert len(bands) == 4
    assert _calculate_ni_from_bands(Decimal("60000"), bands) == (Decimal("3210.60"), Decimal("8250.00"))


def test_copied_per_period_ni_bands_are_counted_once():
    weekly = [Slab(Decimal("0"), Decimal("242"), Decimal("0"), rule_type="NI_BAND_WEEKLY"),
              Slab(Decimal("242"), None, Decimal("8"), rule_type="NI_BAND_WEEKLY")]
    for band in weekly:
        band.ni_category, band.employer_rate_pct = "A", Decimal("15")
    assert len(_resolve_ni_bands_by_frequency(_copies(weekly), "A", "Weekly")) == 2


def test_payslip_with_copied_bands_matches_a_single_set():
    single = calc("UK", 5000, UK_RATES, UK_SLABS + _NI_CAT_A_BANDS, ni_category="A", pay_frequency="Fortnightly")
    copied = calc("UK", 5000, UK_RATES, _copies(UK_SLABS) + _copies(_NI_CAT_A_BANDS),
                  ni_category="A", pay_frequency="Fortnightly")
    assert (copied.ni_employee, copied.employer_ni, copied.tds) == (
        single.ni_employee, single.employer_ni, single.tds)
    assert single.ni_employee > 0 and single.tds > 0


# ── pack sync: one org row per identical canonical group ─────────────────────

def _uk_pack(db):
    pack = JurisdictionPack(pack_id="UK-DUP-TEST", jurisdiction_country="UK", pack_type="tax",
                            version="1.0", status="Active")
    db.add(pack)
    db.commit()
    db.refresh(pack)
    return pack


def _canonical_band(pack, min_amount, max_amount, rate, category="A"):
    return TaxSlab(organization_id=None, jurisdiction_country="UK", jurisdiction_pack_id=pack.id,
                   min_amount=Decimal(min_amount), max_amount=None if max_amount is None else Decimal(max_amount),
                   rate_pct=Decimal(rate), employer_rate_pct=Decimal("15"), rate_label=f"{rate}%", tax_formula="",
                   rule_type="NI_BAND", ni_category=category)


def test_sync_copies_each_identical_canonical_row_once(db, organization):
    pack = _uk_pack(db)
    for _ in range(3):
        db.add(_canonical_band(pack, "12570", "50270", "8"))
    db.add(_canonical_band(pack, "12570", "50270", "8", category="B"))  # different category: kept
    db.add(_canonical_band(pack, "50270", None, "2"))
    db.commit()

    service.sync_org_rates_from_canonical(db, organization.id, "UK")
    org_rows = db.query(TaxSlab).filter(TaxSlab.organization_id == organization.id,
                                        TaxSlab.jurisdiction_country == "UK").all()
    assert sorted((r.ni_category, r.min_amount) for r in org_rows) == [
        ("A", Decimal("12570")), ("A", Decimal("50270")), ("B", Decimal("12570"))]


# ── A5: every country's income-tax bracket sum (shared engine) ───────────────

from app.modules.payroll.engine.countries.shared import _calculate_annual_tax  # noqa: E402
from tests.test_engine_jurisdiction_upgrade import IN_RATES, IN_SLABS, US_RATES, US_SLABS  # noqa: E402


def test_shared_bracket_sum_counts_a_copied_bracket_once():
    single = _calculate_annual_tax(Decimal("80000"), US_SLABS)
    assert _calculate_annual_tax(Decimal("80000"), _copies(US_SLABS)) == single == Decimal("11000")


def test_copied_filing_status_bracket_is_counted_once():
    # The US pack #32 shape: a filing-status bracket stored twice.
    mfj = [Slab(Decimal("0"), Decimal("100000"), Decimal("12"), filing_status="MFJ")]
    single_set = _calculate_annual_tax(Decimal("60000"), mfj, filing_status="MFJ")
    assert _calculate_annual_tax(Decimal("60000"), _copies(mfj, 2), filing_status="MFJ") == single_set


def test_us_payslip_with_copied_federal_brackets_matches_a_single_set():
    single = calc("US", 8000, US_RATES, US_SLABS)
    copied = calc("US", 8000, US_RATES, _copies(US_SLABS, 2))
    assert copied.tds == single.tds and single.tds > 0


def test_india_payslip_with_copied_brackets_matches_a_single_set():
    single = calc("IN", 150000, IN_RATES, IN_SLABS)
    assert calc("IN", 150000, IN_RATES, _copies(IN_SLABS, 2)).tds == single.tds
