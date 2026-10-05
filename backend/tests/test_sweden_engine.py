"""engine/countries/sweden.py (ZP-SE-ENG-001 §3/§5/§6) — pure engine tests,
no database. Tax-table figures here are ILLUSTRATIVE band values (the real
Skatteverket tables are not yet entered); they exercise the lookup
mechanics, not statutory amounts."""
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.countries import sweden as se
from app.modules.payroll.engine.standard import StandardStrategy


def _rate(key, employer=None, employee=None, flat=None, ef=None, et=None):
    return SimpleNamespace(component_key=key, employer_rate_pct=employer, employee_rate_pct=employee,
                           flat_amount=flat, effective_from=ef, effective_to=et)


RATES = {
    "se_er_age_pension": _rate("se_er_age_pension", employer=D("10.21")),
    "se_er_health_insurance": _rate("se_er_health_insurance", employer=D("3.55")),
    "se_er_parental_insurance": _rate("se_er_parental_insurance", employer=D("2.60")),
    "se_er_labour_market": _rate("se_er_labour_market", employer=D("2.64")),
    "se_er_work_injury": _rate("se_er_work_injury", employer=D("0.20")),
    "se_er_survivor_pension": _rate("se_er_survivor_pension", employer=D("0.60")),
    "se_er_general_payroll_tax": _rate("se_er_general_payroll_tax", employer=D("11.62")),
    "se_youth_reduced": _rate("se_youth_reduced", employer=D("20.81"), ef=date(2026, 4, 1), et=date(2027, 9, 30)),
    "se_youth_monthly_threshold": _rate("se_youth_monthly_threshold", flat=D("25000")),
    "se_sink": _rate("se_sink", employee=D("22.5")),
    "se_supplementary_rate": _rate("se_supplementary_rate", employee=D("30")),
    "se_slp": _rate("se_slp", employer=D("24.26")),
    "se_older_cohort_max_birth_year": _rate("se_older_cohort_max_birth_year", flat=D("1958")),
    "se_zero_cohort_max_birth_year": _rate("se_zero_cohort_max_birth_year", flat=D("1937")),
}


def _band(rule, lo, hi, basis, table="32", column="1", amount=None, pct=D("0")):
    return SimpleNamespace(rule_type=rule, tax_table_number=table, tax_column=column, assessment_basis=basis,
                           min_amount=lo, max_amount=hi, flat_amount=amount, rate_pct=pct)


SLABS = [
    _band(se.SE_TAX_TABLE_RULE, D("0"), D("80000"), "AMOUNT", amount=D("7500")),
    _band(se.SE_TAX_TABLE_RULE, D("80000"), None, "PERCENT", pct=D("50")),
    _band(se.SE_ONE_TIME_PAYMENT_RULE, D("0"), D("700000"), "PERCENT", table=None, pct=D("32")),
    _band(se.SE_ONE_TIME_PAYMENT_RULE, D("700000"), None, "PERCENT", table=None, pct=D("52")),
]


def _profile(**kw):
    base = dict(se_tax_status="A_TAX", se_income_role="MAIN_INCOME", se_tax_table="32", se_tax_column="1",
                se_cba_status="NONE")
    base.update(kw)
    return SimpleNamespace(**base)


def _calc(profile=None, dob=date(1990, 3, 3), gross=D("50000"), pay_date=date(2026, 5, 31), slabs=None,
          rates=None, frequency="Monthly", **kw):
    ctx = PayrollContext(country="SE", gross=gross, basic=gross, pay_frequency=frequency, pay_date=pay_date,
                         date_of_birth=dob, rate_map=RATES if rates is None else rates,
                         slabs=SLABS if slabs is None else slabs,
                         sweden_statutory_profile=_profile() if profile is None else profile,
                         se_organization_id=1, **kw)
    return StandardStrategy().calculate(ctx)


def test_standard_cohort_and_monthly_amount_band():
    r = _calc()
    assert r.se_employer_contribution_cohort == "STANDARD"
    assert r.se_employer_contribution_rate == D("31.42")
    assert r.se_employer_contribution == D("15710.00")
    assert r.employer_social_security == r.se_employer_contribution
    assert (r.se_preliminary_tax, r.se_tax_strategy) == (D("7500.00"), "TAX_TABLE")
    assert r.net_pay == D("42500.00")


def test_components_are_traced_individually():
    r = _calc()
    assert {c["key"] for c in r.se_employer_contribution_components} == set(se.SE_ER_COMPONENT_KEYS)


def test_top_band_published_percentage():
    assert _calc(gross=D("100000")).se_preliminary_tax == D("50000.00")


def test_youth_split_and_accumulator():
    assert _calc(dob=date(2005, 6, 1), gross=D("30000")).se_employer_contribution == D("6773.50")
    r = _calc(dob=date(2005, 6, 1), gross=D("15000"), se_month_to_date_prior=D("15000"))
    assert r.se_employer_contribution == D("3652.00")   # 10,000 @ 20.81% + 5,000 @ 31.42%
    r = _calc(dob=date(2005, 6, 1), gross=D("10000"), se_month_to_date_prior=D("30000"))
    assert r.se_employer_contribution == D("3142.00")   # threshold already used: all at 31.42%


def test_youth_window_is_payment_date_keyed():
    r = _calc(dob=date(2005, 6, 1), pay_date=date(2026, 3, 31))
    assert r.se_employer_contribution_cohort == "STANDARD" and not r.se_youth_applied
    assert _calc(dob=date(2006, 6, 1), pay_date=date(2027, 10, 1)).se_employer_contribution_cohort == "STANDARD"


