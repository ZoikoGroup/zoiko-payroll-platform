"""
tests/test_puerto_rico.py
---------------------------
Validates engine/countries/puerto_rico.py against ZP-PR-ENG-001 §13
fixtures F1 (ordinary month), F2 (Social Security cap crossing), F3
(Additional Medicare threshold crossing), F4 (SINOT cap) — and the
"never fabricate a missing DTRH unemployment rate" contract (PR-018).
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.standard import _COUNTRY_CALC
from app.modules.payroll.engine.countries import puerto_rico


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
    filing_status: Optional[str] = None
    formula_expression: Optional[str] = None


def _pr_slabs():
    return [
        Slab(Decimal("0"), Decimal("9000"), Decimal("0")),
        Slab(Decimal("9000"), Decimal("25000"), Decimal("7")),
        Slab(Decimal("25000"), Decimal("41500"), Decimal("14")),
        Slab(Decimal("41500"), Decimal("61500"), Decimal("25")),
        Slab(Decimal("61500"), None, Decimal("33")),
    ]


def _pr_rate_map(unemployment_rate=None, cfse_rate=None):
    rate_map = {
        "pr_personal_exemption": Rate(flat_amount=Decimal("3500")),
        "pr_ss": Rate(employee_rate_pct=Decimal("0.062"), employer_rate_pct=Decimal("0.062")),
        "pr_ss_wage_base": Rate(flat_amount=Decimal("184500")),
        "pr_medicare": Rate(employee_rate_pct=Decimal("0.0145"), employer_rate_pct=Decimal("0.0145")),
        "pr_additional_medicare": Rate(employee_rate_pct=Decimal("0.009")),
        "pr_additional_medicare_threshold": Rate(flat_amount=Decimal("200000")),
        "pr_futa": Rate(employer_rate_pct=Decimal("0.06")),
        "pr_futa_wage_base": Rate(flat_amount=Decimal("7000")),
        "pr_unemployment_wage_base": Rate(flat_amount=Decimal("7000")),
        "pr_sinot": Rate(employee_rate_pct=Decimal("0.003"), employer_rate_pct=Decimal("0.003")),
        "pr_sinot_wage_base": Rate(flat_amount=Decimal("9000")),
    }
    if unemployment_rate is not None:
        rate_map["pr_unemployment"] = Rate(employer_rate_pct=unemployment_rate)
    if cfse_rate is not None:
        rate_map["pr_cfse"] = Rate(employer_rate_pct=cfse_rate)
    return rate_map


def _ctx(gross, pay_frequency="Monthly", unemployment_rate=None, cfse_rate=None, **ytd_kwargs) -> PayrollContext:
    return PayrollContext(
        gross=Decimal(gross), basic=Decimal(gross), country="PR",
        rate_map=_pr_rate_map(unemployment_rate, cfse_rate), slabs=_pr_slabs(),
        pay_frequency=pay_frequency, **ytd_kwargs,
    )


def test_dispatch_resolves_pr_to_its_own_calculator():
    assert _COUNTRY_CALC["PR"] is puerto_rico.calculate


def test_fixture_f1_ordinary_monthly_worker():
    """$4,000 monthly, no dependents/allowances, first month of SINOT
    year (no YTD wired yet -> dormant per-period-cap fallback, which is
    correct here since nobody is near any cap)."""
    result = puerto_rico.calculate(_ctx("4000", unemployment_rate=Decimal("0.03")))
    assert result["tds"] == Decimal("348.33")
    assert result["social_security"] == Decimal("248.00")
    assert result["employer_social_security"] == Decimal("248.00")
    assert result["medicare"] == Decimal("58.00")
    assert result["employer_medicare"] == Decimal("58.00")
    assert result["state_disability_insurance"] == Decimal("12.00")  # SINOT employee, 0.30%
    assert result["employer_state_program_contributions"] == Decimal("12.00")  # SINOT employer, 0.30%
    net_before_other = Decimal("4000") - result["tds"] - result["social_security"] - result["medicare"] - result["state_disability_insurance"]
    assert net_before_other == Decimal("3333.67")


def test_fixture_f2_social_security_cap_crossing():
    """YTD SS wages $180,000; current pay $20,000 -> only $4,500 subject
    to SS; Medicare applies to the full $20,000."""
    result = puerto_rico.calculate(_ctx(
        "20000", ytd_pr_ss_wages_before=Decimal("180000"),
    ))
    assert result["social_security"] == Decimal("279.00")
    assert result["employer_social_security"] == Decimal("279.00")
    assert result["ytd_pr_ss_wages_after"] == Decimal("184500")
    # Medicare (regular only here, YTD medicare not wired in this call) on the full $20,000.
    assert result["medicare"] == Decimal("290.00")


def test_fixture_f3_additional_medicare_crossing():
    """YTD Medicare wages $195,000; current pay $20,000 -> Additional
    Medicare 0.9% only on the $15,000 above the $200,000 threshold."""
    result = puerto_rico.calculate(_ctx(
        "20000", ytd_pr_medicare_wages_before=Decimal("195000"),
    ))
    regular_medicare = Decimal("20000") * Decimal("0.0145")
    additional_medicare = Decimal("135.00")
    assert result["medicare"] == regular_medicare + additional_medicare
    assert result["ytd_pr_medicare_wages_after"] == Decimal("215000")


def test_fixture_f4_sinot_cap():
    """YTD SINOT wages $8,500; current pay $1,000; 0.30/0.30 split ->
    only $500 subject to SINOT; employee $1.50, employer $1.50."""
    result = puerto_rico.calculate(_ctx(
        "1000", ytd_pr_sinot_wages_before=Decimal("8500"),
    ))
    assert result["state_disability_insurance"] == Decimal("1.50")
    assert result["employer_state_program_contributions"] == Decimal("1.50")
    assert result["ytd_pr_sinot_wages_after"] == Decimal("9000")


def test_missing_dtrh_unemployment_rate_never_fabricates_a_percentage():
    """PR-018: a missing employer-specific DTRH unemployment rate must
    compute as $0, never a guessed generic percentage, and must be
    surfaced via pr_unemployment_rate_configured=False rather than
    silently look like a genuine 0% statutory rate."""
    result = puerto_rico.calculate(_ctx("4000"))
    assert result["employer_sui"] == Decimal("0")
    assert result["pr_unemployment_rate_configured"] is False


def test_configured_dtrh_unemployment_rate_applies():
    result = puerto_rico.calculate(_ctx("4000", unemployment_rate=Decimal("0.03")))
    assert result["employer_sui"] == Decimal("120.00")  # 4000 * 3%
    assert result["pr_unemployment_rate_configured"] is True


def test_futa_equivalent_gross_rate_under_wage_base():
    """Not-wired fallback treats YTD as $0 (see _capped_wage_base's own
    docstring) -- the full $4,000 is taxable since it's under the $7,000
    annual wage base."""
    result = puerto_rico.calculate(_ctx("4000"))
    assert result["employer_futa"] == Decimal("240.00")  # 4000 * 6%


def test_futa_equivalent_caps_a_single_period_above_the_wage_base():
    result = puerto_rico.calculate(_ctx("10000"))
    assert result["employer_futa"] == Decimal("420.00")  # 7000 * 6% (capped)


def test_missing_cfse_rate_never_fabricates_a_percentage():
    """PR-021: a missing employer-specific CFSE policy rate must compute
    as $0, never a guessed universal percentage."""
    result = puerto_rico.calculate(_ctx("4000"))
    assert result["au_workers_compensation_premium"] == Decimal("0")
    assert result["pr_cfse_rate_configured"] is False


def test_configured_cfse_rate_applies_as_an_estimate():
    result = puerto_rico.calculate(_ctx("4000", cfse_rate=Decimal("0.02")))
    assert result["au_workers_compensation_premium"] == Decimal("80.00")  # 4000 * 2%
    assert result["pr_cfse_rate_configured"] is True


def test_fixture_f5_christmas_bonus_post_2017_large_employer():
    result = puerto_rico.calculate_pr_christmas_bonus(
        hired_before_2017=False, employer_size_over_threshold=True,
        qualifying_hours=Decimal("1600"), bonus_year_wages=Decimal("40000"),
    )
    assert result["eligible"] is True
    assert result["bonus_amount"] == Decimal("600.00")  # 2% of 40,000 = 800, capped at 600


def test_fixture_f6_christmas_bonus_first_year():
    result = puerto_rico.calculate_pr_christmas_bonus(
        hired_before_2017=False, employer_size_over_threshold=True,
        qualifying_hours=Decimal("1600"), bonus_year_wages=Decimal("40000"), is_first_year=True,
    )
    assert result["bonus_amount"] == Decimal("300.00")  # 600 capped, then 50% first-year rule


def test_christmas_bonus_ineligible_under_hours_threshold():
    result = puerto_rico.calculate_pr_christmas_bonus(
        hired_before_2017=False, employer_size_over_threshold=True,
        qualifying_hours=Decimal("1000"), bonus_year_wages=Decimal("40000"),
    )
    assert result["eligible"] is False
    assert result["bonus_amount"] == Decimal("0.00")


def test_christmas_bonus_pre_2017_large_employer():
    """6% of wages up to $10,000 -> exactly $600 for a $10,000+ earner."""
    result = puerto_rico.calculate_pr_christmas_bonus(
        hired_before_2017=True, employer_size_over_threshold=True,
        qualifying_hours=Decimal("700"), bonus_year_wages=Decimal("15000"),
    )
    assert result["bonus_amount"] == Decimal("600.00")


def test_fixture_f7_tipped_minimum_wage():
    result = puerto_rico.calculate_pr_tipped_minimum_wage(hours=Decimal("80"), tips_received=Decimal("500"))
    assert result["cash_wage"] == Decimal("170.40")
    assert result["total_received"] == Decimal("670.40")
    assert result["minimum_required"] == Decimal("840.00")
    assert result["make_up_required"] == Decimal("169.60")


def test_tipped_minimum_wage_no_make_up_needed_when_tips_cover_it():
    result = puerto_rico.calculate_pr_tipped_minimum_wage(hours=Decimal("80"), tips_received=Decimal("1000"))
    assert result["make_up_required"] == Decimal("0.00")


def test_fixture_f8_vacation_accrual_post_2017_year_six():
    days = puerto_rico.calculate_pr_vacation_accrual(
        hired_before_2017=False, years_of_service=Decimal("6"), qualifying_small_employer=False,
        qualifying_hours_in_month=Decimal("132"),
    )
    assert days == Decimal("1")


def test_vacation_accrual_below_130_hours_is_zero():
    days = puerto_rico.calculate_pr_vacation_accrual(
        hired_before_2017=False, years_of_service=Decimal("6"), qualifying_small_employer=False,
        qualifying_hours_in_month=Decimal("100"),
    )
    assert days == Decimal("0")


def test_vacation_accrual_pre_2017_flat_rate():
    days = puerto_rico.calculate_pr_vacation_accrual(
        hired_before_2017=True, years_of_service=Decimal("20"), qualifying_small_employer=False,
        qualifying_hours_in_month=Decimal("130"),
    )
    assert days == Decimal("1.25")


def test_certificate_personal_exemption_overrides_the_default():
    """PR-005/PR-006: a certificate on file overrides the engine default
    entirely, not blended with it."""
    ctx = _ctx("4000", pr_certificate_personal_exemption=Decimal("6000"))
    result = puerto_rico.calculate(ctx)
    # annual_gross 48,000 - 6,000 exemption = 42,000 taxable.
    # 0-9,000: 0%; 9,000-25,000: 7% -> 1,120; 25,000-41,500: 14% -> 2,310;
    # 41,500-42,000: 25% -> 125. Total 3,555.00 / 12 = 296.25.
    assert result["tds"] == Decimal("296.25")


def test_certificate_dependents_and_deduction_allowance_reduce_taxable_income():
    ctx_no_cert = _ctx("4000")
    ctx_with_cert = _ctx(
        "4000", pr_certificate_personal_exemption=Decimal("3500"),
        pr_certificate_dependents_count=2, pr_certificate_dependent_exemption_per_dependent=Decimal("1000"),
        pr_certificate_deduction_allowance=Decimal("500"),
    )
    result_no_cert = puerto_rico.calculate(ctx_no_cert)
    result_with_cert = puerto_rico.calculate(ctx_with_cert)
    # $2,500 more total exemption -> strictly less tax withheld.
    assert result_with_cert["tds"] < result_no_cert["tds"]


def test_certificate_additional_withholding_is_added_on_top():
    ctx = _ctx("4000", pr_certificate_additional_withholding=Decimal("25"))
    result = puerto_rico.calculate(ctx)
    baseline = puerto_rico.calculate(_ctx("4000"))
    assert result["tds"] == baseline["tds"] + Decimal("25")


def test_certificate_msrra_election_suppresses_pr_withholding():
    ctx = _ctx("4000", pr_certificate_msrra_election=True)
    result = puerto_rico.calculate(ctx)
    assert result["tds"] == Decimal("0")


def test_no_certificate_falls_back_to_engine_default_exemption():
    """Same as F1 — the default-treatment contract (PR-006) must hold
    when pr_certificate_personal_exemption is None."""
    result = puerto_rico.calculate(_ctx("4000"))
    assert result["tds"] == Decimal("348.33")


def test_overtime_daily_only_regular_pool_exactly_reaches_forty():
    """5 days x 9 hours = 45 total -> 5 hours daily OT (1/day), 40 regular,
    0 weekly OT (the regular pool exactly reaches 40, never exceeds it)."""
    result = puerto_rico.calculate_pr_overtime([Decimal("9")] * 5, Decimal("10"))
    assert result["daily_overtime_hours"] == Decimal("5")
    assert result["weekly_overtime_hours"] == Decimal("0")
    assert result["regular_hours"] == Decimal("40")
    assert result["total_overtime_hours"] == Decimal("5")
    assert result["regular_pay"] == Decimal("400.00")
    assert result["overtime_pay"] == Decimal("75.00")  # 5 * 10 * 1.5


def test_overtime_weekly_only_no_single_day_over_eight():
    """6 days x 7 hours = 42 total, no single day over 8 -> 0 daily OT,
    40 regular + 2 weekly OT."""
    result = puerto_rico.calculate_pr_overtime([Decimal("7")] * 6, Decimal("10"))
    assert result["daily_overtime_hours"] == Decimal("0")
    assert result["weekly_overtime_hours"] == Decimal("2")
    assert result["regular_hours"] == Decimal("40")
    assert result["total_overtime_hours"] == Decimal("2")


def test_overtime_daily_overtime_never_double_counted_into_weekly():
    """4 days x 11 hours = 44 total -> 12 hours daily OT, regular pool
    only 32 (never reaches 40) -> 0 weekly OT, even though total hours
    (44) exceed 40."""
    result = puerto_rico.calculate_pr_overtime([Decimal("11")] * 4, Decimal("10"))
    assert result["daily_overtime_hours"] == Decimal("12")
    assert result["weekly_overtime_hours"] == Decimal("0")
    assert result["regular_hours"] == Decimal("32")
    assert result["total_overtime_hours"] == Decimal("12")


def test_overtime_ordinary_week_under_both_thresholds():
    result = puerto_rico.calculate_pr_overtime([Decimal("8")] * 5, Decimal("10"))
    assert result["daily_overtime_hours"] == Decimal("0")
    assert result["weekly_overtime_hours"] == Decimal("0")
    assert result["regular_hours"] == Decimal("40")
    assert result["overtime_pay"] == Decimal("0.00")
    assert result["total_pay"] == Decimal("400.00")


def test_vacation_accrual_small_employer_exception():
    days = puerto_rico.calculate_pr_vacation_accrual(
        hired_before_2017=False, years_of_service=Decimal("6"), qualifying_small_employer=True,
        qualifying_hours_in_month=Decimal("132"),
    )
    assert days == Decimal("0.5")


def test_sick_leave_accrual_one_day_at_threshold():
    assert puerto_rico.calculate_pr_sick_leave_accrual(Decimal("130")) == Decimal("1")
    assert puerto_rico.calculate_pr_sick_leave_accrual(Decimal("200")) == Decimal("1")


def test_sick_leave_accrual_zero_below_threshold():
    assert puerto_rico.calculate_pr_sick_leave_accrual(Decimal("129.99")) == Decimal("0")


def test_sick_leave_accrual_does_not_vary_by_hire_date():
    """Unlike vacation, PR-029: sick leave's minimum does not vary by hire
    date/service — calculate_pr_sick_leave_accrual takes no cohort
    parameters at all, by design."""
    assert puerto_rico.calculate_pr_sick_leave_accrual(Decimal("130")) == Decimal("1")
