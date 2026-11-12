"""
modules/payroll/engine/countries/malaysia_content.py
-----------------------------------------------------
Malaysia 2026 statutory content catalog (Draft) — the ONE list of every rate,
threshold, schedule, date rule and classification the Malaysia engine
(engine/countries/malaysia.py + engine/jurisdictions/malaysia/*) reads from
`rate_map` / `slabs`. Pure data, no ORM import, shared by:

  * malaysia_service.seed_malaysia_pack — writes these rows into the
    MY-PAYROLL-2026 canonical JurisdictionPack (Draft);
  * the statutory workbook (statutory_workbook.py + my_workbook_adapter.py)
    — the Excel template a Super Admin fills from the official documents;
  * tests/test_malaysia_content.py — pins the values below to ZP-MY-ENG-001.

Production safety rule (spec, page 1): "No rate, contribution table, relief,
eligibility condition, filing schema, statutory date, wage floor or
labour-rule entitlement may exist only as application code or UI logic."
Every value here reaches calculation only through a signed, effective-dated
pack. Only values the specification itself states are filled in; anything
else is EMPTY or "PENDING_G1" — never a guess.

EVERY row is seeded UNSIGNED (label carries "[PENDING G1]"): a value taken
from a document is "extracted", not verified. A row becomes usable only
when a Super Admin signs it against a stored, hashed source document
reviewed by a second Super Admin (spec §16 G1). `spec_value` below only
records whether the specification states the value.

Conventions (the engine must match them):
  * Scalar parameters are ContributionRate rows keyed by component_key:
      kind "pct_employee" / "pct_employer" / "pct_both" — PERCENT numbers
        (11 = 11%) in employee_rate_pct / employer_rate_pct;
      kind "amount" — flat_amount (RM, days, hours or a count);
      kind "text"   — text_value (an enum label, list or "PENDING_G1").
    Every row names its DATE BASIS (MY-006): CALENDAR_YEAR, WAGE_MONTH,
    CONTRIBUTION_MONTH, PAYMENT_DATE or EMPLOYMENT_EVENT.
  * TERRITORY (MY-024): national rows have jurisdiction_state NULL.
    Labour-law rows exist once per territory — PENINSULAR_LABUAN, SABAH,
    SARAWAK — with jurisdiction_state = the territory and the component key
    suffixed "__PEN" / "__SBH" / "__SWK" (territory_key()), because the
    engine indexes rows by key. Never one row for "Malaysia" labour law.
  * Contribution schedules are TABLE rows (MY-005 / MY-011), never derived
    from a percentage: TaxSlab rule_type in SCHEDULE_RULES,
      filing_status = member class / category,
      min_amount / max_amount = the schedule's wage band,
      tax_regime = "EMPLOYEE" or "EMPLOYER",
      flat_amount = the contribution amount for that band.
    They ship with NO rows: they are loaded from the official PDFs through
    the workbook. A percentage scalar below (e.g. EPF 11%) is reference
    content for the direct-calculation branch only where a signed rule
    permits it.
  * Earning classification rows are TaxSlab rule_type="MY_EARNING_CLASS":
      filing_status = pay component, tax_regime = obligation,
      assessment_basis = "INCLUDED" | "EXCLUDED" | "REVIEW".
    Each obligation has its own base. REVIEW = the specification does not
    decide; a non-zero REVIEW component BLOCKS that obligation.

Scope (spec §1): private-sector employers, employees under contracts of
service, MONTHLY pay in release 1 (decision D6). Gig/platform workers,
public sector, domestic workers, sector awards and tax equalisation have NO
rows on purpose — the engine returns UNSUPPORTED.
"""

from datetime import date

PACK_STATUS = "Draft"
SPEC = "ZP-MY-ENG-001 v1.0"

MY_2026 = ("MY-PAYROLL-2026", date(2026, 1, 1), date(2026, 12, 31))
TAX_YEAR = "2026"
CURRENCY = "MYR"
PENDING = "PENDING_G1"
PENDING_MARK = "[PENDING G1]"

