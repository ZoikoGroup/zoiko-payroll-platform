"""
scripts/seed_statutory_report_templates.py
--------------------------------------------
Seeds concrete, named Report Templates for the statutory forms explicitly
named in the India/UK configuration packs (Form 130 TDS certificate, Form
138 quarterly TDS statement + its Q1-Q4 filing calendar, UK P60, and a UK
EPS/FPS-style employer summary) — Phase 3 of the Report Template system.
Later additions: Canada (T4/RL-1/ROE/PD7A), US (W-2/941/940), Australia
(STP/SuperStream/8 state payroll-tax returns), and Germany (DE-LSTB
Lohnsteuerbescheinigung + DE-PAYROLL-SUMMARY aggregate).

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
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.modules.payroll import service
from app.modules.payroll.engine.jurisdictions.singapore import statutory_summary as sg_catalog
from app.modules.payroll.models import ReportTemplate
from app.modules.payroll.schemas import (
    ReportTemplateUpsert, ReportTemplateComponentUpsert, ReportTemplateFieldUpsert, FilingCalendarUpsert,
)


def _seed_template(db, *, template_key, name, report_type, country, reporting_year, document_scope, components, state=None,
                   description=None, regulatory_authority=None, effective_from=None, source_references=None):
    """`components` = [(component_key, label, [(field_key, label, field_type, data_source_kind, source_column, aggregation), ...])]

    Genuinely idempotent (matching this module's own docstring, which
    upsert_report_template alone does NOT guarantee): once a real Super
    Admin has moved a previously-seeded template past Draft/Review/
    Approved in production, upsert_report_template's own editability
    guard correctly refuses to silently rewrite it in place — but that
    means a straight re-run of this whole script would crash on the
    FIRST such promoted template and never reach any jurisdiction seeded
    after it. Checked here via the exact same (template_key, version)
    natural-key lookup upsert_report_template itself uses, so an
    already-promoted row is skipped with a clear message instead of
    raising — no template is ever edited in place either way; a
    genuinely new version still upserts normally.

    Review/Approved are skipped too (Phase 5.6): upserting them passes
    status="Draft" and approvedById=None, which silently demoted a
    reviewed template and cleared its approver on every re-run. Only a
    template still in Draft is refreshed from this script.
    """
    existing = (
        db.query(ReportTemplate)
        .filter(ReportTemplate.template_key == template_key, ReportTemplate.version == "1.0")
        .first()
    )
    if existing is not None and existing.status != "Draft":
        print(f"  SKIP {template_key} v{existing.version} — already {existing.status} (id={existing.id}); not re-seeding.")
        return existing

    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=template_key, name=name, reportType=report_type,
            jurisdictionCountry=country, jurisdictionState=state, reportingYear=reporting_year, documentScope=document_scope,
            changeSummary="Seeded via scripts/seed_statutory_report_templates.py",
            description=description, regulatoryAuthority=regulatory_authority, effectiveFrom=effective_from,
            sourceReferences=source_references,
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

        print("Seeding US W-2 (Wage and Tax Statement, per-employee, calendar year)...")
        _seed_template(
            db, template_key="US-W2", name="W-2 - Wage and Tax Statement", report_type="W2",
            country="US", reporting_year="2026", document_scope="PER_EMPLOYEE",
            components=[
                ("employer_info", "Employer Information (Box b/c)", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_ein", "Employer Identification Number (EIN)", "text", "EMPLOYER_PROFILE", "employer_id", None),
                    ("employer_address", "Employer Address", "text", "EMPLOYER_PROFILE", "address", None),
                ]),
                ("employee_info", "Employee Information (Box a/e/f)", [
                    ("employee_name", "Employee Name", "text", "PAYROLL_EMPLOYEE", "name", None),
                ]),
                ("wages", "Wages & Federal Tax (Box 1-2)", [
                    ("box1_wages", "Box 1 - Wages, Tips, Other Compensation", "currency", "PAYSLIP_ITEM", "gross_pay", "SUM_YTD"),
                    ("box2_federal_tax", "Box 2 - Federal Income Tax Withheld", "currency", "PAYSLIP_ITEM", "federal_income_tax", "SUM_YTD"),
                ]),
                ("ss_medicare", "Social Security & Medicare (Box 3-6)", [
                    ("box3_ss_wages", "Box 3 - Social Security Wages (wage-base capped)", "currency", "PAYSLIP_ITEM", "gross_pay", "SUM_YTD"),
                    ("box4_ss_tax", "Box 4 - Social Security Tax Withheld", "currency", "PAYSLIP_ITEM", "social_security", "SUM_YTD"),
                    ("box5_medicare_wages", "Box 5 - Medicare Wages and Tips", "currency", "PAYSLIP_ITEM", "gross_pay", "SUM_YTD"),
                    ("box6_medicare_tax", "Box 6 - Medicare Tax Withheld", "currency", "PAYSLIP_ITEM", "medicare", "SUM_YTD"),
                ]),
                ("state_local", "State & Local (Box 14-20)", [
                    ("box14_sdi", "Box 14 - State Disability Insurance", "currency", "PAYSLIP_ITEM", "state_disability_insurance", "SUM_YTD"),
                    ("box14_state_program", "Box 14 - State Payroll Programs (e.g. Paid Leave/TDI)", "currency", "PAYSLIP_ITEM", "state_program_deductions", "SUM_YTD"),
                    ("box16_state_wages", "Box 16 - State Wages, Tips, etc.", "currency", "PAYSLIP_ITEM", "gross_pay", "SUM_YTD"),
                    ("box17_state_tax", "Box 17 - State Income Tax", "currency", "PAYSLIP_ITEM", "state_income_tax", "SUM_YTD"),
                    ("box18_local_wages", "Box 18 - Local Wages, Tips, etc.", "currency", "PAYSLIP_ITEM", "gross_pay", "SUM_YTD"),
                    ("box19_local_tax", "Box 19 - Local Income Tax", "currency", "PAYSLIP_ITEM", "local_tax", "SUM_YTD"),
                ]),
            ],
        )
        # These field/component rows are DOCUMENTATION of the template's
        # real box structure for the Super Admin UI — actual generation
        # (service.generate_us_w2) computes every box directly from real
        # PayslipItem rows with bespoke logic these generic SUM_YTD/
        # source_column mappings cannot express on their own (Box 3's
        # Social Security wage-base cap, and Box 15-17/18-20 as genuinely
        # repeatable per-state/per-locality groups when an employee worked
        # in more than one jurisdiction during the year) — see that
        # function's own docstring for the full list of disclosed
        # simplifications (no Box 12/13, no employee address on Box f, no
        # US pre-tax deduction modeling reducing Box 1/3/5/16/18 below
        # gross pay).

        print("Seeding US Form 941 (Employer's Quarterly Federal Tax Return, aggregate/quarterly)...")
        _seed_template(
            db, template_key="US-941", name="Form 941 - Employer's Quarterly Federal Tax Return", report_type="941",
            country="US", reporting_year="2026", document_scope="AGGREGATE",
            components=[
                ("employer_info", "Employer Information (Line 1 area)", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_ein", "Employer Identification Number (EIN)", "text", "EMPLOYER_PROFILE", "employer_id", None),
                    ("line1_employee_count", "Line 1 - Number of Employees", "number", "PAYSLIP_ITEM", "gross_pay", None),  # placeholder — value is bespoke-computed, not mapped
                ]),
                ("wages_tax", "Wages & Federal Tax (Line 2-3)", [
                    ("line2_wages", "Line 2 - Wages, Tips, Other Compensation", "currency", "PAYSLIP_ITEM", "gross_pay", "SUM_RUN"),
                    ("line3_federal_tax_withheld", "Line 3 - Federal Income Tax Withheld", "currency", "PAYSLIP_ITEM", "federal_income_tax", "SUM_RUN"),
                ]),
                ("ss_medicare", "Social Security & Medicare (Line 5a/5c)", [
                    ("line5a_ss_wages", "Line 5a - Taxable Social Security Wages (col. 1)", "currency", "PAYSLIP_ITEM", "social_security", "SUM_RUN"),
                    ("line5a_ss_tax", "Line 5a - Social Security Tax (col. 2, both shares)", "currency", "PAYSLIP_ITEM", "social_security", "SUM_RUN"),
                    ("line5c_medicare_wages", "Line 5c - Taxable Medicare Wages (col. 1)", "currency", "PAYSLIP_ITEM", "gross_pay", "SUM_RUN"),
                    ("line5c_medicare_tax", "Line 5c - Medicare Tax (col. 2, both shares, incl. Additional)", "currency", "PAYSLIP_ITEM", "medicare", "SUM_RUN"),
                ]),
                ("totals", "Totals (Line 6/12)", [
                    ("line6_total_taxes_before_adjustments", "Line 6 - Total Taxes Before Adjustments", "currency", "PAYSLIP_ITEM", "tds", "SUM_RUN"),
                    ("line12_total_taxes_after_adjustments_and_credits", "Line 12 - Total Taxes After Adjustments and Credits", "currency", "PAYSLIP_ITEM", "tds", "SUM_RUN"),
                ]),
            ],
        )
        # As with W-2, these rows document the template's real box
        # structure for the Super Admin UI — actual generation
        # (service.generate_us_941) computes every box with bespoke logic
        # (Line 5a's wage figure is derived from the tax actually
        # withheld, not re-summed/re-capped) — see that function's own
        # docstring for the full list of disclosed simplifications (Lines
        # 5c/5d combined, no Line 13 deposits total, no adjustments/
        # credits modeled).

        print("Seeding US Form 940 (Employer's Annual FUTA Tax Return, aggregate/annual)...")
        _seed_template(
            db, template_key="US-940", name="Form 940 - Employer's Annual Federal Unemployment (FUTA) Tax Return", report_type="940",
            country="US", reporting_year="2026", document_scope="AGGREGATE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_ein", "Employer Identification Number (EIN)", "text", "EMPLOYER_PROFILE", "employer_id", None),
                ]),
                ("futa", "FUTA Wages & Tax", [
                    ("total_payments", "Total Payments to All Employees", "currency", "PAYSLIP_ITEM", "gross_pay", "SUM_RUN"),
                    ("futa_taxable_wages", "Total Taxable FUTA Wages ($7,000/employee cap)", "currency", "PAYSLIP_ITEM", "employer_futa", "SUM_RUN"),
                    ("futa_tax_due", "FUTA Tax (before deposits)", "currency", "PAYSLIP_ITEM", "employer_futa", "SUM_RUN"),
                    ("employee_count", "Number of Employees Paid", "number", "PAYSLIP_ITEM", "gross_pay", None),  # placeholder — value is bespoke-computed, not mapped
                ]),
            ],
        )
        # Same documentation-only reasoning — service.generate_us_940
        # independently recomputes the real $7,000/employee/year FUTA wage
        # base cap (not derived from tax, since the effective rate can
        # vary by state/config) rather than a plain SUM_RUN of these
        # mapped source_columns. See that function's own docstring.

        print("Seeding Australia STP (Single Touch Payroll) pay-event submission, aggregate...")
        _seed_template(
            db, template_key="AU-STP", name="Single Touch Payroll (STP) Pay Event", report_type="STP",
            country="AU", reporting_year="2026-27", document_scope="AGGREGATE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_abn", "Australian Business Number (ABN)", "text", "EMPLOYER_PROFILE", "employer_id", None),
                ]),
                ("employee_info", "Employee Information", [
                    ("employee_name", "Employee Name", "text", "PAYSLIP_ITEM", "employee_name", None),
                ]),
                ("earnings", "Earnings", [
                    ("gross_pay", "Gross Pay", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ]),
                ("payg", "PAYG Withholding", [
                    ("payg_withholding", "PAYG Withholding (Schedule 1 + STSL)", "currency", "PAYSLIP_ITEM", "tds", None),
                    ("stsl_component", "Study and Training Support Loan Component", "currency", "PAYSLIP_ITEM", "study_loan_deduction", None),
                ]),
                ("super", "Superannuation", [
                    ("sg_amount", "Superannuation Guarantee (this payday)", "currency", "PAYSLIP_ITEM", "employer_pension", None),
                ]),
                ("ytd", "Year-to-Date", [
                    ("payg_withholding_ytd", "PAYG Withholding (Year-to-Date)", "currency", "PAYSLIP_ITEM", "tds", "SUM_YTD"),
                    ("sg_amount_ytd", "Superannuation Guarantee (Year-to-Date)", "currency", "PAYSLIP_ITEM", "employer_pension", "SUM_YTD"),
                ]),
            ],
        )
        # DISCLOSED SCOPE LIMITATION (Phase 9, 2026-09-17): qualifying
        # earnings (PayrollResult.sg_qualifying_earnings_period) is NOT
        # mapped above — it is an ephemeral engine-calculation field, not
        # a persisted PayslipItem column, so PAYSLIP_ITEM source_column
        # mapping cannot reach it (see models.PayslipItem's own
        # calculation-trace disclosure). The 8 states' payroll-tax
        # periodic/annual return reports are still open — this seed only
        # covers the STP pay-event submission and the SuperStream
        # contribution message (below).

        print("Seeding Australia SuperStream contribution message, aggregate (bespoke generator)...")
        # No components/fields registered — service.generate_au_
        # superstream_report is a bespoke generator (same reasoning as
        # generate_uk_eps) that reads SuperGuaranteeLiability directly,
        # never the generic ReportTemplateComponentField mapping. This
        # template row exists purely to carry status/version/lifecycle —
        # the same minimal-template pattern EPS's own declaration fields
        # already established for data the field-mapper can't reach.
        _seed_template(
            db, template_key="AU-SUPERSTREAM", name="SuperStream Contribution Message", report_type="SUPERSTREAM",
            country="AU", reporting_year="2026-27", document_scope="AGGREGATE", components=[],
        )

        print("Seeding Australia state/territory payroll-tax returns, one per jurisdiction (bespoke generator)...")
        # No components/fields registered — service.generate_au_state_
        # payroll_tax_return is a bespoke generator (same reasoning as
        # SuperStream above) that sums PayslipItem.employer_payroll_tax
        # directly, never the generic field-mapper. One template row per
        # state, matching the document's own AU-NSW-2026-27/AU-VIC-2026-
        # 27/... package-per-state model (§3) — jurisdiction_state scopes
        # generate_au_state_payroll_tax_return to exactly that state.
        for state_code, state_name in [
            ("NSW", "New South Wales"), ("VIC", "Victoria"), ("QLD", "Queensland"), ("WA", "Western Australia"),
            ("SA", "South Australia"), ("TAS", "Tasmania"), ("ACT", "Australian Capital Territory"), ("NT", "Northern Territory"),
        ]:
            _seed_template(
                db, template_key=f"AU-PAYROLL-TAX-{state_code}", name=f"{state_name} Payroll Tax Return",
                report_type="AU_PAYROLL_TAX_RETURN", country="AU", state=state_code,
                reporting_year="2026-27", document_scope="AGGREGATE", components=[],
            )

        # Caribbean 7 (2026-09-22, Group D gap-closure) — one PER_EMPLOYEE
        # itemized statutory pay-component statement per country, all via
        # the generic field mapper (straight PayslipItem columns for this
        # one committed run, no cross-run aggregation and no bespoke
        # generator). Deliberately NOT the literal government e-filing
        # artifact (TAMIS/GRA Form 5/C10/DGII IR-3/NIBTT upload) — those
        # need real external file schemas the specs themselves say
        # aren't acquired yet. All calendar-year countries, so
        # reporting_year="2026" (matching the US/CA convention above,
        # not AU/IN's fiscal-year "2026-27").

        print("Seeding Barbados PAYE + NIS/R&R statement, per-employee...")
        _seed_template(
            db, template_key="BB-PAYE-NIS", name="PAYE + NIS/R&R Statement", report_type="BB_PAYE_NIS",
            country="BB", reporting_year="2026", document_scope="PER_EMPLOYEE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_tamis_tin", "TAMIS TIN", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                ("employee_info", "Employee Information", [
                    ("employee_name", "Employee Name", "text", "PAYSLIP_ITEM", "employee_name", None),
                ]),
                ("earnings", "Earnings", [
                    ("gross_pay", "Gross Pay", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ]),
                ("tax", "PAYE", [
                    ("tds", "PAYE", "currency", "PAYSLIP_ITEM", "tds", None),
                ]),
                ("contributions", "NIS / R&R (Employee)", [
                    ("social_security", "NIS (Employee, Code R)", "currency", "PAYSLIP_ITEM", "social_security", None),
                    ("employee_pension", "Resilience & Regeneration Levy (Employee)", "currency", "PAYSLIP_ITEM", "employee_pension", None),
                ]),
                ("employer_contributions", "NIS / R&R (Employer)", [
                    ("employer_social_security", "NIS (Employer, Code R)", "currency", "PAYSLIP_ITEM", "employer_social_security", None),
                    ("employer_pension", "Resilience & Regeneration Levy (Employer)", "currency", "PAYSLIP_ITEM", "employer_pension", None),
                ]),
            ],
        )

        print("Seeding Barbados TAMIS Monthly PAYE return, employer-wide (real per-employee rows computed by generate_bb_tamis_monthly_paye)...")
        _seed_template(
            db, template_key="BB-TAMIS-MONTHLY-PAYE", name="TAMIS Monthly PAYE Return", report_type="BB_TAMIS_MONTHLY_PAYE",
            country="BB", reporting_year="2026", document_scope="AGGREGATE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_tamis_tin", "TAMIS TIN", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                # source_column below is a real-column placeholder only (schema requires
                # one) — actual values are bespoke-computed by generate_bb_tamis_monthly_paye,
                # same convention as US-941's own line1_employee_count field.
                ("totals", "Employer Totals (PAYE / NIS / R&R Levy)", [
                    ("total_employee_count", "Employee Count", "number", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_remuneration", "Total Remuneration", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_paye_tax_deducted", "Total PAYE Tax Deducted", "currency", "PAYSLIP_ITEM", "tds", None),
                    ("total_nis_employee", "Total NIS (Employee)", "currency", "PAYSLIP_ITEM", "social_security", None),
                    ("total_nis_employer", "Total NIS (Employer)", "currency", "PAYSLIP_ITEM", "employer_social_security", None),
                    ("total_rr_levy_employee", "Total R&R Levy (Employee)", "currency", "PAYSLIP_ITEM", "employee_pension", None),
                    ("total_rr_levy_employer", "Total R&R Levy (Employer)", "currency", "PAYSLIP_ITEM", "employer_pension", None),
                ]),
            ],
        )

        print("Seeding Barbados NIS Earnings Schedule, employer-wide (real per-employee rows computed by generate_bb_nis_earnings_schedule)...")
        _seed_template(
            db, template_key="BB-NIS-EARNINGS-SCHEDULE", name="NIS Earnings Schedule", report_type="BB_NIS_EARNINGS_SCHEDULE",
            country="BB", reporting_year="2026", document_scope="AGGREGATE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                ]),
                ("totals", "Employer Totals (Insurable Earnings / NIS)", [
                    ("total_employee_count", "Employee Count", "number", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_insurable_earnings", "Total Insurable Earnings", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_nis_employee", "Total NIS (Employee)", "currency", "PAYSLIP_ITEM", "social_security", None),
                    ("total_nis_employer", "Total NIS (Employer)", "currency", "PAYSLIP_ITEM", "employer_social_security", None),
                ]),
            ],
        )

        print("Seeding Cayman Islands pension statement, per-employee (no personal income tax)...")
        _seed_template(
            db, template_key="KY-PENSION", name="Mandatory Pension Statement", report_type="KY_PENSION_STATEMENT",
            country="KY", reporting_year="2026", document_scope="PER_EMPLOYEE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                ]),
                ("employee_info", "Employee Information", [
                    ("employee_name", "Employee Name", "text", "PAYSLIP_ITEM", "employee_name", None),
                ]),
                ("earnings", "Earnings", [
                    ("gross_pay", "Gross Pay", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ]),
                ("contributions", "Mandatory Pension (Employee)", [
                    ("employee_pension", "Mandatory Pension (Employee)", "currency", "PAYSLIP_ITEM", "employee_pension", None),
                ]),
                ("employer_contributions", "Mandatory Pension (Employer)", [
                    ("employer_pension", "Mandatory Pension (Employer)", "currency", "PAYSLIP_ITEM", "employer_pension", None),
                ]),
            ],
        )

        print("Seeding Cayman Islands Wage/Gratuity Statement, per-employee, per-run (generic mapper — gratuity itself not populated, no gratuity/tip figure is computed anywhere in cayman_islands.py)...")
        _seed_template(
            db, template_key="KY-WAGE-GRATUITY", name="Wage / Gratuity Statement", report_type="KY_WAGE_GRATUITY_STATEMENT",
            country="KY", reporting_year="2026", document_scope="PER_EMPLOYEE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                ]),
                ("employee_info", "Employee Information", [
                    ("employee_name", "Employee Name", "text", "PAYSLIP_ITEM", "employee_name", None),
                ]),
                ("earnings", "Wages", [
                    ("gross_pay", "Gross Pay", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ]),
                ("contributions", "Mandatory Pension (Employee)", [
                    ("employee_pension", "Mandatory Pension (Employee)", "currency", "PAYSLIP_ITEM", "employee_pension", None),
                ]),
                ("employer_contributions", "Mandatory Pension (Employer)", [
                    ("employer_pension", "Mandatory Pension (Employer)", "currency", "PAYSLIP_ITEM", "employer_pension", None),
                ]),
            ],
        )

        print("Seeding Cayman Islands monthly Pension contribution submission, employer-wide (real per-employee rows computed by generate_ky_pension_submission)...")
        _seed_template(
            db, template_key="KY-PENSION-SUBMISSION", name="Monthly Pension Contribution Submission", report_type="KY_PENSION_SUBMISSION",
            country="KY", reporting_year="2026", document_scope="AGGREGATE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                ]),
                # source_column below is a real-column placeholder only (schema requires
                # one) — actual values are bespoke-computed by generate_ky_pension_submission,
                # same convention as US-941's own line1_employee_count field.
                ("totals", "Employer Totals (Pensionable Earnings / Pension)", [
                    ("total_employee_count", "Employee Count", "number", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_pensionable_earnings", "Total Pensionable Earnings", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_pension_employee", "Total Pension (Employee)", "currency", "PAYSLIP_ITEM", "employee_pension", None),
                    ("total_pension_employer", "Total Pension (Employer)", "currency", "PAYSLIP_ITEM", "employer_pension", None),
                ]),
            ],
        )

        print("Seeding Dominican Republic payroll statement, per-employee...")
        _seed_template(
            db, template_key="DO-PAYROLL", name="ISR + SFS/SVDS/SRL/INFOTEP Statement", report_type="DO_PAYROLL_STATEMENT",
            country="DO", reporting_year="2026", document_scope="PER_EMPLOYEE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_rnc", "RNC", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                ("employee_info", "Employee Information", [
                    ("employee_name", "Employee Name", "text", "PAYSLIP_ITEM", "employee_name", None),
                ]),
                ("earnings", "Earnings", [
                    ("gross_pay", "Gross Pay", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ]),
                ("tax", "ISR", [
                    ("tds", "ISR", "currency", "PAYSLIP_ITEM", "tds", None),
                ]),
                ("contributions", "SFS / Pensión (Employee)", [
                    ("social_security", "SFS (Employee)", "currency", "PAYSLIP_ITEM", "social_security", None),
                    ("employee_pension", "Pensión / SVDS (Employee)", "currency", "PAYSLIP_ITEM", "employee_pension", None),
                ]),
                ("employer_contributions", "SFS / Pensión / SRL / INFOTEP (Employer)", [
                    ("employer_social_security", "SFS (Employer)", "currency", "PAYSLIP_ITEM", "employer_social_security", None),
                    ("employer_pension", "Pensión / SVDS (Employer)", "currency", "PAYSLIP_ITEM", "employer_pension", None),
                    ("employer_payroll_tax", "Seguro de Riesgos Laborales — SRL (Employer)", "currency", "PAYSLIP_ITEM", "employer_payroll_tax", None),
                    ("employer_ni", "INFOTEP (Employer)", "currency", "PAYSLIP_ITEM", "employer_ni", None),
                ]),
            ],
        )

        print("Seeding Dominican Republic DGII IR-3 monthly withholding declaration, employer-wide (real per-employee rows computed by generate_do_ir3)...")
        _seed_template(
            db, template_key="DO-IR3", name="DGII IR-3 — Monthly Withholding Declaration", report_type="DO_IR3",
            country="DO", reporting_year="2026", document_scope="AGGREGATE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_rnc", "RNC", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                # source_column below is a real-column placeholder only (schema requires
                # one) — actual values are bespoke-computed by generate_do_ir3, same
                # convention as US-941's own line1_employee_count field.
                ("totals", "Employer Totals (Gross Pay / ISR)", [
                    ("total_employee_count", "Employee Count", "number", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_gross_pay", "Total Gross Pay", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_isr_withheld", "Total ISR Withheld", "currency", "PAYSLIP_ITEM", "tds", None),
                ]),
            ],
        )

        print("Seeding Dominican Republic TSS/SUIR contribution submission, employer-wide (real per-employee rows computed by generate_do_tss_suir)...")
        _seed_template(
            db, template_key="DO-TSS-SUIR", name="TSS/SUIR Contribution Submission", report_type="DO_TSS_SUIR",
            country="DO", reporting_year="2026", document_scope="AGGREGATE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_rnc", "RNC", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                ("totals", "Employer Totals (SFS / Pensión / SRL / INFOTEP)", [
                    ("total_employee_count", "Employee Count", "number", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_gross_pay", "Total Gross Pay", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_sfs_employee", "Total SFS (Employee)", "currency", "PAYSLIP_ITEM", "social_security", None),
                    ("total_sfs_employer", "Total SFS (Employer)", "currency", "PAYSLIP_ITEM", "employer_social_security", None),
                    ("total_pension_employee", "Total Pensión / SVDS (Employee)", "currency", "PAYSLIP_ITEM", "employee_pension", None),
                    ("total_pension_employer", "Total Pensión / SVDS (Employer)", "currency", "PAYSLIP_ITEM", "employer_pension", None),
                    ("total_srl_employer", "Total SRL (Employer)", "currency", "PAYSLIP_ITEM", "employer_payroll_tax", None),
                    ("total_infotep_employer", "Total INFOTEP (Employer)", "currency", "PAYSLIP_ITEM", "employer_ni", None),
                ]),
            ],
        )

        print("Seeding Dominican Republic DGII IR-13 annual withholding declaration, per-employee...")
        _seed_template(
            db, template_key="DO-IR13", name="DGII IR-13 — Annual Withholding Declaration", report_type="IR13",
            country="DO", reporting_year="2026", document_scope="PER_EMPLOYEE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_rnc", "RNC", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                ("employee_info", "Employee Information", [
                    ("employee_name", "Employee Name", "text", "PAYROLL_EMPLOYEE", "name", None),
                ]),
                ("earnings", "Earnings (Year-to-Date)", [
                    ("gross_pay_ytd", "Total Gross Pay (YTD)", "currency", "PAYSLIP_ITEM", "gross_pay", "SUM_YTD"),
                ]),
                ("tax", "ISR (Year-to-Date)", [
                    ("tds_ytd", "ISR Withheld (YTD)", "currency", "PAYSLIP_ITEM", "tds", "SUM_YTD"),
                ]),
            ],
        )

        print("Seeding Guyana PAYE + NIS statement, per-employee...")
        _seed_template(
            db, template_key="GY-PAYE-NIS", name="PAYE + NIS Statement", report_type="GY_PAYE_NIS",
            country="GY", reporting_year="2026", document_scope="PER_EMPLOYEE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_gra_tin", "GRA TIN", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                ("employee_info", "Employee Information", [
                    ("employee_name", "Employee Name", "text", "PAYSLIP_ITEM", "employee_name", None),
                ]),
                ("earnings", "Earnings", [
                    ("gross_pay", "Gross Pay", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ]),
                ("tax", "PAYE", [
                    ("tds", "PAYE", "currency", "PAYSLIP_ITEM", "tds", None),
                ]),
                ("contributions", "NIS (Employee)", [
                    ("social_security", "NIS (Employee)", "currency", "PAYSLIP_ITEM", "social_security", None),
                ]),
                ("employer_contributions", "NIS (Employer)", [
                    ("employer_social_security", "NIS (Employer)", "currency", "PAYSLIP_ITEM", "employer_social_security", None),
                ]),
            ],
        )

        print("Seeding Germany Lohnsteuerbescheinigung (annual wage tax certificate, per-employee)...")
        # Uses PAYROLL_EMPLOYEE for employee_name/steuer_id/iban (not
        # PAYSLIP_ITEM) — same reason as Canada T4/RL1/ROE and US W-2
        # above: this is a non-run-based, generate_uk_employee_report
        # document (see that function's own docstring — the "employee_
        # name" PAYSLIP_ITEM field only resolves inside an actual
        # PayrollRun context). "tax" lists Lohnsteuer/Soli/Kirchensteuer
        # as three separately-persisted PayslipItem columns (tds/soli/
        # church_tax) rather than one folded figure — the real form
        # prints them as distinct lines. The "ytd" component carries the
        # real annual totals a wage-tax certificate is actually about;
        # "earnings"/"tax"/"contributions" mirror UK P60's own convention
        # of also showing the final period's own (non-aggregated) figures.
        _seed_template(
            db, template_key="DE-LSTB", name="Lohnsteuerbescheinigung - Annual Wage Tax Certificate", report_type="LSTB",
            country="DE", reporting_year="2026", document_scope="PER_EMPLOYEE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_tax_no", "Betriebsnummer / Steuernummer", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                ("employee_info", "Employee Information", [
                    ("employee_name", "Employee Name", "text", "PAYROLL_EMPLOYEE", "name", None),
                    ("employee_steuer_id", "Tax ID (Steuer-ID)", "text", "PAYROLL_EMPLOYEE", "steuer_id", None),
                    ("employee_iban", "IBAN", "text", "PAYROLL_EMPLOYEE", "iban", None),
                ]),
                ("earnings", "Earnings", [
                    ("gross_pay", "Total Pay (Final Period)", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ]),
                ("tax", "Wage Tax (Lohnsteuer / Soli / Kirchensteuer)", [
                    # `tds` is persisted as Lohnsteuer + Solidaritätszuschlag combined
                    # (see engine/countries/germany.py's monthly tds derivation) — there
                    # is no separate pure-Lohnsteuer PayslipItem column. Labeled to match
                    # what the value actually is, not "Lohnsteuer" alone, so a reader who
                    # also sees the separate "Solidaritätszuschlag" field below cannot
                    # double-count Soli by summing the two.
                    ("lohnsteuer", "Lohnsteuer + Solidaritätszuschlag", "currency", "PAYSLIP_ITEM", "tds", None),
                    ("soli", "Solidaritätszuschlag", "currency", "PAYSLIP_ITEM", "soli", None),
                    ("church_tax", "Kirchensteuer", "currency", "PAYSLIP_ITEM", "church_tax", None),
                ]),
                ("contributions", "Social Insurance", [
                    ("pf", "Pension Insurance (Rentenversicherung, Employee)", "currency", "PAYSLIP_ITEM", "pf", None),
                    ("esi", "Health / Unemployment / Care Insurance (Employee)", "currency", "PAYSLIP_ITEM", "esi", None),
                ]),
                ("employer_contributions", "Employer Contributions", [
                    ("employer_pf", "Pension Insurance (Employer)", "currency", "PAYSLIP_ITEM", "employer_pf", None),
                    ("employer_esi", "Health / Unemployment / Care Insurance (Employer)", "currency", "PAYSLIP_ITEM", "employer_esi", None),
                ]),
                ("ytd", "Year-to-Date", [
                    ("gross_pay_ytd", "Total Pay (Year-to-Date)", "currency", "PAYSLIP_ITEM", "gross_pay", "SUM_YTD"),
                    ("lohnsteuer_ytd", "Lohnsteuer + Solidaritätszuschlag (Year-to-Date)", "currency", "PAYSLIP_ITEM", "tds", "SUM_YTD"),
                    ("soli_ytd", "Solidaritätszuschlag (Year-to-Date)", "currency", "PAYSLIP_ITEM", "soli", "SUM_YTD"),
                    ("church_tax_ytd", "Kirchensteuer (Year-to-Date)", "currency", "PAYSLIP_ITEM", "church_tax", "SUM_YTD"),
                ]),
            ],
        )

        print("Seeding Guyana GRA Form 5 monthly PAYE return, employer-wide (real per-employee rows computed by generate_gy_form_5)...")
        _seed_template(
            db, template_key="GY-FORM-5", name="GRA Form 5 — Monthly PAYE Return", report_type="GY_FORM_5",
            country="GY", reporting_year="2026", document_scope="AGGREGATE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_gra_tin", "GRA TIN", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                # source_column below is a real-column placeholder only (schema requires
                # one) — actual values are bespoke-computed by generate_gy_form_5, same
                # convention as US-941's own line1_employee_count field above.
                ("totals", "Employer Totals (PAYE / NIS)", [
                    ("total_employee_count", "Employee Count", "number", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_salary_wages", "Total Salary / Wages", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_paye_tax_deducted", "Total PAYE Tax Deducted", "currency", "PAYSLIP_ITEM", "tds", None),
                    ("total_nis_employee", "Total NIS (Employee)", "currency", "PAYSLIP_ITEM", "social_security", None),
                    ("total_nis_employer", "Total NIS (Employer)", "currency", "PAYSLIP_ITEM", "employer_social_security", None),
                ]),
            ],
        )

        print("Seeding Guyana NIS Electronic Schedule, employer-wide (real per-employee rows computed by generate_gy_nis_schedule)...")
        _seed_template(
            db, template_key="GY-NIS-SCHEDULE", name="NIS Electronic Schedule", report_type="GY_NIS_SCHEDULE",
            country="GY", reporting_year="2026", document_scope="AGGREGATE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                ]),
                # source_column below is a real-column placeholder only (schema requires
                # one) — actual values are bespoke-computed by generate_gy_nis_schedule.
                ("totals", "Employer Totals (Insurable Earnings / NIS)", [
                    ("total_employee_count", "Employee Count", "number", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_insurable_earnings", "Total Insurable Earnings", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_nis_employee", "Total NIS (Employee)", "currency", "PAYSLIP_ITEM", "social_security", None),
                    ("total_nis_employer", "Total NIS (Employer)", "currency", "PAYSLIP_ITEM", "employer_social_security", None),
                ]),
            ],
        )

        print("Seeding Guyana Form 7B annual employee earnings statement, per-employee...")
        _seed_template(
            db, template_key="GY-FORM-7B", name="Form 7B — Annual Employee Earnings Statement", report_type="FORM_7B",
            country="GY", reporting_year="2026", document_scope="PER_EMPLOYEE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_gra_tin", "GRA TIN", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                ("employee_info", "Employee Information", [
                    ("employee_name", "Employee Name", "text", "PAYROLL_EMPLOYEE", "name", None),
                ]),
                ("earnings", "Earnings (Year-to-Date)", [
                    ("gross_pay_ytd", "Total Salary / Wages (YTD)", "currency", "PAYSLIP_ITEM", "gross_pay", "SUM_YTD"),
                ]),
                ("tax", "PAYE (Year-to-Date)", [
                    ("tds_ytd", "PAYE Tax Deducted (YTD)", "currency", "PAYSLIP_ITEM", "tds", "SUM_YTD"),
                ]),
                ("contributions", "NIS (Year-to-Date)", [
                    ("nis_employee_ytd", "NIS Employee (YTD)", "currency", "PAYSLIP_ITEM", "social_security", "SUM_YTD"),
                ]),
            ],
        )

        print("Seeding Jamaica payroll statement (PAYE/NIS/NHT/Education Tax/HEART), per-employee...")
        _seed_template(
            db, template_key="JM-PAYROLL", name="PAYE + NIS/NHT/Education Tax Statement", report_type="JM_PAYROLL_STATEMENT",
            country="JM", reporting_year="2026", document_scope="PER_EMPLOYEE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                ]),
                ("employee_info", "Employee Information", [
                    ("employee_name", "Employee Name", "text", "PAYSLIP_ITEM", "employee_name", None),
                ]),
                ("earnings", "Earnings", [
                    ("gross_pay", "Gross Pay", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ]),
                ("tax", "PAYE / Education Tax", [
                    ("tds", "PAYE", "currency", "PAYSLIP_ITEM", "tds", None),
                    ("ni_employee", "Education Tax (Employee)", "currency", "PAYSLIP_ITEM", "ni_employee", None),
                ]),
                ("contributions", "NIS / NHT (Employee)", [
                    ("social_security", "NIS (Employee)", "currency", "PAYSLIP_ITEM", "social_security", None),
                    ("employee_pension", "NHT (Employee)", "currency", "PAYSLIP_ITEM", "employee_pension", None),
                ]),
                ("employer_contributions", "NIS / NHT / HEART (Employer)", [
                    ("employer_social_security", "NIS (Employer)", "currency", "PAYSLIP_ITEM", "employer_social_security", None),
                    ("employer_pension", "NHT (Employer)", "currency", "PAYSLIP_ITEM", "employer_pension", None),
                    ("employer_ni", "Education Tax (Employer)", "currency", "PAYSLIP_ITEM", "employer_ni", None),
                    ("employer_payroll_tax", "HEART (Employer)", "currency", "PAYSLIP_ITEM", "employer_payroll_tax", None),
                ]),
            ],
        )

        print("Seeding Jamaica S01 monthly PAYE/NIS/NHT/Education Tax/HEART return, employer-wide (real per-employee rows computed by generate_jm_s01)...")
        _seed_template(
            db, template_key="JM-S01", name="S01 — Monthly Return", report_type="JM_S01",
            country="JM", reporting_year="2026", document_scope="AGGREGATE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                ]),
                # source_column below is a real-column placeholder only (schema requires
                # one) — actual values are bespoke-computed by generate_jm_s01, same
                # convention as US-941's own line1_employee_count field.
                ("totals", "Employer Totals (PAYE / NIS / NHT / Education Tax / HEART)", [
                    ("total_employee_count", "Employee Count", "number", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_salary_wages", "Total Salary / Wages", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_paye_tax_deducted", "Total PAYE Tax Deducted", "currency", "PAYSLIP_ITEM", "tds", None),
                    ("total_nis_employee", "Total NIS (Employee)", "currency", "PAYSLIP_ITEM", "social_security", None),
                    ("total_nis_employer", "Total NIS (Employer)", "currency", "PAYSLIP_ITEM", "employer_social_security", None),
                    ("total_nht_employee", "Total NHT (Employee)", "currency", "PAYSLIP_ITEM", "employee_pension", None),
                    ("total_nht_employer", "Total NHT (Employer)", "currency", "PAYSLIP_ITEM", "employer_pension", None),
                    ("total_education_tax_employee", "Total Education Tax (Employee)", "currency", "PAYSLIP_ITEM", "ni_employee", None),
                    ("total_education_tax_employer", "Total Education Tax (Employer)", "currency", "PAYSLIP_ITEM", "employer_ni", None),
                    ("total_heart_employer", "Total HEART (Employer)", "currency", "PAYSLIP_ITEM", "employer_payroll_tax", None),
                ]),
            ],
        )

        print("Seeding Jamaica S02 annual employer return, employer-wide (real per-employee rows computed by generate_jm_s02)...")
        _seed_template(
            db, template_key="JM-S02", name="S02 — Annual Employer Return", report_type="JM_S02",
            country="JM", reporting_year="2026", document_scope="AGGREGATE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                ]),
                ("totals", "Employer Totals (PAYE / NIS / NHT / Education Tax / HEART, Annual)", [
                    ("total_employee_count", "Employee Count", "number", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_salary_wages", "Total Salary / Wages", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_paye_tax_deducted", "Total PAYE Tax Deducted", "currency", "PAYSLIP_ITEM", "tds", None),
                    ("total_nis_employee", "Total NIS (Employee)", "currency", "PAYSLIP_ITEM", "social_security", None),
                    ("total_nis_employer", "Total NIS (Employer)", "currency", "PAYSLIP_ITEM", "employer_social_security", None),
                    ("total_nht_employee", "Total NHT (Employee)", "currency", "PAYSLIP_ITEM", "employee_pension", None),
                    ("total_nht_employer", "Total NHT (Employer)", "currency", "PAYSLIP_ITEM", "employer_pension", None),
                    ("total_education_tax_employee", "Total Education Tax (Employee)", "currency", "PAYSLIP_ITEM", "ni_employee", None),
                    ("total_education_tax_employer", "Total Education Tax (Employer)", "currency", "PAYSLIP_ITEM", "employer_ni", None),
                    ("total_heart_employer", "Total HEART (Employer)", "currency", "PAYSLIP_ITEM", "employer_payroll_tax", None),
                ]),
            ],
        )

        def _sg_catalog_meta(key, source_key):
            """Phase 6.4: the three Phase 4/5 Singapore templates predate the
            description/authority/source kwargs and were seeded with none of
            them. Same catalogue fields the Phase 5.6 templates use, plus the
            official source artifact the canonical pack already registers
            (with its SHA-256) for the generator's rules."""
            from scripts.seed_singapore_canonical_pack import SOURCES as SG_SOURCES

            entry = sg_catalog.template_catalog_entry(key)
            publisher, title, url, sha256 = SG_SOURCES[source_key][:4]
            return dict(description=f"[{entry['classification']}] {entry['description']}",
                        regulatory_authority=entry["regulatoryAuthority"], effective_from=date(2026, 1, 1),
                        source_references=f"{publisher} — {title} ({url}; SHA-256 {sha256}). Figures computed by "
                                          f"{entry['generator']}; no official form layout is certified.")

        print("Seeding Singapore IR8A annual employment-income data extract (EXPORT_READY only — computed by generate_sg_ir8a)...")
        _seed_template(
            db, template_key="SG-IR8A", name="IR8A — Employment Income Data Extract (AIS)", report_type="SG_IR8A",
            country="SG", reporting_year="2026", document_scope="AGGREGATE",
            **_sg_catalog_meta("SG-IR8A", "iras_ais"),
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                ]),
                # source_column values are real-column placeholders only (schema
                # requires one) — figures are bespoke-computed by generate_sg_ir8a,
                # same convention as JM-S02 above.
                ("totals", "Employer Totals (Income Year, reported for YA = year + 1)", [
                    ("total_employee_count", "Employee Count", "number", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_gross_salary", "Total Gross Salary (OW)", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_bonus_additional_wages", "Total Bonus / Additional Wages", "currency", "PAYSLIP_ITEM", "additional_compensation", None),
                    ("total_employment_income", "Total Employment Income", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_employee_cpf", "Total Employee CPF", "currency", "PAYSLIP_ITEM", "employee_pension", None),
                    ("total_shg_donations", "Total SHG Donations", "currency", "PAYSLIP_ITEM", "professional_tax", None),
                ]),
            ],
        )

        print("Seeding Singapore monthly SDL payable (employer aggregate, rounded down — computed by generate_sg_sdl_monthly)...")
        _seed_template(
            db, template_key="SG-SDL-MONTHLY", name="Skills Development Levy — Monthly Employer Total", report_type="SG_SDL_MONTHLY",
            country="SG", reporting_year="2026", document_scope="AGGREGATE",
            **_sg_catalog_meta("SG-SDL-MONTHLY", "cpf_sdl"),
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                ]),
                # Bespoke-computed by generate_sg_sdl_monthly (CPF Board SDL
                # page: sum each employee's SDL, then round the total down to
                # the nearest dollar); source_column is a real-column placeholder.
                ("totals", "SDL for the calendar month", [
                    ("total_employee_count", "Employee Count", "number", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_sdl_before_rounding", "Total SDL (sum of per-employee SDL)", "currency", "PAYSLIP_ITEM", "employer_payroll_tax", None),
                    ("total_sdl_payable", "Total SDL Payable (rounded down to the nearest dollar)", "currency", "PAYSLIP_ITEM", "employer_payroll_tax", None),
                ]),
            ],
        )

        print("Seeding Singapore CPF EZPay contribution file (CPF Board FTP specification — computed by generate_sg_cpf_ezpay)...")
        _seed_template(
            db, template_key="SG-CPF-EZPAY", name="CPF EZPay Contribution File (FTP specification)", report_type="SG_CPF_EZPAY",
            country="SG", reporting_year="2026", document_scope="AGGREGATE",
            **_sg_catalog_meta("SG-CPF-EZPAY", "cpf_ezpay_ftp_spec"),
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                ]),
                # Bespoke-computed by generate_sg_cpf_ezpay (fixed-length
                # 150-byte records per the CPF Board specification);
                # source_column values are real-column placeholders only.
                ("totals", "CPF EZPay contribution file totals (wage month)", [
                    ("total_cpf", "Total CPF contributions (payment code 01)", "currency", "PAYSLIP_ITEM", "employee_pension", None),
                    ("total_shg", "Total SHG contributions (payment codes 02–05)", "currency", "PAYSLIP_ITEM", "professional_tax", None),
                    ("total_sdl", "SDL payable (payment code 11)", "currency", "PAYSLIP_ITEM", "employer_payroll_tax", None),
                ]),
            ],
        )

        # Singapore Phase 5.6 — eight more templates. Name, report type,
        # classification text and authority come from the Singapore catalog
        # (engine/jurisdictions/singapore/statutory_summary.SG_REPORT_TEMPLATES).
        # Every field is a real persisted column read at its true meaning —
        # never a placeholder. None is an official form: no source_document_id
        # (that FK is for the government publication a form is based on).
        print("Seeding Singapore internal / submission-support / workspace templates (Draft; none officially certified)...")
        employer = ("employer_info", "Employer Information", [
            ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
            ("employer_uen", "UEN / Tax Registration Number", "text", "EMPLOYER_PROFILE", "tax_no", None),
        ])
        employee = ("employee_info", "Employee Information", [
            ("employee_name", "Employee Name", "text", "PAYSLIP_ITEM", "employee_name", None),
            ("designation", "Designation", "text", "PAYSLIP_ITEM", "designation", None),
        ])
        period = [
            ("period_label", "Period", "text", "PAYROLL_RUN", "period_label", None),
            ("pay_date", "Pay Date", "date", "PAYROLL_RUN", "pay_date", None),
        ]
        sg_templates = {
            "SG-PAYROLL-REGISTER": [
                (employer[0], employer[1], employer[2] + period), employee,
                ("earnings", "Earnings", [
                    ("basic_salary", "Basic Salary", "currency", "PAYSLIP_ITEM", "basic_salary", None),
                    ("overtime", "Overtime Pay", "currency", "PAYSLIP_ITEM", "overtime", None),
                    ("additional_compensation", "Additional Compensation", "currency", "PAYSLIP_ITEM", "additional_compensation", None),
                    ("gross_pay", "Gross Pay", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ]),
                ("contributions", "CPF / SHG (Employee)", [
                    ("employee_cpf", "CPF (Employee)", "currency", "PAYSLIP_ITEM", "employee_pension", None),
                    ("shg", "SHG Contribution", "currency", "PAYSLIP_ITEM", "professional_tax", None),
                ]),
                ("deductions", "Deductions and Net Pay", [
                    ("total_deductions", "Total Deductions", "currency", "PAYSLIP_ITEM", "total_deductions", None),
                    ("net_pay", "Net Pay", "currency", "PAYSLIP_ITEM", "net_pay", None),
                ]),
                ("employer_contributions", "CPF / SDL / FWL (Employer)", [
                    ("employer_cpf", "CPF (Employer)", "currency", "PAYSLIP_ITEM", "employer_pension", None),
                    ("sdl", "SDL (Employer)", "currency", "PAYSLIP_ITEM", "employer_payroll_tax", None),
                    ("fwl", "Foreign Worker Levy (Employer)", "currency", "PAYSLIP_ITEM", "employer_eht", None),
                ]),
            ],
            "SG-PAYROLL-SUMMARY": [
                (employer[0], employer[1], employer[2] + period + [
                    ("employee_count", "Employee Count", "text", "PAYROLL_RUN", "employee_count", None),
                ]),
                ("earnings", "Earnings", [
                    ("total_gross_pay", "Total Gross Pay", "currency", "PAYSLIP_ITEM", "gross_pay", "SUM_RUN"),
                    ("total_net_pay", "Total Net Pay", "currency", "PAYSLIP_ITEM", "net_pay", "SUM_RUN"),
                ]),
                ("contributions", "CPF / SHG (Employee)", [
                    ("total_employee_cpf", "Total CPF (Employee)", "currency", "PAYSLIP_ITEM", "employee_pension", "SUM_RUN"),
                    ("total_shg", "Total SHG", "currency", "PAYSLIP_ITEM", "professional_tax", "SUM_RUN"),
                ]),
                ("employer_contributions", "CPF / SDL / FWL (Employer)", [
                    ("total_employer_cpf", "Total CPF (Employer)", "currency", "PAYSLIP_ITEM", "employer_pension", "SUM_RUN"),
                    ("total_sdl", "Total SDL (sum of per-employee SDL, before the employer rounding)", "currency", "PAYSLIP_ITEM", "employer_payroll_tax", "SUM_RUN"),
                    ("total_fwl", "Total Foreign Worker Levy", "currency", "PAYSLIP_ITEM", "employer_eht", "SUM_RUN"),
                ]),
            ],
            "SG-CPF-CONTRIBUTION": [
                (employer[0], employer[1], employer[2] + period), employee,
                ("earnings", "Earnings", [
                    ("gross_pay", "Gross Pay (total — not CPF-subject OW/AW)", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ]),
                ("contributions", "CPF (Employee)", [
                    ("employee_cpf", "CPF (Employee)", "currency", "PAYSLIP_ITEM", "employee_pension", None),
                    ("total_employee_cpf", "Total CPF (Employee)", "currency", "PAYSLIP_ITEM", "employee_pension", "SUM_RUN"),
                ]),
                ("employer_contributions", "CPF (Employer)", [
                    ("employer_cpf", "CPF (Employer)", "currency", "PAYSLIP_ITEM", "employer_pension", None),
                    ("total_employer_cpf", "Total CPF (Employer)", "currency", "PAYSLIP_ITEM", "employer_pension", "SUM_RUN"),
                ]),
            ],
            "SG-SHG-MONTHLY": [
                (employer[0], employer[1], employer[2] + period), employee,
                ("contributions", "SHG (Employee)", [
                    ("shg", "SHG Contribution", "currency", "PAYSLIP_ITEM", "professional_tax", None),
                    ("total_shg", "Total SHG", "currency", "PAYSLIP_ITEM", "professional_tax", "SUM_RUN"),
                ]),
            ],
            "SG-FWL-MONTHLY": [
                (employer[0], employer[1], employer[2] + period), employee,
                ("employer_contributions", "Foreign Worker Levy (Employer cost)", [
                    ("fwl", "Foreign Worker Levy (payroll-computed)", "currency", "PAYSLIP_ITEM", "employer_eht", None),
                    ("total_fwl", "Total Foreign Worker Levy", "currency", "PAYSLIP_ITEM", "employer_eht", "SUM_RUN"),
                ]),
            ],
            "SG-PWM-COMPLIANCE": [
                employer, employee,
                ("earnings", "Wages (PWM required gross evaluated by the Compliance Centre, not stored here)", [
                    ("basic_salary", "Basic Salary", "currency", "PAYSLIP_ITEM", "basic_salary", None),
                    ("overtime", "Overtime Pay", "currency", "PAYSLIP_ITEM", "overtime", None),
                    ("gross_pay", "Gross Pay", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ]),
            ],
            "SG-IR21-REGISTER": [
                employer,
                ("employee_info", "Employee and Employment Dates", [
                    ("employee_name", "Employee Name", "text", "PAYROLL_EMPLOYEE", "name", None),
                    ("date_of_joining", "Start Date", "date", "PAYROLL_EMPLOYEE", "date_of_joining", None),
                    ("date_of_leaving", "Cessation Date", "date", "PAYROLL_EMPLOYEE", "date_of_leaving", None),
                ]),
            ],
            "SG-LQS-COMPLIANCE": [
                employer, employee,
                ("earnings", "Wages (LQS threshold evaluated by the Compliance Centre, not stored here)", [
                    ("basic_salary", "Basic Salary", "currency", "PAYSLIP_ITEM", "basic_salary", None),
                    ("gross_pay", "Gross Pay", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ]),
            ],
        }
        for key, components in sg_templates.items():
            entry = sg_catalog.template_catalog_entry(key)
            _seed_template(
                db, template_key=key, name=entry["name"], report_type=entry["reportType"],
                country="SG", reporting_year="2026", document_scope="AGGREGATE", components=components,
                description=f"[{entry['classification']}] {entry['description']}",
                regulatory_authority=entry["regulatoryAuthority"], effective_from=date(2026, 1, 1),
                source_references="Internal Zoiko template (Phase 5.6) — no official form layout; figures are the "
                                  "persisted payslip columns named in each field.",
            )

        print("Seeding The Bahamas NIB statement, per-employee (no personal income tax)...")
        _seed_template(
            db, template_key="BS-NIB", name="NIB Contribution Statement", report_type="BS_NIB_STATEMENT",
            country="BS", reporting_year="2026", document_scope="PER_EMPLOYEE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                ]),
                ("employee_info", "Employee Information", [
                    ("employee_name", "Employee Name", "text", "PAYSLIP_ITEM", "employee_name", None),
                ]),
                ("earnings", "Earnings", [
                    ("gross_pay", "Gross Pay", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ]),
                ("contributions", "NIB (Employee)", [
                    ("social_security", "NIB (Employee)", "currency", "PAYSLIP_ITEM", "social_security", None),
                ]),
                ("employer_contributions", "NIB (Employer)", [
                    ("employer_social_security", "NIB (Employer)", "currency", "PAYSLIP_ITEM", "employer_social_security", None),
                ]),
            ],
        )

        print("Seeding The Bahamas C10 monthly NIB contribution statement (non-hospitality), employer-wide (real per-employee rows computed by generate_bs_c10)...")
        _seed_template(
            db, template_key="BS-C10", name="C10 — Monthly NIB Contribution Statement (Non-Hospitality)", report_type="BS_C10",
            country="BS", reporting_year="2026", document_scope="AGGREGATE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                ]),
                # source_column below is a real-column placeholder only (schema requires
                # one) — actual values are bespoke-computed by generate_bs_c10, same
                # convention as US-941's own line1_employee_count field.
                ("totals", "Employer Totals (Insurable Earnings / NIB)", [
                    ("total_employee_count", "Employee Count", "number", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_insurable_earnings", "Total Insurable Earnings", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_nib_employee", "Total NIB (Employee)", "currency", "PAYSLIP_ITEM", "social_security", None),
                    ("total_nib_employer", "Total NIB (Employer)", "currency", "PAYSLIP_ITEM", "employer_social_security", None),
                ]),
            ],
        )

        print("Seeding Trinidad and Tobago PAYE + Health Surcharge + NIS statement, per-employee...")
        _seed_template(
            db, template_key="TT-PAYE-HS-NIS", name="PAYE + Health Surcharge + NIS Statement", report_type="TT_PAYE_HS_NIS",
            country="TT", reporting_year="2026", document_scope="PER_EMPLOYEE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_bir_number", "BIR File Number", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                ("employee_info", "Employee Information", [
                    ("employee_name", "Employee Name", "text", "PAYSLIP_ITEM", "employee_name", None),
                ]),
                ("earnings", "Earnings", [
                    ("gross_pay", "Gross Pay", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ]),
                ("tax", "PAYE / Health Surcharge", [
                    ("tds", "PAYE", "currency", "PAYSLIP_ITEM", "tds", None),
                    ("professional_tax", "Health Surcharge", "currency", "PAYSLIP_ITEM", "professional_tax", None),
                ]),
                ("contributions", "NIS (Employee)", [
                    ("social_security", "NIS (Employee)", "currency", "PAYSLIP_ITEM", "social_security", None),
                ]),
                ("employer_contributions", "NIS (Employer)", [
                    ("employer_social_security", "NIS (Employer)", "currency", "PAYSLIP_ITEM", "employer_social_security", None),
                ]),
            ],
        )

        print("Seeding Trinidad and Tobago Monthly PAYE/Health Surcharge Return, employer-wide (real per-employee rows computed by generate_tt_monthly_return)...")
        _seed_template(
            db, template_key="TT-MONTHLY-RETURN", name="Monthly PAYE / Health Surcharge Return", report_type="TT_MONTHLY_RETURN",
            country="TT", reporting_year="2026", document_scope="AGGREGATE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_bir_number", "BIR File Number", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                # source_column below is a real-column placeholder only (schema requires
                # one) — actual values are bespoke-computed by generate_tt_monthly_return,
                # same convention as US-941's own line1_employee_count field.
                ("totals", "Employer Totals (PAYE / Health Surcharge / NIS)", [
                    ("total_employee_count", "Employee Count", "number", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_salary_wages", "Total Salary / Wages", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_paye_tax_deducted", "Total PAYE Tax Deducted", "currency", "PAYSLIP_ITEM", "tds", None),
                    ("total_health_surcharge", "Total Health Surcharge", "currency", "PAYSLIP_ITEM", "professional_tax", None),
                    ("total_nis_employee", "Total NIS (Employee)", "currency", "PAYSLIP_ITEM", "social_security", None),
                    ("total_nis_employer", "Total NIS (Employer)", "currency", "PAYSLIP_ITEM", "employer_social_security", None),
                ]),
            ],
        )

        print("Seeding Trinidad and Tobago NIBTT contribution data, employer-wide (real per-employee rows computed by generate_tt_nibtt_data)...")
        _seed_template(
            db, template_key="TT-NIBTT-DATA", name="NIBTT Contribution Data", report_type="TT_NIBTT_DATA",
            country="TT", reporting_year="2026", document_scope="AGGREGATE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                ]),
                ("totals", "Employer Totals (Insurable Earnings / NIS)", [
                    ("total_employee_count", "Employee Count", "number", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_insurable_earnings", "Total Insurable Earnings", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                    ("total_nis_employee", "Total NIS (Employee)", "currency", "PAYSLIP_ITEM", "social_security", None),
                    ("total_nis_employer", "Total NIS (Employer)", "currency", "PAYSLIP_ITEM", "employer_social_security", None),
                ]),
            ],
        )

        print("Seeding Trinidad and Tobago TD4 annual employee certificate, per-employee...")
        _seed_template(
            db, template_key="TT-TD4", name="TD4 — Annual Employee Certificate", report_type="TD4",
            country="TT", reporting_year="2026", document_scope="PER_EMPLOYEE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_bir_number", "BIR File Number", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                ("employee_info", "Employee Information", [
                    ("employee_name", "Employee Name", "text", "PAYROLL_EMPLOYEE", "name", None),
                ]),
                ("earnings", "Earnings (Year-to-Date)", [
                    ("gross_pay_ytd", "Total Salary / Wages (YTD)", "currency", "PAYSLIP_ITEM", "gross_pay", "SUM_YTD"),
                ]),
                ("tax", "PAYE / Health Surcharge (Year-to-Date)", [
                    ("tds_ytd", "PAYE Tax Deducted (YTD)", "currency", "PAYSLIP_ITEM", "tds", "SUM_YTD"),
                    ("professional_tax_ytd", "Health Surcharge (YTD)", "currency", "PAYSLIP_ITEM", "professional_tax", "SUM_YTD"),
                ]),
                ("contributions", "NIS (Year-to-Date)", [
                    ("nis_employee_ytd", "NIS Employee (YTD)", "currency", "PAYSLIP_ITEM", "social_security", "SUM_YTD"),
                ]),
            ],
        )

        print("Seeding Puerto Rico Withholding + Social Security/Medicare + SINOT statement, per-employee...")
        # Same "generic PER_EMPLOYEE statement, no bespoke generator"
        # baseline every other Caribbean country got first — the real
        # named Hacienda/SSA forms (499 R-1B, 499R-2/W-2PR, Form
        # 940/941-equivalent) are deferred to a follow-up phase, same
        # sequencing KY's own real-forms commit followed its own base
        # country build by.
        _seed_template(
            db, template_key="PR-WITHHOLDING-STATEMENT", name="Withholding + Social Security/Medicare + SINOT Statement",
            report_type="PR_WITHHOLDING_STATEMENT",
            country="PR", reporting_year="2026", document_scope="PER_EMPLOYEE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_hacienda_ein", "Hacienda EIN", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                ("employee_info", "Employee Information", [
                    ("employee_name", "Employee Name", "text", "PAYSLIP_ITEM", "employee_name", None),
                ]),
                ("earnings", "Earnings", [
                    ("gross_pay", "Gross Pay", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ]),
                ("tax", "Hacienda Withholding", [
                    ("tds", "Puerto Rico Income Tax Withheld", "currency", "PAYSLIP_ITEM", "tds", None),
                ]),
                ("contributions", "Social Security / Medicare / SINOT (Employee)", [
                    ("social_security", "Social Security (Employee)", "currency", "PAYSLIP_ITEM", "social_security", None),
                    ("medicare", "Medicare (incl. Additional Medicare, Employee)", "currency", "PAYSLIP_ITEM", "medicare", None),
                    ("state_disability_insurance", "SINOT (Employee)", "currency", "PAYSLIP_ITEM", "state_disability_insurance", None),
                ]),
                ("employer_contributions", "Social Security / Medicare / FUTA-equivalent / Unemployment / SINOT (Employer)", [
                    ("employer_social_security", "Social Security (Employer)", "currency", "PAYSLIP_ITEM", "employer_social_security", None),
                    ("employer_medicare", "Medicare (Employer)", "currency", "PAYSLIP_ITEM", "employer_medicare", None),
                    ("employer_futa", "FUTA-equivalent (Employer)", "currency", "PAYSLIP_ITEM", "employer_futa", None),
                    ("employer_sui", "DTRH Unemployment (Employer)", "currency", "PAYSLIP_ITEM", "employer_sui", None),
                    ("employer_state_program_contributions", "SINOT (Employer)", "currency", "PAYSLIP_ITEM", "employer_state_program_contributions", None),
                ]),
            ],
        )

        print("Seeding Puerto Rico Form 499 R-1B (quarterly Hacienda withholding return, aggregate)...")
        _seed_template(
            db, template_key="PR-499R1B", name="Form 499 R-1B - Puerto Rico Quarterly Withholding Return", report_type="PR_499R1B",
            country="PR", reporting_year="2026", document_scope="AGGREGATE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_hacienda_ein", "Hacienda Employer Identification Number", "text", "EMPLOYER_PROFILE", "tax_no", None),
                    ("employee_count", "Number of Employees", "number", "PAYSLIP_ITEM", "gross_pay", None),  # placeholder — bespoke-computed
                ]),
                ("withholding", "Wages & Withholding", [
                    ("total_wages", "Total Wages Paid", "currency", "PAYSLIP_ITEM", "gross_pay", "SUM_RUN"),
                    ("total_pr_withholding", "Total Puerto Rico Income Tax Withheld", "currency", "PAYSLIP_ITEM", "tds", "SUM_RUN"),
                ]),
            ],
        )
        # service.generate_pr_499r1b independently sums real committed PR
        # payslips only (never derives from these mapped source_columns
        # directly) — see that function's own docstring for disclosed gaps
        # (no deposit-category classification, no prior-period-correction
        # deltas reflected yet).

        print("Seeding federal Form 941 for Puerto Rico employers (FICA on PR wages, aggregate)...")
        _seed_template(
            db, template_key="PR-941", name="Form 941 - Employer's Quarterly Federal Tax Return (Puerto Rico)", report_type="PR_941",
            country="PR", reporting_year="2026", document_scope="AGGREGATE",
            components=[
                ("employer_info", "Employer Information (Line 1 area)", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_ein", "Employer Identification Number (EIN)", "text", "EMPLOYER_PROFILE", "tax_no", None),
                    ("line1_employee_count", "Line 1 - Number of Employees", "number", "PAYSLIP_ITEM", "gross_pay", None),  # placeholder — bespoke-computed
                ]),
                ("wages_tax", "Wages & Federal Tax (Line 2-3)", [
                    ("line2_wages", "Line 2 - Wages, Tips, Other Compensation", "currency", "PAYSLIP_ITEM", "gross_pay", "SUM_RUN"),
                    ("line3_federal_tax_withheld", "Line 3 - Federal Income Tax Withheld", "currency", "PAYSLIP_ITEM", "gross_pay", None),  # placeholder — always $0, see generate_pr_941's own docstring
                ]),
                ("ss_medicare", "Social Security & Medicare (Line 5a/5c)", [
                    ("line5a_ss_wages", "Line 5a - Taxable Social Security Wages (col. 1)", "currency", "PAYSLIP_ITEM", "social_security", "SUM_RUN"),
                    ("line5a_ss_tax", "Line 5a - Social Security Tax (col. 2, both shares)", "currency", "PAYSLIP_ITEM", "social_security", "SUM_RUN"),
                    ("line5c_medicare_wages", "Line 5c - Taxable Medicare Wages (col. 1)", "currency", "PAYSLIP_ITEM", "gross_pay", "SUM_RUN"),
                    ("line5c_medicare_tax", "Line 5c - Medicare Tax (col. 2, both shares, incl. Additional)", "currency", "PAYSLIP_ITEM", "medicare", "SUM_RUN"),
                ]),
                ("totals", "Totals (Line 6/12)", [
                    ("line6_total_taxes_before_adjustments", "Line 6 - Total Taxes Before Adjustments", "currency", "PAYSLIP_ITEM", "social_security", "SUM_RUN"),
                    ("line12_total_taxes_after_adjustments_and_credits", "Line 12 - Total Taxes After Adjustments and Credits", "currency", "PAYSLIP_ITEM", "social_security", "SUM_RUN"),
                ]),
            ],
        )
        # Independent from US-941/generate_us_941 — see
        # generate_pr_941's own docstring (Line 3 always $0: PR federal FIT
        # applicability is a separate, undetermined employee-level fact).

        print("Seeding federal Form 940 (FUTA-equivalent) for Puerto Rico employers, aggregate/annual...")
        _seed_template(
            db, template_key="PR-940", name="Form 940 - Employer's Annual Federal Unemployment (FUTA) Tax Return (Puerto Rico)", report_type="PR_940",
            country="PR", reporting_year="2026", document_scope="AGGREGATE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_ein", "Employer Identification Number (EIN)", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                ("futa", "FUTA-equivalent Wages & Tax", [
                    ("total_payments", "Total Payments to All Employees", "currency", "PAYSLIP_ITEM", "gross_pay", "SUM_RUN"),
                    ("futa_taxable_wages", "Total Taxable FUTA-equivalent Wages ($7,000/employee cap)", "currency", "PAYSLIP_ITEM", "employer_futa", "SUM_RUN"),
                    ("futa_tax_due", "FUTA-equivalent Tax (before deposits)", "currency", "PAYSLIP_ITEM", "employer_futa", "SUM_RUN"),
                    ("employee_count", "Number of Employees Paid", "number", "PAYSLIP_ITEM", "gross_pay", None),  # placeholder — bespoke-computed
                ]),
            ],
        )
        # Independent from US-940/generate_us_940 — see generate_pr_940's
        # own docstring.

        print("Seeding Puerto Rico Form 499R-2/W-2PR (annual employee withholding statement, per-employee)...")
        _seed_template(
            db, template_key="PR-W2PR", name="Form 499R-2/W-2PR - Withholding Statement", report_type="PR_W2PR",
            country="PR", reporting_year="2026", document_scope="PER_EMPLOYEE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_hacienda_ein", "Hacienda Employer Identification Number", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                ("employee_info", "Employee Information", [
                    ("employee_name", "Employee Name", "text", "PAYROLL_EMPLOYEE", "name", None),
                ]),
                ("box_wages", "Wages & PR Tax Withheld", [
                    ("box_wages", "Total Wages Paid", "currency", "PAYSLIP_ITEM", "gross_pay", "SUM_YTD"),
                    ("box_pr_tax_withheld", "Puerto Rico Income Tax Withheld", "currency", "PAYSLIP_ITEM", "tds", "SUM_YTD"),
                ]),
                ("box_ss_medicare", "Social Security & Medicare", [
                    ("box_ss_wages", "Social Security Wages (wage-base capped)", "currency", "PAYSLIP_ITEM", "social_security", "SUM_YTD"),
                    ("box_ss_tax", "Social Security Tax Withheld", "currency", "PAYSLIP_ITEM", "social_security", "SUM_YTD"),
                    ("box_medicare_wages", "Medicare Wages", "currency", "PAYSLIP_ITEM", "gross_pay", "SUM_YTD"),
                    ("box_medicare_tax", "Medicare Tax Withheld (incl. Additional Medicare)", "currency", "PAYSLIP_ITEM", "medicare", "SUM_YTD"),
                ]),
                ("box_sinot", "SINOT", [
                    ("box_sinot", "SINOT Withheld (Employee)", "currency", "PAYSLIP_ITEM", "state_disability_insurance", "SUM_YTD"),
                ]),
            ],
        )
        # Independent from US-W2/generate_us_w2 — see generate_pr_w2pr's
        # own docstring for disclosed gaps (no Act 60 boxes, dependents/
        # deduction-allowance detail not broken out).

        print("Seeding Puerto Rico DTRH quarterly wage/contribution return (PR-020, aggregate)...")
        _seed_template(
            db, template_key="PR-DTRH-QUARTERLY", name="DTRH Quarterly Wage & Contribution Return", report_type="PR_DTRH_QUARTERLY",
            country="PR", reporting_year="2026", document_scope="AGGREGATE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_dtrh_account", "DTRH Employer Account Number", "text", "EMPLOYER_PROFILE", "tax_no", None),
                    ("employee_count", "Number of Employees", "number", "PAYSLIP_ITEM", "gross_pay", None),  # placeholder — bespoke-computed
                ]),
                ("unemployment", "Unemployment Wages & Tax", [
                    ("total_wages", "Total Wages Paid", "currency", "PAYSLIP_ITEM", "gross_pay", "SUM_RUN"),
                    ("unemployment_taxable_wages", "Taxable Unemployment Wages ($7,000/employee cap)", "currency", "PAYSLIP_ITEM", "employer_sui", "SUM_RUN"),
                    ("unemployment_tax_due", "DTRH Unemployment Tax Due", "currency", "PAYSLIP_ITEM", "employer_sui", "SUM_RUN"),
                ]),
                ("sinot", "SINOT Wages & Contributions", [
                    ("sinot_taxable_wages", "Taxable SINOT Wages ($9,000/employee cap)", "currency", "PAYSLIP_ITEM", "state_disability_insurance", "SUM_RUN"),
                    ("sinot_employee_contribution", "SINOT Employee Contribution", "currency", "PAYSLIP_ITEM", "state_disability_insurance", "SUM_RUN"),
                    ("sinot_employer_contribution", "SINOT Employer Contribution", "currency", "PAYSLIP_ITEM", "employer_state_program_contributions", "SUM_RUN"),
                ]),
            ],
        )
        # Independent from every US report_type — see
        # generate_pr_dtrh_quarterly's own docstring for the disclosed
        # this-quarter-only wage-base-capping simplification.

        print("Seeding Germany Payroll Summary (aggregate, per payroll run)...")
        # AGGREGATE, run-based — uses the fully generic
        # service.generate_report_from_template directly (no bespoke
        # generator, same mechanism as UK's EPS/FPS-style summary above).
        _seed_template(
            db, template_key="DE-PAYROLL-SUMMARY", name="Germany Payroll Summary", report_type="DE_PAYROLL_SUMMARY",
            country="DE", reporting_year="2026", document_scope="AGGREGATE",
            components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_tax_no", "Betriebsnummer / Steuernummer", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                ("earnings", "Earnings", [
                    ("total_gross_pay", "Total Gross Pay", "currency", "PAYSLIP_ITEM", "gross_pay", "SUM_RUN"),
                ]),
                ("tax", "Wage Tax (Lohnsteuer / Soli / Kirchensteuer)", [
                    # Same combined-value labeling fix as DE-LSTB above — `tds` is
                    # Lohnsteuer + Soli, never Lohnsteuer alone.
                    ("total_lohnsteuer", "Total Lohnsteuer + Solidaritätszuschlag", "currency", "PAYSLIP_ITEM", "tds", "SUM_RUN"),
                    ("total_soli", "Total Solidaritätszuschlag", "currency", "PAYSLIP_ITEM", "soli", "SUM_RUN"),
                    ("total_church_tax", "Total Kirchensteuer", "currency", "PAYSLIP_ITEM", "church_tax", "SUM_RUN"),
                ]),
                ("contributions", "Social Insurance", [
                    ("total_pf", "Total Pension Insurance (Employee)", "currency", "PAYSLIP_ITEM", "pf", "SUM_RUN"),
                    ("total_esi", "Total Health / Unemployment / Care Insurance (Employee)", "currency", "PAYSLIP_ITEM", "esi", "SUM_RUN"),
                ]),
                ("employer_contributions", "Employer Contributions", [
                    ("total_employer_pf", "Total Pension Insurance (Employer)", "currency", "PAYSLIP_ITEM", "employer_pf", "SUM_RUN"),
                    ("total_employer_esi", "Total Health / Unemployment / Care Insurance (Employer)", "currency", "PAYSLIP_ITEM", "employer_esi", "SUM_RUN"),
                ]),
            ],
        )
        # DEÜV (social-insurance registration/notification submission) and
        # an ELSTER-transmitted Lohnsteuer-Anmeldung are explicitly NOT
        # seeded here — REQUIRES STATUTORY EVIDENCE. DEÜV has zero code
        # anywhere in this repository (confirmed by search; see docs/
        # GERMANY_JURISDICTION_FINAL_BLOCKER_MATRIX.md's own DEÜV entry —
        # "zero code, correctly blocked on missing specification"). ELSTER
        # already has its own dedicated, more sophisticated transmission-
        # lifecycle subsystem (elster-transmissions/elster-certificate-
        # config — signature/certificate/retry, not a field-mapped
        # document) — folding it into the generic ReportTemplate shape
        # would duplicate, not reuse, that existing architecture.

        seed_hong_kong(db)
        # ------------------------------------------------------------------
        # Ireland (ZP-IE-ENG-001) — Revenue Online System (ROS) templates.
        # ------------------------------------------------------------------
        #
        # All DRAFT, like every other template here: a Super Admin must
        # review, Approve, Publish and Activate before an organization can
        # generate against them.
        #
        # The per-head Irish figures (USC, PRSI by sub-class, MyFutureFund,
        # LPT, the applied RPN) are read through the "PAYSLIP_ITEM_JSON"
        # data source — ie_calculation_snapshot.<path> — because they are
        # computed per employee but have no scalar PayslipItem column. They
        # were being discarded entirely before that column existed, so these
        # templates are the first thing in the product able to show them.
        #
        # NOT seeded: a ROS file-format submission itself. Revenue's
        # published ROS file format / upload specification is external
        # evidence not present in this repository, and inventing a field
        # order or layout for it would be exactly the fabrication this
        # module's own Germany/ELSTER comments above refuse. When that spec
        # is available it needs its own transmission path (like DE's ELSTER
        # subsystem note), not a field-mapped ReportTemplate.
        _seed_template(
            db, template_key="IE-ROS-EMP-CERT", name="ROS Employee PAYE Certificate",
            report_type="IE_ROS_EMPLOYEE_CERT", country="IE", reporting_year="2026",
            document_scope="PER_EMPLOYEE", components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_tax_no", "Revenue PAYE Reference / Employer Number", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                # The RPN actually applied is the reason this certificate can
                # be reconciled against Revenue at all (IE-005/IE-045).
                ("employee_info", "Employee & RPN Reference", [
                    ("employee_name", "Employee Name", "text", "PAYSLIP_ITEM", "employee_name", None),
                    ("rpn_number", "RPN Number", "text", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.rpn.rpn_number", None),
                    ("paye_basis", "PAYE Basis (RPN / Emergency)", "text", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.paye.basis", None),
                    ("tax_year", "Irish Tax Year", "text", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.tax_year", None),
                ]),
                ("earnings", "Earnings", [
                    ("gross_pay", "Total Gross Pay", "currency", "PAYSLIP_ITEM", "gross_pay", "SUM_RUN"),
                ]),
                ("tax", "PAYE", [
                    ("total_paye", "PAYE Deducted", "currency", "PAYSLIP_ITEM", "tds", "SUM_RUN"),
                    ("standard_rate_pay", "PAYE Standard-Rate Pay", "currency", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.paye.standard_rate_pay", None),
                    ("higher_rate_pay", "PAYE Higher-Rate Pay", "currency", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.paye.higher_rate_pay", None),
                    ("tax_credit", "PAYE Tax Credit Applied", "currency", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.paye.tax_credit_applied", None),
                ]),
                ("usc", "Universal Social Charge", [
                    ("total_usc", "USC Deducted", "currency", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.usc.amount", "SUM_RUN"),
                ]),
                ("prsi", "PRSI", [
                    ("prsi_subclass", "PRSI Sub-Class", "text", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.prsi.subclass", None),
                    ("prsi_employee", "PRSI (Employee)", "currency", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.prsi.employee", "SUM_RUN"),
                    ("prsi_employer", "PRSI (Employer)", "currency", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.prsi.employer", "SUM_RUN"),
                    ("prsi_ax_credit", "PRSI AX Tapered Credit", "currency", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.prsi.ax_credit", None),
                    ("prsi_weeks", "PRSI Contribution Weeks", "text", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.prsi.contribution_weeks", None),
                ]),
                ("pension", "PRSC Additional Pension", [
                    ("employee_prsc", "PRSC (Employee)", "currency", "PAYSLIP_ITEM", "employee_pension", "SUM_RUN"),
                    ("employer_prsc", "PRSC (Employer)", "currency", "PAYSLIP_ITEM", "employer_pension", "SUM_RUN"),
                ]),
                ("deductions", "Total Deductions", [
                    ("total_deductions", "Total Deductions", "currency", "PAYSLIP_ITEM", "total_deductions", "SUM_RUN"),
                    ("employee_statutory_total", "Total Employee Statutory Deductions", "currency", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.employee_total", "SUM_RUN"),
                ]),
                ("ytd", "Year-to-Date", [
                    ("net_pay", "Net Pay", "currency", "PAYSLIP_ITEM", "net_pay", "SUM_RUN"),
                ]),
            ],
        )
        _seed_template(
            db, template_key="IE-ROS-PAYROLL", name="ROS Period Payroll Summary",
            report_type="IE_ROS_PAYROLL", country="IE", reporting_year="2026",
            document_scope="AGGREGATE", components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_tax_no", "Revenue PAYE Reference / Employer Number", "text", "EMPLOYER_PROFILE", "tax_no", None),
                    ("period_label", "Period", "text", "PAYROLL_RUN", "period_label", None),
                    ("pay_date", "Pay Date", "date", "PAYROLL_RUN", "pay_date", None),
                ]),
                ("earnings", "Earnings", [
                    ("total_gross_pay", "Total Gross Pay", "currency", "PAYSLIP_ITEM", "gross_pay", "SUM_RUN"),
                ]),
                ("tax", "PAYE", [
                    ("total_paye", "PAYE Deducted", "currency", "PAYSLIP_ITEM", "tds", "SUM_RUN"),
                ]),
                ("usc", "Universal Social Charge", [
                    ("total_usc", "USC Deducted", "currency", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.usc.amount", "SUM_RUN"),
                ]),
                ("prsi", "PRSI", [
                    ("prsi_employee", "PRSI (Employee)", "currency", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.prsi.employee", "SUM_RUN"),
                    ("prsi_employer", "PRSI (Employer)", "currency", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.prsi.employer", "SUM_RUN"),
                ]),
                ("pension", "PRSC Additional Pension", [
                    ("employee_prsc", "PRSC (Employee)", "currency", "PAYSLIP_ITEM", "employee_pension", "SUM_RUN"),
                    ("employer_prsc", "PRSC (Employer)", "currency", "PAYSLIP_ITEM", "employer_pension", "SUM_RUN"),
                ]),
                ("totals", "Period Totals", [
                    ("total_deductions", "Total Deductions", "currency", "PAYSLIP_ITEM", "total_deductions", "SUM_RUN"),
                    ("total_net", "Total Net Pay", "currency", "PAYSLIP_ITEM", "net_pay", "SUM_RUN"),
                ]),
            ],
        )
        # PRSI, USC, MyFutureFund and LPT are each reported PER EMPLOYEE —
        # every one of their distinguishing attributes (PRSI sub-class and
        # weekly reckonable band, the NAERSA-notified MFF status, whether
        # LPT was instructed on that employee's RPN) is a property of an
        # individual, and summing any of them across a run is meaningless.
        # That is also why their currency fields carry no aggregation here,
        # matching DE-LSTB's own convention for PER_EMPLOYEE templates. The
        # period-level roll-up is IE-ROS-PAYROLL above, which is AGGREGATE.
        _seed_template(
            db, template_key="IE-PRSI-SCHEDULE", name="PRSI Return Schedule",
            report_type="IE_PRSI_SCHEDULE", country="IE", reporting_year="2026",
            document_scope="PER_EMPLOYEE", components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_tax_no", "Revenue PAYE Reference / Employer Number", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                ("prsi", "PRSI by Sub-Class and Band", [
                    ("prsi_subclass", "PRSI Sub-Class", "text", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.prsi.subclass", None),
                    ("prsi_weekly_reckonable", "PRSI Weekly Reckonable Pay", "currency", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.prsi.weekly_reckonable", None),
                    ("prsi_employee", "PRSI (Employee)", "currency", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.prsi.employee", None),
                    ("prsi_ax_credit", "PRSI AX Tapered Credit", "currency", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.prsi.ax_credit", None),
                    ("prsi_weeks", "PRSI Contribution Weeks", "text", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.prsi.contribution_weeks", None),
                ]),
                ("totals", "PRSI Totals", [
                    ("prsi_employer", "PRSI (Employer)", "currency", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.prsi.employer", None),
                ]),
            ],
        )
        _seed_template(
            db, template_key="IE-USC-SCHEDULE", name="USC Return Schedule",
            report_type="IE_USC_SCHEDULE", country="IE", reporting_year="2026",
            document_scope="PER_EMPLOYEE", components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_tax_no", "Revenue PAYE Reference / Employer Number", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                ("usc", "Universal Social Charge", [
                    ("total_usc", "USC Deducted", "currency", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.usc.amount", None),
                ]),
            ],
        )
        _seed_template(
            db, template_key="IE-MFF-SCHEDULE", name="MyFutureFund Contribution Schedule",
            report_type="IE_MFF_SCHEDULE", country="IE", reporting_year="2026",
            document_scope="PER_EMPLOYEE", components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_tax_no", "Revenue PAYE Reference / Employer Number", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                ("myfuturefund", "MyFutureFund Contributions and Status", [
                    ("mff_status", "NAERSA-notified Status", "text", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.myfuturefund.status", None),
                    ("mff_contributory", "Contributory", "text", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.myfuturefund.contributory", None),
                    ("mff_employee", "MyFutureFund (Employee)", "currency", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.myfuturefund.employee", None),
                    ("mff_employer", "MyFutureFund (Employer)", "currency", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.myfuturefund.employer", None),
                ]),
                # Informational only. The 0.5% State contribution is
                # administered by the State/NAERSA and is never deducted from
                # pay (IE-018) — kept in its own component so it cannot be
                # mistaken for a payroll deduction or land in a totals block.
                ("myfuturefund_state", "MyFutureFund State Top-Up (informational — not a deduction)", [
                    ("mff_state_topup", "State Top-Up", "currency", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.myfuturefund.state_topup", None),
                ]),
            ],
        )
        _seed_template(
            db, template_key="IE-LPT-SCHEDULE", name="Local Property Tax Deduction Schedule",
            report_type="IE_LPT_SCHEDULE", country="IE", reporting_year="2026",
            document_scope="PER_EMPLOYEE", components=[
                ("employer_info", "Employer Information", [
                    ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
                    ("employer_tax_no", "Revenue PAYE Reference / Employer Number", "text", "EMPLOYER_PROFILE", "tax_no", None),
                ]),
                # LPT is deducted only where Revenue instructed it on the RPN
                # (IE-003) — both the amount and the "instructed" flag are
                # carried so a return can show why a head has no LPT line.
                ("lpt", "Local Property Tax", [
                    ("lpt_instructed", "Instructed on RPN", "text", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.lpt.instructed", None),
                    ("lpt_rate_pct", "Instructed Rate %", "text", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.lpt.rate_pct", None),
                    ("lpt_amount", "LPT Deducted", "currency", "PAYSLIP_ITEM_JSON", "ie_calculation_snapshot.lpt.amount", None),
                ]),
            ],
        )

        print("\nDone. All templates are in Draft status — a Super Admin still needs to review, Approve, Publish, and Activate each one before Organizations can generate against it.")
    finally:
        db.close()


def seed_hong_kong(db):
    """The seven Hong Kong report templates and the BIR56A / IR56B filing
    calendar rows, seeded through the same validated service functions every
    other jurisdiction uses. Exposed as its own function (rather than inlined
    in run()) so a test can seed Hong Kong in isolation without paying for - or
    polluting its fixtures with - every other country's templates.
    """
    # ── Hong Kong (ZP-HK-ENG-001 §7, §5, HK-011, HK-010) ─────────────
    # Hong Kong's reporting runs through the SAME shared pipeline as every
    # other jurisdiction: these seven templates are ordinary ReportTemplates
    # (versioned, effective dated, maker-checker approved, Activated
    # before use), and each of the five generators below writes a shared
    # GeneratedReport whose rendered_data the shared certificate PDF
    # renders for the per-employee forms.
    #
    # Two things are deliberately true of every one of them:
    #  1. NO "tax" component. Hong Kong has no payroll income tax — Salaries
    #     Tax is employee-assessed and reported to IRD after the year of
    #     assessment, never withheld by the employer. MPF uses the shared
    #     employee/employer pension slots. Same reasoning as Cayman
    #     (KY_PENSION) and The Bahamas (BS_NIB_STATEMENT).
    #  2. The description states, per template, that this is Zoiko's own
    #     INTERNAL layout and not the IRD / eMPF prescribed format. The
    #     official BIR56A / IR56B / IR56E / IR56F / IR56G XML schemas and
    #     the eMPF remittance specification are not archived in this
    #     build, so no official layout is invented and no e-filing is
    #     offered (release gate G2). The source_column values are real
    #     persisted columns or, for bespoke-computed figures, the same
    #     real-column placeholder convention JM-S02 / SG-IR8A use.
    _HK_DISCLOSURE = ("[INTERNAL LAYOUT — NOT THE IRD/eMPF PRESCRIBED FORMAT, gate G2] Zoiko's own field map. "
                      "The official IRD BIR56A/IR56B/IR56E/IR56F/IR56G XML schemas and the eMPF remittance "
                      "specification are not archived in this build, so no official layout is claimed and "
                      "nothing is transmitted to IRD or eMPF. All figures are computed from committed "
                      "payroll; the HK statutory pack (ZP-HK-ENG-001 v1.0) is the source of every value.")
    _hk_employer = ("employer_info", "Employer Information", [
        ("employer_name", "Employer Name", "text", "EMPLOYER_PROFILE", "name", None),
        ("employer_address", "Employer Address", "text", "EMPLOYER_PROFILE", "address", None),
        ("employer_br_number", "Business Registration (BR) Number", "text", "EMPLOYER_PROFILE", "tax_no", None),
        ("employer_ird_file_number", "IRD Employer File Number", "text", "EMPLOYER_PROFILE", "ird_employer_file_number", None),
        ("employer_empf_account", "eMPF Employer Account", "text", "EMPLOYER_PROFILE", "empf_employer_account", None),
    ])
    _hk_filing_metadata = ("filing_metadata", "Filing Metadata", [
        ("schema_status", "Filing Status / Schema", "text", "PAYSLIP_ITEM", "gross_pay", None),
    ])

    print("Seeding Hong Kong BIR56A annual employer's return (aggregate)...")
    _seed_template(
        db, template_key="HK-BIR56A", name="BIR56A — Annual Employer's Return (Year of Assessment)",
        report_type="HK_BIR56A", country="HK", reporting_year="2025/26", document_scope="AGGREGATE",
        description=_HK_DISCLOSURE, regulatory_authority="Inland Revenue Department (IRD)",
        effective_from=date(2025, 4, 1),
        source_references="IRD PAM (employer) — annual employer's return for the year of assessment ending "
                          "31 March. Field map computed by service.generate_hong_kong_bir56a; no official "
                          "BIR56A XML layout is certified (G2).",
        components=[
            _hk_employer,
            ("employee_summary", "Employee Summary", [
                ("employee_count", "Employees reported", "number", "PAYSLIP_ITEM", "gross_pay", None),
                ("bir56a_case_id", "BIR56A reporting case", "number", "PAYSLIP_ITEM", "gross_pay", None),
            ]),
            ("totals", "Totals", [
                ("employer_ya", "Year of Assessment (1 April – 31 March)", "text", "PAYSLIP_ITEM", "gross_pay", None),
                ("total_remuneration", "Total remuneration reported (IRD fields)", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ("committed_payroll_gross", "Committed payroll gross (reconciliation target)", "currency", "PAYSLIP_ITEM", "gross_pay", None),
            ]),
            _hk_filing_metadata,
        ],
    )

    print("Seeding Hong Kong IR56B per-employee annual return (employee copy)...")
    _seed_template(
        db, template_key="HK-IR56B", name="IR56B — Employee's Annual Return",
        report_type="HK_IR56B", country="HK", reporting_year="2025/26", document_scope="PER_EMPLOYEE",
        description=_HK_DISCLOSURE + " PER_EMPLOYEE, so the shared certificate PDF renders the employee's own copy.",
        regulatory_authority="Inland Revenue Department (IRD)", effective_from=date(2025, 4, 1),
        source_references="IRD PAM — the employee's annual return for the year of assessment ending 31 March. "
                          "Field map computed by service.generate_hong_kong_ir56b from the employee's "
                          "committed HK payslips and the HK_EARNING_CLASS pack rows.",
        components=[
            _hk_employer,
            ("employee_info", "Employee Information", [
                ("employee_name", "Employee Name", "text", "PAYROLL_EMPLOYEE", "name", None),
                ("employee_hkid", "HKID", "text", "PAYROLL_EMPLOYEE", "hkid", None),
                ("employee_passport_number", "Passport Number", "text", "PAYROLL_EMPLOYEE", "passport_number", None),
            ]),
            ("employment", "Employment Period", [
                ("year_of_assessment", "Year of Assessment", "text", "PAYSLIP_ITEM", "gross_pay", None),
                ("employment_start", "Employment start reported", "date", "PAYROLL_EMPLOYEE", "date_of_joining", None),
                ("employment_end", "Employment end reported", "date", "PAYROLL_EMPLOYEE", "date_of_leaving", None),
            ]),
            ("remuneration", "Remuneration Details", [
                # The per-field breakdown the generator already computes from the
                # case payload (ird_<field>): earning classes mapped to an IR56B
                # field. Internal field names, NOT the IRD prescribed items (G2).
                ("ird_salary_wages", "Salary / wages (internal IRD field)", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ("ird_other_rewards_allowances", "Other rewards / allowances (internal IRD field)", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ("ird_unmapped_requires_classification", "Unclassified remuneration (blocks filing until classified)", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ("total_remuneration", "Total reportable remuneration", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ("mpf_relevant_income_total", "Total MPF relevant income", "currency", "PAYSLIP_ITEM", "gross_pay", None),
            ]),
            ("contributions", "MPF (Employee)", [
                ("mpf_employee_total", "MPF mandatory contribution (employee)", "currency", "PAYSLIP_ITEM", "employee_pension", None),
            ]),
            ("employer_contributions", "MPF (Employer)", [
                ("mpf_employer_total", "MPF mandatory contribution (employer)", "currency", "PAYSLIP_ITEM", "employer_pension", None),
            ]),
            _hk_filing_metadata,
        ],
    )

    _hk_notification_identity = [
        _hk_employer,
        ("employee_info", "Employee Information", [
            ("employee_name", "Employee Name", "text", "PAYROLL_EMPLOYEE", "name", None),
            ("employee_hkid", "HKID", "text", "PAYROLL_EMPLOYEE", "hkid", None),
            ("employee_passport_number", "Passport Number", "text", "PAYROLL_EMPLOYEE", "passport_number", None),
        ]),
    ]
    for _key, _name, _type, _event_label in [
        ("HK-IR56E", "IR56E — Employee's Notification of Commencement of Employment", "HK_IR56E", "Commencement Details"),
        ("HK-IR56F", "IR56F — Employee's Notification of Cessation of Employment", "HK_IR56F", "Cessation Details"),
    ]:
        print(f"Seeding Hong Kong {_key} employee notification (per-employee)...")
        _seed_template(
            db, template_key=_key, name=_name, report_type=_type, country="HK",
            reporting_year="2025/26", document_scope="PER_EMPLOYEE",
            description=_HK_DISCLOSURE, regulatory_authority="Inland Revenue Department (IRD)",
            effective_from=date(2025, 4, 1),
            source_references="IRD PAM — the employee's notification for this event. Field map computed by "
                              "service.generate_hong_kong_ir56_notification from the reporting case, which "
                              "hk_service builds from committed payroll.",
            components=_hk_notification_identity + [
                ("event", _event_label, [
                    ("form_type", "Form", "text", "PAYSLIP_ITEM", "gross_pay", None),
                    ("event_date", "Event date", "date", "PAYSLIP_ITEM", "gross_pay", None),
                    ("due_date", "Notification due by", "date", "PAYSLIP_ITEM", "gross_pay", None),
                    ("income_period_start", "Income period from", "date", "PAYSLIP_ITEM", "gross_pay", None),
                    ("income_period_end", "Income period to", "date", "PAYSLIP_ITEM", "gross_pay", None),
                    ("reported_total", "Remuneration reported", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ]),
                _hk_filing_metadata,
            ],
        )

    print("Seeding Hong Kong IR56G departure notification (per-employee, with the tax-clearance hold)...")
    _seed_template(
        db, template_key="HK-IR56G", name="IR56G — Employee's Notification of Departure from Hong Kong",
        report_type="HK_IR56G", country="HK", reporting_year="2025/26", document_scope="PER_EMPLOYEE",
        description=_HK_DISCLOSURE + " The amount withheld is a LEGAL HOLD under the IR56G tax clearance, not a "
                                      "deduction — net pay is unchanged and the money stays owed to the employee.",
        regulatory_authority="Inland Revenue Department (IRD)", effective_from=date(2025, 4, 1),
        source_references="IRD PAM 46(e) — the departure notification and the one-month tax-clearance hold. "
                          "Field map computed by service.generate_hong_kong_ir56_notification.",
        components=_hk_notification_identity + [
            ("event", "Departure Details", [
                ("form_type", "Form", "text", "PAYSLIP_ITEM", "gross_pay", None),
                ("event_date", "Expected departure date", "date", "PAYSLIP_ITEM", "gross_pay", None),
                ("due_date", "Notification due by", "date", "PAYSLIP_ITEM", "gross_pay", None),
                ("income_period_start", "Income period from", "date", "PAYSLIP_ITEM", "gross_pay", None),
                ("income_period_end", "Income period to", "date", "PAYSLIP_ITEM", "gross_pay", None),
                ("reported_total", "Remuneration reported", "currency", "PAYSLIP_ITEM", "gross_pay", None),
            ]),
            ("tax_clearance_hold", "Tax Clearance Hold (amount withheld)", [
                ("hold_state", "Hold state", "text", "PAYSLIP_ITEM", "gross_pay", None),
                ("hold_filing_deadline", "Filing deadline", "date", "PAYSLIP_ITEM", "gross_pay", None),
                ("hold_statutory_expiry", "Statutory hold expiry", "date", "PAYSLIP_ITEM", "gross_pay", None),
                ("amount_withheld", "Amount withheld (legal hold, not a deduction)", "currency", "PAYSLIP_ITEM", "gross_pay", None),
            ]),
            _hk_filing_metadata,
        ],
    )

    print("Seeding Hong Kong eMPF monthly remittance statement (aggregate, per contribution period)...")
    _seed_template(
        db, template_key="HK-EMPF-REMITTANCE", name="eMPF — Monthly Remittance Statement",
        report_type="HK_EMPF_REMITTANCE", country="HK", reporting_year="2026", document_scope="AGGREGATE",
        description=_HK_DISCLOSURE + " Zoiko transmits nothing to eMPF (no certified interface, G2): this "
                                      "statement is the employer's input to its own eMPF submission.",
        regulatory_authority="MPFA / eMPF platform", effective_from=date(2026, 1, 1),
        source_references="MPFA Mandatory Contributions — Employees. Field map computed by "
                          "service.generate_hong_kong_empf_remittance from the prepared eMPF submission.",
        components=[
            _hk_employer,
            ("contributions", "MPF Contributions", [
                ("contribution_period", "Contribution period", "text", "PAYSLIP_ITEM", "gross_pay", None),
                ("contribution_day", "Contribution day", "date", "PAYSLIP_ITEM", "gross_pay", None),
                ("total_relevant_income", "Total relevant income", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ("total_employer_mandatory", "Total mandatory contribution (employer)", "currency", "PAYSLIP_ITEM", "employer_pension", None),
                ("total_employee_mandatory", "Total mandatory contribution (employee)", "currency", "PAYSLIP_ITEM", "employee_pension", None),
            ]),
            ("members", "Contributing Members", [
                ("member_count", "Contributing members", "number", "PAYSLIP_ITEM", "gross_pay", None),
            ]),
            ("totals", "Period Totals", [
                ("total_relevant_income", "Total relevant income", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ("total_employer_mandatory", "Total employer mandatory contribution", "currency", "PAYSLIP_ITEM", "employer_pension", None),
                ("total_employee_mandatory", "Total employee mandatory contribution", "currency", "PAYSLIP_ITEM", "employee_pension", None),
                ("validation_error_count", "Rows with validation errors", "number", "PAYSLIP_ITEM", "gross_pay", None),
            ]),
            _hk_filing_metadata,
        ],
    )

    print("Seeding Hong Kong employee MPF contribution record (per-employee, HK-010)...")
    _seed_template(
        db, template_key="HK-MPF-CONTRIBUTION-RECORD",
        name="MPF Contribution Record (employee's own record)", report_type="HK_MPF_CONTRIBUTION_RECORD",
        country="HK", reporting_year="2026", document_scope="PER_EMPLOYEE",
        description="Employee's own MPF contribution / pay record (HK-010). NOT a filing and not an IRD form — "
                    "there is no e-file layout to disclose. Mandatory employer and employee contributions "
                    "only: MPF voluntary contributions are OUT OF SCOPE for the first release and no "
                    "voluntary-contribution subsystem exists.",
        regulatory_authority="MPFA (employee record)", effective_from=date(2026, 1, 1),
        source_references="MPFA Mandatory Contributions — Employees. Field map computed by "
                          "service.generate_hong_kong_mpf_contribution_record from the employee's committed "
                          "HK payslips, including the statutory pack pinned on each payslip's tax_rule_snapshot.",
        components=[
            _hk_employer,
            ("employee_info", "Employee Information", [
                ("employee_name", "Employee Name", "text", "PAYROLL_EMPLOYEE", "name", None),
                ("employee_hkid", "HKID", "text", "PAYROLL_EMPLOYEE", "hkid", None),
            ]),
            ("contributions", "MPF Contributions", [
                ("contribution_period", "Contribution period", "text", "PAYSLIP_ITEM", "gross_pay", None),
                ("payslip_count", "Payslips in the period", "number", "PAYSLIP_ITEM", "gross_pay", None),
                ("total_relevant_income", "Total relevant income", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ("total_employer_mandatory", "MPF mandatory contribution (employer)", "currency", "PAYSLIP_ITEM", "employer_pension", None),
                ("total_employee_mandatory", "MPF mandatory contribution (employee)", "currency", "PAYSLIP_ITEM", "employee_pension", None),
            ]),
            ("ytd", "Statutory Pack Provenance", [
                ("pack_id", "Statutory pack (HK-PAYROLL-YYYY)", "text", "PAYSLIP_ITEM", "gross_pay", None),
                ("pack_version", "Statutory pack version", "text", "PAYSLIP_ITEM", "gross_pay", None),
            ]),
            ("coverage", "MPF Coverage", [
                ("total_relevant_income", "Total relevant income", "currency", "PAYSLIP_ITEM", "gross_pay", None),
            ]),
        ],
    )

    print("Seeding Hong Kong employee termination statement (per-employee, document service)...")
    _seed_template(
        db, template_key="HK-TERMINATION-STATEMENT",
        name="Termination Statement (employee's copy)", report_type="HK_TERMINATION_STATEMENT",
        country="HK", reporting_year="2026", document_scope="PER_EMPLOYEE",
        description="Employee's termination statement rendered from an APPROVED (four-eyes) termination "
                    "calculation: SP / LSP with the 1 May 2025 pre / post transition split, permitted offsets, "
                    "final wages, annual leave pay and holiday pay. NOT a filing — nothing is transmitted.",
        regulatory_authority="Labour Department (employee document)", effective_from=date(2026, 1, 1),
        source_references="Labour Department Concise Guide ch.11 (SP / LSP) and Abolition of the MPF Offsetting "
                          "Arrangement. Field map computed by service.generate_hong_kong_termination_statement "
                          "from the approved HkgTerminationResult (evidence hash included).",
        components=[
            _hk_employer,
            ("employee_info", "Employee Information", [
                ("employee_name", "Employee Name", "text", "PAYROLL_EMPLOYEE", "name", None),
                ("employee_hkid", "HKID", "text", "PAYROLL_EMPLOYEE", "hkid", None),
            ]),
            ("termination", "Termination", [
                ("termination_date", "Termination date", "text", "PAYSLIP_ITEM", "gross_pay", None),
                ("termination_reason", "Reason", "text", "PAYSLIP_ITEM", "gross_pay", None),
                ("payment_type", "Statutory payment (SP / LSP / none)", "text", "PAYSLIP_ITEM", "gross_pay", None),
            ]),
            ("entitlement", "Severance / Long Service Payment", [
                ("pre_transition_portion", "Pre-transition portion (to 30 Apr 2025)", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ("post_transition_portion", "Post-transition portion (from 1 May 2025)", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ("gross_entitlement", "Gross entitlement", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ("total_offsets", "Permitted offsets", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ("net_statutory_payment", "Net statutory payment", "currency", "PAYSLIP_ITEM", "gross_pay", None),
            ]),
            ("final_payment", "Final Payment", [
                ("final_wages", "Final wages", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ("annual_leave_pay", "Annual leave pay", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ("holiday_pay", "Holiday pay", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ("total_final_payment", "Total final payment", "currency", "PAYSLIP_ITEM", "gross_pay", None),
                ("payment_hold", "Payment hold (IR56G)", "text", "PAYSLIP_ITEM", "gross_pay", None),
                ("evidence_hash", "Calculation evidence hash", "text", "PAYSLIP_ITEM", "gross_pay", None),
            ]),
        ],
    )

    # Hong Kong filing calendar (ZP-HK-ENG-001 §7, HK-011). BIR56A / IR56B
    # are issued on the first working day of April and are due within one
    # month of issue; the IR56 notification deadlines are themselves
    # resolved from the statutory pack at run time, not hard-coded here, so
    # only the employer-level annual return gets calendar rows (the same
    # restraint India uses — it seeds Form 138's quarters, not per-employee
    # notification deadlines).
    print("Seeding Hong Kong filing calendar (BIR56A / IR56B annual return)...")
    for period_key, period_label, due_date in [
        ("ANNUAL-2025/26", "Year of assessment 2025/26 (issued 1 Apr 2026)", "2026-05-01"),
        ("ANNUAL-2026/27", "Year of assessment 2026/27 (issued 1 Apr 2027)", "2027-05-01"),
    ]:
        year = period_key.split("-")[1]
        for report_type, label in (("HK_BIR56A", "BIR56A"), ("HK_IR56B", "IR56B")):
            entry = service.upsert_filing_calendar_entry(
                db, FilingCalendarUpsert(
                    jurisdictionCountry="HK", reportType=report_type, reportingYear=year,
                    periodKey=period_key, periodLabel=f"{label} — {period_label}", dueDate=due_date,
                ), actor_id=None,
            )
            print(f"  seeded HK {report_type} {period_key} due {due_date} (id={entry.id}, status={entry.status})")


if __name__ == "__main__":
    run()
