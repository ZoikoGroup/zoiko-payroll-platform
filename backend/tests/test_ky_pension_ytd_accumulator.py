"""
tests/test_ky_pension_ytd_accumulator.py
---------------------------------------------
DB-level coverage for the Cayman Islands mandatory-pension CI$87,000
annual-cap real-YTD-accumulator wiring (service.py's
_load_ky_pension_ytd/_upsert_ky_pension_ytd_accumulator,
PayrollYtdAccumulator) — KY-008. Mirrors tests/test_au_sg_ytd_
accumulator.py's exact pattern. Calculation correctness itself (the
"remaining cap room" math) is covered engine-side in
test_cayman_islands.py — these tests are about the DB read/write
plumbing and the rollout-switch dormancy contract.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee, PayrollYtdAccumulator
from app.modules.payroll.engine.base import PayrollResult
import app.modules.payroll.engine.countries.shared as shared


def _make_ky_employee(db, org_id, code="KYE1"):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="KY", ctc=Decimal("72000"),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


@pytest.fixture(autouse=True)
def _restore_ytd_switch():
    """The rollout switch is a plain module-level set — tests that flip it
    (even though "KY" is already enabled by default) must not leak any
    change into other tests, same pattern test_au_sg_ytd_accumulator.py
    already uses."""
    original = set(shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES)
    yield
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.clear()
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.update(original)


def test_load_ky_pension_ytd_empty_when_switch_off(db, organization):
    emp = _make_ky_employee(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.discard("KY")
    result = service._load_ky_pension_ytd(db, emp.id, date(2026, 8, 1))
    assert result == {}


def test_load_ky_pension_ytd_defaults_to_zero_for_fresh_employee(db, organization):
    emp = _make_ky_employee(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("KY")
    result = service._load_ky_pension_ytd(db, emp.id, date(2026, 2, 1))
    assert result == dict(ytd_ky_mandatory_pensionable_earnings_before=Decimal("0"))


def test_upsert_then_load_round_trips_real_values(db, organization):
    emp = _make_ky_employee(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("KY")
    result = PayrollResult(
        gross=Decimal("6000"), basic=Decimal("6000"),
        ytd_ky_mandatory_pensionable_earnings_after=Decimal("48000.00"),
    )
    service._upsert_ky_pension_ytd_accumulator(db, emp.id, date(2026, 8, 1), result, payslip_id=None)
    db.commit()

    loaded = service._load_ky_pension_ytd(db, emp.id, date(2026, 9, 1))
    assert loaded == dict(ytd_ky_mandatory_pensionable_earnings_before=Decimal("48000.00"))


def test_upsert_updates_existing_row_not_duplicate(db, organization):
    emp = _make_ky_employee(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("KY")
    first = PayrollResult(gross=Decimal("6000"), basic=Decimal("6000"), ytd_ky_mandatory_pensionable_earnings_after=Decimal("6000.00"))
    service._upsert_ky_pension_ytd_accumulator(db, emp.id, date(2026, 1, 1), first, payslip_id=None)
    second = PayrollResult(gross=Decimal("6000"), basic=Decimal("6000"), ytd_ky_mandatory_pensionable_earnings_after=Decimal("12000.00"))
    service._upsert_ky_pension_ytd_accumulator(db, emp.id, date(2026, 2, 1), second, payslip_id=None)
    db.commit()

    rows = db.query(PayrollYtdAccumulator).filter(
        PayrollYtdAccumulator.employee_id == emp.id, PayrollYtdAccumulator.tax_component == "ky_mandatory_pensionable_earnings",
    ).all()
    assert len(rows) == 1  # updated in place, not a second row
    assert rows[0].ytd_taxable_wages == Decimal("12000.00")
    assert rows[0].tax_year == "KY-CY-2026"


def test_upsert_noop_when_result_carries_no_ytd(db, organization):
    emp = _make_ky_employee(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("KY")
    dormant_result = PayrollResult(gross=Decimal("6000"), basic=Decimal("6000"))  # ytd_* all None (default)
    service._upsert_ky_pension_ytd_accumulator(db, emp.id, date(2026, 8, 1), dormant_result, payslip_id=None)
    db.commit()
    count = db.query(PayrollYtdAccumulator).filter(PayrollYtdAccumulator.employee_id == emp.id).count()
    assert count == 0


def test_ky_ytd_tax_year_is_calendar_year_not_financial_year():
    # Calendar year (KY-008), unlike AU's July-June financial year.
    assert service._ky_ytd_tax_year(date(2026, 1, 1)) == "KY-CY-2026"
    assert service._ky_ytd_tax_year(date(2026, 12, 31)) == "KY-CY-2026"
    assert service._ky_ytd_tax_year(date(2027, 1, 1)) == "KY-CY-2027"


def test_cap_crossing_end_to_end_via_real_accumulator(db, organization):
    """Fixture F2 (ZP-KY-ENG-001 §14): YTD mandatory pensionable earnings
    already at 80,000 of the 87,000 annual cap; this period's earnings are
    10,000 — only 7,000 is mandatory. Proves the full read -> calculate ->
    write chain, not just the engine-level dataclass test in
    test_cayman_islands.py."""
    from app.modules.payroll.engine.countries import cayman_islands

    emp = _make_ky_employee(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("KY")

    seed = PayrollResult(gross=Decimal("80000"), basic=Decimal("80000"), ytd_ky_mandatory_pensionable_earnings_after=Decimal("80000"))
    service._upsert_ky_pension_ytd_accumulator(db, emp.id, date(2026, 10, 1), seed, payslip_id=None)
    db.commit()

    ytd_kwargs = service._load_ky_pension_ytd(db, emp.id, date(2026, 11, 1))
    from app.modules.payroll.engine.base import PayrollContext

    ctx = PayrollContext(gross=Decimal("10000"), basic=Decimal("10000"), country="KY", rate_map={}, slabs=[], **ytd_kwargs)
    result = cayman_islands.calculate(ctx)
    assert result["employee_pension"] == Decimal("350.00")   # 5% of 7,000 remaining
    assert result["employer_pension"] == Decimal("350.00")
    assert result["pension_cap_ytd_wired"] is True
    assert result["ytd_ky_mandatory_pensionable_earnings_after"] == Decimal("87000")


def _stub_business_code_generation(monkeypatch):
    """generate_payslips_for_run numbers payslips via generate_business_code,
    which needs a Postgres advisory lock the SQLite test DB can't provide —
    same stub tests/test_engine_calendar_days.py uses."""
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def test_generate_payslips_for_run_works_for_a_real_ky_employee(db, organization, monkeypatch):
    """Real end-to-end regression guard (2026-09-22): every earlier test in
    this file calls _load_ky_pension_ytd/_upsert_ky_pension_ytd_accumulator
    directly, or builds PayrollContext by hand — none of them go through
    build_context_from_employee(**ytd_inputs), the actual call every real
    payslip generation uses. That gap let a real bug ship and go
    undetected: build_context_from_employee had no
    ytd_ky_mandatory_pensionable_earnings_before parameter at all, so
    _load_ky_pension_ytd's returned dict, spread as **ytd_inputs, raised
    TypeError: got an unexpected keyword argument — meaning every real
    Cayman Islands employee's payroll (preview, generation, and manual
    payslip-item add) crashed outright. Fixed by adding the parameter to
    build_context_from_employee (engine/resolver.py) and threading it to
    PayrollContext. This test proves the real integration point, not just
    the accumulator plumbing in isolation."""
    from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem

    _stub_business_code_generation(monkeypatch)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("KY")

    emp = PayrollEmployee(
        organization_id=organization.id, employee_code="KY-E2E-1", name="Employee KY-E2E-1",
        country_code="KY", ctc=Decimal("72000"),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)

    run = PayrollRun(
        organization_id=organization.id, period_label="Aug 2026",
        period_start=date(2026, 8, 1), period_end=date(2026, 8, 31), pay_date=date(2026, 8, 31),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    service.generate_payslips_for_run(db, run, organization.id)

    item = db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id,
    ).first()
    assert item is not None
    # 72,000/12 = 6,000 monthly gross; 5% mandatory pension each side.
    assert item.employee_pension == Decimal("300.00")
    assert item.employer_pension == Decimal("300.00")

    # The write side must also have actually run (not silently skipped).
    accumulator = db.query(PayrollYtdAccumulator).filter(
        PayrollYtdAccumulator.employee_id == emp.id,
        PayrollYtdAccumulator.tax_component == service._KY_PENSION_YTD_COMPONENT,
    ).first()
    assert accumulator is not None
    assert accumulator.ytd_taxable_wages == Decimal("6000.00")
