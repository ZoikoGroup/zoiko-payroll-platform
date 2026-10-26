"""
modules/payroll/engine/countries/south_africa_content.py
---------------------------------------------------------
South Africa 2027 tax-year statutory content catalog (Draft) — the ONE list
of every rate, threshold, band and classification the South Africa engine
(engine/countries/south_africa.py, Phase 3) reads from `rate_map` / `slabs`.
Pure data, no ORM import, shared by:

  * south_africa_service.seed_south_africa_pack (via
    scripts/seed_south_africa_canonical_packs.py) — writes these rows into
    the ZA-PAYROLL-2027 canonical JurisdictionPack (Draft);
  * tests/test_south_africa_content.py — the contract test that pins the
    values below to ZP-ZA-ENG-001 and its fixtures F1–F4;
  * the Super Admin South Africa compliance tabs (key lists only — the
    frontend never carries a statutory value of its own).

"ZA" is South Africa. "SA" in this repository is Saudi Arabia.

Conventions (the engine must match them):
  * Scalar parameters are ContributionRate rows keyed by component_key:
      kind "employee_pct"/"employer_pct" — a PERCENT number (1.00 = 1%)
        in employee_rate_pct / employer_rate_pct;
      kind "pct_pair" — both employee_rate_pct and employer_rate_pct;
      kind "amount" — flat_amount (ZAR, hours, days, years or a count);
      kind "text"   — text_value (an enum label or a version string).
    A scalar row may carry its own LEGAL effective_from / effective_to
    (the BCEA threshold changes on 1 May 2026, inside the tax year).
  * PAYE bands are TaxSlab rule_type="ZA_PAYE_BAND" on ANNUAL taxable income:
      min_amount  = the band threshold ("above R245,100" → 245100; 0 for the first)
      max_amount  = the band ceiling (inclusive), NULL for the top band
      flat_amount = tax on income up to min_amount (the published base)
      rate_pct    = the marginal rate (percent) on income above min_amount
    The bands are validation anchors for the certified SARS periodic
    algorithm (spec §3) — they are not "annual tax ÷ 12" on their own.
  * ETI bands are TaxSlab rule_type="ZA_ETI_BAND" on MONTHLY remuneration
    (after 160-hour normalisation), min_amount <= remuneration < max_amount:
      filing_status = qualifying period ("FIRST_12" | "SECOND_12")
      tax_regime    = formula ("PCT" | "FLAT" | "TAPER")
        PCT   → rate_pct % of remuneration
        FLAT  → flat_amount
        TAPER → flat_amount − rate_pct % × (remuneration − min_amount)
  * Earning classification rows are TaxSlab rule_type="ZA_EARNING_CLASS"
    (the Hong Kong / Saudi Arabia layout):
      filing_status    = pay component (SALARY, OVERTIME, BONUS, …)
      tax_regime       = obligation ("PAYE" | "UIF" | "SDL" | "ETI" | "COIDA")
      assessment_basis = "INCLUDED" | "EXCLUDED" | "TRAVEL_RULE" | "REVIEW"
      tax_table_number = IRP5 source code — deliberately EMPTY until the
                         SARS PAYE BRS (S4) source-code catalogue is archived;
                         a source code is never guessed (ZA-015, ZA-018).
    TRAVEL_RULE applies the za_travel_inclusion_* parameters (ZA-008).
    REVIEW means "not decided by the specification" and BLOCKS any
    calculation in which that component is non-zero (spec §1: unsupported
    cases are blocked, never approximated). Each obligation has its own
    base (spec §4) — there is no shared "taxable gross".

Scope (spec §1): resident standard employees and ordinary directors on a
MONTHLY payroll. Weekly/fortnightly frequencies, non-residents, SEZ ETI,
equity awards and foreign-currency pay have NO rows on purpose — the engine
BLOCKS them.

Status is Draft throughout; the registry row stays PLANNED. Rows marked
pending_g1=True must be signed by Payroll/Tax Operations and an independent
South African reviewer at gate G1 (spec §14) before any pack carrying them
is activated. The production safety rule (spec, page 1) applies: no value
here is active merely because it appears in the specification.
"""

from datetime import date
from decimal import Decimal

PACK_STATUS = "Draft"
SPEC = "ZP-ZA-ENG-001 v1.0"

