"""
tests/test_jamaica.py
------------------------
Validates engine/countries/jamaica.py against ZP-JM-ENG-001 §12 Fixture
F1 — including the fixture's own accounting invariant (employee
deductions total 23,232.50, employer contributions total 24,790.00, net
cash 176,767.50).
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.standard import StandardStrategy, _COUNTRY_CALC
from app.modules.payroll.engine.countries import jamaica


@dataclass
class Rate:
    employee_rate_pct: Optional[Decimal] = None
    employer_rate_pct: Optional[Decimal] = None
    flat_amount: Optional[Decimal] = None


@dataclass
class Slab:
    min_amount: Decimal
    max_amount: Optional[Decimal]
    rate_pct: Decimal
    rule_type: str = "MARGINAL_RATE"
    formula_expression: Optional[str] = None
    filing_status: Optional[str] = None


def _jm_rate_map():
    return {
        "jm_personal_allowance": Rate(flat_amount=Decimal("1902360")),
        "jm_nis": Rate(employee_rate_pct=Decimal("0.03"), employer_rate_pct=Decimal("0.03")),
        "jm_nht": Rate(employee_rate_pct=Decimal("0.02"), employer_rate_pct=Decimal("0.03")),
        "jm_education_tax": Rate(employee_rate_pct=Decimal("0.0225"), employer_rate_pct=Decimal("0.035")),
        "jm_heart_threshold": Rate(flat_amount=Decimal("14444")),
        "jm_heart": Rate(employer_rate_pct=Decimal("0.03")),
    }


def _jm_slabs():
    return [
        Slab(min_amount=Decimal("0"), max_amount=Decimal("6000000"), rate_pct=Decimal("25")),
        Slab(min_amount=Decimal("6000000"), max_amount=None, rate_pct=Decimal("30")),
    ]


def _ctx(gross: Decimal) -> PayrollContext:
    return PayrollContext(gross=gross, basic=gross, country="JM", rate_map=_jm_rate_map(), slabs=_jm_slabs(), pay_frequency="Monthly")


def test_dispatch_resolves_jamaica_to_its_own_calculator():
    assert _COUNTRY_CALC["JM"] is jamaica.calculate


def test_fixture_f1_regular_monthly_cash_salary():
    result = jamaica.calculate(_ctx(Decimal("200000")))
    assert result["social_security"] == Decimal("6000.00")        # NIS employee
    assert result["employer_social_security"] == Decimal("6000.00")  # NIS employer
    assert result["employee_pension"] == Decimal("4000.00")       # NHT employee
    assert result["employer_pension"] == Decimal("6000.00")       # NHT employer
    assert result["ni_employee"] == Decimal("4365.00")            # Education Tax employee
    assert result["employer_ni"] == Decimal("6790.00")            # Education Tax employer
    assert result["tds"] == Decimal("8867.50")                    # PAYE
    assert result["employer_payroll_tax"] == Decimal("6000.00")   # HEART

    employee_total = result["social_security"] + result["employee_pension"] + result["ni_employee"] + result["tds"]
    assert employee_total == Decimal("23232.50")
    employer_total = (
        result["employer_social_security"] + result["employer_pension"] + result["employer_ni"] + result["employer_payroll_tax"]
    )
    assert employer_total == Decimal("24790.00")


def test_standard_strategy_end_to_end_net_pay_matches_fixture():
    result = StandardStrategy().calculate(_ctx(Decimal("200000")))
    assert result.net_pay == Decimal("176767.50")


def test_heart_not_applied_below_threshold():
    result = jamaica.calculate(_ctx(Decimal("14444")))
    assert result["employer_payroll_tax"] == Decimal("0")
