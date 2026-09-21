"""
tests/test_trinidad_and_tobago.py
------------------------------------
Validates engine/countries/trinidad_and_tobago.py against ZP-TT-ENG-001
§12 fixtures F1/F2, including the fixed 16-class NIS table lookup
(TT_NIS_CLASS rule_type) and the flat weekly Health Surcharge fee.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.standard import _COUNTRY_CALC
from app.modules.payroll.engine.countries import trinidad_and_tobago
from app.modules.payroll.engine.countries.shared import _calculate_annual_tax


@dataclass
class Rate:
    employee_rate_pct: Optional[Decimal] = None
    employer_rate_pct: Optional[Decimal] = None
    flat_amount: Optional[Decimal] = None


@dataclass
class Slab:
    min_amount: Decimal
    max_amount: Optional[Decimal]
    rate_pct: Decimal = Decimal("0")
    rule_type: str = "MARGINAL_RATE"
    formula_expression: Optional[str] = None
    filing_status: Optional[str] = None
    flat_amount: Optional[Decimal] = None
    # TT_NIS_CLASS's weekly EMPLOYER dollar amount — deliberately
    # adjustment_amount, NOT employer_rate_pct (a real Numeric(6,4)
    # percentage column on the actual TaxSlab model that overflows on a
    # $339.00 figure; this dataclass stand-in would never have caught
    # that, which is exactly why it was only found against real Postgres).
    adjustment_amount: Optional[Decimal] = None


def _tt_rate_map():
    return {
        "tt_personal_allowance": Rate(flat_amount=Decimal("90000")),
        "tt_health_surcharge_high": Rate(flat_amount=Decimal("8.25")),
        "tt_health_surcharge_low": Rate(flat_amount=Decimal("4.80")),
        "tt_hs_monthly_threshold": Rate(flat_amount=Decimal("469.99")),
        "tt_hs_weekly_threshold": Rate(flat_amount=Decimal("109")),
    }


def _tt_slabs():
    slabs = [
        Slab(min_amount=Decimal("0"), max_amount=Decimal("1000000"), rate_pct=Decimal("25")),
        Slab(min_amount=Decimal("1000000"), max_amount=None, rate_pct=Decimal("30")),
    ]
    slabs.append(Slab(min_amount=Decimal("9273"), max_amount=Decimal("10312.99"), rule_type="TT_NIS_CLASS",
                       filing_status="MONTHLY",
                       flat_amount=Decimal("122.00"), adjustment_amount=Decimal("244.00")))  # Class XII (monthly)
    slabs.append(Slab(min_amount=Decimal("13600"), max_amount=None, rule_type="TT_NIS_CLASS",
                       filing_status="MONTHLY",
                       flat_amount=Decimal("169.50"), adjustment_amount=Decimal("339.00")))  # Class XVI (monthly)
    slabs.append(Slab(min_amount=Decimal("610"), max_amount=Decimal("759.99"), rule_type="TT_NIS_CLASS",
                       filing_status="WEEKLY",
                       flat_amount=Decimal("37.00"), adjustment_amount=Decimal("74.00")))  # Class IV (weekly)
    return slabs


def _ctx(gross: Decimal, pay_frequency="Monthly") -> PayrollContext:
    return PayrollContext(gross=gross, basic=gross, country="TT", rate_map=_tt_rate_map(), slabs=_tt_slabs(), pay_frequency=pay_frequency)


def test_dispatch_resolves_tt_to_its_own_calculator():
    assert _COUNTRY_CALC["TT"] is trinidad_and_tobago.calculate


def test_tt_nis_class_rows_are_excluded_from_the_income_tax_bracket_sum():
    """A regression guard for the shared.py exclusion list: if TT_NIS_CLASS
    rows leaked into the bracket-sum loop, this would return a bogus huge
    number instead of the correct income-tax amount."""
    annual_tax = _calculate_annual_tax(Decimal("120000"), _tt_slabs())
    assert annual_tax == Decimal("30000")  # 25% of 120,000 — TaxSlab bands only


def test_fixture_f1_ordinary_monthly_employee_class_xii():
    result = trinidad_and_tobago.calculate(_ctx(Decimal("10000")))
    assert result["tds"] == Decimal("625.00")
    assert result["social_security"] == Decimal("488.00")          # 122.00 x 4 weeks
    assert result["employer_social_security"] == Decimal("976.00")  # 244.00 x 4 weeks
    assert result["professional_tax"] == Decimal("33.00")           # 8.25 x 4 weeks
    net = Decimal("10000") - result["tds"] - result["social_security"] - result["professional_tax"]
    assert net == Decimal("8854.00")


def test_fixture_f2_salary_above_nis_top_class_xvi():
    result = trinidad_and_tobago.calculate(_ctx(Decimal("15000")))
    assert result["tds"] == Decimal("1875.00")
    assert result["social_security"] == Decimal("678.00")           # 169.50 x 4
    assert result["employer_social_security"] == Decimal("1356.00")  # 339.00 x 4
    assert result["professional_tax"] == Decimal("33.00")
    net = Decimal("15000") - result["tds"] - result["social_security"] - result["professional_tax"]
    assert net == Decimal("12414.00")


def test_weekly_paid_employee_classified_against_weekly_bands_not_monthly():
    """A Weekly-paid employee earning $700/week must resolve against the
    WEEKLY band set (Class IV: 610-759.99) via filing_status, not the
    MONTHLY set (which would put $700 in Class I — a completely wrong
    class if the monthly/weekly bands were conflated)."""
    result = trinidad_and_tobago.calculate(_ctx(Decimal("700"), pay_frequency="Weekly"))
    assert result["social_security"] == Decimal("37.00")            # one week, no x4 multiplier
    assert result["employer_social_security"] == Decimal("74.00")


def test_weekly_paid_employee_uses_weekly_health_surcharge_threshold():
    """Spec: "monthly emoluments > TT$469.99 OR weekly emoluments >
    TT$109" — a $700/week employee is well above the $109 weekly
    threshold, so the high weekly rate applies, charged once (not x4)."""
    result = trinidad_and_tobago.calculate(_ctx(Decimal("700"), pay_frequency="Weekly"))
    assert result["professional_tax"] == Decimal("8.25")


def test_weekly_paid_employee_below_weekly_threshold_gets_low_health_surcharge_rate():
    result = trinidad_and_tobago.calculate(_ctx(Decimal("100"), pay_frequency="Weekly"))
    assert result["professional_tax"] == Decimal("4.80")