# The 2027 South African tax year: 1 March 2026 – 28 February 2027 (spec §2).
ZA_2027 = ("ZA-PAYROLL-2027", date(2026, 3, 1), date(2027, 2, 28))
TAX_YEAR = "2027"
CURRENCY = "ZAR"

# ── Evidence register (ZP-ZA-ENG-001 §15, S1–S14) ─────────────────────────
SOURCE_REFERENCES = (
    ("S1", "SARS — Guide for Employers in Respect of Employees' Tax (2027): PAYE, UIF, SDL, "
           "allowances, directives, payments and record keeping"),
    ("S2", "SARS — Rates of Tax for Individuals (2027 tax year): bands, rebates and thresholds"),
    ("S3", "SARS — Guide for Employers in Respect of Tax Deduction Tables: deduction tables "
           "and medical scheme fees tax credits"),
    ("S4", "SARS — Updated PAYE Employer Reconciliation BRS for 2026/2027 (v25.3.0, "
           "source-code validation changes)"),
    ("S5", "SARS — Employer Interim Declarations EMP501, 21 September to 31 October 2026"),
    ("S6", "SARS — Unemployment Insurance Fund (1% employee / 1% employer, monthly ceiling)"),
    ("S7", "SARS — Skills Development Levy (1% employer levy, R500,000 exemption threshold)"),
    ("S8", "SARS — Employment Tax Incentive (eligibility and formula guidance)"),
    ("S9", "Department of Employment and Labour — National Minimum Wage R30.23 per hour "
           "from 1 March 2026"),
    ("S10", "Department of Employment and Labour — BCEA earnings threshold R269,900.90 "
            "from 1 May 2026"),
    ("S11", "Department of Employment and Labour — Basic Guide to Pay Slips / Deductions / Leave"),
    ("S12", "Department of Employment and Labour — Compensation Fund (COIDA) employer obligations"),
    ("S13", "South Africa — Protection of Personal Information Act 4 of 2013 (POPIA)"),
    ("S14", "SARS — Record keeping (five-year baseline, offshore electronic records)"),
)
SOURCE_CODES = tuple(code for code, _ in SOURCE_REFERENCES)

# Public URLs of the evidence register (spec §15). Archived copies and their
# SHA-256 are attached at gate G1 — a URL alone is not archived evidence.
SOURCE_URLS = {
    "S1": "https://www.sars.gov.za/guide-for-employers-in-respect-of-employees-tax-2027/",
    "S2": "https://www.sars.gov.za/tax-rates/income-tax/rates-of-tax-for-individuals/",
    "S3": "https://www.sars.gov.za/guide-for-employers-in-respect-of-tax-deduction-tables/",
    "S4": "https://www.sars.gov.za/latest-news/updated-paye-employer-reconciliation-brs-for-2026-2027-2/",
    "S5": "https://www.sars.gov.za/latest-news/employer-interim-declarations-emp501-21-september-to-october-2026/",
    "S6": "https://www.sars.gov.za/types-of-tax/unemployment-insurance-fund/",
    "S7": "https://www.sars.gov.za/types-of-tax/skills-development-levy/",
    "S8": "https://www.sars.gov.za/types-of-tax/pay-as-you-earn/employment-tax-incentive-eti/",
    "S9": "https://www.labour.gov.za/Media-Desk/Media-Statements/Pages/Minister-of-Employment-and-Labour%2C-Meth-increases-the-statutory-National-Minimum-Wage-to-R30%2C23-per-hour.aspx",
    "S10": "https://www.labour.gov.za/Media-Desk/Media-Statements/Pages/Department-of-Employment-and-Labour-sets-a-new-threshold-in-the-protection-of-employees-.aspx",
    "S11": "https://www.labour.gov.za/DocumentCenter/Pages/Basic-Guide-to-Pay-Slips.aspx",
    "S12": "https://www.labour.gov.za/DocumentCenter/Pages/Compensation-Fund--obligations-of-the-employer-.aspx",
    "S13": "https://www.justice.gov.za/legislation/acts/2013-004.pdf",
    "S14": "https://www.sars.gov.za/client-segments/record-keeping/",
}

