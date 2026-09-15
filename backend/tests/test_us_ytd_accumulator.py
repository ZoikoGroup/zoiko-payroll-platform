"""
tests/test_us_ytd_accumulator.py
----------------------------------
DB-level coverage for the US Social Security/FUTA/Additional Medicare
real-YTD-accumulator wiring (service.py's _load_us_ytd/
_upsert_us_ytd_accumulator, PayrollYtdAccumulator) — gap-closure Plan
Phase 2a. Mirrors tests/test_ca_ytd_accumulator.py's exact pattern.
Calculation correctness itself (the "remaining room" math) is covered
engine-side in test_engine_standard.py's test_us_ytd_* tests — these
tests are about the DB read/write plumbing and the rollout-switch
dormancy contract, not the arithmetic.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee, PayrollYtdAccumulator
from app.modules.payroll.engine.base import PayrollResult
import app.modules.payroll.engine.countries.shared as shared


def _make_us_employee(db, org_id, code="USE1", work_state=None):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="US", work_state=work_state, ctc=Decimal("96000"),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


@pytest.fixture(autouse=True)
def _restore_ytd_switch():
    """The rollout switch is a plain module-level set — tests that flip it
    (even though "US" is already enabled by default) must not leak any
    change into other tests, same pattern test_ca_ytd_accumulator.py
    already uses."""
    original = set(shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES)
    yield
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.clear()
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.update(original)


def test_load_us_ytd_empty_when_switch_off(db, organization):
    emp = _make_us_employee(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.discard("US")
    result = service._load_us_ytd(db, emp.id, date(2026, 6, 1))
    assert result == {}


def test_load_us_ytd_defaults_to_zero_for_fresh_employee(db, organization):
    emp = _make_us_employee(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("US")
    result = service._load_us_ytd(db, emp.id, date(2026, 6, 1))
    assert result == dict(
        ytd_ss_wages_before=Decimal("0"), ytd_futa_wages_before=Decimal("0"),
        ytd_medicare_wages_before=Decimal("0"),
    )


def test_upsert_then_load_round_trips_real_values(db, organization):
    emp = _make_us_employee(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("US")
    result = PayrollResult(
        gross=Decimal("15000"), basic=Decimal("15000"),
        ytd_ss_wages_after=Decimal("150000.00"), ytd_futa_wages_after=Decimal("7000.00"),
        ytd_medicare_wages_after=Decimal("150000.00"),
    )
    service._upsert_us_ytd_accumulator(db, emp.id, date(2026, 6, 1), result, payslip_id=None)
    db.commit()

    loaded = service._load_us_ytd(db, emp.id, date(2026, 7, 1))
    assert loaded == dict(
        ytd_ss_wages_before=Decimal("150000.00"), ytd_futa_wages_before=Decimal("7000.00"),
        ytd_medicare_wages_before=Decimal("150000.00"),
    )


def test_upsert_updates_existing_row_not_duplicate(db, organization):
    emp = _make_us_employee(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("US")
    first = PayrollResult(
        gross=Decimal("15000"), basic=Decimal("15000"),
        ytd_ss_wages_after=Decimal("15000.00"), ytd_futa_wages_after=Decimal("7000.00"),
        ytd_medicare_wages_after=Decimal("15000.00"),
    )
    service._upsert_us_ytd_accumulator(db, emp.id, date(2026, 1, 1), first, payslip_id=None)
    second = PayrollResult(
        gross=Decimal("15000"), basic=Decimal("15000"),
        ytd_ss_wages_after=Decimal("30000.00"), ytd_futa_wages_after=Decimal("7000.00"),
        ytd_medicare_wages_after=Decimal("30000.00"),
    )
    service._upsert_us_ytd_accumulator(db, emp.id, date(2026, 2, 1), second, payslip_id=None)
    db.commit()

    rows = db.query(PayrollYtdAccumulator).filter(
        PayrollYtdAccumulator.employee_id == emp.id, PayrollYtdAccumulator.tax_component == "social_security",
    ).all()
    assert len(rows) == 1  # updated in place, not a second row
    assert rows[0].ytd_taxable_wages == Decimal("30000.00")


def test_upsert_noop_when_result_carries_no_ytd(db, organization):
    emp = _make_us_employee(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("US")
    dormant_result = PayrollResult(gross=Decimal("8000"), basic=Decimal("8000"))  # ytd_* all None (default)
    service._upsert_us_ytd_accumulator(db, emp.id, date(2026, 6, 1), dormant_result, payslip_id=None)
    db.commit()
    count = db.query(PayrollYtdAccumulator).filter(PayrollYtdAccumulator.employee_id == emp.id).count()
    assert count == 0


def test_us_ytd_tax_year_is_calendar_year_no_state_variant():
    """Federal-only (SS/FUTA/Additional Medicare have no per-state
    variant), unlike Canada's own CA/CA-QC prefix split — a single
    "US-CY-<year>" key regardless of the employee's work_state."""
    assert service._us_ytd_tax_year(date(2026, 6, 1)) == "US-CY-2026"
    assert service._us_ytd_tax_year(date(2026, 1, 1)) == "US-CY-2026"
