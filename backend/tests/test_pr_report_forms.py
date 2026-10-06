"""
tests/test_pr_report_forms.py
------------------------------
Puerto Rico's real named statutory forms (ZP-PR-ENG-001 §10):
Form 499 R-1B (quarterly local withholding), federal Form 941 (FICA on
PR wages), and federal Form 940 (FUTA-equivalent) — all independent from
their US counterparts (generate_us_941/generate_us_940), filtering only
on PayslipItem.country_code == "PR".
"""
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import service
from app.modules.payroll.models import ContributionRate, JurisdictionPack, PayrollEmployee, PayrollRun, PayslipItem
from app.modules.payroll.schemas import (
    ReportTemplateUpsert, ReportTemplateComponentUpsert, ReportTemplateFieldUpsert,
)

from tests.test_report_templates import _make_user, _make_company, _build_template


def _make_pr_employee(db, organization_id, code, name="PR Employee"):
    employee = PayrollEmployee(organization_id=organization_id, employee_code=code, name=name)
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


def _make_pr_run_with_payslip(db, organization_id, employee_id, pay_date, *, status="Approved", employee_name="PR Employee", **overrides):
    run = PayrollRun(
        organization_id=organization_id, period_label=str(pay_date),
        period_start=pay_date.replace(day=1), period_end=pay_date, pay_date=pay_date,
        status=status,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    fields = dict(
        gross_pay=Decimal("4000"), tds=Decimal("348.33"),
        social_security=Decimal("248.00"), employer_social_security=Decimal("248.00"),
        medicare=Decimal("58.00"), employer_medicare=Decimal("58.00"),
        employer_futa=Decimal("240.00"),
        total_deductions=Decimal("654.33"), net_pay=Decimal("3345.67"),
    )
    fields.update(overrides)
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee_id, organization_id=organization_id,
        employee_name=employee_name, country_code="PR", **fields,
    )
    db.add(item)
    db.commit()
    return run, item


def _make_pr_ss_canonical_rate(db):
    """generate_pr_941 derives SS wages back out of SS tax via the
    canonical pr_ss employee rate — needs a real canonical ContributionRate
    row to resolve against (same as generate_us_941's own dependency)."""
    pack = JurisdictionPack(pack_id="PR-PAYROLL-TEST-V1", jurisdiction_country="PR", version="1.0", pack_type="tax", status="Active")
    db.add(pack)
    db.commit()
    db.refresh(pack)
    rate = ContributionRate(
        jurisdiction_pack_id=pack.id, jurisdiction_country="PR", organization_id=None,
        component_key="pr_ss", label="Social Security",
        employee_rate_pct=Decimal("0.0620"), employer_rate_pct=Decimal("0.0620"),
        employee_share="6.2%", employer_share="6.2%", total="12.4%",
    )
    db.add(rate)
    db.commit()


def _build_pr_499r1b_template(db, creator, approver, key="PR-499R1B-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="Form 499 R-1B", reportType="PR_499R1B",
            jurisdictionCountry="PR", reportingYear="2026", documentScope="AGGREGATE",
        ), actor_id=creator.id,
    )
    employer_info = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="employer_info", label="Employer Information"), actor_id=creator.id,
    )
    for field_key, label, source_column in (
        ("employer_name", "Employer Name", "name"),
        ("employer_hacienda_ein", "Hacienda EIN", "tax_no"),
        ("employee_count", "Employee Count", "gross_pay"),
    ):
        kind = "EMPLOYER_PROFILE" if field_key != "employee_count" else "PAYSLIP_ITEM"
        service.upsert_report_field(
            db, employer_info.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=label, fieldType="text", dataSourceKind=kind, sourceColumn=source_column,
            ), actor_id=creator.id,
        )
    withholding = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="withholding", label="Wages & Withholding"), actor_id=creator.id,
    )
    for field_key, source_column in (("total_wages", "gross_pay"), ("total_pr_withholding", "tds")):
        service.upsert_report_field(
            db, withholding.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=field_key, fieldType="currency",
                dataSourceKind="PAYSLIP_ITEM", sourceColumn=source_column,
            ), actor_id=creator.id,
        )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)
    return template


