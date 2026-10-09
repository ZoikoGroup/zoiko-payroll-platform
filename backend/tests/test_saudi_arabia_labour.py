"""Saudi Arabia labour-pay controls (ZP-SA-ENG-001 §11) — engine/jurisdictions/
saudi_arabia/labour.py and its integration into engine/countries/saudi_arabia.py.

Deductions are validated per type and in aggregate and then DEDUCTED from net
pay; a breach BLOCKS (SA-029/SA-030). Approved overtime must be paid at least
hourly wage + 50% of basic hourly wage unless consented compensatory leave is
recorded. Hours are a compliance report.
"""
from decimal import Decimal

import pytest

from app.modules.payroll.engine.resolver import calculate_payroll
from app.modules.payroll.engine.countries import saudi_arabia
from app.modules.payroll.engine.countries.saudi_arabia import SACalculationBlockedError
from app.modules.payroll.engine.jurisdictions.saudi_arabia import labour
from app.modules.payroll.hmrc_golden_harness import _build_rate_map, build_context


def _rates(**over):
    base = {
        "sa_rate_selection_basis": {"text_value": "PENDING_G1"},
        "sa_gosi_below_min_behaviour": {"text_value": "BLOCK"},
        "sa_rounding_mode": {"text_value": "HALF_UP"},
        "sa_rounding_precision": {"flat_amount": 2},
        "sa_normal_hours_daily": {"flat_amount": 8},
        "sa_normal_hours_weekly": {"flat_amount": 48},
        "sa_overtime_basic_premium_pct": {"employee_rate_pct": 50},
        "sa_monthly_hours_divisor": {"flat_amount": 240},
        "sa_loan_cap_pct": {"employee_rate_pct": 10},
        "sa_aggregate_deduction_cap_pct": {"employee_rate_pct": 50},
    }
    base.update(over)
    return base


def _case(**over):
    data = {
        "country": "SA", "gross": "10000", "basic": "8000", "hra": "2000",
        "pay_date": "2026-03-31", "pay_frequency": "Monthly",
        "sa_worker_class": "NON_SAUDI", "sa_contributory_wage": "10000",
        "rate_map": _rates(),
        "slabs": [{"rule_type": "SA_GOSI_BRANCH", "filing_status": "NON_SAUDI",
                   "tax_regime": "OCCUPATIONAL_HAZARDS", "rate_pct": 0, "employer_rate_pct": 2,
                   "min_amount": 400, "max_amount": 45000}],
    }
    data.update(over)
    return data


def _calc(**over):
    return saudi_arabia.calculate(build_context(_case(**over)))


# ── hours report ────────────────────────────────────────────────────────────
def test_hours_check_weekly_breach_on_49_hour_week():
    records = [{"date": f"2026-03-{day:02d}", "hours": 7} for day in range(2, 9)]
    out = labour.hours_check(records, _build_rate_map(_rates()), ramadan=False)
    assert out["status"] == "BREACH"
    assert any(b["scope"] == "weekly" for b in out["breaches"])
    assert all(b["scope"] != "daily" for b in out["breaches"])


def test_hours_check_missing_rows_not_evaluated():
    assert labour.hours_check([{"date": "2026-03-02", "hours": 9}], {})["status"] == "NOT_EVALUATED"


# ── overtime (spec §11: hourly wage + 50% of basic hourly wage) ─────────────
def test_overtime_formula_matches_spec():
    # wage 10,500 / 240 = 43.75; basic 8,000 / 240 = 33.3333 x 50% = 16.6667;
    # per hour 60.4167; 10 hours = 604.17 (hand-computed).
    ot = labour.overtime_pay(Decimal("10500"), Decimal("8000"), Decimal("10"), _build_rate_map(_rates()))
    assert ot["status"] == "OK"
    assert ot["amount"] == Decimal("604.17")


def test_overtime_without_divisor_not_evaluated():
    rates = _rates()
    del rates["sa_monthly_hours_divisor"]
    assert labour.overtime_pay(Decimal("1"), Decimal("1"), Decimal("1"), _build_rate_map(rates))["status"] == "NOT_EVALUATED"


def test_underpaid_approved_overtime_blocks():
    with pytest.raises(SACalculationBlockedError) as exc:
        _calc(sa_overtime_hours="10", overtime="0")
    assert exc.value.key == "sa_overtime_underpaid"


def test_statutory_overtime_paid_passes():
    # wage 10,000 / 240 = 41.6667; basic 8,000 / 240 x 50% = 16.6667; 10h = 583.33
    result = _calc(sa_overtime_hours="10", overtime="583.33", gross="10583.33")
    assert result["sa_result"]["labour"]["overtime"]["amount"] == "583.33"


def test_consented_compensatory_leave_skips_payment_check():
    result = _calc(sa_overtime_hours="10", overtime="0", sa_overtime_comp_leave_consented=True)
    assert result["sa_result"]["labour"]["overtime"]["compensatoryLeave"] is True


# ── deductions (SA-029 / SA-030) ────────────────────────────────────────────
def test_deductions_reduce_net_pay():
    ctx = build_context(_case(sa_deduction_orders=[
        {"id": 1, "type": "LOAN", "amount": "500", "evidence_ref": "loan-2026-04"},
        {"id": 2, "type": "DISCIPLINARY", "amount": "100", "evidence_ref": "hr-77"},
    ]))
    result = calculate_payroll(ctx, "standard")
    assert result.sa_result["sa_other_deductions_total"] == "600"
    # Non-Saudi: no employee GOSI, so net = 10,000 - 600.
    assert result.net_pay == Decimal("9400.00")


def test_loan_over_ten_percent_cap_blocks():
    with pytest.raises(SACalculationBlockedError):
        _calc(sa_deduction_orders=[{"id": 1, "type": "LOAN", "amount": "1500", "evidence_ref": "loan-1"}])


def test_aggregate_over_fifty_percent_cap_blocks():
    with pytest.raises(SACalculationBlockedError):
        _calc(sa_deduction_orders=[
            {"id": 1, "type": "LOAN", "amount": "999", "evidence_ref": "loan-1"},
            {"id": 2, "type": "COURT_ORDER", "amount": "4500", "evidence_ref": "court-9"},
        ])


def test_damage_without_configured_limit_blocks():
    with pytest.raises(SACalculationBlockedError):
        _calc(sa_deduction_orders=[{"id": 1, "type": "DAMAGE", "amount": "100", "evidence_ref": "incident-3"}])


def test_unauthorised_type_blocks():
    with pytest.raises(SACalculationBlockedError):
        _calc(sa_deduction_orders=[{"id": 1, "type": "PARKING_FINE", "amount": "100", "evidence_ref": "x"}])


def test_missing_evidence_blocks():
    with pytest.raises(SACalculationBlockedError):
        _calc(sa_deduction_orders=[{"id": 1, "type": "ADVANCE", "amount": "100", "evidence_ref": ""}])


def test_deductions_are_sequenced_statutorily():
    out = labour.evaluate_deductions(
        [{"id": 1, "type": "DISCIPLINARY", "amount": "10", "evidence_ref": "a"},
         {"id": 2, "type": "COURT_ORDER", "amount": "10", "evidence_ref": "b"},
         {"id": 3, "type": "LOAN", "amount": "10", "evidence_ref": "c"}],
        Decimal("10000"), _build_rate_map(_rates()))
    assert [line["type"] for line in out["lines"]] == ["COURT_ORDER", "LOAN", "DISCIPLINARY"]
