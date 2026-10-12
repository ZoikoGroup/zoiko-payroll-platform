"""
scripts/seed_hong_kong_canonical_pack.py
----------------------------------------
Seeds the canonical (organization_id IS NULL) Hong Kong rule packs as DRAFT —
JurisdictionPack + ContributionRate + TaxSlab rows + SourceArtifact evidence —
the same DB-driven shape as seed_singapore_canonical_pack.py.

  HK-PAYROLL-2025 v1.0  year of assessment 2025/26 (1 Apr 2025 – 31 Mar 2026)
  HK-PAYROLL-2026 v1.0  year of assessment 2026/27 (1 Apr 2026 – 31 Mar 2027)

Lineage (ZP-HK-ENG-001 Step 15): official authority → SourceArtifact (URL,
retrieval time, SHA-256 of the exact bytes retrieved 2026-09-30) → pack row
(source_document_id per row) → resolver → calculation trace → payslip.

Sources: ZP-HK-ENG-001 v1.0 (22 Sep 2026) + IRD / MPFA / Labour Department
publications in SOURCES below. Where an official source differs from the
specification the SOURCE wins and the difference is recorded:
  * 2026/27 allowances — the spec's Step 6 lists the allowance NAMES only; the
    amounts are IRD PAM 61(e) (Aug 2026): basic HK$145,000, married HK$290,000,
    child HK$140,000 … (increased by the 2026-27 Budget).
  * IR56G hold — spec §8 "until a letter of release"; IRD PAM 46(e): one month
    from filing OR the letter of release, WHICHEVER IS EARLIER (both release
    conditions implemented in tax_clearance.py; neither is automatic).

Rows seeded with an explicit G1 CERTIFICATION flag (label suffix "[G1]" and a
SourceArtifact titled "[UNVERIFIED — G1]") where the official text could not
be retrieved or the interpretation needs the Hong Kong specialist sign-off:
  * eo_week_start_day (Cap. 57 s.2 "week"; statutory text not retrievable),
  * mpf_partial_month_threshold_basis (monthly levels for a monthly-paid
    employee's incomplete first/last month),
  * every HK_EARNING_CLASS row (spec "Open implementation decisions": a
    specialist must certify earning classifications).

Nothing is ever set Active here: activation goes through Super Admin
maker-checker, linked evidence, G1 acceptance and a passing HK golden run
(service.set_jurisdiction_pack_status). The service-registry row is created
PLANNED only when missing. Re-running refuses to touch a pack that left
Draft; identical rows are kept (idempotent, same reconcile as SG).

Usage (local / disposable databases only — scripts/_local_db_guard):
    python -m scripts.seed_hong_kong_canonical_pack
"""
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, initialize_database  # noqa: E402
from app.modules.payroll.models import ContributionRate, JurisdictionPack, SourceArtifact, TaxSlab  # noqa: E402
from scripts._local_db_guard import assert_local_database  # noqa: E402

CODE = "HK"
SPEC = "ZP-HK-ENG-001 v1.0 (22 Sep 2026)"
RETRIEVED_AT = datetime(2026, 9, 30, 6, 0, 0, tzinfo=timezone.utc)