def _build_pr_941_template(db, creator, approver, key="PR-941-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="Form 941 (Puerto Rico)", reportType="PR_941",
            jurisdictionCountry="PR", reportingYear="2026", documentScope="AGGREGATE",
        ), actor_id=creator.id,
    )
    component = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="totals", label="Totals"), actor_id=creator.id,
    )
    for field_key, source_column in (
        ("line2_wages", "gross_pay"),
        ("line5a_ss_wages", "social_security"),
        ("line5a_ss_tax", "social_security"),
        ("line5c_medicare_wages", "gross_pay"),
        ("line5c_medicare_tax", "medicare"),
    ):
        service.upsert_report_field(
            db, component.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=field_key, fieldType="currency",
                dataSourceKind="PAYSLIP_ITEM", sourceColumn=source_column,
            ), actor_id=creator.id,
        )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)
    return template


def _build_pr_940_template(db, creator, approver, key="PR-940-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="Form 940 (Puerto Rico)", reportType="PR_940",
            jurisdictionCountry="PR", reportingYear="2026", documentScope="AGGREGATE",
        ), actor_id=creator.id,
    )
    component = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="futa", label="FUTA-equivalent"), actor_id=creator.id,
    )
    for field_key, source_column in (
        ("total_payments", "gross_pay"),
        ("futa_taxable_wages", "employer_futa"),
        ("futa_tax_due", "employer_futa"),
    ):
        service.upsert_report_field(
            db, component.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=field_key, fieldType="currency",
                dataSourceKind="PAYSLIP_ITEM", sourceColumn=source_column,
            ), actor_id=creator.id,
        )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)
    return template


# ── Form 499 R-1B ─────────────────────────────────────────────────────

def test_generate_pr_499r1b_aggregates_two_employees_in_the_quarter(db, organization):
    creator = _make_user(db, "creator_pr499a@test.com")
    approver = _make_user(db, "approver_pr499a@test.com")
    _make_company(db, organization.id, country="PR")
    emp1 = _make_pr_employee(db, organization.id, code="PR499A1", name="Maria Rivera")
    emp2 = _make_pr_employee(db, organization.id, code="PR499A2", name="Jose Ortiz")

    _make_pr_run_with_payslip(db, organization.id, emp1.id, date(2026, 2, 15), gross_pay=Decimal("4000"), tds=Decimal("348.33"), employee_name="Maria Rivera")
    _make_pr_run_with_payslip(db, organization.id, emp2.id, date(2026, 3, 15), gross_pay=Decimal("6000"), tds=Decimal("650.00"), employee_name="Jose Ortiz")
    # Outside Q1 — must NOT be summed in.
    _make_pr_run_with_payslip(db, organization.id, emp1.id, date(2026, 4, 15), gross_pay=Decimal("9999"), tds=Decimal("9999"), employee_name="Maria Rivera")

    template = _build_pr_499r1b_template(db, creator, approver)
    generated = service.generate_pr_499r1b(db, organization.id, template.id, 2026, 1, actor_id=creator.id)

    assert generated.report_type == "PR_499R1B"
    assert generated.reporting_period == "Q1"
    assert generated.rendered_data["employeeCount"] == 2
    assert generated.rendered_data["employer"]["total_wages"] == 10000.0
    assert generated.rendered_data["employer"]["total_pr_withholding"] == 998.33
    assert generated.rendered_data["dueDate"] == "2026-04-30"


def test_generate_pr_499r1b_rejects_wrong_report_type(db, organization):
    creator = _make_user(db, "creator_pr499b@test.com")
    approver = _make_user(db, "approver_pr499b@test.com")
    _make_company(db, organization.id, country="PR")
    template = _build_template(db, creator, approver, country="PR", version="pr499-neg")  # TDS, not PR_499R1B
    with pytest.raises(BadRequestException):
        service.generate_pr_499r1b(db, organization.id, template.id, 2026, 1)


