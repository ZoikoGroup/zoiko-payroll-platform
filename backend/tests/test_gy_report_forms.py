"""
tests/test_gy_report_forms.py
------------------------------
Guyana's real named statutory forms (Caribbean forms gap-closure,
2026-09-22): GRA Form 5 (monthly PAYE return) + NIS Electronic Schedule
(monthly) — both bespoke, per-employee-row cross-run aggregations, the
exact class of bug generate_us_941 already guards against (a missed
wiring point silently drops or double-counts an employee/period) — and
Form 7B (annual employee earnings statement), which reuses the existing
generic generate_uk_employee_report mapper unchanged.
"""
from datetime import date

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import service
from app.modules.payroll.schemas import (
    ReportTemplateUpsert, ReportTemplateComponentUpsert, ReportTemplateFieldUpsert,
)

from tests.test_report_templates import _make_user, _make_company, _build_template


def _make_gy_employee(db, organization_id, code, name="GY Employee", **overrides):
    from app.modules.payroll.models import PayrollEmployee

    fields = dict(compliance_fields={"gra_tin": "1234567", "nis_number": "NIS-001"})
    fields.update(overrides)
    employee = PayrollEmployee(organization_id=organization_id, employee_code=code, name=name, **fields)
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


def _make_gy_run_with_payslip(db, organization_id, employee_id, pay_date, *, status="Approved", employee_name="GY Employee", **overrides):
    from app.modules.payroll.models import PayrollRun, PayslipItem

    run = PayrollRun(
        organization_id=organization_id, period_label=str(pay_date),
        period_start=pay_date.replace(day=1), period_end=pay_date, pay_date=pay_date,
        status=status,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    fields = dict(gross_pay=100000, tds=15000, social_security=5600, employer_social_security=8400, total_deductions=20600, net_pay=79400)
    fields.update(overrides)
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee_id, organization_id=organization_id,
        employee_name=employee_name, country_code="GY", **fields,
    )
    db.add(item)
    db.commit()
    return run, item


def _build_gy_form_5_template(db, creator, approver, key="GY-FORM-5-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="GRA Form 5", reportType="GY_FORM_5",
            jurisdictionCountry="GY", reportingYear="2026", documentScope="AGGREGATE",
        ), actor_id=creator.id,
    )
    employer_info = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="employer_info", label="Employer Information"),
        actor_id=creator.id,
    )
    for field_key, label, source_column in (
        ("employer_name", "Employer Name", "name"),
        ("employer_gra_tin", "GRA TIN", "tax_no"),
    ):
        service.upsert_report_field(
            db, employer_info.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=label, fieldType="text",
                dataSourceKind="EMPLOYER_PROFILE", sourceColumn=source_column,
            ), actor_id=creator.id,
        )
    totals = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="totals", label="Employer Totals (PAYE / NIS)"), actor_id=creator.id,
    )
    for field_key, source_column in (
        ("total_employee_count", "gross_pay"),
        ("total_salary_wages", "gross_pay"),
        ("total_paye_tax_deducted", "tds"),
        ("total_nis_employee", "social_security"),
        ("total_nis_employer", "employer_social_security"),
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


def _build_gy_nis_schedule_template(db, creator, approver, key="GY-NIS-SCHEDULE-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="NIS Electronic Schedule", reportType="GY_NIS_SCHEDULE",
            jurisdictionCountry="GY", reportingYear="2026", documentScope="AGGREGATE",
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
        db, template.id, ReportTemplateComponentUpsert(componentKey="totals", label="Employer Totals (Insurable Earnings / NIS)"),
        actor_id=creator.id,
    )
    for field_key, source_column in (
        ("total_employee_count", "gross_pay"),
        ("total_insurable_earnings", "gross_pay"),
        ("total_nis_employee", "social_security"),
        ("total_nis_employer", "employer_social_security"),
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


def _build_gy_form_7b_template(db, creator, approver, key="GY-FORM-7B-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="Form 7B", reportType="FORM_7B",
            jurisdictionCountry="GY", reportingYear="2026", documentScope="PER_EMPLOYEE",
        ), actor_id=creator.id,
    )
    employee_info = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="employee_info", label="Employee Information"),
        actor_id=creator.id,
    )
    service.upsert_report_field(
        db, employee_info.id, ReportTemplateFieldUpsert(
            fieldKey="employee_name", label="Employee Name", fieldType="text",
            dataSourceKind="PAYROLL_EMPLOYEE", sourceColumn="name",
        ), actor_id=creator.id,
    )
    earnings = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="earnings", label="Earnings (YTD)"), actor_id=creator.id,
    )
    service.upsert_report_field(
        db, earnings.id, ReportTemplateFieldUpsert(
            fieldKey="gross_pay_ytd", label="Gross Pay YTD", fieldType="currency",
            dataSourceKind="PAYSLIP_ITEM", sourceColumn="gross_pay", aggregation="SUM_YTD",
        ), actor_id=creator.id,
    )
    tax = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="tax", label="PAYE (YTD)"), actor_id=creator.id,
    )
    service.upsert_report_field(
        db, tax.id, ReportTemplateFieldUpsert(
            fieldKey="tds_ytd", label="PAYE YTD", fieldType="currency",
            dataSourceKind="PAYSLIP_ITEM", sourceColumn="tds", aggregation="SUM_YTD",
        ), actor_id=creator.id,
    )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)
    return template


