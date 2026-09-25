"""
tests/test_pr_bonus_year_accumulator.py
-------------------------------------------
Coverage for the Puerto Rico Christmas Bonus bonus-year accumulator
(PR-032) — service.accrue_pr_bonus_year_totals/get_pr_bonus_year_totals/
calculate_pr_christmas_bonus_from_accumulator. Reuses the SAME
PayrollYtdAccumulator table every other wage-base tracker in this build
uses, with its own Oct 1-Sep 30 "PR-BONUS-<year>" pseudo-tax-year key
(never a calendar year).
"""
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import NotFoundException
from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee


def _make_employee(db, organization_id, code="PRB1", name="Maria Rivera"):
    employee = PayrollEmployee(organization_id=organization_id, employee_code=code, name=name)
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


def test_bonus_year_key_before_october_belongs_to_the_year_ending_that_september(db, organization):
    """Feb 2026 -> the bonus year that ends Sep 30, 2026 -> "PR-BONUS-2026"."""
    employee = _make_employee(db, organization.id)
    result = service.accrue_pr_bonus_year_totals(
        db, organization.id, employee.id, date(2026, 2, 15), Decimal("4000"), Decimal("173"),
    )
    assert result["bonus_year"] == "PR-BONUS-2026"


def test_bonus_year_key_in_october_belongs_to_the_new_year_starting_that_october(db, organization):
    """Oct 15, 2026 -> the NEW bonus year (ends Sep 30, 2027) -> "PR-BONUS-2027"."""
    employee = _make_employee(db, organization.id)
    result = service.accrue_pr_bonus_year_totals(
        db, organization.id, employee.id, date(2026, 10, 15), Decimal("4000"), Decimal("173"),
    )
    assert result["bonus_year"] == "PR-BONUS-2027"


def test_accrual_is_additive_across_pay_periods(db, organization):
    employee = _make_employee(db, organization.id)
    service.accrue_pr_bonus_year_totals(db, organization.id, employee.id, date(2026, 2, 15), Decimal("4000"), Decimal("173"))
    result = service.accrue_pr_bonus_year_totals(db, organization.id, employee.id, date(2026, 3, 15), Decimal("4000"), Decimal("173"))
    assert result["cumulative_wages"] == Decimal("8000")
    assert result["cumulative_hours"] == Decimal("346")


def test_accrual_across_the_bonus_year_boundary_does_not_mix_years(db, organization):
    """A period in the OLD bonus year (Sep 2026) and one in the NEW bonus
    year (Oct 2026) must accumulate into two genuinely separate totals."""
    employee = _make_employee(db, organization.id)
    service.accrue_pr_bonus_year_totals(db, organization.id, employee.id, date(2026, 9, 15), Decimal("4000"), Decimal("173"))
    service.accrue_pr_bonus_year_totals(db, organization.id, employee.id, date(2026, 10, 15), Decimal("5000"), Decimal("180"))

    old_year = service.get_pr_bonus_year_totals(db, organization.id, employee.id, date(2026, 9, 15))
    new_year = service.get_pr_bonus_year_totals(db, organization.id, employee.id, date(2026, 10, 15))
    assert old_year["bonus_year"] == "PR-BONUS-2026"
    assert old_year["cumulative_wages"] == Decimal("4000")
    assert new_year["bonus_year"] == "PR-BONUS-2027"
    assert new_year["cumulative_wages"] == Decimal("5000")


def test_get_totals_is_zero_when_nothing_accrued_yet(db, organization):
    employee = _make_employee(db, organization.id)
    totals = service.get_pr_bonus_year_totals(db, organization.id, employee.id, date(2026, 2, 15))
    assert totals["cumulative_wages"] == Decimal("0")
    assert totals["cumulative_hours"] == Decimal("0")


def test_calculate_from_accumulator_matches_fixture_f5(db, organization):
    """Same numbers as ZP-PR-ENG-001 fixture F5, but sourced from a real
    accrued accumulator instead of caller-supplied totals."""
    employee = _make_employee(db, organization.id)
    # Accrue up to the fixture's own $40,000/1,600-hour totals across a
    # few periods.
    service.accrue_pr_bonus_year_totals(db, organization.id, employee.id, date(2026, 2, 15), Decimal("20000"), Decimal("800"))
    service.accrue_pr_bonus_year_totals(db, organization.id, employee.id, date(2026, 3, 15), Decimal("20000"), Decimal("800"))

    result = service.calculate_pr_christmas_bonus_from_accumulator(
        db, organization.id, employee.id, date(2026, 3, 15),
        hired_before_2017=False, employer_size_over_threshold=True, is_first_year=False,
    )
    assert result["eligible"] is True
    assert result["bonus_amount"] == Decimal("600.00")
    assert result["cumulative_wages"] == Decimal("40000")
    assert result["cumulative_hours"] == Decimal("1600")


def test_calculate_from_accumulator_first_year_matches_fixture_f6(db, organization):
    employee = _make_employee(db, organization.id)
    service.accrue_pr_bonus_year_totals(db, organization.id, employee.id, date(2026, 2, 15), Decimal("40000"), Decimal("1600"))

    result = service.calculate_pr_christmas_bonus_from_accumulator(
        db, organization.id, employee.id, date(2026, 2, 15),
        hired_before_2017=False, employer_size_over_threshold=True, is_first_year=True,
    )
    assert result["bonus_amount"] == Decimal("300.00")


def test_accrue_bonus_year_unknown_employee_raises(db, organization):
    with pytest.raises(NotFoundException):
        service.accrue_pr_bonus_year_totals(db, organization.id, 999999, date(2026, 2, 15), Decimal("4000"), Decimal("173"))
