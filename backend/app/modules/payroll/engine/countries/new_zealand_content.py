"""
modules/payroll/engine/countries/new_zealand_content.py
--------------------------------------------------------
New Zealand 2026-27 statutory content catalog (Draft): the ONE list of every
rate, threshold, calendar and classification the New Zealand engine
(engine/countries/new_zealand.py, Phase 3) reads from `rate_map` / `slabs`.
Pure data, no ORM import. It is shared by:

  * new_zealand_service.seed_nz_pack (via scripts/seed_nz_canonical_packs.py)
    — writes these rows into the NZ-PAYROLL-2026-27 canonical
    JurisdictionPack (Draft);
  * tests/test_nz_content.py — the contract test that pins the values below
    to ZP-NZ-ENG-001;
  * the Super Admin New Zealand compliance tabs (key lists only — the
    frontend never carries a statutory value of its own).

Conventions (the engine must match them, and they are the Japan conventions):
  * Scalar parameters are ContributionRate rows keyed by component_key:
      kind "pct_total" — a percentage as a PERCENT number in flat_amount
        (1.7500 = 1.75%);
      kind "amount"    — flat_amount (NZD, days, weeks, months, an age);
      kind "text"      — text_value (an enum label, a list, MM-DD, PENDING_G1).
    A row may carry its own LEGAL effective_from / effective_to. KiwiSaver
    rows are selected by PAYDAY, not by pay period (NZ-008): a period that
    straddles 1 April 2026 uses the new rate when the payday is on or after
    1 April. A payday with no row in force BLOCKS — the pre-April-2026
    KiwiSaver rates are not in the specification.
  * Rate bands are TaxSlab rows (NZ_PAYE_BAND, NZ_ESCT_BAND): rate_pct
    applies to the part of income ABOVE min_amount up to max_amount
    (max_amount NULL = no upper limit).
  * The tax-code catalogue is TaxSlab rule_type="NZ_TAX_CODE":
      filing_status    = the tax code ("M", "ME SL", "SB", …)
      tax_regime       = "MAIN" | "SECONDARY" | "SPECIAL"
      assessment_basis = "SUPPORTED" | "REFUSED"
      tax_column       = "SL" when the code carries student-loan deductions
      tax_table_number = "IETC" for the independent-earner (ME) codes
    An unknown code is REJECTED, never mapped to a "closest" code (§3).
  * Earning classification rows are TaxSlab rule_type="NZ_EARNING_CLASS":
      filing_status    = pay component (SALARY, OVERTIME, BONUS, …)
      tax_regime       = obligation ("PAYE" | "ACC" | "KIWISAVER" |
                         "STUDENT_LOAN" | "HOLIDAY_GROSS" | "MIN_WAGE")
      assessment_basis = "INCLUDED" | "EXCLUDED" | "LUMP_SUM_PATH" | "REVIEW"
    Each obligation has its own base — there is no universal "taxable
    gross" (spec, "Critical refinements"). REVIEW means "not decided by the
    specification" and BLOCKS any calculation in which that component is
    non-zero. LUMP_SUM_PATH routes the amount to the IRD lump-sum method,
    which is empty until G1, so it blocks too.
  * Authority content the specification does NOT reproduce — the IRD PAYE
    business-rule method, secondary-code and no-notification rates, the
    independent earner tax credit, child-support variation codes, the
    lump-sum method, official examples and public-holiday dates — is
    declared below as EMPTY containers (NZ_EMPTY_TABLES). They are filled
    only from archived authority artefacts at the named gate; until then
    every calculation that needs one BLOCKS.

Rounding (spec §3): "use official rounding/whole-dollar/cents rules from the
IRD business-rule specification, not generic currency rounding". The
specification does not state them, so every rounding row is PENDING_G1 and
the engine BLOCKS on it. There is no global rounding helper.

Status is Draft throughout and the registry row stays PLANNED. Per the
production safety rule (spec, page 1) every row below is pending_g1=True:
signed effective-dated content, archived authority evidence, fixtures and
an independent New Zealand payroll/tax review come first (gate G1).
"""

from datetime import date

PACK_STATUS = "Draft"
SPEC = "ZP-NZ-ENG-001 v1.0"

# Tax and levy year 1 April 2026 – 31 March 2027 (spec §2). Selection is by
# payday (NZ-008): a payday inside this window uses this pack.
NZ_2026_27 = ("NZ-PAYROLL-2026-27", date(2026, 4, 1), date(2027, 3, 31))
TAX_YEAR = "2026-27"
CURRENCY = "NZD"
TIMEZONES = ("Pacific/Auckland", "Pacific/Chatham")

