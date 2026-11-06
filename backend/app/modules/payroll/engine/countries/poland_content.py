"""
modules/payroll/engine/countries/poland_content.py
---------------------------------------------------
Poland 2026 statutory content catalog (Draft) — the ONE list of every rate,
threshold, cap, band, date rule and classification the Poland engine
(engine/countries/poland.py + engine/jurisdictions/poland/*, Phase 3) reads
from `rate_map` / `slabs`. Pure data, no ORM import, shared by:

  * poland_service.seed_poland_pack (via scripts/seed_poland_canonical_packs.py)
    — writes these rows into the PL-PAYROLL-2026 canonical JurisdictionPack
    (Draft);
  * tests/test_poland_content.py — the contract test that pins the values
    below to ZP-PL-ENG-001;
  * the Super Admin Poland compliance tabs (key lists only — the frontend
    never carries a statutory value of its own).

Production safety rule (spec, page 1): no statutory rate, threshold, cap,
tax-cost amount, filing version, ZUS code, PPK rule or labour-law date lives
only in application code or UI. Every value here reaches calculation only
through a signed, effective-dated pack. A value the specification does NOT
give is an EMPTY row (POLAND_EMPTY_BY_DESIGN) or a "PENDING_G1" text value —
never a guess. Unsupported or undecided cases BLOCK in the engine.

Conventions (the engine must match them):
  * Scalar parameters are ContributionRate rows keyed by component_key:
      kind "employee_pct"/"employer_pct" — a PERCENT number (9.76 = 9.76%)
        in employee_rate_pct / employer_rate_pct;
      kind "pct_pair" — both employee_rate_pct and employer_rate_pct;
      kind "amount" — flat_amount (PLN, days, hours, years or a day-of-month);
      kind "text"   — text_value (an enum label, list or "PENDING_G1").
    Every scalar row also names its DATE BASIS (PL-003): which date decides
    whether it applies — CALENDAR_YEAR, CONTRIBUTION_YEAR (ZUS accident year,
    1 April - 31 March), PAYROLL_MONTH, PAYMENT_DATE or EMPLOYMENT_EVENT.
    Never assume every Polish rule changes on 1 January.
  * PIT scale rows are TaxSlab rule_type="PL_PIT_BAND" on ANNUAL taxable
    income, exactly as published (spec §2 / §4, S3/S4):
      min_amount  = band threshold (0, 120,000)
      max_amount  = band ceiling, NULL for the top band
      rate_pct    = marginal rate (12, 32)
      flat_amount = the PUBLISHED base for the band (0, 10,800).
    IMPORTANT: the published 10,800 already NETS the 3,600 annual
    tax-reducing amount (120,000 x 12% = 14,400; 14,400 - 3,600 = 10,800).
    The first band's 0 does not. The engine (Phase 3) therefore must compute
    tax BEFORE the reducing amount as   rate x income   (band 1) and
    flat_amount + pl_pit_tax_reducing_annual + rate x (income - min) (band 2),
    then apply the PIT-2 monthly reduction separately — never subtract the
    reducing amount twice. tests/test_poland_content.py pins this identity.
  * Earning classification rows are TaxSlab rule_type="PL_EARNING_CLASS":
      filing_status    = pay component (SALARY, OVERTIME_50, ...)
      tax_regime       = obligation (PIT, EMERYTALNE, ... MIN_WAGE)
      assessment_basis = "INCLUDED" | "EXCLUDED" | "REVIEW"
    Each obligation has its own base (spec "Critical refinements"): there is
    no universal "taxable gross". REVIEW = the specification does not decide
    the treatment; a non-zero REVIEW component BLOCKS the calculation.
    PPK and FEP rows mirror EMERYTALNE (PL-014: PPK uses the pension base
    without the 30x cap; FEP "uses pension-base logic").
  * Rounding is per obligation (PL-004) and is NOT given by the
    specification: every pl_rounding_* row is "PENDING_G1".

Scope (spec §1, decision D2): employees under umowa o pracę on MONTHLY pay.
Civil-law contracts, multiple insurance titles, posted workers / A1,
management contracts, equity and the 50% creator costs have NO rows on
purpose — the engine BLOCKS them.

Status is Draft throughout and the registry row stays PLANNED. Rows marked
pending_g1=True need the Polish specialist's signature at gate G1 (spec §15)
before any pack carrying them is activated; rows stated by the specification
still go through the same four-eyes activation.
"""

from datetime import date
from decimal import Decimal

PACK_STATUS = "Draft"
SPEC = "ZP-PL-ENG-001 v1.0"

# Polish PIT and the 30x ZUS cap are calendar-year (spec §2).
PL_2026 = ("PL-PAYROLL-2026", date(2026, 1, 1), date(2026, 12, 31))
TAX_YEAR = "2026"
CURRENCY = "PLN"

