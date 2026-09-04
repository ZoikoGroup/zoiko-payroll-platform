"""
tests/test_ca_qc_hsf_labour_standards_service_integration.py
----------------------------------------------------------------
Service-layer integration coverage for Quebec's Health Services Fund
(org-level-accumulator-banded, sliding rate) and labour standards
contribution (per-employee capped, no accumulator) — ZP-TAX-CA-2026-001
§13. Pure arithmetic boundary cases already live in
test_engine_standard.py; these tests are about the DB wiring, mirroring
test_ca_bc_mb_nl_levy_service_integration.py's style.
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


def _make_ca_employee(db, org_id, code, work_state="QC", ctc=Decimal("1200000")):
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


def _seed_qc_hsf_general(db):
    _seed_rate(db, "QC", "qc_hsf_threshold_low", flat_amount=Decimal("1000000"))
    _seed_rate(db, "QC", "qc_hsf_threshold_high", flat_amount=Decimal("7800000"))
    _seed_rate(db, "QC", "qc_hsf_general_low_rate", employer_rate_pct=Decimal("1.65"))
    _seed_rate(db, "QC", "qc_hsf_general_mid_base", employer_rate_pct=Decimal("1.2662"))
    _seed_rate(db, "QC", "qc_hsf_general_mid_slope", employer_rate_pct=Decimal("0.3838"))
    _seed_rate(db, "QC", "qc_hsf_general_high_rate", employer_rate_pct=Decimal("4.26"))
    db.commit()


def _seed_qc_hsf_public(db):
    _seed_rate(db, "QC", "qc_hsf_public_rate", employer_rate_pct=Decimal("4.26"))
    db.commit()


def _seed_qc_labour_standards(db):
    _seed_rate(db, "QC", "qc_labour_standards_cap", flat_amount=Decimal("103000"))
    _seed_rate(db, "QC", "qc_labour_standards_rate", employer_rate_pct=Decimal("0.07"))
    db.commit()


def _stub_business_code_generation(monkeypatch):
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def test_generate_payslips_for_run_computes_qc_hsf_general(db, organization, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    _seed_qc_hsf_general(db)
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    service._upsert_ca_org_levy_ytd(db, organization.id, date(2026, 1, 1), {"qc_hsf": Decimal("500000")})
    db.commit()
    employee = _make_ca_employee(db, organization.id, "QC-1", "QC", ctc=Decimal("1200000"))  # 100,000/mo
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    service.generate_payslips_for_run(db, run, organization.id)

    item = db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == employee.id,
    ).first()
    # before=500,000, gross=100,000 -> after=600,000, both under the $1M
    # threshold — flat 1.65% applies to the WHOLE total, not an excess:
    # 500,000*1.65% = 8,250.00; 600,000*1.65% = 9,900.00 -> period = 1,650.00
    assert item.employer_qc_hsf == Decimal("1650.00")
    row = db.query(OrganizationYtdAccumulator).filter(
        OrganizationYtdAccumulator.organization_id == organization.id,
        OrganizationYtdAccumulator.tax_component == "qc_hsf",
    ).first()
    assert row.ytd_taxable_wages == Decimal("600000.00")


def test_generate_payslips_for_run_reads_public_sector_category_from_compliance_details(db, organization, monkeypatch):
    _stub_business_code_generation(monkeypatch)
    _seed_qc_hsf_general(db)
    _seed_qc_hsf_public(db)
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    db.add(CompanyComplianceDetails(
        organization_id=organization.id, jurisdiction_country="Canada",
        qc_hsf_employer_category="PUBLIC_SECTOR",
    ))
    service._upsert_ca_org_levy_ytd(db, organization.id, date(2026, 1, 1), {"qc_hsf": Decimal("500000")})
    db.commit()
    employee = _make_ca_employee(db, organization.id, "QC-PUBLIC", "QC", ctc=Decimal("1200000"))
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    service.generate_payslips_for_run(db, run, organization.id)

    item = db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == employee.id,
    ).first()
    # General's 1.65% would give 1,650.00 — proving PUBLIC_SECTOR's flat
    # 4.26% was used instead: 500,000*4.26%=21,300.00; 600,000*4.26%=25,560.00
    assert item.employer_qc_hsf == Decimal("4260.00")


def test_add_payslip_item_computes_qc_labour_standards_no_accumulator_needed(db, organization):
    _seed_qc_labour_standards(db)
    employee = _make_ca_employee(db, organization.id, "QC-LS", "QC", ctc=Decimal("1200000"))  # 100,000/mo
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    item = service.add_payslip_item(db, run.id, PayslipItemCreate(
        employee_id=employee.id, basic_salary=Decimal("100000"),
    ), organization.id)

    # annual 1,200,000 > $103,000 cap -> subject capped at 103,000 * 0.07% = 72.10 -> /12 = 6.01
    assert item.employer_qc_labour_standards == Decimal("6.01")
    # No org accumulator row at all — this levy needs none.
    assert db.query(OrganizationYtdAccumulator).filter(
        OrganizationYtdAccumulator.organization_id == organization.id,
        OrganizationYtdAccumulator.tax_component == "qc_hsf",
    ).count() == 0


def test_preview_payroll_run_surfaces_qc_hsf_and_labour_standards_read_only(db, organization):
    _seed_qc_hsf_general(db)
    _seed_qc_labour_standards(db)
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    service._upsert_ca_org_levy_ytd(db, organization.id, date(2026, 1, 1), {"qc_hsf": Decimal("500000")})
    db.commit()
    employee = _make_ca_employee(db, organization.id, "QC-PREVIEW", "QC", ctc=Decimal("1200000"))
    result = service.preview_payroll_run(
        db, organization.id, [employee.id], "CA",
        period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
    )
    assert result["employees"][0]["employerQcHsf"] == 1650.0
    assert result["employees"][0]["employerQcLabourStandards"] == 6.01
    # Read-only — must never increment the org total.
    row = db.query(OrganizationYtdAccumulator).filter(
        OrganizationYtdAccumulator.organization_id == organization.id,
        OrganizationYtdAccumulator.tax_component == "qc_hsf",
    ).first()
    assert row.ytd_taxable_wages == Decimal("500000")


def test_qc_employee_without_category_flag_defaults_to_general(db, organization, monkeypatch):
    """No CompanyComplianceDetails row at all (the common case today,
    since no UI sets qc_hsf_employer_category yet) must resolve to
    GENERAL, not silently error or default to public sector."""
    _stub_business_code_generation(monkeypatch)
    _seed_qc_hsf_general(db)
    _seed_qc_hsf_public(db)
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    service._upsert_ca_org_levy_ytd(db, organization.id, date(2026, 1, 1), {"qc_hsf": Decimal("500000")})
    db.commit()
    employee = _make_ca_employee(db, organization.id, "QC-DEFAULT", "QC", ctc=Decimal("1200000"))
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    service.generate_payslips_for_run(db, run, organization.id)

    item = db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == employee.id,
    ).first()
    assert item.employer_qc_hsf == Decimal("1650.00")  # general's 1.65%, not public's 4.26%