# key -> (agency, title, url, sha256 of the retrieved bytes, publication date)
SOURCES = {
    "ird_pam61e": ("Inland Revenue Department", "PAM 61(e) Allowances, Deductions and Tax Rate Table (Aug 2026)",
                   "https://www.ird.gov.hk/eng/pdf/pam61e.pdf",
                   "357f13eb3f93bfaff98e8027e0974aef08abc683e561ca9959e488d517969152", date(2026, 8, 1)),
    "ird_budget_2627": ("Inland Revenue Department", "2026-27 Budget — Tax Measures",
                        "https://www.ird.gov.hk/eng/tax/budget.htm",
                        "34aa86e582fcfa6cea962cee245ea72b64c7ea3a0d054c05c9763f0e91691b7c", None),
    "ird_example2627": ("Inland Revenue Department", "2026-27 Budget — Tax Measures: worked examples",
                        "https://www.ird.gov.hk/eng/pdf/2026/example2627.pdf",
                        "52aea360758c7b21a8ce98f5112d531e84a84d36c3b05a51e259680b46eedd83", None),
    "ird_employers": ("Inland Revenue Department", "Employers — BIR56A/IR56B, IR56E/F/G obligations",
                      "https://www.ird.gov.hk/eng/tax/ere.htm",
                      "f3c47471346d6b50b7596049ad3b37fc5b065889fafecc3ae77c1a4c1788e9a0", None),
    "ird_pam46e": ("Inland Revenue Department", "PAM 46(e) You or your employee is going to leave Hong Kong",
                   "https://www.ird.gov.hk/eng/pdf/pam46e.pdf",
                   "fee4eaa115d6f4b0b0846696eabe7d6e9056ab9eb2ce5632b8f86624111dc808", None),
    "mpfa_employees": ("Mandatory Provident Fund Schemes Authority", "Mandatory Contributions — Employees",
                       "https://www.mpfa.org.hk/en/mpf-system/mandatory-contributions/employees",
                       "97b6c8c42685fc848dd1584453aada7d9cc1c2afe2399ed11e9947014449f35c", None),
    "mpfa_coverage": ("Mandatory Provident Fund Schemes Authority", "MPF Coverage (regular employees, exempt persons)",
                      "https://www.mpfa.org.hk/en/mpf-system/mpf-coverage",
                      "175f278de736e6c1f502ae8d4bb1364a20a02df2c6a1a15a41ef9a0b7a797599", None),
    "ld_smw": ("Labour Department", "Statutory Minimum Wage",
               "https://www.labour.gov.hk/eng/news/mwo.htm",
               "11e750937bf71eab322f94adb536452f1372c0f8a26fa51a56a71608f7695d1e", None),
    "isd_smw_2026": ("HKSAR Government (ISD)", "New SMW rate of $43.1 per hour takes effect today (1 May 2026)",
                     "https://www.info.gov.hk/gia/general/202605/01/P2026043000261.htm",
                     "25f1e8b7485aa32e069c0dbaf392764b51995b2e47dbc8eff71f6d3df871333f", date(2026, 5, 1)),
    "isd_smw_2025": ("HKSAR Government (ISD)", "New SMW rate of $42.1 per hour takes effect today (1 May 2025)",
                     "https://www.info.gov.hk/gia/general/202505/01/P2025042900231.htm",
                     "f0125621b0b89ea78d51f4c383d00e4e24617010581a87bf359e83e464c857e8", date(2025, 5, 1)),
    "ld_eao2025": ("Labour Department", "Revise the 'Continuous Contract' Requirement (Employment (Amendment) Ordinance 2025)",
                   "https://www.labour.gov.hk/eng/news/EAO2025.htm",
                   "abe141556c48541f662de599298e43f6474a98e8e72ed8990cd018583c9c6b88", None),
    "ird_adc": ("Inland Revenue Department",
                "Increasing ceiling amount for concessionary deductions allowable for home loan interest and domestic rent",
                "https://www.ird.gov.hk/eng/tax/adc.htm",
                "cfaca97642542753892a2143ed875f978b6c58d0234a3122ded873a06243eddc", None),
    "ld_cc_edutool": ("Labour Department", "Education Tool on New 'Continuous Contract' Requirement (Note 1: the 468 rule "
                                          "does not apply to the first three weeks of a new employment)",
                      "https://www.labour.gov.hk/eng/labour/Continuous_Contract_EduTool.htm",
                      "b92a44121ad8d0f10b671cb43d9431d553cbd399011071d5d3635917b00f1e67", None),
    "ld_cg_01": ("Labour Department", "Concise Guide to the Employment Ordinance — Ch.1 Application (continuous contract)",
                 "https://www.labour.gov.hk/eng/public/wcp/ConciseGuide/01.pdf",
                 "c328c40a98d9bf24963f2cac3636bba802b2d82200a196794744c2ade826536f", None),
    "ld_cg_03": ("Labour Department", "Concise Guide — Ch.3 Wages",
                 "https://www.labour.gov.hk/eng/public/wcp/ConciseGuide/03.pdf",
                 "dd61788183c75fca935308466a13dcf1450e00769a7f9a10257b565f5c1aff99", None),
    "ld_cg_04": ("Labour Department", "Concise Guide — Ch.4 Rest Days, Holidays and Leave",
                 "https://www.labour.gov.hk/eng/public/wcp/ConciseGuide/04.pdf",
                 "9cc70ff9e4fdc62a9eeda51239a794c010b6c978b07b2ceda0c79deeae3058b0", None),
    "ld_cg_05": ("Labour Department", "Concise Guide — Ch.5 Sickness Allowance",
                 "https://www.labour.gov.hk/eng/public/wcp/ConciseGuide/05.pdf",
                 "f368735f9f77240a4854c55574e82a36ded3df023d380310b93eed83d6ffee22", None),
    "ld_cg_06": ("Labour Department", "Concise Guide — Ch.6 Maternity Protection",
                 "https://www.labour.gov.hk/eng/public/wcp/ConciseGuide/06.pdf",
                 "23988131d3fd53ab16057f5a93ffe967a23a3c5e0f2904fbcf0100cf62dc4150", None),
    "ld_cg_07": ("Labour Department", "Concise Guide — Ch.7 Paternity Leave",
                 "https://www.labour.gov.hk/eng/public/wcp/ConciseGuide/07.pdf",
                 "bb4ada8c1ac3c472c69c577d3d27b84b8ed972668149fe0f2922e40ff6bea0e2", None),
    "ld_cg_11": ("Labour Department", "Concise Guide — Ch.11 Severance Payment and Long Service Payment",
                 "https://www.labour.gov.hk/eng/public/wcp/ConciseGuide/11.pdf",
                 "ef8fe29153964c3a4b9c8905d813fba18cc95d236a937fef262a9c29121037b0", None),
    "ld_cg_app1": ("Labour Department", "Concise Guide — Appendix 1: 12-Month Average Wages",
                   "https://www.labour.gov.hk/eng/public/wcp/ConciseGuide/Appendix1.pdf",
                   "dc9e32d8be3f5f48be21969621b090d9859782efefdf257f42e273edde3d6595", None),
    "ld_holidays_2025": ("Labour Department", "Statutory Holidays for 2025",
                         "https://www.labour.gov.hk/eng/news/latest_holidays2025.htm",
                         "dcf353421d6ce60ca9da6319aa901fad4b3818f43d5ba680add29a49ae3bc445", None),
    "ld_holidays_2026": ("Labour Department", "Statutory Holidays for 2026",
                         "https://www.labour.gov.hk/eng/news/latest_holidays2026.htm",
                         "4fe56c8677a98a26b999f459a2ebc5a7828b56ed2af51a78eb816d2037eb28d2", None),
    "ld_holidays_2027": ("Labour Department", "Statutory Holidays for 2027",
                         "https://www.labour.gov.hk/eng/news/latest_holidays2027.htm",
                         "9eebdd134cfe17c2a8fde140d2db3f3fc38c2ad817f9f2e8e7f615f287ee5e8a", None),
    "ld_aoa": ("Labour Department", "Abolition of MPF Offsetting — employment commencing before 1 May 2025",
               "https://www.op.labour.gov.hk/en/before-1-may.html",
               "4c40afaa941fd852fc8fcf476c6729afcfe3981eb9557c17a888bf388e1f3c10", None),
    "pcpd_hr_code": ("Office of the Privacy Commissioner for Personal Data", "Code of Practice on Human Resource Management",
                     "https://www.pcpd.org.hk/english/data_privacy_law/code_of_practices/code_hrm.html",
                     "abf4fe7a83e0af605914641e80a2ffb471e930e6b6503cc8c0ad2b2fea04ee9e", None),
    # G1: the Cap. 57 s.2 "week" definition could not be retrieved (eLegislation
    # needs a browser). The value below is recorded, flagged, and must be
    # confirmed by the Hong Kong specialist before activation.
    "g1_eo_week": ("Hong Kong specialist (G1) — pending",
                   "[UNVERIFIED — G1] Employment Ordinance Cap. 57 s.2 definition of 'week' (continuous contract)",
                   "https://www.elegislation.gov.hk/hk/cap57", None, None),
}

