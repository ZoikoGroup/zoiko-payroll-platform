"""
tests/test_cayman_islands.py
------------------------------
Validates engine/countries/cayman_islands.py against ZP-KY-ENG-001 §14
fixture F1, the no-income-tax invariant (F8), and the pension YTD-cap
fallback/wiring contract.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.standard import _COUNTRY_CALC
from app.modules.payroll.engine.countries import cayman_islands


@dataclass
class Rate:
    employee_rate_pct: Optional[Decimal] = None
    employer_rate_pct: Optional[Decimal] = None
    flat_amount: Optional[Decimal] = None


def _ky_rate_map():
    return {
        "ky_pension_annual_cap": Rate(flat_amount=Decimal("87000")),
        "ky_pension": Rate(employee_rate_pct=Decimal("0.05"), employer_rate_pct=Decimal("0.05")),
    }


def _ctx(gross: Decimal, pay_frequency="Monthly", ytd_before=None) -> PayrollContext:
    return PayrollContext(
        gross=gross, basic=gross, country="KY", rate_map=_ky_rate_map(), slabs=[],
        pay_frequency=pay_frequency, ytd_ky_mandatory_pensionable_earnings_before=ytd_before,
    )


def test_dispatch_resolves_cayman_to_its_own_calculator():
    assert _COUNTRY_CALC["KY"] is cayman_islands.calculate


def test_no_income_tax_invariant():
    result = cayman_islands.calculate(_ctx(Decimal("6000")))
    assert result["tds"] == Decimal("0")


def test_fixture_f1_ordinary_pension_month():
    result = cayman_islands.calculate(_ctx(Decimal("6000")))
    assert result["employee_pension"] == Decimal("300.00")
    assert result["employer_pension"] == Decimal("300.00")
    assert result["pension_cap_ytd_wired"] is False


def test_ytd_cap_crossing_when_accumulator_is_wired():
    """Fixture F2: YTD mandatory pensionable earnings already at 80,000 of
    the 87,000 annual cap; this period's earnings are 10,000 — only 7,000
    is mandatory."""
    result = cayman_islands.calculate(_ctx(Decimal("10000"), ytd_before=Decimal("80000")))
    assert result["employee_pension"] == Decimal("350.00")   # 5% of 7,000
    assert result["employer_pension"] == Decimal("350.00")
    assert result["pension_cap_ytd_wired"] is True


def test_ytd_cap_fully_exhausted_yields_zero_mandatory_pension():
    result = cayman_islands.calculate(_ctx(Decimal("5000"), ytd_before=Decimal("87000")))
    assert result["employee_pension"] == Decimal("0.00")
    assert result["employer_pension"] == Decimal("0.00")
