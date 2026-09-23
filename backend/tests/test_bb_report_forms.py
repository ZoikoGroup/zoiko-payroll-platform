"""
tests/test_bb_report_forms.py
------------------------------
Barbados's real named statutory forms (Caribbean forms gap-closure,
country #4, 2026-09-23): TAMIS Monthly PAYE return + NIS Earnings
Schedule — both bespoke, per-employee-row cross-run aggregations (same
shape as Guyana's Form 5/Trinidad's Monthly Return/Jamaica's S01).
"""
from datetime import date

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import service
from app.modules.payroll.schemas import (
    ReportTemplateUpsert, ReportTemplateComponentUpsert, ReportTemplateFieldUpsert,
)

from tests.test_report_templates import _make_user, _make_company, _build_template


def _make_bb_employee(db, organization_id, code, name="BB Employee", **overrides):
    from app.modules.payroll.models import PayrollEmployee

    fields = dict(compliance_fields={"tamis_tin": "123456789", "nis_number": "NIS-001"})
    fields.update(overrides)
    employee = PayrollEmployee(organization_id=organization_id, employee_code=code, name=name, **fields)
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


def _make_bb_run_with_payslip(db, organization_id, employee_id, pay_date, *, status="Approved", employee_name="BB Employee", **overrides):
    from app.modules.payroll.models import PayrollRun, PayslipItem

    run = PayrollRun(
        organization_id=organization_id, period_label=str(pay_date),
        period_start=pay_date.replace(day=1), period_end=pay_date, pay_date=pay_date,
        status=status,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    fields = dict(gross_pay=100000, basic_salary=90000, tds=15000, social_security=3000, employer_social_security=3000, employee_pension=1000, employer_pension=1500, total_deductions=22000, net_pay=78000)
    fields.update(overrides)
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee_id, organization_id=organization_id,
        employee_name=employee_name, country_code="BB", **fields,
    )
    db.add(item)
    db.commit()
    return run, item


