"""
tests/test_uk_director_ni_ytd_accumulator.py
-----------------------------------------------
DB-level coverage for the UK Directors NIC real-YTD-accumulator wiring
(service.py's _load_uk_director_ytd/_upsert_uk_director_ytd_accumulator,
PayrollYtdAccumulator) — mirrors test_ca_ytd_accumulator.py's own
structure exactly. Calculation correctness itself (the annual-method/
alternative-method true-up math) is covered engine-side in
test_engine_standard.py's test_director_ni_* tests — these tests are
about the DB read/write plumbing and the shared rollout-switch dormancy
contract, not the arithmetic. Reuses Canada's existing
PayrollYtdAccumulator.ytd_tax_withheld column — the first real consumer
of it (Canada's own upsert never populates it).
"""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee, PayrollYtdAccumulator
from app.modules.payroll.engine.base import PayrollResult
import app.modules.payroll.engine.countries.shared as shared


def _make_uk_director(db, org_id, code="UKD1"):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="UK", ctc=Decimal("96000"), is_director=True,
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


@pytest.fixture(autouse=True)
def _restore_ytd_switch():
    """Same shared module-level set as Canada's own YTD switch (one
    switch, multiple countries) — must not leak between tests."""
    original = set(shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES)
    yield
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.clear()
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.update(original)


def test_load_uk_director_ytd_empty_when_switch_off(db, organization):
    emp = _make_uk_director(db, organization.id)
    assert "UK" not in shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES
    result = service._load_uk_director_ytd(db, emp.id, date(2026, 6, 1))
    assert result == {}


def test_load_uk_director_ytd_empty_for_fresh_employee(db, organization):
    emp = _make_uk_director(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("UK")
    result = service._load_uk_director_ytd(db, emp.id, date(2026, 6, 1))
    # No accumulator row exists yet — never guesses/backfills a starting
    # value, same discipline as _load_ca_ytd.
    assert result == {}


def test_upsert_then_load_round_trips_real_values(db, organization):
    emp = _make_uk_director(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("UK")
    result = PayrollResult(
        gross=Decimal("5000"), basic=Decimal("5000"),
        ytd_director_ni_gross=Decimal("50000.00"),
        ytd_director_ni_employee_paid=Decimal("2994.40"),
        ytd_director_ni_employer_paid=Decimal("6210.00"),
    )
    service._upsert_uk_director_ytd_accumulator(db, emp.id, date(2026, 8, 1), result, payslip_id=None)
    db.commit()

    loaded = service._load_uk_director_ytd(db, emp.id, date(2026, 9, 1))
    assert loaded == dict(
        ytd_director_ni_gross=Decimal("50000.00"),
        ytd_director_ni_employee_paid=Decimal("2994.40"),
        ytd_director_ni_employer_paid=Decimal("6210.00"),
    )


def test_upsert_updates_existing_row_not_duplicate(db, organization):
    emp = _make_uk_director(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("UK")
    first = PayrollResult(
        gross=Decimal("5000"), basic=Decimal("5000"),
        ytd_director_ni_gross=Decimal("5000.00"),
        ytd_director_ni_employee_paid=Decimal("0"), ytd_director_ni_employer_paid=Decimal("0"),
    )
    service._upsert_uk_director_ytd_accumulator(db, emp.id, date(2026, 4, 10), first, payslip_id=None)
    second = PayrollResult(
        gross=Decimal("5000"), basic=Decimal("5000"),
        ytd_director_ni_gross=Decimal("10000.00"),
        ytd_director_ni_employee_paid=Decimal("0"), ytd_director_ni_employer_paid=Decimal("750.00"),
    )
    service._upsert_uk_director_ytd_accumulator(db, emp.id, date(2026, 5, 10), second, payslip_id=None)
    db.commit()

    rows = db.query(PayrollYtdAccumulator).filter(
        PayrollYtdAccumulator.employee_id == emp.id,
        PayrollYtdAccumulator.tax_component == "uk_director_ni_er",
    ).all()
    assert len(rows) == 1  # updated in place, not a second row
    assert rows[0].ytd_taxable_wages == Decimal("10000.00")
    assert rows[0].ytd_tax_withheld == Decimal("750.00")


def test_upsert_noop_when_result_carries_no_director_ytd(db, organization):
    emp = _make_uk_director(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("UK")
    dormant_result = PayrollResult(gross=Decimal("5000"), basic=Decimal("5000"))  # ytd_director_ni_* all None
    service._upsert_uk_director_ytd_accumulator(db, emp.id, date(2026, 6, 1), dormant_result, payslip_id=None)
    db.commit()
    count = db.query(PayrollYtdAccumulator).filter(
        PayrollYtdAccumulator.employee_id == emp.id,
        PayrollYtdAccumulator.tax_component.in_(("uk_director_ni_ee", "uk_director_ni_er")),
    ).count()
    assert count == 0


def test_uk_tax_year_boundary_before_and_after_6_april():
    # 5 April is still the OLD tax year; 6 April starts the new one.
    assert service._uk_tax_year(date(2026, 4, 5)) == "UK-TY-2025-26"
    assert service._uk_tax_year(date(2026, 4, 6)) == "UK-TY-2026-27"


def test_ca_and_uk_ytd_accumulators_never_collide(db, organization):
    # Same employee id space, same tax-year-ish string shape — confirm the
    # tax_component keys keep the two countries' accumulators fully
    # independent, same reasoning as Quebec's own collision test.
    emp = _make_uk_director(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.update({"UK", "CA"})
    uk_result = PayrollResult(
        gross=Decimal("5000"), basic=Decimal("5000"),
        ytd_director_ni_gross=Decimal("50000.00"),
        ytd_director_ni_employee_paid=Decimal("2994.40"), ytd_director_ni_employer_paid=Decimal("6210.00"),
    )
    service._upsert_uk_director_ytd_accumulator(db, emp.id, date(2026, 8, 1), uk_result, payslip_id=None)
    ca_result = PayrollResult(
        gross=Decimal("5000"), basic=Decimal("5000"),
        ytd_pensionable_earnings=Decimal("30000.00"), ytd_cpp2_pensionable_earnings=Decimal("0"),
        ytd_insurable_earnings=Decimal("30000.00"), ytd_basic_exemption_used=Decimal("2000.00"),
    )
    service._upsert_ca_ytd_accumulator(db, emp.id, date(2026, 6, 1), None, ca_result, payslip_id=None)
    db.commit()

    uk_loaded = service._load_uk_director_ytd(db, emp.id, date(2026, 9, 1))
    ca_loaded = service._load_ca_ytd(db, emp.id, date(2026, 7, 1), None)
    assert uk_loaded["ytd_director_ni_gross"] == Decimal("50000.00")
    assert ca_loaded["ytd_pensionable_earnings"] == Decimal("30000.00")