# Employment Leave Act 2026 (spec §8, AC-NZ-08): enacted, but it replaces the
# Holidays Act only from 6 August 2028. Its pack exists only as a staging
# container; seed_nz_pack writes it Draft and empty, and the activation
# refusal makes it impossible to activate before this date (and, after it,
# without its own signed content and approval).
NZ_ELA_2028 = ("NZ-ELA-2028", date(2028, 8, 6), None)
ELA_EARLIEST_EFFECTIVE = date(2028, 8, 6)

# ── Evidence register (ZP-NZ-ENG-001 §15, S1–S10, reviewed 22 Sep 2026) ────
SOURCE_REFERENCES = (
    ("S1", "Inland Revenue — Payroll calculations and business rules, 1 Apr 2026 to 31 Mar 2027"),
    ("S2", "Inland Revenue — Payday filing (electronic within 2 working days; paper timing; "
           "electronic filing threshold)"),
    ("S3", "Inland Revenue — PAYE deduction tables / Employer guide (IR340, IR341, IR335), Apr 2026"),
    ("S4", "Inland Revenue — KiwiSaver changes / employer calculations (3.5% from 1 Apr 2026)"),
    ("S5", "Inland Revenue — Paying deductions to Inland Revenue (monthly vs twice-monthly)"),
    ("S6", "Employment New Zealand — Minimum wage rates and types (from 1 Apr 2026)"),
    ("S7", "Employment New Zealand — Holidays and leave / Holidays Act guidance"),
    ("S8", "Employment New Zealand — Employment Leave Act 2026"),
    ("S9", "Employment New Zealand — Record-keeping (wage/time and holiday/leave records, 6 years)"),
    ("S10", "Office of the Privacy Commissioner — Privacy Act guidance / breach notification"),
)
SOURCE_CODES = tuple(code for code, _ in SOURCE_REFERENCES)

# Public URLs of the evidence register (spec §15). Archived copies and their
# SHA-256 are attached at gate G1 — a URL alone is not archived evidence.
SOURCE_URLS = {
    "S1": "https://www.ird.govt.nz/digital-service-providers/services-catalogue/returns-and-information/"
          "payday-filing/payroll-calculations-and-business-rules",
    "S2": "https://www.ird.govt.nz/payday",
    "S3": "https://www.ird.govt.nz/deductions",
    "S4": "https://www.ird.govt.nz/kiwisaver-changes",
    "S5": "https://www.ird.govt.nz/employing-staff/payday-filing/paying-deductions-to-inland-revenue",
    "S6": "https://www.employment.govt.nz/pay-and-hours/pay-and-wages/minimum-wage/minimum-wage-rates-and-types",
    "S7": "https://www.employment.govt.nz/leave-and-holidays",
    "S8": "https://www.employment.govt.nz/news-and-updates/employment-leave-act-2026",
    "S9": "https://www.employment.govt.nz/starting-employment/rights-and-responsibilities/record-keeping",
    "S10": "https://www.privacy.org.nz/responsibilities/privacy-breaches/notify-us/",
}

# ── TaxSlab rule_type discriminators (all ≤ 30 chars) ────────────────────
NZ_EARNING_CLASS_RULE = "NZ_EARNING_CLASS"
NZ_PAYE_BAND_RULE = "NZ_PAYE_BAND"
NZ_ESCT_BAND_RULE = "NZ_ESCT_BAND"
NZ_TAX_CODE_RULE = "NZ_TAX_CODE"
# Authority tables, empty until their gate signs them (NZ_EMPTY_TABLES).
NZ_PAYE_METHOD_RULE = "NZ_PAYE_METHOD"
NZ_SECONDARY_RATE_RULE = "NZ_SECONDARY_RATE"
NZ_ND_RATE_RULE = "NZ_ND_RATE"
NZ_IETC_RULE = "NZ_IETC"
NZ_CS_VARIATION_RULE = "NZ_CS_VARIATION"
NZ_LUMP_SUM_RULE = "NZ_LUMP_SUM"
NZ_HOLIDAY_ADVANCE_RULE = "NZ_HOLIDAY_ADVANCE"
NZ_IRD_EXAMPLE_RULE = "NZ_IRD_EXAMPLE"
NZ_PUBLIC_HOLIDAY_RULE = "NZ_PUBLIC_HOLIDAY"
NZ_ACC_CLASSIFICATION_RULE = "NZ_ACC_CLASSIFICATION"
NZ_TABLE_RULE_TYPES = (
    NZ_PAYE_BAND_RULE, NZ_ESCT_BAND_RULE, NZ_TAX_CODE_RULE,
    NZ_PAYE_METHOD_RULE, NZ_SECONDARY_RATE_RULE, NZ_ND_RATE_RULE, NZ_IETC_RULE, NZ_CS_VARIATION_RULE,
    NZ_LUMP_SUM_RULE, NZ_HOLIDAY_ADVANCE_RULE, NZ_IRD_EXAMPLE_RULE, NZ_PUBLIC_HOLIDAY_RULE,
    NZ_ACC_CLASSIFICATION_RULE,
)

