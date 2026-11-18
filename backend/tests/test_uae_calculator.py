"""UAE calculator (ZP-AE-ENG-001) — spec fixtures F1–F7 and fail-closed cases.

All statutory values come from the seeded pack content; the test rate_map is
built from that same content with SimpleNamespace rows (no ORM, no database).
Synthetic figures only.
"""
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.payroll.engine.countries import uae_content as C
from app.modules.payroll.engine.jurisdictions.uae import errors as E
from app.modules.payroll.engine.jurisdictions.uae import gratuity as G
from app.modules.payroll.engine.jurisdictions.uae import overtime as O
from app.modules.payroll.engine.jurisdictions.uae import pension as PN


def rate_map(**changes):
    result = {}
    for key, _label, employee, employer, flat, text, row_from, _source in C.RATES:
        result[key] = SimpleNamespace(
            component_key=key,
            employee_rate_pct=Decimal(employee) if employee is not None else None,
            employer_rate_pct=Decimal(employer) if employer is not None else None,
            flat_amount=Decimal(flat) if flat is not None else None,
            text_value=text,
            effective_from=row_from,
        )
    for key, row in changes.items():
        if row is None:
            result.pop(key, None)
        else:
            result[key] = row
    return result


def rate(key, employee=None, employer=None, flat=None, effective_from=None):
    return SimpleNamespace(component_key=key,
                           employee_rate_pct=Decimal(employee) if employee is not None else None,
                           employer_rate_pct=Decimal(employer) if employer is not None else None,
                           flat_amount=Decimal(flat) if flat is not None else None,
                           effective_from=effective_from)


EXPAT = {"nationality_category": "EXPATRIATE", "eos_regime": "TRADITIONAL"}
LAW57 = {"nationality_category": "UAE_NATIONAL", "pension_scheme": "GPSSA_LAW_57_2023",
         "pension_contribution_salary": "15000", "government_support_eligible": "YES"}
ADPF_NEW = {"nationality_category": "UAE_NATIONAL", "pension_scheme": "ADPF_NEW_MEMBER",
            "pension_contribution_salary": "30000"}


def d(value):
    return Decimal(str(value))


# ── F1/F2: traditional gratuity ignores allowances and applies the cap ─────
def test_f1_three_years_uses_basic_wage_only():
    result = G.entitlement(d(3), d(8000), d(12000), rate_map())
    assert result["days"] == d(63)
    assert result["amount"] == d(16800)
    assert result["capped"] is False


def test_f2_seven_years_has_165_days_and_stays_below_the_cap():
    result = G.entitlement(d(7), d(10000), d(120000), rate_map())
    assert result["days"] == d(165)
    assert result["amount"] == d(55000)
    assert result["cap"] == d(2880000)


def test_gratuity_requires_one_year_and_honours_unpaid_absence():
    assert G.entitlement(d("0.99"), d(8000), d(8000), rate_map())["amount"] == d(0)
    assert G.service_years(date(2025, 1, 1), date(2027, 12, 31), 729) == d(1)


def test_cap_months_of_total_wage_is_applied_without_hardcoding():
    result = G.entitlement(d(20), d(50000), d(10000), rate_map())
    assert result["capped"] is True and result["amount"] == d(240000)


# ── F3: savings scheme ─────────────────────────────────────────────────────
@pytest.mark.parametrize("end, expected", [(date(2024, 12, 31), d("583.00")), (date(2025, 1, 1), d("833.00"))])
def test_f3_savings_subscription_uses_the_service_band(end, expected):
    result = G.savings(date(2020, 1, 2), end, d(10000), date(2020, 6, 1), d(9000), d(10000), 0, rate_map())
    assert result["subscription"] == expected
    assert result["frozen_legacy_gratuity"] == G.entitlement(d("0.41"), d(9000), d(10000), rate_map())["amount"]


# ── F4/F5: pension ─────────────────────────────────────────────────────────
def test_f4_law57_splits_the_15_percent_employer_share():
    result = PN.calculate(LAW57, rate_map())
    assert result["employee"] == d(1650)
    assert result["employer_gross"] == d(2250)
    assert result["government_support"] == d(375)
    assert result["employer_cash"] == d(1875)