YA_2025 = {"pack_id": "HK-PAYROLL-2025", "version": "1.0", "tax_year": "2025/26",
           "effective_from": date(2025, 4, 1), "effective_to": date(2026, 3, 31)}
YA_2026 = {"pack_id": "HK-PAYROLL-2026", "version": "1.0", "tax_year": "2026/27",
           "effective_from": date(2026, 4, 1), "effective_to": date(2027, 3, 31)}

# ── Rows common to both years (same official value throughout both windows) ──
# (component_key, label, source_key, kwargs)
COMMON_RATES = [
    ("mpf_employee_rate", "MPF employee mandatory contribution rate", "mpfa_employees", dict(employee_rate_pct="0.05")),
    ("mpf_employer_rate", "MPF employer mandatory contribution rate", "mpfa_employees", dict(employer_rate_pct="0.05")),
    ("mpf_min_relevant_income_monthly", "MPF minimum relevant income — monthly", "mpfa_employees", dict(flat_amount="7100")),
    ("mpf_max_relevant_income_monthly", "MPF maximum relevant income — monthly", "mpfa_employees", dict(flat_amount="30000")),
    ("mpf_min_relevant_income_daily", "MPF minimum relevant income — daily (non-monthly)", "mpfa_employees", dict(flat_amount="280")),
    ("mpf_max_relevant_income_daily", "MPF maximum relevant income — daily (non-monthly)", "mpfa_employees", dict(flat_amount="1000")),
    ("mpf_regular_employee_min_age", "MPF regular employee — minimum age", "mpfa_coverage", dict(flat_amount="18")),
    ("mpf_regular_employee_max_age", "MPF regular employee — maximum age", "mpfa_coverage", dict(flat_amount="64")),
    ("mpf_regular_employee_days", "MPF regular employee — continuous employment days", "mpfa_coverage", dict(flat_amount="60")),
    ("mpf_employee_holiday_days", "MPF employee contribution holiday — days", "mpfa_employees", dict(flat_amount="30")),
    ("mpf_contribution_day", "MPF contribution day (day of following month)", "mpfa_employees", dict(flat_amount="10")),
    ("mpf_partial_month_threshold_basis", "MPF levels for an incomplete monthly wage period [G1]", "mpfa_employees",
     dict(text_value="MONTHLY_LEVELS")),
    # The MPF mandatory-contribution Salaries Tax ceiling is NOT seeded here: one
    # statutory fact, one row. It lives in the deduction-ceiling table as
    # hk_deduction_mandatory_contributions, which is what salaries_tax resolves.
    ("eo_cc_legacy_weekly_hours", "Continuous contract before 18 Jan 2026 — hours each week (4-18)", "ld_eao2025", dict(flat_amount="18")),
    ("eo_cc_weekly_hours", "Continuous contract from 18 Jan 2026 — hours each week", "ld_eao2025", dict(flat_amount="17")),
    ("eo_cc_four_week_hours", "Continuous contract from 18 Jan 2026 — hours in 4 weeks", "ld_eao2025", dict(flat_amount="68")),
    ("eo_cc_min_weeks", "Continuous contract — minimum weeks of continuous employment", "ld_cg_01", dict(flat_amount="4")),
    ("eo_cc_468_effective_date", "Continuous contract 4-week 17/68 rule effective date", "ld_eao2025", dict(text_value="2026-01-18")),
    ("eo_cc_468_first_weeks", "Continuous contract — first weeks of a NEW employment with no 68-hour alternative",
     "ld_cc_edutool", dict(flat_amount="3")),
    ("eo_week_start_day", "Employment Ordinance statutory week start [G1]", "g1_eo_week", dict(text_value="SUNDAY")),
    ("eo_four_fifths_factor", "Sickness / maternity / paternity pay factor (4/5)", "ld_cg_05", dict(text_value="4/5")),
    ("eo_sickness_days_per_month_first_year", "Paid sickness days per completed month — first 12 months", "ld_cg_05", dict(flat_amount="2")),
    ("eo_sickness_days_per_month_after", "Paid sickness days per completed month — thereafter", "ld_cg_05", dict(flat_amount="4")),
    ("eo_sickness_days_cap", "Paid sickness days — maximum accumulated", "ld_cg_05", dict(flat_amount="120")),
    ("eo_sickness_min_consecutive_days", "Sickness allowance — minimum consecutive sick days", "ld_cg_05", dict(flat_amount="4")),
    ("eo_holiday_pay_cc_months", "Holiday pay — continuous contract months before the holiday", "ld_cg_04", dict(flat_amount="3")),
    ("eo_maternity_leave_weeks", "Maternity leave — weeks", "ld_cg_06", dict(flat_amount="14")),
    ("eo_maternity_pay_cc_weeks", "Maternity leave pay — continuous contract weeks before leave", "ld_cg_06", dict(flat_amount="40")),
    ("eo_maternity_weeks_11_14_cap", "Maternity leave pay — cap for weeks 11 to 14", "ld_cg_06", dict(flat_amount="80000")),
    ("eo_paternity_leave_days", "Paternity leave — days", "ld_cg_07", dict(flat_amount="5")),
    ("eo_paternity_pay_cc_weeks", "Paternity leave pay — continuous contract weeks before leave", "ld_cg_07", dict(flat_amount="40")),
    ("eo_wage_payment_days", "Wages — latest payment, days after the wage period ends", "ld_cg_03", dict(flat_amount="7")),
    ("sp_lsp_monthly_wage_cap", "SP/LSP monthly wage ceiling", "ld_cg_11", dict(flat_amount="22500")),
    ("sp_lsp_wage_fraction", "SP/LSP wage fraction (2/3)", "ld_cg_11", dict(text_value="2/3")),
    ("sp_lsp_overall_cap", "SP/LSP overall maximum", "ld_cg_11", dict(flat_amount="390000")),
    ("sp_min_months", "Severance payment — continuous contract months", "ld_cg_11", dict(flat_amount="24")),
    ("lsp_min_years", "Long service payment — continuous contract years", "ld_cg_11", dict(flat_amount="5")),
    ("sp_lsp_daily_rated_days", "SP/LSP daily-rated — days' wages", "ld_cg_11", dict(flat_amount="18")),
    ("lsp_resignation_min_age", "LSP on resignation — minimum age", "ld_cg_11", dict(flat_amount="65")),
    ("mpf_offset_transition_date", "Abolition of MPF offsetting — transition date", "ld_aoa", dict(text_value="2025-05-01")),
    ("ird_ir56e_months", "IR56E — months after commencement", "ird_employers", dict(flat_amount="3")),
    ("ird_ir56f_months_before", "IR56F — months before cessation", "ird_employers", dict(flat_amount="1")),
    ("ird_ir56g_months_before", "IR56G — months before departure", "ird_pam46e", dict(flat_amount="1")),
    ("ird_ir56g_hold_months", "IR56G — withholding months from filing (or letter of release, earlier)", "ird_pam46e",
     dict(flat_amount="1")),
    ("ird_ir56g_absence_months", "IR56G — absence exceeding this many months requires notification", "ird_pam46e",
     dict(flat_amount="1")),
    ("ird_ir56b_due_months", "BIR56A / IR56B — months after issue of the return", "ird_employers", dict(flat_amount="1")),
    ("ird_return_issue_month", "BIR56A / IR56B — month the return is issued (number)", "ird_employers", dict(flat_amount="4")),
    ("ird_return_issue_day", "BIR56A / IR56B — day of month the return is issued", "ird_employers", dict(flat_amount="1")),
]

