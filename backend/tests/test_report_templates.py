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