def test_f4_government_support_is_optional_and_stops_at_the_limit():
    without = PN.calculate({**LAW57, "government_support_eligible": "NO"}, rate_map())
    assert without["government_support"] == d(0) and without["employer_cash"] == d(2250)
    above = PN.calculate({**LAW57, "pension_contribution_salary": "25000"}, rate_map())
    assert above["government_support"] == d(0)
    assert above["employee"] == d(2750) and above["employer_cash"] == d(3750)


def test_f5_adpf_new_member_and_the_salary_maxima():
    result = PN.calculate(ADPF_NEW, rate_map())
    assert result["employee"] == d(3300) and result["employer_cash"] == d(4500)
    capped = PN.calculate({"nationality_category": "UAE_NATIONAL", "pension_scheme": "ADPF_NEW_MEMBER",
                           "pension_contribution_salary": "150000"}, rate_map())
    assert capped["salary_used"] == d(100000) and capped["employee"] == d(11000)
    law7 = PN.calculate({"nationality_category": "UAE_NATIONAL", "pension_scheme": "GPSSA_LAW_7_1999",
                         "pension_contribution_salary": "60000"}, rate_map())
    assert law7["salary_used"] == d(50000) and law7["employee"] == d(2500)


def test_law57_below_the_minimum_blocks_with_named_reason():
    with pytest.raises(E.AECalculationBlockedError) as raised:
        PN.calculate({**LAW57, "pension_contribution_salary": "2000"}, rate_map())
    assert raised.value.key == E.PENSION_SALARY_BELOW_MINIMUM


def test_gcc_national_blocks_until_super_admin_adds_the_home_country_rate():
    facts = {"nationality_category": "GCC_NATIONAL", "gcc_country": "OM", "pension_scheme": "GCC_EXTENSION",
             "pension_contribution_salary": "10000"}
    with pytest.raises(E.AECalculationBlockedError) as raised:
        PN.calculate(facts, rate_map())
    assert raised.value.key == f"{E.GCC_RATES_NOT_CONFIGURED}:OM"
    result = PN.calculate(facts, rate_map(ae_gcc_om=rate("ae_gcc_om", "0.05", "0.15")))
    assert result["employee"] == d(500) and result["employer_cash"] == d(1500)


# ── F6: overtime minimums ──────────────────────────────────────────────────
def test_f6_overtime_hourly_rates():
    rates = O.hourly_rates(d(7200), rate_map())
    assert rates["basic_hourly"] == d(30)
    assert rates["ordinary"] == d("37.50")
    assert rates["night"] == d(45)
    assert rates["rest_day"] == d(45)


# ── F7 and the orchestrator ────────────────────────────────────────────────
def ctx_for(facts, rate_map_value=None, **kwargs):
    from app.modules.payroll.engine.base import PayrollContext

    values = dict(country="AE", gross=d(5500), basic=d(5000), hra=d(500),
                  pay_date=date(2026, 7, 2), rate_map=rate_map_value if rate_map_value is not None else rate_map(),
                  ae_facts=facts, period_start=date(2026, 7, 1), period_end=date(2026, 7, 31),
                  date_of_joining=date(2020, 1, 1))
    values.update(kwargs)
    return PayrollContext(**values)


def test_f7_emirati_below_the_minimum_blocks_but_expatriate_does_not():
    from app.modules.payroll.engine.countries import uae

    with pytest.raises(E.AECalculationBlockedError) as raised:
        uae.calculate(ctx_for({"nationality_category": "UAE_NATIONAL", "pension_scheme": "ADPF_NEW_MEMBER",
                               "pension_contribution_salary": "5500"}))
    assert raised.value.key == E.EMIRATI_MINIMUM_SALARY
    result = uae.calculate(ctx_for({**EXPAT, "eos_regime": "TRADITIONAL"}))
    assert result["ae_result"]["inputs"]["emirati_minimum_applied"] is None
    assert result["employee_pension"] == d(0)


