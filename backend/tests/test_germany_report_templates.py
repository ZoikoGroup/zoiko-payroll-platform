"""
tests/test_germany_report_templates.py
----------------------------------------
Germany's addition to the Report Template system — same architecture as
India/UK/Canada/US/Australia (see tests/test_report_templates.py), no new
backend machinery: Germany's Lohnsteuerbescheinigung (LSTB, per-employee,
via the shared generate_uk_employee_report engine — never actually
UK-specific) and a Germany Payroll Summary (aggregate, via the shared
generate_report_from_template engine). Also covers the two small,
additive field-catalog extensions this addition needed: a "DE" entry in
_PAYROLL_EMPLOYEE_FIELDS_BY_COUNTRY (steuer_id/iban, resolved from
PayrollEmployee.compliance_fields — the exact same mechanism UK's "nino"
already used) and "LSTB"/"DE_PAYROLL_SUMMARY" in _REPORT_COMPONENTS_BY_TYPE.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import service
from app.modules.payroll.schemas import (
    ReportTemplateUpsert, ReportTemplateComponentUpsert, ReportTemplateFieldUpsert,
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


def _make_company(db, organization_id, country="DE", state=None):
    from app.modules.payroll.models import CompanyComplianceDetails
    company = CompanyComplianceDetails(
        organization_id=organization_id, name="Zoiko Germany GmbH", tax_no="12/345/67890",
        jurisdiction_country=country, jurisdiction_state=state or "",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _make_de_run_with_payslip(db, organization_id, status="Approved"):
    from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem

    employee = PayrollEmployee(
        organization_id=organization_id, employee_code="DE001", name="Anna Schmidt", country_code="DE",
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)

    run = PayrollRun(
        organization_id=organization_id, period_label="Aug 2026",
        period_start=date(2026, 8, 1), period_end=date(2026, 8, 31), pay_date=date(2026, 8, 31),
        status=status, total_gross=4500, total_deductions=1500, total_net=3000,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee.id, organization_id=organization_id,
        employee_name="Anna Schmidt", basic_salary=4500, gross_pay=4500,
        pf=418.5, esi=475.65, tds=689.0, soli=0, church_tax=55.12,
        employer_pf=418.5, employer_esi=475.65,
        total_deductions=1500, net_pay=3000,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return run, employee, item


def _build_de_lstb_template(db, creator, approver, key="DE-LSTB-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="Lohnsteuerbescheinigung", reportType="LSTB",
            jurisdictionCountry="DE", reportingYear="2026", documentScope="PER_EMPLOYEE",
        ), actor_id=creator.id,
    )
    employee_info = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="employee_info", label="Employee Information"),
        actor_id=creator.id,
    )
    for field_key, label in (("name", "Employee Name"), ("steuer_id", "Tax ID"), ("iban", "IBAN")):
        service.upsert_report_field(
            db, employee_info.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=label, fieldType="text",
                dataSourceKind="PAYROLL_EMPLOYEE", sourceColumn=field_key,
            ), actor_id=creator.id,
        )
    ytd = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="ytd", label="Year-to-Date"), actor_id=creator.id,
    )
    for field_key, label, source_column in (
        # "tds" is Lohnsteuer + Soli combined (never Lohnsteuer alone) —
        # label matches the seeded production template, see
        # scripts/seed_statutory_report_templates.py.
        ("lohnsteuer_ytd", "Lohnsteuer + Soli (YTD)", "tds"),
        ("soli_ytd", "Soli (YTD)", "soli"),
        ("church_tax_ytd", "Kirchensteuer (YTD)", "church_tax"),
    ):
        service.upsert_report_field(
            db, ytd.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=label, fieldType="currency",
                dataSourceKind="PAYSLIP_ITEM", sourceColumn=source_column, aggregation="SUM_YTD",
            ), actor_id=creator.id,
        )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    return service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)


def _build_de_payroll_summary_template(db, creator, approver, key="DE-SUMMARY-TEST"):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=key, name="Germany Payroll Summary", reportType="DE_PAYROLL_SUMMARY",
            jurisdictionCountry="DE", reportingYear="2026", documentScope="AGGREGATE",
        ), actor_id=creator.id,
    )
    tax = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="tax", label="Wage Tax"), actor_id=creator.id,
    )
    for field_key, label, source_column in (
        ("total_lohnsteuer", "Total Lohnsteuer + Soli", "tds"),
        ("total_soli", "Total Soli", "soli"),
        ("total_church_tax", "Total Kirchensteuer", "church_tax"),
    ):
        service.upsert_report_field(
            db, tax.id, ReportTemplateFieldUpsert(
                fieldKey=field_key, label=label, fieldType="currency",
                dataSourceKind="PAYSLIP_ITEM", sourceColumn=source_column, aggregation="SUM_RUN",
            ), actor_id=creator.id,
        )
    contributions = service.upsert_report_component(
        db, template.id, ReportTemplateComponentUpsert(componentKey="contributions", label="Social Insurance"),
        actor_id=creator.id,
    )
    service.upsert_report_field(
        db, contributions.id, ReportTemplateFieldUpsert(
            fieldKey="total_pf", label="Total Pension Insurance", fieldType="currency",
            dataSourceKind="PAYSLIP_ITEM", sourceColumn="pf", aggregation="SUM_RUN",
        ), actor_id=creator.id,
    )
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    return service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)


# ── Field/component catalogs are genuinely DE-specific, not a fallback ────

def test_available_report_components_for_lstb_is_de_specific_not_default():
    components = service.get_available_report_components("LSTB")
    keys = {c["key"] for c in components}
    assert keys == {"employer_info", "employee_info", "earnings", "tax", "contributions", "employer_contributions", "ytd"}


def test_available_report_components_for_de_payroll_summary():
    components = service.get_available_report_components("DE_PAYROLL_SUMMARY")
    keys = {c["key"] for c in components}
    assert "tax" in keys and "contributions" in keys and "employer_contributions" in keys


def test_available_report_data_fields_de_includes_church_tax_and_soli_not_india_us_fields():
    fields = service.get_available_report_data_fields("DE")
    keys = {f["key"] for f in fields if f["dataSourceKind"] == "PAYSLIP_ITEM"}
    assert "church_tax" in keys and "soli" in keys and "pf" in keys and "esi" in keys
    # Confirms this is the narrowed DE list, not the full default catalog
    # (which would also include India/US-only columns like "uan"/"cess").
    assert "uan" not in keys and "cess" not in keys


def test_available_report_data_fields_de_includes_steuer_id_and_iban():
    fields = service.get_available_report_data_fields("DE")
    employee_fields = {f["key"] for f in fields if f["dataSourceKind"] == "PAYROLL_EMPLOYEE"}
    assert "steuer_id" in employee_fields
    assert "iban" in employee_fields


# ── LSTB (per-employee, no run — generate_uk_employee_report) ────────────

def test_generate_de_lstb_resolves_employee_and_ytd_fields(db, organization):
    creator = _make_user(db, "creator_de1@test.com")
    approver = _make_user(db, "approver_de1@test.com")
    _make_company(db, organization.id, country="DE")
    run, employee, item = _make_de_run_with_payslip(db, organization.id, status="Approved")
    employee.compliance_fields = {"steuer_id": "12 345 678 901", "iban": "DE89370400440532013000"}
    db.commit()

    template = _build_de_lstb_template(db, creator, approver)
    generated = service.generate_uk_employee_report(
        db, organization.id, template.id, employee.id, date(2026, 12, 31), actor_id=creator.id,
    )
    assert generated.payroll_run_id is None
    assert generated.employee_id == employee.id
    assert generated.report_type == "LSTB"

    values = generated.rendered_data["employees"][0]["values"]
    assert values["steuer_id"] == "12 345 678 901"
    assert values["iban"] == "DE89370400440532013000"
    assert values["lohnsteuer_ytd"] == float(item.tds)
    assert values["church_tax_ytd"] == float(item.church_tax)

    # Label must not claim to be Lohnsteuer alone — `tds` is Lohnsteuer +
    # Soli combined. See test_generate_de_lstb_lohnsteuer_field_label_and_
    # value_are_consistent for the dedicated regression test.
    ytd_component = next(
        c for c in generated.rendered_data["templateSnapshot"]["components"] if c["componentKey"] == "ytd"
    )
    lohnsteuer_field = next(f for f in ytd_component["fields"] if f["fieldKey"] == "lohnsteuer_ytd")
    assert lohnsteuer_field["label"] != "Lohnsteuer (YTD)"


def test_generate_de_lstb_lohnsteuer_field_label_and_value_are_consistent(db, organization):
    """Regression test for the mislabeling this project's own live-UAT PDF
    inspection caught: a field labeled plain "Lohnsteuer" but sourced from
    `PayslipItem.tds`, which is persisted as Lohnsteuer + Soli COMBINED
    (see engine/countries/germany.py's monthly tds derivation — there is
    no separate pure-Lohnsteuer column). This test fails if either:
      (a) the label reverts to something that claims to be Lohnsteuer
          alone (e.g. exactly "Lohnsteuer" or "Lohnsteuer (YTD)"), or
      (b) the value stops equalling tds (i.e. someone "fixes" the label
          by silently changing the underlying value instead, which would
          be changing calculation semantics, not presentation).
    Uses a payslip where tds != soli (both non-zero and distinct) so a
    field that silently collapsed to Soli-only, or to zero, or to some
    other confusion, could not accidentally pass by coincidence."""
    creator = _make_user(db, "creator_de_label@test.com")
    approver = _make_user(db, "approver_de_label@test.com")
    _make_company(db, organization.id, country="DE")

    from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem

    employee = PayrollEmployee(
        organization_id=organization.id, employee_code="DE-LABEL-001", name="Label Test Employee", country_code="DE",
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)

    run = PayrollRun(
        organization_id=organization.id, period_label="Jan 2026",
        period_start=date(2026, 1, 1), period_end=date(2026, 1, 31), pay_date=date(2026, 1, 31),
        status="Approved", total_gross=9000, total_deductions=3927.93, total_net=5072.07,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Deliberately distinct, non-zero Lohnsteuer-only vs Soli amounts,
    # matching this project's own real Employee-D-shaped UAT scenario:
    # Lohnsteuer-only = 2161.84, Soli = 55.45, tds (combined) = 2217.29.
    lohnsteuer_only = Decimal("2161.84")
    soli_only = Decimal("55.45")
    tds_combined = lohnsteuer_only + soli_only  # 2217.29
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee.id, organization_id=organization.id,
        employee_name="Label Test Employee", basic_salary=9000, gross_pay=9000,
        pf=785.85, esi=751.84, tds=tds_combined, soli=soli_only, church_tax=172.95,
        employer_pf=785.85, employer_esi=729.65,
        total_deductions=3927.93, net_pay=5072.07,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    template = _build_de_lstb_template(db, creator, approver, key="DE-LSTB-LABEL-TEST")
    generated = service.generate_uk_employee_report(
        db, organization.id, template.id, employee.id, date(2026, 1, 31), actor_id=creator.id,
    )

    # Pull the field's LABEL from the rendered template snapshot, and its
    # VALUE from the employee's rendered values, independently.
    ytd_component = next(
        c for c in generated.rendered_data["templateSnapshot"]["components"] if c["componentKey"] == "ytd"
    )
    lohnsteuer_field = next(f for f in ytd_component["fields"] if f["fieldKey"] == "lohnsteuer_ytd")
    soli_field = next(f for f in ytd_component["fields"] if f["fieldKey"] == "soli_ytd")
    values = generated.rendered_data["employees"][0]["values"]

    # LABEL: must not claim to be Lohnsteuer alone.
    assert lohnsteuer_field["label"] != "Lohnsteuer"
    assert lohnsteuer_field["label"] != "Lohnsteuer (YTD)"
    assert "Soli" in lohnsteuer_field["label"] or "soli" in lohnsteuer_field["label"].lower()
    assert soli_field["label"] == "Soli (YTD)"

    # VALUE: the combined field must equal Lohnsteuer + Soli exactly, and
    # the separate Soli field must equal Soli alone — proving the two
    # fields are genuinely distinct sources, not the same number twice.
    assert Decimal(str(values["lohnsteuer_ytd"])) == tds_combined == lohnsteuer_only + soli_only
    assert Decimal(str(values["soli_ytd"])) == soli_only
    assert values["lohnsteuer_ytd"] != values["soli_ytd"]


def test_generate_de_lstb_certificate_pdf_renders(db, organization):
    """Same PDF-rendering reuse UK P60/Canada T4 already proved — no new
    renderer code needed for Germany's per-employee document either."""
    creator = _make_user(db, "creator_de2@test.com")
    approver = _make_user(db, "approver_de2@test.com")
    _make_company(db, organization.id, country="DE")
    run, employee, item = _make_de_run_with_payslip(db, organization.id, status="Approved")
    template = _build_de_lstb_template(db, creator, approver, key="DE-LSTB-CERT")

    generated = service.generate_uk_employee_report(db, organization.id, template.id, employee.id, date(2026, 12, 31))
    pdf_bytes = service.generate_report_certificate_pdf_bytes(db, organization.id, generated.id, employee.id)
    assert pdf_bytes.startswith(b"%PDF")