def test_generate_pr_499r1b_regenerating_supersedes_prior(db, organization):
    creator = _make_user(db, "creator_pr499c@test.com")
    approver = _make_user(db, "approver_pr499c@test.com")
    _make_company(db, organization.id, country="PR")
    employee = _make_pr_employee(db, organization.id, code="PR499C")
    _make_pr_run_with_payslip(db, organization.id, employee.id, date(2026, 2, 10))

    template = _build_pr_499r1b_template(db, creator, approver, key="PR-499R1B-SUPERSEDE-TEST")
    first = service.generate_pr_499r1b(db, organization.id, template.id, 2026, 1, actor_id=creator.id)
    second = service.generate_pr_499r1b(db, organization.id, template.id, 2026, 1, actor_id=creator.id)
    db.refresh(first)
    assert first.status == "Superseded"
    assert second.status == "Generated"


def test_generate_pr_499r1b_never_touches_a_us_payslip(db, organization):
    """A US-country-code payslip in the same org/period must never be
    swept into a PR filing — the whole point of never reusing the US
    filter/generator."""
    creator = _make_user(db, "creator_pr499d@test.com")
    approver = _make_user(db, "approver_pr499d@test.com")
    _make_company(db, organization.id, country="PR")
    pr_employee = _make_pr_employee(db, organization.id, code="PR499D1", name="Maria Rivera")
    us_employee = PayrollEmployee(organization_id=organization.id, employee_code="PR499D-US", name="John Smith")
    db.add(us_employee)
    db.commit()
    db.refresh(us_employee)

    _make_pr_run_with_payslip(db, organization.id, pr_employee.id, date(2026, 2, 10), gross_pay=Decimal("4000"), tds=Decimal("348.33"))
    run = PayrollRun(
        organization_id=organization.id, period_label="2026-02-10", period_start=date(2026, 2, 1),
        period_end=date(2026, 2, 10), pay_date=date(2026, 2, 10), status="Approved",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    db.add(PayslipItem(
        payroll_run_id=run.id, employee_id=us_employee.id, organization_id=organization.id,
        employee_name="John Smith", country_code="US",
        gross_pay=Decimal("99999"), tds=Decimal("99999"), total_deductions=Decimal("0"), net_pay=Decimal("0"),
    ))
    db.commit()

    template = _build_pr_499r1b_template(db, creator, approver, key="PR-499R1B-ISOLATION-TEST")
    generated = service.generate_pr_499r1b(db, organization.id, template.id, 2026, 1, actor_id=creator.id)
    assert generated.rendered_data["employeeCount"] == 1
    assert generated.rendered_data["employer"]["total_wages"] == 4000.0


# ── Federal Form 941 ──────────────────────────────────────────────────

def test_generate_pr_941_computes_ss_wages_from_canonical_rate(db, organization):
    creator = _make_user(db, "creator_pr941a@test.com")
    approver = _make_user(db, "approver_pr941a@test.com")
    _make_company(db, organization.id, country="PR")
    _make_pr_ss_canonical_rate(db)
    employee = _make_pr_employee(db, organization.id, code="PR941A")
    _make_pr_run_with_payslip(
        db, organization.id, employee.id, date(2026, 2, 15),
        gross_pay=Decimal("4000"), social_security=Decimal("248.00"), employer_social_security=Decimal("248.00"),
        medicare=Decimal("58.00"), employer_medicare=Decimal("58.00"),
    )

    template = _build_pr_941_template(db, creator, approver)
    generated = service.generate_pr_941(db, organization.id, template.id, 2026, 1, actor_id=creator.id)

    assert generated.report_type == "PR_941"
    values = generated.rendered_data["employer"]
    assert values["line5a_ss_wages"] == 4000.0  # 248/0.062 == 4000 employee-side, and employer matches -> ss_wages derived from EMPLOYEE tax only, still 4000
    assert values["line5a_ss_tax"] == 496.0   # 248 + 248 (both shares)
    assert values["line5c_medicare_tax"] == 116.0  # 58 + 58


def test_generate_pr_941_rejects_wrong_report_type(db, organization):
    creator = _make_user(db, "creator_pr941b@test.com")
    approver = _make_user(db, "approver_pr941b@test.com")
    _make_company(db, organization.id, country="PR")
    template = _build_template(db, creator, approver, country="PR", version="pr941-neg")
    with pytest.raises(BadRequestException):
        service.generate_pr_941(db, organization.id, template.id, 2026, 1)


# ── Federal Form 940 (FUTA-equivalent) ───────────────────────────────

def test_generate_pr_940_caps_futa_wages_per_employee(db, organization):
    creator = _make_user(db, "creator_pr940a@test.com")
    approver = _make_user(db, "approver_pr940a@test.com")
    _make_company(db, organization.id, country="PR")
    employee = _make_pr_employee(db, organization.id, code="PR940A")
    # Two runs in the same year for the same employee — gross sums to
    # $10,000, above the $7,000 FUTA-equivalent wage base.
    _make_pr_run_with_payslip(db, organization.id, employee.id, date(2026, 1, 15), gross_pay=Decimal("5000"), employer_futa=Decimal("300.00"))
    _make_pr_run_with_payslip(db, organization.id, employee.id, date(2026, 2, 15), gross_pay=Decimal("5000"), employer_futa=Decimal("120.00"))

    template = _build_pr_940_template(db, creator, approver)
    generated = service.generate_pr_940(db, organization.id, template.id, 2026, actor_id=creator.id)

    assert generated.report_type == "PR_940"
    values = generated.rendered_data["employer"]
    assert values["total_payments"] == 10000.0
    assert values["futa_taxable_wages"] == 7000.0  # capped, not the raw 10,000
    assert values["futa_tax_due"] == 420.0  # 300 + 120, whatever the engine actually withheld


def test_generate_pr_940_rejects_wrong_report_type(db, organization):
    creator = _make_user(db, "creator_pr940b@test.com")
    approver = _make_user(db, "approver_pr940b@test.com")
    _make_company(db, organization.id, country="PR")
    template = _build_template(db, creator, approver, country="PR", version="pr940-neg")
    with pytest.raises(BadRequestException):
        service.generate_pr_940(db, organization.id, template.id, 2026)


def _build_pr_w2pr_template(db, creator, approver, key="PR-W2PR-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="Form 499R-2/W-2PR", reportType="PR_W2PR",
            jurisdictionCountry="PR", reportingYear="2026", documentScope="PER_EMPLOYEE",
        ), actor_id=creator.id,
    )
    employer_info = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="employer_info", label="Employer Information"), actor_id=creator.id,
    )
    for field_key, source_column in (("employer_name", "name"), ("employer_hacienda_ein", "tax_no")):
        service.upsert_report_field(
            db, employer_info.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=field_key, fieldType="text",
                dataSourceKind="EMPLOYER_PROFILE", sourceColumn=source_column,
            ), actor_id=creator.id,
        )
    employee_info = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="employee_info", label="Employee Information"), actor_id=creator.id,
    )
    service.upsert_report_field(
        db, employee_info.id, ReportTemplateFieldUpsert(
            fieldKey="employee_name", label="Employee Name", fieldType="text",
            dataSourceKind="PAYROLL_EMPLOYEE", sourceColumn="name",
        ), actor_id=creator.id,
    )
    box_wages = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="box_wages", label="Wages & PR Tax Withheld"), actor_id=creator.id,
    )
    for field_key, source_column in (("box_wages", "gross_pay"), ("box_pr_tax_withheld", "tds")):
        service.upsert_report_field(
            db, box_wages.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=field_key, fieldType="currency",
                dataSourceKind="PAYSLIP_ITEM", sourceColumn=source_column, aggregation="SUM_YTD",
            ), actor_id=creator.id,
        )
    box_ss_medicare = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="box_ss_medicare", label="Social Security & Medicare"), actor_id=creator.id,
    )
    for field_key, source_column in (
        ("box_ss_wages", "social_security"), ("box_ss_tax", "social_security"),
        ("box_medicare_wages", "gross_pay"), ("box_medicare_tax", "medicare"),
    ):
        service.upsert_report_field(
            db, box_ss_medicare.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=field_key, fieldType="currency",
                dataSourceKind="PAYSLIP_ITEM", sourceColumn=source_column, aggregation="SUM_YTD",
            ), actor_id=creator.id,
        )
    box_sinot = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="box_sinot", label="SINOT"), actor_id=creator.id,
    )
    service.upsert_report_field(
        db, box_sinot.id, ReportTemplateFieldUpsert(
            fieldKey="box_sinot", label="box_sinot", fieldType="currency",
            dataSourceKind="PAYSLIP_ITEM", sourceColumn="state_disability_insurance", aggregation="SUM_YTD",
        ), actor_id=creator.id,
    )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)
    return template