def test_f7_before_the_rows_effective_date_there_is_no_minimum():
    from app.modules.payroll.engine.countries import uae

    result = uae.calculate(ctx_for({"nationality_category": "UAE_NATIONAL", "pension_scheme": "ADPF_NEW_MEMBER",
                                    "pension_contribution_salary": "5500"},
                                   pay_date=date(2026, 6, 30), period_start=date(2026, 6, 1),
                                   period_end=date(2026, 6, 30)))
    assert result["employee_pension"] == d(605)  # 11% of 5,500


def test_standard_dispatch_produces_the_same_figures_and_no_tax_line():
    from app.modules.payroll.engine.resolver import calculate_payroll

    result = calculate_payroll(ctx_for({**LAW57, "eos_regime": None},
                                       hra=d(0), gross=d(15000), basic=d(15000)), "standard")
    assert result.tds == d(0)
    assert result.employee_pension == d(1650)
    assert result.employer_pension == d(1875)
    assert result.net_pay == d(13350)
    snapshot = json.loads(json.dumps(result.ae_result))
    assert snapshot["income_tax"] == "0"
    assert snapshot["pension"]["government_support"] == "375.00"
    assert snapshot["final_settlement_days"] == "14"


def test_breakdown_and_employer_cost_add_up():
    from app.modules.payroll.engine.countries import uae

    result = uae.calculate(ctx_for({**LAW57}, hra=d(0), gross=d(15000), basic=d(15000)))
    e = result["ae_result"]
    assert d(e["employer_cost"]["pension_cash"]) == result["employer_pension"]
    assert d(e["employer_cost"]["end_of_service"]) == result["employer_payroll_tax"] == d(0)
    assert d(e["employer_cost"]["total"]) == d(16875)
    assert d(e["employee_deductions"]) == d(1650)


def test_difc_and_adgm_are_blocked_by_the_employees_region():
    from app.modules.payroll.engine.countries import uae

    for state in ("Dubai – DIFC", "Abu Dhabi – ADGM"):
        with pytest.raises(E.AECalculationBlockedError) as raised:
            uae.calculate(ctx_for(EXPAT, work_state=state))
        assert raised.value.key.startswith(E.OUT_OF_SCOPE)


def test_part_time_traditional_gratuity_is_blocked():
    from app.modules.payroll.engine.countries import uae

    with pytest.raises(E.AECalculationBlockedError) as raised:
        uae.calculate(ctx_for({**EXPAT, "work_pattern": "PART_TIME"}))
    assert raised.value.key == E.PART_TIME_EOS_NOT_SUPPORTED


def test_missing_pack_value_raises_named_error_and_no_partial_result():
    from app.modules.payroll.engine.countries import uae

    with pytest.raises(E.AECalculationBlockedError) as raised:
        uae.calculate(ctx_for(EXPAT, rate_map(ae_eos_band_years=None)))
    assert raised.value.key == f"{E.RATE_MISSING}:ae_eos_band_years"


def test_missing_employee_fact_raises_named_error():
    from app.modules.payroll.engine.countries import uae

    with pytest.raises(E.AECalculationBlockedError) as raised:
        uae.calculate(ctx_for({}))
    assert raised.value.key == f"{E.EMPLOYEE_FACT_MISSING}:nationality_category"


def test_row_effective_dates_are_honoured_for_an_old_payroll():
    from app.modules.payroll.engine.countries import uae

    old = rate_map(ae_gpssa_law57=rate("ae_gpssa_law57", "0.11", "0.15", effective_from=date(2026, 1, 1)))
    new = rate_map(ae_gpssa_law57=rate("ae_gpssa_law57", "0.12", "0.15", effective_from=date(2026, 8, 1)))
    assert uae.calculate(ctx_for(LAW57, old, basic=d(5000), hra=d(1000), gross=d(6000)))["employee_pension"] == d(1650)
    assert uae.calculate(ctx_for(LAW57, new, basic=d(5000), hra=d(1000), gross=d(6000)))["employee_pension"] == d(1800)


def test_unpaid_absence_is_derived_from_the_payslip_not_an_employee_field():
    from app.modules.payroll.engine.countries import uae

    result = uae.calculate(ctx_for(EXPAT, unpaid_leave_days=1))
    assert result["ae_result"]["end_of_service"]["unpaid_absence_days"] == 1
    assert d(result["ae_result"]["wages"]["unpaid_leave_deduction"]) > d(0)