# SMW + hours-record cap: row-level effective windows (a wage period crossing
# 1 May sees both rows through the service's period segments).
SMW_ROWS = [
    # (from, to, hourly rate, record cap, source)
    (date(2023, 5, 1), date(2025, 4, 30), "40.00", "16300", "isd_smw_2025"),
    (date(2025, 5, 1), date(2026, 4, 30), "42.10", "17200", "isd_smw_2025"),
    (date(2026, 5, 1), None, "43.10", "17600", "isd_smw_2026"),
]

# Salaries Tax (informational) — PAM 61(e).
ALLOWANCES = {
    # key: (2025/26, 2026/27)
    "hk_allowance_basic": ("Basic allowance", "132000", "145000"),
    "hk_allowance_married": ("Married person's allowance", "264000", "290000"),
    "hk_allowance_single_parent": ("Single parent allowance", "132000", "145000"),
    "hk_allowance_child": ("Child allowance (each of 1st–9th child)", "130000", "140000"),
    "hk_allowance_child_additional": ("Additional child allowance (year of birth)", "130000", "140000"),
    "hk_allowance_dependent_parent_60": ("Dependent parent/grandparent allowance (60+ / disability)", "50000", "55000"),
    "hk_allowance_dependent_parent_55": ("Dependent parent/grandparent allowance (55–59)", "25000", "27500"),
    "hk_allowance_dependent_parent_60_additional": ("Additional dependent parent/grandparent (60+, living with)", "50000", "55000"),
    "hk_allowance_dependent_parent_55_additional": ("Additional dependent parent/grandparent (55–59, living with)", "25000", "27500"),
    "hk_allowance_personal_disability": ("Personal disability allowance", "75000", "75000"),
    "hk_allowance_disabled_dependant": ("Disabled dependant allowance", "75000", "75000"),
    "hk_allowance_dependent_sibling": ("Dependent brother or sister allowance", "37500", "37500"),
}
PROGRESSIVE_BANDS = [("0", "50000", "2"), ("50000", "100000", "6"), ("100000", "150000", "10"),
                     ("150000", "200000", "14"), ("200000", None, "17")]
STANDARD_TIERS = [("0", "5000000", "15"), ("5000000", None, "16")]