# ── Enumerations the engine validates against ─────────────────────────────
# Certification baseline (spec §1): regular weekly, fortnightly, four-weekly
# or monthly payroll.
PAY_FREQUENCIES = ("WEEKLY", "FORTNIGHTLY", "FOUR_WEEKLY", "MONTHLY")
RESIDENCY_STATUSES = ("RESIDENT", "NON_RESIDENT")          # NON_RESIDENT → deferred (spec §1)
IRD_NUMBER_STATES = ("VALID", "PENDING", "MISSING", "INVALID")
TAX_CODE_SOURCES = ("IR330_DECLARATION", "IRD_NOTICE", "NO_NOTIFICATION")
MIN_WAGE_CATEGORIES = ("ADULT", "STARTING_OUT", "TRAINING", "EXEMPTION_PERMIT")
KS_MEMBERSHIP_STATES = ("NOT_MEMBER", "CONTRIBUTING", "OPTED_OUT", "SAVINGS_SUSPENSION", "NOT_ELIGIBLE")
KS_SETTLEMENT_DESTINATIONS = ("INLAND_REVENUE", "COMPLYING_FUND")
ESCT_BASES = ("PRIOR_YEAR", "ESTIMATE", "NEW_EMPLOYEE_ESTIMATE")
EMPLOYER_CONTRIBUTION_TREATMENTS = ("ESCT", "PAYE_ALTERNATIVE")   # PAYE_ALTERNATIVE → deferred (D-6)
AUTHORITY_DEDUCTION_TYPES = ("CHILD_SUPPORT", "STUDENT_LOAN_EXTRA", "IRD_DEDUCTION_NOTICE", "COURT_ATTACHMENT")
FILING_METHODS = ("PAYDAY_GATEWAY", "MYIR_FILE_UPLOAD", "MYIR_ONSCREEN", "PAPER")
REMITTANCE_CLASSES = ("MONTHLY", "TWICE_MONTHLY")
PAYMENT_KINDS = ("REGULAR", "OUT_OF_CYCLE", "LUMP_SUM", "FINAL", "HOLIDAY_PAY_ADVANCE", "CORRECTION")
OBLIGATIONS = ("PAYE", "ACC", "KIWISAVER", "STUDENT_LOAN", "HOLIDAY_GROSS", "MIN_WAGE")
TREATMENTS = ("INCLUDED", "EXCLUDED", "LUMP_SUM_PATH", "REVIEW")
PENDING = "PENDING_G1"
# Payday filing export formats (IR gateway / myIR file). EMPTY until G3
# certifies a schema: every submission file is refused and only JSON
# previews are produced (decision D-3, the Japan / South Africa pattern).
NZ_EXPORT_SCHEMAS = {}

# Out of the first release (spec §1, decision D-6). Each is refused with its
# own reason code rather than approximated.
NZ_DEFERRED = {
    "NZ_NON_RESIDENT_UNSUPPORTED": "Cross-border, treaty and non-resident shadow payroll",
    "NZ_ESS_UNSUPPORTED": "Employee share schemes beyond standard reportable support",
    "NZ_SCHEDULAR_UNSUPPORTED": "Schedular-payment contractors (WT tax code)",
    "NZ_BUREAU_FILING_UNSUPPORTED": "Payroll bureau multi-client agency filing",
    "NZ_KS_PAYE_ALTERNATIVE_UNSUPPORTED": "Employer KiwiSaver contributions taxed under PAYE instead of ESCT",
    "NZ_ACC_INVOICE_UNSUPPORTED": "ACC levy invoices and settlement",
    "NZ_ELA_2028_NOT_IN_FORCE": "Employment Leave Act 2026 rules (effective 6 August 2028)",
}

