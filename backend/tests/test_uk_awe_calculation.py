"""
tests/test_uk_awe_calculation.py
------------------------------------
Coverage for service.py's calculate_average_weekly_earnings() (ZP-TAX-UK-
2026-27-001 §11/§12 gap-closure Phase 4, 2026-09-09) — the AWE derivation
uk.py's calculate_ssp()/calculate_statutory_family_pay() both need as an
input but never computed themselves. DB-integration style, same pattern
as test_ca_org_eht_service_integration.py: real PayrollRun/PayslipItem
rows, no mocking.
"""

from datetime import date
from decimal import Decimal

from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem, PayrollStatus


def _make_uk_employee(db, org_id, code="AWE1"):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="UK", ctc=Decimal("60000"),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _make_run(db, org_id, pay_date, status=PayrollStatus.PAID.value, label="Test Run"):
    run = PayrollRun(
        organization_id=org_id, period_label=label,
        period_start=pay_date, period_end=pay_date, pay_date=pay_date,
        status=status,
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
    db.refresh(item)
    return item


def test_weekly_awe_averages_last_8_payments(db, organization):
    emp = _make_uk_employee(db, organization.id, "AWE-W1")
    pay_dates = [date(2026, 6, d) for d in (1, 8, 15, 22, 29)] + [date(2026, 7, d) for d in (6, 13, 20)]
    for i, pd in enumerate(pay_dates):
        run = _make_run(db, organization.id, pd)
        _make_payslip(db, run, emp, organization.id, Decimal("500") + i)  # 500..507
    result = service.calculate_average_weekly_earnings(db, emp.id, date(2026, 7, 27), "Weekly")
    assert result["eligible"] is True
    # sum(500..507) = 4028 -> /8 = 503.50
    assert result["average_weekly_earnings"] == Decimal("503.50")


def test_weekly_awe_insufficient_history(db, organization):
    emp = _make_uk_employee(db, organization.id, "AWE-W2")
    for pd in (date(2026, 6, 1), date(2026, 6, 8)):
        run = _make_run(db, organization.id, pd)
        _make_payslip(db, run, emp, organization.id, Decimal("500"))
    result = service.calculate_average_weekly_earnings(db, emp.id, date(2026, 6, 15), "Weekly")
    assert result["eligible"] is False
    assert "insufficient pay history" in result["reason"]
    assert result["average_weekly_earnings"] == Decimal("0")


def test_monthly_awe_uses_hmrc_two_month_formula(db, organization):
    emp = _make_uk_employee(db, organization.id, "AWE-M1")
    run1 = _make_run(db, organization.id, date(2026, 5, 1))
    _make_payslip(db, run1, emp, organization.id, Decimal("3000"))
    run2 = _make_run(db, organization.id, date(2026, 6, 1))
    _make_payslip(db, run2, emp, organization.id, Decimal("3000"))
    result = service.calculate_average_weekly_earnings(db, emp.id, date(2026, 7, 1), "Monthly")
    assert result["eligible"] is True
    # (3000+3000) * 6 / 52 = 6000*6/52 = 692.3076... -> 692.31
    assert result["average_weekly_earnings"] == Decimal("692.31")


def test_monthly_awe_insufficient_history_with_only_one_payslip(db, organization):
    emp = _make_uk_employee(db, organization.id, "AWE-M2")
    run = _make_run(db, organization.id, date(2026, 6, 1))
    _make_payslip(db, run, emp, organization.id, Decimal("3000"))
    result = service.calculate_average_weekly_earnings(db, emp.id, date(2026, 7, 1), "Monthly")
    assert result["eligible"] is False
    assert result["average_weekly_earnings"] == Decimal("0")


def test_fortnightly_awe_uses_last_4_payments(db, organization):
    emp = _make_uk_employee(db, organization.id, "AWE-F1")
    for pd, amount in zip(
        (date(2026, 5, 1), date(2026, 5, 15), date(2026, 5, 29), date(2026, 6, 12)),
        (Decimal("1000"), Decimal("1000"), Decimal("1000"), Decimal("1000")),
    ):
        run = _make_run(db, organization.id, pd)
        _make_payslip(db, run, emp, organization.id, amount)
    result = service.calculate_average_weekly_earnings(db, emp.id, date(2026, 6, 26), "Fortnightly")
    assert result["eligible"] is True
    # sum = 4000 -> /8 = 500.00
    assert result["average_weekly_earnings"] == Decimal("500.00")


def test_four_weekly_awe_uses_last_2_payments(db, organization):
    emp = _make_uk_employee(db, organization.id, "AWE-4W1")
    for pd, amount in zip((date(2026, 5, 1), date(2026, 5, 29)), (Decimal("2000"), Decimal("2400"))):
        run = _make_run(db, organization.id, pd)
        _make_payslip(db, run, emp, organization.id, amount)
    result = service.calculate_average_weekly_earnings(db, emp.id, date(2026, 6, 26), "FourWeekly")
    assert result["eligible"] is True
    # sum = 4400 -> /8 = 550.00
    assert result["average_weekly_earnings"] == Decimal("550.00")


def test_draft_run_payslips_are_excluded(db, organization):
    emp = _make_uk_employee(db, organization.id, "AWE-D1")
    # 8 real (Paid) weekly payslips...
    pay_dates = [date(2026, 6, d) for d in (1, 8, 15, 22, 29)] + [date(2026, 7, d) for d in (6, 13, 20)]
    for pd in pay_dates:
        run = _make_run(db, organization.id, pd)
        _make_payslip(db, run, emp, organization.id, Decimal("500"))
    # ...plus one more-recent DRAFT payslip with a very different amount —
    # must not be counted at all (not summed, not occupying a "slot" that
    # would otherwise push out the oldest real payslip).
    draft_run = _make_run(db, organization.id, date(2026, 7, 24), status=PayrollStatus.DRAFT.value)
    _make_payslip(db, draft_run, emp, organization.id, Decimal("999999"))

    without_draft = service.calculate_average_weekly_earnings(db, emp.id, date(2026, 7, 27), "Weekly")
    assert without_draft["eligible"] is True
    assert without_draft["average_weekly_earnings"] == Decimal("500.00")


def test_payslip_on_qualifying_week_start_itself_is_excluded(db, organization):
    # AWE must only look at payments BEFORE the qualifying week — a
    # payslip dated exactly on qualifying_week_start belongs to a period
    # that hasn't happened relative to the statutory event yet.
    emp = _make_uk_employee(db, organization.id, "AWE-Q1")
    pay_dates = [date(2026, 6, d) for d in (1, 8, 15, 22, 29)] + [date(2026, 7, d) for d in (6, 13, 20)]
    for pd in pay_dates:
        run = _make_run(db, organization.id, pd)
        _make_payslip(db, run, emp, organization.id, Decimal("500"))
    same_day_run = _make_run(db, organization.id, date(2026, 7, 27))
    _make_payslip(db, same_day_run, emp, organization.id, Decimal("999999"))

    result = service.calculate_average_weekly_earnings(db, emp.id, date(2026, 7, 27), "Weekly")
    assert result["eligible"] is True
    assert result["average_weekly_earnings"] == Decimal("500.00")


def test_unknown_pay_frequency_is_not_computable(db, organization):
    emp = _make_uk_employee(db, organization.id, "AWE-U1")
    result = service.calculate_average_weekly_earnings(db, emp.id, date(2026, 7, 1), "Irregular")
    assert result["eligible"] is False
    assert "not defined" in result["reason"]