# ── Evidence register (ZP-MY-ENG-001 §16, S1–S15, reviewed 22 Sep 2026) ────
SOURCE_REFERENCES = (
    ("S1", "HASiL — MTD tables and data specifications: 2026 computerised MTD specification and official "
           "2026 test questions"),
    ("S2", "HASiL — Employer responsibilities / PCB payment: PCB remitted by the 15th of the following "
           "month; Form E/CP8D, EA/EC and employer-event obligations"),
    ("S3", "HASiL — TP1/TP3 2026 materials: employee claims, prior-employment inputs and seven-year TP1 "
           "retention"),
    ("S4", "HASiL — Public Ruling 2/2026 (foreign nationals): residence analysis and 30% non-resident "
           "employment-income baseline"),
    ("S5", "EPF — Employer mandatory contribution / Third Schedule: contribution branches"),
    ("S6", "EPF — Non-Malaysian employees: mandatory 2% employer + 2% employee from October 2025 wages"),
    ("S7", "PERKESO — Contribution rate: RM6,000 Act 4 / Act 800 wage ceiling and authority schedules"),
    ("S8", "PERKESO — Foreign workers: Act 4 treatment and LINDUNG 24 JAM phase 1 from 1 Jun 2026"),
    ("S9", "PERKESO — Employed worker / EIS: coverage, age rule, 0.2% / 0.2% baseline, RM6,000 ceiling"),
    ("S10", "MOHR — Minimum Wages Order 2024 implementation: RM1,700/month"),
    ("S11", "JTKSM — Employment Act 1955 amendment FAQ: Peninsular/Labuan scope, 45-hour week, 98-day "
            "maternity, 7-day paternity, RM4,000 overtime boundary"),
    ("S12", "Sabah Labour Department — Labour Ordinance of Sabah (Amendment) Act 2025, in force 1 May 2025"),
    ("S13", "Sarawak Labour Department — Labour Ordinance amendment FAQ, in force 1 May 2025"),
    ("S14", "HRD Corp — Registered employers / levy: 10+ Malaysian employees compulsory at 1%; 5-9 "
            "optional at 0.5%; levy-base guidance"),
    ("S15", "Personal Data Protection Commissioner — PDPA amendment, DPO, breach and cross-border "
            "transfer guidance"),
)
SOURCE_CODES = tuple(code for code, _ in SOURCE_REFERENCES)
# Public URLs from the evidence register (spec §16). A URL is not archived
# evidence: archived copies and their SHA-256 are attached at gate G1.
SOURCE_URLS = {
    "S1": "https://www.hasil.gov.my/majikan/jadual-pcb-dan-spesifikasi-data/",
    "S2": "https://www.hasil.gov.my/majikan/tanggungjawab-majikan/",
    "S3": "https://www.hasil.gov.my/majikan/jadual-pcb-dan-spesifikasi-data/",
    "S4": "https://www.hasil.gov.my/media/ikelbhz0/pr-2-2026-tax-treatment-of-foreign-nationals-exercising-employment-in-malaysia.pdf",
    "S5": "https://www.kwsp.gov.my/en/employer/responsibilities/mandatory-contribution",
    "S6": "https://www.kwsp.gov.my/en/employer/responsibilities/non-malaysian-citizen-employees",
    "S7": "https://www.perkeso.gov.my/en/contribution-rate/",
    "S8": "https://www.perkeso.gov.my/en/our-services/protection/foreign-worker",
    "S9": "https://perkeso.gov.my/en/our-services/protection/pekerja-bermajikan.html",
    "S10": "https://www.mohr.gov.my/images/pdf/JLD4%20%2819%29%20KENYATAAN%20MEDIA%20KESUMA_Pelaksanaan%20Perintah%20Gaji%20Minimum%20RM1700%20Sebulan.pdf",
    "S11": "https://jtksm.mohr.gov.my/ms/soalan-lazim/akta-kerja-1955-pindaan-2022",
    "S12": "https://jtksbh.mohr.gov.my/images/warta_2025/A1753_-Labour_Ordinance_of_Sabah_Amendment_Act_2025.pdf",
    "S13": "https://www.jtkswk.gov.my/v2/?lang=en&page_id=3817",
    "S14": "https://hrdcorp.gov.my/registered-employers",
    "S15": "https://www.pdp.gov.my/ppdpv1/en/akta709/",
}

# ── Enumerations (vocabulary only — no statutory values) ──────────────────
TERRITORIES = ("PENINSULAR_LABUAN", "SABAH", "SARAWAK")
TERRITORY_SUFFIX = {"PENINSULAR_LABUAN": "PEN", "SABAH": "SBH", "SARAWAK": "SWK"}
TERRITORY_SOURCE = {"PENINSULAR_LABUAN": "S11", "SABAH": "S12", "SARAWAK": "S13"}
# Public-holiday calendars are per state / federal territory, not per labour
# territory (Labuan follows Peninsular labour law but has its own holidays).
HOLIDAY_STATES = ("JHR", "KDH", "KTN", "MLK", "NSN", "PHG", "PRK", "PLS", "PNG", "SBH", "SWK", "SGR", "TRG",
                  "KUL", "LBN", "PJY")
CITIZENSHIP = ("CITIZEN", "PERMANENT_RESIDENT", "NON_CITIZEN")
TAX_RESIDENCE = ("RESIDENT", "NON_RESIDENT", "REVIEW_REQUIRED")
EPF_MEMBER_CLASSES = ("MY_PR_BELOW_60", "MY_60_PLUS", "PR_OR_PRE1998_NONMY_60_PLUS", "NONMY_POST_1998",
                      "NOT_COVERED")
