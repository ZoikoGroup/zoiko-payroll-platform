"""
tests/test_ca_ytd_accumulator.py
----------------------------------
DB-level coverage for the Canada CPP/CPP2/EI real-YTD-accumulator wiring
(service.py's _load_ca_ytd/_upsert_ca_ytd_accumulator, PayrollYtdAccumulator).
Calculation correctness itself (the "remaining room" math) is covered
engine-side in test_engine_standard.py's test_canada_ytd_* tests — these
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


def _make_ca_employee(db, org_id, code="CAE1", work_state=None):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="CA", work_state=work_state, ctc=Decimal("96000"),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


@pytest.fixture(autouse=True)
def _restore_ytd_switch():
    """The rollout switch is a plain module-level set — tests that flip it
    on must not leak that into other tests (same pattern already used for
    _VALIDATION_ENABLED_COUNTRIES elsewhere in this suite)."""
    original = set(shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES)
    yield
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.clear()
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.update(original)


def test_load_ca_ytd_empty_when_switch_off(db, organization):
    emp = _make_ca_employee(db, organization.id)
    assert "CA" not in shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES
    result = service._load_ca_ytd(db, emp.id, date(2026, 6, 1), None)
    assert result == {}


def test_load_ca_ytd_defaults_to_zero_for_fresh_employee(db, organization):
    emp = _make_ca_employee(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    result = service._load_ca_ytd(db, emp.id, date(2026, 6, 1), None)
    assert result == dict(
        ytd_pensionable_earnings=Decimal("0"), ytd_cpp2_pensionable_earnings=Decimal("0"),
        ytd_insurable_earnings=Decimal("0"), ytd_basic_exemption_used=Decimal("0"),
    )


def test_upsert_then_load_round_trips_real_values(db, organization):
    emp = _make_ca_employee(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    result = PayrollResult(
        gross=Decimal("8000"), basic=Decimal("8000"),
        ytd_pensionable_earnings=Decimal("50000.00"), ytd_cpp2_pensionable_earnings=Decimal("0"),
        ytd_insurable_earnings=Decimal("40000.00"), ytd_basic_exemption_used=Decimal("1500.00"),
    )
    service._upsert_ca_ytd_accumulator(db, emp.id, date(2026, 6, 1), None, result, payslip_id=None)
    db.commit()

    loaded = service._load_ca_ytd(db, emp.id, date(2026, 7, 1), None)
    assert loaded == dict(
        ytd_pensionable_earnings=Decimal("50000.00"), ytd_cpp2_pensionable_earnings=Decimal("0"),
        ytd_insurable_earnings=Decimal("40000.00"), ytd_basic_exemption_used=Decimal("1500.00"),
    )


def test_upsert_updates_existing_row_not_duplicate(db, organization):
    emp = _make_ca_employee(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    first = PayrollResult(
        gross=Decimal("8000"), basic=Decimal("8000"),
        ytd_pensionable_earnings=Decimal("8000.00"), ytd_cpp2_pensionable_earnings=Decimal("0"),
        ytd_insurable_earnings=Decimal("8000.00"), ytd_basic_exemption_used=Decimal("100.00"),
    )
    service._upsert_ca_ytd_accumulator(db, emp.id, date(2026, 1, 1), None, first, payslip_id=None)
    second = PayrollResult(
        gross=Decimal("8000"), basic=Decimal("8000"),
        ytd_pensionable_earnings=Decimal("16000.00"), ytd_cpp2_pensionable_earnings=Decimal("0"),
        ytd_insurable_earnings=Decimal("16000.00"), ytd_basic_exemption_used=Decimal("200.00"),
    )
    service._upsert_ca_ytd_accumulator(db, emp.id, date(2026, 2, 1), None, second, payslip_id=None)
    db.commit()

    rows = db.query(PayrollYtdAccumulator).filter(
        PayrollYtdAccumulator.employee_id == emp.id, PayrollYtdAccumulator.tax_component == "cpp",
    ).all()
    assert len(rows) == 1  # updated in place, not a second row
    assert rows[0].ytd_taxable_wages == Decimal("16000.00")


def test_upsert_noop_when_result_carries_no_ytd(db, organization):
    emp = _make_ca_employee(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    dormant_result = PayrollResult(gross=Decimal("8000"), basic=Decimal("8000"))  # ytd_* all None (default)
    service._upsert_ca_ytd_accumulator(db, emp.id, date(2026, 6, 1), None, dormant_result, payslip_id=None)
    db.commit()
    count = db.query(PayrollYtdAccumulator).filter(PayrollYtdAccumulator.employee_id == emp.id).count()
    assert count == 0


def test_quebec_employee_uses_qc_prefixed_tax_year_and_components(db, organization):
    emp = _make_ca_employee(db, organization.id, work_state="QC")
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    result = PayrollResult(
        gross=Decimal("8000"), basic=Decimal("8000"),
        ytd_pensionable_earnings=Decimal("50000.00"), ytd_cpp2_pensionable_earnings=Decimal("0"),
        ytd_insurable_earnings=Decimal("40000.00"), ytd_basic_exemption_used=Decimal("1500.00"),
    )
    service._upsert_ca_ytd_accumulator(db, emp.id, date(2026, 6, 1), "QC", result, payslip_id=None)
    db.commit()
    row = db.query(PayrollYtdAccumulator).filter(
        PayrollYtdAccumulator.employee_id == emp.id, PayrollYtdAccumulator.tax_component == "qpp",
    ).first()
    assert row is not None
    assert row.tax_year == f"CA-QC-CY-2026"
    # A non-Quebec employee in the same tax year must not collide with
    # this row (different tax_component key ("cpp" vs "qpp") on its own,
    # plus a different tax_year prefix).
    non_qc = service._load_ca_ytd(db, emp.id, date(2026, 6, 1), None)  # work_state=None -> "cpp"/"CA-CY-2026"
    assert non_qc["ytd_pensionable_earnings"] == Decimal("0")  # no "cpp" row exists for this employee
