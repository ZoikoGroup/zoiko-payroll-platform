"""
tests/test_jm_heart_org_levy.py
---------------------------------
DB-level coverage for Jamaica HEART's employer-wide monthly aggregation
(JM-008) real-org-level-accumulator wiring (service.py's
_load_jm_heart_ytd/_upsert_jm_heart_ytd, reusing OrganizationYtdAccumulator
via the generic _load_ca_org_levy_ytd/_upsert_ca_org_levy_ytd pair with
HEART's own monthly tax_year key). Written with the real end-to-end
service.generate_payslips_for_run multi-employee test FIRST — the gap
that let a real bug ship silently for Cayman Islands (see
test_ky_pension_ytd_accumulator.py's own postmortem test) and nearly
shipped a second time for Guyana (see test_gy_paye_credit_ytd_
accumulator.py's own comment) before being caught here too, on the very
first real run. Calculation correctness itself (the telescoping math) is
covered engine-side in test_jamaica.py.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem, OrganizationYtdAccumulator, TaxSlab
import app.modules.payroll.engine.countries.shared as shared


@pytest.fixture(autouse=True)
def _restore_org_levy_switch():
    original = set(shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES)
    yield
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.clear()
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.update(original)


def _stub_business_code_generation(monkeypatch):
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def _seed_jm_slabs(db, organization_id):
    """Org-scoped PAYE bands, needed for a real payroll run to resolve any
    slabs at all — same reasoning as test_gy_paye_credit_ytd_accumulator.
    py's own _seed_gy_paye_slabs."""
    db.add_all([
        TaxSlab(
            organization_id=organization_id, jurisdiction_country="JM",
            min_amount=Decimal("0"), max_amount=Decimal("6000000"), rate_pct=Decimal("25"), rate_label="PAYE 25%",
            tax_formula="",
        ),
        TaxSlab(
            organization_id=organization_id, jurisdiction_country="JM",
            min_amount=Decimal("6000000"), max_amount=None, rate_pct=Decimal("30"), rate_label="PAYE 30%",
            tax_formula="",
        ),
    ])
    db.commit()


def _make_jm_employee(db, org_id, code, monthly_gross):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="JM", ctc=monthly_gross * 12,
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def test_generate_payslips_for_run_aggregates_heart_across_three_employees(db, organization, monkeypatch):
    """The real end-to-end regression guard, written from day one: three
    employees each individually under the JMD 14,444 threshold, processed
    through the genuine service.generate_payslips_for_run entry point in
    one run, must collect the correct combined-total HEART liability
    exactly once — not $0 (Phase 1's old per-employee bug) and not
    triple-charged."""
    _stub_business_code_generation(monkeypatch)
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("JM")
    _seed_jm_slabs(db, organization.id)

    emp1 = _make_jm_employee(db, organization.id, "JME1", Decimal("5000"))
    emp2 = _make_jm_employee(db, organization.id, "JME2", Decimal("5000"))
    emp3 = _make_jm_employee(db, organization.id, "JME3", Decimal("5000"))

    run = PayrollRun(
        organization_id=organization.id, period_label="Sep 2026",
        period_start=date(2026, 9, 1), period_end=date(2026, 9, 30), pay_date=date(2026, 9, 30),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    service.generate_payslips_for_run(db, run, organization.id)

    items = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).all()
    assert len(items) == 3
    total_heart = sum((item.employer_payroll_tax or Decimal("0")) for item in items)
    # 3% of the combined 15,000 employer-wide monthly total.
    assert total_heart == Decimal("450.00")
    # Not evenly/independently charged to each employee — exactly one
    # employee's period (whichever crossed the cumulative threshold)
    # carries the whole liability, the other two carry $0.
    nonzero = [item for item in items if (item.employer_payroll_tax or Decimal("0")) > 0]
    assert len(nonzero) == 1
    assert nonzero[0].employer_payroll_tax == Decimal("450.00")

    accumulator = db.query(OrganizationYtdAccumulator).filter(
        OrganizationYtdAccumulator.organization_id == organization.id,
        OrganizationYtdAccumulator.tax_component == "jm_heart",
    ).first()
    assert accumulator is not None
    assert accumulator.ytd_taxable_wages == Decimal("15000.00")


def test_generate_payslips_for_run_falls_back_when_switch_off(db, organization, monkeypatch):
    """The rollout switch off (JM not in _ORG_LEVY_ACCUMULATOR_ENABLED_
    COUNTRIES) must reproduce Phase 1's exact old per-employee behavior —
    three employees each under threshold pay $0 HEART each, not the
    combined-total figure."""
    _stub_business_code_generation(monkeypatch)
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.discard("JM")
    _seed_jm_slabs(db, organization.id)

    for i in range(3):
        _make_jm_employee(db, organization.id, f"JMOFF{i}", Decimal("5000"))

    run = PayrollRun(
        organization_id=organization.id, period_label="Sep 2026",
        period_start=date(2026, 9, 1), period_end=date(2026, 9, 30), pay_date=date(2026, 9, 30),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    service.generate_payslips_for_run(db, run, organization.id)

    items = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).all()
    assert len(items) == 3
    assert all((item.employer_payroll_tax or Decimal("0")) == Decimal("0.00") for item in items)


def test_load_jm_heart_ytd_empty_when_switch_off(db, organization):
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.discard("JM")
    result = service._load_jm_heart_ytd(db, organization.id, date(2026, 9, 1))
    assert result == {}


def test_load_jm_heart_ytd_defaults_to_zero_for_fresh_org(db, organization):
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("JM")
    result = service._load_jm_heart_ytd(db, organization.id, date(2026, 9, 1))
    assert result == dict(jm_heart_ytd_remuneration_before=Decimal("0"))


def test_jm_heart_tax_year_is_monthly_not_calendar_year():
    assert service._jm_heart_tax_year(date(2026, 9, 1)) == "JM-M-2026-09"
    assert service._jm_heart_tax_year(date(2026, 9, 30)) == "JM-M-2026-09"
    assert service._jm_heart_tax_year(date(2026, 10, 1)) == "JM-M-2026-10"
    assert service._jm_heart_tax_year(date(2026, 1, 5)) == "JM-M-2026-01"


def test_jm_heart_resets_across_month_boundary(db, organization):
    """A new calendar month must start the org's HEART accumulator fresh
    at 0, not carry over the prior month's cumulative total — the whole
    point of using a MONTHLY key instead of _org_ytd_tax_year's
    calendar-year one."""
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("JM")
    service._upsert_jm_heart_ytd(db, organization.id, date(2026, 9, 15), Decimal("15000"), payslip_id=None)
    db.commit()

    september_after = service._load_jm_heart_ytd(db, organization.id, date(2026, 9, 30))
    assert september_after == dict(jm_heart_ytd_remuneration_before=Decimal("15000"))

    october_before = service._load_jm_heart_ytd(db, organization.id, date(2026, 10, 1))
    assert october_before == dict(jm_heart_ytd_remuneration_before=Decimal("0"))