SOCSO_CATEGORIES = ("EI_AND_INVALIDITY", "EI_ONLY", "FOREIGN_WORKER", "NOT_COVERED", "UNSUPPORTED_DOMESTIC")
EIS_STATES = ("COVERED", "EXEMPT_AGE", "EXEMPT_HISTORY", "FOREIGN_EXCLUDED")
HRD_CATEGORIES = ("COMPULSORY", "OPTIONAL_REGISTERED", "NOT_REGISTERED")
WORK_PASS_TYPES = ("NONE", "EMPLOYMENT_PASS", "VISIT_PASS_TEMP_EMPLOYMENT", "RESIDENCE_PASS_TALENT", "OTHER")
DECLARATION_TYPES = ("TP1", "TP3", "CP38", "ZAKAT", "TAX_BORNE_BY_EMPLOYER", "EPF_VOLUNTARY_EXCESS")
EMPLOYER_EVENT_TYPES = ("CP22", "CP22A", "CP21", "DEATH_NOTICE")
FILING_FORMS = ("PCB_MONTHLY", "EPF_MONTHLY", "PERKESO_EIS_MONTHLY", "HRD_MONTHLY", "EA", "EC", "FORM_E", "CP8D",
                "EDATA_PRAISI", "CP22", "CP22A", "CP21")
PAY_FREQUENCIES_SUPPORTED = ("MONTHLY",)
CONTRACT_TYPES_SUPPORTED = ("CONTRACT_OF_SERVICE",)
TREATMENTS = ("INCLUDED", "EXCLUDED", "REVIEW")
DATE_BASES = ("CALENDAR_YEAR", "WAGE_MONTH", "CONTRIBUTION_MONTH", "PAYMENT_DATE", "EMPLOYMENT_EVENT")
ANNUAL_DUE_RULES = ("END_FEBRUARY", "END_MARCH")
# Rounding vocabulary (unit + mode). WHICH one applies to each obligation is
# not given by the specification: every my_rounding_* row is PENDING_G1.
# Engine policies (values PENDING_G1 until signed; vocabulary only).
EPF_AGE_TRANSITION_RULES = ("AGE_AT_WAGE_MONTH_START", "FROM_MONTH_AFTER_BIRTHDAY")
EIS_AGE_RULES = ("AGE_AT_WAGE_MONTH_START", "AGE_AT_WAGE_MONTH_END")
HRD_NON_MALAYSIAN_RULES = ("LEVY_ON_ALL_COVERED_WAGES", "MALAYSIAN_EMPLOYEES_ONLY")
EPF_DIRECT_CALC_RULES = ("NON_MALAYSIAN_PART_F_ONLY",)
ROUNDING_RULES = ("SEN_HALF_UP", "SEN_DOWN", "SEN_UP", "FIVE_SEN_UP", "RINGGIT_HALF_UP", "RINGGIT_DOWN",
                  "RINGGIT_UP")
# Schedule bands: lower bound exclusive, upper bound inclusive ("exceeds X but
# not exceeding Y"); the first band starts at 0 (inclusive); the top band may
# be open. A schedule row may carry effective_from / effective_to (e.g. the
# LINDUNG 24 JAM phase): the row in force on the pay date is used.
# Public-holiday rows: the date (ISO) in tax_formula, the name in rate_label,
# jurisdiction_state = the HOLIDAY_STATES code (NULL = national).

# ── TaxSlab rule_type discriminators (all <= 30 chars) ────────────────────
MY_EPF_SCHEDULE_RULE = "MY_EPF_SCHEDULE"
MY_SOCSO_SCHEDULE_RULE = "MY_SOCSO_SCHEDULE"
MY_EIS_SCHEDULE_RULE = "MY_EIS_SCHEDULE"
MY_FW_SOCSO_SCHEDULE_RULE = "MY_FW_SOCSO_SCHEDULE"
MY_PCB_TABLE_RULE = "MY_PCB_TABLE"
MY_PUBLIC_HOLIDAY_RULE = "MY_PUBLIC_HOLIDAY"
MY_EARNING_CLASS_RULE = "MY_EARNING_CLASS"
MY_AUTHORITY_EXAMPLE_RULE = "MY_AUTHORITY_EXAMPLE"
SCHEDULE_RULES = (MY_EPF_SCHEDULE_RULE, MY_SOCSO_SCHEDULE_RULE, MY_EIS_SCHEDULE_RULE, MY_FW_SOCSO_SCHEDULE_RULE)
# Member class / category vocabulary per schedule (filing_status).
SCHEDULE_CLASSES = {
    MY_EPF_SCHEDULE_RULE: EPF_MEMBER_CLASSES[:-1],
    MY_SOCSO_SCHEDULE_RULE: ("EI_AND_INVALIDITY", "EI_ONLY"),
    MY_EIS_SCHEDULE_RULE: ("COVERED",),
    MY_FW_SOCSO_SCHEDULE_RULE: ("FOREIGN_WORKER",),
}
SCHEDULE_SOURCE = {MY_EPF_SCHEDULE_RULE: "S5", MY_SOCSO_SCHEDULE_RULE: "S7", MY_EIS_SCHEDULE_RULE: "S9",
                   MY_FW_SOCSO_SCHEDULE_RULE: "S8"}