def _build_pr_dtrh_quarterly_template(db, creator, approver, key="PR-DTRH-QUARTERLY-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="DTRH Quarterly Return", reportType="PR_DTRH_QUARTERLY",
            jurisdictionCountry="PR", reportingYear="2026", documentScope="AGGREGATE",
        ), actor_id=creator.id,
    )
    employer_info = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="employer_info", label="Employer Information"), actor_id=creator.id,
    )
    for field_key, label, source_column, kind in (
        ("employer_name", "Employer Name", "name", "EMPLOYER_PROFILE"),
        ("employer_dtrh_account", "DTRH Account", "tax_no", "EMPLOYER_PROFILE"),
        ("employee_count", "Employee Count", "gross_pay", "PAYSLIP_ITEM"),
    ):
        service.upsert_report_field(
            db, employer_info.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=label, fieldType="text", dataSourceKind=kind, sourceColumn=source_column,
            ), actor_id=creator.id,
        )
    unemployment = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="unemployment", label="Unemployment Wages & Tax"), actor_id=creator.id,
    )
    for field_key, source_column in (
        ("total_wages", "gross_pay"), ("unemployment_taxable_wages", "employer_sui"), ("unemployment_tax_due", "employer_sui"),
    ):
        service.upsert_report_field(
            db, unemployment.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=field_key, fieldType="currency",
                dataSourceKind="PAYSLIP_ITEM", sourceColumn=source_column, aggregation="SUM_RUN",
            ), actor_id=creator.id,
        )
    sinot = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="sinot", label="SINOT Wages & Contributions"), actor_id=creator.id,
    )
    for field_key, source_column in (
        ("sinot_taxable_wages", "state_disability_insurance"), ("sinot_employee_contribution", "state_disability_insurance"),
        ("sinot_employer_contribution", "employer_state_program_contributions"),
    ):
        service.upsert_report_field(
            db, sinot.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=field_key, fieldType="currency",
                dataSourceKind="PAYSLIP_ITEM", sourceColumn=source_column, aggregation="SUM_RUN",
            ), actor_id=creator.id,
        )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)
    return template