# ── Evidence register (ZP-PL-ENG-001 §15, S1–S12, reviewed 22 Sep 2026) ────
SOURCE_REFERENCES = (
    ("S1", "Ministry of Family, Labour and Social Policy — Minimum wage: 2026 minimum monthly wage "
           "PLN 4,806 and national treatment"),
    ("S2", "Ministry of Family, Labour and Social Policy — Minimum hourly rate: 2026 covered civil-law "
           "hourly floor PLN 31.40"),
    ("S3", "Ministry of Finance — Income from employment: 2026 PIT scale, employee deductible costs and "
           "work-income tax treatment"),
    ("S4", "Ministry of Finance — PIT-2 statements guide: PLN 30,000 tax-free amount, PLN 3,600 "
           "tax-reducing amount, monthly 300/150/100 allocation"),
    ("S5", "ZUS — Contributions / 2026 contribution indicators: employee/employer social contribution "
           "rates and accident-rate framework"),
    ("S6", "ZUS — 2026 social contribution amounts: annual pension/disability base limit PLN 282,600 "
           "and accident contribution-year rules"),
    ("S7", "ZUS — Health insurance: contribution rate 9% and obligation-specific base rules"),
    ("S8", "ZUS — Filing/payment deadlines: monthly DRA/named reports and contributions by the "
           "5th/15th/20th by payer type"),
    ("S9", "Official PPK portal — contribution rules: employee 2% / employer 1.5%, reduced employee "
           "contribution and additional-rate limits"),
    ("S10", "State Labour Inspectorate / Ministry — pay, overtime, leave, sickness: monthly pay timing, "
            "overtime 50%/100%, annual leave 20/26 days, employer sick-pay 33/14 days"),
    ("S11", "Ministry of Finance — payer annual forms: PIT-11 to tax office by end January and employee "
            "by end February; PIT-4R/PIT-8AR by end January"),
    ("S12", "ZUS — FEP / FGSP: FEP 1.5% for qualifying work and FGSP 0.10% framework"),
)
SOURCE_CODES = tuple(code for code, _ in SOURCE_REFERENCES)

# Public URLs of the evidence register (spec §15). Archived copies and their
# SHA-256 are attached at gate G1 — a URL alone is not archived evidence.
SOURCE_URLS = {
    "S1": "https://www.gov.pl/web/rodzina/minimum-wage",
    "S2": "https://www.gov.pl/web/rodzina/minimalna-stawka-godzinowa",
    "S3": "https://www.podatki.gov.pl/podatki-osobiste/pit/informacje-podstawowe/co-jest-opodatkowane/dochody-z-pracy/",
    "S4": "https://www.podatki.gov.pl/poradniki-i-informatory/pit-2-pit-2a-pit-3-zasady-skladania-oswiadczen-o-stosowaniu-pomniejszenia-zaliczki-o-kwote-zmniejszajaca-podatek-112-124-lub-136",
    "S5": "https://lang.zus.pl/finances/contributions",
    "S6": "https://www.zus.pl/en/-/nowe-wysoko%C5%9Bci-sk%C5%82adek-na-ubezpieczenia-spo%C5%82eczne-w-2026-r.",
    "S7": "https://www.zus.pl/firmy/rozliczenia-z-zus/skladki-na-ubezpieczenia/zdrowotne",
    "S8": "https://www.zus.pl/en/baza-wiedzy/skladki-wskazniki-odsetki/skladki/terminy-rozliczania-i-oplacania-skladek-na-ubezpieczenia-spoleczne",
    "S9": "https://www.mojeppk.pl/faq.html",
    "S10": "https://www.pip.gov.pl/dla-pracodawcow/porady-prawne/wynagrodzenie-za-prace",
    "S11": "https://podatki.gov.pl/poradniki-i-informatory/platnik",
    "S12": "https://www.zus.pl/pracujacy/fundusze-pozaubezpieczeniowe/fep",
}

# ── TaxSlab rule_type discriminators (all <= 30 chars) ────────────────────
PL_PIT_BAND_RULE = "PL_PIT_BAND"
PL_EARNING_CLASS_RULE = "PL_EARNING_CLASS"
# Official / independently prepared worked examples (AC-PL-02, gate G1): added
# only through the governed console with a reviewed source; never seeded here.
PL_AUTHORITY_EXAMPLE_RULE = "PL_AUTHORITY_EXAMPLE"

# ── Enumerations (vocabulary only — no statutory values) ─────────────────
PAY_FREQUENCIES_SUPPORTED = ("MONTHLY",)
CONTRACT_TYPES_SUPPORTED = ("UMOWA_O_PRACE",)
# Architecture accommodates these (spec §1); the engine BLOCKS them until
# coverage determination and their own rules pass the country gates.
CONTRACT_TYPES_BLOCKED = ("UMOWA_ZLECENIE", "UMOWA_O_DZIELO", "MANAGEMENT_CONTRACT", "BOARD_REMUNERATION")
# PL-006: one determination + reason code per obligation.
COVERAGE_OBLIGATIONS = ("PIT", "EMERYTALNE", "RENTOWE", "CHOROBOWE", "WYPADKOWE", "ZDROWOTNE",
                        "FP_FS", "FGSP", "FEP", "PPK")