# Tables activation requires to hold signed rows (PCB tables come with the S1
# specification in Phase 4 and are required from then on).
REQUIRED_TABLES = SCHEDULE_RULES + (MY_PUBLIC_HOLIDAY_RULE,)

# ── Form / schema catalogue (Phase 9) — DELIBERATELY EMPTY ────────────────
# No authority file layout is archived yet; until a form's `versions` holds
# one, a filing is a canonical preview and authorisation is refused.
MY_FORM_SCHEMA_CATALOG = {
    form: {"authority": authority, "versions": {}, "evidence": source}
    for form, authority, source in (
        ("PCB_MONTHLY", "HASIL", "S1"), ("EPF_MONTHLY", "EPF", "S5"), ("PERKESO_EIS_MONTHLY", "PERKESO", "S7"),
        ("HRD_MONTHLY", "HRD", "S14"), ("EA", "HASIL", "S2"), ("EC", "HASIL", "S2"), ("FORM_E", "HASIL", "S2"),
        ("CP8D", "HASIL", "S2"), ("EDATA_PRAISI", "HASIL", "S2"), ("CP22", "HASIL", "S2"),
        ("CP22A", "HASIL", "S2"), ("CP21", "HASIL", "S2"))
}

# ── Accumulator ledger keys (Phase 2 table, spec §5 / §12) ─────────────────
ACCUMULATORS = ("PCB_GROSS_NORMAL", "PCB_GROSS_ADDITIONAL", "PCB_PAID", "PCB_EPF_RELIEF_USED", "ZAKAT_PAID",
                "CP38_PAID", "EPF_EE", "EPF_ER", "SOCSO_EE", "SOCSO_ER", "EIS_EE", "EIS_ER", "HRD_LEVY",
                "LEAVE_ANNUAL_DAYS", "LEAVE_SICK_DAYS")

# ── Scalar parameters ─────────────────────────────────────────────────────
_CY, _WM, _CM, _PD, _EE = DATE_BASES

# National parameters: key -> kind.
MALAYSIA_PARAMETER_KEYS = {
    # scope and policy
    "my_supported_pay_frequencies": "text",
    "my_supported_contract_types": "text",
    "my_rounding_pcb": "text",
    "my_rounding_epf_direct": "text",
    "my_rounding_socso": "text",
    "my_rounding_eis": "text",
    "my_rounding_hrd": "text",
    # minimum wage (spec §3, §9)
    "my_min_wage_monthly": "amount",
    "my_min_wage_daily_rule": "text",
    "my_min_wage_hourly_rule": "text",
    # PCB / MTD (spec §5) — the computation itself comes with S1 (Phase 4)
    "my_pcb_spec_version": "text",
    "my_pcb_remittance_day": "amount",
    "my_pcb_non_resident_rate": "pct_employee",
    "my_tp1_retention_years": "amount",
    # EPF (spec §6) — reference rates; the Third Schedule table controls
    "my_epf_wage_band_threshold": "amount",
    "my_epf_schedule_upper_wage": "amount",
    "my_epf_rate_my_pr_low": "pct_both",
    "my_epf_rate_my_pr_high": "pct_both",
    "my_epf_rate_60_plus": "pct_both",
    "my_epf_rate_pr_hist_60_plus_low": "pct_both",
    "my_epf_rate_pr_hist_60_plus_high": "pct_both",
    "my_epf_rate_non_malaysian": "pct_both",
    "my_epf_direct_calc_rule": "text",
    "my_epf_age_transition_rule": "text",
    "my_epf_age_threshold": "amount",
    # PERKESO Act 4 / EIS Act 800 / foreign workers (spec §7)
    "my_socso_wage_ceiling": "amount",
    "my_socso_employee_rate_ref": "pct_employee",
    "my_eis_rate_ref": "pct_both",
    "my_eis_min_age": "amount",
    "my_eis_max_age": "amount",
    "my_eis_age_rule": "text",
    "my_fw_lindung_employee_rate": "pct_employee",
    "my_fw_lindung_phase_rule": "text",
    # HRD levy (spec §8)
    "my_hrd_rate_compulsory": "pct_employer",
    "my_hrd_rate_optional": "pct_employer",
    "my_hrd_compulsory_min_employees": "amount",
    "my_hrd_optional_min_employees": "amount",
    "my_hrd_base_rule": "text",
    "my_hrd_non_malaysian_rule": "text",
    # employer events, filing and settlement (spec §10, §11)
    "my_cp22_days_after_start": "amount",
    "my_cp22a_days_before_cessation": "amount",
    "my_cp22a_days_after_death": "amount",
    "my_cp21_days_before_departure": "amount",
    "my_clearance_hold_max_days": "amount",
    "my_ea_due": "text",
    "my_form_e_due": "text",
    "my_epf_due_rule": "text",
    "my_socso_due_rule": "text",
    "my_hrd_due_rule": "text",
    "my_transfer_split_rule": "text",
    # operations (Phase 10 evidence; the specification gives no values)
    "my_record_retention_years": "amount",
    "my_reconciliation_tolerance": "amount",
    "my_parallel_materiality_amount": "amount",
}