# ── TaxSlab rule_type discriminators (all ≤ 30 chars) ────────────────────
ZA_PAYE_BAND_RULE = "ZA_PAYE_BAND"
ZA_ETI_BAND_RULE = "ZA_ETI_BAND"
ZA_EARNING_CLASS_RULE = "ZA_EARNING_CLASS"

# ── Enumerations the engine validates against ─────────────────────────────
PAY_FREQUENCIES_SUPPORTED = ("MONTHLY",)
# Recorded but never calculated at launch (spec §1, deferred scope).
PAY_FREQUENCIES_BLOCKED = ("WEEKLY", "FORTNIGHTLY")
EMPLOYMENT_TYPES = ("STANDARD", "NON_STANDARD")
OBLIGATIONS = ("PAYE", "UIF", "SDL", "ETI", "COIDA")
TREATMENTS = ("INCLUDED", "EXCLUDED", "TRAVEL_RULE", "REVIEW")
ETI_PERIODS = ("FIRST_12", "SECOND_12")
ETI_FORMULAS = ("PCT", "FLAT", "TAPER")
ROUNDING_MODES = ("HALF_UP", "DOWN", "UP")
# Explicit policy choices the specification requires but does not make
# (ZA-006): until G1 signs one, the engine BLOCKS any case that depends on it.
DATE_BASES = ("PAYMENT_DATE", "EARNING_DATE", "PENDING_G1")

# ── Scalar engine parameter keys ──────────────────────────────────────────
# key -> kind. The engine's ZA_PARAMETER_KEYS is THIS dict (imported).
ZA_PARAMETER_KEYS = {
    # Scope and policy (spec §1, §3, ZA-006)
    "za_supported_pay_frequencies": "text",
    "za_paye_tax_year_date_basis": "text",
    "za_variable_remuneration_basis": "text",
    "za_rounding_mode": "text",
    "za_rounding_precision": "amount",
    # PAYE rebates (spec §2)
    "za_rebate_primary": "amount",
    "za_rebate_secondary": "amount",
    "za_rebate_tertiary": "amount",
    "za_rebate_secondary_age": "amount",
    "za_rebate_tertiary_age": "amount",
    # Medical scheme fees tax credit, per month (spec §2)
    "za_mtc_main_member": "amount",
    "za_mtc_first_dependant": "amount",
    "za_mtc_additional_dependant": "amount",
    # Retirement fund contribution deduction (spec §2)
    "za_retirement_deduction_pct": "employee_pct",
    "za_retirement_annual_cap": "amount",
    # Travel allowance inclusion (ZA-008)
    "za_travel_inclusion_default_pct": "employee_pct",
    "za_travel_inclusion_business_pct": "employee_pct",
    "za_travel_business_use_min_pct": "employee_pct",
    # UIF (spec §2, §4)
    "za_uif": "pct_pair",
    "za_uif_monthly_ceiling": "amount",
    # SDL (spec §2, §4)
    "za_sdl": "employer_pct",
    "za_sdl_exemption_threshold": "amount",
    # ETI (spec §2, §4, F3)
    "za_eti_hours_normaliser": "amount",
    "za_eti_qualifying_months_max": "amount",
    "za_eti_min_age": "amount",
    "za_eti_max_age": "amount",
    # Labour baselines (spec §5)
    "za_nmw_hourly": "amount",
    "za_bcea_earnings_threshold": "amount",
    # Filing and records (spec §9, §11)
    "za_emp201_due_day": "amount",
    "za_emp201_non_business_day_rule": "text",
    "za_brs_version": "text",
    "za_record_retention_years": "amount",
}

# ── ContributionRate scalar content ───────────────────────────────────────
# (component_key, label, employee_pct, employer_pct, flat_amount, text_value,
#  source, pending_g1, effective_from, effective_to)
# effective_from/to None → the row is dated by the pack window.
_BCEA_FROM = date(2026, 5, 1)

