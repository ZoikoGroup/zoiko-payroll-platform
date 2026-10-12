"""
tests/test_bs_report_forms.py
------------------------------
The Bahamas's real named statutory form (Caribbean forms gap-closure,
country #6, 2026-09-23): C10 monthly NIB contribution statement
(non-hospitality variant) — bespoke, per-employee-row cross-run
aggregation (same shape as the prior 5 countries). No PAYE/ISR
equivalent — Bahamas has no personal income tax.
"""
from datetime import date

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import service
from app.modules.payroll.schemas import (
    ReportTemplateUpsert, ReportTemplateComponentUpsert, ReportTemplateFieldUpsert,
)

from tests.test_report_templates import _make_user, _make_company, _build_template


def _make_bs_employee(db, organization_id, code, name="BS Employee", **overrides):
    from app.modules.payroll.models import PayrollEmployee

    fields = dict(compliance_fields={"nib_number": "NIB-001"})
    fields.update(overrides)
    employee = PayrollEmployee(organization_id=organization_id, employee_code=code, name=name, **fields)
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


def _make_bs_run_with_payslip(db, organization_id, employee_id, pay_date, *, status="Approved", employee_name="BS Employee", **overrides):
    from app.modules.payroll.models import PayrollRun, PayslipItem

    run = PayrollRun(
        organization_id=organization_id, period_label=str(pay_date),
        period_start=pay_date.replace(day=1), period_end=pay_date, pay_date=pay_date,
        status=status,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    fields = dict(gross_pay=100000, social_security=4650, employer_social_security=6650, total_deductions=4650, net_pay=95350)
    fields.update(overrides)
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee_id, organization_id=organization_id,
        employee_name=employee_name, country_code="BS", **fields,
    )
    db.add(item)
    db.commit()
    return run, item


def _build_bs_c10_template(db, creator, approver, key="BS-C10-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="C10", reportType="BS_C10",
            jurisdictionCountry="BS", reportingYear="2026", documentScope="AGGREGATE",
        ), actor_id=creator.id,
    )
    employer_info = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="employer_info", label="Employer Information"),
        actor_id=creator.id,
    )
    service.upsert_report_field(
        db, employer_info.id, ReportTemplateFieldUpsert(
            fieldKey="employer_name", label="Employer Name", fieldType="text",
            dataSourceKind="EMPLOYER_PROFILE", sourceColumn="name",
        ), actor_id=creator.id,
    )
    totals = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="totals", label="Employer Totals (Insurable Earnings / NIB)"),
        actor_id=creator.id,
    )
    for field_key, source_column in (
        ("total_employee_count", "gross_pay"),
        ("total_insurable_earnings", "gross_pay"),
        ("total_nib_employee", "social_security"),
        ("total_nib_employer", "employer_social_security"),
    ):
        service.upsert_report_field(
            db, totals.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=field_key, fieldType="currency",
                dataSourceKind="PAYSLIP_ITEM", sourceColumn=source_column,
            ), actor_id=creator.id,
        )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)
    return template


def test_generate_bs_c10_aggregates_two_employees_across_multiple_runs_same_month(db, organization):
    creator = _make_user(db, "creator_bsc10a@test.com")
    approver = _make_user(db, "approver_bsc10a@test.com")
    _make_company(db, organization.id, country="BS")
    emp1 = _make_bs_employee(db, organization.id, code="BSC10A1", name="Latoya Pinder")
    emp2 = _make_bs_employee(db, organization.id, code="BSC10A2", name="Anton Rolle")

    _make_bs_run_with_payslip(db, organization.id, emp1.id, date(2026, 8, 7), gross_pay=50000, social_security=2325, employer_social_security=3325, employee_name="Latoya Pinder")
    _make_bs_run_with_payslip(db, organization.id, emp1.id, date(2026, 8, 14), gross_pay=50000, social_security=2325, employer_social_security=3325, employee_name="Latoya Pinder")
    _make_bs_run_with_payslip(db, organization.id, emp2.id, date(2026, 8, 21), gross_pay=120000, social_security=5580, employer_social_security=7980, employee_name="Anton Rolle")

    template = _build_bs_c10_template(db, creator, approver)
    generated = service.generate_bs_c10(db, organization.id, template.id, 2026, 8, actor_id=creator.id)

    assert generated.report_type == "BS_C10"
    assert generated.scope_key == "PERIOD:2026-08-01:2026-08-31"
    totals = generated.rendered_data["employerTotals"]
    assert totals["total_employee_count"] == 2
    assert totals["total_insurable_earnings"] == 220000.0
    assert totals["total_nib_employee"] == 10230.0
    assert totals["total_nib_employer"] == 14630.0

    rows = {r["employeeName"]: r for r in generated.rendered_data["employeeRows"]}
    assert rows["Latoya Pinder"]["insurableEarnings"] == 100000.0  # 2 runs summed into ONE row
    assert rows["Latoya Pinder"]["nibNumber"] == "NIB-001"
    assert rows["Anton Rolle"]["insurableEarnings"] == 120000.0


def test_generate_bs_c10_excludes_other_months_and_unfinalized_runs(db, organization):
    creator = _make_user(db, "creator_bsc10b@test.com")
    approver = _make_user(db, "approver_bsc10b@test.com")
    _make_company(db, organization.id, country="BS")
    employee = _make_bs_employee(db, organization.id, code="BSC10B")

    _make_bs_run_with_payslip(db, organization.id, employee.id, date(2026, 8, 10), gross_pay=60000)
    _make_bs_run_with_payslip(db, organization.id, employee.id, date(2026, 9, 5), gross_pay=99999)
    _make_bs_run_with_payslip(db, organization.id, employee.id, date(2026, 8, 20), gross_pay=99999, status="Draft")

    template = _build_bs_c10_template(db, creator, approver, key="BS-C10-EXCLUDE-TEST")
    generated = service.generate_bs_c10(db, organization.id, template.id, 2026, 8, actor_id=creator.id)
    assert generated.rendered_data["employerTotals"]["total_insurable_earnings"] == 60000.0
    assert len(generated.rendered_data["employeeRows"]) == 1


def test_generate_bs_c10_rejects_wrong_report_type(db, organization):
    creator = _make_user(db, "creator_bsc10c@test.com")
    approver = _make_user(db, "approver_bsc10c@test.com")
    _make_company(db, organization.id, country="BS")
    template = _build_template(db, creator, approver, country="BS", version="bsc10-neg")
    with pytest.raises(BadRequestException):
        service.generate_bs_c10(db, organization.id, template.id, 2026, 8)


def test_generate_bs_c10_regenerating_supersedes_prior(db, organization):
    creator = _make_user(db, "creator_bsc10d@test.com")
    approver = _make_user(db, "approver_bsc10d@test.com")
    _make_company(db, organization.id, country="BS")
    employee = _make_bs_employee(db, organization.id, code="BSC10D")
    _make_bs_run_with_payslip(db, organization.id, employee.id, date(2026, 8, 10))

    template = _build_bs_c10_template(db, creator, approver, key="BS-C10-SUPERSEDE-TEST")
    first = service.generate_bs_c10(db, organization.id, template.id, 2026, 8, actor_id=creator.id)
    second = service.generate_bs_c10(db, organization.id, template.id, 2026, 8, actor_id=creator.id)
    db.refresh(first)
    assert first.status == "Superseded"
    assert second.status == "Generated"