# Earning-class obligations = coverage obligations + the minimum-wage test (PL-015).
OBLIGATIONS = COVERAGE_OBLIGATIONS + ("MIN_WAGE",)
TREATMENTS = ("INCLUDED", "EXCLUDED", "REVIEW")
DATE_BASES = ("CALENDAR_YEAR", "CONTRIBUTION_YEAR", "PAYROLL_MONTH", "PAYMENT_DATE", "EMPLOYMENT_EVENT")
# Rounding rule vocabulary (unit + mode). Which rule each obligation uses is
# NOT given by the specification (PL-004) — every pl_rounding_* row ships
# PENDING_G1 and the engine blocks until G1 signs one of these.
ROUNDING_MODES = ("GROSZ_HALF_UP", "GROSZ_DOWN", "FULL_PLN_HALF_UP", "FULL_PLN_DOWN", "PENDING_G1")
# Signed-value vocabularies for the policy rows the specification leaves open.
# A vocabulary is not a decision: the shipped rows stay PENDING_G1.
HEALTH_LIMITATION_RULES = ("NONE",)
FP_FS_MIN_BASE_RULES = ("NONE", "BASE_AT_LEAST_MIN_WAGE")
FUND_CAP_RULES = ("CAPPED_WITH_PENSION_BASE", "UNCAPPED")
PPK_EMPLOYER_PIT_TREATMENTS = ("TAXABLE_EMPLOYEE_INCOME", "NOT_TAXABLE")
PIT2_ALLOCATIONS = {"FULL": "pl_pit2_reduction_full", "HALF": "pl_pit2_reduction_half",
                    "THIRD": "pl_pit2_reduction_third"}
# PL-016: the event that created an overtime premium (spec §8). Which events
# earn the standard vs the high premium is NOT given by the specification:
# pl_overtime_premium_map ("DAILY=50,WEEKLY=100,...") ships PENDING_G1.
OVERTIME_EVENT_KINDS = ("DAILY", "WEEKLY", "NIGHT", "SUNDAY_HOLIDAY", "COMP_TIME_FAILED")
LEAVE_PART_TIME_ROUNDING = ("ROUND_UP_FULL_DAY", "EXACT")
# The night-work supplement formula is not given by the specification; no
# signed vocabulary exists yet, so a non-zero supplement always blocks.
NIGHT_SUPPLEMENT_RULES = ()
# Spec §9 IncapacityEpisode statutory category. Which categories are paid at
# the full rate is a signed list (pl_sick_full_rate_cases, PENDING_G1).
INCAPACITY_CATEGORIES = ("ILLNESS", "ROUTE_ACCIDENT", "PREGNANCY", "DONOR", "WORK_ACCIDENT", "OTHER")
# How "aged over 50 under statutory age rule" is measured is not given.
SICK_AGE_RULES = ("AGE_AT_EPISODE_START", "FROM_YEAR_AFTER_REACHING_AGE")
ZUS_DEADLINE_CLASSES = ("DAY_5", "DAY_15", "DAY_20")
ACCIDENT_RATE_SOURCES = ("ZUS_NOTICE", "SELF_DETERMINED", "SMALL_PAYER_DEFAULT")
# PL-005: every declaration is effective-dated with evidence (Phase 2 table).
DECLARATION_TYPES = ("PIT2", "COSTS_COMMUTER", "COSTS_MULTIPLE", "PIT0_UNDER26", "PIT0_RETURN",
                     "PIT0_FAMILY4", "PIT0_SENIOR", "PIT0_WAIVER", "HIGHER_RATE_REQUEST",
                     "PPK_OPT_OUT", "PPK_REDUCED_RATE", "PPK_ADDITIONAL", "PRIOR_EMPLOYER_CAP")
PIT0_RELIEFS = ("PIT0_UNDER26", "PIT0_RETURN", "PIT0_FAMILY4", "PIT0_SENIOR")
# Accumulator ledger keys (payroll_pl_accumulator_entries.accumulator, spec §11).
ACCUMULATORS = ("PIT_TAXABLE_INCOME", "PIT_ADVANCE", "PIT_COSTS_USED", "PIT0_EXEMPT_UNDER26", "PIT0_EXEMPT_RETURN",
                "PIT0_EXEMPT_FAMILY4", "PIT0_EXEMPT_SENIOR", "ZUS_CAP_PENSION_BASE", "ZUS_CAP_DISABILITY_BASE",
                "SICK_DAYS_EMPLOYER", "PPK_EMPLOYEE", "PPK_EMPLOYER")
# Spec §7 PPK state machine.
PPK_STATES = ("NOT_ELIGIBLE", "ELIGIBLE_NOT_ENROLLED", "ENROLLED", "OPTED_OUT", "SUSPENDED_BY_LAW", "ENDED")
PPK_SETTLEMENT_STATES = ("CALCULATED", "WITHHELD", "EMPLOYER_FUNDED", "TRANSFERRED", "RECONCILED",
                         "CORRECTED")
# Spec §10 compliance states.
COMPLIANCE_STATES = ("DRAFT", "APPROVED", "SUBMITTED", "ACCEPTED", "REJECTED", "CORRECTED", "PAID",
                     "RECONCILED")

# ── Statutory form / schema catalogue (PL-019) ─────────────────────────────
# Versioned form catalogue the Phase 8 filing adapter reads. DELIBERATELY
# EMPTY: no official ZUS (KEDU / e-Płatnik) or e-Deklaracje schema is
# archived yet, and a schema version or field code is never guessed. While a
# form's `versions` is empty only the canonical (schema-neutral) payload is
# generated for preview; approval and submission BLOCK (FILING_SCHEMA_MISMATCH).
# Shape once archived: versions = {"<version>": {"effective_from": "YYYY-MM-DD",
# "effective_to": None, "evidence": "<archived schema reference>"}}.
PL_FORM_SCHEMA_CATALOG = {
    "DRA": {"authority": "ZUS", "versions": {}, "evidence": "S8"},
    "RCA": {"authority": "ZUS", "versions": {}, "evidence": "S8"},
    "RSA": {"authority": "ZUS", "versions": {}, "evidence": "S8"},
    "RPA": {"authority": "ZUS", "versions": {}, "evidence": "S8"},
    "ZUA": {"authority": "ZUS", "versions": {}, "evidence": "S5"},
    "ZZA": {"authority": "ZUS", "versions": {}, "evidence": "S5"},
    "ZWUA": {"authority": "ZUS", "versions": {}, "evidence": "S5"},
    "PIT11": {"authority": "KAS", "versions": {}, "evidence": "S11"},
    "PIT4R": {"authority": "KAS", "versions": {}, "evidence": "S11"},
    "PIT8AR": {"authority": "KAS", "versions": {}, "evidence": "S11"},
}