ZA_SCALAR_CONTENT = (
    ("za_supported_pay_frequencies", "Pay frequencies certified for calculation (spec §1)",
     None, None, None, "MONTHLY", "S1", False, None, None),
    # ZA-006: earning date, payment date, payroll period and certificate year
    # are distinct; the date that selects the tax year is a signed policy.
    ("za_paye_tax_year_date_basis", "Date that selects the PAYE tax year (ZA-006)",
     None, None, None, "PENDING_G1", "S1", True, None, None),
    # ZA-006: section 7B variable remuneration paid/accrual timing.
    ("za_variable_remuneration_basis", "Section 7B variable remuneration timing (ZA-006)",
     None, None, None, "PENDING_G1", "S1", True, None, None),
    # SARS rounding/truncation points come from the certified deduction-table
    # algorithm (spec §3 "Dates, precision and rounding") — PENDING_G1.
    ("za_rounding_mode", "ZAR rounding mode for statutory amounts", None, None, None, "HALF_UP", "S3", True,
     None, None),
    ("za_rounding_precision", "ZAR rounding precision (decimals)", None, None, "2", None, "S3", True, None, None),

    ("za_rebate_primary", "PAYE primary rebate (annual)", None, None, "17820", None, "S2", False, None, None),
    ("za_rebate_secondary", "PAYE secondary rebate, age 65+ (annual)", None, None, "9765", None, "S2", False,
     None, None),
    ("za_rebate_tertiary", "PAYE tertiary rebate, age 75+ (annual)", None, None, "3249", None, "S2", False,
     None, None),
    ("za_rebate_secondary_age", "Age from which the secondary rebate applies", None, None, "65", None, "S2", False,
     None, None),
    ("za_rebate_tertiary_age", "Age from which the tertiary rebate applies", None, None, "75", None, "S2", False,
     None, None),

    ("za_mtc_main_member", "Medical scheme fees tax credit — taxpayer (monthly)", None, None, "376", None, "S3",
     False, None, None),
    ("za_mtc_first_dependant", "Medical scheme fees tax credit — first dependant (monthly)", None, None, "376",
     None, "S3", False, None, None),
    ("za_mtc_additional_dependant", "Medical scheme fees tax credit — each additional dependant (monthly)",
     None, None, "254", None, "S3", False, None, None),

    # The payroll deduction algorithm, YTD limits and excess handling come
    # from certified guidance (spec §2) — PENDING_G1.
    ("za_retirement_deduction_pct", "Retirement fund deduction (% of remuneration or taxable income)",
     "27.5000", None, None, None, "S1", True, None, None),
    ("za_retirement_annual_cap", "Retirement fund deduction annual cap", None, None, "430000", None, "S1", True,
     None, None),

    ("za_travel_inclusion_default_pct", "Fixed travel allowance included in PAYE remuneration",
     "80.0000", None, None, None, "S1", False, None, None),
    ("za_travel_inclusion_business_pct", "Fixed travel allowance inclusion where >= 80% business use",
     "20.0000", None, None, None, "S1", False, None, None),
    ("za_travel_business_use_min_pct", "Business-use share that qualifies for the reduced inclusion",
     "80.0000", None, None, None, "S1", False, None, None),

    ("za_uif", "UIF contribution (employee / employer)", "1.0000", "1.0000", None, None, "S6", False,
     None, None),
    ("za_uif_monthly_ceiling", "UIF monthly remuneration ceiling", None, None, "17712", None, "S6", False,
     None, None),

    ("za_sdl", "Skills Development Levy (employer only)", None, "1.0000", None, None, "S7", False, None, None),
    ("za_sdl_exemption_threshold", "SDL exemption — annual leviable remuneration not exceeding",
     None, None, "500000", None, "S7", False, None, None),

    # ETI legislative validity, eligibility and formula must be verified in the
    # production pack (spec §15 S8) — every ETI value is PENDING_G1.
    ("za_eti_hours_normaliser", "ETI hours normaliser (paid hours per month)", None, None, "160", None, "S8", True,
     None, None),
    ("za_eti_qualifying_months_max", "ETI maximum qualifying months per employee", None, None, "24", None, "S8",
     True, None, None),
    ("za_eti_min_age", "ETI minimum employee age", None, None, "18", None, "S8", True, None, None),
    ("za_eti_max_age", "ETI maximum employee age", None, None, "29", None, "S8", True, None, None),

    ("za_nmw_hourly", "National Minimum Wage (per ordinary hour)", None, None, "30.23", None, "S9", False,
     date(2026, 3, 1), None),
    # The threshold in force before 1 May 2026 is not in the specification:
    # March–April 2026 has NO row, so a BCEA check for those months BLOCKS
    # until G1 supplies the prior value.
    ("za_bcea_earnings_threshold", "BCEA earnings threshold (annual, specified working-time sections)",
     None, None, "269900.90", None, "S10", False, _BCEA_FROM, None),

    ("za_emp201_due_day", "EMP201 payment and declaration due by day of following month",
     None, None, "7", None, "S1", False, None, None),
    ("za_emp201_non_business_day_rule", "EMP201 due date on a weekend or public holiday",
     None, None, None, "PRECEDING_BUSINESS_DAY", "S1", False, None, None),
    ("za_brs_version", "SARS PAYE reconciliation BRS version (202608 interim period)",
     None, None, None, "25.3.0", "S4", True, None, None),
    ("za_record_retention_years", "SARS payroll/tax record retention (years, minimum)",
     None, None, "5", None, "S14", False, None, None),
)

