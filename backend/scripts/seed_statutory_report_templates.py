"""
scripts/seed_statutory_report_templates.py
--------------------------------------------
Seeds concrete, named Report Templates for the statutory forms explicitly
named in the India/UK configuration packs (Form 130 TDS certificate, Form
138 quarterly TDS statement + its Q1-Q4 filing calendar, UK P60, and a UK
EPS/FPS-style employer summary) — Phase 3 of the Report Template system.

This is NOT hardcoded business logic: every row is created by calling the
same validated service functions (upsert_report_template/_component/
_field, upsert_filing_calendar_entry) a Super Admin's own UI action calls,
so the real-column allow-list, component catalog, and versioning all still
apply. This script only removes the burden of typing out ~15-20 field
mappings by hand for a first-run pilot.

Seeded templates land in "Draft" status — they still require a distinct
Super Admin to Approve, Publish and Activate them through the normal
lifecycle before an Organization can generate against them. This script
does not bypass maker-checker.

Idempotent: safe to re-run (upsert_report_template/_component/_field all
look up by natural key when no id is given, so re-running updates the
existing seeded rows rather than duplicating or erroring).

Usage:
    python -m scripts.seed_statutory_report_templates
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.modules.payroll import service
from app.modules.payroll.schemas import (
    ReportTemplateUpsert, ReportTemplateComponentUpsert, ReportTemplateFieldUpsert, FilingCalendarUpsert,
)


def _seed_template(db, *, template_key, name, report_type, country, reporting_year, document_scope, components):
    """`components` = [(component_key, label, [(field_key, label, field_type, data_source_kind, source_column, aggregation), ...])]"""
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=template_key, name=name, reportType=report_type,
            jurisdictionCountry=country, reportingYear=reporting_year, documentScope=document_scope,
            changeSummary="Seeded via scripts/seed_statutory_report_templates.py",
        ), actor_id=None,
    )
    for sort_order, (component_key, label, fields) in enumerate(components):
        component = service.upsert_report_component(
            db, template.id, ReportTemplateComponentUpsert(componentKey=component_key, label=label, sortOrder=sort_order),
            actor_id=None,
        )
        for field_sort_order, (field_key, field_label, field_type, data_source_kind, source_column, aggregation) in enumerate(fields):
            service.upsert_report_field(
                db, component.id, ReportTemplateFieldUpsert(
                    fieldKey=field_key, label=field_label, fieldType=field_type,
                    dataSourceKind=data_source_kind, sourceColumn=source_column, aggregation=aggregation,
                    sortOrder=field_sort_order,
                ), actor_id=None,
            )
    print(f"  seeded {template_key} v{template.version} (id={template.id}, status={template.status})")
    return template


def run():
    db = SessionLocal()
    try:
        print("Seeding India Form 130 (Salary TDS Certificate, per-employee)...")
        _seed_template(
            db, template_key="IN-FORM-130", name="Salary TDS Certificate (Form 130)", report_type="FORM_130",
            country="IN", reporting_year="2026-27", document_scope="PER_EMPLOYEE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_tax_no", "Tax Registration Number (TAN)", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                ("employee_info", "Employee Information", [
                    ("employee_name", "Employee Name", "text", "PAYSLIP_ITEM", "employee_name", None),
                    ("employee_pan", "PAN", "text", "PAYSLIP_ITEM", "pan", None),
                ]),
                ("earnings", "Earnings", [
                    ("gross_pay", "Gross Salary", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ]),
                ("tax", "Tax", [
                    ("tds", "Tax Deducted at Source", "currency", "PAYSLIP_ITEM", "tds", None),
                    ("surcharge", "Surcharge", "currency", "PAYSLIP_ITEM", "surcharge", None),
                    ("cess", "Health & Education Cess", "currency", "PAYSLIP_ITEM", "cess", None),
                ]),
                ("ytd", "Year-to-Date", [
                    ("tds_ytd", "TDS (Year-to-Date)", "currency", "PAYSLIP_ITEM", "tds", "SUM_YTD"),
                ]),
            ],
        )

        print("Seeding India Form 123 (Employer Perquisite Statement, per-employee)...")
        _seed_template(
            db, template_key="IN-FORM-123", name="Employer Perquisite Statement (Form 123)", report_type="FORM_123",
            country="IN", reporting_year="2026-27", document_scope="PER_EMPLOYEE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_tax_no", "Tax Registration Number (TAN)", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
            ],
        )
        # Benefit-line content (car/accommodation/stock benefit/...) comes
        # directly from Issued EmployeeBenefitValuation rows at generation
        # time (service.generate_india_form_123), not from a component/
        # field mapping — there's no PayslipItem column for a perquisite's
        # value.

        print("Seeding India Form 138 (Quarterly Salary TDS Statement, aggregate)...")
        _seed_template(
            db, template_key="IN-FORM-138", name="Quarterly Salary TDS Statement (Form 138)", report_type="FORM_138",
            country="IN", reporting_year="2026-27", document_scope="AGGREGATE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_tax_no", "Tax Registration Number (TAN)", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                ("tax", "Tax", [
                    ("total_tds", "Total TDS Deducted", "currency", "PAYSLIP_ITEM", "tds", "SUM_RUN"),
                ]),
            ],
        )

        # India pack §6.3 Form 138 filing calendar — Q1-Q4 due dates,
        # exactly as printed in the source document, never guessed.
        print("Seeding India Form 138 filing calendar (Q1-Q4, per the India statutory pack section 6.3)...")
        for period_key, period_label, due_date in [
            ("Q1", "April-June", "2026-07-31"),
            ("Q2", "July-September", "2026-10-31"),
            ("Q3", "October-December", "2027-01-31"),
            ("Q4", "January-March", "2027-05-31"),
        ]:
            entry = service.upsert_filing_calendar_entry(
                db, FilingCalendarUpsert(
                    jurisdictionCountry="IN", reportType="FORM_138", reportingYear="2026-27",
                    periodKey=period_key, periodLabel=period_label, dueDate=due_date,
                ), actor_id=None,
            )
            print(f"  seeded IN FORM_138 {period_key} due {due_date} (id={entry.id}, status={entry.status})")

        print("Seeding UK P60 (End of Year Certificate, per-employee)...")
        _seed_template(
            db, template_key="UK-P60", name="P60 - End of Year Certificate", report_type="P60",
            country="UK", reporting_year="2026-27", document_scope="PER_EMPLOYEE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                ]),
                ("employee_info", "Employee Information", [
                    ("employee_name", "Employee Name", "text", "PAYSLIP_ITEM", "employee_name", None),
                ]),
                ("earnings", "Earnings", [
                    ("gross_pay", "Total Pay", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ]),
                ("tax", "Tax", [
                    ("paye", "PAYE Tax Deducted", "currency", "PAYSLIP_ITEM", "tds", None),
                ]),
                ("contributions", "National Insurance", [
                    ("ni_employee", "National Insurance (Employee)", "currency", "PAYSLIP_ITEM", "ni_employee", None),
                ]),
                ("employer_contributions", "Employer Contributions", [
                    ("employer_ni", "National Insurance (Employer)", "currency", "PAYSLIP_ITEM", "employer_ni", None),
                ]),
                ("ytd", "Year-to-Date", [
                    ("paye_ytd", "PAYE Tax (Year-to-Date)", "currency", "PAYSLIP_ITEM", "tds", "SUM_YTD"),
                    ("ni_employee_ytd", "National Insurance (Year-to-Date)", "currency", "PAYSLIP_ITEM", "ni_employee", "SUM_YTD"),
                ]),
            ],
        )

        print("Seeding UK EPS/FPS-style employer summary (aggregate)...")
        _seed_template(
            db, template_key="UK-EPS-FPS-SUMMARY", name="Employer Payment Summary (EPS/FPS)", report_type="EPS_FPS",
            country="UK", reporting_year="2026-27", document_scope="AGGREGATE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                ]),
                ("contributions", "National Insurance", [
                    ("total_ni_employee", "Total Employee NI", "currency", "PAYSLIP_ITEM", "ni_employee", "SUM_RUN"),
                ]),
                ("employer_contributions", "Employer Contributions", [
                    ("total_employer_ni", "Total Employer NI", "currency", "PAYSLIP_ITEM", "employer_ni", "SUM_RUN"),
                ]),
            ],
        )

        print("Seeding Canada T4 (Statement of Remuneration Paid, per-employee)...")
        _seed_template(
            db, template_key="CA-T4", name="T4 - Statement of Remuneration Paid", report_type="T4",
            country="CA", reporting_year="2026", document_scope="PER_EMPLOYEE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_bn", "Business Number (BN)", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                ("employee_info", "Employee Information", [
                    ("employee_name", "Employee Name", "text", "PAYROLL_EMPLOYEE", "name", None),
                ]),
                ("earnings", "Earnings (Year-to-Date)", [
                    ("employment_income", "Box 14 - Employment Income", "currency", "PAYSLIP_ITEM", "gross_pay", "SUM_YTD"),
                ]),
                ("tax", "Tax (Year-to-Date)", [
                    ("income_tax_deducted", "Box 22 - Income Tax Deducted", "currency", "PAYSLIP_ITEM", "tds", "SUM_YTD"),
                ]),
                ("cpp", "CPP (Year-to-Date)", [
                    ("cpp_contributions", "Box 16 - CPP Contributions", "currency", "PAYSLIP_ITEM", "social_security", "SUM_YTD"),
                    ("cpp2_contributions", "Box 16A - CPP2 Contributions", "currency", "PAYSLIP_ITEM", "cpp2", "SUM_YTD"),
                ]),
                ("ei", "EI (Year-to-Date)", [
                    ("ei_premiums", "Box 18 - EI Premiums", "currency", "PAYSLIP_ITEM", "esi", "SUM_YTD"),
                ]),
                ("employer_contributions", "Employer Contributions (Year-to-Date, informational)", [
                    ("employer_cpp", "Employer CPP", "currency", "PAYSLIP_ITEM", "employer_social_security", "SUM_YTD"),
                    ("employer_cpp2", "Employer CPP2", "currency", "PAYSLIP_ITEM", "employer_cpp2", "SUM_YTD"),
                    ("employer_ei", "Employer EI", "currency", "PAYSLIP_ITEM", "employer_esi", "SUM_YTD"),
                ]),
            ],
        )
        # Box numbers above match CRA's published T4 layout at the time this
        # template was authored — re-verify against the current T4 guide
        # before relying on box numbers for anything beyond internal display.

        print("Seeding Quebec RL-1 (Relevé 1, per-employee)...")
        _seed_template(
            db, template_key="CA-QC-RL1", name="RL-1 - Releve de renseignements", report_type="RL1",
            country="CA", reporting_year="2026", document_scope="PER_EMPLOYEE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_bn", "Quebec Enterprise Number (NEQ)", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                ("employee_info", "Employee Information", [
                    ("employee_name", "Employee Name", "text", "PAYROLL_EMPLOYEE", "name", None),
                ]),
                ("earnings", "Earnings (Year-to-Date)", [
                    ("employment_income", "Employment Income", "currency", "PAYSLIP_ITEM", "gross_pay", "SUM_YTD"),
                ]),
                ("tax", "Tax (Year-to-Date)", [
                    ("quebec_income_tax", "Quebec Income Tax Withheld", "currency", "PAYSLIP_ITEM", "state_income_tax", "SUM_YTD"),
                ]),
                ("qpp_qpip", "QPP / QPIP (Year-to-Date)", [
                    ("qpp_contributions", "QPP Contributions", "currency", "PAYSLIP_ITEM", "social_security", "SUM_YTD"),
                    ("qpp2_contributions", "QPP2 Contributions", "currency", "PAYSLIP_ITEM", "cpp2", "SUM_YTD"),
                    ("qpip_premiums", "QPIP Premiums", "currency", "PAYSLIP_ITEM", "esi", "SUM_YTD"),
                ]),
            ],
        )
        # Field labels use descriptive names rather than asserting exact RL-1
        # box letters (A/B/E/etc.) — verify against Revenu Quebec's current
        # RL-1 form/guide before relying on box lettering specifically.

        print("Seeding Canada ROE (Record of Employment, per-employee, triggered by an interruption of earnings)...")
        _seed_template(
            db, template_key="CA-ROE", name="ROE - Record of Employment", report_type="ROE",
            country="CA", reporting_year="2026", document_scope="PER_EMPLOYEE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_bn", "Business Number (BN)", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                ("employee_info", "Employee Information", [
                    ("employee_name", "Employee Name", "text", "PAYROLL_EMPLOYEE", "name", None),
                ]),
                ("earnings", "Insurable Earnings (Year-to-Date, approximation)", [
                    ("insurable_earnings", "Insurable Earnings", "currency", "PAYSLIP_ITEM", "gross_pay", "SUM_YTD"),
                    ("ei_premiums_deducted", "EI Premiums Deducted", "currency", "PAYSLIP_ITEM", "esi", "SUM_YTD"),
                ]),
            ],
        )
        # Block 15C (insurable hours per pay period) is NOT populated — this
        # codebase has no insurable-hours accumulator wired to reports yet;
        # see generate_uk_employee_report's own docstring for this
        # disclosed limitation. The interruption/last-day-worked date is
        # captured generically as rendered_data.asOfDate, not a template field.

        print("Seeding Canada PD7A (Statement of Account for Current Source Deductions, aggregate/period)...")
        _seed_template(
            db, template_key="CA-PD7A", name="PD7A - Statement of Account for Current Source Deductions", report_type="PD7A",
            country="CA", reporting_year="2026", document_scope="AGGREGATE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_bn", "Business Number (BN)", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                ("remittance", "Remittance Totals (Period)", [
                    ("income_tax_withheld", "Income Tax Withheld", "currency", "PAYSLIP_ITEM", "tds", "SUM_RUN"),
                    ("cpp_employee", "CPP - Employee", "currency", "PAYSLIP_ITEM", "social_security", "SUM_RUN"),
                    ("cpp_employer", "CPP - Employer", "currency", "PAYSLIP_ITEM", "employer_social_security", "SUM_RUN"),
                    ("cpp2_employee", "CPP2 - Employee", "currency", "PAYSLIP_ITEM", "cpp2", "SUM_RUN"),
                    ("cpp2_employer", "CPP2 - Employer", "currency", "PAYSLIP_ITEM", "employer_cpp2", "SUM_RUN"),
                    ("ei_employee", "EI - Employee", "currency", "PAYSLIP_ITEM", "esi", "SUM_RUN"),
                    ("ei_employer", "EI - Employer", "currency", "PAYSLIP_ITEM", "employer_esi", "SUM_RUN"),
                ]),
            ],
        )
        # PD7A's own SUM_RUN fields are reinterpreted by generate_ca_pd7a as
        # "sum across every finalized CA payslip in the given date range,"
        # the same cross-run reinterpretation Form 138 uses for SUM_RUN
        # above — service.py's own docstring explains why. totalRemittance
        # (the actual amount owed) is computed directly in that function,
        # not as a mapped field, since it's a sum-of-sums no single
        # PayslipItem column represents.

        print("\nDone. All templates are in Draft status — a Super Admin still needs to review, Approve, Publish, and Activate each one before Organizations can generate against it.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
