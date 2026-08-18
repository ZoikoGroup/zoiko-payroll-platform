"""
tests/test_engine_standard.py
------------------------------
Boundary/regression coverage for engine/standard.py's per-country
calculators (Phase 29): below/at/above threshold, bracket boundaries,
zero/high income, and the rate_map-parameter-with-fallback mechanism
Milestone 3 introduced (Super Admin can override a government constant;
absent that override, behavior is unchanged from the hardcoded default).
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

import pytest

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.standard import StandardStrategy, evaluate_tax_formula


@dataclass
class Rate:
    """Minimal stand-in for a ContributionRate/TaxSlab row — only the
    attributes the engine actually reads."""
    component_key: str = ""
    employee_rate_pct: Optional[Decimal] = None
    employer_rate_pct: Optional[Decimal] = None
    flat_amount: Optional[Decimal] = None


@dataclass
class Slab:
    min_amount: Decimal = Decimal("0")
    max_amount: Optional[Decimal] = None
    rate_pct: Decimal = Decimal("0")
    rule_type: str = "MARGINAL_RATE"
    formula_expression: Optional[str] = None


STRATEGY = StandardStrategy()


def calc(country, gross, rate_map=None, slabs=None, basic=None):
    ctx = PayrollContext(
        gross=Decimal(gross), basic=Decimal(basic if basic is not None else gross),
        country=country, rate_map=rate_map or {}, slabs=slabs or [],
    )
    return STRATEGY.calculate(ctx)


# ── India ────────────────────────────────────────────────────────────────

IN_RATES = {
    "pf": Rate("pf", Decimal("12.00"), Decimal("12.00")),
    "esi": Rate("esi", Decimal("0.75"), Decimal("3.25")),
    "pt": Rate("pt", flat_amount=Decimal("200")),
}
IN_SLABS = [
    Slab(Decimal("0"), Decimal("400000"), Decimal("0")),
    Slab(Decimal("400000"), Decimal("800000"), Decimal("5")),
    Slab(Decimal("800000"), None, Decimal("10")),
]


def test_india_esi_applies_below_ceiling():
    result = calc("IN", 20000, IN_RATES, IN_SLABS)
    assert result.employee_esi > 0


def test_india_esi_not_applicable_above_ceiling():
    result = calc("IN", 21001, IN_RATES, IN_SLABS)
    assert result.employee_esi == 0


def test_india_esi_ceiling_override_via_rate_map():
    rates = dict(IN_RATES, esi_wage_ceiling=Rate(flat_amount=Decimal("30000")))
    result = calc("IN", 25000, rates, IN_SLABS)
    assert result.employee_esi > 0  # would be 0 under the default 21000 ceiling


def test_india_zero_income():
    result = calc("IN", 0, IN_RATES, IN_SLABS)
    assert result.net_pay == 0
    assert result.tds == 0


def test_india_pt_is_flat():
    result = calc("IN", 100000, IN_RATES, IN_SLABS)
    assert result.professional_tax == Decimal("200")


def test_india_87a_rebate_zeroes_tax_at_low_income():
    result = calc("IN", 50000, IN_RATES, IN_SLABS)  # well under standard deduction + rebate limit
    assert result.tds == 0


def test_india_high_income_taxed():
    result = calc("IN", 300000, IN_RATES, IN_SLABS)
    assert result.tds > 0


# ── United States ────────────────────────────────────────────────────────

US_RATES = {
    "social-security": Rate("social-security", Decimal("6.20"), Decimal("6.20")),
    "medicare": Rate("medicare", Decimal("1.45"), Decimal("1.45")),
}
US_SLABS = [
    Slab(Decimal("0"), Decimal("11925"), Decimal("10")),
    Slab(Decimal("11925"), Decimal("48475"), Decimal("12")),
    Slab(Decimal("48475"), None, Decimal("22")),
]


def test_us_social_security_below_wage_base():
    result = calc("US", 5000, US_RATES, US_SLABS)  # $60k/yr, under $176,100 base
    assert result.social_security == pytest.approx(Decimal("310.00"), abs=Decimal("0.01"))


def test_us_social_security_capped_at_wage_base():
    result = calc("US", 30000, US_RATES, US_SLABS)  # $360k/yr, well above the wage base
    annual_ss = result.social_security * 12
    assert annual_ss < Decimal("360000") * Decimal("0.062")  # capped, not linear


def test_us_medicare_additional_above_threshold():
    below = calc("US", Decimal("16000"), US_RATES, US_SLABS)   # $192k/yr — under $200k
    above = calc("US", Decimal("18000"), US_RATES, US_SLABS)   # $216k/yr — over $200k
    below_rate = below.medicare / (Decimal("16000"))
    above_rate = above.medicare / (Decimal("18000"))
    assert above_rate > below_rate  # additional 0.9% kicked in


def test_us_wage_base_override_via_rate_map():
    rates = dict(US_RATES, ss_wage_base=Rate(flat_amount=Decimal("50000")))
    result = calc("US", 10000, rates, US_SLABS)  # $120k/yr, over the overridden $50k base
    default_result = calc("US", 10000, US_RATES, US_SLABS)
    assert result.social_security < default_result.social_security


def test_us_zero_income():
    result = calc("US", 0, US_RATES, US_SLABS)
    assert result.net_pay == 0


# ── United Kingdom ───────────────────────────────────────────────────────

UK_RATES = {
    "national-insurance": Rate("national-insurance", Decimal("8.00"), Decimal("13.80")),
    "employer-pension": Rate("employer-pension", employer_rate_pct=Decimal("3.00")),
}
UK_SLABS = [
    Slab(Decimal("0"), Decimal("12570"), Decimal("0")),
    Slab(Decimal("12570"), Decimal("50270"), Decimal("20")),
    Slab(Decimal("50270"), None, Decimal("40")),
]


def test_uk_ni_below_primary_threshold():
    result = calc("UK", 1000, UK_RATES, UK_SLABS)  # £12k/yr, under £12,570 threshold
    assert result.ni_employee == 0


def test_uk_ni_above_primary_threshold():
    result = calc("UK", 2000, UK_RATES, UK_SLABS)  # £24k/yr, over the threshold
    assert result.ni_employee > 0


def test_uk_personal_allowance_taper_reduces_allowance():
    normal = calc("UK", Decimal("6000"), UK_RATES, UK_SLABS)      # £72k/yr, no taper
    tapered = calc("UK", Decimal("10000"), UK_RATES, UK_SLABS)    # £120k/yr, tapered
    normal_rate = normal.tds / Decimal("6000")
    tapered_rate = tapered.tds / Decimal("10000")
    assert tapered_rate > normal_rate


def test_uk_zero_income():
    result = calc("UK", 0, UK_RATES, UK_SLABS)
    assert result.net_pay == 0


# ── Australia / Germany / Canada ─────────────────────────────────────────

def test_australia_super_and_medicare_levy():
    rates = {
        "super": Rate("super", employer_rate_pct=Decimal("11.50")),
        "medicare-levy": Rate("medicare-levy", employee_rate_pct=Decimal("2.00")),
    }
    slabs = [Slab(Decimal("0"), Decimal("18200"), Decimal("0")), Slab(Decimal("18200"), None, Decimal("16"))]
    result = calc("AU", 5000, rates, slabs)
    assert result.employer_pension > 0
    assert result.medicare > 0


def test_germany_pension_and_social_insurance():
    rates = {
        "pension": Rate("pension", Decimal("9.30"), Decimal("9.30")),
        "social-insurance": Rate("social-insurance", Decimal("9.00"), Decimal("9.00")),
    }
    slabs = [Slab(Decimal("0"), Decimal("11000"), Decimal("0")), Slab(Decimal("11000"), None, Decimal("14"))]
    result = calc("DE", 4000, rates, slabs)
    assert result.employee_pf > 0
    assert result.employee_esi > 0


def test_canada_cpp_and_ei():
    rates = {
        "cpp": Rate("cpp", Decimal("5.95"), Decimal("5.95")),
        "ei": Rate("ei", Decimal("1.66"), Decimal("2.32")),
    }
    slabs = [Slab(Decimal("0"), Decimal("55000"), Decimal("15")), Slab(Decimal("55000"), None, Decimal("20.5"))]
    result = calc("CA", 4000, rates, slabs)
    assert result.social_security > 0
    assert result.employee_esi > 0


# ── Australia / Germany / Canada named scalar parameters ────────────────
# Fallback-default thresholds (no override rows): AU medicare_levy_low_
# income_threshold=24276, mls_threshold=97000/mls_rate=1.0%,
# super_max_contribution_base=260280; DE contribution_ceiling=96600;
# CA cpp_ympe=71300/cpp_basic_exemption=3500/ei_mie=65700. Flat 10% slab
# used throughout so income-tax math never obscures the contribution
# assertions being tested.

_FLAT_10_SLAB = [Slab(Decimal("0"), None, Decimal("10"))]


def test_australia_medicare_levy_exempt_below_low_income_threshold():
    rates = {"medicare-levy": Rate("medicare-levy", employee_rate_pct=Decimal("2.00"))}
    result = calc("AU", 1500, rates, _FLAT_10_SLAB)  # annual 18,000 < 24,276 threshold
    assert result.medicare == 0


def test_australia_medicare_levy_applies_above_low_income_threshold():
    rates = {"medicare-levy": Rate("medicare-levy", employee_rate_pct=Decimal("2.00"))}
    result = calc("AU", 2100, rates, _FLAT_10_SLAB)  # annual 25,200 > 24,276 threshold
    assert result.medicare == Decimal("42.00")  # 2100 * 2%


def test_australia_medicare_levy_surcharge_above_mls_threshold():
    rates = {"medicare-levy": Rate("medicare-levy", employee_rate_pct=Decimal("2.00"))}
    result = calc("AU", 10000, rates, _FLAT_10_SLAB)  # annual 120,000 > 97,000 MLS threshold
    # base levy 10000*2% = 200.00, + MLS 1% of annual/12 = 100.00
    assert result.medicare == Decimal("300.00")


def test_australia_super_guarantee_capped_at_max_contribution_base():
    rates = {"super": Rate("super", employer_rate_pct=Decimal("11.50"))}
    result = calc("AU", 30000, rates, _FLAT_10_SLAB)  # annual 360,000 > 260,280 cap
    uncapped = Decimal("30000") * Decimal("11.50") / 100
    assert result.employer_pension < uncapped
    assert result.employer_pension == Decimal("2494.35")  # (260280 * 11.5% ) / 12


def test_germany_contributions_capped_at_contribution_ceiling():
    rates = {"pension": Rate("pension", employee_rate_pct=Decimal("9.30"), employer_rate_pct=Decimal("9.30"))}
    result = calc("DE", 10000, rates, _FLAT_10_SLAB)  # annual 120,000 > 96,600 ceiling
    uncapped = Decimal("10000") * Decimal("9.30") / 100
    assert result.employee_pf < uncapped
    assert result.employee_pf == Decimal("748.65")  # (96600 * 9.3%) / 12


def test_canada_cpp_exempts_basic_amount_and_caps_at_ympe_ei_caps_separately():
    rates = {
        "cpp": Rate("cpp", employee_rate_pct=Decimal("5.95"), employer_rate_pct=Decimal("5.95")),
        "ei": Rate("ei", employee_rate_pct=Decimal("1.66"), employer_rate_pct=Decimal("2.32")),
    }
    result = calc("CA", 7000, rates, _FLAT_10_SLAB)  # annual 84,000 > both YMPE (71,300) and MIE (65,700)
    # CPP pensionable = min(84000, 71300) - 3500 = 67800 -> (67800*5.95%)/12
    assert result.social_security == Decimal("336.18")
    # EI insurable = min(84000, 65700) = 65700 -> (65700*1.66%)/12 — capped
    # independently of CPP's own (lower) cap.
    assert result.employee_esi == Decimal("90.89")


def test_unknown_country_falls_back_to_generic():
    slabs = [Slab(Decimal("0"), None, Decimal("10"))]
    result = calc("ZZ", 1000, {}, slabs)
    assert result.tds > 0
    assert result.employee_pf == 0


# ── Formula-based tax rule (Germany-style continuous formula) ───────────

def test_formula_rule_overrides_bracket_loop():
    slabs = [Slab(rule_type="FORMULA", formula_expression="income * 0.2")]
    result = calc("DE", 10000, {}, slabs)
    # DE income tax now goes through _calculate_annual_tax_de, which
    # subtracts the Grundfreibetrag (11,784) before the formula runs, then
    # adds the Solidarity Surcharge (5.5%) since the resulting tax exceeds
    # the Soli threshold (18,130) — both use fallback defaults here since
    # no override rows were given (rate_map={}):
    #   taxable = 120000 - 11784 = 108216
    #   formula tax = 108216 * 0.2 = 21643.20
    #   + Soli (21643.20 > 18130 threshold, so +5.5%) = 22833.576
    #   tds = 22833.576 / 12 = 1902.80
    assert result.tds == pytest.approx(Decimal("1902.80"), abs=Decimal("0.01"))


def test_evaluate_tax_formula_supports_min_max_and_arithmetic():
    assert evaluate_tax_formula("min(income, 1000) * 0.1", Decimal("5000")) == Decimal("100")
    assert evaluate_tax_formula("max(income - 500, 0) * 0.1", Decimal("300")) == Decimal("0")


def test_evaluate_tax_formula_rejects_unsafe_expressions():
    with pytest.raises(Exception):
        evaluate_tax_formula("__import__('os').system('echo hi')", Decimal("1000"))
    with pytest.raises(Exception):
        evaluate_tax_formula("income.__class__", Decimal("1000"))
