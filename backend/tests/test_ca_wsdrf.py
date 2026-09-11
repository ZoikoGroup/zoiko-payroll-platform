"""
tests/test_ca_wsdrf.py
------------------------
Coverage for service.py's calculate_ca_wsdrf_shortfall (ZP-TAX-CA-2026-001
§13/§15, gap-closure Phase 7, 2026-09-11) — Quebec's Workforce Skills
Development and Recognition Fund: 1% of total Quebec payroll minus the
employer's own declared eligible training expenditure. A standalone
ANNUAL reconciliation calculator (never wired into canada.py's
calculate()), same cross-run-summation discipline as
generate_india_form_138/generate_ca_pd7a.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem, EmployerTaxProfile


def _make_qc_run_and_item(db, organization_id, employee_id, period_end, gross_pay, status="Approved"):
    run = PayrollRun(
        organization_id=organization_id, period_label=str(period_end),
        period_start=period_end.replace(day=1), period_end=period_end, pay_date=period_end,
        status=status,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee_id, organization_id=organization_id,
        employee_name="WSDRF Employee", country_code="CA", work_state="QC",
        gross_pay=gross_pay, total_deductions=0, net_pay=gross_pay,
    )
    db.add(item)
    db.commit()
    return run, item


def test_wsdrf_rejects_inverted_date_range(db, organization):
    with pytest.raises(BadRequestException):
        service.calculate_ca_wsdrf_shortfall(db, organization.id, date(2026, 12, 31), date(2026, 1, 1))


def test_wsdrf_sums_only_finalized_quebec_payroll_in_range(db, organization):
    employee = PayrollEmployee(organization_id=organization.id, employee_code="WSDRF1", name="Employee One")
    db.add(employee)
    db.commit()
    db.refresh(employee)

    # Inside the year, finalized -> counts.
    _make_qc_run_and_item(db, organization.id, employee.id, date(2026, 3, 31), Decimal("2000000"))
    _make_qc_run_and_item(db, organization.id, employee.id, date(2026, 9, 30), Decimal("3000000"))
    # Outside the year -> must NOT count.
    _make_qc_run_and_item(db, organization.id, employee.id, date(2025, 12, 31), Decimal("9999999"))
    # Inside the year but still Draft -> must NOT count.
    _make_qc_run_and_item(db, organization.id, employee.id, date(2026, 6, 30), Decimal("8888888"), status="Draft")

    result = service.calculate_ca_wsdrf_shortfall(db, organization.id, date(2026, 1, 1), date(2026, 12, 31))
    assert result["total_quebec_payroll"] == Decimal("5000000")
    # 1% default rate (no state_rate_map row configured) -> $50,000 required.
    assert result["required_investment"] == Decimal("50000.00")
    assert result["training_expenditure"] == Decimal("0")
    assert result["shortfall"] == Decimal("50000.00")
    assert result["employee_count"] == 1


def test_wsdrf_training_expenditure_reduces_shortfall(db, organization):
    employee = PayrollEmployee(organization_id=organization.id, employee_code="WSDRF2", name="Employee Two")
    db.add(employee)
    db.commit()
    db.refresh(employee)
    _make_qc_run_and_item(db, organization.id, employee.id, date(2026, 6, 30), Decimal("5000000"))

    db.add(EmployerTaxProfile(
        organization_id=organization.id, jurisdiction_id="CA-QC", component_code="QC_WSDRF_TRAINING_EXPENDITURE",
        taxable_wage_base=Decimal("30000"), effective_from=date(2026, 1, 1),
    ))
    db.commit()

    result = service.calculate_ca_wsdrf_shortfall(db, organization.id, date(2026, 1, 1), date(2026, 12, 31))
    assert result["required_investment"] == Decimal("50000.00")
    assert result["training_expenditure"] == Decimal("30000")
    assert result["shortfall"] == Decimal("20000.00")


def test_wsdrf_training_expenditure_exceeding_requirement_floors_shortfall_at_zero(db, organization):
    employee = PayrollEmployee(organization_id=organization.id, employee_code="WSDRF3", name="Employee Three")
    db.add(employee)
    db.commit()
    db.refresh(employee)
    _make_qc_run_and_item(db, organization.id, employee.id, date(2026, 6, 30), Decimal("1000000"))

    db.add(EmployerTaxProfile(
        organization_id=organization.id, jurisdiction_id="CA-QC", component_code="QC_WSDRF_TRAINING_EXPENDITURE",
        taxable_wage_base=Decimal("50000"), effective_from=date(2026, 1, 1),
    ))
    db.commit()

    result = service.calculate_ca_wsdrf_shortfall(db, organization.id, date(2026, 1, 1), date(2026, 12, 31))
    assert result["required_investment"] == Decimal("10000.00")  # 1% of 1,000,000
    assert result["shortfall"] == Decimal("0")


def test_wsdrf_training_expenditure_override_ignores_real_profile(db, organization):
    employee = PayrollEmployee(organization_id=organization.id, employee_code="WSDRF4", name="Employee Four")
    db.add(employee)
    db.commit()
    db.refresh(employee)
    _make_qc_run_and_item(db, organization.id, employee.id, date(2026, 6, 30), Decimal("2000000"))

    db.add(EmployerTaxProfile(
        organization_id=organization.id, jurisdiction_id="CA-QC", component_code="QC_WSDRF_TRAINING_EXPENDITURE",
        taxable_wage_base=Decimal("5000"), effective_from=date(2026, 1, 1),
    ))
    db.commit()

    result = service.calculate_ca_wsdrf_shortfall(
        db, organization.id, date(2026, 1, 1), date(2026, 12, 31),
        training_expenditure_override=Decimal("15000"),
    )
    assert result["training_expenditure"] == Decimal("15000")
    assert result["shortfall"] == Decimal("5000.00")  # 20,000 required - 15,000 override


def test_wsdrf_non_quebec_payroll_excluded(db, organization):
    employee = PayrollEmployee(organization_id=organization.id, employee_code="WSDRF5", name="Employee Five")
    db.add(employee)
    db.commit()
    db.refresh(employee)
    run = PayrollRun(
        organization_id=organization.id, period_label="ON run",
        period_start=date(2026, 6, 1), period_end=date(2026, 6, 30), pay_date=date(2026, 6, 30),
        status="Approved",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee.id, organization_id=organization.id,
        employee_name="Ontario Employee", country_code="CA", work_state="ON",
        gross_pay=Decimal("3000000"), total_deductions=0, net_pay=Decimal("3000000"),
    )
    db.add(item)
    db.commit()

    result = service.calculate_ca_wsdrf_shortfall(db, organization.id, date(2026, 1, 1), date(2026, 12, 31))
    assert result["total_quebec_payroll"] == Decimal("0")
    assert result["shortfall"] == Decimal("0")
