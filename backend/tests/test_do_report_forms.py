"""
tests/test_do_report_forms.py
------------------------------
Dominican Republic's real named statutory forms (Caribbean forms
gap-closure, country #5, 2026-09-23): DGII IR-3 (monthly withholding
declaration) + TSS/SUIR contribution submission — both bespoke,
per-employee-row cross-run aggregations (same shape as Guyana's Form
5/Trinidad's Monthly Return/Jamaica's S01/Barbados's TAMIS return) —
and IR-13 (annual withholding declaration), which reuses the existing
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


def _make_do_employee(db, organization_id, code, name="DO Employee", **overrides):
    from app.modules.payroll.models import PayrollEmployee

    fields = dict(compliance_fields={"cedula": "001-1234567-8"})
    fields.update(overrides)
    employee = PayrollEmployee(organization_id=organization_id, employee_code=code, name=name, **fields)
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


def _make_do_run_with_payslip(db, organization_id, employee_id, pay_date, *, status="Approved", employee_name="DO Employee", **overrides):
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
        gross_pay=100000, tds=12000, social_security=3800, employer_social_security=3800,
        employee_pension=2870, employer_pension=2870, employer_payroll_tax=1780, employer_ni=1000,
        total_deductions=18670, net_pay=81330,
    )
    fields.update(overrides)
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee_id, organization_id=organization_id,
        employee_name=employee_name, country_code="DO", **fields,
    )
    db.add(item)
    db.commit()
    return run, item


def _build_do_ir3_template(db, creator, approver, key="DO-IR3-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="DGII IR-3", reportType="DO_IR3",
            jurisdictionCountry="DO", reportingYear="2026", documentScope="AGGREGATE",
        ), actor_id=creator.id,
    )
    employer_info = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="employer_info", label="Employer Information"),
        actor_id=creator.id,
    )
    for field_key, label, source_column in (
        ("employer_name", "Employer Name", "name"),
        ("employer_rnc", "RNC", "tax_no"),
    ):
        service.upsert_report_field(
            db, employer_info.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=label, fieldType="text",
                dataSourceKind="EMPLOYER_PROFILE", sourceColumn=source_column,
            ), actor_id=creator.id,
        )
    totals = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="totals", label="Employer Totals (Gross Pay / ISR)"),
        actor_id=creator.id,
    )
    for field_key, source_column in (
        ("total_employee_count", "gross_pay"),
        ("total_gross_pay", "gross_pay"),
        ("total_isr_withheld", "tds"),
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


def _build_do_tss_suir_template(db, creator, approver, key="DO-TSS-SUIR-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="TSS/SUIR", reportType="DO_TSS_SUIR",
            jurisdictionCountry="DO", reportingYear="2026", documentScope="AGGREGATE",
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
    for field_key, source_column in (
        ("total_employee_count", "gross_pay"),
        ("total_gross_pay", "gross_pay"),
        ("total_sfs_employee", "social_security"),
        ("total_sfs_employer", "employer_social_security"),
        ("total_pension_employee", "employee_pension"),
        ("total_pension_employer", "employer_pension"),
        ("total_srl_employer", "employer_payroll_tax"),
        ("total_infotep_employer", "employer_ni"),
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


def _build_do_ir13_template(db, creator, approver, key="DO-IR13-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="DGII IR-13", reportType="IR13",
            jurisdictionCountry="DO", reportingYear="2026", documentScope="PER_EMPLOYEE",
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
        db, template.id, ReportTemplateComponentUpsert(componentKey="tax", label="ISR (YTD)"), actor_id=creator.id,
    )
    service.upsert_report_field(
        db, tax.id, ReportTemplateFieldUpsert(
            fieldKey="tds_ytd", label="ISR YTD", fieldType="currency",
            dataSourceKind="PAYSLIP_ITEM", sourceColumn="tds", aggregation="SUM_YTD",
        ), actor_id=creator.id,
    )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)
    return template


# ── DGII IR-3 ────────────────────────────────────────────────────────

def test_generate_do_ir3_aggregates_two_employees_across_multiple_runs_same_month(db, organization):
    creator = _make_user(db, "creator_doir3a@test.com")
    approver = _make_user(db, "approver_doir3a@test.com")
    _make_company(db, organization.id, country="DO")
    emp1 = _make_do_employee(db, organization.id, code="DOIR3A1", name="Yolanda Peña")
    emp2 = _make_do_employee(db, organization.id, code="DOIR3A2", name="Rafael Cruz")

    _make_do_run_with_payslip(db, organization.id, emp1.id, date(2026, 3, 7), gross_pay=50000, tds=6000, employee_name="Yolanda Peña")
    _make_do_run_with_payslip(db, organization.id, emp1.id, date(2026, 3, 14), gross_pay=50000, tds=6000, employee_name="Yolanda Peña")
    _make_do_run_with_payslip(db, organization.id, emp2.id, date(2026, 3, 21), gross_pay=120000, tds=18000, employee_name="Rafael Cruz")

    template = _build_do_ir3_template(db, creator, approver)
    generated = service.generate_do_ir3(db, organization.id, template.id, 2026, 3, actor_id=creator.id)

    assert generated.report_type == "DO_IR3"
    assert generated.scope_key == "PERIOD:2026-03-01:2026-03-31"
    totals = generated.rendered_data["employerTotals"]
    assert totals["total_employee_count"] == 2
    assert totals["total_gross_pay"] == 220000.0
    assert totals["total_isr_withheld"] == 30000.0

    rows = {r["employeeName"]: r for r in generated.rendered_data["employeeRows"]}
    assert rows["Yolanda Peña"]["grossPay"] == 100000.0  # 2 runs summed into ONE row
    assert rows["Yolanda Peña"]["cedula"] == "001-1234567-8"
    assert rows["Rafael Cruz"]["grossPay"] == 120000.0


def test_generate_do_ir3_excludes_other_months_and_unfinalized_runs(db, organization):
    creator = _make_user(db, "creator_doir3b@test.com")
    approver = _make_user(db, "approver_doir3b@test.com")
    _make_company(db, organization.id, country="DO")
    employee = _make_do_employee(db, organization.id, code="DOIR3B")

    _make_do_run_with_payslip(db, organization.id, employee.id, date(2026, 3, 10), gross_pay=60000)
    _make_do_run_with_payslip(db, organization.id, employee.id, date(2026, 4, 5), gross_pay=99999)
    _make_do_run_with_payslip(db, organization.id, employee.id, date(2026, 3, 20), gross_pay=99999, status="Draft")

    template = _build_do_ir3_template(db, creator, approver, key="DO-IR3-EXCLUDE-TEST")
    generated = service.generate_do_ir3(db, organization.id, template.id, 2026, 3, actor_id=creator.id)
    assert generated.rendered_data["employerTotals"]["total_gross_pay"] == 60000.0
    assert len(generated.rendered_data["employeeRows"]) == 1


def test_generate_do_ir3_rejects_wrong_report_type(db, organization):
    creator = _make_user(db, "creator_doir3c@test.com")
    approver = _make_user(db, "approver_doir3c@test.com")
    _make_company(db, organization.id, country="DO")
    template = _build_template(db, creator, approver, country="DO", version="doir3-neg")
    with pytest.raises(BadRequestException):
        service.generate_do_ir3(db, organization.id, template.id, 2026, 3)


def test_generate_do_ir3_regenerating_supersedes_prior(db, organization):
    creator = _make_user(db, "creator_doir3d@test.com")
    approver = _make_user(db, "approver_doir3d@test.com")
    _make_company(db, organization.id, country="DO")
    employee = _make_do_employee(db, organization.id, code="DOIR3D")
    _make_do_run_with_payslip(db, organization.id, employee.id, date(2026, 3, 10))

    template = _build_do_ir3_template(db, creator, approver, key="DO-IR3-SUPERSEDE-TEST")
    first = service.generate_do_ir3(db, organization.id, template.id, 2026, 3, actor_id=creator.id)
    second = service.generate_do_ir3(db, organization.id, template.id, 2026, 3, actor_id=creator.id)
    db.refresh(first)
    assert first.status == "Superseded"
    assert second.status == "Generated"


# ── TSS/SUIR ─────────────────────────────────────────────────────────

def test_generate_do_tss_suir_aggregates_employees_for_the_month(db, organization):
    creator = _make_user(db, "creator_dotss_a@test.com")
    approver = _make_user(db, "approver_dotss_a@test.com")
    _make_company(db, organization.id, country="DO")
    emp1 = _make_do_employee(db, organization.id, code="DOTSSA1", name="Yolanda Peña")
    emp2 = _make_do_employee(db, organization.id, code="DOTSSA2", name="Rafael Cruz")

    _make_do_run_with_payslip(db, organization.id, emp1.id, date(2026, 5, 8), gross_pay=70000, social_security=2660, employer_social_security=2660, employee_name="Yolanda Peña")
    _make_do_run_with_payslip(db, organization.id, emp2.id, date(2026, 5, 22), gross_pay=90000, social_security=3420, employer_social_security=3420, employee_name="Rafael Cruz")

    template = _build_do_tss_suir_template(db, creator, approver)
    generated = service.generate_do_tss_suir(db, organization.id, template.id, 2026, 5, actor_id=creator.id)

    assert generated.report_type == "DO_TSS_SUIR"
    totals = generated.rendered_data["employerTotals"]
    assert totals["total_employee_count"] == 2
    assert totals["total_gross_pay"] == 160000.0
    assert totals["total_sfs_employee"] == 6080.0
    assert totals["total_sfs_employer"] == 6080.0


def test_generate_do_tss_suir_rejects_wrong_report_type(db, organization):
    creator = _make_user(db, "creator_dotss_b@test.com")
    approver = _make_user(db, "approver_dotss_b@test.com")
    _make_company(db, organization.id, country="DO")
    template = _build_template(db, creator, approver, country="DO", version="dotss-neg")
    with pytest.raises(BadRequestException):
        service.generate_do_tss_suir(db, organization.id, template.id, 2026, 5)


# ── IR-13 (generic mapper reuse) ─────────────────────────────────────

def test_generate_do_ir13_sums_ytd_via_generic_mapper(db, organization):
    creator = _make_user(db, "creator_doir13_a@test.com")
    approver = _make_user(db, "approver_doir13_a@test.com")
    _make_company(db, organization.id, country="DO")
    employee = _make_do_employee(db, organization.id, code="DOIR13A", name="Yolanda Peña")

    _make_do_run_with_payslip(db, organization.id, employee.id, date(2026, 1, 31), gross_pay=100000, tds=12000, employee_name="Yolanda Peña")
    _make_do_run_with_payslip(db, organization.id, employee.id, date(2026, 2, 28), gross_pay=100000, tds=12000, employee_name="Yolanda Peña")

    template = _build_do_ir13_template(db, creator, approver)
    generated = service.generate_uk_employee_report(
        db, organization.id, template.id, employee.id, date(2026, 12, 31), actor_id=creator.id,
    )
    assert generated.report_type == "IR13"
    values = generated.rendered_data["employees"][0]["values"]
    assert values["employee_name"] == "Yolanda Peña"
    assert values["tds_ytd"] == 24000.0
