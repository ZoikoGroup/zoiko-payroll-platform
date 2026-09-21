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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.modules.payroll import service
from app.modules.payroll.models import ReportTemplate
from app.modules.payroll.schemas import (
    ReportTemplateUpsert, ReportTemplateComponentUpsert, ReportTemplateFieldUpsert, FilingCalendarUpsert,
)


def _seed_template(db, *, template_key, name, report_type, country, reporting_year, document_scope, components, state=None):
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
    """
    existing = (
        db.query(ReportTemplate)
        .filter(ReportTemplate.template_key == template_key, ReportTemplate.version == "1.0")
        .first()
    )
    if existing is not None and existing.status not in ("Draft", "Review", "Approved"):
        print(f"  SKIP {template_key} v{existing.version} — already {existing.status} in production (id={existing.id}); not re-seeding.")
        return existing

    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=template_key, name=name, reportType=report_type,
            jurisdictionCountry=country, jurisdictionState=state, reportingYear=reporting_year, documentScope=document_scope,
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
                    ("lohnsteuer", "Lohnsteuer", "currency", "PAYSLIP_ITEM", "tds", None),
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
                    ("lohnsteuer_ytd", "Lohnsteuer (Year-to-Date)", "currency", "PAYSLIP_ITEM", "tds", "SUM_YTD"),
                    ("soli_ytd", "Solidaritätszuschlag (Year-to-Date)", "currency", "PAYSLIP_ITEM", "soli", "SUM_YTD"),
                    ("church_tax_ytd", "Kirchensteuer (Year-to-Date)", "currency", "PAYSLIP_ITEM", "church_tax", "SUM_YTD"),
                ]),
            ],
        )

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
                    ("total_lohnsteuer", "Total Lohnsteuer", "currency", "PAYSLIP_ITEM", "tds", "SUM_RUN"),
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

        print("\nDone. All templates are in Draft status — a Super Admin still needs to review, Approve, Publish, and Activate each one before Organizations can generate against it.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
