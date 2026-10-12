"""
tests/test_ca_bc_mb_nl_levy_service_integration.py
-----------------------------------------------------
Service-layer integration coverage for BC EHT, Manitoba HE Levy and NL
HAPSET (ZP-TAX-CA-2026-001 §15) — the same "read org total, calculate,
write back the increment" contract already proven for Ontario EHT in
test_ca_org_eht_service_integration.py, exercised here through
generate_payslips_for_run/add_payslip_item/preview_payroll_run for the
three notch-shaped levies and BC's ordinary-vs-charity/nonprofit
classification switch. Pure arithmetic boundary cases already live in
test_engine_standard.py — these tests are about the DB wiring instead.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll import service
from app.modules.payroll.models import (
    ContributionRate, PayrollEmployee, PayrollRun, PayslipItem, OrganizationYtdAccumulator,
    CompanyComplianceDetails,
)
from app.modules.payroll.schemas import PayslipItemCreate
import app.modules.payroll.engine.countries.shared as shared


@pytest.fixture(autouse=True)
def _restore_org_levy_switch():
    original = set(shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES)
    yield
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.clear()
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.update(original)


def _make_ca_employee(db, org_id, code, work_state, ctc=Decimal("18000000")):
    # A large ctc (1.5M/mo) by default — these levies only activate in the
    # $1M-$5M+ remuneration range, well above a normal single-employee
    # salary, so tests push the org total there deliberately via ctc size
    # or via a pre-seeded accumulator instead of dozens of employees.
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


def _seed_rate(db, state, component_key, flat_amount=None, employer_rate_pct=None):
    db.add(ContributionRate(
        organization_id=None, jurisdiction_country="CA", jurisdiction_state=state,
        component_key=component_key, label=component_key,
        employee_share="—", employer_share="—", total="—",
        flat_amount=flat_amount, employer_rate_pct=employer_rate_pct,
    ))


def _seed_bc_eht(db):
    _seed_rate(db, "BC", "bc_eht_exemption_threshold", flat_amount=Decimal("1000000"))
    _seed_rate(db, "BC", "bc_eht_upper_threshold", flat_amount=Decimal("1500000"))
    _seed_rate(db, "BC", "bc_eht_notch_rate", employer_rate_pct=Decimal("5.85"))
    _seed_rate(db, "BC", "bc_eht_flat_rate", employer_rate_pct=Decimal("1.95"))
    db.commit()


def _seed_bc_eht_charity(db):
    _seed_rate(db, "BC", "bc_eht_charity_exemption_threshold", flat_amount=Decimal("1500000"))
    _seed_rate(db, "BC", "bc_eht_charity_upper_threshold", flat_amount=Decimal("4500000"))
    _seed_rate(db, "BC", "bc_eht_charity_notch_rate", employer_rate_pct=Decimal("2.925"))
    _seed_rate(db, "BC", "bc_eht_charity_flat_rate", employer_rate_pct=Decimal("1.95"))
    db.commit()


def _seed_mb_he_levy(db):
    _seed_rate(db, "MB", "mb_he_levy_exemption_threshold", flat_amount=Decimal("2500000"))
    _seed_rate(db, "MB", "mb_he_levy_upper_threshold", flat_amount=Decimal("5000000"))
    _seed_rate(db, "MB", "mb_he_levy_notch_rate", employer_rate_pct=Decimal("4.3"))
    _seed_rate(db, "MB", "mb_he_levy_flat_rate", employer_rate_pct=Decimal("2.15"))
    db.commit()


def _seed_nl_hapset(db):
    _seed_rate(db, "NL", "nl_hapset_exemption_threshold", flat_amount=Decimal("2000000"))
    _seed_rate(db, "NL", "nl_hapset_flat_rate", employer_rate_pct=Decimal("2.0"))
    db.commit()


def _stub_business_code_generation(monkeypatch):
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def test_generate_payslips_for_run_computes_bc_eht_ordinary(db, organization, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    _seed_bc_eht(db)
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    # Pre-seed the org already inside the BC notch range so this one
    # employee's gross both starts and ends inside it — isolates the
    # wiring from the pure arithmetic already proven in
    # test_engine_standard.py.
    service._upsert_ca_org_levy_ytd(db, organization.id, date(2026, 1, 1), {"bc_eht": Decimal("1100000")})
    db.commit()
    employee = _make_ca_employee(db, organization.id, "BC-1", "BC", ctc=Decimal("600000"))  # 50,000/mo
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    service.generate_payslips_for_run(db, run, organization.id)

    item = db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == employee.id,
    ).first()
    # before=1,100,000, gross=50,000 -> after=1,150,000, both in notch tier:
    # (1,150,000-1,000,000)*5.85% - (1,100,000-1,000,000)*5.85% = 2,925.00
    assert item.employer_bc_eht == Decimal("2925.00")
    row = db.query(OrganizationYtdAccumulator).filter(
        OrganizationYtdAccumulator.organization_id == organization.id,
        OrganizationYtdAccumulator.tax_component == "bc_eht",
    ).first()
    assert row.ytd_taxable_wages == Decimal("1150000.00")


def test_generate_payslips_for_run_reads_charity_classification_from_compliance_details(db, organization, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    _seed_bc_eht(db)
    _seed_bc_eht_charity(db)
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    db.add(CompanyComplianceDetails(
        organization_id=organization.id, jurisdiction_country="Canada",
        bc_eht_employer_classification="CHARITY_NONPROFIT",
    ))
    service._upsert_ca_org_levy_ytd(db, organization.id, date(2026, 1, 1), {"bc_eht": Decimal("2000000")})
    db.commit()
    employee = _make_ca_employee(db, organization.id, "BC-CHARITY", "BC", ctc=Decimal("2400000"))  # 200,000/mo
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    service.generate_payslips_for_run(db, run, organization.id)

    item = db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == employee.id,
    ).first()
    # Ordinary thresholds at total=$2.2M would already be in the flat
    # 1.95%-of-total tier — this proves the CHARITY notch tier was used:
    # before: (2,000,000-1,500,000)*2.925% = 14,625.00
    # after:  (2,200,000-1,500,000)*2.925% = 20,475.00 -> period = 5,850.00
    assert item.employer_bc_eht == Decimal("5850.00")


def test_add_payslip_item_computes_mb_he_levy(db, organization):
    _seed_mb_he_levy(db)
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    service._upsert_ca_org_levy_ytd(db, organization.id, date(2026, 1, 1), {"mb_he_levy": Decimal("2900000")})
    db.commit()
    employee = _make_ca_employee(db, organization.id, "MB-1", "MB", ctc=Decimal("2400000"))
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    item = service.add_payslip_item(db, run.id, PayslipItemCreate(
        employee_id=employee.id, basic_salary=Decimal("200000"),
    ), organization.id)

    # before=2,900,000, gross=200,000 -> after=3,100,000, both in notch tier:
    # (3,100,000-2,500,000)*4.3% - (2,900,000-2,500,000)*4.3% = 8,600.00
    assert item.employer_mb_he_levy == Decimal("8600.00")
    row = db.query(OrganizationYtdAccumulator).filter(
        OrganizationYtdAccumulator.organization_id == organization.id,
        OrganizationYtdAccumulator.tax_component == "mb_he_levy",
    ).first()
    assert row.ytd_taxable_wages == Decimal("3100000.00")


def test_generate_payslips_for_run_computes_nl_hapset(db, organization, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    _seed_nl_hapset(db)
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    service._upsert_ca_org_levy_ytd(db, organization.id, date(2026, 1, 1), {"nl_hapset": Decimal("2200000")})
    db.commit()
    employee = _make_ca_employee(db, organization.id, "NL-1", "NL", ctc=Decimal("2400000"))
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    service.generate_payslips_for_run(db, run, organization.id)

    item = db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == employee.id,
    ).first()
    # before=2,200,000, gross=200,000 -> after=2,400,000:
    # (2,400,000-2,000,000)*2% - (2,200,000-2,000,000)*2% = 4,000.00
    assert item.employer_nl_hapset == Decimal("4000.00")


def test_preview_payroll_run_surfaces_all_four_levies_read_only(db, organization):
    _seed_bc_eht(db)
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    service._upsert_ca_org_levy_ytd(db, organization.id, date(2026, 1, 1), {"bc_eht": Decimal("1100000")})
    db.commit()
    employee = _make_ca_employee(db, organization.id, "BC-PREVIEW", "BC", ctc=Decimal("600000"))
    result = service.preview_payroll_run(
        db, organization.id, [employee.id], "CA",
        period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
    )
    assert result["employees"][0]["employerBcEht"] == 2925.0
    assert result["employees"][0]["employerMbHeLevy"] == 0.0
    assert result["employees"][0]["employerNlHapset"] == 0.0
    # Read-only — must never increment the org total.
    row = db.query(OrganizationYtdAccumulator).filter(
        OrganizationYtdAccumulator.organization_id == organization.id,
        OrganizationYtdAccumulator.tax_component == "bc_eht",
    ).first()
    assert row.ytd_taxable_wages == Decimal("1100000")


def test_bc_employee_without_charity_flag_defaults_to_ordinary(db, organization, monkeypatch):
    """No CompanyComplianceDetails row at all (the common case today,
    since no UI sets bc_eht_employer_classification yet) must resolve to
    ordinary, not silently error or default to charity."""
    _stub_business_code_generation(monkeypatch)
    _seed_bc_eht(db)
    _seed_bc_eht_charity(db)
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    service._upsert_ca_org_levy_ytd(db, organization.id, date(2026, 1, 1), {"bc_eht": Decimal("1100000")})
    db.commit()
    employee = _make_ca_employee(db, organization.id, "BC-DEFAULT", "BC", ctc=Decimal("600000"))
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    service.generate_payslips_for_run(db, run, organization.id)

    item = db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == employee.id,
    ).first()
    assert item.employer_bc_eht == Decimal("2925.00")  # ordinary notch, not charity's
