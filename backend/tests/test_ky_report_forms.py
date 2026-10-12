"""
tests/test_ky_report_forms.py
------------------------------
Cayman Islands's real named statutory forms (Caribbean forms
gap-closure, country #7 — the last of the 7, 2026-09-23): Wage/
Gratuity Statement (per-employee, per-run — uses the existing fully
generic generate_report_from_template mapper unchanged, gratuity
itself not populated) and monthly Pension contribution submission
(bespoke, per-employee-row cross-run aggregation, same shape as the
prior 6 countries).
"""
from datetime import date

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import service
from app.modules.payroll.schemas import (
    ReportTemplateUpsert, ReportTemplateComponentUpsert, ReportTemplateFieldUpsert,
)

from tests.test_report_templates import _make_user, _make_company, _build_template


def _make_ky_employee(db, organization_id, code, name="KY Employee", **overrides):
    from app.modules.payroll.models import PayrollEmployee

    fields = dict(compliance_fields={"nib_member_number": "PENSION-001"})
    fields.update(overrides)
    employee = PayrollEmployee(organization_id=organization_id, employee_code=code, name=name, **fields)
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


def _make_ky_run_with_payslip(db, organization_id, employee_id, pay_date, *, status="Approved", employee_name="KY Employee", **overrides):
    from app.modules.payroll.models import PayrollRun, PayslipItem

    run = PayrollRun(
        organization_id=organization_id, period_label=str(pay_date),
        period_start=pay_date.replace(day=1), period_end=pay_date, pay_date=pay_date,
        status=status,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    fields = dict(gross_pay=100000, employee_pension=5000, employer_pension=5000, total_deductions=5000, net_pay=95000)
    fields.update(overrides)
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee_id, organization_id=organization_id,
        employee_name=employee_name, country_code="KY", **fields,
    )
    db.add(item)
    db.commit()
    return run, item


def _build_ky_wage_gratuity_template(db, creator, approver, key="KY-WAGE-GRATUITY-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="Wage / Gratuity Statement", reportType="KY_WAGE_GRATUITY_STATEMENT",
            jurisdictionCountry="KY", reportingYear="2026", documentScope="PER_EMPLOYEE",
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
    employee_info = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="employee_info", label="Employee Information"),
        actor_id=creator.id,
    )
    service.upsert_report_field(
        db, employee_info.id, ReportTemplateFieldUpsert(
            fieldKey="employee_name", label="Employee Name", fieldType="text",
            dataSourceKind="PAYSLIP_ITEM", sourceColumn="employee_name",
        ), actor_id=creator.id,
    )
    earnings = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="earnings", label="Wages"), actor_id=creator.id,
    )
    service.upsert_report_field(
        db, earnings.id, ReportTemplateFieldUpsert(
            fieldKey="gross_pay", label="Gross Pay", fieldType="currency",
            dataSourceKind="PAYSLIP_ITEM", sourceColumn="gross_pay",
        ), actor_id=creator.id,
    )
    contributions = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="contributions", label="Mandatory Pension (Employee)"), actor_id=creator.id,
    )
    service.upsert_report_field(
        db, contributions.id, ReportTemplateFieldUpsert(
            fieldKey="employee_pension", label="Mandatory Pension (Employee)", fieldType="currency",
            dataSourceKind="PAYSLIP_ITEM", sourceColumn="employee_pension",
        ), actor_id=creator.id,
    )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    return template


