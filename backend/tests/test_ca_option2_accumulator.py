"""
tests/test_ca_option2_accumulator.py
----------------------------------------
Service-layer coverage for Canada Option 2 cumulative-averaging income
tax withholding's PayrollYtdAccumulator read/write (ZP-TAX-CA-2026-001
§7, gap-closure Phase 9, 2026-09-11) — service._load_ca_option2_ytd/
_upsert_ca_option2_ytd_accumulator specifically. The underlying
calculation formula itself is covered by test_engine_standard.py's
option2 tests; this file proves the DB round-trip (get-or-create,
component keys, dormancy) works the same way CPP/EI's own accumulator
already does.
"""

from datetime import date
from decimal import Decimal

from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee
import app.modules.payroll.engine.countries.shared as shared


def _make_employee(db, org_id, code="OPT2E1"):
    emp = PayrollEmployee(organization_id=org_id, employee_code=code, name=f"Employee {code}", country_code="CA")
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def test_load_ca_option2_ytd_dormant_by_default(db, organization):
    shared._CA_OPTION2_WITHHOLDING_ENABLED_COUNTRIES.discard("CA")  # simulate the switch OFF
    emp = _make_employee(db, organization.id)
    result = service._load_ca_option2_ytd(db, emp.id, date(2026, 6, 30))
    assert result == {}


def test_load_ca_option2_ytd_defaults_to_zero_when_switch_on_and_no_row_exists(db, organization):
    shared._CA_OPTION2_WITHHOLDING_ENABLED_COUNTRIES.add("CA")
    try:
        emp = _make_employee(db, organization.id)
        result = service._load_ca_option2_ytd(db, emp.id, date(2026, 6, 30))
        assert result == {
            "option2_cumulative_gross_before": Decimal("0"),
            "option2_periods_elapsed_before": 0,
            "option2_federal_tax_withheld_before": Decimal("0"),
            "option2_provincial_tax_withheld_before": Decimal("0"),
        }
    finally:
        shared._CA_OPTION2_WITHHOLDING_ENABLED_COUNTRIES.discard("CA")


def test_upsert_then_load_round_trips_correctly(db, organization):
    shared._CA_OPTION2_WITHHOLDING_ENABLED_COUNTRIES.add("CA")
    try:
        emp = _make_employee(db, organization.id)

        class _FakeResult:
            option2_cumulative_gross_after = Decimal("8000")
            option2_periods_elapsed_after = 2
            option2_federal_tax_withheld_after = Decimal("650.00")
            option2_provincial_tax_withheld_after = Decimal("310.00")

        service._upsert_ca_option2_ytd_accumulator(db, emp.id, date(2026, 6, 30), None, _FakeResult())
        db.commit()

        loaded = service._load_ca_option2_ytd(db, emp.id, date(2026, 7, 31))
        assert loaded["option2_cumulative_gross_before"] == Decimal("8000")
        assert loaded["option2_periods_elapsed_before"] == 2
        assert loaded["option2_federal_tax_withheld_before"] == Decimal("650.00")
        assert loaded["option2_provincial_tax_withheld_before"] == Decimal("310.00")
    finally:
        shared._CA_OPTION2_WITHHOLDING_ENABLED_COUNTRIES.discard("CA")


def test_upsert_is_noop_when_result_carries_no_option2_state(db, organization):
    emp = _make_employee(db, organization.id)

    class _FakeResult:
        option2_cumulative_gross_after = None

    # Must not raise, must not create any row.
    service._upsert_ca_option2_ytd_accumulator(db, emp.id, date(2026, 6, 30), None, _FakeResult())
    db.commit()

    shared._CA_OPTION2_WITHHOLDING_ENABLED_COUNTRIES.add("CA")
    try:
        loaded = service._load_ca_option2_ytd(db, emp.id, date(2026, 6, 30))
        assert loaded["option2_cumulative_gross_before"] == Decimal("0")
    finally:
        shared._CA_OPTION2_WITHHOLDING_ENABLED_COUNTRIES.discard("CA")


def test_load_ca_option2_ytd_scopes_by_tax_year(db, organization):
    shared._CA_OPTION2_WITHHOLDING_ENABLED_COUNTRIES.add("CA")
    try:
        emp = _make_employee(db, organization.id)

        class _FakeResult:
            option2_cumulative_gross_after = Decimal("5000")
            option2_periods_elapsed_after = 1
            option2_federal_tax_withheld_after = Decimal("400.00")
            option2_provincial_tax_withheld_after = Decimal("100.00")

        service._upsert_ca_option2_ytd_accumulator(db, emp.id, date(2026, 12, 31), None, _FakeResult())
        db.commit()

        # A new calendar year must start fresh, not carry over 2026's totals.
        loaded_2027 = service._load_ca_option2_ytd(db, emp.id, date(2027, 1, 31))
        assert loaded_2027["option2_cumulative_gross_before"] == Decimal("0")
        assert loaded_2027["option2_periods_elapsed_before"] == 0

        loaded_2026 = service._load_ca_option2_ytd(db, emp.id, date(2026, 12, 31))
        assert loaded_2026["option2_cumulative_gross_before"] == Decimal("5000")
    finally:
        shared._CA_OPTION2_WITHHOLDING_ENABLED_COUNTRIES.discard("CA")
