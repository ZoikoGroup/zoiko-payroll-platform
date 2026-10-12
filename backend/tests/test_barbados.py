"""
tests/test_barbados.py
------------------------
Validates engine/countries/barbados.py against ZP-BB-ENG-001 §12 fixtures
F1/F2, and confirms the dispatch/DB-driven wiring: BB resolves through
_COUNTRY_CALC (never falls through to the generic no-contributions
calculator) and every rate/threshold comes from rate_map/slabs, not a
Python constant, once configured.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.standard import StandardStrategy, _COUNTRY_CALC
from app.modules.payroll.engine.countries import barbados


@dataclass
class Rate:
    employee_rate_pct: Optional[Decimal] = None
    employer_rate_pct: Optional[Decimal] = None
    flat_amount: Optional[Decimal] = None
    text_value: Optional[str] = None


@dataclass
class Slab:
    min_amount: Decimal
    max_amount: Optional[Decimal]
    rate_pct: Decimal
    rule_type: str = "MARGINAL_RATE"
    formula_expression: Optional[str] = None
    filing_status: Optional[str] = None


def _bb_rate_map():
    return {
        "bb_personal_allowance": Rate(flat_amount=Decimal("25000")),
        "bb_nis": Rate(employee_rate_pct=Decimal("0.1100"), employer_rate_pct=Decimal("0.1275")),
        "bb_nis_ceiling_monthly": Rate(flat_amount=Decimal("5360")),
        "bb_nis_ceiling_weekly": Rate(flat_amount=Decimal("1238")),
        "bb_resilience_regeneration": Rate(employee_rate_pct=Decimal("0.0025"), employer_rate_pct=Decimal("0.0025")),
    }


def _bb_slabs():
    return [
        Slab(min_amount=Decimal("0"), max_amount=Decimal("50000"), rate_pct=Decimal("11.5")),
        Slab(min_amount=Decimal("50000"), max_amount=None, rate_pct=Decimal("27.5")),
    ]


def _ctx(gross: Decimal) -> PayrollContext:
    return PayrollContext(
        gross=gross, basic=gross, country="BB", rate_map=_bb_rate_map(), slabs=_bb_slabs(),
        pay_frequency="Monthly",
    )


def test_dispatch_resolves_barbados_to_its_own_calculator():
    assert _COUNTRY_CALC["BB"] is barbados.calculate


def test_fixture_f1_ordinary_below_ceiling():
    result = barbados.calculate(_ctx(Decimal("5000")))
    assert result["tds"] == Decimal("335.42")
    assert result["social_security"] == Decimal("550.00")
    assert result["employer_social_security"] == Decimal("637.50")
    assert result["employee_pension"] == Decimal("12.50")   # R&R employee
    assert result["employer_pension"] == Decimal("12.50")   # R&R employer
    net = gross_minus_deductions = Decimal("5000") - result["tds"] - result["social_security"] - result["employee_pension"]
    assert net == Decimal("4102.08")


def test_fixture_f2_above_nis_ceiling():
    result = barbados.calculate(_ctx(Decimal("10000")))
    assert result["tds"] == Decimal("1510.42")
    assert result["social_security"] == Decimal("589.60")
    assert result["employer_social_security"] == Decimal("683.40")
    assert result["employee_pension"] == Decimal("25.00")
    assert result["employer_pension"] == Decimal("25.00")
    net = Decimal("10000") - result["tds"] - result["social_security"] - result["employee_pension"]
    assert net == Decimal("7874.98")


def test_standard_strategy_end_to_end_matches_direct_calculator():
    ctx = _ctx(Decimal("5000"))
    result = StandardStrategy().calculate(ctx)
    assert result.tds == Decimal("335.42")
    assert result.social_security == Decimal("550.00")
    # net_pay = gross - attendance(0) - tds - social_security - employee_pension (R&R)
    assert result.net_pay == Decimal("5000") - Decimal("335.42") - Decimal("550.00") - Decimal("12.50")


def test_rate_map_override_is_honoured_over_hardcoded_fallback():
    """Changing the configured NIS rate must change the result — proves
    this is genuinely DB-driven, not a hardcoded constant."""
    rate_map = _bb_rate_map()
    rate_map["bb_nis"] = Rate(employee_rate_pct=Decimal("0.20"), employer_rate_pct=Decimal("0.20"))
    ctx = PayrollContext(gross=Decimal("5000"), basic=Decimal("5000"), country="BB", rate_map=rate_map, slabs=_bb_slabs(), pay_frequency="Monthly")
    result = barbados.calculate(ctx)
    assert result["social_security"] == Decimal("1000.00")  # 20% of 5000, not 11%