# ── Scalar engine parameter keys ──────────────────────────────────────────
# key -> kind. The engine's NZ_PARAMETER_KEYS is THIS dict (imported).
NZ_PARAMETER_KEYS = {
    # Scope and policy (spec §1, NZ-006, NZ-011)
    "nz_supported_pay_frequencies": "text",
    "nz_correction_policy": "text",
    "nz_deduction_precedence": "text",
    # Rounding — one row per statutory amount, no global helper (spec §3)
    "nz_paye_rounding": "text",
    "nz_acc_rounding": "text",
    "nz_sl_rounding": "text",
    "nz_ks_rounding": "text",
    "nz_esct_rounding": "text",
    "nz_cs_rounding": "text",
    # ACC earner levy (spec §2, §6)
    "nz_acc_earner_levy_rate": "pct_total",
    "nz_acc_max_liable_earnings": "amount",
    # KiwiSaver (spec §2, §4)
    "nz_ks_employee_rates": "text",
    "nz_ks_temporary_reduction_rate": "pct_total",
    "nz_ks_default_rate": "pct_total",
    "nz_ks_employer_min_rate": "pct_total",
    "nz_ks_employer_min_age": "amount",
    "nz_ks_employer_max_age": "amount",
    "nz_ks_rate_selection_basis": "text",
    # Student loan (spec §2, §5)
    "nz_sl_rate": "pct_total",
    "nz_sl_annual_threshold": "amount",
    "nz_sl_threshold_weekly": "amount",
    "nz_sl_threshold_fortnightly": "amount",
    "nz_sl_threshold_four_weekly": "amount",
    "nz_sl_threshold_monthly": "amount",
    "nz_sl_secondary_basis": "text",
    # Child support (spec §5)
    "nz_cs_protected_net_pct": "pct_total",
    "nz_cs_max_deduction_pct": "pct_total",
    # Minimum wage (spec §2, §7)
    "nz_min_wage_adult": "amount",
    "nz_min_wage_starting_out": "amount",
    "nz_min_wage_training": "amount",
    # Payday filing and remittance (spec §9)
    "nz_payday_filing_working_days": "amount",
    "nz_paper_filing_working_days": "amount",
    "nz_efiling_threshold": "amount",
    "nz_efiling_threshold_after_months": "amount",
    "nz_large_employer_threshold": "amount",
    "nz_remit_monthly_due_day": "amount",
    "nz_remit_first_half_due_day": "amount",
    "nz_remit_second_half_due_day": "amount",
    "nz_remit_december_second_half_due": "text",
    # Holidays Act 2003 (spec §8) — read by Phases 5 and 6
    "nz_hol_annual_weeks": "amount",
    "nz_hol_annual_qualifying_months": "amount",
    "nz_hol_sick_days": "amount",
    "nz_hol_sick_qualifying_months": "amount",
    "nz_hol_sick_carry_max": "amount",
    "nz_hol_bereavement_close_days": "amount",
    "nz_hol_bereavement_other_days": "amount",
    "nz_hol_family_violence_days": "amount",
    "nz_hol_payg_pct": "pct_total",
    "nz_hol_cashup_max_weeks": "amount",
    "nz_hol_ph_worked_multiplier": "amount",
    # Record-keeping (spec §7, S9)
    "nz_record_retention_years": "amount",
}

# ── ContributionRate scalar content ───────────────────────────────────────
# (component_key, label, employee_pct, employer_pct, flat_amount, text_value,
#  source, pending_g1, effective_from, effective_to)
# effective_from/to None → the row is dated by the pack window.
_KS_2026_FROM = date(2026, 4, 1)        # payday on or after (NZ-008)

