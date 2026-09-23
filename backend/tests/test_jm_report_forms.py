"""
tests/test_jm_report_forms.py
------------------------------
Jamaica's real named statutory forms (Caribbean forms gap-closure,
country #3, 2026-09-23): S01 (monthly PAYE/NIS/NHT/Education Tax/HEART
return) and S02 (annual employer return) — both bespoke, per-employee-
row cross-run aggregations (same shape as Guyana's Form 5 and
Trinidad's Monthly Return), with HEART deliberately shown as an
EMPLOYER-ONLY total (never attributed to any one employee's row, since
it's already correctly aggregated across the whole employer's payroll
by the org-levy accumulator, JM-008).
"""
from datetime import date

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import service
from app.modules.payroll.schemas import (
    ReportTemplateUpsert, ReportTemplateComponentUpsert, ReportTemplateFieldUpsert,
)

from tests.test_report_templates import _make_user, _make_company, _build_template


def _make_jm_employee(db, organization_id, code, name="JM Employee", **overrides):
    from app.modules.payroll.models import PayrollEmployee

    fields = dict(compliance_fields={"trn": "123456789"})
    fields.update(overrides)
    employee = PayrollEmployee(organization_id=organization_id, employee_code=code, name=name, **fields)
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


def _make_jm_run_with_payslip(db, organization_id, employee_id, pay_date, *, status="Approved", employee_name="JM Employee", **overrides):
    from app.modules.payroll.models import PayrollRun, PayslipItem

    run = PayrollRun(
        organization_id=organization_id, period_label=str(pay_date),
        period_start=pay_date.replace(day=1), period_end=pay_date, pay_date=pay_date,
        status=status,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    fields = dict(
        gross_pay=100000, tds=15000, social_security=3000, employer_social_security=3000,
        employee_pension=2000, employer_pension=3000, ni_employee=1250, employer_ni=1250,
        employer_payroll_tax=0, total_deductions=24250, net_pay=75750,
    )
    fields.update(overrides)
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee_id, organization_id=organization_id,
        employee_name=employee_name, country_code="JM", **fields,
    )
    db.add(item)
    db.commit()
    return run, item


def _jm_totals_fields():
    return (
        ("total_employee_count", "gross_pay"),
        ("total_salary_wages", "gross_pay"),
        ("total_paye_tax_deducted", "tds"),
        ("total_nis_employee", "social_security"),
        ("total_nis_employer", "employer_social_security"),
        ("total_nht_employee", "employee_pension"),
        ("total_nht_employer", "employer_pension"),
        ("total_education_tax_employee", "ni_employee"),
        ("total_education_tax_employer", "employer_ni"),
        ("total_heart_employer", "employer_payroll_tax"),
    )


def _build_jm_s01_template(db, creator, approver, key="JM-S01-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="S01", reportType="JM_S01",
            jurisdictionCountry="JM", reportingYear="2026", documentScope="AGGREGATE",
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
        db, template.id, ReportTemplateComponentUpsert(componentKey="totals", label="Employer Totals"), actor_id=creator.id,
    )
    for field_key, source_column in _jm_totals_fields():
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


def _build_jm_s02_template(db, creator, approver, key="JM-S02-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="S02", reportType="JM_S02",
            jurisdictionCountry="JM", reportingYear="2026", documentScope="AGGREGATE",
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
        db, template.id, ReportTemplateComponentUpsert(componentKey="totals", label="Employer Totals"), actor_id=creator.id,
    )
    for field_key, source_column in _jm_totals_fields():
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


# ── S01 ────────────────────────────────────────────────────────────────

def test_generate_jm_s01_aggregates_two_employees_and_attributes_heart_employer_only(db, organization):
    creator = _make_user(db, "creator_jms01a@test.com")
    approver = _make_user(db, "approver_jms01a@test.com")
    _make_company(db, organization.id, country="JM")
    emp1 = _make_jm_employee(db, organization.id, code="JMS01A1", name="Andrea Clarke")
    emp2 = _make_jm_employee(db, organization.id, code="JMS01A2", name="Tyrone Bailey")

    _make_jm_run_with_payslip(db, organization.id, emp1.id, date(2026, 5, 7), gross_pay=50000, tds=7000, social_security=1500, employer_social_security=1500, employee_pension=1000, employer_pension=1500, ni_employee=625, employer_ni=625, employer_payroll_tax=0, employee_name="Andrea Clarke")
    _make_jm_run_with_payslip(db, organization.id, emp1.id, date(2026, 5, 14), gross_pay=50000, tds=7000, social_security=1500, employer_social_security=1500, employee_pension=1000, employer_pension=1500, ni_employee=625, employer_ni=625, employer_payroll_tax=0, employee_name="Andrea Clarke")
    _make_jm_run_with_payslip(db, organization.id, emp2.id, date(2026, 5, 21), gross_pay=120000, tds=18000, social_security=3600, employer_social_security=3600, employee_pension=2400, employer_pension=3600, ni_employee=1500, employer_ni=1500, employer_payroll_tax=450, employee_name="Tyrone Bailey")

    template = _build_jm_s01_template(db, creator, approver)
    generated = service.generate_jm_s01(db, organization.id, template.id, 2026, 5, actor_id=creator.id)

    assert generated.report_type == "JM_S01"
    assert generated.scope_key == "PERIOD:2026-05-01:2026-05-31"
    totals = generated.rendered_data["employerTotals"]
    assert totals["total_employee_count"] == 2
    assert totals["total_salary_wages"] == 220000.0
    assert totals["total_heart_employer"] == 450.0

    rows = {r["employeeName"]: r for r in generated.rendered_data["employeeRows"]}
    assert rows["Andrea Clarke"]["salaryWages"] == 100000.0  # 2 runs summed into ONE row
    assert rows["Andrea Clarke"]["trn"] == "123456789"
    assert "heart" not in str(rows["Andrea Clarke"]).lower()  # HEART never on an employee row
    assert rows["Tyrone Bailey"]["salaryWages"] == 120000.0