# Labour-law parameters, one row PER TERRITORY: base key -> kind.
MALAYSIA_TERRITORY_KEYS = {
    "my_weekly_hours_max": "amount",
    "my_ot_exclusion_wage": "amount",
    "my_ot_multiplier_workday": "amount",
    "my_ot_multiplier_rest_day": "amount",
    "my_ot_multiplier_public_holiday": "amount",
    "my_ot_rate_divisor_rule": "text",
    "my_maternity_days": "amount",
    "my_paternity_days": "amount",
    "my_sick_leave_tiers": "text",
    "my_hospitalisation_days": "amount",
    "my_annual_leave_tiers": "text",
    "my_leave_pay_rule": "text",
}

# (key, label, ee_pct, er_pct, flat, text, source, spec_value, eff_from, eff_to, date_basis)
# effective_from/to None -> the row is dated by the pack window. spec_value
# False = the specification gives no value (EMPTY / PENDING_G1).
_NATIONAL = (
    ("my_supported_pay_frequencies", "Pay frequencies certified in release 1 (decision D6)",
     None, None, None, "MONTHLY", "S2", True, None, None, _WM),
    ("my_supported_contract_types", "Worker types in release 1 (spec §1: contracts of service)",
     None, None, None, "CONTRACT_OF_SERVICE", "S2", True, None, None, _EE),
    ("my_rounding_pcb", "PCB statutory rounding (S1 specification)", None, None, None, PENDING, "S1", False,
     None, None, _PD),
    ("my_rounding_epf_direct", "EPF rounding on the direct-calculation branch", None, None, None, PENDING, "S5",
     False, None, None, _WM),
    ("my_rounding_socso", "PERKESO rounding (schedule controls)", None, None, None, PENDING, "S7", False,
     None, None, _CM),
    ("my_rounding_eis", "EIS rounding (schedule controls)", None, None, None, PENDING, "S9", False,
     None, None, _CM),
    ("my_rounding_hrd", "HRD levy rounding", None, None, None, PENDING, "S14", False, None, None, _WM),
    ("my_min_wage_monthly", "Minimum wage per month (RM)", None, None, "1700", None, "S10", True,
     None, None, _WM),
    ("my_min_wage_daily_rule", "Minimum wage daily equivalent rule", None, None, None, PENDING, "S10", False,
     None, None, _WM),
    ("my_min_wage_hourly_rule", "Minimum wage hourly equivalent rule", None, None, None, PENDING, "S10", False,
     None, None, _WM),
    ("my_pcb_spec_version", "HASiL computerised MTD specification version in force", None, None, None, PENDING,
     "S1", False, None, None, _PD),
    ("my_pcb_remittance_day", "PCB remitted by this day of the following month", None, None, "15", None, "S2",
     True, None, None, _PD),
    ("my_pcb_non_resident_rate", "Non-resident employment income rate (%)", "30", None, None, None, "S4", True,
     None, None, _PD),
    ("my_tp1_retention_years", "TP1 document retention (years)", None, None, "7", None, "S3", True,
     None, None, _CY),
    ("my_epf_wage_band_threshold", "EPF employer-rate wage boundary (RM)", None, None, "5000", None, "S5", True,
     None, None, _WM),
    ("my_epf_schedule_upper_wage", "Third Schedule table controls up to this wage (RM)", None, None, "20000",
     None, "S5", True, None, None, _WM),
    ("my_epf_rate_my_pr_low", "EPF Malaysian/PR below 60, wages up to the boundary (%)", "11", "13", None, None,
     "S5", True, None, None, _WM),
    ("my_epf_rate_my_pr_high", "EPF Malaysian/PR below 60, wages above the boundary (%)", "11", "12", None, None,
     "S5", True, None, None, _WM),
    ("my_epf_rate_60_plus", "EPF Malaysian aged 60 and over (%)", "0", "4", None, None, "S5", True,
     None, None, _WM),
    ("my_epf_rate_pr_hist_60_plus_low", "EPF PR / pre-1998 non-Malaysian 60+, lower band (%)", "5.5", "6.5",
     None, None, "S5", True, None, None, _WM),
    ("my_epf_rate_pr_hist_60_plus_high", "EPF PR / pre-1998 non-Malaysian 60+, upper band (%)", "5.5", "6",
     None, None, "S5", True, None, None, _WM),
    ("my_epf_rate_non_malaysian", "EPF non-Malaysian members after 1 Aug 1998 (%)", "2", "2", None, None, "S6",
     True, date(2025, 10, 1), None, _WM),
    ("my_epf_direct_calc_rule", "When EPF may be calculated directly instead of by table", None, None, None,
     PENDING, "S5", False, None, None, _WM),
    ("my_epf_age_transition_rule", "Which wage month the age-60 EPF class change applies from", None, None, None,
     PENDING, "S5", False, None, None, _WM),
    ("my_epf_age_threshold", "EPF age at which the 60-and-over member classes apply", None, None, "60", None,
     "S5", True, None, None, _WM),
    ("my_socso_wage_ceiling", "PERKESO Act 4 / EIS Act 800 contribution wage ceiling (RM)", None, None, "6000",
     None, "S7", True, date(2024, 10, 1), None, _CM),
    ("my_socso_employee_rate_ref", "Act 4 standard employee contribution reference (%)", "0.5", None, None,
     None, "S7", True, None, None, _CM),
    ("my_eis_rate_ref", "EIS contribution reference (%)", "0.2", "0.2", None, None, "S9", True, None, None, _CM),
    ("my_eis_min_age", "EIS coverage lower age", None, None, "18", None, "S9", True, None, None, _CM),
    ("my_eis_max_age", "EIS coverage upper age", None, None, "60", None, "S9", True, None, None, _CM),
    ("my_eis_age_rule", "How the EIS age bounds are measured", None, None, None, PENDING, "S9", False,
     None, None, _CM),
    ("my_fw_lindung_employee_rate", "Foreign-worker LINDUNG 24 JAM phase 1 employee component (%)", "0.75",
     None, None, None, "S8", True, date(2026, 6, 1), None, _CM),
    ("my_fw_lindung_phase_rule", "LINDUNG 24 JAM phase boundaries and shares", None, None, None, PENDING, "S8",
     False, None, None, _CM),
    ("my_hrd_rate_compulsory", "HRD levy, compulsory category (%)", None, "1", None, None, "S14", True,
     None, None, _WM),
    ("my_hrd_rate_optional", "HRD levy, optional registered category (%)", None, "0.5", None, None, "S14", True,
     None, None, _WM),
    ("my_hrd_compulsory_min_employees", "HRD compulsory category: Malaysian employees at least", None, None,
     "10", None, "S14", True, None, None, _EE),
    ("my_hrd_optional_min_employees", "HRD optional category: Malaysian employees at least", None, None, "5",
     None, "S14", True, None, None, _EE),
    ("my_hrd_base_rule", "HRD levy base inclusions / exclusions", None, None, None, PENDING, "S14", False,
     None, None, _WM),
    ("my_hrd_non_malaysian_rule", "Whether non-Malaysian employees' wages are in the HRD levy base", None, None,
     None, PENDING, "S14", False, None, None, _WM),
    ("my_cp22_days_after_start", "CP22 within days after employment starts", None, None, "30", None, "S2", True,
     None, None, _EE),
    ("my_cp22a_days_before_cessation", "CP22A at least days before cessation", None, None, "30", None, "S2",
     True, None, None, _EE),
    ("my_cp22a_days_after_death", "CP22A within days after learning of a death", None, None, "30", None, "S2",
     True, None, None, _EE),
    ("my_cp21_days_before_departure", "CP21 at least days before departure", None, None, "30", None, "S2", True,
     None, None, _EE),
    ("my_clearance_hold_max_days", "Tax-clearance hold, at most days", None, None, "90", None, "S2", True,
     None, None, _EE),
    ("my_ea_due", "EA/EC to employees", None, None, None, "END_FEBRUARY", "S2", True, None, None, _CY),
    ("my_form_e_due", "Form E + CP8D to HASiL", None, None, None, "END_MARCH", "S2", True, None, None, _CY),
    ("my_epf_due_rule", "EPF contribution payment due-date rule", None, None, None, PENDING, "S5", False,
     None, None, _CM),
    ("my_socso_due_rule", "PERKESO / EIS payment due-date rule", None, None, None, PENDING, "S7", False,
     None, None, _CM),
    ("my_hrd_due_rule", "HRD levy payment due-date rule", None, None, None, PENDING, "S14", False,
     None, None, _CM),
    ("my_transfer_split_rule", "Pay-period split when a worker changes labour territory", None, None, None,
     PENDING, "S11", False, None, None, _EE),
    ("my_record_retention_years", "Payroll / filing record retention (years)", None, None, None, None, "S2",
     False, None, None, _CY),
    ("my_reconciliation_tolerance", "Statutory reconciliation tolerance (RM)", None, None, None, None, "S2",
     False, None, None, _CM),
    ("my_parallel_materiality_amount", "Parallel-cycle materiality per employee per concept (RM)", None, None,
     None, None, "S2", False, None, None, _WM),
)