# ── Form 499R-2/W-2PR ─────────────────────────────────────────────────

def test_generate_pr_w2pr_sums_the_calendar_year(db, organization):
    creator = _make_user(db, "creator_prw2a@test.com")
    approver = _make_user(db, "approver_prw2a@test.com")
    _make_company(db, organization.id, country="PR")
    employee = _make_pr_employee(db, organization.id, code="PRW2A", name="Maria Rivera")
    _make_pr_run_with_payslip(
        db, organization.id, employee.id, date(2026, 2, 15),
        gross_pay=Decimal("4000"), tds=Decimal("296.25"), social_security=Decimal("248.00"),
        medicare=Decimal("58.00"), state_disability_insurance=Decimal("12.00"),
        employee_name="Maria Rivera",
    )
    _make_pr_run_with_payslip(
        db, organization.id, employee.id, date(2026, 3, 15),
        gross_pay=Decimal("4000"), tds=Decimal("296.25"), social_security=Decimal("248.00"),
        medicare=Decimal("58.00"), state_disability_insurance=Decimal("12.00"),
        employee_name="Maria Rivera",
    )
    # Outside the tax year — must NOT be summed in.
    _make_pr_run_with_payslip(
        db, organization.id, employee.id, date(2027, 1, 15),
        gross_pay=Decimal("9999"), tds=Decimal("9999"), employee_name="Maria Rivera",
    )

    template = _build_pr_w2pr_template(db, creator, approver)
    generated = service.generate_pr_w2pr(db, organization.id, template.id, employee.id, "2026", actor_id=creator.id)

    assert generated.report_type == "PR_W2PR"
    assert generated.reporting_year == "2026"
    values = generated.rendered_data["employees"][0]["values"]
    assert values["box_wages"] == 8000.0
    assert values["box_pr_tax_withheld"] == 592.50
    assert values["box_ss_tax"] == 496.0
    assert values["box_medicare_tax"] == 116.0
    assert values["box_sinot"] == 24.0