# ── PAYE bands — TaxSlab rule_type="ZA_PAYE_BAND" (spec §2, S2) ───────────
# (min_amount, max_amount, rate_pct, base_tax, label, source)
ZA_PAYE_BANDS = (
    ("0", "245100", "18.0000", "0", "R1 – R245,100: 18% of taxable income", "S2"),
    ("245100", "383100", "26.0000", "44118", "R245,101 – R383,100: R44,118 + 26% above R245,100", "S2"),
    ("383100", "530200", "31.0000", "79998", "R383,101 – R530,200: R79,998 + 31% above R383,100", "S2"),
    ("530200", "695800", "36.0000", "125599", "R530,201 – R695,800: R125,599 + 36% above R530,200", "S2"),
    ("695800", "887000", "39.0000", "185215", "R695,801 – R887,000: R185,215 + 39% above R695,800", "S2"),
    ("887000", "1878600", "41.0000", "259783", "R887,001 – R1,878,600: R259,783 + 41% above R887,000", "S2"),
    ("1878600", None, "45.0000", "666339", "R1,878,601 and above: R666,339 + 45% above R1,878,600", "S2"),
)

# ── ETI bands — TaxSlab rule_type="ZA_ETI_BAND" (spec §2, F3, S8) ─────────
# (period, formula, min_amount, max_amount, rate_pct, flat_amount, label, source)
# Fixture F3 places R5,000 in the R2,500–R5,499.99 band at R1,500 for the
# first 12 qualifying months. The second-12-month rows are half the first.
# PENDING_G1 throughout: legislative validity by month must be verified.
ZA_ETI_BANDS = (
    ("FIRST_12", "PCT", "0", "2500", "60.0000", None, "First 12 months — below R2,500: 60% of remuneration", "S8"),
    ("FIRST_12", "FLAT", "2500", "5500", None, "1500", "First 12 months — R2,500 to R5,499.99: R1,500", "S8"),
    ("FIRST_12", "TAPER", "5500", "7500", "75.0000", "1500",
     "First 12 months — R5,500 to R7,499.99: R1,500 − 75% of excess over R5,500", "S8"),
    ("SECOND_12", "PCT", "0", "2500", "30.0000", None, "Second 12 months — below R2,500: 30% of remuneration", "S8"),
    ("SECOND_12", "FLAT", "2500", "5500", None, "750", "Second 12 months — R2,500 to R5,499.99: R750", "S8"),
    ("SECOND_12", "TAPER", "5500", "7500", "37.5000", "750",
     "Second 12 months — R5,500 to R7,499.99: R750 − 37.5% of excess over R5,500", "S8"),
)

# ── Earning classification — TaxSlab rule_type="ZA_EARNING_CLASS" ─────────
# (obligation, treatment, component, label, source)
# Components map to PayrollContext (Phase 3): SALARY=basic,
# OVERTIME=overtime, BONUS / COMMISSION / LEAVE_PAYOUT / TRAVEL_FIXED /
# TRAVEL_REIMBURSIVE / FRINGE_BENEFIT = named pay components,
# OTHER_EARNINGS = gross minus every named component.
# Only the treatments the specification states are INCLUDED; everything
# else is REVIEW until G1 signs the per-base interpretation (spec §4:
# "A new earning code is not production-ready until every relevant base and
# certificate code is classified").
ZA_COMPONENTS = ("SALARY", "OVERTIME", "BONUS", "COMMISSION", "LEAVE_PAYOUT", "TRAVEL_FIXED",
                 "TRAVEL_REIMBURSIVE", "FRINGE_BENEFIT", "OTHER_EARNINGS")