def test_generate_de_lstb_rejects_jurisdiction_mismatch(db, organization):
    """A UK employee (org's default jurisdiction) cannot generate against
    a Germany LSTB template — same guard as every other jurisdiction."""
    creator = _make_user(db, "creator_de3@test.com")
    approver = _make_user(db, "approver_de3@test.com")
    _make_company(db, organization.id, country="UK")
    run, employee, item = _make_de_run_with_payslip(db, organization.id, status="Approved")
    employee.country_code = None  # falls back to the org's UK default
    db.commit()
    template = _build_de_lstb_template(db, creator, approver, key="DE-LSTB-MISMATCH")
    with pytest.raises(BadRequestException):
        service.generate_uk_employee_report(db, organization.id, template.id, employee.id, date(2026, 12, 31))


def test_generate_de_lstb_rejects_wrong_report_type(db, organization):
    """generate_uk_employee_report's allow-list genuinely includes LSTB
    now, but still rejects an unrelated Germany report_type (DE_PAYROLL_
    SUMMARY, AGGREGATE) — the extension didn't accidentally widen the
    gate to "anything goes"."""
    creator = _make_user(db, "creator_de7@test.com")
    approver = _make_user(db, "approver_de7@test.com")
    _make_company(db, organization.id, country="DE")
    run, employee, item = _make_de_run_with_payslip(db, organization.id, status="Approved")
    template = _build_de_payroll_summary_template(db, creator, approver, key="DE-SUMMARY-WRONGTYPE")
    with pytest.raises(BadRequestException):
        service.generate_uk_employee_report(db, organization.id, template.id, employee.id, date(2026, 12, 31))


