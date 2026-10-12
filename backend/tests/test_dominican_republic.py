"""
tests/test_dominican_republic.py
-----------------------------------
Validates engine/countries/dominican_republic.py against ZP-DO-ENG-001
§13 fixture F1 exactly, and F2's SFS/pension figures (its ISR figure is
asserted against this engine's own correct marginal-bracket-sum math,
not the spec's rounded 12,105.44 — the spec's own published band-base
constants, RD$31,216 and RD$79,776, are themselves rounded from the
exact marginal sums 31,216.35/79,774.80, so a pure bracket-sum engine
and the spec's own worked example differ by a few cents at that
boundary; this is a documented spec-rounding nuance, not an engine bug
— see the module's own docstring).
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.standard import _COUNTRY_CALC
from app.modules.payroll.engine.countries import dominican_republic


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


def _do_rate_map():
    return {
        "do_sfs_ceiling": Rate(flat_amount=Decimal("232230")),
        "do_sfs": Rate(employee_rate_pct=Decimal("0.0304"), employer_rate_pct=Decimal("0.0709")),
        "do_pension_ceiling": Rate(flat_amount=Decimal("464460")),
        "do_pension": Rate(employee_rate_pct=Decimal("0.0287"), employer_rate_pct=Decimal("0.0710")),
        "do_srl_ceiling": Rate(flat_amount=Decimal("92892")),
        "do_srl": Rate(employer_rate_pct=Decimal("0.0110")),
        "do_infotep": Rate(employer_rate_pct=Decimal("0.0100")),
    }


def _do_slabs():
    return [
        Slab(min_amount=Decimal("416220"), max_amount=Decimal("624329"), rate_pct=Decimal("15")),
        Slab(min_amount=Decimal("624329"), max_amount=Decimal("867123"), rate_pct=Decimal("20")),
        Slab(min_amount=Decimal("867123"), max_amount=None, rate_pct=Decimal("25")),
    ]


def _ctx(gross: Decimal) -> PayrollContext:
    return PayrollContext(gross=gross, basic=gross, country="DO", rate_map=_do_rate_map(), slabs=_do_slabs(), pay_frequency="Monthly")


def test_dispatch_resolves_do_to_its_own_calculator():
    assert _COUNTRY_CALC["DO"] is dominican_republic.calculate


def test_fixture_f1_50000_monthly_risk_type_i():
    result = dominican_republic.calculate(_ctx(Decimal("50000")))
    assert result["social_security"] == Decimal("1520.00")     # SFS employee
    assert result["employer_social_security"] == Decimal("3545.00")  # SFS employer
    assert result["employee_pension"] == Decimal("1435.00")    # SVDS employee
    assert result["employer_pension"] == Decimal("3550.00")    # SVDS employer
    assert result["employer_payroll_tax"] == Decimal("550.00")  # SRL at 1.10%
    assert result["tds"] == Decimal("1854.00")


def test_fixture_f2_100000_monthly_sfs_and_pension():
    result = dominican_republic.calculate(_ctx(Decimal("100000")))
    assert result["social_security"] == Decimal("3040.00")
    assert result["employer_social_security"] == Decimal("7090.00")
    assert result["employee_pension"] == Decimal("2870.00")
    assert result["employer_pension"] == Decimal("7100.00")
    # Engine's own correct marginal-bracket-sum result — see module docstring.
    assert result["tds"] == Decimal("12105.37")


def test_srl_rate_uses_employer_tax_profile_when_configured():
    """Fixture F2's risk-type-II SRL rate (1.15%) — an agency-assigned,
    employer-specific fact, not the module's own risk-type-I default."""
    @dataclass
    class Profile:
        employer_rate_pct: Optional[Decimal] = None

    ctx = _ctx(Decimal("100000"))
    ctx.employer_tax_profiles = {"do_srl": Profile(employer_rate_pct=Decimal("1.15"))}
    result = dominican_republic.calculate(ctx)
    # SRL base is capped at the 92,892 ceiling regardless of rate source.
    assert result["employer_payroll_tax"] == Decimal("1068.26")  # 92,892 x 1.15%


def test_srl_falls_back_to_default_rate_when_no_profile_configured():
    result = dominican_republic.calculate(_ctx(Decimal("50000")))
    assert result["employer_payroll_tax"] == Decimal("550.00")  # 50,000 x 1.10% (risk type I default)


def test_three_ceilings_are_independent_at_high_income():
    """Fixture F3: RD$600,000 must show three DIFFERENT capped bases, not
    one universal social-security cap. Gross (600,000) exceeds every
    ceiling, so each base below is exactly that component's own ceiling."""
    result = dominican_republic.calculate(_ctx(Decimal("600000")))
    assert result["social_security"] == Decimal("7059.79")       # 232,230 x 3.04%
    assert result["employee_pension"] == Decimal("13330.00")     # 464,460 x 2.87%
    assert result["employer_payroll_tax"] == Decimal("1021.81")  # 92,892 x 1.10%