# ── Payroll preflight / four-eyes exception codes (spec §12) ───────────────
PL_RUN_EXCEPTION_CODES = (
    "MISSING_IDENTIFIER", "MISSING_DECLARATION", "NEGATIVE_NET", "MIN_WAGE_BREACH", "ANNUAL_CAP_CROSSED",
    "PPK_ANOMALY", "ZUS_TITLE_MISSING", "FILING_SCHEMA_MISMATCH", "CONTENT_PACK_OUT_OF_DATE",
    "PAYLOAD_CHANGED_AFTER_APPROVAL",
)

# ── ContributionRate scalar content ───────────────────────────────────────
# (component_key, label, employee_pct, employer_pct, flat_amount, text_value,
#  source, pending_g1, effective_from, effective_to, date_basis)
# effective_from/to None -> the row is dated by the pack window.
POLAND_PARAMETER_KEYS = {
    # scope and policy
    "pl_supported_pay_frequencies": "text",
    "pl_supported_contract_types": "text",
    "pl_pit_social_deduction_rule": "text",
    "pl_health_base_rule": "text",
    "pl_health_limitation_rule": "text",
    "pl_rounding_pit": "text",
    "pl_rounding_zus": "text",
    "pl_rounding_health": "text",
    "pl_rounding_ppk": "text",
    # wages
    "pl_min_wage_monthly": "amount",
    "pl_min_hourly_civil": "amount",
    "pl_pay_deadline_day": "amount",
    # PIT
    "pl_pit_tax_free_amount": "amount",
    "pl_pit_tax_reducing_annual": "amount",
    "pl_pit2_reduction_full": "amount",
    "pl_pit2_reduction_half": "amount",
    "pl_pit2_reduction_third": "amount",
    "pl_costs_standard_monthly": "amount",
    "pl_costs_standard_annual_cap": "amount",
    "pl_costs_standard_multi_annual_cap": "amount",
    "pl_costs_commuter_monthly": "amount",
    "pl_costs_commuter_annual_cap": "amount",
    "pl_costs_commuter_multi_annual_cap": "amount",
    "pl_pit0_annual_limit": "amount",
    # ZUS social and health
    "pl_zus_emerytalne": "pct_pair",
    "pl_zus_rentowe": "pct_pair",
    "pl_zus_chorobowe": "employee_pct",
    "pl_zus_wypadkowe_min": "employer_pct",
    "pl_zus_wypadkowe_max": "employer_pct",
    "pl_zus_wypadkowe_small_payer": "employer_pct",
    "pl_zus_contribution_year_start": "text",
    "pl_zus_annual_cap": "amount",
    "pl_health": "employee_pct",
    # employer funds
    "pl_fp_fs": "employer_pct",
    "pl_fp_fs_min_base_rule": "text",
    "pl_fund_cap_rule": "text",
    "pl_fgsp": "employer_pct",
    "pl_fep": "employer_pct",
    "pl_fund_exemption_rules": "text",
    # PPK
    "pl_ppk_employee_basic": "employee_pct",
    "pl_ppk_employee_reduced_min": "employee_pct",
    "pl_ppk_reduced_income_pct_min_wage": "employee_pct",
    "pl_ppk_employee_additional_max": "employee_pct",
    "pl_ppk_employer_basic": "employer_pct",
    "pl_ppk_employer_additional_max": "employer_pct",
    "pl_ppk_transfer_day": "amount",
    "pl_ppk_reenrolment_cycle_years": "amount",
    "pl_ppk_employer_pit_treatment": "text",
    # working time, overtime, leave
    "pl_working_hours_daily": "amount",
    "pl_working_hours_weekly_avg": "amount",
    "pl_overtime_premium_standard": "employee_pct",
    "pl_overtime_premium_high": "employee_pct",
    "pl_overtime_premium_map": "text",
    "pl_night_supplement_basis": "text",
    "pl_leave_part_time_rounding": "text",
    "pl_leave_days_base": "amount",
    "pl_leave_days_senior": "amount",
    "pl_leave_service_years_senior": "amount",
    "pl_leave_pay_reference_rule": "text",
    # sickness
    "pl_sick_employer_days": "amount",
    "pl_sick_employer_days_older": "amount",
    "pl_sick_older_age_threshold": "amount",
    "pl_sick_rate_standard": "employee_pct",
    "pl_sick_rate_full": "employee_pct",
    "pl_sick_full_rate_cases": "text",
    "pl_sick_age_rule": "text",
    "pl_benefit_reference_months": "amount",
    # filing and settlement
    "pl_zus_due_day_classes": "text",
    "pl_pit_remittance_due_rule": "text",
    "pl_pit11_authority_due": "text",
    "pl_pit11_employee_due": "text",
    "pl_pit4r_due": "text",
    "pl_pit8ar_due": "text",
    # operations (Phase 9 evidence)
    "pl_record_retention_years": "amount",
    "pl_reconciliation_tolerance": "amount",
    "pl_parallel_materiality_amount": "amount",
}

