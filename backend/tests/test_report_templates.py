"""
tests/test_report_templates.py
-------------------------------
End-to-end coverage for the Report Template system (Super Admin authoring +
Organization report generation): lifecycle/maker-checker, the real-column
allow-list enforcement, applicable-template resolution, actual report
generation against real PayslipItem/PayrollRun data, the reconciliation
check, and historical immutability across template versions.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import service
from app.modules.payroll.schemas import (
    ReportTemplateUpsert, ReportTemplateComponentUpsert, ReportTemplateFieldUpsert, FilingCalendarUpsert,
)


def _make_user(db, email):
    from app.modules.auth.models import User, UserRole
    user = User(
        email=email, hashed_password="x", role=UserRole.PAYROLL_ADMIN,
        first_name="Test", last_name="User",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_company(db, organization_id, country="IN", state=None):
    from app.modules.payroll.models import CompanyComplianceDetails
    company = CompanyComplianceDetails(
        organization_id=organization_id, name="Acme India Pvt Ltd", tax_no="AAAAA0000A",
        jurisdiction_country=country, jurisdiction_state=state or "",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _make_run_with_payslip(db, organization_id, status="Approved"):
    from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem

    employee = PayrollEmployee(organization_id=organization_id, employee_code="E001", name="Asha Rao")
    db.add(employee)
    db.commit()
    db.refresh(employee)

    run = PayrollRun(
        organization_id=organization_id, period_label="Aug 2026",
        period_start=date(2026, 8, 1), period_end=date(2026, 8, 31), pay_date=date(2026, 8, 31),
        status=status, total_gross=100000, total_deductions=20000, total_net=80000,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee.id, organization_id=organization_id,
        employee_name="Asha Rao", basic_salary=60000, hra=20000, gross_pay=100000,
        pf=7200, esi=750, professional_tax=200, tds=11850, total_deductions=20000, net_pay=80000,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return run, employee, item


def _build_template(db, creator, approver, country="IN", state=None, year="2026-27", version="1.0"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey="IN-TDS-SALARY", name="Salary TDS Report", reportType="TDS",
            jurisdictionCountry=country, jurisdictionState=state, reportingYear=year, version=version,
        ), actor_id=creator.id,
    )
    earnings = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="earnings", label="Earnings"), actor_id=creator.id,
    )
    service.upsert_report_field(
        db, earnings.id, ReportTemplateFieldUpsert(
            fieldKey="gross_pay", label="Gross Pay", fieldType="currency",
            dataSourceKind="PAYSLIP_ITEM", sourceColumn="gross_pay",
        ), actor_id=creator.id,
    )
    tax = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="tax", label="Tax"), actor_id=creator.id,
    )
    service.upsert_report_field(
        db, tax.id, ReportTemplateFieldUpsert(
            fieldKey="tds", label="TDS Deducted", fieldType="currency",
            dataSourceKind="PAYSLIP_ITEM", sourceColumn="tds",
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
    template = service.set_report_template_approver(db, template.id, actor_id=approver.id)
    assert template.status == "Approved"
    template = service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    template = service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)
    assert template.status == "Active"
    return template


def test_upsert_report_field_rejects_unknown_column(db, organization):
    creator = _make_user(db, "creator@test.com")
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey="IN-TDS-SALARY", name="Salary TDS Report", reportType="TDS",
            jurisdictionCountry="IN", reportingYear="2026-27",
        ), actor_id=creator.id,
    )
    component = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="earnings", label="Earnings"), actor_id=creator.id,
    )
    with pytest.raises(BadRequestException):
        service.upsert_report_field(
            db, component.id, ReportTemplateFieldUpsert(
                fieldKey="made_up", label="Made Up Field", fieldType="currency",
                dataSourceKind="PAYSLIP_ITEM", sourceColumn="employee_secret_bonus_pool",
            ), actor_id=creator.id,
        )


def test_status_transition_requires_distinct_approver(db, organization):
    creator = _make_user(db, "creator2@test.com")
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey="IN-TDS-SALARY-2", name="Salary TDS Report", reportType="TDS",
            jurisdictionCountry="IN", reportingYear="2026-27",
        ), actor_id=creator.id,
    )
    # approved_by_id is None -> cannot go Published.
    with pytest.raises(BadRequestException):
        service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    # Self-approval (same actor) still cannot go Published.
    service.set_report_template_approver(db, template.id, actor_id=creator.id)
    with pytest.raises(BadRequestException):
        service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)


def test_list_available_reports_for_org(db, organization):
    creator = _make_user(db, "creator6@test.com")
    approver = _make_user(db, "approver6@test.com")
    _make_company(db, organization.id, country="IN")

    # Before any template is Published/Active, nothing is offered.
    assert service.list_available_reports_for_org(db, organization.id, "2026-27") == []

    template = _build_template(db, creator, approver)
    available = service.list_available_reports_for_org(db, organization.id, "2026-27")
    assert available == [{"reportType": "TDS", "name": template.name}]

    # A different reporting year sees nothing.
    assert service.list_available_reports_for_org(db, organization.id, "2027-28") == []


def test_generate_report_end_to_end_with_reconciliation(db, organization):
    creator = _make_user(db, "creator3@test.com")
    approver = _make_user(db, "approver3@test.com")
    _make_company(db, organization.id, country="IN")
    run, employee, item = _make_run_with_payslip(db, organization.id, status="Approved")

    template = _build_template(db, creator, approver)

    resolved = service.get_applicable_report_template(db, "IN", None, "2026-27", "TDS")
    assert resolved is not None and resolved.id == template.id

    validation = service.validate_report_generation_context(db, organization.id, template, run)
    assert validation["jurisdictionMatch"] and validation["runFinalized"] and validation["periodMatch"] and validation["templatePublished"]

    generated = service.generate_report_from_template(
        db, organization.id, template.id, run.id, reporting_period=run.period_label, actor_id=creator.id,
    )
    assert generated.status == "Generated"
    assert generated.template_version == "1.0"

    employees = generated.rendered_data["employees"]
    assert len(employees) == 1
    assert employees[0]["values"]["gross_pay"] == float(item.gross_pay)
    assert employees[0]["values"]["tds"] == float(item.tds)
    assert generated.rendered_data["employer"]["employer_name"] == "Acme India Pvt Ltd"
    assert generated.reconciliation["status"] == "MATCH"

    # A second generate for the same (org, run, template) supersedes the
    # first rather than erroring or duplicating.
    generated_again = service.generate_report_from_template(
        db, organization.id, template.id, run.id, reporting_period=run.period_label, actor_id=creator.id,
    )
    assert generated_again.id != generated.id
    refreshed_first = service.get_generated_report(db, organization.id, generated.id)
    assert refreshed_first.status == "Superseded"


def test_generate_report_blocked_for_unfinalized_run(db, organization):
    creator = _make_user(db, "creator4@test.com")
    approver = _make_user(db, "approver4@test.com")
    _make_company(db, organization.id, country="IN")
    run, employee, item = _make_run_with_payslip(db, organization.id, status="Draft")
    template = _build_template(db, creator, approver)

    with pytest.raises(BadRequestException):
        service.generate_report_from_template(db, organization.id, template.id, run.id, actor_id=creator.id)


def test_generate_report_uk_p60(db, organization):
    """Phase 2 sanity check: the exact same authoring/generation path works
    for UK (P60) with no backend changes — only the field/component
    catalogs differ per jurisdiction, confirming the design is genuinely
    jurisdiction-agnostic rather than India-specific."""
    creator = _make_user(db, "creator_uk@test.com")
    approver = _make_user(db, "approver_uk@test.com")
    _make_company(db, organization.id, country="UK")
    run, employee, item = _make_run_with_payslip(db, organization.id, status="Approved")
    item.tds = 0
    item.ni_employee = 950
    db.commit()

    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey="UK-P60", name="P60", reportType="P60",
            jurisdictionCountry="UK", reportingYear="2026-27",
        ), actor_id=creator.id,
    )
    tax = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="contributions", label="National Insurance"), actor_id=creator.id,
    )
    service.upsert_report_field(
        db, tax.id, ReportTemplateFieldUpsert(
            fieldKey="ni_employee", label="National Insurance (Employee)", fieldType="currency",
            dataSourceKind="PAYSLIP_ITEM", sourceColumn="ni_employee",
        ), actor_id=creator.id,
    )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)

    resolved = service.get_applicable_report_template(db, "UK", None, "2026-27", "P60")
    assert resolved is not None and resolved.id == template.id

    generated = service.generate_report_from_template(
        db, organization.id, template.id, run.id, reporting_period=run.period_label, actor_id=creator.id,
    )
    assert generated.rendered_data["employees"][0]["values"]["ni_employee"] == 950.0

    available = service.list_available_reports_for_org(db, organization.id, "2026-27")
    assert available == [{"reportType": "P60", "name": "P60"}]


# ── UK RTI gap-closure Part 9 (ZP-TAX-UK-2026-27-001 §18, 2026-09-09): ───
# PAYROLL_EMPLOYEE data source + tax-year-exact SUM_YTD ──────────────────

def test_upsert_report_field_accepts_payroll_employee_source(db, organization):
    creator = _make_user(db, "creator_pe1@test.com")
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey="UK-FPS-TEST", name="FPS", reportType="FPS",
            jurisdictionCountry="UK", reportingYear="2026-27",
        ), actor_id=creator.id,
    )
    component = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="employee_info", label="Employee Information"),
        actor_id=creator.id,
    )
    field = service.upsert_report_field(
        db, component.id, ReportTemplateFieldUpsert(
            fieldKey="nino", label="National Insurance Number", fieldType="text",
            dataSourceKind="PAYROLL_EMPLOYEE", sourceColumn="nino",
        ), actor_id=creator.id,
    )
    assert field.source_column == "nino"


def test_upsert_report_field_rejects_unknown_payroll_employee_column(db, organization):
    creator = _make_user(db, "creator_pe2@test.com")
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey="UK-FPS-TEST2", name="FPS", reportType="FPS",
            jurisdictionCountry="UK", reportingYear="2026-27",
        ), actor_id=creator.id,
    )
    component = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="employee_info", label="Employee Information"),
        actor_id=creator.id,
    )
    with pytest.raises(BadRequestException):
        service.upsert_report_field(
            db, component.id, ReportTemplateFieldUpsert(
                fieldKey="ssn", label="SSN", fieldType="text",
                dataSourceKind="PAYROLL_EMPLOYEE", sourceColumn="ssn",
            ), actor_id=creator.id,
        )


def test_generate_report_resolves_payroll_employee_fields(db, organization):
    creator = _make_user(db, "creator_pe3@test.com")
    approver = _make_user(db, "approver_pe3@test.com")
    _make_company(db, organization.id, country="UK")
    run, employee, item = _make_run_with_payslip(db, organization.id, status="Approved")
    employee.compliance_fields = {"nino": "QQ123456C"}
    employee.address_line1 = "1 Test Street"
    employee.address_postcode = "SW1A 1AA"
    employee.starter_declaration = "A"
    db.commit()

    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey="UK-FPS-PE-TEST", name="FPS", reportType="FPS",
            jurisdictionCountry="UK", reportingYear="2026-27",
        ), actor_id=creator.id,
    )
    component = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="employee_info", label="Employee Information"),
        actor_id=creator.id,
    )
    for key, label in (("nino", "NINO"), ("address_line1", "Address"), ("address_postcode", "Postcode"), ("starter_declaration", "Starter Declaration")):
        service.upsert_report_field(
            db, component.id, ReportTemplateFieldUpsert(
                fieldKey=key, label=label, fieldType="text",
                dataSourceKind="PAYROLL_EMPLOYEE", sourceColumn=key,
            ), actor_id=creator.id,
        )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)

    generated = service.generate_report_from_template(
        db, organization.id, template.id, run.id, reporting_period=run.period_label, actor_id=creator.id,
    )
    values = generated.rendered_data["employees"][0]["values"]
    assert values["nino"] == "QQ123456C"
    assert values["address_line1"] == "1 Test Street"
    assert values["address_postcode"] == "SW1A 1AA"
    assert values["starter_declaration"] == "A"


def test_generate_report_payroll_employee_field_none_when_unset(db, organization):
    creator = _make_user(db, "creator_pe4@test.com")
    approver = _make_user(db, "approver_pe4@test.com")
    _make_company(db, organization.id, country="UK")
    run, employee, item = _make_run_with_payslip(db, organization.id, status="Approved")
    # compliance_fields defaults to {} — nino deliberately left unset.

    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey="UK-FPS-PE-TEST2", name="FPS", reportType="FPS",
            jurisdictionCountry="UK", reportingYear="2026-27",
        ), actor_id=creator.id,
    )
    component = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="employee_info", label="Employee Information"),
        actor_id=creator.id,
    )
    service.upsert_report_field(
        db, component.id, ReportTemplateFieldUpsert(
            fieldKey="nino", label="NINO", fieldType="text",
            dataSourceKind="PAYROLL_EMPLOYEE", sourceColumn="nino",
        ), actor_id=creator.id,
    )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)

    generated = service.generate_report_from_template(
        db, organization.id, template.id, run.id, reporting_period=run.period_label, actor_id=creator.id,
    )
    assert generated.rendered_data["employees"][0]["values"]["nino"] is None


def test_sum_ytd_is_tax_year_exact_for_uk_not_calendar_year(db, organization):
    """Before this fix, SUM_YTD used a blanket "1 January" boundary for
    every jurisdiction — silently wrong for UK, whose real tax year
    starts 6 April. A payment from 5 April (the OLD tax year's very last
    day) must NOT be included in a 10 April run's YTD figure, even
    though both dates share the same calendar year."""
    from app.modules.payroll.models import PayrollRun, PayslipItem

    creator = _make_user(db, "creator_ytd1@test.com")
    approver = _make_user(db, "approver_ytd1@test.com")
    _make_company(db, organization.id, country="UK")
    run, employee, item = _make_run_with_payslip(db, organization.id, status="Approved")
    run.period_end = date(2026, 4, 10)
    run.pay_date = date(2026, 4, 10)
    item.ni_employee = 100
    db.commit()

    # A prior payslip dated 5 April (the OLD 2025-26 tax year's last day)
    # — must be EXCLUDED from the 2026-27 tax year's YTD sum.
    prior_run = PayrollRun(
        organization_id=organization.id, period_label="Mar 2026",
        period_start=date(2026, 3, 6), period_end=date(2026, 4, 5), pay_date=date(2026, 4, 5),
        status="Approved", total_gross=100000, total_deductions=20000, total_net=80000,
    )
    db.add(prior_run)
    db.commit()
    db.refresh(prior_run)
    prior_item = PayslipItem(
        payroll_run_id=prior_run.id, employee_id=employee.id, organization_id=organization.id,
        employee_name=employee.name, gross_pay=100000, ni_employee=500, total_deductions=20000, net_pay=80000,
    )
    db.add(prior_item)
    db.commit()

    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey="UK-FPS-YTD-TEST", name="FPS", reportType="FPS",
            jurisdictionCountry="UK", reportingYear="2026-27",
        ), actor_id=creator.id,
    )
    component = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="ytd", label="Year-to-Date"), actor_id=creator.id,
    )
    service.upsert_report_field(
        db, component.id, ReportTemplateFieldUpsert(
            fieldKey="ni_ytd", label="NI (YTD)", fieldType="currency",
            dataSourceKind="PAYSLIP_ITEM", sourceColumn="ni_employee", aggregation="SUM_YTD",
        ), actor_id=creator.id,
    )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)

    generated = service.generate_report_from_template(
        db, organization.id, template.id, run.id, reporting_period=run.period_label, actor_id=creator.id,
    )
    # Only this period's own 100 — the 5-April prior-tax-year payment's
    # 500 must be excluded, unlike the old Jan-1 approximation which
    # would have wrongly included it (both fall in calendar year 2026).
    assert generated.rendered_data["employees"][0]["values"]["ni_ytd"] == 100.0


def test_sum_ytd_calendar_year_unchanged_for_non_uk(db, organization):
    """India (and every non-UK jurisdiction) keeps the pre-existing
    calendar-year approximation exactly as before this fix — only UK's
    boundary changed."""
    from app.modules.payroll.models import PayrollRun, PayslipItem

    creator = _make_user(db, "creator_ytd2@test.com")
    approver = _make_user(db, "approver_ytd2@test.com")
    _make_company(db, organization.id, country="IN")
    run, employee, item = _make_run_with_payslip(db, organization.id, status="Approved")
    run.period_end = date(2026, 2, 10)
    db.commit()

    prior_run = PayrollRun(
        organization_id=organization.id, period_label="Jan 2026",
        period_start=date(2026, 1, 1), period_end=date(2026, 1, 31), pay_date=date(2026, 1, 31),
        status="Approved", total_gross=100000, total_deductions=20000, total_net=80000,
    )
    db.add(prior_run)
    db.commit()
    db.refresh(prior_run)
    prior_item = PayslipItem(
        payroll_run_id=prior_run.id, employee_id=employee.id, organization_id=organization.id,
        employee_name=employee.name, gross_pay=100000, tds=1000, total_deductions=20000, net_pay=80000,
    )
    db.add(prior_item)
    db.commit()

    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey="IN-TDS-YTD-TEST", name="Salary TDS Report", reportType="TDS",
            jurisdictionCountry="IN", reportingYear="2026-27",
        ), actor_id=creator.id,
    )
    component = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="ytd", label="Year-to-Date"), actor_id=creator.id,
    )
    service.upsert_report_field(
        db, component.id, ReportTemplateFieldUpsert(
            fieldKey="tds_ytd", label="TDS (YTD)", fieldType="currency",
            dataSourceKind="PAYSLIP_ITEM", sourceColumn="tds", aggregation="SUM_YTD",
        ), actor_id=creator.id,
    )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)

    generated = service.generate_report_from_template(
        db, organization.id, template.id, run.id, reporting_period=run.period_label, actor_id=creator.id,
    )
    # January's TDS IS included — same calendar year (2026), matching the
    # unchanged pre-existing behavior for non-UK jurisdictions.
    assert generated.rendered_data["employees"][0]["values"]["tds_ytd"] == 1000.0 + float(item.tds)


def test_historical_immutability_across_template_versions(db, organization):
    creator = _make_user(db, "creator5@test.com")
    approver = _make_user(db, "approver5@test.com")
    _make_company(db, organization.id, country="IN")
    run, employee, item = _make_run_with_payslip(db, organization.id, status="Approved")

    template_v1 = _build_template(db, creator, approver)
    generated = service.generate_report_from_template(
        db, organization.id, template_v1.id, run.id, reporting_period=run.period_label, actor_id=creator.id,
    )
    assert generated.template_version == "1.0"

    # Publish a new version — must not retroactively change the already
    # generated report, and activating it requires superseding v1.0 first
    # (the one-Active-per-jurisdiction/year/report-type overlap guard).
    template_v2 = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey="IN-TDS-SALARY", name="Salary TDS Report", reportType="TDS",
            jurisdictionCountry="IN", reportingYear="2026-27", version="1.1",
        ), actor_id=creator.id,
    )
    service.set_report_template_approver(db, template_v2.id, actor_id=approver.id)
    service.set_report_template_status(db, template_v2.id, "Published", actor_id=creator.id)
    with pytest.raises(BadRequestException):
        service.set_report_template_status(db, template_v2.id, "Active", actor_id=creator.id)

    service.set_report_template_status(db, template_v1.id, "Superseded", actor_id=creator.id)
    template_v2 = service.set_report_template_status(db, template_v2.id, "Active", actor_id=creator.id)
    assert template_v2.status == "Active"

    resolved = service.get_applicable_report_template(db, "IN", None, "2026-27", "TDS")
    assert resolved.id == template_v2.id  # org would now generate against v1.1 going forward

    unchanged = service.get_generated_report(db, organization.id, generated.id)
    assert unchanged.template_version == "1.0"  # historical report still pinned to what it actually used


# ── Phase 3: document_scope + certificate rendering ──────────────────────

def _build_per_employee_template(db, creator, approver, template_key="IN-FORM-130-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=template_key, name="Salary TDS Certificate (Form 130)", reportType="FORM_130",
            jurisdictionCountry="IN", reportingYear="2026-27", documentScope="PER_EMPLOYEE",
        ), actor_id=creator.id,
    )
    tax = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="tax", label="Tax"), actor_id=creator.id,
    )
    service.upsert_report_field(
        db, tax.id, ReportTemplateFieldUpsert(
            fieldKey="tds", label="Tax Deducted at Source", fieldType="currency",
            dataSourceKind="PAYSLIP_ITEM", sourceColumn="tds",
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
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    return service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)


def test_certificate_pdf_renders_for_per_employee_template(db, organization):
    creator = _make_user(db, "creator7@test.com")
    approver = _make_user(db, "approver7@test.com")
    _make_company(db, organization.id, country="IN")
    run, employee, item = _make_run_with_payslip(db, organization.id, status="Approved")
    template = _build_per_employee_template(db, creator, approver)

    generated = service.generate_report_from_template(
        db, organization.id, template.id, run.id, reporting_period=run.period_label, actor_id=creator.id,
    )
    assert generated.rendered_data["employees"][0]["values"]["tds"] == float(item.tds)

    pdf_bytes = service.generate_report_certificate_pdf_bytes(db, organization.id, generated.id, employee.id)
    assert isinstance(pdf_bytes, (bytes, bytearray))
    assert pdf_bytes[:4] == b"%PDF"
    assert len(pdf_bytes) > 1000

    with pytest.raises(NotFoundException):
        service.generate_report_certificate_pdf_bytes(db, organization.id, generated.id, employee.id + 999)


def test_certificate_pdf_rejects_aggregate_template(db, organization):
    creator = _make_user(db, "creator8@test.com")
    approver = _make_user(db, "approver8@test.com")
    _make_company(db, organization.id, country="IN")
    run, employee, item = _make_run_with_payslip(db, organization.id, status="Approved")
    # _build_template() (existing helper) creates an AGGREGATE (default) template.
    template = _build_template(db, creator, approver)
    generated = service.generate_report_from_template(
        db, organization.id, template.id, run.id, reporting_period=run.period_label, actor_id=creator.id,
    )
    with pytest.raises(BadRequestException):
        service.generate_report_certificate_pdf_bytes(db, organization.id, generated.id, employee.id)


# ── Phase 3: statutory filing calendar ────────────────────────────────────

def test_filing_calendar_seed_idempotent_and_overlap_guarded(db, organization):
    admin = _make_user(db, "filingadmin@test.com")

    entry = service.upsert_filing_calendar_entry(
        db, FilingCalendarUpsert(
            jurisdictionCountry="IN", reportType="FORM_138", reportingYear="2026-27",
            periodKey="Q1", periodLabel="April-June", dueDate=date(2026, 7, 31),
        ), actor_id=admin.id,
    )
    assert entry.status == "Draft"

    # Re-upserting with no id, same natural key, updates the existing Draft
    # row instead of creating a duplicate (this is what makes the seed
    # script idempotent).
    entry_again = service.upsert_filing_calendar_entry(
        db, FilingCalendarUpsert(
            jurisdictionCountry="IN", reportType="FORM_138", reportingYear="2026-27",
            periodKey="Q1", periodLabel="April-June", dueDate=date(2026, 7, 31),
        ), actor_id=admin.id,
    )
    assert entry_again.id == entry.id
    all_entries = service.list_filing_calendar(db, country="IN", report_type="FORM_138", reporting_year="2026-27")
    assert len(all_entries) == 1

    activated = service.set_filing_calendar_status(db, entry.id, "Active", actor_id=admin.id)
    assert activated.status == "Active"

    # A second Active entry for the SAME period is blocked (overlap guard) —
    # must supersede the first one first.
    entry2 = service.upsert_filing_calendar_entry(
        db, FilingCalendarUpsert(
            id=None, jurisdictionCountry="IN", reportType="FORM_138", reportingYear="2026-27",
            periodKey="Q1", periodLabel="April-June (corrected)", dueDate=date(2026, 8, 15),
        ), actor_id=admin.id,
    )
    # entry2 falls back to natural-key lookup too, but `entry` is no longer
    # Draft (it's Active) so this creates a genuinely NEW row via the
    # previous_version_id chain instead of illegally editing the Active one.
    assert entry2.id != entry.id
    assert entry2.previous_version_id == entry.id
    with pytest.raises(BadRequestException):
        service.set_filing_calendar_status(db, entry2.id, "Active", actor_id=admin.id)

    service.set_filing_calendar_status(db, entry.id, "Superseded", actor_id=admin.id)
    entry2 = service.set_filing_calendar_status(db, entry2.id, "Active", actor_id=admin.id)
    assert entry2.status == "Active"


def test_get_upcoming_filing_dates_for_org(db, organization):
    admin = _make_user(db, "filingadmin2@test.com")
    _make_company(db, organization.id, country="IN")

    past = service.upsert_filing_calendar_entry(
        db, FilingCalendarUpsert(
            jurisdictionCountry="IN", reportType="FORM_138", reportingYear="2025-26",
            periodKey="Q4", periodLabel="January-March", dueDate=date(2020, 5, 31),
        ), actor_id=admin.id,
    )
    service.set_filing_calendar_status(db, past.id, "Active", actor_id=admin.id)

    future = service.upsert_filing_calendar_entry(
        db, FilingCalendarUpsert(
            jurisdictionCountry="IN", reportType="FORM_138", reportingYear="2026-27",
            periodKey="Q1", periodLabel="April-June", dueDate=date(2099, 7, 31),
        ), actor_id=admin.id,
    )
    service.set_filing_calendar_status(db, future.id, "Active", actor_id=admin.id)

    upcoming = service.get_upcoming_filing_dates_for_org(db, organization.id)
    upcoming_ids = [e.id for e in upcoming]
    assert future.id in upcoming_ids
    assert past.id not in upcoming_ids  # already due — not "upcoming"


# ── Phase 3: honest test vectors from the statutory packs ─────────────────
# These assert the REPORT faithfully echoes real PayslipItem figures set up
# to match the documents' own printed examples — they test this module's
# reporting code, not the calculation engine (a separate, existing test
# surface this deliberately does not touch).

def test_india_esi_test_vector_echoed_in_report(db, organization):
    """India pack §10 ESI test vector: contribution wages 20,000 -> employee
    150, employer 650. Sets those exact figures on a PayslipItem (as if the
    engine had already computed them) and confirms the report shows them
    unchanged."""
    from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem

    creator = _make_user(db, "creator9@test.com")
    approver = _make_user(db, "approver9@test.com")
    _make_company(db, organization.id, country="IN")

    employee = PayrollEmployee(organization_id=organization.id, employee_code="E002", name="Ravi Kumar")
    db.add(employee); db.commit(); db.refresh(employee)
    run = PayrollRun(
        organization_id=organization.id, period_label="Aug 2026",
        period_start=date(2026, 8, 1), period_end=date(2026, 8, 31), pay_date=date(2026, 8, 31),
        status="Approved", total_gross=20000, total_deductions=800, total_net=19200,
    )
    db.add(run); db.commit(); db.refresh(run)
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee.id, organization_id=organization.id,
        employee_name="Ravi Kumar", gross_pay=20000, esi=150, employer_esi=650,
        total_deductions=800, net_pay=19200,
    )
    db.add(item); db.commit(); db.refresh(item)

    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey="IN-ESI-VECTOR-TEST", name="ESI Statement", reportType="FORM_138",
            jurisdictionCountry="IN", reportingYear="2026-27",
        ), actor_id=creator.id,
    )
    component = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="contributions", label="ESI"), actor_id=creator.id,
    )
    service.upsert_report_field(
        db, component.id, ReportTemplateFieldUpsert(
            fieldKey="esi", label="ESI (Employee)", fieldType="currency",
            dataSourceKind="PAYSLIP_ITEM", sourceColumn="esi",
        ), actor_id=creator.id,
    )
    service.upsert_report_field(
        db, component.id, ReportTemplateFieldUpsert(
            fieldKey="employer_esi", label="ESI (Employer)", fieldType="currency",
            dataSourceKind="PAYSLIP_ITEM", sourceColumn="employer_esi",
        ), actor_id=creator.id,
    )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)

    generated = service.generate_report_from_template(
        db, organization.id, template.id, run.id, reporting_period=run.period_label, actor_id=creator.id,
    )
    values = generated.rendered_data["employees"][0]["values"]
    assert values["esi"] == 150.0
    assert values["employer_esi"] == 650.0


def test_uk_nic_category_a_test_vector_echoed_in_report(db, organization):
    """UK pack §22's reference NIC vector: Category A, weekly earnings
    £1,000 -> employee NIC £58.66, employer NIC £135.60."""
    from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem

    creator = _make_user(db, "creator10@test.com")
    approver = _make_user(db, "approver10@test.com")
    _make_company(db, organization.id, country="UK")

    employee = PayrollEmployee(organization_id=organization.id, employee_code="E003", name="Alex Doe")
    db.add(employee); db.commit(); db.refresh(employee)
    run = PayrollRun(
        organization_id=organization.id, period_label="Week 1 Aug 2026",
        period_start=date(2026, 8, 1), period_end=date(2026, 8, 7), pay_date=date(2026, 8, 7),
        status="Approved", total_gross=1000, total_deductions=58.66, total_net=941.34,
    )
    db.add(run); db.commit(); db.refresh(run)
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee.id, organization_id=organization.id,
        employee_name="Alex Doe", gross_pay=1000, ni_employee=58.66, employer_ni=135.60,
        total_deductions=58.66, net_pay=941.34,
    )
    db.add(item); db.commit(); db.refresh(item)

    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey="UK-NIC-VECTOR-TEST", name="NI Statement", reportType="EPS_FPS",
            jurisdictionCountry="UK", reportingYear="2026-27",
        ), actor_id=creator.id,
    )
    component = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="contributions", label="National Insurance"), actor_id=creator.id,
    )
    service.upsert_report_field(
        db, component.id, ReportTemplateFieldUpsert(
            fieldKey="ni_employee", label="NI (Employee)", fieldType="currency",
            dataSourceKind="PAYSLIP_ITEM", sourceColumn="ni_employee",
        ), actor_id=creator.id,
    )
    employer_contributions = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="employer_contributions", label="Employer Contributions"),
        actor_id=creator.id,
    )
    service.upsert_report_field(
        db, employer_contributions.id, ReportTemplateFieldUpsert(
            fieldKey="employer_ni", label="NI (Employer)", fieldType="currency",
            dataSourceKind="PAYSLIP_ITEM", sourceColumn="employer_ni",
        ), actor_id=creator.id,
    )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)

    generated = service.generate_report_from_template(
        db, organization.id, template.id, run.id, reporting_period=run.period_label, actor_id=creator.id,
    )
    values = generated.rendered_data["employees"][0]["values"]
    assert values["ni_employee"] == 58.66
    assert values["employer_ni"] == 135.6


# ── UK RTI gap-closure Part 9 (ZP-TAX-UK-2026-27-001 §18, 2026-09-09): ───
# P45/P60 (per-employee, no run) + EPS (per-period, employer-only) ───────

def _build_uk_p60_template(db, creator, approver, key="UK-P60-GEN-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="P60", reportType="P60",
            jurisdictionCountry="UK", reportingYear="2026-27",
            documentScope="PER_EMPLOYEE",
        ), actor_id=creator.id,
    )
    employee_info = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="employee_info", label="Employee Information"),
        actor_id=creator.id,
    )
    service.upsert_report_field(
        db, employee_info.id, ReportTemplateFieldUpsert(
            fieldKey="nino", label="NINO", fieldType="text",
            dataSourceKind="PAYROLL_EMPLOYEE", sourceColumn="nino",
        ), actor_id=creator.id,
    )
    ytd = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="ytd", label="Year-to-Date"), actor_id=creator.id,
    )
    service.upsert_report_field(
        db, ytd.id, ReportTemplateFieldUpsert(
            fieldKey="ni_ytd", label="NI (YTD)", fieldType="currency",
            dataSourceKind="PAYSLIP_ITEM", sourceColumn="ni_employee", aggregation="SUM_YTD",
        ), actor_id=creator.id,
    )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)
    return template


def test_generate_uk_employee_report_p60_resolves_employee_and_ytd_fields(db, organization):
    creator = _make_user(db, "creator_p60a@test.com")
    approver = _make_user(db, "approver_p60a@test.com")
    _make_company(db, organization.id, country="UK")
    run, employee, item = _make_run_with_payslip(db, organization.id, status="Approved")
    run.period_end = date(2027, 3, 20)
    item.ni_employee = 200
    employee.compliance_fields = {"nino": "QQ654321C"}
    db.commit()

    template = _build_uk_p60_template(db, creator, approver)
    generated = service.generate_uk_employee_report(
        db, organization.id, template.id, employee.id, date(2027, 4, 5), actor_id=creator.id,
    )
    assert generated.payroll_run_id is None
    assert generated.employee_id == employee.id
    assert generated.scope_key == f"EMPLOYEE:{employee.id}"
    values = generated.rendered_data["employees"][0]["values"]
    assert values["nino"] == "QQ654321C"
    assert values["ni_ytd"] == 200.0


def test_generate_uk_employee_report_certificate_pdf_renders(db, organization):
    """Confirms P60's "employees": [...] shape is genuinely compatible
    with the EXISTING generate_report_certificate_pdf_bytes renderer —
    no new PDF-rendering code needed for P45/P60."""
    creator = _make_user(db, "creator_p60cert@test.com")
    approver = _make_user(db, "approver_p60cert@test.com")
    _make_company(db, organization.id, country="UK")
    run, employee, item = _make_run_with_payslip(db, organization.id, status="Approved")
    template = _build_uk_p60_template(db, creator, approver, key="UK-P60-CERT")
    generated = service.generate_uk_employee_report(db, organization.id, template.id, employee.id, date(2026, 4, 5))

    pdf_bytes = service.generate_report_certificate_pdf_bytes(db, organization.id, generated.id, employee.id)
    assert pdf_bytes.startswith(b"%PDF")


def test_generate_uk_employee_report_rejects_wrong_report_type(db, organization):
    creator = _make_user(db, "creator_p60b@test.com")
    approver = _make_user(db, "approver_p60b@test.com")
    _make_company(db, organization.id, country="UK")
    run, employee, item = _make_run_with_payslip(db, organization.id, status="Approved")
    template = _build_template(db, creator, approver, country="UK", version="9.0")  # TDS, not P45/P60
    with pytest.raises(BadRequestException):
        service.generate_uk_employee_report(db, organization.id, template.id, employee.id, date(2026, 4, 5))


def test_generate_uk_employee_report_rejects_jurisdiction_mismatch(db, organization):
    creator = _make_user(db, "creator_p60c@test.com")
    approver = _make_user(db, "approver_p60c@test.com")
    _make_company(db, organization.id, country="IN")
    run, employee, item = _make_run_with_payslip(db, organization.id, status="Approved")
    # Employee has no explicit country_code -> resolves to the org's IN default.
    template = _build_uk_p60_template(db, creator, approver, key="UK-P60-MISMATCH")
    with pytest.raises(BadRequestException):
        service.generate_uk_employee_report(db, organization.id, template.id, employee.id, date(2026, 4, 5))


def test_generate_uk_employee_report_regenerating_supersedes_prior(db, organization):
    creator = _make_user(db, "creator_p60d@test.com")
    approver = _make_user(db, "approver_p60d@test.com")
    _make_company(db, organization.id, country="UK")
    run, employee, item = _make_run_with_payslip(db, organization.id, status="Approved")
    template = _build_uk_p60_template(db, creator, approver, key="UK-P60-SUPERSEDE")

    first = service.generate_uk_employee_report(db, organization.id, template.id, employee.id, date(2026, 4, 5))
    second = service.generate_uk_employee_report(db, organization.id, template.id, employee.id, date(2026, 4, 5))
    db.refresh(first)
    assert first.status == "Superseded"
    assert second.status == "Generated"


def _build_uk_eps_template(db, creator, approver, key="UK-EPS-GEN-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="EPS", reportType="EPS",
            jurisdictionCountry="UK", reportingYear="2026-27",
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
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)
    return template


def test_generate_uk_eps_is_org_level_with_no_run_or_employee(db, organization):
    from app.modules.payroll.models import OrganizationYtdAccumulator

    creator = _make_user(db, "creator_eps1@test.com")
    approver = _make_user(db, "approver_eps1@test.com")
    _make_company(db, organization.id, country="UK")
    db.add(OrganizationYtdAccumulator(
        organization_id=organization.id, tax_year="UK-TY-2026-27", tax_component="uk_employer_ni_total",
        ytd_taxable_wages=8000,
    ))
    db.commit()

    template = _build_uk_eps_template(db, creator, approver)
    generated = service.generate_uk_eps(
        db, organization.id, template.id, "2026-27", "M06",
        employer_has_claimed_allowance=True, as_of=date(2026, 9, 1), actor_id=creator.id,
    )
    assert generated.payroll_run_id is None
    assert generated.employee_id is None
    assert generated.scope_key == "PERIOD:2026-27:M06"
    assert generated.rendered_data["employer"]["employer_name"]
    declaration = generated.rendered_data["declaration"]
    assert declaration["employerHasClaimedAllowance"] is True
    assert declaration["cumulativeEmployerNi"] == 8000.0


def test_generate_uk_eps_no_employees_paid_flag(db, organization):
    creator = _make_user(db, "creator_eps2@test.com")
    approver = _make_user(db, "approver_eps2@test.com")
    _make_company(db, organization.id, country="UK")
    template = _build_uk_eps_template(db, creator, approver, key="UK-EPS-NOEMP")
    generated = service.generate_uk_eps(
        db, organization.id, template.id, "2026-27", "M07",
        no_employees_paid=True, as_of=date(2026, 10, 1), actor_id=creator.id,
    )
    assert generated.rendered_data["declaration"]["noEmployeesPaidThisPeriod"] is True
    assert generated.rendered_data["declaration"]["cumulativeEmployerNi"] == 0.0


def test_generate_uk_eps_regenerating_same_period_supersedes_prior(db, organization):
    creator = _make_user(db, "creator_eps3@test.com")
    approver = _make_user(db, "approver_eps3@test.com")
    _make_company(db, organization.id, country="UK")
    template = _build_uk_eps_template(db, creator, approver, key="UK-EPS-SUPERSEDE")
    first = service.generate_uk_eps(db, organization.id, template.id, "2026-27", "M08", actor_id=creator.id)
    second = service.generate_uk_eps(db, organization.id, template.id, "2026-27", "M08", actor_id=creator.id)
    db.refresh(first)
    assert first.status == "Superseded"
    assert second.status == "Generated"


def test_generate_uk_eps_includes_recovered_statutory_pay_when_declared(db, organization):
    creator = _make_user(db, "creator_eps5@test.com")
    approver = _make_user(db, "approver_eps5@test.com")
    _make_company(db, organization.id, country="UK")
    template = _build_uk_eps_template(db, creator, approver, key="UK-EPS-RECOVERY")
    from decimal import Decimal as D
    generated = service.generate_uk_eps(
        db, organization.id, template.id, "2026-27", "M16",
        total_statutory_pay_recovered=D("450.75"), as_of=date(2026, 11, 1), actor_id=creator.id,
    )
    assert generated.rendered_data["declaration"]["totalStatutoryPayRecovered"] == 450.75


def test_generate_uk_eps_omits_recovery_field_when_not_declared(db, organization):
    creator = _make_user(db, "creator_eps6@test.com")
    approver = _make_user(db, "approver_eps6@test.com")
    _make_company(db, organization.id, country="UK")
    template = _build_uk_eps_template(db, creator, approver, key="UK-EPS-NORECOVERY")
    generated = service.generate_uk_eps(db, organization.id, template.id, "2026-27", "M17", actor_id=creator.id)
    assert "totalStatutoryPayRecovered" not in generated.rendered_data["declaration"]


def test_generate_uk_eps_rejects_wrong_report_type(db, organization):
    creator = _make_user(db, "creator_eps4@test.com")
    approver = _make_user(db, "approver_eps4@test.com")
    _make_company(db, organization.id, country="UK")
    template = _build_uk_p60_template(db, creator, approver, key="UK-EPS-WRONGTYPE")
    with pytest.raises(BadRequestException):
        service.generate_uk_eps(db, organization.id, template.id, "2026-27", "M09")


# ── RTI XML rendering + RtiSubmission tracking (Part 9, 2026-09-09) ──────

def test_generate_rti_xml_bytes_fps_shape(db, organization):
    creator = _make_user(db, "creator_xml1@test.com")
    approver = _make_user(db, "approver_xml1@test.com")
    _make_company(db, organization.id, country="UK")
    run, employee, item = _make_run_with_payslip(db, organization.id, status="Approved")
    item.ni_employee = 58.66
    employee.compliance_fields = {"nino": "QQ111222C"}
    db.commit()

    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey="UK-FPS-XML-TEST", name="FPS", reportType="FPS",
            jurisdictionCountry="UK", reportingYear="2026-27",
        ), actor_id=creator.id,
    )
    employee_info = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="employee_info", label="Employee Information"),
        actor_id=creator.id,
    )
    service.upsert_report_field(
        db, employee_info.id, ReportTemplateFieldUpsert(
            fieldKey="nino", label="NINO", fieldType="text",
            dataSourceKind="PAYROLL_EMPLOYEE", sourceColumn="nino",
        ), actor_id=creator.id,
    )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)

    generated = service.generate_report_from_template(
        db, organization.id, template.id, run.id, reporting_period=run.period_label, actor_id=creator.id,
    )
    xml_bytes = service.generate_rti_xml_bytes(db, organization.id, generated.id)
    xml_text = xml_bytes.decode("utf-8")
    assert "<FullPaymentSubmission>" in xml_text
    assert "<NINO>QQ111222C</NINO>" in xml_text
    assert "<TaxYear>2026-27</TaxYear>" in xml_text


def test_generate_rti_xml_bytes_eps_shape(db, organization):
    creator = _make_user(db, "creator_xml2@test.com")
    approver = _make_user(db, "approver_xml2@test.com")
    _make_company(db, organization.id, country="UK")
    template = _build_uk_eps_template(db, creator, approver, key="UK-EPS-XML-TEST")
    generated = service.generate_uk_eps(
        db, organization.id, template.id, "2026-27", "M10", no_employees_paid=True, actor_id=creator.id,
    )
    xml_bytes = service.generate_rti_xml_bytes(db, organization.id, generated.id)
    xml_text = xml_bytes.decode("utf-8")
    assert "<EmployerPaymentSummary>" in xml_text
    assert "<NoEmployeesPaidThisPeriod>True</NoEmployeesPaidThisPeriod>" in xml_text


def test_generate_rti_xml_bytes_rejects_unsupported_report_type(db, organization):
    creator = _make_user(db, "creator_xml3@test.com")
    approver = _make_user(db, "approver_xml3@test.com")
    _make_company(db, organization.id, country="IN")
    run, employee, item = _make_run_with_payslip(db, organization.id, status="Approved")
    template = _build_template(db, creator, approver, country="IN", version="8.0")  # TDS
    generated = service.generate_report_from_template(
        db, organization.id, template.id, run.id, reporting_period=run.period_label, actor_id=creator.id,
    )
    with pytest.raises(BadRequestException):
        service.generate_rti_xml_bytes(db, organization.id, generated.id)


def test_rti_submission_lifecycle_draft_to_ready_to_submitted_to_acknowledged(db, organization):
    creator = _make_user(db, "creator_rti1@test.com")
    approver = _make_user(db, "approver_rti1@test.com")
    _make_company(db, organization.id, country="UK")
    template = _build_uk_eps_template(db, creator, approver, key="UK-EPS-RTI1")
    generated = service.generate_uk_eps(db, organization.id, template.id, "2026-27", "M11", actor_id=creator.id)

    submission = service.create_rti_submission(db, organization.id, generated.id, created_by_id=creator.id)
    assert submission.status == "DRAFT"
    assert submission.submission_type == "EPS"

    submission = service.set_rti_submission_status(db, organization.id, submission.id, "READY")
    assert submission.status == "READY"

    submission = service.set_rti_submission_status(db, organization.id, submission.id, "SUBMITTED", hmrc_correlation_id="CORR-123")
    assert submission.status == "SUBMITTED"
    assert submission.hmrc_correlation_id == "CORR-123"
    assert submission.submitted_at is not None

    submission = service.set_rti_submission_status(db, organization.id, submission.id, "ACKNOWLEDGED")
    assert submission.status == "ACKNOWLEDGED"
    assert submission.acknowledged_at is not None


def test_rti_submission_rejects_invalid_transition(db, organization):
    creator = _make_user(db, "creator_rti2@test.com")
    approver = _make_user(db, "approver_rti2@test.com")
    _make_company(db, organization.id, country="UK")
    template = _build_uk_eps_template(db, creator, approver, key="UK-EPS-RTI2")
    generated = service.generate_uk_eps(db, organization.id, template.id, "2026-27", "M12", actor_id=creator.id)
    submission = service.create_rti_submission(db, organization.id, generated.id)
    with pytest.raises(BadRequestException):
        service.set_rti_submission_status(db, organization.id, submission.id, "ACKNOWLEDGED")


def test_rti_submission_rejected_can_return_to_ready(db, organization):
    creator = _make_user(db, "creator_rti3@test.com")
    approver = _make_user(db, "approver_rti3@test.com")
    _make_company(db, organization.id, country="UK")
    template = _build_uk_eps_template(db, creator, approver, key="UK-EPS-RTI3")
    generated = service.generate_uk_eps(db, organization.id, template.id, "2026-27", "M13", actor_id=creator.id)
    submission = service.create_rti_submission(db, organization.id, generated.id)
    service.set_rti_submission_status(db, organization.id, submission.id, "READY")
    service.set_rti_submission_status(db, organization.id, submission.id, "SUBMITTED")
    submission = service.set_rti_submission_status(db, organization.id, submission.id, "REJECTED", rejection_reason="Invalid PAYE reference")
    assert submission.status == "REJECTED"
    assert submission.rejection_reason == "Invalid PAYE reference"
    submission = service.set_rti_submission_status(db, organization.id, submission.id, "READY")
    assert submission.status == "READY"


def test_rti_submission_rejects_non_rti_report_type(db, organization):
    creator = _make_user(db, "creator_rti4@test.com")
    approver = _make_user(db, "approver_rti4@test.com")
    _make_company(db, organization.id, country="IN")
    run, employee, item = _make_run_with_payslip(db, organization.id, status="Approved")
    template = _build_template(db, creator, approver, country="IN", version="7.0")  # TDS
    generated = service.generate_report_from_template(
        db, organization.id, template.id, run.id, reporting_period=run.period_label, actor_id=creator.id,
    )
    with pytest.raises(BadRequestException):
        service.create_rti_submission(db, organization.id, generated.id)


def test_list_rti_submissions_filters_by_status(db, organization):
    creator = _make_user(db, "creator_rti5@test.com")
    approver = _make_user(db, "approver_rti5@test.com")
    _make_company(db, organization.id, country="UK")
    template = _build_uk_eps_template(db, creator, approver, key="UK-EPS-RTI5")
    g1 = service.generate_uk_eps(db, organization.id, template.id, "2026-27", "M14", actor_id=creator.id)
    g2 = service.generate_uk_eps(db, organization.id, template.id, "2026-27", "M15", actor_id=creator.id)
    s1 = service.create_rti_submission(db, organization.id, g1.id)
    s2 = service.create_rti_submission(db, organization.id, g2.id)
    service.set_rti_submission_status(db, organization.id, s2.id, "READY")

    drafts = service.list_rti_submissions(db, organization.id, status="DRAFT")
    assert [s.id for s in drafts] == [s1.id]
    ready = service.list_rti_submissions(db, organization.id, status="READY")
    assert [s.id for s in ready] == [s2.id]


# ── India Form 130/138 (ZP-TAX-IN-2026-27-001 §6.2/§6.3, gap-closure ────
# Phase E, 2026-09-10): Form 130 reuses the widened generate_uk_employee_
# report (its own logic was never actually UK-specific); Form 138 is
# genuinely new (cross-run quarterly TDS aggregation).

def _build_india_form_130_template(db, creator, approver, key="IN-FORM-130-GEN-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="Form 130", reportType="FORM_130",
            jurisdictionCountry="IN", reportingYear="2026-27",
            documentScope="PER_EMPLOYEE",
        ), actor_id=creator.id,
    )
    tax = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="tax", label="Tax"), actor_id=creator.id,
    )
    service.upsert_report_field(
        db, tax.id, ReportTemplateFieldUpsert(
            fieldKey="tds", label="TDS", fieldType="currency",
            dataSourceKind="PAYSLIP_ITEM", sourceColumn="tds",
        ), actor_id=creator.id,
    )
    ytd = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="ytd", label="Year-to-Date"), actor_id=creator.id,
    )
    service.upsert_report_field(
        db, ytd.id, ReportTemplateFieldUpsert(
            fieldKey="tds_ytd", label="TDS (Year-to-Date)", fieldType="currency",
            dataSourceKind="PAYSLIP_ITEM", sourceColumn="tds", aggregation="SUM_YTD",
        ), actor_id=creator.id,
    )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)
    return template


def test_generate_india_form_130_via_widened_uk_employee_report(db, organization):
    creator = _make_user(db, "creator_f130a@test.com")
    approver = _make_user(db, "approver_f130a@test.com")
    _make_company(db, organization.id, country="IN")
    run, employee, item = _make_run_with_payslip(db, organization.id, status="Approved")
    run.period_end = date(2026, 6, 15)
    item.tds = 1200
    db.commit()

    template = _build_india_form_130_template(db, creator, approver)
    generated = service.generate_uk_employee_report(
        db, organization.id, template.id, employee.id, date(2027, 3, 31), actor_id=creator.id,
    )
    assert generated.report_type == "FORM_130"
    assert generated.payroll_run_id is None
    assert generated.scope_key == f"EMPLOYEE:{employee.id}"
    values = generated.rendered_data["employees"][0]["values"]
    assert values["tds_ytd"] == 1200.0


def test_india_report_ytd_uses_april_fy_not_calendar_year(db, organization):
    # The bug this proves fixed: a payslip from April-December (the FIRST
    # half of India's real FY) must count toward a Jan-March as_of date's
    # YTD total — a naive "Jan 1 of as_of's year" boundary would silently
    # EXCLUDE it (Jan 1 2027 > June 2026), understating TDS on the
    # certificate exactly like ZP-TAX-UK-2026-27-001's own §18 P60 bug did
    # for UK before that fix.
    from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem

    creator = _make_user(db, "creator_f130b@test.com")
    approver = _make_user(db, "approver_f130b@test.com")
    _make_company(db, organization.id, country="IN")

    employee = PayrollEmployee(organization_id=organization.id, employee_code="E130", name="Priya Nair")
    db.add(employee)
    db.commit()
    db.refresh(employee)

    def _make_item(period_end, tds):
        run = PayrollRun(
            organization_id=organization.id, period_label=str(period_end), period_start=period_end, period_end=period_end,
            pay_date=period_end, status="Approved",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        item = PayslipItem(
            payroll_run_id=run.id, employee_id=employee.id, organization_id=organization.id,
            employee_name=employee.name, gross_pay=50000, tds=tds, total_deductions=0, net_pay=50000,
        )
        db.add(item)
        db.commit()

    _make_item(date(2025, 12, 15), Decimal("999"))  # previous FY — must NOT count
    _make_item(date(2026, 6, 15), Decimal("500"))    # this FY, April-December half — MUST count

    template = _build_india_form_130_template(db, creator, approver, key="IN-FORM-130-FY")
    generated = service.generate_uk_employee_report(
        db, organization.id, template.id, employee.id, date(2027, 3, 31), actor_id=creator.id,
    )
    values = generated.rendered_data["employees"][0]["values"]
    assert values["tds_ytd"] == 500.0


def _build_india_form_138_template(db, creator, approver, key="IN-FORM-138-GEN-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="Form 138", reportType="FORM_138",
            jurisdictionCountry="IN", reportingYear="2026-27",
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
    tax = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="tax", label="Tax"), actor_id=creator.id,
    )
    service.upsert_report_field(
        db, tax.id, ReportTemplateFieldUpsert(
            fieldKey="total_tds", label="Total TDS Deducted", fieldType="currency",
            dataSourceKind="PAYSLIP_ITEM", sourceColumn="tds", aggregation="SUM_RUN",
        ), actor_id=creator.id,
    )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)
    return template


def _make_india_quarter_run(db, organization_id, employee_id, period_end, tds, status="Approved"):
    from app.modules.payroll.models import PayrollRun, PayslipItem

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
        employee_name="Quarter Employee", country_code="IN",
        gross_pay=50000, tds=tds, total_deductions=0, net_pay=50000,
    )
    db.add(item)
    db.commit()
    return run, item


def test_india_quarter_date_range_boundaries():
    assert service._india_quarter_date_range("2026-27", "Q1") == (date(2026, 4, 1), date(2026, 6, 30))
    assert service._india_quarter_date_range("2026-27", "Q2") == (date(2026, 7, 1), date(2026, 9, 30))
    assert service._india_quarter_date_range("2026-27", "Q3") == (date(2026, 10, 1), date(2026, 12, 31))
    # Q4 (Jan-Mar) falls in the SECOND calendar year of the FY string.
    assert service._india_quarter_date_range("2026-27", "Q4") == (date(2027, 1, 1), date(2027, 3, 31))


def test_india_quarter_date_range_rejects_unknown_period_or_year():
    with pytest.raises(BadRequestException):
        service._india_quarter_date_range("2026-27", "Q5")
    with pytest.raises(BadRequestException):
        service._india_quarter_date_range("not-a-year", "Q1")


def test_generate_india_form_138_sums_tds_across_quarter_runs(db, organization):
    creator = _make_user(db, "creator_f138a@test.com")
    approver = _make_user(db, "approver_f138a@test.com")
    _make_company(db, organization.id, country="IN")
    from app.modules.payroll.models import PayrollEmployee

    employee = PayrollEmployee(organization_id=organization.id, employee_code="E138", name="Quarter Employee")
    db.add(employee)
    db.commit()
    db.refresh(employee)

    # Q1 = April-June 2026 — three monthly runs, all inside the quarter.
    _make_india_quarter_run(db, organization.id, employee.id, date(2026, 4, 30), Decimal("1000"))
    _make_india_quarter_run(db, organization.id, employee.id, date(2026, 5, 31), Decimal("1500"))
    _make_india_quarter_run(db, organization.id, employee.id, date(2026, 6, 30), Decimal("2000"))
    # Outside the quarter (Q2) — must NOT be summed in.
    _make_india_quarter_run(db, organization.id, employee.id, date(2026, 7, 31), Decimal("9999"))
    # Inside the quarter but still Draft — must NOT be summed in (only
    # finalized runs count toward a real filed statutory statement).
    _make_india_quarter_run(db, organization.id, employee.id, date(2026, 6, 15), Decimal("8888"), status="Draft")

    template = _build_india_form_138_template(db, creator, approver)
    generated = service.generate_india_form_138(
        db, organization.id, template.id, "2026-27", "Q1", actor_id=creator.id,
    )
    assert generated.report_type == "FORM_138"
    assert generated.payroll_run_id is None
    assert generated.scope_key == "PERIOD:2026-27:Q1"
    assert generated.reporting_period == "Q1"
    assert generated.rendered_data["employer"]["total_tds"] == 4500.0  # 1000+1500+2000, not 9999/8888
    assert generated.rendered_data["employeeCount"] == 1


def test_generate_india_form_138_rejects_wrong_report_type(db, organization):
    creator = _make_user(db, "creator_f138b@test.com")
    approver = _make_user(db, "approver_f138b@test.com")
    _make_company(db, organization.id, country="IN")
    template = _build_template(db, creator, approver, country="IN", version="8.0")  # TDS, not FORM_138
    with pytest.raises(BadRequestException):
        service.generate_india_form_138(db, organization.id, template.id, "2026-27", "Q1")


def test_generate_india_form_138_regenerating_supersedes_prior(db, organization):
    creator = _make_user(db, "creator_f138c@test.com")
    approver = _make_user(db, "approver_f138c@test.com")
    _make_company(db, organization.id, country="IN")
    template = _build_india_form_138_template(db, creator, approver, key="IN-FORM-138-SUPERSEDE")

    first = service.generate_india_form_138(db, organization.id, template.id, "2026-27", "Q1")
    second = service.generate_india_form_138(db, organization.id, template.id, "2026-27", "Q1")
    db.refresh(first)
    assert first.status == "Superseded"
    assert second.status == "Generated"


# ── RTI & Forms summary widened to include India (gap-closure follow-up, ─
# 2026-09-10) — get_rti_forms_summary previously only ever returned UK
# FPS/EPS/P45/P60 rows.

def test_rti_forms_summary_includes_india_forms(db, organization):
    creator = _make_user(db, "creator_summary1@test.com")
    approver = _make_user(db, "approver_summary1@test.com")
    _make_company(db, organization.id, country="IN")
    template = _build_india_form_138_template(db, creator, approver, key="IN-FORM-138-SUMMARY")
    service.generate_india_form_138(db, organization.id, template.id, "2026-27", "Q1")

    rows = service.get_rti_forms_summary(db, organization.id)
    assert len(rows) == 1
    assert rows[0]["reportType"] == "FORM_138"
    assert rows[0]["submissions"] == []  # RTI submission tracking is UK-only


def test_rti_forms_summary_includes_ca_forms(db, organization):
    creator = _make_user(db, "creator_summary3@test.com")
    approver = _make_user(db, "approver_summary3@test.com")
    _make_company(db, organization.id, country="CA")
    template = _build_ca_pd7a_template(db, creator, approver, key="CA-PD7A-SUMMARY")
    service.generate_ca_pd7a(db, organization.id, template.id, date(2026, 1, 1), date(2026, 1, 31))

    rows = service.get_rti_forms_summary(db, organization.id)
    assert len(rows) == 1
    assert rows[0]["reportType"] == "PD7A"
    assert rows[0]["submissions"] == []  # RTI submission tracking is UK-only


def test_rti_forms_summary_excludes_unrelated_report_types(db, organization):
    creator = _make_user(db, "creator_summary2@test.com")
    approver = _make_user(db, "approver_summary2@test.com")
    _make_company(db, organization.id, country="IN")
    run, employee, item = _make_run_with_payslip(db, organization.id, status="Approved")
    template = _build_template(db, creator, approver, country="IN", version="11.0")  # plain "TDS", not a tracked type
    service.generate_report_from_template(db, organization.id, template.id, run.id, actor_id=creator.id)

    rows = service.get_rti_forms_summary(db, organization.id)
    assert rows == []


# ── India Form 123 (employer perquisite statement) ──────────────────────

def _build_india_form_123_template(db, creator, approver, key="IN-FORM-123-GEN-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="Form 123", reportType="FORM_123",
            jurisdictionCountry="IN", reportingYear="2026-27",
            documentScope="PER_EMPLOYEE",
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
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)
    return template


def test_generate_india_form_123_sources_from_issued_benefit_valuations(db, organization):
    from app.modules.payroll.models import PayrollEmployee

    creator = _make_user(db, "creator_f123a@test.com")
    approver = _make_user(db, "approver_f123a@test.com")
    _make_company(db, organization.id, country="IN")
    employee = PayrollEmployee(organization_id=organization.id, employee_code="F123", name="Ravi Kumar", country_code="IN")
    db.add(employee)
    db.commit()
    db.refresh(employee)

    issued = service.create_employee_benefit_valuation(db, organization.id, employee.id, "2026-27", "CAR", Decimal("50000"))
    service.issue_employee_benefit_valuation(db, organization.id, issued.id)
    # Draft valuation must NOT appear in the generated statement.
    service.create_employee_benefit_valuation(db, organization.id, employee.id, "2026-27", "ACCOMMODATION", Decimal("999999"))

    template = _build_india_form_123_template(db, creator, approver)
    generated = service.generate_india_form_123(db, organization.id, template.id, employee.id, "2026-27", actor_id=creator.id)

    assert generated.report_type == "FORM_123"
    assert generated.scope_key == f"EMPLOYEE:{employee.id}:2026-27"
    employee_data = generated.rendered_data["employees"][0]
    assert employee_data["values"]["totalTaxableValue"] == 50000.0
    assert len(employee_data["benefits"]) == 1
    assert employee_data["benefits"][0]["benefitType"] == "CAR"


def test_generate_india_form_123_rejects_wrong_report_type(db, organization):
    creator = _make_user(db, "creator_f123b@test.com")
    approver = _make_user(db, "approver_f123b@test.com")
    _make_company(db, organization.id, country="IN")
    template = _build_template(db, creator, approver, country="IN", version="10.0")  # TDS, not FORM_123
    with pytest.raises(BadRequestException):
        service.generate_india_form_123(db, organization.id, template.id, 1, "2026-27")


# ── Canada T4/RL-1/ROE (per-employee) + PD7A (per-period) ────────────────
# (ZP-TAX-CA-2026-001, forms/reports gap-closure). T4/RL-1/ROE reuse the
# widened generate_uk_employee_report exactly like India's Form 130 above;
# PD7A is genuinely new (cross-run remittance-period aggregation, same
# shape as Form 138 but with an explicit date range instead of a fixed
# FY-quarter scheme).

def _build_ca_t4_template(db, creator, approver, key="CA-T4-GEN-TEST", report_type="T4"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="T4", reportType=report_type,
            jurisdictionCountry="CA", reportingYear="2026",
            documentScope="PER_EMPLOYEE",
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
        db, template.id, ReportTemplateComponentUpsert(componentKey="earnings", label="Earnings"), actor_id=creator.id,
    )
    for field_key, source_column in (
        ("employment_income", "gross_pay"), ("income_tax_deducted", "tds"),
        ("cpp_contributions", "social_security"), ("ei_premiums", "esi"),
    ):
        service.upsert_report_field(
            db, earnings.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=field_key, fieldType="currency",
                dataSourceKind="PAYSLIP_ITEM", sourceColumn=source_column, aggregation="SUM_YTD",
            ), actor_id=creator.id,
        )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)
    return template


def test_generate_ca_t4_via_widened_uk_employee_report(db, organization):
    creator = _make_user(db, "creator_t4a@test.com")
    approver = _make_user(db, "approver_t4a@test.com")
    _make_company(db, organization.id, country="CA")
    run, employee, item = _make_run_with_payslip(db, organization.id, status="Approved")
    run.period_end = date(2026, 6, 15)
    item.gross_pay = 8000
    item.tds = 1200
    item.social_security = 396
    item.esi = 104
    db.commit()

    template = _build_ca_t4_template(db, creator, approver)
    generated = service.generate_uk_employee_report(
        db, organization.id, template.id, employee.id, date(2026, 12, 31), actor_id=creator.id,
    )
    assert generated.report_type == "T4"
    assert generated.payroll_run_id is None
    assert generated.scope_key == f"EMPLOYEE:{employee.id}"
    values = generated.rendered_data["employees"][0]["values"]
    assert values["employee_name"] == employee.name  # PAYROLL_EMPLOYEE, not the (unresolvable, item=None) PAYSLIP_ITEM field
    assert values["employment_income"] == 8000.0
    assert values["income_tax_deducted"] == 1200.0
    assert values["cpp_contributions"] == 396.0
    assert values["ei_premiums"] == 104.0


def test_generate_ca_rl1_and_roe_reuse_same_widened_function(db, organization):
    # RL-1 and ROE are just two more entries on generate_uk_employee_
    # report's report_type allow-list — this proves both are actually
    # reachable, not merely documented.
    creator = _make_user(db, "creator_t4b@test.com")
    approver = _make_user(db, "approver_t4b@test.com")
    _make_company(db, organization.id, country="CA")
    run, employee, item = _make_run_with_payslip(db, organization.id, status="Approved")
    run.period_end = date(2026, 6, 15)
    item.gross_pay = 5000
    db.commit()

    rl1_template = _build_ca_t4_template(db, creator, approver, key="CA-RL1-GEN-TEST", report_type="RL1")
    rl1 = service.generate_uk_employee_report(
        db, organization.id, rl1_template.id, employee.id, date(2026, 12, 31), actor_id=creator.id,
    )
    assert rl1.report_type == "RL1"
    assert rl1.rendered_data["employees"][0]["values"]["employment_income"] == 5000.0

    roe_template = _build_ca_t4_template(db, creator, approver, key="CA-ROE-GEN-TEST", report_type="ROE")
    roe = service.generate_uk_employee_report(
        db, organization.id, roe_template.id, employee.id, date(2026, 9, 30), actor_id=creator.id,
    )
    assert roe.report_type == "ROE"
    assert roe.rendered_data["asOfDate"] == "2026-09-30"


def _build_ca_pd7a_template(db, creator, approver, key="CA-PD7A-GEN-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="PD7A", reportType="PD7A",
            jurisdictionCountry="CA", reportingYear="2026",
        ), actor_id=creator.id,
    )
    remittance = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="remittance", label="Remittance"), actor_id=creator.id,
    )
    for field_key, source_column in (
        ("income_tax_withheld", "tds"), ("cpp_employee", "social_security"),
        ("cpp_employer", "employer_social_security"), ("ei_employee", "esi"), ("ei_employer", "employer_esi"),
    ):
        service.upsert_report_field(
            db, remittance.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=field_key, fieldType="currency",
                dataSourceKind="PAYSLIP_ITEM", sourceColumn=source_column, aggregation="SUM_RUN",
            ), actor_id=creator.id,
        )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)
    return template


def _make_ca_period_run(db, organization_id, employee_id, period_end, *, tds, cpp_ee, cpp_er, ei_ee, ei_er, status="Approved"):
    from app.modules.payroll.models import PayrollRun, PayslipItem

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
        employee_name="Remittance Employee", country_code="CA",
        gross_pay=8000, tds=tds, social_security=cpp_ee, employer_social_security=cpp_er,
        esi=ei_ee, employer_esi=ei_er, total_deductions=0, net_pay=8000,
    )
    db.add(item)
    db.commit()
    return run, item


def test_generate_ca_pd7a_sums_across_period_runs(db, organization):
    from app.modules.payroll.models import PayrollEmployee

    creator = _make_user(db, "creator_pd7a1@test.com")
    approver = _make_user(db, "approver_pd7a1@test.com")
    _make_company(db, organization.id, country="CA")
    employee = PayrollEmployee(organization_id=organization.id, employee_code="ECA1", name="Remittance Employee")
    db.add(employee)
    db.commit()
    db.refresh(employee)

    # Inside the January remittance period.
    _make_ca_period_run(db, organization.id, employee.id, date(2026, 1, 15), tds=1200, cpp_ee=396, cpp_er=396, ei_ee=104, ei_er=146)
    _make_ca_period_run(db, organization.id, employee.id, date(2026, 1, 31), tds=1200, cpp_ee=396, cpp_er=396, ei_ee=104, ei_er=146)
    # Outside the period — must NOT be summed in.
    _make_ca_period_run(db, organization.id, employee.id, date(2026, 2, 15), tds=9999, cpp_ee=9999, cpp_er=9999, ei_ee=9999, ei_er=9999)
    # Inside the period but still Draft — must NOT be summed in.
    _make_ca_period_run(db, organization.id, employee.id, date(2026, 1, 20), tds=8888, cpp_ee=8888, cpp_er=8888, ei_ee=8888, ei_er=8888, status="Draft")

    template = _build_ca_pd7a_template(db, creator, approver)
    generated = service.generate_ca_pd7a(
        db, organization.id, template.id, date(2026, 1, 1), date(2026, 1, 31), actor_id=creator.id,
    )
    assert generated.report_type == "PD7A"
    assert generated.payroll_run_id is None
    assert generated.scope_key == "PERIOD:2026-01-01:2026-01-31"
    assert generated.rendered_data["employer"]["income_tax_withheld"] == 2400.0
    assert generated.rendered_data["employer"]["cpp_employee"] == 792.0
    assert generated.rendered_data["employer"]["cpp_employer"] == 792.0
    assert generated.rendered_data["employer"]["ei_employee"] == 208.0
    assert generated.rendered_data["employer"]["ei_employer"] == 292.0
    assert generated.rendered_data["employeeCount"] == 1
    assert generated.rendered_data["totalRemittance"] == 2400.0 + 792.0 + 792.0 + 208.0 + 292.0


def test_generate_ca_pd7a_rejects_wrong_report_type(db, organization):
    creator = _make_user(db, "creator_pd7a2@test.com")
    approver = _make_user(db, "approver_pd7a2@test.com")
    _make_company(db, organization.id, country="CA")
    template = _build_template(db, creator, approver, country="CA", version="12.0")  # TDS, not PD7A
    with pytest.raises(BadRequestException):
        service.generate_ca_pd7a(db, organization.id, template.id, date(2026, 1, 1), date(2026, 1, 31))


def test_generate_ca_pd7a_rejects_inverted_date_range(db, organization):
    creator = _make_user(db, "creator_pd7a3@test.com")
    approver = _make_user(db, "approver_pd7a3@test.com")
    _make_company(db, organization.id, country="CA")
    template = _build_ca_pd7a_template(db, creator, approver, key="CA-PD7A-INVERTED")
    with pytest.raises(BadRequestException):
        service.generate_ca_pd7a(db, organization.id, template.id, date(2026, 1, 31), date(2026, 1, 1))


def test_generate_ca_pd7a_regenerating_supersedes_prior(db, organization):
    creator = _make_user(db, "creator_pd7a4@test.com")
    approver = _make_user(db, "approver_pd7a4@test.com")
    _make_company(db, organization.id, country="CA")
    template = _build_ca_pd7a_template(db, creator, approver, key="CA-PD7A-SUPERSEDE")

    first = service.generate_ca_pd7a(db, organization.id, template.id, date(2026, 1, 1), date(2026, 1, 31))
    second = service.generate_ca_pd7a(db, organization.id, template.id, date(2026, 1, 1), date(2026, 1, 31))
    db.refresh(first)
    assert first.status == "Superseded"
    assert second.status == "Generated"


# ── US: Form W-2 (Production-Readiness Plan Phase 5, 2026-09-15) ────────
# A bespoke generator (not the widened generate_uk_employee_report) — Box 3
# needs a wage-base cap and Box 15-20 are genuinely repeatable per-state/
# per-locality groups, neither of which the generic field mapper expresses.

def _build_us_w2_template(db, creator, approver, key="US-W2-GEN-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="W-2", reportType="W2",
            jurisdictionCountry="US", reportingYear="2026",
            documentScope="PER_EMPLOYEE",
        ), actor_id=creator.id,
    )
    # Real components/fields (same shape as scripts/seed_statutory_report_
    # templates.py's US-W2 entry) — generate_us_w2 walks these to build
    # component_snapshots/values, exactly like generate_india_form_123/
    # generate_ca_pd7a do, so the shared per-employee certificate PDF
    # renderer has real fieldKey/label pairs to render.
    employer_info = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="employer_info", label="Employer Information"),
        actor_id=creator.id,
    )
    for field_key, label, source_column in (
        ("employer_name", "Employer Name", "name"),
        ("employer_ein", "Employer Identification Number (EIN)", "employer_id"),
        ("employer_address", "Employer Address", "address"),
    ):
        service.upsert_report_field(
            db, employer_info.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=label, fieldType="text",
                dataSourceKind="EMPLOYER_PROFILE", sourceColumn=source_column,
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
    wages = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="wages", label="Wages & Federal Tax"), actor_id=creator.id,
    )
    for field_key, label, source_column in (
        ("box1_wages", "Box 1 - Wages, Tips, Other Compensation", "gross_pay"),
        ("box2_federal_tax", "Box 2 - Federal Income Tax Withheld", "federal_income_tax"),
    ):
        service.upsert_report_field(
            db, wages.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=label, fieldType="currency",
                dataSourceKind="PAYSLIP_ITEM", sourceColumn=source_column, aggregation="SUM_YTD",
            ), actor_id=creator.id,
        )
    ss_medicare = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="ss_medicare", label="Social Security & Medicare"),
        actor_id=creator.id,
    )
    for field_key, label, source_column in (
        ("box3_ss_wages", "Box 3 - Social Security Wages", "gross_pay"),
        ("box4_ss_tax", "Box 4 - Social Security Tax Withheld", "social_security"),
        ("box5_medicare_wages", "Box 5 - Medicare Wages and Tips", "gross_pay"),
        ("box6_medicare_tax", "Box 6 - Medicare Tax Withheld", "medicare"),
    ):
        service.upsert_report_field(
            db, ss_medicare.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=label, fieldType="currency",
                dataSourceKind="PAYSLIP_ITEM", sourceColumn=source_column, aggregation="SUM_YTD",
            ), actor_id=creator.id,
        )
    state_local = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="state_local", label="State & Local"), actor_id=creator.id,
    )
    for field_key, label, source_column in (
        ("box14_sdi", "Box 14 - State Disability Insurance", "state_disability_insurance"),
        ("box14_state_program", "Box 14 - State Payroll Programs (e.g. Paid Leave/TDI)", "state_program_deductions"),
        ("box16_state_wages", "Box 16 - State Wages, Tips, etc.", "gross_pay"),
        ("box17_state_tax", "Box 17 - State Income Tax", "state_income_tax"),
        ("box18_local_wages", "Box 18 - Local Wages, Tips, etc.", "gross_pay"),
        ("box19_local_tax", "Box 19 - Local Income Tax", "local_tax"),
    ):
        service.upsert_report_field(
            db, state_local.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=label, fieldType="currency",
                dataSourceKind="PAYSLIP_ITEM", sourceColumn=source_column, aggregation="SUM_YTD",
            ), actor_id=creator.id,
        )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)
    return template


def _make_us_run_with_payslip(db, organization_id, employee_id, pay_date, *, status="Approved", **overrides):
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
        gross_pay=8000, federal_income_tax=800, social_security=496, medicare=116,
        employer_social_security=496, employer_medicare=116,
        state_income_tax=200, local_tax=0, state_disability_insurance=0, state_program_deductions=0,
        work_state="CA", work_locality=None, total_deductions=0, net_pay=8000,
    )
    fields.update(overrides)
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee_id, organization_id=organization_id,
        employee_name="W-2 Employee", country_code="US", **fields,
    )
    db.add(item)
    db.commit()
    return run, item


def _make_us_employee(db, organization_id, code="EUSW2"):
    from app.modules.payroll.models import PayrollEmployee

    employee = PayrollEmployee(
        organization_id=organization_id, employee_code=code, name="W-2 Employee",
        compliance_fields={"ssn": "123-45-6789"},
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


def test_generate_us_w2_computes_boxes_from_ytd_payslips(db, organization):
    creator = _make_user(db, "creator_w2a@test.com")
    approver = _make_user(db, "approver_w2a@test.com")
    company = _make_company(db, organization.id, country="US")
    company.employer_id = "12-3456789"
    db.commit()
    employee = _make_us_employee(db, organization.id)

    _make_us_run_with_payslip(db, organization.id, employee.id, date(2026, 1, 31))
    _make_us_run_with_payslip(db, organization.id, employee.id, date(2026, 2, 28))

    template = _build_us_w2_template(db, creator, approver)
    generated = service.generate_us_w2(db, organization.id, template.id, employee.id, "2026", actor_id=creator.id)

    assert generated.report_type == "W2"
    assert generated.payroll_run_id is None
    assert generated.employee_id == employee.id
    assert generated.scope_key == f"EMPLOYEE:{employee.id}:2026"
    values = generated.rendered_data["employees"][0]["values"]
    assert values["employee_name"] == employee.name
    assert values["employer_name"] == "Acme India Pvt Ltd"
    assert values["employer_ein"] == "12-3456789"
    assert values["box1_wages"] == 16000.0
    assert values["box2_federal_tax"] == 1600.0
    assert values["box3_ss_wages"] == 16000.0  # well under the wage base
    assert values["box4_ss_tax"] == 992.0
    assert values["box5_medicare_wages"] == 16000.0
    assert values["box6_medicare_tax"] == 232.0
    assert values["box17_state_tax"] == 400.0
    assert values["stateLines"] == [{"state": "CA", "stateWages": 16000.0, "stateIncomeTax": 400.0}]
    assert values["localityLines"] == []


def test_generate_us_w2_caps_box3_at_social_security_wage_base(db, organization):
    from app.modules.payroll.hardcoded_defaults import _US_SOCIAL_SECURITY_WAGE_BASE

    creator = _make_user(db, "creator_w2b@test.com")
    approver = _make_user(db, "approver_w2b@test.com")
    _make_company(db, organization.id, country="US")
    employee = _make_us_employee(db, organization.id, code="EUSW2B")

    high_gross = _US_SOCIAL_SECURITY_WAGE_BASE + Decimal("50000")
    _make_us_run_with_payslip(db, organization.id, employee.id, date(2026, 12, 31), gross_pay=high_gross)

    template = _build_us_w2_template(db, creator, approver, key="US-W2-CAP-TEST")
    generated = service.generate_us_w2(db, organization.id, template.id, employee.id, "2026", actor_id=creator.id)
    values = generated.rendered_data["employees"][0]["values"]
    assert values["box3_ss_wages"] == float(_US_SOCIAL_SECURITY_WAGE_BASE)
    assert values["box5_medicare_wages"] == float(high_gross)  # Medicare has no wage-base ceiling


def test_generate_us_w2_handles_multiple_states_as_repeating_groups(db, organization):
    creator = _make_user(db, "creator_w2c@test.com")
    approver = _make_user(db, "approver_w2c@test.com")
    _make_company(db, organization.id, country="US")
    employee = _make_us_employee(db, organization.id, code="EUSW2C")

    _make_us_run_with_payslip(db, organization.id, employee.id, date(2026, 3, 31), work_state="CA", gross_pay=6000, state_income_tax=300)
    _make_us_run_with_payslip(db, organization.id, employee.id, date(2026, 9, 30), work_state="NY", gross_pay=7000, state_income_tax=350)

    template = _build_us_w2_template(db, creator, approver, key="US-W2-MULTISTATE-TEST")
    generated = service.generate_us_w2(db, organization.id, template.id, employee.id, "2026", actor_id=creator.id)
    values = generated.rendered_data["employees"][0]["values"]
    assert values["stateLines"] == [
        {"state": "CA", "stateWages": 6000.0, "stateIncomeTax": 300.0},
        {"state": "NY", "stateWages": 7000.0, "stateIncomeTax": 350.0},
    ]


def test_generate_us_w2_includes_local_and_box14_lines(db, organization):
    creator = _make_user(db, "creator_w2d@test.com")
    approver = _make_user(db, "approver_w2d@test.com")
    _make_company(db, organization.id, country="US")
    employee = _make_us_employee(db, organization.id, code="EUSW2D")

    _make_us_run_with_payslip(
        db, organization.id, employee.id, date(2026, 6, 30),
        work_locality="PHILADELPHIA", local_tax=50, state_disability_insurance=120, state_program_deductions=30,
    )

    template = _build_us_w2_template(db, creator, approver, key="US-W2-LOCAL-TEST")
    generated = service.generate_us_w2(db, organization.id, template.id, employee.id, "2026", actor_id=creator.id)
    values = generated.rendered_data["employees"][0]["values"]
    assert values["localityLines"] == [{"locality": "PHILADELPHIA", "localWages": 8000.0, "localIncomeTax": 50.0}]
    assert values["box14_sdi"] == 120.0
    assert values["box14_state_program"] == 30.0


def test_generate_us_w2_excludes_other_years_non_us_and_unfinalized_runs(db, organization):
    creator = _make_user(db, "creator_w2e@test.com")
    approver = _make_user(db, "approver_w2e@test.com")
    _make_company(db, organization.id, country="US")
    employee = _make_us_employee(db, organization.id, code="EUSW2E")

    _make_us_run_with_payslip(db, organization.id, employee.id, date(2026, 6, 30), gross_pay=8000)
    # Outside the tax year — must NOT be summed in.
    _make_us_run_with_payslip(db, organization.id, employee.id, date(2027, 1, 15), gross_pay=9999)
    # Still Draft — must NOT be summed in.
    _make_us_run_with_payslip(db, organization.id, employee.id, date(2026, 7, 31), gross_pay=9999, status="Draft")
    # Wrong country_code snapshot — must NOT be summed in.
    _, other_country_item = _make_us_run_with_payslip(db, organization.id, employee.id, date(2026, 8, 31), gross_pay=9999)
    other_country_item.country_code = "IN"
    db.commit()

    template = _build_us_w2_template(db, creator, approver, key="US-W2-EXCLUDE-TEST")
    generated = service.generate_us_w2(db, organization.id, template.id, employee.id, "2026", actor_id=creator.id)
    values = generated.rendered_data["employees"][0]["values"]
    assert values["box1_wages"] == 8000.0


def test_generate_us_w2_rejects_wrong_report_type(db, organization):
    creator = _make_user(db, "creator_w2f@test.com")
    approver = _make_user(db, "approver_w2f@test.com")
    _make_company(db, organization.id, country="US")
    employee = _make_us_employee(db, organization.id, code="EUSW2F")
    template = _build_template(db, creator, approver, country="US", version="w2-neg")  # TDS, not W2
    with pytest.raises(BadRequestException):
        service.generate_us_w2(db, organization.id, template.id, employee.id, "2026")


def test_generate_us_w2_rejects_invalid_tax_year(db, organization):
    creator = _make_user(db, "creator_w2g@test.com")
    approver = _make_user(db, "approver_w2g@test.com")
    _make_company(db, organization.id, country="US")
    employee = _make_us_employee(db, organization.id, code="EUSW2G")
    template = _build_us_w2_template(db, creator, approver, key="US-W2-BADYEAR-TEST")
    with pytest.raises(BadRequestException):
        service.generate_us_w2(db, organization.id, template.id, employee.id, "not-a-year")


def test_us_w2_certificate_pdf_renders_via_shared_renderer(db, organization):
    # The shared per-employee certificate renderer (generate_report_
    # certificate_pdf_bytes) reads templateSnapshot.components/fields to
    # know what to print — this confirms generate_us_w2 actually populates
    # that structure (not just a flat values dict the renderer can't see).
    creator = _make_user(db, "creator_w2i@test.com")
    approver = _make_user(db, "approver_w2i@test.com")
    company = _make_company(db, organization.id, country="US")
    company.employer_id = "98-7654321"
    db.commit()
    employee = _make_us_employee(db, organization.id, code="EUSW2I")
    _make_us_run_with_payslip(db, organization.id, employee.id, date(2026, 4, 30))

    template = _build_us_w2_template(db, creator, approver, key="US-W2-PDF-TEST")
    generated = service.generate_us_w2(db, organization.id, template.id, employee.id, "2026", actor_id=creator.id)

    pdf_bytes = service.generate_report_certificate_pdf_bytes(db, organization.id, generated.id, employee.id)
    assert isinstance(pdf_bytes, (bytes, bytearray))
    assert pdf_bytes[:4] == b"%PDF"
    assert len(pdf_bytes) > 1000


def test_generate_us_w2_regenerating_supersedes_prior(db, organization):
    creator = _make_user(db, "creator_w2h@test.com")
    approver = _make_user(db, "approver_w2h@test.com")
    _make_company(db, organization.id, country="US")
    employee = _make_us_employee(db, organization.id, code="EUSW2H")
    _make_us_run_with_payslip(db, organization.id, employee.id, date(2026, 5, 31))

    template = _build_us_w2_template(db, creator, approver, key="US-W2-SUPERSEDE-TEST")
    first = service.generate_us_w2(db, organization.id, template.id, employee.id, "2026", actor_id=creator.id)
    second = service.generate_us_w2(db, organization.id, template.id, employee.id, "2026", actor_id=creator.id)
    db.refresh(first)
    assert first.status == "Superseded"
    assert second.status == "Generated"


# ── US: Form 941 (Employer's Quarterly Federal Tax Return, 2026-09-15) ──
# Aggregate/employer-level, a fixed IRS calendar quarter — bespoke
# generator, same reasoning as generate_us_w2.

def _build_us_941_template(db, creator, approver, key="US-941-GEN-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="Form 941", reportType="941",
            jurisdictionCountry="US", reportingYear="2026",
            documentScope="AGGREGATE",
        ), actor_id=creator.id,
    )
    employer_info = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="employer_info", label="Employer Information"),
        actor_id=creator.id,
    )
    for field_key, label, source_column in (
        ("employer_name", "Employer Name", "name"),
        ("employer_ein", "EIN", "employer_id"),
    ):
        service.upsert_report_field(
            db, employer_info.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=label, fieldType="text",
                dataSourceKind="EMPLOYER_PROFILE", sourceColumn=source_column,
            ), actor_id=creator.id,
        )
    wages_tax = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="wages_tax", label="Wages & Federal Tax"), actor_id=creator.id,
    )
    for field_key, label, source_column in (
        ("line1_employee_count", "Line 1", "gross_pay"),  # placeholder — value is bespoke-computed, not mapped
        ("line2_wages", "Line 2", "gross_pay"),
        ("line3_federal_tax_withheld", "Line 3", "federal_income_tax"),
    ):
        service.upsert_report_field(
            db, wages_tax.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=label, fieldType="currency",
                dataSourceKind="PAYSLIP_ITEM", sourceColumn=source_column, aggregation="SUM_RUN",
            ), actor_id=creator.id,
        )
    ss_medicare = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="ss_medicare", label="SS & Medicare"), actor_id=creator.id,
    )
    for field_key in ("line5a_ss_wages", "line5a_ss_tax", "line5c_medicare_wages", "line5c_medicare_tax"):
        service.upsert_report_field(
            db, ss_medicare.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=field_key, fieldType="currency",
                dataSourceKind="PAYSLIP_ITEM", sourceColumn="social_security", aggregation="SUM_RUN",
            ), actor_id=creator.id,
        )
    totals = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="totals", label="Totals"), actor_id=creator.id,
    )
    for field_key in ("line6_total_taxes_before_adjustments", "line12_total_taxes_after_adjustments_and_credits"):
        service.upsert_report_field(
            db, totals.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=field_key, fieldType="currency",
                dataSourceKind="PAYSLIP_ITEM", sourceColumn="tds", aggregation="SUM_RUN",
            ), actor_id=creator.id,
        )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)
    return template


def test_generate_us_941_sums_quarter_wages_and_taxes(db, organization):
    creator = _make_user(db, "creator_941a@test.com")
    approver = _make_user(db, "approver_941a@test.com")
    company = _make_company(db, organization.id, country="US")
    company.employer_id = "11-2223334"
    db.commit()
    employee = _make_us_employee(db, organization.id, code="E941A")

    _make_us_run_with_payslip(db, organization.id, employee.id, date(2026, 1, 31))
    _make_us_run_with_payslip(db, organization.id, employee.id, date(2026, 2, 28))

    template = _build_us_941_template(db, creator, approver)
    generated = service.generate_us_941(db, organization.id, template.id, 2026, 1, actor_id=creator.id)

    assert generated.report_type == "941"
    assert generated.payroll_run_id is None
    assert generated.employee_id is None
    assert generated.scope_key == "PERIOD:2026-01-01:2026-03-31"
    assert generated.reporting_period == "Q1"
    values = generated.rendered_data["employer"]
    assert values["employer_ein"] == "11-2223334"
    assert values["line1_employee_count"] == 1
    assert values["line2_wages"] == 16000.0
    assert values["line3_federal_tax_withheld"] == 1600.0
    assert values["line5a_ss_wages"] == 16000.0  # derived from tax/rate, well under the wage base
    assert values["line5a_ss_tax"] == 992.0 + 992.0  # employee + employer (6.2% each on the same base)
    assert values["line5c_medicare_wages"] == 16000.0
    assert generated.rendered_data["employeeCount"] == 1


def test_generate_us_941_excludes_other_quarters_and_unfinalized_runs(db, organization):
    creator = _make_user(db, "creator_941b@test.com")
    approver = _make_user(db, "approver_941b@test.com")
    _make_company(db, organization.id, country="US")
    employee = _make_us_employee(db, organization.id, code="E941B")

    _make_us_run_with_payslip(db, organization.id, employee.id, date(2026, 2, 15), gross_pay=8000)
    # Outside Q1 — must NOT be summed in.
    _make_us_run_with_payslip(db, organization.id, employee.id, date(2026, 4, 15), gross_pay=9999)
    # Still Draft — must NOT be summed in.
    _make_us_run_with_payslip(db, organization.id, employee.id, date(2026, 3, 1), gross_pay=9999, status="Draft")

    template = _build_us_941_template(db, creator, approver, key="US-941-EXCLUDE-TEST")
    generated = service.generate_us_941(db, organization.id, template.id, 2026, 1, actor_id=creator.id)
    assert generated.rendered_data["employer"]["line2_wages"] == 8000.0


def test_generate_us_941_rejects_wrong_report_type(db, organization):
    creator = _make_user(db, "creator_941c@test.com")
    approver = _make_user(db, "approver_941c@test.com")
    _make_company(db, organization.id, country="US")
    template = _build_template(db, creator, approver, country="US", version="941-neg")  # TDS, not 941
    with pytest.raises(BadRequestException):
        service.generate_us_941(db, organization.id, template.id, 2026, 1)


def test_generate_us_941_rejects_invalid_quarter(db, organization):
    creator = _make_user(db, "creator_941d@test.com")
    approver = _make_user(db, "approver_941d@test.com")
    _make_company(db, organization.id, country="US")
    template = _build_us_941_template(db, creator, approver, key="US-941-BADQ-TEST")
    with pytest.raises(BadRequestException):
        service.generate_us_941(db, organization.id, template.id, 2026, 5)


def test_generate_us_941_regenerating_supersedes_prior(db, organization):
    creator = _make_user(db, "creator_941e@test.com")
    approver = _make_user(db, "approver_941e@test.com")
    _make_company(db, organization.id, country="US")
    employee = _make_us_employee(db, organization.id, code="E941E")
    _make_us_run_with_payslip(db, organization.id, employee.id, date(2026, 1, 15))

    template = _build_us_941_template(db, creator, approver, key="US-941-SUPERSEDE-TEST")
    first = service.generate_us_941(db, organization.id, template.id, 2026, 1, actor_id=creator.id)
    second = service.generate_us_941(db, organization.id, template.id, 2026, 1, actor_id=creator.id)
    db.refresh(first)
    assert first.status == "Superseded"
    assert second.status == "Generated"


# ── US: Form 940 (Employer's Annual FUTA Tax Return, 2026-09-15) ────────
# Aggregate/employer-level, calendar year — bespoke generator; the
# taxable-wages figure independently recomputes the real $7,000/employee/
# year FUTA wage-base cap rather than deriving it from tax (see
# generate_us_940's own docstring for why).

def _build_us_940_template(db, creator, approver, key="US-940-GEN-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="Form 940", reportType="940",
            jurisdictionCountry="US", reportingYear="2026",
            documentScope="AGGREGATE",
        ), actor_id=creator.id,
    )
    employer_info = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="employer_info", label="Employer Information"),
        actor_id=creator.id,
    )
    for field_key, label, source_column in (
        ("employer_name", "Employer Name", "name"),
        ("employer_ein", "EIN", "employer_id"),
    ):
        service.upsert_report_field(
            db, employer_info.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=label, fieldType="text",
                dataSourceKind="EMPLOYER_PROFILE", sourceColumn=source_column,
            ), actor_id=creator.id,
        )
    futa = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="futa", label="FUTA Wages & Tax"), actor_id=creator.id,
    )
    for field_key in ("total_payments", "futa_taxable_wages", "futa_tax_due", "employee_count"):
        service.upsert_report_field(
            db, futa.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=field_key, fieldType="currency",
                dataSourceKind="PAYSLIP_ITEM", sourceColumn="gross_pay", aggregation="SUM_RUN",
            ), actor_id=creator.id,
        )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)
    return template


def test_generate_us_940_caps_futa_wages_per_employee(db, organization):
    from app.modules.payroll.hardcoded_defaults import _US_FUTA_WAGE_BASE

    creator = _make_user(db, "creator_940a@test.com")
    approver = _make_user(db, "approver_940a@test.com")
    company = _make_company(db, organization.id, country="US")
    company.employer_id = "22-3334445"
    db.commit()
    employee = _make_us_employee(db, organization.id, code="E940A")

    high_gross = _US_FUTA_WAGE_BASE + Decimal("3000")
    _make_us_run_with_payslip(
        db, organization.id, employee.id, date(2026, 3, 31),
        gross_pay=high_gross, employer_futa=float(_US_FUTA_WAGE_BASE * Decimal("0.006")),
    )

    template = _build_us_940_template(db, creator, approver)
    generated = service.generate_us_940(db, organization.id, template.id, 2026, actor_id=creator.id)

    assert generated.report_type == "940"
    assert generated.payroll_run_id is None
    assert generated.employee_id is None
    assert generated.scope_key == "PERIOD:2026-01-01:2026-12-31"
    values = generated.rendered_data["employer"]
    assert values["employer_ein"] == "22-3334445"
    assert values["total_payments"] == float(high_gross)
    assert values["futa_taxable_wages"] == float(_US_FUTA_WAGE_BASE)  # capped, not the full high_gross
    assert values["employee_count"] == 1


def test_generate_us_940_sums_multiple_employees(db, organization):
    creator = _make_user(db, "creator_940b@test.com")
    approver = _make_user(db, "approver_940b@test.com")
    _make_company(db, organization.id, country="US")
    emp1 = _make_us_employee(db, organization.id, code="E940B1")
    emp2 = _make_us_employee(db, organization.id, code="E940B2")

    _make_us_run_with_payslip(db, organization.id, emp1.id, date(2026, 6, 30), gross_pay=5000, employer_futa=30)
    _make_us_run_with_payslip(db, organization.id, emp2.id, date(2026, 6, 30), gross_pay=6000, employer_futa=36)

    template = _build_us_940_template(db, creator, approver, key="US-940-MULTI-TEST")
    generated = service.generate_us_940(db, organization.id, template.id, 2026, actor_id=creator.id)
    values = generated.rendered_data["employer"]
    assert values["total_payments"] == 11000.0
    assert values["futa_tax_due"] == 66.0
    assert values["employee_count"] == 2


def test_generate_us_940_rejects_wrong_report_type(db, organization):
    creator = _make_user(db, "creator_940c@test.com")
    approver = _make_user(db, "approver_940c@test.com")
    _make_company(db, organization.id, country="US")
    template = _build_template(db, creator, approver, country="US", version="940-neg")  # TDS, not 940
    with pytest.raises(BadRequestException):
        service.generate_us_940(db, organization.id, template.id, 2026)


def test_generate_us_940_regenerating_supersedes_prior(db, organization):
    creator = _make_user(db, "creator_940d@test.com")
    approver = _make_user(db, "approver_940d@test.com")
    _make_company(db, organization.id, country="US")
    employee = _make_us_employee(db, organization.id, code="E940D")
    _make_us_run_with_payslip(db, organization.id, employee.id, date(2026, 5, 31), employer_futa=48)

    template = _build_us_940_template(db, creator, approver, key="US-940-SUPERSEDE-TEST")
    first = service.generate_us_940(db, organization.id, template.id, 2026, actor_id=creator.id)
    second = service.generate_us_940(db, organization.id, template.id, 2026, actor_id=creator.id)
    db.refresh(first)
    assert first.status == "Superseded"
    assert second.status == "Generated"
