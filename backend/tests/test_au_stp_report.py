"""
tests/test_au_stp_report.py
------------------------------
Phase 9 (Forms & Reports, ZP-TAX-AU-2026-27-001 §12, 2026-09-17) —
proves the seeded "AU-STP" ReportTemplate (scripts/seed_statutory_
report_templates.py) generates correctly through the SAME generic
generate_report_from_template engine every other country's reports
already use (CA T4/RL1/ROE/PD7A, India Form 130/138/123, UK P60) — no
new generation code was needed for Australia, only the template
authoring this test reproduces inline. Also proves RtiSubmission's
widened submission_type set (now including "STP"/"SUPERSTREAM") and its
new schema_version column work end to end.
"""
from datetime import date

from app.modules.payroll import service
from app.modules.payroll.schemas import ReportTemplateUpsert, ReportTemplateComponentUpsert, ReportTemplateFieldUpsert


def _make_user(db, email):
    from app.modules.auth.models import User, UserRole
    user = User(email=email, hashed_password="x", role=UserRole.PAYROLL_ADMIN, first_name="Test", last_name="User")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_au_company(db, organization_id):
    from app.modules.payroll.models import CompanyComplianceDetails
    company = CompanyComplianceDetails(
        organization_id=organization_id, name="Acme Australia Pty Ltd", tax_no="51824753556",
        jurisdiction_country="AU", jurisdiction_state="",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _make_au_run_with_payslip(db, organization_id, status="Approved"):
    from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem

    employee = PayrollEmployee(organization_id=organization_id, employee_code="AU-E001", name="Jamie Chen")
    db.add(employee)
    db.commit()
    db.refresh(employee)

    run = PayrollRun(
        organization_id=organization_id, period_label="Aug 2026",
        period_start=date(2026, 8, 1), period_end=date(2026, 8, 31), pay_date=date(2026, 8, 31),
        status=status, total_gross=8000, total_deductions=2000, total_net=6000,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee.id, organization_id=organization_id,
        employee_name="Jamie Chen", basic_salary=8000, gross_pay=8000,
        tds=1600, study_loan_deduction=400, employer_pension=960,
        total_deductions=2000, net_pay=6000,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return run, employee, item


def _build_au_stp_template(db, creator, approver):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey="AU-STP", name="Single Touch Payroll (STP) Pay Event", reportType="STP",
            jurisdictionCountry="AU", reportingYear="2026-27", documentScope="AGGREGATE",
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
    earnings = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="earnings", label="Earnings"), actor_id=creator.id,
    )
    service.upsert_report_field(
        db, earnings.id, ReportTemplateFieldUpsert(
            fieldKey="gross_pay", label="Gross Pay", fieldType="currency",
            dataSourceKind="PAYSLIP_ITEM", sourceColumn="gross_pay",
        ), actor_id=creator.id,
    )
    payg = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="payg", label="PAYG Withholding"), actor_id=creator.id,
    )
    service.upsert_report_field(
        db, payg.id, ReportTemplateFieldUpsert(
            fieldKey="payg_withholding", label="PAYG Withholding", fieldType="currency",
            dataSourceKind="PAYSLIP_ITEM", sourceColumn="tds",
        ), actor_id=creator.id,
    )
    service.upsert_report_field(
        db, payg.id, ReportTemplateFieldUpsert(
            fieldKey="stsl_component", label="STSL Component", fieldType="currency",
            dataSourceKind="PAYSLIP_ITEM", sourceColumn="study_loan_deduction",
        ), actor_id=creator.id,
    )
    superann = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="super", label="Superannuation"), actor_id=creator.id,
    )
    service.upsert_report_field(
        db, superann.id, ReportTemplateFieldUpsert(
            fieldKey="sg_amount", label="Superannuation Guarantee", fieldType="currency",
            dataSourceKind="PAYSLIP_ITEM", sourceColumn="employer_pension",
        ), actor_id=creator.id,
    )
    template = service.set_report_template_approver(db, template.id, actor_id=approver.id)
    assert template.status == "Approved"
    template = service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    template = service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)
    assert template.status == "Active"
    return template