# ── Germany Payroll Summary (aggregate, run-based — generic mapper) ──────

def test_generate_de_payroll_summary_end_to_end(db, organization):
    creator = _make_user(db, "creator_de4@test.com")
    approver = _make_user(db, "approver_de4@test.com")
    _make_company(db, organization.id, country="DE")
    run, employee, item = _make_de_run_with_payslip(db, organization.id, status="Approved")

    template = _build_de_payroll_summary_template(db, creator, approver)

    resolved = service.get_applicable_report_template(db, "DE", None, "2026", "DE_PAYROLL_SUMMARY")
    assert resolved is not None and resolved.id == template.id

    generated = service.generate_report_from_template(
        db, organization.id, template.id, run.id, reporting_period=run.period_label, actor_id=creator.id,
    )
    assert generated.status == "Generated"
    # Every field on this template is SUM_RUN, so generate_report_from_
    # template resolves them as HEADER (employer-level) values, not
    # per-employee rows — see its own header_values/employee_values split.
    header = generated.rendered_data["employer"]
    assert header["total_lohnsteuer"] == float(item.tds)
    assert header["total_soli"] == float(item.soli)
    assert header["total_church_tax"] == float(item.church_tax)
    assert header["total_pf"] == float(item.pf)

    # Label must not claim to be Lohnsteuer alone — same combined-value
    # fix as DE-LSTB above.
    tax_component = next(
        c for c in generated.rendered_data["templateSnapshot"]["components"] if c["componentKey"] == "tax"
    )
    lohnsteuer_field = next(f for f in tax_component["fields"] if f["fieldKey"] == "total_lohnsteuer")
    assert lohnsteuer_field["label"] != "Total Lohnsteuer"
    # The three fallback reconciliation totals (gross/deductions/net) are
    # always computed straight from the run's own PayslipItem rows
    # regardless of which fields the template maps, so they tie out...
    assert generated.rendered_data["totals"]["gross_pay"] == float(item.gross_pay)
    # ...but the row-count check inside _compute_report_reconciliation
    # compares len(rendered_data["employees"]) against the run's real
    # payslip count — an all-SUM_RUN template (this one, and the
    # pre-existing UK-EPS-FPS-SUMMARY seed template — same shape) never
    # populates any "employees" rows at all, so this is a genuine,
    # pre-existing characteristic of the shared engine for a pure
    # header-aggregate template, not a defect introduced here.
    assert generated.reconciliation["rowCountReport"] == 0
    assert generated.reconciliation["rowCountRun"] == 1
    assert generated.reconciliation["status"] == "MISMATCH"
    assert all(d["delta"] == 0 for d in generated.reconciliation["fieldDiffs"])


