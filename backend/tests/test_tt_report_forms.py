"""
tests/test_tt_report_forms.py
------------------------------
Trinidad and Tobago's real named statutory forms (Caribbean forms
gap-closure, country #2, 2026-09-23): Monthly PAYE/Health Surcharge
Return + NIBTT contribution data — both bespoke, per-employee-row
cross-run aggregations (same shape as Guyana's Form 5/NIS Schedule) —
and TD4 (annual employee certificate), which reuses the existing
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


def _make_tt_employee(db, organization_id, code, name="TT Employee", **overrides):
    from app.modules.payroll.models import PayrollEmployee

    fields = dict(compliance_fields={"bir_file_number": "123456789", "nibtt_number": "NIBTT-001"})
    fields.update(overrides)
    employee = PayrollEmployee(organization_id=organization_id, employee_code=code, name=name, **fields)
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


def _make_tt_run_with_payslip(db, organization_id, employee_id, pay_date, *, status="Approved", employee_name="TT Employee", **overrides):
    from app.modules.payroll.models import PayrollRun, PayslipItem

    run = PayrollRun(
        organization_id=organization_id, period_label=str(pay_date),
        period_start=pay_date.replace(day=1), period_end=pay_date, pay_date=pay_date,
        status=status,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    fields = dict(gross_pay=100000, tds=15000, professional_tax=469, social_security=5600, employer_social_security=8400, total_deductions=21069, net_pay=78931)
    fields.update(overrides)
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee_id, organization_id=organization_id,
        employee_name=employee_name, country_code="TT", **fields,
    )
    db.add(item)
    db.commit()
    return run, item


def _build_tt_monthly_return_template(db, creator, approver, key="TT-MONTHLY-RETURN-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="Monthly PAYE / Health Surcharge Return", reportType="TT_MONTHLY_RETURN",
            jurisdictionCountry="TT", reportingYear="2026", documentScope="AGGREGATE",
        ), actor_id=creator.id,
    )
    employer_info = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="employer_info", label="Employer Information"),
        actor_id=creator.id,
    )
    for field_key, label, source_column in (
        ("employer_name", "Employer Name", "name"),
        ("employer_bir_number", "BIR File Number", "tax_no"),
    ):
        service.upsert_report_field(
            db, employer_info.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=label, fieldType="text",
                dataSourceKind="EMPLOYER_PROFILE", sourceColumn=source_column,
            ), actor_id=creator.id,
        )
    totals = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="totals", label="Employer Totals (PAYE / Health Surcharge / NIS)"),
        actor_id=creator.id,
    )
    for field_key, source_column in (
        ("total_employee_count", "gross_pay"),
        ("total_salary_wages", "gross_pay"),
        ("total_paye_tax_deducted", "tds"),
        ("total_health_surcharge", "professional_tax"),
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


def _build_tt_nibtt_data_template(db, creator, approver, key="TT-NIBTT-DATA-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="NIBTT Contribution Data", reportType="TT_NIBTT_DATA",
            jurisdictionCountry="TT", reportingYear="2026", documentScope="AGGREGATE",
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


def _build_tt_td4_template(db, creator, approver, key="TT-TD4-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="TD4", reportType="TD4",
            jurisdictionCountry="TT", reportingYear="2026", documentScope="PER_EMPLOYEE",
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
    tax = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="tax", label="PAYE / Health Surcharge (YTD)"), actor_id=creator.id,
    )
    for field_key, source_column in (("tds_ytd", "tds"), ("professional_tax_ytd", "professional_tax")):
        service.upsert_report_field(
            db, tax.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=field_key, fieldType="currency",
                dataSourceKind="PAYSLIP_ITEM", sourceColumn=source_column, aggregation="SUM_YTD",
            ), actor_id=creator.id,
        )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)
    return template


# ── Monthly PAYE / Health Surcharge Return ───────────────────────────

def test_generate_tt_monthly_return_aggregates_two_employees_across_multiple_runs_same_month(db, organization):
    creator = _make_user(db, "creator_ttmra@test.com")
    approver = _make_user(db, "approver_ttmra@test.com")
    _make_company(db, organization.id, country="TT")
    emp1 = _make_tt_employee(db, organization.id, code="TTMRA1", name="Kavita Ramnarine")
    emp2 = _make_tt_employee(db, organization.id, code="TTMRA2", name="Marcus Bharath")

    _make_tt_run_with_payslip(db, organization.id, emp1.id, date(2026, 4, 7), gross_pay=50000, tds=7000, professional_tax=469, social_security=2800, employer_social_security=4200, employee_name="Kavita Ramnarine")
    _make_tt_run_with_payslip(db, organization.id, emp1.id, date(2026, 4, 14), gross_pay=50000, tds=7000, professional_tax=469, social_security=2800, employer_social_security=4200, employee_name="Kavita Ramnarine")
    _make_tt_run_with_payslip(db, organization.id, emp2.id, date(2026, 4, 21), gross_pay=120000, tds=18000, professional_tax=469, social_security=6720, employer_social_security=10080, employee_name="Marcus Bharath")

    template = _build_tt_monthly_return_template(db, creator, approver)
    generated = service.generate_tt_monthly_return(db, organization.id, template.id, 2026, 4, actor_id=creator.id)

    assert generated.report_type == "TT_MONTHLY_RETURN"
    assert generated.scope_key == "PERIOD:2026-04-01:2026-04-30"
    totals = generated.rendered_data["employerTotals"]
    assert totals["total_employee_count"] == 2
    assert totals["total_salary_wages"] == 220000.0
    assert totals["total_paye_tax_deducted"] == 32000.0
    assert totals["total_health_surcharge"] == 1407.0

    rows = {r["employeeName"]: r for r in generated.rendered_data["employeeRows"]}
    assert rows["Kavita Ramnarine"]["salaryWages"] == 100000.0  # 2 runs summed into ONE row
    assert rows["Kavita Ramnarine"]["birFileNumber"] == "123456789"
    assert rows["Marcus Bharath"]["salaryWages"] == 120000.0


def test_generate_tt_monthly_return_excludes_other_months_and_unfinalized_runs(db, organization):
    creator = _make_user(db, "creator_ttmrb@test.com")
    approver = _make_user(db, "approver_ttmrb@test.com")
    _make_company(db, organization.id, country="TT")
    employee = _make_tt_employee(db, organization.id, code="TTMRB")

    _make_tt_run_with_payslip(db, organization.id, employee.id, date(2026, 4, 10), gross_pay=60000)
    _make_tt_run_with_payslip(db, organization.id, employee.id, date(2026, 5, 5), gross_pay=99999)
    _make_tt_run_with_payslip(db, organization.id, employee.id, date(2026, 4, 20), gross_pay=99999, status="Draft")

    template = _build_tt_monthly_return_template(db, creator, approver, key="TT-MONTHLY-RETURN-EXCLUDE-TEST")
    generated = service.generate_tt_monthly_return(db, organization.id, template.id, 2026, 4, actor_id=creator.id)
    assert generated.rendered_data["employerTotals"]["total_salary_wages"] == 60000.0
    assert len(generated.rendered_data["employeeRows"]) == 1


def test_generate_tt_monthly_return_rejects_wrong_report_type(db, organization):
    creator = _make_user(db, "creator_ttmrc@test.com")
    approver = _make_user(db, "approver_ttmrc@test.com")
    _make_company(db, organization.id, country="TT")
    template = _build_template(db, creator, approver, country="TT", version="ttmr-neg")
    with pytest.raises(BadRequestException):
        service.generate_tt_monthly_return(db, organization.id, template.id, 2026, 4)


def test_generate_tt_monthly_return_regenerating_supersedes_prior(db, organization):
    creator = _make_user(db, "creator_ttmrd@test.com")
    approver = _make_user(db, "approver_ttmrd@test.com")
    _make_company(db, organization.id, country="TT")
    employee = _make_tt_employee(db, organization.id, code="TTMRD")
    _make_tt_run_with_payslip(db, organization.id, employee.id, date(2026, 4, 10))

    template = _build_tt_monthly_return_template(db, creator, approver, key="TT-MONTHLY-RETURN-SUPERSEDE-TEST")
    first = service.generate_tt_monthly_return(db, organization.id, template.id, 2026, 4, actor_id=creator.id)
    second = service.generate_tt_monthly_return(db, organization.id, template.id, 2026, 4, actor_id=creator.id)
    db.refresh(first)
    assert first.status == "Superseded"
    assert second.status == "Generated"


# ── NIBTT contribution data ───────────────────────────────────────────

def test_generate_tt_nibtt_data_buckets_weeks_and_aggregates_employees(db, organization):
    creator = _make_user(db, "creator_ttnis_a@test.com")
    approver = _make_user(db, "approver_ttnis_a@test.com")
    _make_company(db, organization.id, country="TT")
    emp1 = _make_tt_employee(db, organization.id, code="TTNISA1", name="Kavita Ramnarine", compliance_fields={"nibtt_number": "NIBTT-100"})

    # Two weeks within the same month for the same employee — must both
    # be captured (in separate week buckets) AND correctly summed into
    # the employer/employee totals.
    _make_tt_run_with_payslip(db, organization.id, emp1.id, date(2026, 6, 5), gross_pay=25000, social_security=1400, employer_social_security=2100, employee_name="Kavita Ramnarine")
    _make_tt_run_with_payslip(db, organization.id, emp1.id, date(2026, 6, 12), gross_pay=25000, social_security=1400, employer_social_security=2100, employee_name="Kavita Ramnarine")

    template = _build_tt_nibtt_data_template(db, creator, approver)
    generated = service.generate_tt_nibtt_data(db, organization.id, template.id, 2026, 6, actor_id=creator.id)

    assert generated.report_type == "TT_NIBTT_DATA"
    totals = generated.rendered_data["employerTotals"]
    assert totals["total_insurable_earnings"] == 50000.0
    assert totals["total_nis_employee"] == 2800.0
    assert totals["total_nis_employer"] == 4200.0

    row = generated.rendered_data["employeeRows"][0]
    assert row["nibttNumber"] == "NIBTT-100"
    assert row["insurableEarnings"] == 50000.0
    assert "week1" in row["weeks"]
    assert "week2" in row["weeks"]
    assert row["weeks"]["week1"]["earnings"] == 25000.0
    assert row["weeks"]["week2"]["earnings"] == 25000.0


def test_generate_tt_nibtt_data_rejects_wrong_report_type(db, organization):
    creator = _make_user(db, "creator_ttnis_b@test.com")
    approver = _make_user(db, "approver_ttnis_b@test.com")
    _make_company(db, organization.id, country="TT")
    template = _build_template(db, creator, approver, country="TT", version="ttnis-neg")
    with pytest.raises(BadRequestException):
        service.generate_tt_nibtt_data(db, organization.id, template.id, 2026, 6)


# ── TD4 (generic mapper reuse) ────────────────────────────────────────

def test_generate_tt_td4_sums_ytd_via_generic_mapper(db, organization):
    creator = _make_user(db, "creator_tttd4_a@test.com")
    approver = _make_user(db, "approver_tttd4_a@test.com")
    _make_company(db, organization.id, country="TT")
    employee = _make_tt_employee(db, organization.id, code="TTTD4A", name="Kavita Ramnarine")

    _make_tt_run_with_payslip(db, organization.id, employee.id, date(2026, 1, 31), gross_pay=100000, tds=14000, professional_tax=469, employee_name="Kavita Ramnarine")
    _make_tt_run_with_payslip(db, organization.id, employee.id, date(2026, 2, 28), gross_pay=100000, tds=14000, professional_tax=469, employee_name="Kavita Ramnarine")

    template = _build_tt_td4_template(db, creator, approver)
    generated = service.generate_uk_employee_report(
        db, organization.id, template.id, employee.id, date(2026, 12, 31), actor_id=creator.id,
    )
    assert generated.report_type == "TD4"
    values = generated.rendered_data["employees"][0]["values"]
    assert values["employee_name"] == "Kavita Ramnarine"
    assert values["tds_ytd"] == 28000.0
    assert values["professional_tax_ytd"] == 938.0