NZ_SCALAR_CONTENT = (
    ("nz_supported_pay_frequencies", "Pay frequencies certified for calculation (spec §1)",
     None, None, None, "WEEKLY,FORTNIGHTLY,FOUR_WEEKLY,MONTHLY", "S1", True, None, None),
    # NZ-006: retro corrections create compensating results and amended filings.
    ("nz_correction_policy", "Retro-pay and correction policy (NZ-006)",
     None, None, None, PENDING, "S1", True, None, None),
    # NZ-011: legal deduction priority is an approved country policy.
    ("nz_deduction_precedence", "Statutory deduction precedence (NZ-011)",
     None, None, None, PENDING, "S3", True, None, None),

    # Spec §3: official IRD rounding — not stated by the specification.
    ("nz_paye_rounding", "PAYE rounding (per the IRD business rules)", None, None, None, PENDING, "S1", True,
     None, None),
    ("nz_acc_rounding", "ACC earner levy rounding (per the IRD business rules)", None, None, None, PENDING,
     "S1", True, None, None),
    ("nz_sl_rounding", "Student-loan deduction rounding", None, None, None, PENDING, "S1", True, None, None),
    ("nz_ks_rounding", "KiwiSaver contribution rounding", None, None, None, PENDING, "S1", True, None, None),
    ("nz_esct_rounding", "ESCT rounding", None, None, None, PENDING, "S1", True, None, None),
    ("nz_cs_rounding", "Child-support deduction rounding", None, None, None, PENDING, "S1", True, None, None),

    ("nz_acc_earner_levy_rate", "ACC earner levy 2026-27 (% of liable earnings)",
     None, None, "1.7500", None, "S3", True, None, None),
    ("nz_acc_max_liable_earnings", "ACC earner levy maximum liable earnings 2026-27 (NZD)",
     None, None, "156641", None, "S3", True, None, None),

    ("nz_ks_employee_rates", "KiwiSaver employee standard contribution rates (%)",
     None, None, None, "3.5,4,6,8,10", "S4", True, _KS_2026_FROM, None),
    ("nz_ks_temporary_reduction_rate", "KiwiSaver temporary rate reduction (%)",
     None, None, "3.0000", None, "S4", True, _KS_2026_FROM, None),
    ("nz_ks_default_rate", "KiwiSaver default employee rate (paydays on/after 1 Apr 2026)",
     None, None, "3.5000", None, "S4", True, _KS_2026_FROM, None),
    ("nz_ks_employer_min_rate", "KiwiSaver compulsory employer contribution minimum (paydays on/after 1 Apr 2026)",
     None, None, "3.5000", None, "S4", True, _KS_2026_FROM, None),
    ("nz_ks_employer_min_age", "KiwiSaver compulsory employer contributions — from member age",
     None, None, "16", None, "S4", True, _KS_2026_FROM, None),
    # Not stated by the specification: empty, so an employer contribution for
    # a member at an age the rule would exclude BLOCKS until G1 signs it.
    ("nz_ks_employer_max_age", "KiwiSaver compulsory employer contributions — up to member age",
     None, None, None, None, "S4", True, None, None),
    ("nz_ks_rate_selection_basis", "KiwiSaver rate selected by (NZ-008)",
     None, None, None, "PAYDAY", "S4", True, None, None),

    ("nz_sl_rate", "Student-loan standard deduction rate (%)", None, None, "12.0000", None, "S3", True,
     None, None),
    ("nz_sl_annual_threshold", "Student-loan annual repayment threshold (NZD)", None, None, "24128", None,
     "S3", True, None, None),
    ("nz_sl_threshold_weekly", "Student-loan pay-period threshold — weekly (NZD)", None, None, "464", None,
     "S3", True, None, None),
    ("nz_sl_threshold_fortnightly", "Student-loan pay-period threshold — fortnightly (NZD)", None, None, "928",
     None, "S3", True, None, None),
    ("nz_sl_threshold_four_weekly", "Student-loan pay-period threshold — four-weekly (NZD)", None, None, "1856",
     None, "S3", True, None, None),
    ("nz_sl_threshold_monthly", "Student-loan pay-period threshold — monthly (NZD)", None, None, "2010.66",
     None, "S3", True, None, None),
    ("nz_sl_secondary_basis", "Student loan on secondary codes — deduction basis",
     None, None, None, "WHOLE_PAYMENT", "S3", True, None, None),

    ("nz_cs_protected_net_pct", "Child support — protected net earnings (% of net)",
     None, None, "60.0000", None, "S3", True, None, None),
    ("nz_cs_max_deduction_pct", "Child support — maximum deduction share (% of net)",
     None, None, "40.0000", None, "S3", True, None, None),

    ("nz_min_wage_adult", "Minimum wage — adult (NZD per hour, from 1 Apr 2026)",
     None, None, "23.95", None, "S6", True, date(2026, 4, 1), None),
    ("nz_min_wage_starting_out", "Minimum wage — starting-out (NZD per hour, from 1 Apr 2026)",
     None, None, "19.16", None, "S6", True, date(2026, 4, 1), None),
    ("nz_min_wage_training", "Minimum wage — training (NZD per hour, from 1 Apr 2026)",
     None, None, "19.16", None, "S6", True, date(2026, 4, 1), None),

    ("nz_payday_filing_working_days", "Electronic employment information due (working days after payday)",
     None, None, "2", None, "S2", True, None, None),
    ("nz_paper_filing_working_days", "Paper employment information due (working days after payday)",
     None, None, "10", None, "S2", True, None, None),
    ("nz_efiling_threshold", "Electronic filing required at annual PAYE + ESCT of (NZD)",
     None, None, "50000", None, "S2", True, None, None),
    ("nz_efiling_threshold_after_months", "Electronic filing threshold applies after (months as employer)",
     None, None, "6", None, "S2", True, None, None),
    ("nz_large_employer_threshold", "Twice-monthly remittance at annual PAYE + ESCT of (NZD)",
     None, None, "500000", None, "S5", True, None, None),
    ("nz_remit_monthly_due_day", "Monthly remitter — due day of the following month",
     None, None, "20", None, "S5", True, None, None),
    ("nz_remit_first_half_due_day", "Twice-monthly remitter — 1st–15th due day of the same month",
     None, None, "20", None, "S5", True, None, None),
    ("nz_remit_second_half_due_day", "Twice-monthly remitter — 16th–end due day of the following month",
     None, None, "5", None, "S5", True, None, None),
    ("nz_remit_december_second_half_due", "Twice-monthly remitter — 16–31 December due (MM-DD)",
     None, None, None, "01-15", "S5", True, None, None),

    ("nz_hol_annual_weeks", "Annual holidays — weeks after each 12 months' continuous employment",
     None, None, "4", None, "S7", True, None, None),
    ("nz_hol_annual_qualifying_months", "Annual holidays — qualifying continuous employment (months)",
     None, None, "12", None, "S7", True, None, None),
    ("nz_hol_sick_days", "Sick leave — days per entitlement year", None, None, "10", None, "S7", True,
     None, None),
    ("nz_hol_sick_qualifying_months", "Sick leave — qualifying employment (months)", None, None, "6", None,
     "S7", True, None, None),
    ("nz_hol_sick_carry_max", "Sick leave — maximum balance carried over (days)", None, None, "20", None,
     "S7", True, None, None),
    ("nz_hol_bereavement_close_days", "Bereavement leave — immediate family (days)", None, None, "3", None,
     "S7", True, None, None),
    ("nz_hol_bereavement_other_days", "Bereavement leave — other qualifying bereavement (days)",
     None, None, "1", None, "S7", True, None, None),
    ("nz_hol_family_violence_days", "Family violence leave — paid days per year", None, None, "10", None,
     "S7", True, None, None),
    ("nz_hol_payg_pct", "Pay-as-you-go annual holiday pay (% of gross earnings)",
     None, None, "8.0000", None, "S7", True, None, None),
    ("nz_hol_cashup_max_weeks", "Annual holidays cash-up — maximum weeks per entitlement year",
     None, None, "1", None, "S7", True, None, None),
    ("nz_hol_ph_worked_multiplier", "Public holiday worked — minimum pay multiplier",
     None, None, "1.5", None, "S7", True, None, None),

    ("nz_record_retention_years", "Wage/time and holiday/leave records retained (years)",
     None, None, "6", None, "S9", True, None, None),
)