_CY = "CALENDAR_YEAR"
_CTY = "CONTRIBUTION_YEAR"
_PM = "PAYROLL_MONTH"
_PD = "PAYMENT_DATE"
_EE = "EMPLOYMENT_EVENT"
_PENDING = "PENDING_G1"

POLAND_SCALAR_CONTENT = (
    # ── scope and policy ──────────────────────────────────────────────────
    ("pl_supported_pay_frequencies", "Pay frequencies certified for calculation (spec §1, §8)",
     None, None, None, "MONTHLY", "S10", False, None, None, _PM),
    # D2 / PL-002: the contract label is an input; only this title is in scope.
    ("pl_supported_contract_types", "Contract types in the first certified release (spec §1)",
     None, None, None, "UMOWA_O_PRACE", "S3", False, None, None, _EE),
    # Spec §4 trace: "only employee social contributions deductible".
    ("pl_pit_social_deduction_rule", "Social contributions deductible for PIT (spec §4)",
     None, None, None, "EMPLOYEE_SOCIAL_ONLY", "S3", False, None, None, _PD),
    # Spec §2 / §5: health base derived after applicable social deductions.
    ("pl_health_base_rule", "Health contribution base (spec §2, §5)",
     None, None, None, "GROSS_LESS_EMPLOYEE_SOCIAL", "S7", False, None, None, _PD),
    # Not stated by the specification — whether any limit applies to health.
    ("pl_health_limitation_rule", "Health contribution limitation rule (not in spec)",
     None, None, None, _PENDING, "S7", True, None, None, _PD),
    # PL-004: rounding per obligation — values not given by the specification.
    ("pl_rounding_pit", "PIT advance rounding (PL-004)", None, None, None, _PENDING, "S3", True, None, None, _PD),
    ("pl_rounding_zus", "ZUS social contribution rounding (PL-004)", None, None, None, _PENDING, "S5", True,
     None, None, _PD),
    ("pl_rounding_health", "Health contribution rounding (PL-004)", None, None, None, _PENDING, "S7", True,
     None, None, _PD),
    ("pl_rounding_ppk", "PPK contribution rounding (PL-004)", None, None, None, _PENDING, "S9", True,
     None, None, _PD),

    # ── wages (spec §2, §8) ───────────────────────────────────────────────
    ("pl_min_wage_monthly", "Minimum monthly wage, full-time (PLN)", None, None, "4806", None, "S1", False,
     date(2026, 1, 1), None, _PM),
    ("pl_min_hourly_civil", "Minimum hourly rate, covered civil-law services (PLN)", None, None, "31.40", None,
     "S2", False, date(2026, 1, 1), None, _PM),
    ("pl_pay_deadline_day", "Monthly pay due by this day of the following month", None, None, "10", None,
     "S10", False, None, None, _PM),

    # ── PIT (spec §2, §4) ─────────────────────────────────────────────────
    ("pl_pit_tax_free_amount", "PIT tax-free amount (annual, PLN)", None, None, "30000", None, "S4", False,
     None, None, _CY),
    ("pl_pit_tax_reducing_annual", "PIT tax-reducing amount (annual, PLN)", None, None, "3600", None, "S4",
     False, None, None, _CY),
    ("pl_pit2_reduction_full", "PIT-2 monthly reduction, one payer (PLN)", None, None, "300", None, "S4",
     False, None, None, _PD),
    ("pl_pit2_reduction_half", "PIT-2 monthly reduction, half allocation (PLN)", None, None, "150", None,
     "S4", False, None, None, _PD),
    ("pl_pit2_reduction_third", "PIT-2 monthly reduction, third allocation (PLN)", None, None, "100", None,
     "S4", False, None, None, _PD),
    ("pl_costs_standard_monthly", "Standard employee deductible costs (monthly, PLN)", None, None, "250",
     None, "S3", False, None, None, _PD),
    # Spec: "annual caps depend on one/multiple employment relationships" — no figures.
    ("pl_costs_standard_annual_cap", "Standard costs annual cap, one employment (PLN)", None, None, None,
     None, "S3", True, None, None, _CY),
    ("pl_costs_standard_multi_annual_cap", "Standard costs annual cap, multiple employments (PLN)", None,
     None, None, None, "S3", True, None, None, _CY),
    ("pl_costs_commuter_monthly", "Commuter employee deductible costs (monthly, PLN)", None, None, "300",
     None, "S3", False, None, None, _PD),
    ("pl_costs_commuter_annual_cap", "Commuter costs annual cap, one employment (PLN)", None, None, None,
     None, "S3", True, None, None, _CY),
    ("pl_costs_commuter_multi_annual_cap", "Commuter costs annual cap, multiple employments (PLN)", None,
     None, None, None, "S3", True, None, None, _CY),
    # Spec §4: PIT-0 reliefs have "statutory shared/exemption limits" — no figure.
    ("pl_pit0_annual_limit", "PIT-0 reliefs shared annual exempt-income limit (PLN)", None, None, None,
     None, "S3", True, None, None, _CY),

    # ── ZUS social and health (spec §2, §5) ───────────────────────────────
    ("pl_zus_emerytalne", "Old-age pension contribution (employee / employer)", "9.7600", "9.7600", None,
     None, "S5", False, None, None, _PD),
    ("pl_zus_rentowe", "Disability contribution (employee / employer)", "1.5000", "6.5000", None, None, "S5",
     False, None, None, _PD),
    ("pl_zus_chorobowe", "Sickness contribution (employee, mandatory employment cover)", "2.4500", None,
     None, None, "S5", False, None, None, _PD),
    # Spec: "rate generally 0.67%-3.33%, with 1.67% rule for specified small /
    # non-REGON payers" — "generally" and "specified" need G1 confirmation.
    ("pl_zus_wypadkowe_min", "Accident contribution — lowest employer rate", None, "0.6700", None, None,
     "S5", True, None, None, _CTY),
    ("pl_zus_wypadkowe_max", "Accident contribution — highest employer rate", None, "3.3300", None, None,
     "S5", True, None, None, _CTY),
    ("pl_zus_wypadkowe_small_payer", "Accident contribution — small / non-REGON payer rate", None, "1.6700",
     None, None, "S5", True, None, None, _CTY),
    ("pl_zus_contribution_year_start", "Accident-rate contribution year starts (1 Apr - 31 Mar)", None, None,
     None, "04-01", "S6", False, None, None, _CTY),
    ("pl_zus_annual_cap", "Pension/disability annual base limit (30x, PLN)", None, None, "282600", None,
     "S6", False, None, None, _CY),
    ("pl_health", "Health contribution (employee-funded)", "9.0000", None, None, None, "S7", False, None,
     None, _PD),

    # ── employer funds (spec §6) ──────────────────────────────────────────
    ("pl_fp_fs", "Labour Fund / Solidarity Fund (FP/FS), employer", None, "2.4500", None, None, "S5", False,
     None, None, _PD),
    # Spec: "minimum-wage and exemption tests require an employer-side
    # applicability engine" — the test itself is not given.
    ("pl_fp_fs_min_base_rule", "FP/FS minimum-base applicability test", None, None, None, _PENDING, "S5",
     True, None, None, _PM),
    # Spec §5 says the 30x cap "does not automatically cap ... employer funds
    # that are defined without that limit" and §6 states it only for FEP — so
    # whether FP/FS and FGSP use the capped base is not decided by the spec.
    ("pl_fund_cap_rule", "FP/FS and FGSP base: with or without the 30x cap (not in spec)", None, None, None,
     _PENDING, "S5", True, None, None, _PD),
    ("pl_fgsp", "Guaranteed Employee Benefits Fund (FGSP), employer", None, "0.1000", None, None, "S12",
     False, None, None, _PD),
    ("pl_fep", "Bridging Pension Fund (FEP), employer, qualifying work only", None, "1.5000", None, None,
     "S12", False, None, None, _PD),
    # Spec §6: named exemption rules with exact effective periods — none given.
    ("pl_fund_exemption_rules", "Age / return-to-work employer-fund exemptions", None, None, None, _PENDING,
     "S12", True, None, None, _EE),

    # ── PPK (spec §2, §7) ─────────────────────────────────────────────────
    ("pl_ppk_employee_basic", "PPK employee basic contribution", "2.0000", None, None, None, "S9", False,
     None, None, _PD),
    ("pl_ppk_employee_reduced_min", "PPK reduced employee basic contribution, minimum", "0.5000", None,
     None, None, "S9", False, None, None, _PD),
    ("pl_ppk_reduced_income_pct_min_wage", "PPK reduced rate: monthly income limit, % of minimum wage",
     "120.0000", None, None, None, "S9", False, None, None, _PM),
    ("pl_ppk_employee_additional_max", "PPK employee additional contribution, maximum", "2.0000", None,
     None, None, "S9", False, None, None, _PD),
    ("pl_ppk_employer_basic", "PPK employer basic contribution", None, "1.5000", None, None, "S9", False,
     None, None, _PD),
    ("pl_ppk_employer_additional_max", "PPK employer additional contribution, maximum", None, "2.5000",
     None, None, "S9", False, None, None, _PD),
    # Spec: "no later than 15th ... subject to legal detail and calendar adjustment".
    ("pl_ppk_transfer_day", "PPK transfer due by this day of the following month", None, None, "15", None,
     "S9", True, None, None, _PM),
    # Spec: "periodic auto-re-enrolment" — the period is not given.
    ("pl_ppk_reenrolment_cycle_years", "PPK auto re-enrolment cycle (years)", None, None, None, None, "S9",
     True, None, None, _EE),
    # Not stated by the specification: PIT treatment of the employer PPK contribution.
    ("pl_ppk_employer_pit_treatment", "PIT treatment of the employer PPK contribution (not in spec)", None,
     None, None, _PENDING, "S9", True, None, None, _PD),

    # ── working time, overtime and leave (spec §8) ────────────────────────
    ("pl_working_hours_daily", "Standard working time (hours per day)", None, None, "8", None, "S10", False,
     None, None, _PM),
    ("pl_working_hours_weekly_avg", "Standard working time (average hours per week)", None, None, "40", None,
     "S10", False, None, None, _PM),
    ("pl_overtime_premium_standard", "Overtime premium on normal pay, standard case", "50.0000", None, None,
     None, "S10", False, None, None, _PM),
    ("pl_overtime_premium_high", "Overtime premium on normal pay, statutory high case", "100.0000", None,
     None, None, "S10", False, None, None, _PM),
    # Spec §8: "50% or 100% premium depending on statutory circumstance" — the
    # event-to-premium mapping is not given (PL-016).
    ("pl_overtime_premium_map", "Overtime event kind -> premium (spec §8, not given)", None, None, None,
     _PENDING, "S10", True, None, None, _PM),
    # Spec: "tied to current minimum wage/hours" — the formula is not given.
    ("pl_night_supplement_basis", "Night-work supplement basis", None, None, None, _PENDING, "S10", True,
     None, None, _PM),
    ("pl_leave_days_base", "Annual leave days, service credit under the senior threshold", None, None, "20",
     None, "S10", False, None, None, _EE),
    ("pl_leave_days_senior", "Annual leave days, service credit at/over the senior threshold", None, None,
     "26", None, "S10", False, None, None, _EE),
    ("pl_leave_service_years_senior", "Service credit (years) for the higher leave tier", None, None, "10",
     None, "S10", False, None, None, _EE),
    # Spec §8: "proportional rules for part-time" — the rounding is not given.
    ("pl_leave_part_time_rounding", "Part-time annual leave rounding (not in spec)", None, None, None, _PENDING,
     "S10", True, None, None, _EE),
    ("pl_leave_pay_reference_rule", "Leave remuneration reference-period rule", None, None, None, _PENDING,
     "S10", True, None, None, _PM),

    # ── sickness (spec §9) ────────────────────────────────────────────────
    ("pl_sick_employer_days", "Employer-paid sick days per calendar year", None, None, "33", None, "S10",
     False, None, None, _CY),
    ("pl_sick_employer_days_older", "Employer-paid sick days per year, older employee", None, None, "14",
     None, "S10", False, None, None, _CY),
    # Spec: "aged over 50 under statutory age rule" — the age test needs G1.
    ("pl_sick_older_age_threshold", "Age above which the shorter employer period applies", None, None, "50",
     None, "S10", True, None, None, _CY),
    ("pl_sick_rate_standard", "Employer sick pay, standard rate (% of base)", "80.0000", None, None, None,
     "S10", False, None, None, _EE),
    ("pl_sick_rate_full", "Employer sick pay, full rate for statutory cases (% of base)", "100.0000", None,
     None, None, "S10", False, None, None, _EE),
    # Spec: "such as certain accidents on route, pregnancy and donor-related
    # cases" — an example list, not the closed statutory list.
    ("pl_sick_full_rate_cases", "Cases paid at the full sick-pay rate", None, None, None,
     "ROUTE_ACCIDENT,PREGNANCY,DONOR", "S10", True, None, None, _EE),
    ("pl_sick_age_rule", "How the shorter employer sick-pay period's age test is applied (not in spec)", None, None,
     None, _PENDING, "S10", True, None, None, _CY),
    ("pl_benefit_reference_months", "Benefit base reference period (months)", None, None, None, None, "S10",
     True, None, None, _EE),

    # ── filing and settlement (spec §10) ──────────────────────────────────
    ("pl_zus_due_day_classes", "ZUS DRA filing/payment day by payer class", None, None, None, "5,15,20",
     "S8", False, None, None, _PM),
    # Spec: "production calendar must use authority-verified due-date logic".
    ("pl_pit_remittance_due_rule", "PIT advance remittance due-date rule", None, None, None, _PENDING, "S11",
     True, None, None, _PM),
    ("pl_pit11_authority_due", "PIT-11 to the tax office", None, None, None, "END_JANUARY", "S11", False,
     None, None, _CY),
    ("pl_pit11_employee_due", "PIT-11 to the employee", None, None, None, "END_FEBRUARY", "S11", False,
     None, None, _CY),
    ("pl_pit4r_due", "PIT-4R annual payer declaration", None, None, None, "END_JANUARY", "S11", False, None,
     None, _CY),
    ("pl_pit8ar_due", "PIT-8AR annual payer declaration", None, None, None, "END_JANUARY", "S11", False,
     None, None, _CY),

    # ── operations (Phase 9 evidence; the specification gives no values) ──
    ("pl_record_retention_years", "Payroll / filing record retention (years)", None, None, None, None, "S11",
     True, None, None, _CY),
    ("pl_reconciliation_tolerance", "Statutory reconciliation tolerance (PLN)", None, None, None, None, "S8",
     True, None, None, _PM),
    ("pl_parallel_materiality_amount", "Parallel-cycle materiality per employee per concept (PLN)", None,
     None, None, None, "S3", True, None, None, _PM),
)