def test_generate_jm_s01_excludes_other_months_and_unfinalized_runs(db, organization):
    creator = _make_user(db, "creator_jms01b@test.com")
    approver = _make_user(db, "approver_jms01b@test.com")
    _make_company(db, organization.id, country="JM")
    employee = _make_jm_employee(db, organization.id, code="JMS01B")

    _make_jm_run_with_payslip(db, organization.id, employee.id, date(2026, 5, 10), gross_pay=60000)
    _make_jm_run_with_payslip(db, organization.id, employee.id, date(2026, 6, 5), gross_pay=99999)
    _make_jm_run_with_payslip(db, organization.id, employee.id, date(2026, 5, 20), gross_pay=99999, status="Draft")

    template = _build_jm_s01_template(db, creator, approver, key="JM-S01-EXCLUDE-TEST")
    generated = service.generate_jm_s01(db, organization.id, template.id, 2026, 5, actor_id=creator.id)
    assert generated.rendered_data["employerTotals"]["total_salary_wages"] == 60000.0
    assert len(generated.rendered_data["employeeRows"]) == 1


def test_generate_jm_s01_rejects_wrong_report_type(db, organization):
    creator = _make_user(db, "creator_jms01c@test.com")
    approver = _make_user(db, "approver_jms01c@test.com")
    _make_company(db, organization.id, country="JM")
    template = _build_template(db, creator, approver, country="JM", version="jms01-neg")
    with pytest.raises(BadRequestException):
        service.generate_jm_s01(db, organization.id, template.id, 2026, 5)


def test_generate_jm_s01_regenerating_supersedes_prior(db, organization):
    creator = _make_user(db, "creator_jms01d@test.com")
    approver = _make_user(db, "approver_jms01d@test.com")
    _make_company(db, organization.id, country="JM")
    employee = _make_jm_employee(db, organization.id, code="JMS01D")
    _make_jm_run_with_payslip(db, organization.id, employee.id, date(2026, 5, 10))

    template = _build_jm_s01_template(db, creator, approver, key="JM-S01-SUPERSEDE-TEST")
    first = service.generate_jm_s01(db, organization.id, template.id, 2026, 5, actor_id=creator.id)
    second = service.generate_jm_s01(db, organization.id, template.id, 2026, 5, actor_id=creator.id)
    db.refresh(first)
    assert first.status == "Superseded"
    assert second.status == "Generated"


# ── S02 ────────────────────────────────────────────────────────────────

def test_generate_jm_s02_aggregates_across_the_full_calendar_year(db, organization):
    creator = _make_user(db, "creator_jms02a@test.com")
    approver = _make_user(db, "approver_jms02a@test.com")
    _make_company(db, organization.id, country="JM")
    employee = _make_jm_employee(db, organization.id, code="JMS02A", name="Andrea Clarke")

    _make_jm_run_with_payslip(db, organization.id, employee.id, date(2026, 1, 31), gross_pay=100000, tds=15000, employee_name="Andrea Clarke")
    _make_jm_run_with_payslip(db, organization.id, employee.id, date(2026, 6, 30), gross_pay=100000, tds=15000, employee_name="Andrea Clarke")
    _make_jm_run_with_payslip(db, organization.id, employee.id, date(2026, 12, 31), gross_pay=100000, tds=15000, employee_name="Andrea Clarke")
    # Prior year — must NOT be summed in.
    _make_jm_run_with_payslip(db, organization.id, employee.id, date(2025, 12, 31), gross_pay=99999, employee_name="Andrea Clarke")

    template = _build_jm_s02_template(db, creator, approver)
    generated = service.generate_jm_s02(db, organization.id, template.id, 2026, actor_id=creator.id)

    assert generated.report_type == "JM_S02"
    assert generated.scope_key == "PERIOD:2026-01-01:2026-12-31"
    assert generated.reporting_period is None
    totals = generated.rendered_data["employerTotals"]
    assert totals["total_salary_wages"] == 300000.0
    assert totals["total_paye_tax_deducted"] == 45000.0
    assert len(generated.rendered_data["employeeRows"]) == 1


def test_generate_jm_s02_rejects_wrong_report_type(db, organization):
    creator = _make_user(db, "creator_jms02b@test.com")
    approver = _make_user(db, "approver_jms02b@test.com")
    _make_company(db, organization.id, country="JM")
    template = _build_template(db, creator, approver, country="JM", version="jms02-neg")
    with pytest.raises(BadRequestException):
        service.generate_jm_s02(db, organization.id, template.id, 2026)