ZA_EARNING_CLASSES = (
    # PAYE remuneration (spec §1 table, ZA-006, ZA-008)
    ("PAYE", "INCLUDED", "SALARY", "Salary/wages — PAYE remuneration", "S1"),
    ("PAYE", "INCLUDED", "OVERTIME", "Overtime — PAYE remuneration (section 7B timing applies)", "S1"),
    ("PAYE", "INCLUDED", "BONUS", "Bonus — PAYE remuneration (section 7B timing applies)", "S1"),
    ("PAYE", "INCLUDED", "COMMISSION", "Commission — PAYE remuneration (section 7B timing applies)", "S1"),
    ("PAYE", "INCLUDED", "LEAVE_PAYOUT", "Unused leave paid out — PAYE remuneration (section 7B)", "S1"),
    ("PAYE", "TRAVEL_RULE", "TRAVEL_FIXED", "Fixed travel allowance — 80% / 20% inclusion (ZA-008)", "S1"),
    ("PAYE", "REVIEW", "TRAVEL_REIMBURSIVE", "Reimbursive travel — needs the prescribed-rate rule", "S1"),
    ("PAYE", "REVIEW", "FRINGE_BENEFIT", "Fringe benefit — needs a signed valuation rule", "S1"),
    ("PAYE", "REVIEW", "OTHER_EARNINGS", "Any other earning — needs a classification", "S1"),

    # UIF remuneration (spec §4) — its own base, never the PAYE base.
    ("UIF", "INCLUDED", "SALARY", "Salary/wages — UIF remuneration", "S6"),
    ("UIF", "REVIEW", "OVERTIME", "Overtime — UIF treatment needs signed evidence", "S6"),
    ("UIF", "REVIEW", "BONUS", "Bonus — UIF treatment needs signed evidence", "S6"),
    ("UIF", "REVIEW", "COMMISSION", "Commission — UIF treatment needs signed evidence", "S6"),
    ("UIF", "REVIEW", "LEAVE_PAYOUT", "Leave payout — UIF treatment needs signed evidence", "S6"),
    ("UIF", "REVIEW", "TRAVEL_FIXED", "Travel allowance — UIF treatment needs signed evidence", "S6"),
    ("UIF", "REVIEW", "TRAVEL_REIMBURSIVE", "Reimbursive travel — UIF treatment needs signed evidence", "S6"),
    ("UIF", "REVIEW", "FRINGE_BENEFIT", "Fringe benefit — UIF treatment needs signed evidence", "S6"),
    ("UIF", "REVIEW", "OTHER_EARNINGS", "Any other earning — needs a classification", "S6"),

    # SDL leviable remuneration (spec §4)
    ("SDL", "INCLUDED", "SALARY", "Salary/wages — SDL leviable remuneration", "S7"),
    ("SDL", "REVIEW", "OVERTIME", "Overtime — SDL treatment needs signed evidence", "S7"),
    ("SDL", "REVIEW", "BONUS", "Bonus — SDL treatment needs signed evidence", "S7"),
    ("SDL", "REVIEW", "COMMISSION", "Commission — SDL treatment needs signed evidence", "S7"),
    ("SDL", "REVIEW", "LEAVE_PAYOUT", "Leave payout — SDL treatment needs signed evidence", "S7"),
    ("SDL", "REVIEW", "TRAVEL_FIXED", "Travel allowance — SDL treatment needs signed evidence", "S7"),
    ("SDL", "REVIEW", "TRAVEL_REIMBURSIVE", "Reimbursive travel — SDL treatment needs signed evidence", "S7"),
    ("SDL", "REVIEW", "FRINGE_BENEFIT", "Fringe benefit — SDL treatment needs signed evidence", "S7"),
    ("SDL", "REVIEW", "OTHER_EARNINGS", "Any other earning — needs a classification", "S7"),

    # ETI monthly remuneration (spec §4, F3)
    ("ETI", "INCLUDED", "SALARY", "Salary/wages — ETI monthly remuneration", "S8"),
    ("ETI", "REVIEW", "OVERTIME", "Overtime — ETI treatment needs signed evidence", "S8"),
    ("ETI", "REVIEW", "BONUS", "Bonus — ETI treatment needs signed evidence", "S8"),
    ("ETI", "REVIEW", "COMMISSION", "Commission — ETI treatment needs signed evidence", "S8"),
    ("ETI", "REVIEW", "LEAVE_PAYOUT", "Leave payout — ETI treatment needs signed evidence", "S8"),
    ("ETI", "REVIEW", "TRAVEL_FIXED", "Travel allowance — ETI treatment needs signed evidence", "S8"),
    ("ETI", "REVIEW", "TRAVEL_REIMBURSIVE", "Reimbursive travel — ETI treatment needs signed evidence", "S8"),
    ("ETI", "REVIEW", "FRINGE_BENEFIT", "Fringe benefit — ETI treatment needs signed evidence", "S8"),
    ("ETI", "REVIEW", "OTHER_EARNINGS", "Any other earning — needs a classification", "S8"),

    # COIDA earnings (spec §4) — ROE evidence only, never an employee deduction.
    ("COIDA", "INCLUDED", "SALARY", "Salary/wages — COIDA ROE earnings", "S12"),
    ("COIDA", "REVIEW", "OVERTIME", "Overtime — COIDA treatment needs signed evidence", "S12"),
    ("COIDA", "REVIEW", "BONUS", "Bonus — COIDA treatment needs signed evidence", "S12"),
    ("COIDA", "REVIEW", "COMMISSION", "Commission — COIDA treatment needs signed evidence", "S12"),
    ("COIDA", "REVIEW", "LEAVE_PAYOUT", "Leave payout — COIDA treatment needs signed evidence", "S12"),
    ("COIDA", "REVIEW", "TRAVEL_FIXED", "Travel allowance — COIDA treatment needs signed evidence", "S12"),
    ("COIDA", "REVIEW", "TRAVEL_REIMBURSIVE", "Reimbursive travel — COIDA treatment needs signed evidence", "S12"),
    ("COIDA", "REVIEW", "FRINGE_BENEFIT", "Fringe benefit — COIDA treatment needs signed evidence", "S12"),
    ("COIDA", "REVIEW", "OTHER_EARNINGS", "Any other earning — needs a classification", "S12"),
)

