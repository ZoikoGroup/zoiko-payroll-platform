"""Contract tests pinning saudi_arabia_content.py and eos.py to ZP-SA-ENG-001.

These assert the RULES the specification states (who pays which branch, the EOS
bands, the evidence register), so a content edit that contradicts the spec fails
here before it can reach a pack. Expected figures are hand-computed.
"""
from decimal import Decimal
from fractions import Fraction
from types import SimpleNamespace

import pytest

from app.modules.payroll.engine.countries import saudi_arabia, saudi_arabia_content as content
from app.modules.payroll.engine.fallback_registry import _ENGINE_CONSTANT_REGISTRY, get_engine_fallback_inventory
from app.modules.payroll.engine.jurisdictions.saudi_arabia import eos


# ── content rules ───────────────────────────────────────────────────────────
def test_only_saudi_and_non_saudi_have_branch_rows():
    assert {row[0] for row in content.SA_GOSI_BRANCHES} == {"SAUDI", "NON_SAUDI"}


def test_non_saudi_is_occupational_hazards_only_employer_two_percent():
    rows = [r for r in content.SA_GOSI_BRANCHES if r[0] == "NON_SAUDI"]
    assert [(r[1], r[2], r[3]) for r in rows] == [("OCCUPATIONAL_HAZARDS", "0.0000", "2.0000")]


def test_saudi_branch_rates_match_spec_section_4():
    saudi = {(r[1], r[6]): (r[2], r[3]) for r in content.SA_GOSI_BRANCHES if r[0] == "SAUDI"}
    from datetime import date
    assert saudi[("PENSION_NEW", date(2026, 1, 1))] == ("9.5000", "9.5000")
    assert saudi[("PENSION_NEW", date(2026, 7, 3))] == ("10.0000", "10.0000")
    assert saudi[("PENSION_LEGACY", date(2026, 1, 1))] == ("9.0000", "9.0000")
    assert saudi[("SANED", date(2026, 1, 1))] == ("0.7500", "0.7500")
    assert saudi[("OCCUPATIONAL_HAZARDS", date(2026, 1, 1))] == ("0.0000", "2.0000")


def test_new_system_rows_do_not_overlap_and_meet_at_3_july():
    from datetime import date, timedelta
    new = sorted((r for r in content.SA_GOSI_BRANCHES if r[1] == "PENSION_NEW"), key=lambda r: r[6])
    assert new[0][7] + timedelta(days=1) == new[1][6] == date(2026, 7, 3)


def test_wage_limits_match_sa_010():
    for row in content.SA_GOSI_BRANCHES:
        assert row[5] == "45000"
        assert row[4] == ("400" if row[1] == "OCCUPATIONAL_HAZARDS" else "1500")


def test_gosi_base_is_basic_plus_housing_only():
    gosi = {c: t for (o, t, c, *_rest) in content.SA_EARNING_CLASSES if o == "GOSI"}
    included = {c for c, t in gosi.items() if t == "INCLUDED"}
    assert included == {"BASIC", "HOUSING", "HOUSING_IN_KIND"}
    for component in ("ALLOWANCE_REGULAR", "COMMISSION", "OVERTIME", "BONUS", "OTHER_EARNINGS"):
        assert gosi[component] == "REVIEW"


def test_every_row_cites_a_real_evidence_code():
    codes = set(content.SOURCE_CODES)
    assert codes == {f"S{i}" for i in range(1, 17)}
    for row in content.SA_SCALAR_CONTENT:
        assert row[6] in codes, row[0]
    for row in content.SA_GOSI_BRANCHES:
        assert row[9] in codes, row[8]
    for row in content.SA_EARNING_CLASSES:
        assert row[4] in codes, row[3]


def test_engine_parameter_catalog_is_the_content_catalog():
    assert saudi_arabia.SA_PARAMETER_KEYS is content.SA_PARAMETER_KEYS
    seeded = {row[0] for row in content.SA_SCALAR_CONTENT}
    # sa_damage_cap_pct is deliberately unseeded: the spec states no value.
    assert set(content.SA_PARAMETER_KEYS) - seeded == {"sa_damage_cap_pct"}
    assert seeded <= set(content.SA_PARAMETER_KEYS)


def test_fallback_registry_covers_every_parameter_and_resolves():
    registry_keys = {e["resolverKey"] for e in _ENGINE_CONSTANT_REGISTRY if e["country"] == "SA"}
    assert registry_keys == set(content.SA_PARAMETER_KEYS) - {
        "sa_annual_leave_days_base", "sa_annual_leave_days_after_5_years", "sa_sick_leave_full_pay_days",
        "sa_sick_leave_75_pct_days", "sa_sick_leave_unpaid_days", "sa_maternity_leave_weeks",
        "sa_maternity_mandatory_post_birth_weeks"}
    inventory = get_engine_fallback_inventory()  # raises if a module/attr is missing
    assert any(e["country"] == "SA" for e in inventory["engineConstants"])


# ── EOS (spec §13, fixture F6) ──────────────────────────────────────────────
def _row(flat=None, text=None):
    return SimpleNamespace(flat_amount=None if flat is None else Decimal(flat), text_value=text)


RATES = {
    "sa_eos_first_5_years_months": _row("0.5"),
    "sa_eos_after_5_years_months": _row("1"),
    "sa_eos_resign_frac_under_2": _row(text="0"),
    "sa_eos_resign_frac_2_to_5": _row(text="1/3"),
    "sa_eos_resign_frac_5_to_10": _row(text="2/3"),
    "sa_eos_resign_frac_10_plus": _row(text="1"),
}


def test_f6_employer_termination_eight_years():
    # 5 x 6,000 + 3 x 12,000 = 66,000
    award = eos.eos_award(Decimal("12000"), 8, RATES)
    assert award["award"] == Decimal("66000.00")
    assert eos.settlement_amount(award, False, 8, RATES)["payable"] == Decimal("66000.00")


@pytest.mark.parametrize("years, fraction, payable", [
    ("1.9", Fraction(0), None),
    ("2", Fraction(1, 3), None),
    ("5", Fraction(1, 3), None),
    ("5.01", Fraction(2, 3), None),
    ("8", Fraction(2, 3), Decimal("44000.00")),    # F6 resigned: 66,000 x 2/3
    ("9.99", Fraction(2, 3), None),
    ("10", Fraction(1), None),
])
def test_resignation_bands(years, fraction, payable):
    out = eos.resignation_fraction(Decimal(years), RATES)
    assert out["fraction"] == fraction
    if payable is not None:
        award = eos.eos_award(Decimal("12000"), Decimal(years), RATES)
        assert eos.settlement_amount(award, True, Decimal(years), RATES)["payable"] == payable


def test_resignation_three_years_one_third_is_exact():
    # 3 x 6,000 = 18,000 x 1/3 = 6,000 exactly (no 0.3333 drift)
    award = eos.eos_award(Decimal("12000"), 3, RATES)
    assert eos.settlement_amount(award, True, 3, RATES)["payable"] == Decimal("6000.00")


def test_rounded_numeric_fraction_is_rejected():
    rates = dict(RATES, sa_eos_resign_frac_2_to_5=_row("0.33"))
    assert eos.resignation_fraction(3, rates)["status"] == "NOT_EVALUATED"


def test_partial_year_is_pro_rata():
    # 2.5 years x 0.5 month x 10,000 = 12,500
    assert eos.eos_award(Decimal("10000"), Decimal("2.5"), RATES)["award"] == Decimal("12500.00")