# Rows that are deliberately EMPTY: present so "not configured" is explicit,
# never filled with an assumed value. The engine BLOCKS when a calculation
# needs one of them.
POLAND_EMPTY_BY_DESIGN = frozenset({
    "pl_costs_standard_annual_cap", "pl_costs_standard_multi_annual_cap",
    "pl_costs_commuter_annual_cap", "pl_costs_commuter_multi_annual_cap",
    "pl_pit0_annual_limit", "pl_ppk_reenrolment_cycle_years", "pl_benefit_reference_months",
    "pl_record_retention_years", "pl_reconciliation_tolerance", "pl_parallel_materiality_amount",
})

# ── PIT scale — TaxSlab rule_type="PL_PIT_BAND" (spec §2 / §4, S3/S4) ─────
# (min_amount, max_amount, rate_pct, published_base, label, source)
# See the module docstring: the published 10,800 already nets the 3,600
# tax-reducing amount.
POLAND_PIT_BANDS = (
    ("0", "120000", "12.0000", "0", "Up to PLN 120,000: 12% (tax-reducing amount applied separately)", "S3"),
    ("120000", None, "32.0000", "10800",
     "Above PLN 120,000: PLN 10,800 + 32% of the excess (published base nets the PLN 3,600 reduction)", "S3"),
)