# ── Category labels for UI grouping ──────────────────────────────────────
ZA_CATEGORIES = {
    "paye_bands": "PAYE Bands (annual taxable income)",
    "rebates": "PAYE Rebates & Medical Tax Credits",
    "retirement_travel": "Retirement Deduction & Travel Allowance",
    "uif_sdl": "UIF & SDL",
    "eti": "Employment Tax Incentive",
    "earning_classes": "Earning Classification (PAYE / UIF / SDL / ETI / COIDA)",
    "labour": "Labour Baselines (NMW / BCEA)",
    "filing": "Filing, BRS & Records",
    "policy": "Scope & Policy",
}


def _in_force(eff_from, eff_to, as_of: date) -> bool:
    if eff_from is not None and as_of < eff_from:
        return False
    if eff_to is not None and as_of > eff_to:
        return False
    return True


def content_rows_in_force(as_of: date):
    """Scalar content rows legally in force on `as_of`, keyed by component_key."""
    return {row[0]: row for row in ZA_SCALAR_CONTENT if _in_force(row[8], row[9], as_of)}


def paye_bands():
    """PAYE bands as Decimals: (min, max-or-None, rate_pct, base_tax, label, source)."""
    return tuple((Decimal(lo), Decimal(hi) if hi is not None else None, Decimal(rate), Decimal(base), label, src)
                 for (lo, hi, rate, base, label, src) in ZA_PAYE_BANDS)


def eti_bands(period: str):
    """ETI bands for one qualifying period as Decimals."""
    return tuple((formula, Decimal(lo), Decimal(hi), Decimal(rate) if rate is not None else None,
                  Decimal(flat) if flat is not None else None, label, src)
                 for (p, formula, lo, hi, rate, flat, label, src) in ZA_ETI_BANDS if p == period)


def earning_classes_in_force(as_of: date):
    """Earning classification rows (undated in this Draft)."""
    return ZA_EARNING_CLASSES
