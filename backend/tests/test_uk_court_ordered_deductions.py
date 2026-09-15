"""
tests/test_uk_court_ordered_deductions.py
--------------------------------------------
Coverage for service.py's UK Court-Ordered Deductions CRUD + calculator
(ZP-TAX-UK-2026-27-001 §17 gap-closure Part 8, 2026-09-09) — England &
Wales AEOs, Scottish arrestments, Northern Ireland orders. DB-
integration style: real CourtOrderedDeduction/PayrollEmployee/TaxSlab
rows, exercising the full resolution chain into uk.py's
calculate_court_ordered_deductions().
"""

from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee, TaxSlab


def _make_uk_employee(db, org_id, code="CO1"):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="UK", ctc=Decimal("60000"), pay_frequency="Monthly",
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _seed_aeo_ew_band(db, org_id, rate=Decimal("20")):
    db.add(TaxSlab(
        organization_id=org_id, jurisdiction_country="UK",
        min_amount=Decimal("0"), max_amount=None, rate_pct=rate,
        rate_label=f"{rate}%", tax_formula="Flat", rule_type="AEO_EW_STANDARD",
    ))
    db.commit()


def test_create_court_order_rejects_unknown_jurisdiction(db, organization):
    emp = _make_uk_employee(db, organization.id)
    with pytest.raises(BadRequestException):
        service.create_court_ordered_deduction(
            db, organization.id, emp.id, "WALES_ONLY", "AEO_PRIORITY", date(2026, 6, 1),
        )


def test_create_and_list_court_order(db, organization):
    emp = _make_uk_employee(db, organization.id)
    order = service.create_court_ordered_deduction(
        db, organization.id, emp.id, "ENGLAND_WALES", "AEO_PRIORITY", date(2026, 6, 1),
        court_reference="CR-001", fixed_deduction_amount=Decimal("150"),
    )
    assert order.status == "active"
    orders = service.list_court_ordered_deductions(db, organization.id, emp.id)
    assert len(orders) == 1
    assert orders[0].court_reference == "CR-001"


def test_set_court_order_status_cancels_without_deleting(db, organization):
    emp = _make_uk_employee(db, organization.id)
    order = service.create_court_ordered_deduction(
        db, organization.id, emp.id, "ENGLAND_WALES", "AEO_PRIORITY", date(2026, 6, 1),
        fixed_deduction_amount=Decimal("150"),
    )
    updated = service.set_court_ordered_deduction_status(db, organization.id, emp.id, order.id, "cancelled")
    assert updated.status == "cancelled"
    # Still present in the record, not hard-deleted.
    all_orders = service.list_court_ordered_deductions(db, organization.id, emp.id)
    assert len(all_orders) == 1


def test_set_court_order_status_rejects_unknown_status(db, organization):
    emp = _make_uk_employee(db, organization.id)
    order = service.create_court_ordered_deduction(
        db, organization.id, emp.id, "ENGLAND_WALES", "AEO_PRIORITY", date(2026, 6, 1),
        fixed_deduction_amount=Decimal("150"),
    )
    with pytest.raises(BadRequestException):
        service.set_court_ordered_deduction_status(db, organization.id, emp.id, order.id, "revoked")


def test_set_court_order_status_missing_order_raises(db, organization):
    emp = _make_uk_employee(db, organization.id)
    with pytest.raises(NotFoundException):
        service.set_court_ordered_deduction_status(db, organization.id, emp.id, 999999, "cancelled")