# Territorial labour rows: base key -> (label, flat, text, spec_value, date_basis).
# The specification states 45 hours, RM4,000, 98 and 7 days for all three
# territories (§9: Peninsular/Labuan and the updated Sabah/Sarawak frameworks).
_TERRITORIAL = {
    "my_weekly_hours_max": ("Statutory weekly working hours", "45", None, True, _WM),
    "my_ot_exclusion_wage": ("Non-manual employees above this monthly wage (RM) excluded from overtime",
                             "4000", None, True, _WM),
    "my_ot_multiplier_workday": ("Overtime multiplier, normal working day", None, None, False, _WM),
    "my_ot_multiplier_rest_day": ("Overtime multiplier, rest day", None, None, False, _WM),
    "my_ot_multiplier_public_holiday": ("Overtime multiplier, public holiday", None, None, False, _WM),
    "my_ot_rate_divisor_rule": ("Ordinary / hourly rate divisor rule", None, PENDING, False, _WM),
    "my_maternity_days": ("Maternity leave (days)", "98", None, True, _EE),
    "my_paternity_days": ("Paternity leave (days)", "7", None, True, _EE),
    "my_sick_leave_tiers": ("Sick leave days by service tier", None, PENDING, False, _CY),
    "my_hospitalisation_days": ("Hospitalisation leave (days)", None, None, False, _CY),
    "my_annual_leave_tiers": ("Annual leave days by service tier", None, PENDING, False, _CY),
    "my_leave_pay_rule": ("Leave remuneration rule", None, PENDING, False, _WM),
}