def test_generate_au_stp_report_end_to_end(db, organization):
    """No new generation code exists for AU — this proves the fully
    generic generate_report_from_template engine (already proven for
    CA/IN/UK/US) produces correct AU figures with zero AU-specific
    branching anywhere in that function."""
    creator = _make_user(db, "au-stp-creator@test.com")
    approver = _make_user(db, "au-stp-approver@test.com")
    _make_au_company(db, organization.id)
    run, employee, item = _make_au_run_with_payslip(db, organization.id, status="Approved")
    template = _build_au_stp_template(db, creator, approver)

    generated = service.generate_report_from_template(
        db, organization.id, template.id, run.id, reporting_period=run.period_label, actor_id=creator.id,
    )
    assert generated.status == "Generated"
    assert generated.report_type == "STP"
    assert generated.jurisdiction_country == "AU"

    employees = generated.rendered_data["employees"]
    assert len(employees) == 1
    assert employees[0]["values"]["gross_pay"] == float(item.gross_pay)
    assert employees[0]["values"]["payg_withholding"] == float(item.tds)
    assert employees[0]["values"]["stsl_component"] == float(item.study_loan_deduction)
    assert employees[0]["values"]["sg_amount"] == float(item.employer_pension)
    assert generated.rendered_data["employer"]["employer_name"] == "Acme Australia Pty Ltd"


def test_au_stp_submission_tracking_lifecycle(db, organization):
    """RtiSubmission's widened submission_type set now accepts "STP" —
    same DRAFT->READY->SUBMITTED->ACKNOWLEDGED status-tracker-only
    lifecycle UK's FPS/EPS/P45 already use (never a real ATO
    transmission — see RtiSubmission's own docstring), plus the new
    schema_version column closing AU-AC23."""
    creator = _make_user(db, "au-stp-submit-creator@test.com")
    approver = _make_user(db, "au-stp-submit-approver@test.com")
    _make_au_company(db, organization.id)
    run, employee, item = _make_au_run_with_payslip(db, organization.id, status="Approved")
    template = _build_au_stp_template(db, creator, approver)
    generated = service.generate_report_from_template(
        db, organization.id, template.id, run.id, reporting_period=run.period_label, actor_id=creator.id,
    )

    submission = service.create_rti_submission(
        db, organization.id, generated.id, created_by_id=creator.id, schema_version="NAT-STP-2026-27",
    )
    assert submission.submission_type == "STP"
    assert submission.status == "DRAFT"
    assert submission.schema_version == "NAT-STP-2026-27"

    ready = service.set_rti_submission_status(db, organization.id, submission.id, "READY")
    assert ready.status == "READY"
    submitted = service.set_rti_submission_status(db, organization.id, submission.id, "SUBMITTED")
    assert submitted.status == "SUBMITTED"
    assert submitted.submitted_at is not None


def test_au_stp_appears_in_rti_forms_summary(db, organization):
    """_RTI_FORMS_SUMMARY_REPORT_TYPES's widened set gives Super Admin
    cross-org visibility into AU STP generation, the same way India's
    Form 130/138/123 were widened in 2026-09-10 — no schema change."""
    creator = _make_user(db, "au-stp-summary-creator@test.com")
    approver = _make_user(db, "au-stp-summary-approver@test.com")
    _make_au_company(db, organization.id)
    run, employee, item = _make_au_run_with_payslip(db, organization.id, status="Approved")
    template = _build_au_stp_template(db, creator, approver)
    service.generate_report_from_template(
        db, organization.id, template.id, run.id, reporting_period=run.period_label, actor_id=creator.id,
    )

    summary = service.get_rti_forms_summary(db, organization.id)
    assert any(row["reportType"] == "STP" for row in summary)
