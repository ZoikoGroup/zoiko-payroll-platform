"""
tests/test_au_state_payroll_tax_return.py
---------------------------------------------
Phase 9 (Forms & Reports, ZP-TAX-AU-2026-27-001 §15-18, 2026-09-17) —
proves service.generate_au_state_payroll_tax_return, a bespoke,
cross-run generator (same reasoning as generate_india_form_138's own
quarter-summing) that sums each finalized PayslipItem's own
employer_payroll_tax (already the correct INCREMENTAL period liability,
per calculate_au_state_payroll_tax's telescope_period_amount) across a
reporting period spanning multiple pay runs, scoped to one state.
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


def _make_au_run_with_payslip(db, organization_id, *, period_label, period_start, period_end, pay_date,
                               employer_payroll_tax, work_state="NSW", status="Approved", employee_code="AU-STATE-E1"):
    from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem

    employee = db.query(PayrollEmployee).filter(
        PayrollEmployee.organization_id == organization_id, PayrollEmployee.employee_code == employee_code,
    ).first()
    if not employee:
        employee = PayrollEmployee(organization_id=organization_id, employee_code=employee_code, name="State Tax Employee")
        db.add(employee)
        db.commit()
        db.refresh(employee)

    run = PayrollRun(
        organization_id=organization_id, period_label=period_label,
        period_start=period_start, period_end=period_end, pay_date=pay_date,
        status=status, total_gross=100000, total_deductions=20000, total_net=80000,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee.id, organization_id=organization_id,
        employee_name="State Tax Employee", basic_salary=100000, gross_pay=100000,
        work_state=work_state, employer_payroll_tax=employer_payroll_tax,
        total_deductions=20000, net_pay=80000,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return run, employee, item


def _build_au_nsw_template(db, creator, approver):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey="AU-PAYROLL-TAX-NSW", name="New South Wales Payroll Tax Return", reportType="AU_PAYROLL_TAX_RETURN",
            jurisdictionCountry="AU", jurisdictionState="NSW", reportingYear="2026-27", documentScope="AGGREGATE",
        ), actor_id=creator.id,
    )
    template = service.set_report_template_approver(db, template.id, actor_id=approver.id)
    template = service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    template = service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)
    assert template.status == "Active"
    return template


def test_generate_au_state_payroll_tax_return_sums_across_multiple_runs(db, organization):
    """A quarter spans 3 monthly runs — the return must sum every
    finalized run's own employer_payroll_tax within the date range, not
    just the single most-recent run (the same cross-run requirement
    generate_india_form_138 already proves for a different jurisdiction)."""
    creator = _make_user(db, "au-state-tax-creator@test.com")
    approver = _make_user(db, "au-state-tax-approver@test.com")
    _make_au_company(db, organization.id)
    _make_au_run_with_payslip(
        db, organization.id, period_label="Jul 2026", period_start=date(2026, 7, 1), period_end=date(2026, 7, 31),
        pay_date=date(2026, 7, 31), employer_payroll_tax=1000,
    )
    _make_au_run_with_payslip(
        db, organization.id, period_label="Aug 2026", period_start=date(2026, 8, 1), period_end=date(2026, 8, 31),
        pay_date=date(2026, 8, 31), employer_payroll_tax=1200,
    )
    _make_au_run_with_payslip(
        db, organization.id, period_label="Sep 2026", period_start=date(2026, 9, 1), period_end=date(2026, 9, 30),
        pay_date=date(2026, 9, 30), employer_payroll_tax=1500,
    )
    template = _build_au_nsw_template(db, creator, approver)

    generated = service.generate_au_state_payroll_tax_return(
        db, organization.id, template.id, "NSW", date(2026, 7, 1), date(2026, 9, 30), actor_id=creator.id,
    )
    assert generated.status == "Generated"
    assert generated.jurisdiction_state == "NSW"
    assert generated.rendered_data["totals"]["total_employer_payroll_tax"] == 3700.0
    assert generated.rendered_data["totals"]["payslip_count"] == 3


def test_generate_au_state_payroll_tax_return_excludes_other_states(db, organization):
    creator = _make_user(db, "au-state-tax-other-creator@test.com")
    approver = _make_user(db, "au-state-tax-other-approver@test.com")
    _make_au_company(db, organization.id)
    _make_au_run_with_payslip(
        db, organization.id, period_label="Jul 2026", period_start=date(2026, 7, 1), period_end=date(2026, 7, 31),
        pay_date=date(2026, 7, 31), employer_payroll_tax=1000, work_state="NSW", employee_code="AU-STATE-NSW",
    )
    _make_au_run_with_payslip(
        db, organization.id, period_label="Jul 2026 VIC", period_start=date(2026, 7, 1), period_end=date(2026, 7, 31),
        pay_date=date(2026, 7, 31), employer_payroll_tax=5000, work_state="VIC", employee_code="AU-STATE-VIC",
    )
    template = _build_au_nsw_template(db, creator, approver)

    generated = service.generate_au_state_payroll_tax_return(
        db, organization.id, template.id, "NSW", date(2026, 7, 1), date(2026, 7, 31), actor_id=creator.id,
    )
    assert generated.rendered_data["totals"]["total_employer_payroll_tax"] == 1000.0
    assert generated.rendered_data["totals"]["payslip_count"] == 1


def test_generate_au_state_payroll_tax_return_rejects_mismatched_state(db, organization):
    creator = _make_user(db, "au-state-tax-mismatch-creator@test.com")
    approver = _make_user(db, "au-state-tax-mismatch-approver@test.com")
    _make_au_company(db, organization.id)
    _make_au_run_with_payslip(
        db, organization.id, period_label="Jul 2026", period_start=date(2026, 7, 1), period_end=date(2026, 7, 31),
        pay_date=date(2026, 7, 31), employer_payroll_tax=1000,
    )
    template = _build_au_nsw_template(db, creator, approver)
    try:
        service.generate_au_state_payroll_tax_return(
            db, organization.id, template.id, "VIC", date(2026, 7, 1), date(2026, 7, 31), actor_id=creator.id,
        )
        assert False, "expected BadRequestException"
    except BadRequestException:
        pass
