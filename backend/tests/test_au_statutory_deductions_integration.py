"""
tests/test_au_statutory_deductions_integration.py
------------------------------------------------------
End-to-end DB-level coverage proving Australia's child support/garnishee
wiring (ZP-TAX-AU-2026-27-001 §19, Phase 5) actually fires from a real
persisted payslip — service.add_payslip_item must (a) reduce the
employee's own net pay by the order's deduction, (b) write the amount
back onto CourtOrderedDeduction.total_amount_collected, and (c) mark a
capped order 'completed' once its total_amount_to_collect is reached.
Mirrors test_au_payday_super_integration.py's exact pattern.
"""

from datetime import date
from decimal import Decimal

from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee, PayrollRun, CourtOrderedDeduction
from app.modules.payroll.schemas import PayslipItemCreate


def _make_au_employee(db, org_id, code="AU-CS-1"):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="AU", ctc=Decimal("120000"),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _make_run(db, org_id, period_start, period_end, pay_date):
    run = PayrollRun(
        organization_id=org_id, period_label="AU Statutory Deduction Test Run",
        period_start=period_start, period_end=period_end, pay_date=pay_date,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def test_add_payslip_item_deducts_and_collects_against_real_order(db, organization):
    employee = _make_au_employee(db, organization.id)
    order = service.create_court_ordered_deduction(
        db, organization.id, employee.id, "AUSTRALIA", "CHILD_SUPPORT_DEDUCTION_NOTICE",
        date(2026, 1, 1), fixed_deduction_amount=Decimal("500"), total_amount_to_collect=Decimal("1200"),
    )
    assert order.status == "active"
    assert order.total_amount_collected == Decimal("0")

    run = _make_run(db, organization.id, date(2026, 8, 1), date(2026, 8, 31), date(2026, 9, 1))
    item = service.add_payslip_item(db, run.id, PayslipItemCreate(
        employee_id=employee.id, basic_salary=Decimal("10000"),
    ), organization.id)
    db.commit()

    assert item.au_statutory_deductions_total == Decimal("500.00")
    # $10,000/mo * 12 = $120,000 annual > $97,000 MLS threshold, so a real
    # $100.00/mo Medicare Levy Surcharge also applies on top of the
    # $500.00 garnishee — net_pay reflects BOTH real deductions.
    assert item.net_pay == Decimal("10000.00") - Decimal("500.00") - Decimal("100.00")

    db.refresh(order)
    assert order.total_amount_collected == Decimal("500")
    assert order.status == "active"  # cap ($1,200) not yet reached


def test_second_payslip_completes_a_capped_order(db, organization):
    employee = _make_au_employee(db, organization.id, code="AU-CS-2")
    order = service.create_court_ordered_deduction(
        db, organization.id, employee.id, "AUSTRALIA", "CHILD_SUPPORT_DEDUCTION_NOTICE",
        date(2026, 1, 1), fixed_deduction_amount=Decimal("500"), total_amount_to_collect=Decimal("800"),
    )
    run = _make_run(db, organization.id, date(2026, 8, 1), date(2026, 8, 31), date(2026, 9, 1))
    service.add_payslip_item(db, run.id, PayslipItemCreate(
        employee_id=employee.id, basic_salary=Decimal("10000"),
    ), organization.id)
    db.commit()
    db.refresh(order)
    assert order.total_amount_collected == Decimal("500")
    assert order.status == "active"

    run2 = _make_run(db, organization.id, date(2026, 9, 1), date(2026, 9, 30), date(2026, 10, 1))
    service.add_payslip_item(db, run2.id, PayslipItemCreate(
        employee_id=employee.id, basic_salary=Decimal("10000"),
    ), organization.id)
    db.commit()
    db.refresh(order)
    # 500 + 500 = 1000 >= 800 cap -> completed, even though the second
    # payslip's own contribution ($500) alone exceeds what was left ($300)
    # — the order's own fixed amount is honored per-payslip (§19 doesn't
    # ask the engine to self-limit to the exact remaining balance), only
    # the status transition reacts to the cap being reached.
    assert order.total_amount_collected == Decimal("1000")
    assert order.status == "completed"


def test_completed_order_no_longer_applies_to_a_later_payslip(db, organization):
    employee = _make_au_employee(db, organization.id, code="AU-CS-3")
    order = service.create_court_ordered_deduction(
        db, organization.id, employee.id, "AUSTRALIA", "CHILD_SUPPORT_DEDUCTION_NOTICE",
        date(2026, 1, 1), fixed_deduction_amount=Decimal("500"), total_amount_to_collect=Decimal("500"),
    )
    run = _make_run(db, organization.id, date(2026, 8, 1), date(2026, 8, 31), date(2026, 9, 1))
    service.add_payslip_item(db, run.id, PayslipItemCreate(
        employee_id=employee.id, basic_salary=Decimal("10000"),
    ), organization.id)
    db.commit()
    db.refresh(order)
    assert order.status == "completed"

    run2 = _make_run(db, organization.id, date(2026, 9, 1), date(2026, 9, 30), date(2026, 10, 1))
    item2 = service.add_payslip_item(db, run2.id, PayslipItemCreate(
        employee_id=employee.id, basic_salary=Decimal("10000"),
    ), organization.id)
    db.commit()
    # _load_au_active_court_orders only ever selects status == "active".
    assert item2.au_statutory_deductions_total == Decimal("0")
    # Still a real $100.00/mo Medicare Levy Surcharge on $120,000 annual —
    # only the garnishee itself is gone now that the order is completed.
    assert item2.net_pay == Decimal("10000.00") - Decimal("100.00")