# Deduction CEILINGS, per year of assessment (PAM 61(e) §3). These are caps on
# what the employee may DEDUCT from assessable income — the ceilings, not the
# employee's actual amounts, which stay operator input. The informational
# Salaries Tax estimate caps each claim to the row for its year, so a pack can
# never produce a deduction the IRD would disallow. Elderly residential care
# expenses are new for YA 2026/27 (Allowance (Amendment) Bill 2026).
#   key: (label, 2025/26, 2026/27)
DEDUCTION_CEILINGS = {
    "hk_deduction_mandatory_contributions": ("Deduction — mandatory contributions to recognised retirement schemes", "18000", "18000"),
    "hk_deduction_self_education": ("Deduction — self-education expenses (ceiling)", "100000", "100000"),
    "hk_deduction_home_loan_interest": ("Deduction — home loan interest (ceiling)", "100000", "100000"),
    "hk_deduction_elderly_residential_care": ("Deduction — elderly residential care expenses (ceiling)", "100000", "110000"),
    "hk_deduction_domestic_rents": ("Deduction — domestic rents (ceiling)", "100000", "100000"),
    # A FRACTION (0.35 = 35%), the ContributionRate.employee_rate_pct convention.
    "hk_deduction_approved_donation_pct": ("Deduction — approved charitable donations (share of income)", "0.35", "0.35"),
    "hk_deduction_mpf_voluntary": ("Deduction — voluntary MPF contributions / annuity premiums (ceiling)", "60000", "60000"),
    "hk_deduction_assisted_reproductive": ("Deduction — assisted reproductive service expenses (ceiling)", "100000", "100000"),
    "hk_deduction_qvhi_premium": ("Deduction — qualifying voluntary health insurance premium (per person)", "8000", "8000"),
}
# From YA 2024/25 the HLI and domestic-rent ceilings rise by an ADDITIONAL
# HK$20,000 for a taxpayer residing with a child born on or after 25 Oct 2023,
# by written election, for up to 19 years of assessment (IRD "Increasing ceiling
# amount …", ird_adc; PAM 61(e) "Additional 20,000"). Applied only when the
# estimate is told the election was made.
ADDITIONAL_CEILINGS = {
    "hk_deduction_home_loan_interest_additional": ("Deduction — home loan interest ADDITIONAL ceiling (elected)", "20000", "20000"),
    "hk_deduction_domestic_rents_additional": ("Deduction — domestic rents ADDITIONAL ceiling (elected)", "20000", "20000"),
}
# Claims the IRD limits to a PERCENTAGE rather than a money ceiling — reported
# as a percentage, applied by the estimate to the assessable income base.
DEDUCTION_PERCENT_KEYS = ("hk_deduction_approved_donation_pct",)
ANNUAL_LEAVE_SCALE = [(1, 1, 7), (2, 2, 7), (3, 3, 8), (4, 4, 9), (5, 5, 10), (6, 6, 11), (7, 7, 12), (8, 8, 13), (9, None, 14)]

# Employment Ordinance day-count CONVENTIONS (not allowances/rates, but a
# literal in code that a regulator would still read as a rule). Seeded with
# their authority so the arithmetic is traceable and re-certified on review.
EO_CONVENTIONS = [
    ("eo_days_per_year", "SP/LSP reckonable — days in a year (pro-rata convention)", "ld_cg_11", dict(flat_amount="365")),
    ("eo_average_wage_months", "12-month average wage — months in the averaging period", "ld_cg_app1", dict(flat_amount="12")),
    ("eo_average_wage_days_per_year", "12-month average wage — days in the averaging period [G1]", "ld_cg_app1",
     dict(flat_amount="365")),
    ("eo_sickness_first_year_months", "Sickness allowance — months counted as the FIRST year of employment", "ld_cg_05",
     dict(flat_amount="12")),
    ("eo_maternity_full_pay_weeks", "Maternity leave pay — fully paid weeks (1 to 10)", "ld_cg_06", dict(flat_amount="10")),
    ("eo_overtime_aw_test_share_pct", "12-month average wage — overtime inclusion test (% threshold) [G1]", "ld_cg_app1",
     dict(flat_amount="20")),
    # NOTE: there is deliberately NO "statutory holidays per year" count row.
    # The holiday calendar is enumerated per calendar year from the Labour
    # Department's own annual list (HOLIDAYS below, one source-backed slab row
    # per day); a static count would be a second, uncitable statement of the
    # same fact that could disagree with that list.
    ("mpf_inbound_exempt_months", "MPF exemption — employee employed in HK for fewer months", "mpfa_coverage", dict(flat_amount="13")),
]