def territory_key(base: str, territory: str) -> str:
    """The component_key of a territorial row (keys are unique per pack)."""
    return f"{base}__{TERRITORY_SUFFIX[territory]}"


def _territorial_rows() -> tuple:
    rows = []
    for territory in TERRITORIES:
        for base, (label, flat, text, spec_value, basis) in _TERRITORIAL.items():
            rows.append((territory_key(base, territory), f"{label} — {territory}", None, None, flat, text,
                         TERRITORY_SOURCE[territory], spec_value, None, None, basis, territory))
    return tuple(rows)


# Full scalar content: national rows carry territory None.
MALAYSIA_SCALAR_CONTENT = tuple(row + (None,) for row in _NATIONAL) + _territorial_rows()

# Every key the pack holds, with its kind (national + suffixed territorial).
ALL_PARAMETER_KINDS = {
    **MALAYSIA_PARAMETER_KEYS,
    **{territory_key(base, t): kind for base, kind in MALAYSIA_TERRITORY_KEYS.items() for t in TERRITORIES},
}

# Rows that are deliberately EMPTY (no value at all): "not configured" is
# explicit, never filled with an assumed value.
MALAYSIA_EMPTY_BY_DESIGN = frozenset(
    row[0] for row in MALAYSIA_SCALAR_CONTENT if row[2] is None and row[3] is None and row[4] is None
    and row[5] is None)

# ── Earning classification — TaxSlab rule_type="MY_EARNING_CLASS" ────────
OBLIGATIONS = ("PCB_NORMAL", "PCB_ADDITIONAL", "EPF", "SOCSO", "EIS", "HRD", "MIN_WAGE_BASIC", "OT_RATE_BASE")
COMPONENTS = ("BASIC_SALARY", "HOURLY_PAY", "FIXED_ALLOWANCE", "VARIABLE_ALLOWANCE", "OVERTIME", "BONUS",
              "COMMISSION", "BENEFIT_IN_KIND", "PERQUISITE", "LEAVE_PAY", "ARREARS", "TERMINATION_PAY")