# Rows that are deliberately empty: present so "not configured" is explicit,
# never filled with an assumed value.
NZ_EMPTY_BY_DESIGN = frozenset({"nz_ks_employer_max_age"})

# ── Rate bands (TaxSlab) ──────────────────────────────────────────────────
# (min_amount, max_amount, rate_pct): rate_pct on income above min_amount up
# to max_amount. Spec §3 (personal tax bands 2026-27) and §4 (ESCT bands).
NZ_PAYE_BANDS = (
    ("0", "15600", "10.5000"),
    ("15600", "53500", "17.5000"),
    ("53500", "78100", "30.0000"),
    ("78100", "180000", "33.0000"),
    ("180000", None, "39.0000"),
)
NZ_ESCT_BANDS = (
    ("0", "18720", "10.5000"),
    ("18720", "64200", "17.5000"),
    ("64200", "93720", "30.0000"),
    ("93720", "216000", "33.0000"),
    ("216000", None, "39.0000"),
)

# ── Tax-code catalogue (TaxSlab rule_type="NZ_TAX_CODE") ──────────────────
# (code, income class, status, student loan, independent earner, label)
NZ_TAX_CODES = (
    ("M", "MAIN", "SUPPORTED", False, False, "Main income"),
    ("ME", "MAIN", "SUPPORTED", False, True, "Main income — independent earner tax credit"),
    ("M SL", "MAIN", "SUPPORTED", True, False, "Main income with student loan"),
    ("ME SL", "MAIN", "SUPPORTED", True, True, "Main income — independent earner, with student loan"),
    ("SB", "SECONDARY", "SUPPORTED", False, False, "Secondary income — SB"),
    ("S", "SECONDARY", "SUPPORTED", False, False, "Secondary income — S"),
    ("SH", "SECONDARY", "SUPPORTED", False, False, "Secondary income — SH"),
    ("ST", "SECONDARY", "SUPPORTED", False, False, "Secondary income — ST"),
    ("SA", "SECONDARY", "SUPPORTED", False, False, "Secondary income — SA"),
    ("SB SL", "SECONDARY", "SUPPORTED", True, False, "Secondary income — SB with student loan"),
    ("S SL", "SECONDARY", "SUPPORTED", True, False, "Secondary income — S with student loan"),
    ("SH SL", "SECONDARY", "SUPPORTED", True, False, "Secondary income — SH with student loan"),
    ("ST SL", "SECONDARY", "SUPPORTED", True, False, "Secondary income — ST with student loan"),
    ("SA SL", "SECONDARY", "SUPPORTED", True, False, "Secondary income — SA with student loan"),
    ("ND", "SPECIAL", "SUPPORTED", False, False, "No notification / non-declaration"),
    ("STC", "SPECIAL", "SUPPORTED", False, False, "Tailored tax code (Inland Revenue certificate)"),
    # Deferred from the first release (spec §1, D-6): refused with a reason.
    ("CAE", "SPECIAL", "REFUSED", False, False, "Casual agricultural employee — not in the first release"),
    ("EDW", "SPECIAL", "REFUSED", False, False, "Election day worker — not in the first release"),
    ("NSW", "SPECIAL", "REFUSED", False, False, "Recognised seasonal worker — not in the first release"),
    ("WT", "SPECIAL", "REFUSED", False, False, "Schedular payments — not in the first release"),
)
SUPPORTED_TAX_CODES = tuple(code for code, _cls, status, *_ in NZ_TAX_CODES if status == "SUPPORTED")
REFUSED_TAX_CODES = tuple(code for code, _cls, status, *_ in NZ_TAX_CODES if status == "REFUSED")

