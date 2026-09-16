"""
tests/test_au_sg_ytd_accumulator.py
--------------------------------------
DB-level coverage for the Australia Superannuation Guarantee Maximum
Contribution Base real-YTD-accumulator wiring (service.py's
_load_au_sg_ytd/_upsert_au_sg_ytd_accumulator, PayrollYtdAccumulator) and
the Payday Super liability record (create_au_sg_liability,
SuperGuaranteeLiability) — ZP-TAX-AU-2026-27-001 §10, Payday Super
Phase 2. Mirrors tests/test_us_ytd_accumulator.py's exact pattern.
Calculation correctness itself (the "remaining MCB room" math) is
covered engine-side in test_engine_standard.py's test_australia_sg_*
tests — these tests are about the DB read/write plumbing, the
rollout-switch dormancy contract, and the liability record, not the
arithmetic.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee, PayrollYtdAccumulator, SuperGuaranteeLiability
from app.modules.payroll.engine.base import PayrollResult
import app.modules.payroll.engine.countries.shared as shared


def _make_au_employee(db, org_id, code="AUE1"):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="AU", ctc=Decimal("96000"),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


@pytest.fixture(autouse=True)
def _restore_ytd_switch():
    """The rollout switch is a plain module-level set — tests that flip it
    (even though "AU" is already enabled by default) must not leak any
    change into other tests, same pattern test_us_ytd_accumulator.py
    already uses."""
    original = set(shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES)
    yield
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.clear()
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.update(original)


def test_load_au_sg_ytd_empty_when_switch_off(db, organization):
    emp = _make_au_employee(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.discard("AU")
    result = service._load_au_sg_ytd(db, emp.id, date(2026, 8, 1))
    assert result == {}


def test_load_au_sg_ytd_defaults_to_zero_for_fresh_employee(db, organization):
    emp = _make_au_employee(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("AU")
    result = service._load_au_sg_ytd(db, emp.id, date(2026, 8, 1))
    assert result == dict(ytd_sg_qualifying_earnings_before=Decimal("0"))


def test_upsert_then_load_round_trips_real_values(db, organization):
    emp = _make_au_employee(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("AU")
    result = PayrollResult(
        gross=Decimal("10000"), basic=Decimal("10000"),
        ytd_sg_qualifying_earnings_after=Decimal("60000.00"),
    )
    service._upsert_au_sg_ytd_accumulator(db, emp.id, date(2026, 8, 1), result, payslip_id=None)
    db.commit()

    loaded = service._load_au_sg_ytd(db, emp.id, date(2026, 9, 1))
    assert loaded == dict(ytd_sg_qualifying_earnings_before=Decimal("60000.00"))


def test_upsert_updates_existing_row_not_duplicate(db, organization):
    emp = _make_au_employee(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("AU")
    first = PayrollResult(gross=Decimal("10000"), basic=Decimal("10000"), ytd_sg_qualifying_earnings_after=Decimal("10000.00"))
    service._upsert_au_sg_ytd_accumulator(db, emp.id, date(2026, 7, 1), first, payslip_id=None)
    second = PayrollResult(gross=Decimal("10000"), basic=Decimal("10000"), ytd_sg_qualifying_earnings_after=Decimal("20000.00"))
    service._upsert_au_sg_ytd_accumulator(db, emp.id, date(2026, 8, 1), second, payslip_id=None)
    db.commit()

    rows = db.query(PayrollYtdAccumulator).filter(
        PayrollYtdAccumulator.employee_id == emp.id, PayrollYtdAccumulator.tax_component == "au_sg_qualifying_earnings",
    ).all()
    assert len(rows) == 1  # updated in place, not a second row
    assert rows[0].ytd_taxable_wages == Decimal("20000.00")
    assert rows[0].tax_year == "AU-FY-2026-27"


def test_upsert_noop_when_result_carries_no_ytd(db, organization):
    emp = _make_au_employee(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("AU")
    dormant_result = PayrollResult(gross=Decimal("8000"), basic=Decimal("8000"))  # ytd_* all None (default)
    service._upsert_au_sg_ytd_accumulator(db, emp.id, date(2026, 8, 1), dormant_result, payslip_id=None)
    db.commit()
    count = db.query(PayrollYtdAccumulator).filter(PayrollYtdAccumulator.employee_id == emp.id).count()
    assert count == 0


def test_au_ytd_tax_year_is_australian_financial_year():
    # 1 July - 30 June, NOT a calendar year.
    assert service._au_ytd_tax_year(date(2026, 7, 1)) == "AU-FY-2026-27"
    assert service._au_ytd_tax_year(date(2027, 6, 30)) == "AU-FY-2026-27"
    assert service._au_ytd_tax_year(date(2027, 7, 1)) == "AU-FY-2027-28"
    assert service._au_ytd_tax_year(date(2026, 6, 30)) == "AU-FY-2025-26"


def test_add_business_days_skips_weekends():
    # Thursday 2026-08-06 + 7 business days: Fri(1) Mon(2) Tue(3) Wed(4)
    # Thu(5) Fri(6) Mon(7) -> 2026-08-17.
    assert service._add_business_days(date(2026, 8, 6), 7) == date(2026, 8, 17)


# ── Payday Super liability record (§10) ──────────────────────────────────

def test_create_au_sg_liability_sets_seven_business_day_deadline(db, organization):
    emp = _make_au_employee(db, organization.id)
    liability = service.create_au_sg_liability(
        db, organization.id, emp.id, date(2026, 8, 6),
        qualifying_earnings=Decimal("10000.00"), sg_rate_pct=Decimal("12.00"), sg_amount=Decimal("1200.00"),
        ytd_qualifying_earnings_after=Decimal("60000.00"), mcb_reached=False,
    )
    db.commit()
    assert liability.id is not None
    assert liability.status == "PENDING"
    assert liability.fund_receipt_deadline == date(2026, 8, 17)
    assert liability.mcb_reached is False
    assert liability.sg_amount == Decimal("1200.00")


def test_create_au_sg_liability_records_mcb_reached_flag(db, organization):
    emp = _make_au_employee(db, organization.id)
    liability = service.create_au_sg_liability(
        db, organization.id, emp.id, date(2026, 8, 6),
        qualifying_earnings=Decimal("1280.00"), sg_rate_pct=Decimal("12.00"), sg_amount=Decimal("147.20"),
        ytd_qualifying_earnings_after=Decimal("260280.00"), mcb_reached=True,
    )
    db.commit()
    assert liability.mcb_reached is True


def test_create_au_sg_liability_persists_one_row_per_payslip(db, organization):
    emp = _make_au_employee(db, organization.id)
    service.create_au_sg_liability(
        db, organization.id, emp.id, date(2026, 7, 1),
        qualifying_earnings=Decimal("10000"), sg_rate_pct=Decimal("12.00"), sg_amount=Decimal("1200.00"),
    )
    service.create_au_sg_liability(
        db, organization.id, emp.id, date(2026, 8, 1),
        qualifying_earnings=Decimal("10000"), sg_rate_pct=Decimal("12.00"), sg_amount=Decimal("1200.00"),
    )
    db.commit()
    count = db.query(SuperGuaranteeLiability).filter(SuperGuaranteeLiability.employee_id == emp.id).count()
    assert count == 2  # one per payday, never merged/overwritten