_OBLIGATION_SOURCE = {"PCB_NORMAL": "S1", "PCB_ADDITIONAL": "S1", "EPF": "S5", "SOCSO": "S7", "EIS": "S9",
                      "HRD": "S14", "MIN_WAGE_BASIC": "S10", "OT_RATE_BASE": "S11"}
_COMPONENT_LABEL = {
    "BASIC_SALARY": "Basic salary", "HOURLY_PAY": "Hourly pay", "FIXED_ALLOWANCE": "Fixed allowance",
    "VARIABLE_ALLOWANCE": "Variable allowance", "OVERTIME": "Overtime", "BONUS": "Bonus",
    "COMMISSION": "Commission", "BENEFIT_IN_KIND": "Benefit in kind", "PERQUISITE": "Perquisite",
    "LEAVE_PAY": "Leave pay", "ARREARS": "Arrears", "TERMINATION_PAY": "Termination / final pay",
}
_BASE_PAY = ("BASIC_SALARY", "HOURLY_PAY")
# Only treatments the specification states; everything else is REVIEW.
_STATED = {
    # §8 HRD base: monthly wages/basic salary plus fixed allowances; exclude
    # specified variable allowances and overtime.
    ("HRD", "FIXED_ALLOWANCE"): ("INCLUDED", "HRD base includes fixed allowances (spec §8)"),
    ("HRD", "VARIABLE_ALLOWANCE"): ("EXCLUDED", "HRD base excludes specified variable allowances (spec §8)"),
    ("HRD", "OVERTIME"): ("EXCLUDED", "HRD base excludes overtime (spec §8)"),
    # §9 minimum wage is tested on the basic wage; overtime and bonuses never
    # make up a deficient basic wage.
    ("MIN_WAGE_BASIC", "OVERTIME"): ("EXCLUDED", "minimum wage is tested on the basic wage (spec §9)"),
    ("MIN_WAGE_BASIC", "BONUS"): ("EXCLUDED", "bonuses cannot mask a deficient basic wage (spec §9)"),
    ("MIN_WAGE_BASIC", "COMMISSION"): ("EXCLUDED", "minimum wage is tested on the basic wage (spec §9)"),
    ("MIN_WAGE_BASIC", "VARIABLE_ALLOWANCE"): ("EXCLUDED", "allowances cannot mask a deficient basic wage (spec §9)"),
    # §5 bonus is additional remuneration, never ordinary salary by convenience.
    ("PCB_NORMAL", "BONUS"): ("EXCLUDED", "bonus is additional remuneration (spec §5)"),
    ("PCB_ADDITIONAL", "BONUS"): ("INCLUDED", "bonus is additional remuneration (spec §5)"),
    ("PCB_ADDITIONAL", "BASIC_SALARY"): ("EXCLUDED", "basic salary is normal remuneration (spec §5)"),
    ("PCB_ADDITIONAL", "HOURLY_PAY"): ("EXCLUDED", "hourly pay is normal remuneration (spec §5)"),
}


def _classify(obligation: str, component: str) -> tuple:
    if (obligation, component) in _STATED:
        return _STATED[(obligation, component)]
    if component in _BASE_PAY:
        return "INCLUDED", "base pay under the contract of service"
    return "REVIEW", "treatment not stated by the specification — blocks until signed"


MALAYSIA_EARNING_CLASSES = tuple(
    (obligation, treatment, component,
     f"{obligation}: {_COMPONENT_LABEL[component]} — {why}"[:130], _OBLIGATION_SOURCE[obligation])
    for obligation in OBLIGATIONS
    for component in COMPONENTS
    for treatment, why in (_classify(obligation, component),)
)

# ── Category labels for UI grouping (Phase 8) ─────────────────────────────
MALAYSIA_CATEGORIES = {
    "policy": "Scope, Policy & Rounding",
    "wages": "Minimum Wage",
    "pcb": "PCB / MTD",
    "epf": "EPF",
    "perkeso": "PERKESO / EIS / Foreign Workers",
    "hrd": "HRD Levy",
    "events": "Employer Events, Filing & Settlement",
    "labour": "Labour Law by Territory",
    "operations": "Operations & Evidence",
    "earning_classes": "Earning Classification (8 obligations)",
}


def _in_force(eff_from, eff_to, as_of: date) -> bool:
    if eff_from is not None and as_of < eff_from:
        return False
    if eff_to is not None and as_of > eff_to:
        return False
    return True


def content_rows_in_force(as_of: date) -> dict:
    """Scalar content rows in force on `as_of`, keyed by component_key."""
    return {row[0]: row for row in MALAYSIA_SCALAR_CONTENT if _in_force(row[8], row[9], as_of)}


def date_basis(key: str) -> str:
    """The date basis (MY-006) that decides whether `key` applies."""
    return {row[0]: row[10] for row in MALAYSIA_SCALAR_CONTENT}[key]
