"""
tests/test_gy_paye_credit_ytd_accumulator.py
---------------------------------------------
DB-level coverage for the Guyana PAYE statutory credit ledger real-YTD-
accumulator wiring (service.py's _load_gy_paye_credit_ytd/
_upsert_gy_paye_credit_ytd_accumulator, PayrollYtdAccumulator) — GY-010.
Mirrors tests/test_ky_pension_ytd_accumulator.py's exact pattern,
INCLUDING its real end-to-end service.generate_payslips_for_run test from
the start (that gap — every earlier accumulator test only exercised the
read/write helpers in isolation or hand-built PayrollContext, never the
real build_context_from_employee integration point — is exactly what let
a real bug ship silently for Cayman Islands; see
test_ky_pension_ytd_accumulator.py's own newest test for the postmortem).
Calculation correctness itself (the credit-application math) is covered
engine-side in test_guyana.py.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee, PayrollYtdAccumulator, PayrollRun, PayslipItem, TaxSlab
from app.modules.payroll.engine.base import PayrollResult
import app.modules.payroll.engine.countries.shared as shared


def _seed_gy_paye_slabs(db, organization_id):
    """Org-scoped PAYE bands (ZP-GY-ENG-001 table, same values test_guyana.py
    passes by hand) — needed because generate_payslips_for_run resolves real
    rate_map/slabs from the database, unlike the engine-level unit tests in
    test_guyana.py which construct PayrollContext directly."""
    db.add_all([
        TaxSlab(
            organization_id=organization_id, jurisdiction_country="GY",
            min_amount=Decimal("0"), max_amount=Decimal("280000"), rate_pct=Decimal("25"), rate_label="PAYE 25%",
            tax_formula="",
        ),
        TaxSlab(
            organization_id=organization_id, jurisdiction_country="GY",
            min_amount=Decimal("280000"), max_amount=None, rate_pct=Decimal("35"), rate_label="PAYE 35%",
            tax_formula="",
        ),
    ])
    db.commit()


def _make_gy_employee(db, org_id, code="GYE1"):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="GY", ctc=Decimal("2400000"),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


@pytest.fixture(autouse=True)
def _restore_ytd_switch():
    original = set(shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES)
    yield
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.clear()
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.update(original)


def _stub_business_code_generation(monkeypatch):
    """generate_payslips_for_run numbers payslips via generate_business_code,
    which needs a Postgres advisory lock the SQLite test DB can't provide."""
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def test_generate_payslips_for_run_works_for_a_real_gy_employee_with_credit(db, organization, monkeypatch):
    """Real end-to-end regression guard, written from day one this time:
    a GY employee with a real seeded credit balance actually gets it
    applied when processed through the genuine service.
    generate_payslips_for_run entry point, and the reduced balance is
    correctly persisted back."""
    _stub_business_code_generation(monkeypatch)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("GY")

    emp = _make_gy_employee(db, organization.id)
    _seed_gy_paye_slabs(db, organization.id)

    # Seed a real opening credit balance (2,000) as the DB-level entry
    # point would (no UI/API exists yet — see guyana.py's own docstring).
    seed = PayrollResult(gross=Decimal("0"), basic=Decimal("0"), ytd_gy_paye_credit_after=Decimal("2000.00"))
    service._upsert_gy_paye_credit_ytd_accumulator(db, emp.id, date(2026, 8, 1), seed, payslip_id=None)
    db.commit()

    run = PayrollRun(
        organization_id=organization.id, period_label="Sep 2026",
        period_start=date(2026, 9, 1), period_end=date(2026, 9, 30), pay_date=date(2026, 9, 30),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    service.generate_payslips_for_run(db, run, organization.id)

    item = db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id,
    ).first()
    assert item is not None
    # ctc=2,400,000/12 = 200,000 gross -> same fixture-F1/F4 base as
    # test_guyana.py: liability 12,200, credit 2,000 consumed in full.
    assert item.tds == Decimal("10200.00")

    accumulator = db.query(PayrollYtdAccumulator).filter(
        PayrollYtdAccumulator.employee_id == emp.id,
        PayrollYtdAccumulator.tax_component == service._GY_PAYE_CREDIT_YTD_COMPONENT,
    ).first()
    assert accumulator is not None
    assert accumulator.ytd_taxable_wages == Decimal("0.00")


def test_load_gy_paye_credit_ytd_empty_when_switch_off(db, organization):
    emp = _make_gy_employee(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.discard("GY")
    result = service._load_gy_paye_credit_ytd(db, emp.id, date(2026, 8, 1))
    assert result == {}


def test_load_gy_paye_credit_ytd_defaults_to_zero_for_fresh_employee(db, organization):
    emp = _make_gy_employee(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("GY")
    result = service._load_gy_paye_credit_ytd(db, emp.id, date(2026, 2, 1))
    assert result == dict(ytd_gy_paye_credit_before=Decimal("0"))


def test_upsert_then_load_round_trips_real_values(db, organization):
    emp = _make_gy_employee(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("GY")
    result = PayrollResult(gross=Decimal("200000"), basic=Decimal("200000"), ytd_gy_paye_credit_after=Decimal("7800.00"))
    service._upsert_gy_paye_credit_ytd_accumulator(db, emp.id, date(2026, 3, 1), result, payslip_id=None)
    db.commit()

    loaded = service._load_gy_paye_credit_ytd(db, emp.id, date(2026, 4, 1))
    assert loaded == dict(ytd_gy_paye_credit_before=Decimal("7800.00"))


def test_upsert_updates_existing_row_not_duplicate(db, organization):
    emp = _make_gy_employee(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("GY")
    first = PayrollResult(gross=Decimal("200000"), basic=Decimal("200000"), ytd_gy_paye_credit_after=Decimal("7800.00"))
    service._upsert_gy_paye_credit_ytd_accumulator(db, emp.id, date(2026, 3, 1), first, payslip_id=None)
    db.commit()
    second = PayrollResult(gross=Decimal("200000"), basic=Decimal("200000"), ytd_gy_paye_credit_after=Decimal("0.00"))
    service._upsert_gy_paye_credit_ytd_accumulator(db, emp.id, date(2026, 4, 1), second, payslip_id=None)
    db.commit()

    rows = db.query(PayrollYtdAccumulator).filter(
        PayrollYtdAccumulator.employee_id == emp.id,
        PayrollYtdAccumulator.tax_component == service._GY_PAYE_CREDIT_YTD_COMPONENT,
    ).all()
    assert len(rows) == 1
    assert rows[0].ytd_taxable_wages == Decimal("0.00")


def test_dormant_result_never_writes_a_row(db, organization):
    emp = _make_gy_employee(db, organization.id)
    shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES.add("GY")
    dormant_result = PayrollResult(gross=Decimal("200000"), basic=Decimal("200000"))  # ytd_* all None (default)
    service._upsert_gy_paye_credit_ytd_accumulator(db, emp.id, date(2026, 8, 1), dormant_result, payslip_id=None)
    db.commit()
    count = db.query(PayrollYtdAccumulator).filter(PayrollYtdAccumulator.employee_id == emp.id).count()
    assert count == 0


def test_gy_ytd_tax_year_is_calendar_year():
    assert service._gy_ytd_tax_year(date(2026, 1, 1)) == "GY-CY-2026"
    assert service._gy_ytd_tax_year(date(2026, 12, 31)) == "GY-CY-2026"
    assert service._gy_ytd_tax_year(date(2027, 1, 1)) == "GY-CY-2027"