HOLIDAYS = {
    2025: ("ld_holidays_2025", [
        ("2025-01-01", "The first day of January"), ("2025-01-29", "Lunar New Year's Day"),
        ("2025-01-30", "The second day of Lunar New Year"), ("2025-01-31", "The third day of Lunar New Year"),
        ("2025-04-04", "Ching Ming Festival"), ("2025-05-01", "Labour Day"), ("2025-05-05", "The Birthday of the Buddha"),
        ("2025-05-31", "Tuen Ng Festival"), ("2025-07-01", "HKSAR Establishment Day"), ("2025-10-01", "National Day"),
        ("2025-10-07", "The day following the Chinese Mid-Autumn Festival"), ("2025-10-29", "Chung Yeung Festival"),
        ("2025-12-21", "Chinese Winter Solstice Festival (or 25 Dec, employer's option)"),
        ("2025-12-26", "The first weekday after Christmas Day")]),
    2026: ("ld_holidays_2026", [
        ("2026-01-01", "The first day of January"), ("2026-02-17", "Lunar New Year's Day"),
        ("2026-02-18", "The second day of Lunar New Year"), ("2026-02-19", "The third day of Lunar New Year"),
        ("2026-04-05", "Ching Ming Festival"), ("2026-04-06", "Easter Monday"), ("2026-05-01", "Labour Day"),
        ("2026-05-24", "The Birthday of the Buddha"), ("2026-06-19", "Tuen Ng Festival"),
        ("2026-07-01", "HKSAR Establishment Day"), ("2026-09-26", "The day following the Chinese Mid-Autumn Festival"),
        ("2026-10-01", "National Day"), ("2026-10-18", "Chung Yeung Festival"),
        ("2026-12-22", "Chinese Winter Solstice Festival (or 25 Dec, employer's option)"),
        ("2026-12-26", "The first weekday after Christmas Day")]),
    2027: ("ld_holidays_2027", [
        ("2027-01-01", "The first day of January"), ("2027-02-06", "Lunar New Year's Day"),
        ("2027-02-08", "The third day of Lunar New Year"), ("2027-02-09", "The fourth day of Lunar New Year"),
        ("2027-03-29", "Easter Monday"), ("2027-04-05", "Ching Ming Festival"), ("2027-05-01", "Labour Day"),
        ("2027-05-13", "The Birthday of the Buddha"), ("2027-06-09", "Tuen Ng Festival"),
        ("2027-07-01", "HKSAR Establishment Day"), ("2027-09-16", "The day following the Chinese Mid-Autumn Festival"),
        ("2027-10-01", "National Day"), ("2027-10-08", "Chung Yeung Festival"),
        ("2027-12-22", "Chinese Winter Solstice Festival (or 25 Dec, employer's option)"),
        ("2027-12-27", "The first weekday after Christmas Day")]),
}

# Earning classification [G1] — (component, obligation) -> (basis, IRD field, source key)
_EO, _MPF, _SMW, _IRD = "EO_WAGES", "MPF_RI", "SMW_WAGES", "IRD"
EARNING_CLASSES = {
    "basic": {_EO: ("INCLUDED", None, "ld_cg_03"), _MPF: ("INCLUDED", None, "mpfa_employees"),
              _SMW: ("INCLUDED", None, "ld_smw"), _IRD: ("INCLUDED", "SALARY_WAGES", "ird_employers")},
    "hra": {_EO: ("INCLUDED", None, "ld_cg_03"), _MPF: ("INCLUDED", None, "mpfa_employees"),
            _SMW: ("INCLUDED", None, "ld_smw"), _IRD: ("INCLUDED", "OTHER_REWARDS_ALLOWANCES", "ird_employers")},
    "special_allowance": {_EO: ("INCLUDED", None, "ld_cg_03"), _MPF: ("INCLUDED", None, "mpfa_employees"),
                          _SMW: ("INCLUDED", None, "ld_smw"), _IRD: ("INCLUDED", "OTHER_REWARDS_ALLOWANCES", "ird_employers")},
    "named_allowances": {_EO: ("REVIEW", None, "ld_cg_03"), _MPF: ("INCLUDED", None, "mpfa_employees"),
                         _SMW: ("REVIEW", None, "ld_smw"), _IRD: ("INCLUDED", "OTHER_REWARDS_ALLOWANCES", "ird_employers")},
    "overtime": {_EO: ("INCLUDED", None, "ld_cg_03"), _MPF: ("INCLUDED", None, "mpfa_employees"),
                 _SMW: ("INCLUDED", None, "ld_smw"), _IRD: ("INCLUDED", "SALARY_WAGES", "ird_employers")},
    "additional_compensation": {_EO: ("REVIEW", None, "ld_cg_03"), _MPF: ("INCLUDED", None, "mpfa_employees"),
                                _SMW: ("REVIEW", None, "ld_smw"),
                                _IRD: ("INCLUDED", "UNMAPPED_REQUIRES_CLASSIFICATION", "ird_employers")},
}


def _dec(value):
    return None if value is None else Decimal(str(value))


def _upsert_sources(db) -> dict:
    """One SourceArtifact per document, matched by URL + hash (a changed
    document becomes a NEW artifact). Unreviewed — an independent reviewer
    must still mark each one reviewed."""
    ids = {}
    for key, (agency, title, url, sha256, published) in SOURCES.items():
        q = db.query(SourceArtifact).filter(SourceArtifact.source_url == url)
        q = q.filter(SourceArtifact.checksum_sha256 == sha256) if sha256 else q.filter(SourceArtifact.checksum_sha256.is_(None))
        row = q.first()
        if row is None:
            row = SourceArtifact(agency=agency, title=title, source_url=url, checksum_sha256=sha256,
                                 publication_date=published, retrieved_at=RETRIEVED_AT)
            db.add(row)
            db.flush()
        ids[key] = row.id
    return ids