def test_calculate_rejects_non_uk_employee(db, organization):
    emp = PayrollEmployee(
        organization_id=organization.id, employee_code="US1", name="US Employee",
        country_code="US", ctc=Decimal("60000"),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    with pytest.raises(BadRequestException):
        service.calculate_uk_court_ordered_deductions(db, organization.id, emp.id, Decimal("2000"), "Monthly")


def test_calculate_uses_order_specific_fixed_amount(db, organization):
    emp = _make_uk_employee(db, organization.id)
    service.create_court_ordered_deduction(
        db, organization.id, emp.id, "ENGLAND_WALES", "AEO_PRIORITY", date(2026, 6, 1),
        fixed_deduction_amount=Decimal("150"),
    )
    result = service.calculate_uk_court_ordered_deductions(
        db, organization.id, emp.id, Decimal("2000"), "Monthly", as_of=date(2026, 6, 15),
    )
    assert result["total_deduction"] == Decimal("150")
    assert result["orders"][0]["eligible"] is True


def test_calculate_falls_back_to_band_table_when_no_order_specific_value(db, organization):
    emp = _make_uk_employee(db, organization.id)
    _seed_aeo_ew_band(db, organization.id, rate=Decimal("20"))
    service.create_court_ordered_deduction(
        db, organization.id, emp.id, "ENGLAND_WALES", "AEO_NON_PRIORITY", date(2026, 6, 1),
    )
    result = service.calculate_uk_court_ordered_deductions(
        db, organization.id, emp.id, Decimal("2000"), "Monthly", as_of=date(2026, 6, 15),
    )
    assert result["total_deduction"] == Decimal("400.00")


def test_calculate_fails_closed_with_no_order_specific_value_and_no_band_table(db, organization):
    emp = _make_uk_employee(db, organization.id)
    service.create_court_ordered_deduction(
        db, organization.id, emp.id, "ENGLAND_WALES", "AEO_NON_PRIORITY", date(2026, 6, 1),
    )
    result = service.calculate_uk_court_ordered_deductions(
        db, organization.id, emp.id, Decimal("2000"), "Monthly", as_of=date(2026, 6, 15),
    )
    assert result["total_deduction"] == Decimal("0")
    assert result["orders"][0]["eligible"] is False


def test_calculate_excludes_orders_outside_their_date_window(db, organization):
    emp = _make_uk_employee(db, organization.id)
    service.create_court_ordered_deduction(
        db, organization.id, emp.id, "ENGLAND_WALES", "AEO_PRIORITY",
        start_date=date(2026, 1, 1), end_date=date(2026, 3, 31),
        fixed_deduction_amount=Decimal("150"),
    )
    result = service.calculate_uk_court_ordered_deductions(
        db, organization.id, emp.id, Decimal("2000"), "Monthly", as_of=date(2026, 6, 15),
    )
    assert result["total_deduction"] == Decimal("0")
    assert result["orders"] == []


def test_calculate_excludes_cancelled_orders(db, organization):
    emp = _make_uk_employee(db, organization.id)
    order = service.create_court_ordered_deduction(
        db, organization.id, emp.id, "ENGLAND_WALES", "AEO_PRIORITY", date(2026, 6, 1),
        fixed_deduction_amount=Decimal("150"),
    )
    service.set_court_ordered_deduction_status(db, organization.id, emp.id, order.id, "cancelled")
    result = service.calculate_uk_court_ordered_deductions(
        db, organization.id, emp.id, Decimal("2000"), "Monthly", as_of=date(2026, 6, 15),
    )
    assert result["orders"] == []


def test_calculate_orders_by_priority_lowest_number_first(db, organization):
    emp = _make_uk_employee(db, organization.id)
    # Created out of priority order on purpose — the resolver must sort.
    service.create_court_ordered_deduction(
        db, organization.id, emp.id, "ENGLAND_WALES", "AEO_NON_PRIORITY", date(2026, 6, 1),
        priority=2, fixed_deduction_amount=Decimal("1800"),
    )
    service.create_court_ordered_deduction(
        db, organization.id, emp.id, "ENGLAND_WALES", "AEO_PRIORITY", date(2026, 6, 1),
        priority=1, fixed_deduction_amount=Decimal("300"),
    )
    result = service.calculate_uk_court_ordered_deductions(
        db, organization.id, emp.id, Decimal("2000"), "Monthly", as_of=date(2026, 6, 15),
    )
    # Priority-1 order (300) must be applied first, leaving only 1700 for
    # the priority-2 order (which asked for 1800).
    assert result["orders"][0]["deduction_amount"] == Decimal("300")
    assert result["orders"][1]["deduction_amount"] == Decimal("1700")
    assert result["total_deduction"] == Decimal("2000.00")