# ── Authority tables not reproduced by the specification ──────────────────
# Each is filled ONLY from an archived authority artefact (source code in
# the key) and signed at the named gate. Empty → every calculation needing
# it BLOCKS.
NZ_EMPTY_TABLES = {
    # IRD payday PAYE method for main codes: period annualisation factors,
    # whole-dollar steps and order of operations (S1).
    "paye_main_method": {"source": "S1", "gate": "G1", "rows": (), "rule_type": NZ_PAYE_METHOD_RULE},
    # Flat rates for the secondary codes SB/S/SH/ST/SA (S1/S3).
    "paye_secondary_rates": {"source": "S1", "gate": "G1", "rows": (), "rule_type": NZ_SECONDARY_RATE_RULE},
    # No-notification (ND) rate (S1).
    "paye_nd_rate": {"source": "S1", "gate": "G1", "rows": (), "rule_type": NZ_ND_RATE_RULE},
    # Independent earner tax credit for ME codes (S1/S3).
    "ietc_parameters": {"source": "S1", "gate": "G1", "rows": (), "rule_type": NZ_IETC_RULE},
    # Child-support variation codes reported when the full amount cannot be taken (S3).
    "cs_variation_codes": {"source": "S3", "gate": "G1", "rows": (), "rule_type": NZ_CS_VARIATION_RULE},
    # IRD lump-sum / extra-pay PAYE method (S1) — Phase 6.
    "lump_sum_method": {"source": "S1", "gate": "G1", "rows": (), "rule_type": NZ_LUMP_SUM_RULE},
    # Holiday pay in advance — standard / alternative PAYE approach (S1) — Phase 6.
    "holiday_pay_advance_method": {"source": "S1", "gate": "G1", "rows": (),
                                   "rule_type": NZ_HOLIDAY_ADVANCE_RULE},
    # IRD official calculation examples for golden fixtures (AC-NZ-01).
    "ird_official_examples": {"source": "S1", "gate": "G1", "rows": (), "rule_type": NZ_IRD_EXAMPLE_RULE},
    # Public holidays incl. Matariki and regional anniversary days (S7).
    "public_holidays": {"source": "S7", "gate": "G2", "rows": (), "rule_type": NZ_PUBLIC_HOLIDAY_RULE},
    # Employer ACC classification units and levy rates (NZ-014) — employer
    # content, evidenced per employer, no authority source in the register.
    # Not required to activate the national pack (employer_content=True).
    "acc_employer_classifications": {"source": None, "gate": "G1", "rows": (),
                                     "rule_type": NZ_ACC_CLASSIFICATION_RULE, "employer_content": True},
}

