"""
tests/test_bahamas.py
------------------------
Validates engine/countries/bahamas.py against ZP-BS-ENG-001 §12 fixtures
F1/F2 and the no-income-tax invariant.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.standard import _COUNTRY_CALC
from app.modules.payroll.engine.countries import bahamas


@dataclass
class Rate:
    employee_rate_pct: Optional[Decimal] = None
    employer_rate_pct: Optional[Decimal] = None
    flat_amount: Optional[Decimal] = None


def _bs_rate_map():
    return {
        "bs_nib": Rate(employee_rate_pct=Decimal("0.0465"), employer_rate_pct=Decimal("0.0665")),
        "bs_nib_ceiling_weekly": Rate(flat_amount=Decimal("830")),
        "bs_nib_ceiling_monthly": Rate(flat_amount=Decimal("3597")),
    }


def _ctx(gross: Decimal, pay_frequency="Weekly") -> PayrollContext:
    return PayrollContext(gross=gross, basic=gross, country="BS", rate_map=_bs_rate_map(), slabs=[], pay_frequency=pay_frequency)


def test_dispatch_resolves_bahamas_to_its_own_calculator():
    assert _COUNTRY_CALC["BS"] is bahamas.calculate


def test_no_income_tax_invariant():
    result = bahamas.calculate(_ctx(Decimal("700")))
    assert result["tds"] == Decimal("0")


def test_fixture_f1_ordinary_below_ceiling():
    result = bahamas.calculate(_ctx(Decimal("700")))
    assert result["social_security"] == Decimal("32.55")
    assert result["employer_social_security"] == Decimal("46.55")
    net = Decimal("700") - result["social_security"]
    assert net == Decimal("667.45")


def test_fixture_f2_above_weekly_ceiling():
    result = bahamas.calculate(_ctx(Decimal("1000")))
    assert result["social_security"] == Decimal("38.60")
    assert result["employer_social_security"] == Decimal("55.20")