def _build_ky_pension_submission_template(db, creator, approver, key="KY-PENSION-SUBMISSION-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="Monthly Pension Contribution Submission", reportType="KY_PENSION_SUBMISSION",
            jurisdictionCountry="KY", reportingYear="2026", documentScope="AGGREGATE",
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
        db, template.id, ReportTemplateComponentUpsert(componentKey="totals", label="Employer Totals (Pensionable Earnings / Pension)"),
        actor_id=creator.id,
    )
    for field_key, source_column in (
        ("total_employee_count", "gross_pay"),
        ("total_pensionable_earnings", "gross_pay"),
        ("total_pension_employee", "employee_pension"),
        ("total_pension_employer", "employer_pension"),
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


# ── Wage/Gratuity Statement (generic mapper reuse) ────────────────────

def test_generate_ky_wage_gratuity_statement_via_generic_mapper(db, organization):
    creator = _make_user(db, "creator_kywg_a@test.com")
    approver = _make_user(db, "approver_kywg_a@test.com")
    _make_company(db, organization.id, country="KY")
    employee = _make_ky_employee(db, organization.id, code="KYWGA", name="Trevor Ebanks")
    run, item = _make_ky_run_with_payslip(db, organization.id, employee.id, date(2026, 10, 31), gross_pay=80000, employee_pension=4000, employer_pension=4000, employee_name="Trevor Ebanks")

    template = _build_ky_wage_gratuity_template(db, creator, approver)
    generated = service.generate_report_from_template(db, organization.id, template.id, run.id, actor_id=creator.id)

    assert generated.report_type == "KY_WAGE_GRATUITY_STATEMENT"
    assert generated.payroll_run_id == run.id


def test_generate_ky_wage_gratuity_statement_blocked_for_unfinalized_run(db, organization):
    creator = _make_user(db, "creator_kywg_b@test.com")
    approver = _make_user(db, "approver_kywg_b@test.com")
    _make_company(db, organization.id, country="KY")
    employee = _make_ky_employee(db, organization.id, code="KYWGB")
    run, item = _make_ky_run_with_payslip(db, organization.id, employee.id, date(2026, 10, 31), status="Draft")

    template = _build_ky_wage_gratuity_template(db, creator, approver, key="KY-WAGE-GRATUITY-BLOCKED-TEST")
    with pytest.raises(BadRequestException):
        service.generate_report_from_template(db, organization.id, template.id, run.id, actor_id=creator.id)


# ── Monthly Pension contribution submission ───────────────────────────

def test_generate_ky_pension_submission_aggregates_two_employees_across_multiple_runs_same_month(db, organization):
    creator = _make_user(db, "creator_kyps_a@test.com")
    approver = _make_user(db, "approver_kyps_a@test.com")
    _make_company(db, organization.id, country="KY")
    emp1 = _make_ky_employee(db, organization.id, code="KYPSA1", name="Trevor Ebanks")
    emp2 = _make_ky_employee(db, organization.id, code="KYPSA2", name="Marlene Bodden")

    _make_ky_run_with_payslip(db, organization.id, emp1.id, date(2026, 11, 7), gross_pay=50000, employee_pension=2500, employer_pension=2500, employee_name="Trevor Ebanks")
    _make_ky_run_with_payslip(db, organization.id, emp1.id, date(2026, 11, 14), gross_pay=50000, employee_pension=2500, employer_pension=2500, employee_name="Trevor Ebanks")
    _make_ky_run_with_payslip(db, organization.id, emp2.id, date(2026, 11, 21), gross_pay=120000, employee_pension=6000, employer_pension=6000, employee_name="Marlene Bodden")

    template = _build_ky_pension_submission_template(db, creator, approver)
    generated = service.generate_ky_pension_submission(db, organization.id, template.id, 2026, 11, actor_id=creator.id)

    assert generated.report_type == "KY_PENSION_SUBMISSION"
    assert generated.scope_key == "PERIOD:2026-11-01:2026-11-30"
    totals = generated.rendered_data["employerTotals"]
    assert totals["total_employee_count"] == 2
    assert totals["total_pensionable_earnings"] == 220000.0
    assert totals["total_pension_employee"] == 11000.0
    assert totals["total_pension_employer"] == 11000.0

    rows = {r["employeeName"]: r for r in generated.rendered_data["employeeRows"]}
    assert rows["Trevor Ebanks"]["pensionableEarnings"] == 100000.0  # 2 runs summed into ONE row
    assert rows["Trevor Ebanks"]["pensionMemberNumber"] == "PENSION-001"
    assert rows["Marlene Bodden"]["pensionableEarnings"] == 120000.0


def test_generate_ky_pension_submission_excludes_other_months_and_unfinalized_runs(db, organization):
    creator = _make_user(db, "creator_kyps_b@test.com")
    approver = _make_user(db, "approver_kyps_b@test.com")
    _make_company(db, organization.id, country="KY")
    employee = _make_ky_employee(db, organization.id, code="KYPSB")

    _make_ky_run_with_payslip(db, organization.id, employee.id, date(2026, 11, 10), gross_pay=60000)
    _make_ky_run_with_payslip(db, organization.id, employee.id, date(2026, 12, 5), gross_pay=99999)
    _make_ky_run_with_payslip(db, organization.id, employee.id, date(2026, 11, 20), gross_pay=99999, status="Draft")

    template = _build_ky_pension_submission_template(db, creator, approver, key="KY-PENSION-SUBMISSION-EXCLUDE-TEST")
    generated = service.generate_ky_pension_submission(db, organization.id, template.id, 2026, 11, actor_id=creator.id)
    assert generated.rendered_data["employerTotals"]["total_pensionable_earnings"] == 60000.0
    assert len(generated.rendered_data["employeeRows"]) == 1


def test_generate_ky_pension_submission_rejects_wrong_report_type(db, organization):
    creator = _make_user(db, "creator_kyps_c@test.com")
    approver = _make_user(db, "approver_kyps_c@test.com")
    _make_company(db, organization.id, country="KY")
    template = _build_template(db, creator, approver, country="KY", version="kyps-neg")
    with pytest.raises(BadRequestException):
        service.generate_ky_pension_submission(db, organization.id, template.id, 2026, 11)


def test_generate_ky_pension_submission_regenerating_supersedes_prior(db, organization):
    creator = _make_user(db, "creator_kyps_d@test.com")
    approver = _make_user(db, "approver_kyps_d@test.com")
    _make_company(db, organization.id, country="KY")
    employee = _make_ky_employee(db, organization.id, code="KYPSD")
    _make_ky_run_with_payslip(db, organization.id, employee.id, date(2026, 11, 10))

    template = _build_ky_pension_submission_template(db, creator, approver, key="KY-PENSION-SUBMISSION-SUPERSEDE-TEST")
    first = service.generate_ky_pension_submission(db, organization.id, template.id, 2026, 11, actor_id=creator.id)
    second = service.generate_ky_pension_submission(db, organization.id, template.id, 2026, 11, actor_id=creator.id)
    db.refresh(first)
    assert first.status == "Superseded"
    assert second.status == "Generated"
