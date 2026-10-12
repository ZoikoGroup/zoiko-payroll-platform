"""
tests/test_uk_statutory_leave_wiring.py
--------------------------------------------
Coverage for service.py's wiring of UK Statutory Family Pay into real
leave requests (ZP-TAX-UK-2026-27-001 §11 gap-closure Part 7A,
2026-09-09): _maybe_compute_uk_statutory_leave_pay() (freezes AWE +
total onto a leave request the moment it's approved) and
_uk_statutory_pay_for_period() (pro-rates a frozen total into whichever
pay period(s) it overlaps, at normal payslip generation/preview time —
no manual "run the calculator, type the number in" step needed). DB-
integration style, same fixture pattern as test_uk_statutory_pay_
calculator.py.
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP


def _round2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

import pytest

from app.modules.payroll import service
from app.modules.payroll.engine.countries import shared as shared_module
from app.modules.payroll.models import (
    ContributionRate, PayrollEmployee, PayrollLeaveRequest, PayrollRun, PayslipItem, PayrollStatus,
)


def _make_uk_employee(db, org_id, code="LV1", pay_frequency="Monthly"):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="UK", ctc=Decimal("60000"), pay_frequency=pay_frequency,
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _seed_family_pay_rates(db, org_id):
    db.add(ContributionRate(
        organization_id=org_id, jurisdiction_country="UK",
        component_key="fam_pay_awe_pct", label="Family Pay AWE Percentage",
        employee_share="90%", employer_share="—", total="90%",
        employee_rate_pct=Decimal("90"),
    ))
    db.add(ContributionRate(
        organization_id=org_id, jurisdiction_country="UK",
        component_key="fam_pay_flat_rate", label="Family Pay Standard Weekly Rate",
        employee_share="—", employer_share="—", total="£194.32",
        flat_amount=Decimal("194.32"),
    ))
    db.commit()


def _make_run(db, org_id, pay_date, period_start=None, period_end=None, label="Test Run"):
    run = PayrollRun(
        organization_id=org_id, period_label=label,
        period_start=period_start or pay_date, period_end=period_end or pay_date, pay_date=pay_date,
        status=PayrollStatus.PAID.value,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _make_payslip(db, run, employee, org_id, gross_pay):
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee.id, organization_id=org_id,
        employee_name=employee.name, gross_pay=gross_pay,
    )
    db.add(item)
    db.commit()
    return item


def _make_prior_monthly_history(db, org_id, emp, gross=Decimal("2000"), months=2, before=date(2026, 6, 1)):
    # Monthly AWE needs 2 prior non-Draft payslips before the qualifying week.
    pay_dates = [date(2026, 4, 1), date(2026, 5, 1)][:months]
    for pd in pay_dates:
        run = _make_run(db, org_id, pd)
        _make_payslip(db, run, emp, org_id, gross)


@pytest.fixture(autouse=True)
def _reset_switch():
    shared_module._UK_STATUTORY_LEAVE_PAY_ENABLED_COUNTRIES.discard("UK")
    yield
    shared_module._UK_STATUTORY_LEAVE_PAY_ENABLED_COUNTRIES.discard("UK")


def _approve(db, organization, request_id):
    class _Data:
        status = "approved"
    return service.review_payroll_leave_request(db, request_id, _Data(), organization.id, reviewer_id=1)


def _make_leave_request(db, org_id, employee_id, leave_type, start_date, end_date):
    # Built directly against the model rather than via
    # service.create_payroll_leave_request — that function's business-code
    # generation calls a Postgres-only pg_advisory_xact_lock() that the
    # SQLite test database doesn't support (a pre-existing limitation, not
    # something this Part 7A change introduces — no other test in this
    # suite calls create_payroll_leave_request either).
    days = (end_date - start_date).days + 1
    record = PayrollLeaveRequest(
        organization_id=org_id, employee_id=employee_id, leave_type=leave_type,
        start_date=start_date, end_date=end_date, days=days, status="pending",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def test_approving_maternity_leave_computes_and_freezes_statutory_pay(db, organization):
    shared_module._UK_STATUTORY_LEAVE_PAY_ENABLED_COUNTRIES.add("UK")
    _seed_family_pay_rates(db, organization.id)
    emp = _make_uk_employee(db, organization.id, "LV-SMP1")
    _make_prior_monthly_history(db, organization.id, emp)

    record = _make_leave_request(db, organization.id, emp.id, "maternity", date(2026, 6, 1), date(2026, 6, 7))
    result = _approve(db, organization, record.id)
    assert result["statutoryPayType"] == "SMP"
    assert result["statutoryAweSnapshot"] is not None
    assert result["statutoryPayTotalAmount"] is not None
    # 2 prior months of £2000 each -> AWE = (4000*6)/52 = 461.54; 1 claim
    # week, first-6-weeks phase -> 90% of AWE, uncapped.
    expected_awe = _round2(Decimal("4000") * 6 / 52)
    assert result["statutoryAweSnapshot"] == expected_awe
    assert result["statutoryPayTotalAmount"] == _round2(expected_awe * Decimal("90") / 100)


def test_approving_non_statutory_leave_leaves_columns_null(db, organization):
    shared_module._UK_STATUTORY_LEAVE_PAY_ENABLED_COUNTRIES.add("UK")
    _seed_family_pay_rates(db, organization.id)
    emp = _make_uk_employee(db, organization.id, "LV-PAID1")
    _make_prior_monthly_history(db, organization.id, emp)

    record = _make_leave_request(db, organization.id, emp.id, "paid", date(2026, 6, 1), date(2026, 6, 7))
    result = _approve(db, organization, record.id)
    assert result["statutoryPayType"] is None
    assert result["statutoryPayTotalAmount"] is None


def test_statutory_pay_no_op_when_switch_off(db, organization):
    # Switch left off (default via _reset_switch fixture).
    _seed_family_pay_rates(db, organization.id)
    emp = _make_uk_employee(db, organization.id, "LV-SMP2")
    _make_prior_monthly_history(db, organization.id, emp)

    record = _make_leave_request(db, organization.id, emp.id, "maternity", date(2026, 6, 1), date(2026, 6, 7))
    result = _approve(db, organization, record.id)
    assert result["statutoryPayType"] is None
    assert result["statutoryPayTotalAmount"] is None


def test_statutory_pay_fails_closed_when_awe_not_derivable(db, organization):
    shared_module._UK_STATUTORY_LEAVE_PAY_ENABLED_COUNTRIES.add("UK")
    _seed_family_pay_rates(db, organization.id)
    emp = _make_uk_employee(db, organization.id, "LV-SMP3")
    # No prior pay history at all -> AWE cannot be derived.

    record = _make_leave_request(db, organization.id, emp.id, "maternity", date(2026, 6, 1), date(2026, 6, 7))
    result = _approve(db, organization, record.id)
    assert result["statutoryPayType"] == "SMP"
    assert result["statutoryPayTotalAmount"] is None
    assert "could not be derived" in result["statutoryPayNote"]


def test_statutory_pay_uses_uncapped_first_6_weeks_then_capped_rate(db, organization):
    shared_module._UK_STATUTORY_LEAVE_PAY_ENABLED_COUNTRIES.add("UK")
    _seed_family_pay_rates(db, organization.id)
    emp = _make_uk_employee(db, organization.id, "LV-SMP4")
    # High gross -> 90% of AWE exceeds the £194.32 flat cap from week 7 on.
    _make_prior_monthly_history(db, organization.id, emp, gross=Decimal("5000"))

    # 56 days -> 8 claim weeks.
    record = _make_leave_request(db, organization.id, emp.id, "maternity", date(2026, 6, 1), date(2026, 7, 26))
    result = _approve(db, organization, record.id)
    awe = result["statutoryAweSnapshot"]
    # 2 prior months of £5000 each -> AWE = (10000*6)/52.
    expected_awe = _round2(Decimal("10000") * 6 / 52)
    assert awe == expected_awe
    awe_based_weekly = _round2(expected_awe * Decimal("90") / 100)
    capped_weekly = _round2(min(Decimal("194.32"), expected_awe * Decimal("90") / 100))
    expected = (awe_based_weekly * 6) + (capped_weekly * 2)
    assert result["statutoryPayTotalAmount"] == _round2(expected)


def test_uk_statutory_pay_for_period_prorates_across_pay_periods(db, organization):
    emp = _make_uk_employee(db, organization.id, "LV-PRORATE1")
    record = PayrollLeaveRequest(
        organization_id=organization.id, employee_id=emp.id, leave_type="maternity",
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 30), days=30,
        status="approved", statutory_pay_type="SMP", statutory_pay_total_amount=Decimal("900.00"),
    )
    db.add(record)
    db.commit()

    # First half of June falls in one pay period, second half in the next.
    first_half = service._uk_statutory_pay_for_period(db, emp.id, organization.id, date(2026, 6, 1), date(2026, 6, 15))
    second_half = service._uk_statutory_pay_for_period(db, emp.id, organization.id, date(2026, 6, 16), date(2026, 6, 30))
    assert first_half + second_half == Decimal("900.00")
    # 15 of 30 days each -> exactly half.
    assert first_half == Decimal("450.00")


def test_uk_statutory_pay_for_period_ignores_unapproved_requests(db, organization):
    emp = _make_uk_employee(db, organization.id, "LV-PRORATE2")
    record = PayrollLeaveRequest(
        organization_id=organization.id, employee_id=emp.id, leave_type="maternity",
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 30), days=30,
        status="pending", statutory_pay_type="SMP", statutory_pay_total_amount=Decimal("900.00"),
    )
    db.add(record)
    db.commit()

    total = service._uk_statutory_pay_for_period(db, emp.id, organization.id, date(2026, 6, 1), date(2026, 6, 30))
    assert total == Decimal("0")


def test_uk_statutory_pay_for_period_ignores_requests_with_no_frozen_total(db, organization):
    emp = _make_uk_employee(db, organization.id, "LV-PRORATE3")
    record = PayrollLeaveRequest(
        organization_id=organization.id, employee_id=emp.id, leave_type="maternity",
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 30), days=30,
        status="approved", statutory_pay_type="SMP", statutory_pay_total_amount=None,
    )
    db.add(record)
    db.commit()

    total = service._uk_statutory_pay_for_period(db, emp.id, organization.id, date(2026, 6, 1), date(2026, 6, 30))
    assert total == Decimal("0")