# ── Earning classification — TaxSlab rule_type="PL_EARNING_CLASS" ────────
# Components map to PayrollContext in Phase 3. Only treatments the
# specification states are INCLUDED / EXCLUDED; everything else is REVIEW
# (blocks when non-zero) until G1 signs the per-base treatment.
POLAND_COMPONENTS = ("SALARY", "HOURLY_PAY", "OVERTIME_50", "OVERTIME_100", "NIGHT_SUPPLEMENT",
                     "SENIORITY_ALLOWANCE", "BONUS", "ALLOWANCE", "BENEFIT_IN_KIND", "LEAVE_PAY",
                     "SICK_PAY_EMPLOYER", "SICKNESS_BENEFIT")
# Ordinary base pay under the employment contract — the remuneration every
# obligation's base starts from (spec §1, §2, §5, §8).
_BASE_PAY = ("SALARY", "HOURLY_PAY")
# PL-015: overtime, night supplement and seniority allowance never count
# toward the minimum-wage test.
_MIN_WAGE_EXCLUDED = ("OVERTIME_50", "OVERTIME_100", "NIGHT_SUPPLEMENT", "SENIORITY_ALLOWANCE")
_OBLIGATION_SOURCE = {
    "PIT": "S3", "EMERYTALNE": "S5", "RENTOWE": "S5", "CHOROBOWE": "S5", "WYPADKOWE": "S5",
    "ZDROWOTNE": "S7", "FP_FS": "S5", "FGSP": "S12", "FEP": "S12", "PPK": "S9", "MIN_WAGE": "S1",
}
_COMPONENT_LABEL = {
    "SALARY": "Monthly salary", "HOURLY_PAY": "Hourly pay", "OVERTIME_50": "Overtime (50% premium)",
    "OVERTIME_100": "Overtime (100% premium)", "NIGHT_SUPPLEMENT": "Night-work supplement",
    "SENIORITY_ALLOWANCE": "Seniority allowance", "BONUS": "Bonus", "ALLOWANCE": "Allowance",
    "BENEFIT_IN_KIND": "Non-cash benefit", "LEAVE_PAY": "Annual leave remuneration",
    "SICK_PAY_EMPLOYER": "Employer sick pay", "SICKNESS_BENEFIT": "ZUS sickness benefit",
}