def _build_bb_tamis_template(db, creator, approver, key="BB-TAMIS-MONTHLY-PAYE-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="TAMIS Monthly PAYE Return", reportType="BB_TAMIS_MONTHLY_PAYE",
            jurisdictionCountry="BB", reportingYear="2026", documentScope="AGGREGATE",
        ), actor_id=creator.id,
    )
    employer_info = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="employer_info", label="Employer Information"),
        actor_id=creator.id,
    )
    for field_key, label, source_column in (
        ("employer_name", "Employer Name", "name"),
        ("employer_tamis_tin", "TAMIS TIN", "tax_no"),
    ):
        service.upsert_report_field(
            db, employer_info.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=label, fieldType="text",
                dataSourceKind="EMPLOYER_PROFILE", sourceColumn=source_column,
            ), actor_id=creator.id,
        )
    totals = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="totals", label="Employer Totals (PAYE / NIS / R&R Levy)"),
        actor_id=creator.id,
    )
    for field_key, source_column in (
        ("total_employee_count", "gross_pay"),
        ("total_remuneration", "gross_pay"),
        ("total_paye_tax_deducted", "tds"),
        ("total_nis_employee", "social_security"),
        ("total_nis_employer", "employer_social_security"),
        ("total_rr_levy_employee", "employee_pension"),
        ("total_rr_levy_employer", "employer_pension"),
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


def _build_bb_nis_schedule_template(db, creator, approver, key="BB-NIS-EARNINGS-SCHEDULE-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="NIS Earnings Schedule", reportType="BB_NIS_EARNINGS_SCHEDULE",
            jurisdictionCountry="BB", reportingYear="2026", documentScope="AGGREGATE",
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


# ── TAMIS Monthly PAYE return ─────────────────────────────────────────

def test_generate_bb_tamis_monthly_paye_aggregates_two_employees_across_multiple_runs_same_month(db, organization):
    creator = _make_user(db, "creator_bbtamisa@test.com")
    approver = _make_user(db, "approver_bbtamisa@test.com")
    _make_company(db, organization.id, country="BB")
    emp1 = _make_bb_employee(db, organization.id, code="BBTAMISA1", name="Shonda Griffith")
    emp2 = _make_bb_employee(db, organization.id, code="BBTAMISA2", name="Dario Forde")

    _make_bb_run_with_payslip(db, organization.id, emp1.id, date(2026, 7, 7), gross_pay=50000, tds=7000, social_security=1500, employer_social_security=1500, employee_pension=500, employer_pension=750, employee_name="Shonda Griffith")
    _make_bb_run_with_payslip(db, organization.id, emp1.id, date(2026, 7, 14), gross_pay=50000, tds=7000, social_security=1500, employer_social_security=1500, employee_pension=500, employer_pension=750, employee_name="Shonda Griffith")
    _make_bb_run_with_payslip(db, organization.id, emp2.id, date(2026, 7, 21), gross_pay=120000, tds=18000, social_security=3600, employer_social_security=3600, employee_pension=1200, employer_pension=1800, employee_name="Dario Forde")

    template = _build_bb_tamis_template(db, creator, approver)
    generated = service.generate_bb_tamis_monthly_paye(db, organization.id, template.id, 2026, 7, actor_id=creator.id)

    assert generated.report_type == "BB_TAMIS_MONTHLY_PAYE"
    assert generated.scope_key == "PERIOD:2026-07-01:2026-07-31"
    totals = generated.rendered_data["employerTotals"]
    assert totals["total_employee_count"] == 2
    assert totals["total_remuneration"] == 220000.0
    assert totals["total_paye_tax_deducted"] == 32000.0

    rows = {r["employeeName"]: r for r in generated.rendered_data["employeeRows"]}
    assert rows["Shonda Griffith"]["totalRemuneration"] == 100000.0  # 2 runs summed into ONE row
    assert rows["Shonda Griffith"]["tamisTin"] == "123456789"
    assert rows["Dario Forde"]["totalRemuneration"] == 120000.0


def test_generate_bb_tamis_monthly_paye_excludes_other_months_and_unfinalized_runs(db, organization):
    creator = _make_user(db, "creator_bbtamisb@test.com")
    approver = _make_user(db, "approver_bbtamisb@test.com")
    _make_company(db, organization.id, country="BB")
    employee = _make_bb_employee(db, organization.id, code="BBTAMISB")

    _make_bb_run_with_payslip(db, organization.id, employee.id, date(2026, 7, 10), gross_pay=60000)
    _make_bb_run_with_payslip(db, organization.id, employee.id, date(2026, 8, 5), gross_pay=99999)
    _make_bb_run_with_payslip(db, organization.id, employee.id, date(2026, 7, 20), gross_pay=99999, status="Draft")

    template = _build_bb_tamis_template(db, creator, approver, key="BB-TAMIS-EXCLUDE-TEST")
    generated = service.generate_bb_tamis_monthly_paye(db, organization.id, template.id, 2026, 7, actor_id=creator.id)
    assert generated.rendered_data["employerTotals"]["total_remuneration"] == 60000.0
    assert len(generated.rendered_data["employeeRows"]) == 1


def test_generate_bb_tamis_monthly_paye_rejects_wrong_report_type(db, organization):
    creator = _make_user(db, "creator_bbtamisc@test.com")
    approver = _make_user(db, "approver_bbtamisc@test.com")
    _make_company(db, organization.id, country="BB")
    template = _build_template(db, creator, approver, country="BB", version="bbtamis-neg")
    with pytest.raises(BadRequestException):
        service.generate_bb_tamis_monthly_paye(db, organization.id, template.id, 2026, 7)


def test_generate_bb_tamis_monthly_paye_regenerating_supersedes_prior(db, organization):
    creator = _make_user(db, "creator_bbtamisd@test.com")
    approver = _make_user(db, "approver_bbtamisd@test.com")
    _make_company(db, organization.id, country="BB")
    employee = _make_bb_employee(db, organization.id, code="BBTAMISD")
    _make_bb_run_with_payslip(db, organization.id, employee.id, date(2026, 7, 10))

    template = _build_bb_tamis_template(db, creator, approver, key="BB-TAMIS-SUPERSEDE-TEST")
    first = service.generate_bb_tamis_monthly_paye(db, organization.id, template.id, 2026, 7, actor_id=creator.id)
    second = service.generate_bb_tamis_monthly_paye(db, organization.id, template.id, 2026, 7, actor_id=creator.id)
    db.refresh(first)
    assert first.status == "Superseded"
    assert second.status == "Generated"


# ── NIS Earnings Schedule ─────────────────────────────────────────────

def test_generate_bb_nis_earnings_schedule_buckets_weeks_and_aggregates_employees(db, organization):
    creator = _make_user(db, "creator_bbnis_a@test.com")
    approver = _make_user(db, "approver_bbnis_a@test.com")
    _make_company(db, organization.id, country="BB")
    emp1 = _make_bb_employee(db, organization.id, code="BBNISA1", name="Shonda Griffith", compliance_fields={"nis_number": "NIS-100"})

    _make_bb_run_with_payslip(db, organization.id, emp1.id, date(2026, 9, 5), gross_pay=25000, social_security=1400, employer_social_security=2100, employee_name="Shonda Griffith")
    _make_bb_run_with_payslip(db, organization.id, emp1.id, date(2026, 9, 12), gross_pay=25000, social_security=1400, employer_social_security=2100, employee_name="Shonda Griffith")

    template = _build_bb_nis_schedule_template(db, creator, approver)
    generated = service.generate_bb_nis_earnings_schedule(db, organization.id, template.id, 2026, 9, actor_id=creator.id)

    assert generated.report_type == "BB_NIS_EARNINGS_SCHEDULE"
    totals = generated.rendered_data["employerTotals"]
    assert totals["total_insurable_earnings"] == 50000.0
    assert totals["total_nis_employee"] == 2800.0
    assert totals["total_nis_employer"] == 4200.0

    row = generated.rendered_data["employeeRows"][0]
    assert row["nisNumber"] == "NIS-100"
    assert row["roundedEarnings"] == 50000
    assert "week1" in row["weeks"]
    assert "week2" in row["weeks"]
    assert row["weeks"]["week1"]["earnings"] == 25000.0
    assert row["weeks"]["week2"]["earnings"] == 25000.0


def test_generate_bb_nis_earnings_schedule_rejects_wrong_report_type(db, organization):
    creator = _make_user(db, "creator_bbnis_b@test.com")
    approver = _make_user(db, "approver_bbnis_b@test.com")
    _make_company(db, organization.id, country="BB")
    template = _build_template(db, creator, approver, country="BB", version="bbnis-neg")
    with pytest.raises(BadRequestException):
        service.generate_bb_nis_earnings_schedule(db, organization.id, template.id, 2026, 9)
