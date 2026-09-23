"""
tests/test_jamaica.py
------------------------
Validates engine/countries/jamaica.py against ZP-JM-ENG-001 §12 Fixture
F1 — including the fixture's own accounting invariant (employee
deductions total 23,232.50, employer contributions total 24,790.00, net
cash 176,767.50).
"""

from dataclasses import dataclass
from datetime import date
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


def _ctx(gross: Decimal, pay_date: date = None, jm_heart_ytd_remuneration_before: Decimal = None) -> PayrollContext:
    return PayrollContext(
        gross=gross, basic=gross, country="JM", rate_map=_jm_rate_map(), slabs=_jm_slabs(),
        pay_frequency="Monthly", pay_date=pay_date,
        jm_heart_ytd_remuneration_before=jm_heart_ytd_remuneration_before,
    )


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


# ── Jan-Mar vs Apr-Dec personal allowance (ZP-JM-ENG-001 §3 / §12 F2) ──────
# The spec's own Fixture F2: at the same 194,000 PAYE base (200,000 gross
# minus 6,000 NIS), January's component is (194,000-149,948)x25%=11,013.00
# while September's is 8,867.50 — a real difference of 2,145.50, driven by
# the Jan-Mar monthly allowance (149,948) genuinely being lower than the
# Apr-Dec rate (158,530), not a rounding artifact.

def test_january_uses_the_lower_jan_mar_monthly_allowance():
    result = jamaica.calculate(_ctx(Decimal("200000"), pay_date=date(2026, 1, 15)))
    assert result["tds"] == Decimal("11013.00")


def test_march_still_uses_the_jan_mar_allowance():
    result = jamaica.calculate(_ctx(Decimal("200000"), pay_date=date(2026, 3, 31)))
    assert result["tds"] == Decimal("11013.00")


def test_april_switches_to_the_apr_dec_allowance():
    result = jamaica.calculate(_ctx(Decimal("200000"), pay_date=date(2026, 4, 1)))
    assert result["tds"] == Decimal("8867.50")


def test_no_pay_date_falls_back_to_apr_dec_allowance_unchanged():
    """A caller that never sets pay_date (e.g. an older test double) must
    see identical behavior to before this Jan-Mar split was added."""
    result = jamaica.calculate(_ctx(Decimal("200000")))
    assert result["tds"] == Decimal("8867.50")


# ── HEART employer-wide monthly aggregation (JM-008) ───────────────────────
# Three employees each earning 5,000 (individually well under the 14,444
# threshold): the combined monthly total (15,000) crosses it only once the
# third employee is processed. The full 3% liability (450.00 = 3% of
# 15,000) must be collected exactly once, attributed to whichever
# employee's period pushed the cumulative total over — not charged to
# every employee, and not missed because no single employee was over the
# threshold on their own (the actual bug Phase 1's per-employee-only
# check has).

def test_heart_aggregates_across_employees_not_per_employee():
    before = Decimal("0")
    collected = Decimal("0")
    for _ in range(3):
        result = jamaica.calculate(_ctx(Decimal("5000"), jm_heart_ytd_remuneration_before=before))
        collected += result["employer_payroll_tax"]
        before = result["jm_heart_ytd_remuneration_after"]
    assert collected == Decimal("450.00")  # 3% of the combined 15,000
    assert before == Decimal("15000")


def test_heart_first_two_employees_below_combined_threshold_owe_nothing():
    result1 = jamaica.calculate(_ctx(Decimal("5000"), jm_heart_ytd_remuneration_before=Decimal("0")))
    assert result1["employer_payroll_tax"] == Decimal("0.00")
    result2 = jamaica.calculate(_ctx(Decimal("5000"), jm_heart_ytd_remuneration_before=Decimal("5000")))
    assert result2["employer_payroll_tax"] == Decimal("0.00")


def test_heart_wired_still_levies_full_base_once_liable_same_employee():
    """A single employee whose own gross alone crosses the threshold,
    with the accumulator wired from 0, must match Phase 1's own math
    exactly (3% of the whole base, not just the excess)."""
    result = jamaica.calculate(_ctx(Decimal("200000"), jm_heart_ytd_remuneration_before=Decimal("0")))
    assert result["employer_payroll_tax"] == Decimal("6000.00")  # matches fixture F1's own HEART figure
    assert result["jm_heart_ytd_remuneration_after"] == Decimal("200000")


def test_heart_not_wired_falls_back_to_phase_1_behavior_unchanged():
    """jm_heart_ytd_remuneration_before is None (every employee before this
    accumulator was wired, or the rollout switch off) must produce
    byte-for-byte the same result as before this feature existed."""
    result = jamaica.calculate(_ctx(Decimal("200000")))
    assert result["employer_payroll_tax"] == Decimal("6000.00")
    assert result["jm_heart_ytd_remuneration_after"] is None