def _upsert_pack(db, spec, source_ids):
    pack = (db.query(JurisdictionPack)
            .filter(JurisdictionPack.pack_id == spec["pack_id"], JurisdictionPack.version == spec["version"]).first())
    if pack is not None and pack.status != "Draft":
        raise SystemExit(f"{spec['pack_id']} v{spec['version']} is {pack.status!r}, not Draft — refusing to rewrite a "
                         "pack that has entered review/approval. Create a new version from Super Admin instead.")
    created = pack is None
    if created:
        pack = JurisdictionPack(pack_id=spec["pack_id"], jurisdiction_country=CODE, version=spec["version"])
        db.add(pack)
    pack.jurisdiction_state = None
    pack.pack_type = "tax"
    pack.status = "Draft"
    pack.effective_from, pack.effective_to = spec["effective_from"], spec["effective_to"]
    pack.tax_year = spec["tax_year"]
    pack.currency = "HKD"
    pack.regulatory_authority = "IRD; MPFA; Labour Department"
    pack.compliance_category = "MPF / SMW / Employment Ordinance / SP-LSP / IRD reporting (no PAYE)"
    pack.compliance_owner = "Super Admin — Hong Kong build"
    pack.source_document_id = source_ids["ird_pam61e"]
    pack.change_summary = (
        f"v1.0 — {SPEC}: year of assessment {spec['tax_year']}. MPF (5%/5%, HK$7,100/30,000, daily HK$280/1,000, "
        "60-day rule, 30-day holiday), SMW with effective-dated rows (HK$40.00 → 42.10 on 1 May 2025 → 43.10 on "
        "1 May 2026) and the hours-record cap, continuous contract 4-18 → 4-week 17/68 (18 Jan 2026), EO leave / "
        "sickness / maternity / paternity parameters, statutory holidays, SP/LSP (HK$22,500 / 2/3 / HK$390,000, "
        "1 May 2025 transition), IRD reporting timings, informational Salaries Tax (PAM 61(e)). No payroll "
        "withholding. [G1] rows need specialist certification before activation."
    )
    pack.source_references = f"{SPEC}; " + "; ".join(
        f"{a} — {t} <{u}>" + (f" sha256:{h}" if h else " (not retrieved — G1)") for a, t, u, h, _p in SOURCES.values())
    db.flush()
    prior = {model: [i for (i,) in db.query(model.id).filter(model.jurisdiction_pack_id == pack.id,
                                                              model.organization_id.is_(None))]
             for model in (ContributionRate, TaxSlab)}
    return pack, created, prior


def _display_pct(fraction):
    return None if fraction is None else f"{(fraction * 100).normalize():f}%"


def _add_rate(db, pack, sort_order, key, label, source_id, flat_amount=None, employee_rate_pct=None,
              employer_rate_pct=None, text_value=None, effective_from=None, effective_to=None):
    if len(label) > 100:
        raise SystemExit(f"ContributionRate label longer than 100 characters: {label!r}")
    ee, er, flat = _dec(employee_rate_pct), _dec(employer_rate_pct), _dec(flat_amount)
    display = str(flat) if flat is not None else (text_value or _display_pct(ee if ee is not None else er))
    db.add(ContributionRate(
        jurisdiction_pack_id=pack.id, jurisdiction_country=CODE, organization_id=None,
        component_key=key, label=label,
        employee_share=_display_pct(ee) if ee is not None else ("—" if er is not None else display),
        employer_share=_display_pct(er) if er is not None else "—",
        total=display, employee_rate_pct=ee, employer_rate_pct=er, flat_amount=flat, text_value=text_value,
        effective_from=effective_from, effective_to=effective_to, sort_order=sort_order, source_document_id=source_id,
    ))


def _add_slab(db, pack, sort_order, rule_type, source_id, **kw):
    db.add(TaxSlab(jurisdiction_pack_id=pack.id, jurisdiction_country=CODE, organization_id=None,
                   rule_type=rule_type, sort_order=sort_order, source_document_id=source_id,
                   min_amount=kw.pop("min_amount", Decimal("0")), rate_pct=kw.pop("rate_pct", Decimal("0")), **kw))


def _reconcile(db, pack, prior) -> dict:
    """Same idempotent reconcile as the Singapore seed: identical rows kept,
    differing rows replaced (scripts.seed_singapore_canonical_pack)."""
    from scripts.seed_singapore_canonical_pack import _reconcile_pack_rows

    return _reconcile_pack_rows(db, pack, prior)


def _ensure_service_registry_row(db) -> str:
    """HK's registry row, PLANNED, created only when missing — the PLANNED →
    AVAILABLE step belongs to the owner, never to a seed."""
    from app.modules.billing.models import JurisdictionServiceRegistry

    existing = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == CODE).first()
    if existing is not None:
        return existing.availability
    db.add(JurisdictionServiceRegistry(country=CODE, availability="PLANNED",
                                       payment_execution_responsibility="NOT_OFFERED",
                                       filing_responsibility="NOT_OFFERED", remittance_responsibility="NOT_OFFERED"))
    db.flush()
    return "PLANNED"


