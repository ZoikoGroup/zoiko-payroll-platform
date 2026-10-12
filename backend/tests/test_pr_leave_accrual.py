"""
tests/test_pr_leave_accrual.py
---------------------------------
Coverage for service.accrue_pr_monthly_leave (PR-028/PR-029) — Puerto
Rico vacation (Act 4-2017/Law 180) + sick leave accrual, persisted into
the SAME generic PayrollLeaveAllocation.leave_balances JSON every other
country's leave management already uses (get_leave_allocations/
bulk_save_leaves), never a bespoke parallel ledger.
"""
from decimal import Decimal

import pytest

from app.core.exceptions import NotFoundException
from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee, PayrollLeaveAllocation


def _make_employee(db, organization_id, code="PRL1", name="Maria Rivera"):
    employee = PayrollEmployee(organization_id=organization_id, employee_code=code, name=name)
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


def test_accrue_creates_a_new_leave_allocation_row(db, organization):
    employee = _make_employee(db, organization.id)
    row = service.accrue_pr_monthly_leave(
        db, organization.id, employee.id,
        hired_before_2017=False, years_of_service=Decimal("6"), qualifying_small_employer=False,
        qualifying_hours_in_month=Decimal("132"),
    )
    assert row.leave_balances["vacation"]["total"] == 1.0  # year-6 standard employer -> 1 day/month
    assert row.leave_balances["sick"]["total"] == 1.0


def test_accrue_below_130_hours_adds_nothing(db, organization):
    employee = _make_employee(db, organization.id)
    row = service.accrue_pr_monthly_leave(
        db, organization.id, employee.id,
        hired_before_2017=False, years_of_service=Decimal("6"), qualifying_small_employer=False,
        qualifying_hours_in_month=Decimal("100"),
    )
    assert row.leave_balances["vacation"]["total"] == 0.0
    assert row.leave_balances["sick"]["total"] == 0.0


def test_accrue_is_additive_across_months(db, organization):
    employee = _make_employee(db, organization.id)
    service.accrue_pr_monthly_leave(
        db, organization.id, employee.id,
        hired_before_2017=False, years_of_service=Decimal("6"), qualifying_small_employer=False,
        qualifying_hours_in_month=Decimal("132"), period_label="2026-01",
    )
    row = service.accrue_pr_monthly_leave(
        db, organization.id, employee.id,
        hired_before_2017=False, years_of_service=Decimal("6"), qualifying_small_employer=False,
        qualifying_hours_in_month=Decimal("132"), period_label="2026-02",
    )
    assert row.leave_balances["vacation"]["total"] == 2.0
    assert row.leave_balances["sick"]["total"] == 2.0
    assert row.period_label == "2026-02"


def test_accrue_never_resets_a_manually_edited_used_count(db, organization):
    """An Org Admin's own edits to "used" (e.g. via bulk_save_leaves) must
    survive a later accrual call — accrual only ever touches "total"."""
    employee = _make_employee(db, organization.id)
    existing = PayrollLeaveAllocation(
        organization_id=organization.id, employee_id=employee.id,
        leave_balances={"vacation": {"used": 3, "total": 5}, "sick": {"used": 1, "total": 2}},
    )
    db.add(existing)
    db.commit()

    row = service.accrue_pr_monthly_leave(
        db, organization.id, employee.id,
        hired_before_2017=False, years_of_service=Decimal("6"), qualifying_small_employer=False,
        qualifying_hours_in_month=Decimal("132"),
    )
    assert row.leave_balances["vacation"]["used"] == 3
    assert row.leave_balances["vacation"]["total"] == 6.0  # 5 + 1
    assert row.leave_balances["sick"]["used"] == 1
    assert row.leave_balances["sick"]["total"] == 3.0  # 2 + 1


def test_accrue_preserves_other_leave_types_already_present(db, organization):
    """This is Puerto Rico's own accrual — it must never clobber a "paid"/
    "unpaid"/"compOff" balance any other leave-management flow already
    populated for this employee."""
    employee = _make_employee(db, organization.id)
    existing = PayrollLeaveAllocation(
        organization_id=organization.id, employee_id=employee.id,
        leave_balances={"paid": {"used": 2, "total": 20}, "compOff": {"used": 0, "total": 5}},
    )
    db.add(existing)
    db.commit()

    row = service.accrue_pr_monthly_leave(
        db, organization.id, employee.id,
        hired_before_2017=False, years_of_service=Decimal("6"), qualifying_small_employer=False,
        qualifying_hours_in_month=Decimal("132"),
    )
    assert row.leave_balances["paid"] == {"used": 2, "total": 20}
    assert row.leave_balances["compOff"] == {"used": 0, "total": 5}
    assert row.leave_balances["vacation"]["total"] == 1.0


def test_accrue_pre_2017_cohort_flat_rate(db, organization):
    employee = _make_employee(db, organization.id)
    row = service.accrue_pr_monthly_leave(
        db, organization.id, employee.id,
        hired_before_2017=True, years_of_service=Decimal("20"), qualifying_small_employer=False,
        qualifying_hours_in_month=Decimal("130"),
    )
    assert row.leave_balances["vacation"]["total"] == 1.25


def test_accrue_unknown_employee_raises(db, organization):
    with pytest.raises(NotFoundException):
        service.accrue_pr_monthly_leave(
            db, organization.id, 999999,
            hired_before_2017=False, years_of_service=Decimal("1"), qualifying_small_employer=False,
            qualifying_hours_in_month=Decimal("200"),
        )