def test_generate_pr_w2pr_rejects_wrong_report_type(db, organization):
    creator = _make_user(db, "creator_prw2b@test.com")
    approver = _make_user(db, "approver_prw2b@test.com")
    _make_company(db, organization.id, country="PR")
    employee = _make_pr_employee(db, organization.id, code="PRW2B")
    template = _build_template(db, creator, approver, country="PR", version="prw2pr-neg")
    with pytest.raises(BadRequestException):
        service.generate_pr_w2pr(db, organization.id, template.id, employee.id, "2026")


def test_generate_pr_w2pr_regenerating_supersedes_prior(db, organization):
    creator = _make_user(db, "creator_prw2c@test.com")
    approver = _make_user(db, "approver_prw2c@test.com")
    _make_company(db, organization.id, country="PR")
    employee = _make_pr_employee(db, organization.id, code="PRW2C")
    _make_pr_run_with_payslip(db, organization.id, employee.id, date(2026, 2, 10))

    template = _build_pr_w2pr_template(db, creator, approver, key="PR-W2PR-SUPERSEDE-TEST")
    first = service.generate_pr_w2pr(db, organization.id, template.id, employee.id, "2026", actor_id=creator.id)
    second = service.generate_pr_w2pr(db, organization.id, template.id, employee.id, "2026", actor_id=creator.id)
    db.refresh(first)
    assert first.status == "Superseded"
    assert second.status == "Generated"