# ── GRA Form 5 ────────────────────────────────────────────────────────

def test_generate_gy_form_5_aggregates_two_employees_across_multiple_runs_same_month(db, organization):
    creator = _make_user(db, "creator_gyf5a@test.com")
    approver = _make_user(db, "approver_gyf5a@test.com")
    _make_company(db, organization.id, country="GY")
    emp1 = _make_gy_employee(db, organization.id, code="GYF5A1", name="Amara Singh")
    emp2 = _make_gy_employee(db, organization.id, code="GYF5A2", name="Rohan Persaud")

    # emp1 is paid weekly — two runs land in the same calendar month and
    # must be SUMMED for that one employee, not treated as two rows.
    _make_gy_run_with_payslip(db, organization.id, emp1.id, date(2026, 3, 7), gross_pay=50000, tds=7000, social_security=2800, employer_social_security=4200, employee_name="Amara Singh")
    _make_gy_run_with_payslip(db, organization.id, emp1.id, date(2026, 3, 14), gross_pay=50000, tds=7000, social_security=2800, employer_social_security=4200, employee_name="Amara Singh")
    _make_gy_run_with_payslip(db, organization.id, emp2.id, date(2026, 3, 21), gross_pay=120000, tds=18000, social_security=6720, employer_social_security=10080, employee_name="Rohan Persaud")

    template = _build_gy_form_5_template(db, creator, approver)
    generated = service.generate_gy_form_5(db, organization.id, template.id, 2026, 3, actor_id=creator.id)

    assert generated.report_type == "GY_FORM_5"
    assert generated.payroll_run_id is None
    assert generated.scope_key == "PERIOD:2026-03-01:2026-03-31"
    assert generated.reporting_period == "2026-03"

    totals = generated.rendered_data["employerTotals"]
    assert totals["total_employee_count"] == 2
    assert totals["total_salary_wages"] == 220000.0
    assert totals["total_paye_tax_deducted"] == 32000.0
    assert totals["total_nis_employee"] == 12320.0
    assert totals["total_nis_employer"] == 18480.0

    rows = {r["employeeName"]: r for r in generated.rendered_data["employeeRows"]}
    assert rows["Amara Singh"]["salaryWages"] == 100000.0  # 2 runs summed into ONE row
    assert rows["Amara Singh"]["payeTaxDeducted"] == 14000.0
    assert rows["Amara Singh"]["graTin"] == "1234567"
    assert rows["Rohan Persaud"]["salaryWages"] == 120000.0


def test_generate_gy_form_5_excludes_other_months_and_unfinalized_runs(db, organization):
    creator = _make_user(db, "creator_gyf5b@test.com")
    approver = _make_user(db, "approver_gyf5b@test.com")
    _make_company(db, organization.id, country="GY")
    employee = _make_gy_employee(db, organization.id, code="GYF5B")

    _make_gy_run_with_payslip(db, organization.id, employee.id, date(2026, 3, 10), gross_pay=60000)
    # Outside March — must NOT be summed in.
    _make_gy_run_with_payslip(db, organization.id, employee.id, date(2026, 4, 5), gross_pay=99999)
    # Still Draft — must NOT be summed in.
    _make_gy_run_with_payslip(db, organization.id, employee.id, date(2026, 3, 20), gross_pay=99999, status="Draft")

    template = _build_gy_form_5_template(db, creator, approver, key="GY-FORM-5-EXCLUDE-TEST")
    generated = service.generate_gy_form_5(db, organization.id, template.id, 2026, 3, actor_id=creator.id)
    assert generated.rendered_data["employerTotals"]["total_salary_wages"] == 60000.0
    assert len(generated.rendered_data["employeeRows"]) == 1