def _classify(obligation: str, component: str) -> tuple:
    if component in _BASE_PAY:
        return "INCLUDED", "base pay under the employment contract"
    if obligation == "MIN_WAGE" and component in _MIN_WAGE_EXCLUDED:
        return "EXCLUDED", "excluded from the minimum-wage test (PL-015)"
    return "REVIEW", "treatment not stated by the specification — blocks until signed"


POLAND_EARNING_CLASSES = tuple(
    (obligation, treatment, component,
     f"{obligation}: {_COMPONENT_LABEL[component]} — {why}"[:150], _OBLIGATION_SOURCE[obligation])
    for obligation in OBLIGATIONS
    for component in POLAND_COMPONENTS
    for treatment, why in (_classify(obligation, component),)
)

# ── Category labels for UI grouping (Phase 7) ─────────────────────────────
POLAND_CATEGORIES = {
    "policy": "Scope, Policy & Rounding",
    "wages": "Minimum Wage & Pay Timing",
    "pit": "PIT Scale, PIT-2 & Deductible Costs",
    "zus": "ZUS Social & Health",
    "funds": "Employer Funds (FP/FS, FGSP, FEP)",
    "ppk": "PPK",
    "labour": "Working Time, Overtime & Leave",
    "sickness": "Sickness & Benefits",
    "filing": "Filing & Settlement",
    "operations": "Operations & Evidence",
    "earning_classes": "Earning Classification (11 obligations)",
}


def _in_force(eff_from, eff_to, as_of: date) -> bool:
    if eff_from is not None and as_of < eff_from:
        return False
    if eff_to is not None and as_of > eff_to:
        return False
    return True


def content_rows_in_force(as_of: date) -> dict:
    """Scalar content rows legally in force on `as_of`, keyed by component_key."""
    return {row[0]: row for row in POLAND_SCALAR_CONTENT if _in_force(row[8], row[9], as_of)}


def date_basis(key: str) -> str:
    """The date basis (PL-003) that decides whether `key` applies."""
    return {row[0]: row[10] for row in POLAND_SCALAR_CONTENT}[key]


def pit_bands() -> tuple:
    """PIT scale as Decimals: (min, max-or-None, rate_pct, published_base, label, source)."""
    return tuple((Decimal(lo), Decimal(hi) if hi is not None else None, Decimal(rate), Decimal(base), label, src)
                 for (lo, hi, rate, base, label, src) in POLAND_PIT_BANDS)


def earning_classes_in_force(as_of: date) -> tuple:
    """Earning classification rows (undated in this Draft)."""
    return POLAND_EARNING_CLASSES
