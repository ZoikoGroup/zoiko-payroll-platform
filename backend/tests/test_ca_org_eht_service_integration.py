"""
tests/test_ca_org_eht_service_integration.py
----------------------------------------------
Service-layer integration coverage for Ontario EHT (ZP-TAX-CA-2026-001
§13/§16), exercising the full read/write/dormancy contract THROUGH
generate_payslips_for_run and add_payslip_item — not just the pure
_load_ca_org_levy_ytd/_upsert_ca_org_levy_ytd plumbing already covered by
test_ca_org_levy_accumulator.py, nor the pure canada.py arithmetic already
covered by test_engine_standard.py's test_on_eht_* tests. These tests prove
the three layers actually wire together correctly: the org accumulator is
read before calculating, employer_eht lands on the real PayslipItem, and
the accumulator is incremented afterward — sequentially, across employees
in one run.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll import service
from app.modules.payroll.models import (
    ContributionRate, TaxSlab, PayrollEmployee, PayrollRun, PayslipItem, OrganizationYtdAccumulator,
)
from app.modules.payroll.schemas import PayslipItemCreate
import app.modules.payroll.engine.countries.shared as shared


@pytest.fixture(autouse=True)
def _restore_org_levy_switch():
    original = set(shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES)
    yield
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.clear()
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.update(original)


def _make_ca_employee(db, org_id, code, work_state="ON", ctc=Decimal("96000")):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="CA", work_state=work_state, ctc=ctc,
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _make_run(db, org_id, period_start, period_end, pay_date, label="Test Run"):
    run = PayrollRun(
        organization_id=org_id, period_label=label,
        period_start=period_start, period_end=period_end, pay_date=pay_date,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _seed_on_eht_bands(db):
    """A minimal, real 2-band Ontario EHT table plus its $1M exemption —
    same shape SlabFormModal's ON_EHT_BAND rule_type writes via the Tax
    Slabs UI (see frontend/src/components/jurisdiction/SlabFormModal.jsx)."""
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="CA", jurisdiction_state="ON",
        min_amount=Decimal("0"), max_amount=Decimal("200000"), rate_pct=Decimal("0.98"),
        rate_label="EHT", tax_formula="", rule_type="ON_EHT_BAND",
    ))
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="CA", jurisdiction_state="ON",
        min_amount=Decimal("200000"), max_amount=None, rate_pct=Decimal("1.95"),
        rate_label="EHT", tax_formula="", rule_type="ON_EHT_BAND",
    ))
    db.add(ContributionRate(
        organization_id=None, jurisdiction_country="CA", jurisdiction_state="ON",
        component_key="on_eht_exemption", label="Ontario EHT Exemption",
        employee_share="—", employer_share="—", total="—",
        flat_amount=Decimal("1000000"),
    ))
    db.commit()


def _stub_business_code_generation(monkeypatch):
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def test_employer_eht_stays_zero_when_switch_off(db, organization, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    _seed_on_eht_bands(db)
    assert "CA" not in shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES
    employee = _make_ca_employee(db, organization.id, "EHT-OFF")
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    service.generate_payslips_for_run(db, run, organization.id)

    item = db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == employee.id,
    ).first()
    assert item.employer_eht == Decimal("0")
    assert db.query(OrganizationYtdAccumulator).filter(
        OrganizationYtdAccumulator.organization_id == organization.id,
    ).count() == 0


def test_employer_eht_stays_zero_for_non_ontario_employee_even_when_switch_on(db, organization, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    _seed_on_eht_bands(db)
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    employee = _make_ca_employee(db, organization.id, "EHT-BC", work_state="BC")
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    service.generate_payslips_for_run(db, run, organization.id)

    item = db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == employee.id,
    ).first()
    assert item.employer_eht == Decimal("0")


def test_generate_payslips_for_run_computes_and_persists_employer_eht(db, organization, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    _seed_on_eht_bands(db)
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    # ctc=96000 -> monthly gross 8000; below the $1M exemption entirely,
    # so employer_eht is 0 for this one employee's first period — the
    # accumulator write is still what matters here.
    employee = _make_ca_employee(db, organization.id, "EHT-ON1", ctc=Decimal("96000"))
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    service.generate_payslips_for_run(db, run, organization.id)

    item = db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == employee.id,
    ).first()
    assert item.employer_eht == Decimal("0")  # $8,000 << $1,000,000 exemption
    row = db.query(OrganizationYtdAccumulator).filter(
        OrganizationYtdAccumulator.organization_id == organization.id,
        OrganizationYtdAccumulator.tax_component == "on_eht",
    ).first()
    assert row is not None
    assert row.ytd_taxable_wages == Decimal("8000.00")
    assert row.last_updated_payslip_id == item.id


def test_org_total_accrues_sequentially_across_employees_in_one_run(db, organization, monkeypatch):
    """Two Ontario employees in the SAME run must accrue onto the SAME
    org-wide total, in processing order — the org accumulator is
    genuinely shared, unlike the per-employee YTD accumulator."""
    _stub_business_code_generation(monkeypatch)
    _seed_on_eht_bands(db)
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    _make_ca_employee(db, organization.id, "EHT-ON-A", ctc=Decimal("96000"))   # 8,000/mo
    _make_ca_employee(db, organization.id, "EHT-ON-B", ctc=Decimal("96000"))   # 8,000/mo
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    service.generate_payslips_for_run(db, run, organization.id)

    row = db.query(OrganizationYtdAccumulator).filter(
        OrganizationYtdAccumulator.organization_id == organization.id,
        OrganizationYtdAccumulator.tax_component == "on_eht",
    ).first()
    assert row.ytd_taxable_wages == Decimal("16000.00")  # both employees' gross, summed

    items = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).order_by(PayslipItem.id).all()
    assert len(items) == 2
    # Neither employee individually crosses the $1M exemption, so both
    # show 0 — the accrual (not any single employee's rate) is what this
    # test is proving.
    assert all(i.employer_eht == Decimal("0") for i in items)


def test_add_payslip_item_reads_and_increments_org_total(db, organization, monkeypatch):
    _seed_on_eht_bands(db)
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    # Pre-seed the org already close to the exemption so this one manual
    # payslip's gross pushes it over, proving add_payslip_item reads the
    # CURRENT org total rather than starting fresh from 0.
    service._upsert_ca_org_levy_ytd(db, organization.id, date(2026, 1, 1), {"on_eht": Decimal("995000")})
    db.commit()

    employee = _make_ca_employee(db, organization.id, "EHT-MANUAL", ctc=Decimal("96000"))
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    item = service.add_payslip_item(db, run.id, PayslipItemCreate(
        employee_id=employee.id, basic_salary=Decimal("8000"),
    ), organization.id)

    # before=995,000 (annual EHT there is 0 — fully under the $1M
    # exemption), after=1,003,000 (now $1M exempt, $3,000 taxable — and
    # the RATE is picked off the 1,003,000 total itself, landing in the
    # second band at 1.95%, not the first): 3,000 * 1.95% = 58.50, and
    # the period amount is that annual delta minus the (zero) before-delta.
    assert item.employer_eht == Decimal("58.50")
    row = db.query(OrganizationYtdAccumulator).filter(
        OrganizationYtdAccumulator.organization_id == organization.id,
        OrganizationYtdAccumulator.tax_component == "on_eht",
    ).first()
    assert row.ytd_taxable_wages == Decimal("1003000.00")


def test_preview_payroll_run_is_read_only_and_never_writes_accumulator(db, organization, monkeypatch):
    _seed_on_eht_bands(db)
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    employee = _make_ca_employee(db, organization.id, "EHT-PREVIEW", ctc=Decimal("96000"))
    result = service.preview_payroll_run(
        db, organization.id, [employee.id], "CA",
        period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
    )
    assert result["employees"][0]["employerEht"] == 0.0
    assert db.query(OrganizationYtdAccumulator).filter(
        OrganizationYtdAccumulator.organization_id == organization.id,
    ).count() == 0


def test_regenerate_employee_payslip_leaves_eht_dormant(db, organization, monkeypatch):
    """Recalculation must never re-read the live org accumulator (that
    would silently re-increment it and disagree with the frozen original
    figure) — same discipline already proven for the per-employee YTD
    accumulator's regenerate_employee_payslip path."""
    _stub_business_code_generation(monkeypatch)
    _seed_on_eht_bands(db)
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    employee = _make_ca_employee(db, organization.id, "EHT-REGEN", ctc=Decimal("96000"))
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    service.generate_payslips_for_run(db, run, organization.id)

    before_row = db.query(OrganizationYtdAccumulator).filter(
        OrganizationYtdAccumulator.organization_id == organization.id,
        OrganizationYtdAccumulator.tax_component == "on_eht",
    ).first()
    before_total = before_row.ytd_taxable_wages

    service.regenerate_employee_payslip(db, run.id, employee.id, organization.id)

    item = db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == employee.id,
    ).first()
    assert item.employer_eht == Decimal("0")  # dormant on recalculation, no frozen snapshot to reproduce from
    after_row = db.query(OrganizationYtdAccumulator).filter(
        OrganizationYtdAccumulator.organization_id == organization.id,
        OrganizationYtdAccumulator.tax_component == "on_eht",
    ).first()
    assert after_row.ytd_taxable_wages == before_total  # unchanged — no re-increment