def test_de_payroll_summary_listed_for_de_org_not_other_jurisdictions(db, organization):
    creator = _make_user(db, "creator_de5@test.com")
    approver = _make_user(db, "approver_de5@test.com")
    _make_company(db, organization.id, country="DE")
    _build_de_payroll_summary_template(db, creator, approver, key="DE-SUMMARY-LIST")

    available = service.list_available_reports_for_org(db, organization.id, "2026")
    assert available == [{"reportType": "DE_PAYROLL_SUMMARY", "name": "Germany Payroll Summary"}]

    # A different reporting year (matching the India precedent in
    # test_report_templates.py) sees nothing.
    assert service.list_available_reports_for_org(db, organization.id, "2027") == []


def test_de_template_not_resolved_for_non_de_organization(db, organization):
    """Cross-jurisdiction isolation: an org configured for a different
    country never resolves Germany's own Active template, even though
    both templates share the same reporting_year string."""
    creator = _make_user(db, "creator_de6@test.com")
    approver = _make_user(db, "approver_de6@test.com")
    _make_company(db, organization.id, country="CA")
    _build_de_payroll_summary_template(db, creator, approver, key="DE-SUMMARY-ISOLATION")

    assert service.list_available_reports_for_org(db, organization.id, "2026") == []
    resolved = service.get_applicable_report_template_for_org(db, organization.id, "2026", "DE_PAYROLL_SUMMARY")
    assert resolved["template"] is None