def test_youth_without_threshold_blocks():
    rates = {k: v for k, v in RATES.items() if k != "se_youth_monthly_threshold"}
    with pytest.raises(se.SwedenCalculationBlockedError) as exc:
        _calc(dob=date(2005, 6, 1), rates=rates)
    assert exc.value.key == "se_youth_monthly_threshold"


def test_older_and_zero_cohorts():
    assert _calc(dob=date(1950, 1, 1)).se_employer_contribution == D("5105.00")
    r = _calc(dob=date(1930, 1, 1))
    assert (r.se_employer_contribution, r.se_employer_contribution_cohort) == (D("0.00"), "ZERO")


def test_sink_requires_valid_status():
    r = _calc(profile=_profile(se_tax_status="SINK", se_sink_status="VALID", se_income_role=None))
    assert (r.se_preliminary_tax, r.se_tax_strategy) == (D("11250.00"), "SINK")
    with pytest.raises(se.SwedenCalculationBlockedError) as exc:
        _calc(profile=_profile(se_tax_status="SINK", se_sink_status="EXPIRED"))
    assert exc.value.key == "se_sink_status"


def test_supplementary_income_is_never_the_table():
    r = _calc(profile=_profile(se_income_role="SUPPLEMENTARY_INCOME"))
    assert (r.se_preliminary_tax, r.se_tax_strategy) == (D("15000.00"), "SUPPLEMENTARY")


def test_one_time_payment_uses_annual_income_band_percentage():
    r = _calc(profile=_profile(se_income_role="ONE_TIME_PAYMENT", se_annual_income=D("600000")), gross=D("20000"))
    assert (r.se_preliminary_tax, r.se_tax_strategy) == (D("6400.00"), "ONE_TIME")
    with pytest.raises(se.SwedenCalculationBlockedError) as exc:
        _calc(profile=_profile(se_income_role="ONE_TIME_PAYMENT"))
    assert exc.value.key == "se_annual_income"


def test_decision_override_wins_within_its_dates():
    decision = dict(se_decision_override=True, se_decision_monthly_withholding=D("4000"),
                    se_decision_effective_from=date(2026, 1, 1), se_decision_effective_to=date(2026, 12, 31))
    r = _calc(profile=_profile(**decision))
    assert (r.se_preliminary_tax, r.se_tax_strategy) == (D("4000.00"), "DECISION_AMOUNT")
    r = _calc(profile=_profile(**decision), pay_date=date(2027, 1, 31))
    assert r.se_tax_strategy == "TAX_TABLE"
    with pytest.raises(se.SwedenCalculationBlockedError):
        _calc(profile=_profile(se_decision_override=True))


def test_cash_limit_withholds_nothing_from_benefit_only_pay():
    r = _calc(gross=D("10000"), se_cash_pay=D("0"))
    assert (r.se_preliminary_tax, r.se_tax_strategy) == (D("0"), "CASH_LIMIT")
    assert r.se_employer_contribution == D("3142.00")   # employer contribution still due on the benefit


@pytest.mark.parametrize("profile,slabs,key", [
    (None, None, "worker_tax_profile"),
    (_profile(se_tax_table="40"), None, "se_tax_table"),
    (_profile(se_tax_column=None), None, "se_tax_table"),
    (_profile(se_tax_status="OTHER"), None, "se_tax_status"),
    (_profile(), [_band(se.SE_TAX_TABLE_RULE, D("0"), None, None)], "se_tax_table"),
    (_profile(se_income_role="ONE_TIME_PAYMENT", se_annual_income=D("100")),
     [_band(se.SE_ONE_TIME_PAYMENT_RULE, D("0"), None, None, table=None)], "se_one_time_payment_table"),
])
def test_fail_closed_cases(profile, slabs, key):
    ctx_profile = profile if profile is not None else None
    with pytest.raises(se.SwedenCalculationBlockedError) as exc:
        ctx = PayrollContext(country="SE", gross=D("50000"), basic=D("50000"), pay_frequency="Monthly",
                             pay_date=date(2026, 5, 31), date_of_birth=date(1990, 1, 1), rate_map=RATES,
                             slabs=SLABS if slabs is None else slabs, sweden_statutory_profile=ctx_profile,
                             se_organization_id=1)
        StandardStrategy().calculate(ctx)
    assert exc.value.key == key


def test_overlapping_bands_block():
    slabs = [_band(se.SE_TAX_TABLE_RULE, D("0"), D("60000"), "AMOUNT", amount=D("1")),
             _band(se.SE_TAX_TABLE_RULE, D("40000"), None, "AMOUNT", amount=D("2"))]
    with pytest.raises(se.SwedenCalculationBlockedError):
        _calc(slabs=slabs)


def test_monthly_table_refuses_other_pay_frequencies():
    with pytest.raises(se.SwedenCalculationBlockedError) as exc:
        _calc(frequency="Weekly")
    assert exc.value.key == "pay_frequency"


def test_missing_birth_date_and_pay_date_block():
    with pytest.raises(se.SwedenCalculationBlockedError):
        _calc(dob=None)
    with pytest.raises(se.SwedenCalculationBlockedError):
        _calc(pay_date=None)


def test_slp_is_computed_from_the_pension_cost_ledger_only():
    assert _calc().se_slp == D("0")
    assert _calc(se_pension_cost_base=D("100000")).se_slp == D("24260.00")


def test_occupational_pension_only_from_a_configured_plan_share():
    r = _calc(profile=_profile(se_employee_pension_share=D("2"), se_employer_pension_share=D("4.5")))
    assert (r.se_occupational_pension_employee, r.se_occupational_pension_employer) == (D("1000.00"), D("2250.00"))
    assert _calc().se_occupational_pension_employee == D("0")