def test_generate_gy_form_5_rejects_wrong_report_type(db, organization):
    creator = _make_user(db, "creator_gyf5c@test.com")
    approver = _make_user(db, "approver_gyf5c@test.com")
    _make_company(db, organization.id, country="GY")
    template = _build_template(db, creator, approver, country="GY", version="gyf5-neg")  # TDS, not GY_FORM_5
    with pytest.raises(BadRequestException):
        service.generate_gy_form_5(db, organization.id, template.id, 2026, 3)


def test_generate_gy_form_5_regenerating_supersedes_prior(db, organization):
    creator = _make_user(db, "creator_gyf5d@test.com")
    approver = _make_user(db, "approver_gyf5d@test.com")
    _make_company(db, organization.id, country="GY")
    employee = _make_gy_employee(db, organization.id, code="GYF5D")
    _make_gy_run_with_payslip(db, organization.id, employee.id, date(2026, 3, 10))

    template = _build_gy_form_5_template(db, creator, approver, key="GY-FORM-5-SUPERSEDE-TEST")
    first = service.generate_gy_form_5(db, organization.id, template.id, 2026, 3, actor_id=creator.id)
    second = service.generate_gy_form_5(db, organization.id, template.id, 2026, 3, actor_id=creator.id)
    db.refresh(first)
    assert first.status == "Superseded"
    assert second.status == "Generated"


# ── NIS Electronic Schedule ──────────────────────────────────────────

def test_generate_gy_nis_schedule_aggregates_employees_for_the_month(db, organization):
    creator = _make_user(db, "creator_gynis_a@test.com")
    approver = _make_user(db, "approver_gynis_a@test.com")
    _make_company(db, organization.id, country="GY")
    emp1 = _make_gy_employee(db, organization.id, code="GYNISA1", name="Amara Singh", compliance_fields={"nis_number": "NIS-100"})
    emp2 = _make_gy_employee(db, organization.id, code="GYNISA2", name="Rohan Persaud", compliance_fields={"nis_number": "NIS-200"})

    _make_gy_run_with_payslip(db, organization.id, emp1.id, date(2026, 5, 8), gross_pay=70000, social_security=3920, employer_social_security=5880, employee_name="Amara Singh")
    _make_gy_run_with_payslip(db, organization.id, emp2.id, date(2026, 5, 22), gross_pay=90000, social_security=5040, employer_social_security=7560, employee_name="Rohan Persaud")

    template = _build_gy_nis_schedule_template(db, creator, approver)
    generated = service.generate_gy_nis_schedule(db, organization.id, template.id, 2026, 5, actor_id=creator.id)

    assert generated.report_type == "GY_NIS_SCHEDULE"
    totals = generated.rendered_data["employerTotals"]
    assert totals["total_employee_count"] == 2
    assert totals["total_insurable_earnings"] == 160000.0
    assert totals["total_nis_employee"] == 8960.0
    assert totals["total_nis_employer"] == 13440.0

    rows = {r["employeeName"]: r for r in generated.rendered_data["employeeRows"]}
    assert rows["Amara Singh"]["nisNumber"] == "NIS-100"
    assert rows["Amara Singh"]["insurableEarnings"] == 70000.0


def test_generate_gy_nis_schedule_rejects_wrong_report_type(db, organization):
    creator = _make_user(db, "creator_gynis_b@test.com")
    approver = _make_user(db, "approver_gynis_b@test.com")
    _make_company(db, organization.id, country="GY")
    template = _build_template(db, creator, approver, country="GY", version="gynis-neg")
    with pytest.raises(BadRequestException):
        service.generate_gy_nis_schedule(db, organization.id, template.id, 2026, 5)


# ── Form 7B (generic mapper reuse) ───────────────────────────────────

def test_generate_gy_form_7b_sums_ytd_via_generic_mapper(db, organization):
    creator = _make_user(db, "creator_gy7b_a@test.com")
    approver = _make_user(db, "approver_gy7b_a@test.com")
    _make_company(db, organization.id, country="GY")
    employee = _make_gy_employee(db, organization.id, code="GY7BA", name="Amara Singh")

    _make_gy_run_with_payslip(db, organization.id, employee.id, date(2026, 1, 31), gross_pay=100000, tds=14000, employee_name="Amara Singh")
    _make_gy_run_with_payslip(db, organization.id, employee.id, date(2026, 2, 28), gross_pay=100000, tds=14000, employee_name="Amara Singh")

    template = _build_gy_form_7b_template(db, creator, approver)
    generated = service.generate_uk_employee_report(
        db, organization.id, template.id, employee.id, date(2026, 12, 31), actor_id=creator.id,
    )
    assert generated.report_type == "FORM_7B"
    values = generated.rendered_data["employees"][0]["values"]
    assert values["employee_name"] == "Amara Singh"
    assert values["gross_pay_ytd"] == 200000.0
    assert values["tds_ytd"] == 28000.0