# ── Regions (ISO 3166-2:NZ) — for regional anniversary days (Phase 5) ─────
NZ_REGIONS = (
    ("NTL", "Northland"), ("AUK", "Auckland"), ("WKO", "Waikato"), ("BOP", "Bay of Plenty"),
    ("GIS", "Gisborne"), ("HKB", "Hawke's Bay"), ("TKI", "Taranaki"), ("MWT", "Manawatū-Whanganui"),
    ("WGN", "Wellington"), ("TAS", "Tasman"), ("NSN", "Nelson"), ("MBH", "Marlborough"),
    ("WTC", "West Coast"), ("CAN", "Canterbury"), ("OTA", "Otago"), ("STL", "Southland"),
    ("CIT", "Chatham Islands Territory"),
)

# ── Earning classification — TaxSlab rule_type="NZ_EARNING_CLASS" ─────────
# Components map to PayrollContext (Phase 3): SALARY=basic, OVERTIME=overtime,
# named components from nz_components, OTHER_EARNINGS = gross minus every
# named component. Only the treatments the specification states are decided;
# everything else is REVIEW until G1 signs the per-base interpretation.
NZ_COMPONENTS = ("SALARY", "OVERTIME", "ALLOWANCE", "BONUS", "LUMP_SUM", "HOLIDAY_PAY",
                 "ACC_COMPENSATION", "REIMBURSEMENT", "OTHER_EARNINGS")

_DECIDED = {
    # PAYE, ACC, KiwiSaver and student loan: salary/wages (spec §3–§5).
    ("PAYE", "SALARY"): "INCLUDED", ("PAYE", "OVERTIME"): "INCLUDED",
    ("PAYE", "BONUS"): "LUMP_SUM_PATH", ("PAYE", "LUMP_SUM"): "LUMP_SUM_PATH",
    ("ACC", "SALARY"): "INCLUDED", ("ACC", "OVERTIME"): "INCLUDED",
    ("ACC", "BONUS"): "LUMP_SUM_PATH", ("ACC", "LUMP_SUM"): "LUMP_SUM_PATH",
    ("KIWISAVER", "SALARY"): "INCLUDED", ("KIWISAVER", "OVERTIME"): "INCLUDED",
    ("KIWISAVER", "BONUS"): "LUMP_SUM_PATH", ("KIWISAVER", "LUMP_SUM"): "LUMP_SUM_PATH",
    ("STUDENT_LOAN", "SALARY"): "INCLUDED", ("STUDENT_LOAN", "OVERTIME"): "INCLUDED",
    ("STUDENT_LOAN", "BONUS"): "LUMP_SUM_PATH", ("STUDENT_LOAN", "LUMP_SUM"): "LUMP_SUM_PATH",
    # Holidays Act gross earnings (spec §8) — Phases 5 and 6.
    ("HOLIDAY_GROSS", "SALARY"): "INCLUDED", ("HOLIDAY_GROSS", "OVERTIME"): "INCLUDED",
    # Minimum wage (spec §7): salary for hours worked.
    ("MIN_WAGE", "SALARY"): "INCLUDED",
}
_SOURCE_BY_OBLIGATION = {"PAYE": "S3", "ACC": "S3", "KIWISAVER": "S4", "STUDENT_LOAN": "S3",
                         "HOLIDAY_GROSS": "S7", "MIN_WAGE": "S6"}

# (obligation, treatment, component, label, source)
NZ_EARNING_CLASSES = tuple(
    (obligation, _DECIDED.get((obligation, component), "REVIEW"), component,
     (f"{component.replace('_', ' ').title()} — {obligation.replace('_', ' ').lower()} "
      + ("base" if (obligation, component) in _DECIDED else "treatment needs signed evidence")),
     _SOURCE_BY_OBLIGATION[obligation])
    for obligation in OBLIGATIONS for component in NZ_COMPONENTS
)

# ── Category labels for UI grouping ──────────────────────────────────────
NZ_CATEGORIES = {
    "paye": "PAYE & ACC Earner Levy",
    "kiwisaver": "KiwiSaver & ESCT",
    "deductions": "Student Loan & Child Support",
    "minimum_wage": "Minimum Wage",
    "holidays": "Holidays Act 2003",
    "filing": "Payday Filing & Remittance",
    "policy": "Scope, Rounding & Policy",
}


def _in_force(eff_from, eff_to, as_of: date) -> bool:
    if eff_from is not None and as_of < eff_from:
        return False
    if eff_to is not None and as_of > eff_to:
        return False
    return True


def content_rows_in_force(as_of: date):
    """Scalar content rows legally in force on `as_of` (a payday), keyed by component_key."""
    return {row[0]: row for row in NZ_SCALAR_CONTENT if _in_force(row[8], row[9], as_of)}


def earning_classes_in_force(as_of: date):
    """Earning classification rows (undated in this Draft)."""
    return NZ_EARNING_CLASSES