def test_generate_pr_w2pr_never_touches_a_us_payslip(db, organization):
    """Same employee-isolation guarantee as generate_pr_499r1b's own
    isolation test — a US-country-code payslip must never leak into a PR
    employee's W-2PR totals."""
    creator = _make_user(db, "creator_prw2d@test.com")
    approver = _make_user(db, "approver_prw2d@test.com")
    _make_company(db, organization.id, country="PR")
    employee = _make_pr_employee(db, organization.id, code="PRW2D", name="Maria Rivera")
    _make_pr_run_with_payslip(
        db, organization.id, employee.id, date(2026, 2, 10),
        gross_pay=Decimal("4000"), tds=Decimal("296.25"), employee_name="Maria Rivera",
    )
    run = PayrollRun(
        organization_id=organization.id, period_label="2026-02-10", period_start=date(2026, 2, 1),
        period_end=date(2026, 2, 10), pay_date=date(2026, 2, 10), status="Approved",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    db.add(PayslipItem(
        payroll_run_id=run.id, employee_id=employee.id, organization_id=organization.id,
        employee_name="Maria Rivera", country_code="US",
        gross_pay=Decimal("99999"), tds=Decimal("99999"), total_deductions=Decimal("0"), net_pay=Decimal("0"),
    ))
    db.commit()

    template = _build_pr_w2pr_template(db, creator, approver, key="PR-W2PR-ISOLATION-TEST")
    generated = service.generate_pr_w2pr(db, organization.id, template.id, employee.id, "2026", actor_id=creator.id)
    values = generated.rendered_data["employees"][0]["values"]
    assert values["box_wages"] == 4000.0
    assert values["box_pr_tax_withheld"] == 296.25


# ── DTRH quarterly wage/contribution return ──────────────────────────

def test_generate_pr_dtrh_quarterly_aggregates_two_employees_and_caps_wage_bases(db, organization):
    creator = _make_user(db, "creator_prdtrha@test.com")
    approver = _make_user(db, "approver_prdtrha@test.com")
    _make_company(db, organization.id, country="PR")
    emp1 = _make_pr_employee(db, organization.id, code="PRDTRHA1", name="Maria Rivera")
    emp2 = _make_pr_employee(db, organization.id, code="PRDTRHA2", name="Jose Ortiz")

    _make_pr_run_with_payslip(
        db, organization.id, emp1.id, date(2026, 2, 15),
        gross_pay=Decimal("8000"), employer_sui=Decimal("21.00"),
        state_disability_insurance=Decimal("27.00"), employer_state_program_contributions=Decimal("27.00"),
        employee_name="Maria Rivera",
    )
    _make_pr_run_with_payslip(
        db, organization.id, emp2.id, date(2026, 3, 15),
        gross_pay=Decimal("5000"), employer_sui=Decimal("15.00"),
        state_disability_insurance=Decimal("15.00"), employer_state_program_contributions=Decimal("15.00"),
        employee_name="Jose Ortiz",
    )
    # Outside Q1 — must NOT be summed in.
    _make_pr_run_with_payslip(
        db, organization.id, emp1.id, date(2026, 4, 15),
        gross_pay=Decimal("9999"), employer_sui=Decimal("999"), employee_name="Maria Rivera",
    )

    template = _build_pr_dtrh_quarterly_template(db, creator, approver)
    generated = service.generate_pr_dtrh_quarterly(db, organization.id, template.id, 2026, 1, actor_id=creator.id)

    assert generated.report_type == "PR_DTRH_QUARTERLY"
    assert generated.reporting_period == "Q1"
    assert generated.rendered_data["employeeCount"] == 2
    values = generated.rendered_data["employer"]
    assert values["total_wages"] == 13000.0
    # $7,000/employee unemployment cap: emp1's $8,000 caps to $7,000, emp2's $5,000 stays uncapped -> 12,000.
    assert values["unemployment_taxable_wages"] == 12000.0
    assert values["unemployment_tax_due"] == 36.0
    # $9,000/employee SINOT cap: neither employee exceeds it, so both stay uncapped -> 13,000.
    assert values["sinot_taxable_wages"] == 13000.0
    assert values["sinot_employee_contribution"] == 42.0
    assert values["sinot_employer_contribution"] == 42.0


def test_generate_pr_dtrh_quarterly_rejects_wrong_report_type(db, organization):
    creator = _make_user(db, "creator_prdtrhb@test.com")
    approver = _make_user(db, "approver_prdtrhb@test.com")
    _make_company(db, organization.id, country="PR")
    template = _build_template(db, creator, approver, country="PR", version="prdtrh-neg")
    with pytest.raises(BadRequestException):
        service.generate_pr_dtrh_quarterly(db, organization.id, template.id, 2026, 1)


def test_generate_pr_dtrh_quarterly_never_touches_a_us_payslip(db, organization):
    creator = _make_user(db, "creator_prdtrhc@test.com")
    approver = _make_user(db, "approver_prdtrhc@test.com")
    _make_company(db, organization.id, country="PR")
    pr_employee = _make_pr_employee(db, organization.id, code="PRDTRHC1", name="Maria Rivera")
    us_employee = PayrollEmployee(organization_id=organization.id, employee_code="PRDTRHC-US", name="John Smith")
    db.add(us_employee)
    db.commit()
    db.refresh(us_employee)

    _make_pr_run_with_payslip(
        db, organization.id, pr_employee.id, date(2026, 2, 10),
        gross_pay=Decimal("4000"), employer_sui=Decimal("12.00"),
        state_disability_insurance=Decimal("12.00"), employer_state_program_contributions=Decimal("12.00"),
        employee_name="Maria Rivera",
    )
    run = PayrollRun(
        organization_id=organization.id, period_label="2026-02-10", period_start=date(2026, 2, 1),
        period_end=date(2026, 2, 10), pay_date=date(2026, 2, 10), status="Approved",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    db.add(PayslipItem(
        payroll_run_id=run.id, employee_id=us_employee.id, organization_id=organization.id,
        employee_name="John Smith", country_code="US",
        gross_pay=Decimal("99999"), employer_sui=Decimal("99999"),
        total_deductions=Decimal("0"), net_pay=Decimal("0"),
    ))
    db.commit()

    template = _build_pr_dtrh_quarterly_template(db, creator, approver, key="PR-DTRH-QUARTERLY-ISOLATION-TEST")
    generated = service.generate_pr_dtrh_quarterly(db, organization.id, template.id, 2026, 1, actor_id=creator.id)
    assert generated.rendered_data["employeeCount"] == 1
    assert generated.rendered_data["employer"]["total_wages"] == 4000.0