def seed_hong_kong(db, spec=None) -> JurisdictionPack:
    from app.modules.payroll.service import record_tax_audit

    spec = spec or YA_2026
    year_index = 1 if spec is YA_2026 else 0
    ids = _upsert_sources(db)
    pack, created, prior = _upsert_pack(db, spec, ids)
    n = 0
    for key, label, source, kw in COMMON_RATES + EO_CONVENTIONS:
        n += 1
        _add_rate(db, pack, n, key, label, ids[source], **kw)
    for eff_from, eff_to, rate, cap, source in SMW_ROWS:
        # Only rows in force at some point inside this pack's window (April
        # 2025 still needs HK$40.00; April 2026 still needs HK$42.10).
        if eff_from > spec["effective_to"] or (eff_to is not None and eff_to < spec["effective_from"]):
            continue
        n += 1
        _add_rate(db, pack, n, "smw_hourly_rate", f"Statutory Minimum Wage — hourly ({eff_from:%d %b %Y})",
                  ids[source], flat_amount=rate, effective_from=eff_from, effective_to=eff_to)
        n += 1
        _add_rate(db, pack, n, "smw_hours_record_cap_monthly",
                  f"SMW hours-record monetary cap per month — record-keeping only ({eff_from:%d %b %Y})",
                  ids[source], flat_amount=cap, effective_from=eff_from, effective_to=eff_to)
    for key, (label, v2025, v2026) in ALLOWANCES.items():
        n += 1
        _add_rate(db, pack, n, key, f"{label} — YA {spec['tax_year']}", ids["ird_pam61e"],
                  flat_amount=(v2025, v2026)[year_index])
    for key, (label, v2025, v2026) in DEDUCTION_CEILINGS.items():
        n += 1
        if key in DEDUCTION_PERCENT_KEYS:
            _add_rate(db, pack, n, key, f"{label} — YA {spec['tax_year']}", ids["ird_pam61e"],
                      employee_rate_pct=(v2025, v2026)[year_index])
        else:
            _add_rate(db, pack, n, key, f"{label} — YA {spec['tax_year']}", ids["ird_pam61e"],
                      flat_amount=(v2025, v2026)[year_index])
    for key, (label, v2025, v2026) in ADDITIONAL_CEILINGS.items():
        n += 1
        _add_rate(db, pack, n, key, f"{label} — YA {spec['tax_year']}", ids["ird_adc"],
                  flat_amount=(v2025, v2026)[year_index])
    if spec is YA_2025:     # PAM 61(e) §4: 2025/26 one-off reduction 100%, max HK$3,000
        n += 1
        _add_rate(db, pack, n, "hk_tax_reduction_rate", "One-off Salaries Tax reduction — YA 2025/26", ids["ird_pam61e"],
                  employee_rate_pct="1")
        n += 1
        _add_rate(db, pack, n, "hk_tax_reduction_cap", "One-off Salaries Tax reduction cap — YA 2025/26",
                  ids["ird_pam61e"], flat_amount="3000")
    s = 0
    for lo, hi, pct in PROGRESSIVE_BANDS:
        s += 1
        _add_slab(db, pack, s, "HK_SALARIES_TAX_PROGRESSIVE", ids["ird_pam61e"], min_amount=Decimal(lo),
                  max_amount=_dec(hi), rate_pct=Decimal(pct), rate_label=f"HKST-{spec['tax_year']}-PROG-{s}",
                  tax_formula="Progressive rates on net chargeable income (informational)")
    for lo, hi, pct in STANDARD_TIERS:
        s += 1
        _add_slab(db, pack, s, "HK_SALARIES_TAX_STANDARD", ids["ird_pam61e"], min_amount=Decimal(lo),
                  max_amount=_dec(hi), rate_pct=Decimal(pct), rate_label=f"HKST-{spec['tax_year']}-STD-{s}",
                  tax_formula="Two-tiered standard rates on net income (informational)")
    for lo, hi, days in ANNUAL_LEAVE_SCALE:
        s += 1
        _add_slab(db, pack, s, "HK_ANNUAL_LEAVE_SCALE", ids["ld_cg_04"], min_amount=Decimal(lo), max_amount=_dec(hi),
                  flat_amount=Decimal(days), rate_label=f"HKEO-AL-Y{lo}",
                  tax_formula=f"Service year {lo}{'+' if hi is None else ''}: {days} days paid annual leave")
    years = (2025, 2026) if spec is YA_2025 else (2026, 2027)
    for year in years:
        source, days = HOLIDAYS[year]
        for iso, name in days:
            s += 1
            # A calendar ENTRY, not a dated rule: the date is carried in
            # tax_formula (ISO) so the row resolves for the whole pack window
            # (row effective dates would hide every holiday but the as-of day).
            _add_slab(db, pack, s, "HK_STATUTORY_HOLIDAY", ids[source], rate_label=name[:100],
                      filing_status=str(year), tax_formula=iso)
    for component, obligations in EARNING_CLASSES.items():
        for obligation, (basis, ird_field, source) in obligations.items():
            s += 1
            _add_slab(db, pack, s, "HK_EARNING_CLASS", ids[source], filing_status=component, tax_regime=obligation,
                      assessment_basis=basis,
                      # IRD rows: tax_formula = the IR56 field the amount is reported in.
                      tax_formula=ird_field if obligation == _IRD else f"{obligation}: {basis}",
                      rate_label=f"HKCLS-{spec['tax_year']}-{component}-{obligation} [G1]"[:100])
    changes = _reconcile(db, pack, prior)
    registry = _ensure_service_registry_row(db)
    db.flush()
    record_tax_audit(
        db, actor_id=None, action="create" if created else "update", entity_type="jurisdiction_pack",
        entity_id=pack.id, jurisdiction_pack_id=pack.id, tax_version=pack.version, legal_reference=SPEC,
        old_value=None,
        new_value={"status": pack.status, "contributionRates": str(n), "taxSlabs": str(s),
                   "sourceArtifacts": str(len(ids)),
                   # flat scalars only: the shared Audit tab renders values directly (a nested
                   # object crashed it — React error #31, found in the browser audit)
                   "rowChanges": "; ".join(f"{table}: +{c.get('inserted', 0)} / -{c.get('deleted', 0)}"
                                           for table, c in sorted(changes.items())),
                   "serviceRegistry": registry},
        reason=f"Canonical Hong Kong pack {spec['pack_id']} v{spec['version']} seeded from {SPEC} + official "
               "IRD / MPFA / Labour Department sources (scripts/seed_hong_kong_canonical_pack.py) — Draft.",
        auto_commit=False,
    )
    return pack


def seed_hong_kong_all(db) -> tuple:
    return seed_hong_kong(db, YA_2025), seed_hong_kong(db, YA_2026)


def main() -> None:
    assert_local_database("seed_hong_kong_canonical_pack")
    initialize_database()
    db = SessionLocal()
    try:
        p25, p26 = seed_hong_kong_all(db)
        db.commit()
        print(f"Seeded {p25.pack_id} v{p25.version} (id={p25.id}) and {p26.pack_id} v{p26.version} (id={p26.id}) as Draft.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
