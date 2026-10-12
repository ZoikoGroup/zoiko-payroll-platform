"""
tests/test_au_superstream_report.py
--------------------------------------
Phase 9 (Forms & Reports, ZP-TAX-AU-2026-27-001 §12, 2026-09-17) — proves
service.generate_au_superstream_report, a BESPOKE generator (same
reasoning as generate_uk_eps) reading SuperGuaranteeLiability directly,
since that table's fund_receipt_deadline/status/submitted_at/received_at
fields have no data_source_kind in the generic generate_report_from_
template engine. Uses the seeded "AU-SUPERSTREAM" ReportTemplate shape
(scripts/seed_statutory_report_templates.py) reproduced inline.
"""
from datetime import date

from app.core.exceptions import BadRequestException
from app.modules.payroll import service
from app.modules.payroll.schemas import ReportTemplateUpsert


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


def _make_au_run_with_sg_liability(db, organization_id, status="Approved"):
    from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem

    employee = PayrollEmployee(organization_id=organization_id, employee_code="AU-E002", name="Priya Nair")
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
        employee_name="Priya Nair", basic_salary=8000, gross_pay=8000,
        tds=1600, employer_pension=960, total_deductions=2000, net_pay=6000,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    liability = service.create_au_sg_liability(
        db, organization_id, employee.id, run.pay_date, qualifying_earnings=8000, sg_rate_pct=12,
        sg_amount=960, ytd_qualifying_earnings_after=8000, mcb_reached=False, payslip_item_id=item.id,
    )
    db.commit()
    return run, employee, item, liability


def _build_au_superstream_template(db, creator, approver):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey="AU-SUPERSTREAM", name="SuperStream Contribution Message", reportType="SUPERSTREAM",
            jurisdictionCountry="AU", reportingYear="2026-27", documentScope="AGGREGATE",
        ), actor_id=creator.id,
    )
    template = service.set_report_template_approver(db, template.id, actor_id=approver.id)
    assert template.status == "Approved"
    template = service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    template = service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)
    assert template.status == "Active"
    return template


def test_generate_au_superstream_report_end_to_end(db, organization):
    creator = _make_user(db, "au-superstream-creator@test.com")
    approver = _make_user(db, "au-superstream-approver@test.com")
    _make_au_company(db, organization.id)
    run, employee, item, liability = _make_au_run_with_sg_liability(db, organization.id, status="Approved")
    template = _build_au_superstream_template(db, creator, approver)

    generated = service.generate_au_superstream_report(db, organization.id, template.id, run.id, actor_id=creator.id)
    assert generated.status == "Generated"
    assert generated.report_type == "SUPERSTREAM"
    assert generated.jurisdiction_country == "AU"

    employees = generated.rendered_data["employees"]
    assert len(employees) == 1
    assert employees[0]["employeeId"] == employee.id
    assert employees[0]["employeeName"] == "Priya Nair"
    assert employees[0]["values"]["sg_amount"] == 960.0
    assert employees[0]["values"]["qualifying_earnings"] == 8000.0
    assert employees[0]["values"]["status"] == "PENDING"
    assert employees[0]["values"]["fund_receipt_deadline"] is not None
    assert generated.rendered_data["totals"]["total_sg_amount"] == 960.0
    assert generated.rendered_data["totals"]["contribution_count"] == 1
    assert generated.rendered_data["employer"]["employer_name"] == "Acme Australia Pty Ltd"


def test_generate_au_superstream_report_empty_when_no_liabilities(db, organization):
    """A run with no SuperGuaranteeLiability rows yet (SG Phase 2 not
    wired for this org) produces an empty employees list rather than
    raising — matches every other report generator's "nothing to
    report" handling."""
    from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem

    creator = _make_user(db, "au-superstream-empty-creator@test.com")
    approver = _make_user(db, "au-superstream-empty-approver@test.com")
    _make_au_company(db, organization.id)
    employee = PayrollEmployee(organization_id=organization.id, employee_code="AU-E003", name="No SG Employee")
    db.add(employee)
    db.commit()
    db.refresh(employee)
    run = PayrollRun(
        organization_id=organization.id, period_label="Sep 2026",
        period_start=date(2026, 9, 1), period_end=date(2026, 9, 30), pay_date=date(2026, 9, 30),
        status="Approved", total_gross=5000, total_deductions=1000, total_net=4000,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee.id, organization_id=organization.id,
        employee_name="No SG Employee", basic_salary=5000, gross_pay=5000,
        tds=1000, total_deductions=1000, net_pay=4000,
    )
    db.add(item)
    db.commit()

    template = _build_au_superstream_template(db, creator, approver)
    generated = service.generate_au_superstream_report(db, organization.id, template.id, run.id, actor_id=creator.id)
    assert generated.rendered_data["employees"] == []
    assert generated.rendered_data["totals"]["total_sg_amount"] == 0.0


def test_generate_au_superstream_report_rejects_wrong_report_type(db, organization):
    creator = _make_user(db, "au-superstream-wrongtype-creator@test.com")
    approver = _make_user(db, "au-superstream-wrongtype-approver@test.com")
    _make_au_company(db, organization.id)
    run, employee, item, liability = _make_au_run_with_sg_liability(db, organization.id, status="Approved")

    wrong_template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey="AU-STP-WRONGTYPE", name="Single Touch Payroll", reportType="STP",
            jurisdictionCountry="AU", reportingYear="2026-27", documentScope="AGGREGATE",
        ), actor_id=creator.id,
    )
    try:
        service.generate_au_superstream_report(db, organization.id, wrong_template.id, run.id, actor_id=creator.id)
        assert False, "expected BadRequestException"
    except BadRequestException:
        pass
