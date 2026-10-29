"""
modules/payroll/engine/countries/japan_content.py
--------------------------------------------------
Japan 2026 statutory content catalog (Draft) — the ONE list of every rate,
threshold, calendar and classification the Japan engine
(engine/countries/japan.py, Phase 3) will read from `rate_map` / `slabs`.
Pure data, no ORM import, shared by:

  * japan_service.seed_japan_pack (via scripts/seed_japan_canonical_packs.py)
    — writes these rows into the JP-PAYROLL-2026 canonical JurisdictionPack
    (Draft);
  * tests/test_japan_content.py — the contract test that pins the values
    below to ZP-JP-ENG-001;
  * the Super Admin Japan compliance tabs (key lists only — the frontend
    never carries a statutory value of its own).

Conventions (the engine must match them):
  * Scalar parameters are ContributionRate rows keyed by component_key:
      kind "pct_pair"  — employee_rate_pct and employer_rate_pct, PERCENT
        numbers (0.5000 = 0.5% = 5/1000);
      kind "pct_total" — a TOTAL contribution rate as a PERCENT number in
        flat_amount (18.3000 = 18.3%). The employee/employer split is its own
        "text" row (*_split_rule) — a split is never derived silently;
      kind "amount" — flat_amount (JPY, hours, days, months, an age);
      kind "text"   — text_value (an enum label, MM / MM-MM, or PENDING_G1).
    A scalar row may carry its own LEGAL effective_from / effective_to: the
    child and childcare support contribution starts April 2026 and the
    FY2026 employment-insurance rates run April 2026 – March 2027, inside or
    across the calendar-year pack window (JP-003, JP-004). A month with no
    row in force BLOCKS — January–March 2026 employment insurance has no row
    because the FY2025 rates are not in the specification.
  * Earning classification rows are TaxSlab rule_type="JP_EARNING_CLASS"
    (the ZA / Hong Kong layout):
      filing_status    = pay component (SALARY, OVERTIME, BONUS, …)
      tax_regime       = obligation ("WHT" | "SI" | "EI" | "OT_BASE" | "MIN_WAGE")
      assessment_basis = "INCLUDED" | "EXCLUDED" | "BONUS_PATH" | "REVIEW"
    BONUS_PATH routes the amount to the bonus calculation (NTA bonus-rate
    table for WHT, standard bonus amount for SI) — never the monthly path.
    REVIEW means "not decided by the specification" and BLOCKS any
    calculation in which that component is non-zero (spec §1: unsupported
    cases are blocked, never approximated). Each obligation has its own
    base (JP-018) — there is no shared "taxable gross".
  * Authority tables the specification does NOT reproduce — NTA withholding
    tables and computer-calculation parameters, SMR/SBA grade tables, Kyokai
    Kenpo prefectural health rates and prefectural minimum wages — are
    declared below as EMPTY containers (JP_EMPTY_TABLES). They are filled only
    from archived authority artefacts at G1/G3/G4; until then every
    calculation that needs one BLOCKS. A value is never transcribed from a
    range or an example (spec §3: "rather than transcribing selected bracket
    examples into source code").

Rounding (JP-002): there is NO global rounding helper. Every statutory amount
names its own rounding row; the only rule the specification states is the
standard bonus amount (truncate below 1,000 yen). Every other rounding row is
PENDING_G1 and the engine BLOCKS on it.

Scope (spec §1): resident ordinary employees of one domestic employer on a
MONTHLY JPY payroll. Daily tables, non-residents, directors with complex
treatment, equity, retirement income, seafarers and the other deferred cases
have NO rows on purpose — the engine BLOCKS them.

Status is Draft throughout; the registry row stays PLANNED. The production
safety rule (spec, page 1) is stricter than South Africa's: no rate, table,
premium, due date or reporting field may be activated because it appears in
the specification. EVERY row below is therefore pending_g1=True — signed
effective-dated content, archived primary evidence, executable fixtures and
an independent Japanese payroll/tax review come first (spec §14).
"""

from datetime import date

PACK_STATUS = "Draft"
SPEC = "ZP-JP-ENG-001 v1.0"

# National withholding income tax runs on the calendar year (spec §2): the
# 2026 NTA tables apply to salary/bonus PAID in 2026. Resident tax (June–May),
# SMR (September–August) and employment insurance (April–March) have their
# own calendars, carried by row-level effective dates and calendar rows.
JP_2026 = ("JP-PAYROLL-2026", date(2026, 1, 1), date(2026, 12, 31))
TAX_YEAR = "2026"
CURRENCY = "JPY"

# ── Evidence register (ZP-JP-ENG-001 §15, S1–S17) ─────────────────────────
SOURCE_REFERENCES = (
    ("S1", "National Tax Agency — 2026 Withholding Tax Tables: monthly/daily salary tables, bonus rate "
           "table and approved computer-calculation material"),
    ("S2", "National Tax Agency — 2026 Withholding Tax Guide: employer withholding workflow, declarations "
           "and e-Tax payment"),
    ("S3", "National Tax Agency — 2026 Year-End Adjustment Guide: rules, reform changes, forms and Q&A"),
    ("S4", "National Tax Agency — Withholding agent and payment deadline (10th of the following month)"),
    ("S5", "National Tax Agency — 2026 statutory salary reports: withholding slip and statutory reports"),
    ("S6", "Japan Pension Service — Employees' Pension Insurance contributions (basis, equal sharing, "
           "SMR/SBA)"),
    ("S7", "Japan Pension Service — Annual standard monthly remuneration determination"),
    ("S8", "Japan Pension Service — Bonus payment procedure (5-day report, SBA rounding and caps)"),
    ("S9", "Japan Pension Service — Premium payment (end of the following month)"),
    ("S10", "Japan Health Insurance Association — FY2026 Kyokai Kenpo prefectural health rates"),
    ("S11", "Japan Health Insurance Association — Child and childcare support contribution (0.23% from "
            "April 2026)"),
    ("S12", "Japan Health Insurance Association — FY2026 care insurance rate (1.62%)"),
    ("S13", "Ministry of Health, Labour and Welfare — FY2026 Employment Insurance rates"),
    ("S14", "Ministry of Health, Labour and Welfare — Working time and premium wage rules"),
    ("S15", "Ministry of Health, Labour and Welfare — FY2026 regional minimum wage answers"),
    ("S16", "Tokyo Metropolitan Government — Guide to Metropolitan Taxes (individual inhabitant tax "
            "special collection)"),
    ("S17", "Personal Information Protection Commission — My Number business guidelines"),
)
SOURCE_CODES = tuple(code for code, _ in SOURCE_REFERENCES)

# Public URLs of the evidence register (spec §15). Archived copies and their
# SHA-256 are attached at gate G1 — a URL alone is not archived evidence.
SOURCE_URLS = {
    "S1": "https://www.nta.go.jp/publication/pamph/gensen/zeigakuhyo2026/01.htm",
    "S2": "https://www.nta.go.jp/publication/pamph/gensen/shikata_r08/01.htm",
    "S3": "https://www.nta.go.jp/publication/pamph/gensen/nencho2026/01.htm",
    "S4": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/gensen/2502.htm",
    "S5": "https://www.nta.go.jp/publication/pamph/hotei/tebiki2026/index.htm",
    "S6": "https://www.nenkin.go.jp/international/english/japanese-system/employeespension/epi_contribution.html",
    "S7": "https://www.nenkin.go.jp/service/kounen/hokenryo/hoshu/20121017.html",
    "S8": "https://www.nenkin.go.jp/service/kounen/hokenryo/hoshu/20141203.html",
    "S9": "https://www.nenkin.go.jp/service/kounen/hokenryo/nofu/nofu.html",
    "S10": "https://www.kyoukaikenpo.or.jp/about/business/insurance_rate/rate_prefectures/r08/",
    "S11": "https://www.kyoukaikenpo.or.jp/about/business/insurance_rate/003/",
    "S12": "https://www.kyoukaikenpo.or.jp/about/business/insurance_rate/002/",
    "S13": "https://www.mhlw.go.jp/stf/newpage_71570.html",
    "S14": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/roudouseisaku/chushoukigyou/"
           "joken_kankyou_rule.html",
    "S15": "https://www.mhlw.go.jp/stf/newpage_75950.html",
    "S16": "https://www.tax.metro.tokyo.lg.jp/documents/d/tax/guidebook2024e",
    "S17": "https://www.ppc.go.jp/legal/policy/my_number_guideline_jigyosha/",
}

# ── TaxSlab rule_type discriminators (all ≤ 30 chars) ────────────────────
JP_EARNING_CLASS_RULE = "JP_EARNING_CLASS"

# ── Enumerations the engine validates against ─────────────────────────────
PAY_FREQUENCIES_SUPPORTED = ("MONTHLY",)
# Daily tables exist (S1) but daily workers are outside the first release —
# monthly rules are never reused for them (spec §3).
PAY_FREQUENCIES_BLOCKED = ("DAILY", "WEEKLY", "FORTNIGHTLY")
RESIDENCY_STATUSES = ("RESIDENT", "NON_RESIDENT")          # NON_RESIDENT → UNSUPPORTED (spec §3)
# Primary-employer declaration (扶養控除等申告書 filed / not filed) selects the
# withholding column (spec §3). Internal names only.
DECLARATION_CLASSES = ("PRIMARY", "SECONDARY")
OBLIGATIONS = ("WHT", "SI", "EI", "OT_BASE", "MIN_WAGE")
TREATMENTS = ("INCLUDED", "EXCLUDED", "BONUS_PATH", "REVIEW")
# Health-insurance schemes the employer registration may name (JP-009). Only
# KYOKAI_KENPO has a rate source in the evidence register; a health insurance
# society's rates arrive per insurer with their own evidence.
HEALTH_INSURER_TYPES = ("KYOKAI_KENPO", "HEALTH_INSURANCE_SOCIETY")
# Employment-insurance industry classes (spec §6). The class is required
# before calculation; an unknown class BLOCKS.
EI_CLASSES = ("GENERAL", "AGRICULTURE_SAKE", "CONSTRUCTION")
# Withholding method decided 2026-10-29 (ZP-JP-ENG-001 §3; Venu): the NTA
# computer-calculation method for the PRIMARY monthly column, the official
# tables for every other path. Still subject to G1 sign-off.
WITHHOLDING_METHODS = ("COMPUTER_PRIMARY_TABLES_OTHERS", "TABLES_ONLY", "PENDING_G1")
SPLIT_RULES = ("EQUAL", "PENDING_G1")
ROUNDING_RULES = ("PENDING_G1", "DOWN_1000")
# Explicit policy choices the specification requires but does not make: until
# G1 signs one, the engine BLOCKS any case that depends on it.
PENDING = "PENDING_G1"

# ── Scalar engine parameter keys ──────────────────────────────────────────
# key -> kind. The engine's JP_PARAMETER_KEYS is THIS dict (imported).
JP_PARAMETER_KEYS = {
    # Scope and policy (spec §1, §3, JP-001, JP-006)
    "jp_supported_pay_frequencies": "text",
    "jp_withholding_method": "text",
    "jp_correction_policy": "text",
    # Rounding — one row per statutory amount, no global helper (JP-002)
    "jp_wht_rounding": "text",
    "jp_si_employee_share_rounding": "text",
    "jp_ei_employee_share_rounding": "text",
    "jp_sba_rounding": "text",
    "jp_sba_rounding_unit": "amount",
    # Employees' Pension Insurance (spec §5, S6)
    "jp_epi_total": "pct_total",
    "jp_epi_split_rule": "text",
    "jp_epi_sba_monthly_cap": "amount",
    # Health insurance — insurer-specific; Kyokai Kenpo validation bounds only
    # (JP-009: a generic Japan health rate is prohibited)
    "jp_kyokai_health_total_min": "pct_total",
    "jp_kyokai_health_total_max": "pct_total",
    "jp_health_split_rule": "text",
    "jp_health_sba_annual_cap": "amount",
    # Care insurance (spec §5, S12)
    "jp_kyokai_care_total": "pct_total",
    "jp_care_split_rule": "text",
    "jp_care_min_age": "amount",
    "jp_care_max_age": "amount",
    # Child and childcare support contribution (spec §5, S11)
    "jp_kyokai_child_support_total": "pct_total",
    "jp_child_support_split_rule": "text",
    # Standard monthly remuneration lifecycle (spec §5, S7)
    "jp_smr_determination_months": "text",
    "jp_smr_report_month": "text",
    "jp_smr_application_months": "text",
    "jp_smr_adhoc_revision_from_month": "amount",
    # Employment insurance FY2026 (spec §6, S13)
    "jp_ei_general": "pct_pair",
    "jp_ei_agriculture_sake_total": "pct_total",
    "jp_ei_agriculture_sake": "pct_pair",
    "jp_ei_construction_total": "pct_total",
    "jp_ei_construction": "pct_pair",
    # Working time and premium pay minimums (spec §6, S14)
    "jp_statutory_hours_per_day": "amount",
    "jp_statutory_hours_per_week": "amount",
    "jp_overtime_premium_pct": "amount",
    "jp_overtime_60h_threshold_hours": "amount",
    "jp_overtime_over_60h_premium_pct": "amount",
    "jp_statutory_holiday_premium_pct": "amount",
    "jp_night_premium_pct": "amount",
    "jp_night_window": "text",
    # Resident tax special collection (spec §4, S16)
    "jp_resident_tax_collection_months": "text",
    # Obligations and due dates (spec §2, §5, §8)
    "jp_wht_remittance_due_day": "amount",
    "jp_wht_due_non_business_day_rule": "text",
    "jp_si_remittance_due": "text",
    "jp_bonus_report_days": "amount",
    "jp_statutory_reports_due": "text",
}

# ── ContributionRate scalar content ───────────────────────────────────────
# (component_key, label, employee_pct, employer_pct, flat_amount, text_value,
#  source, pending_g1, effective_from, effective_to)
# effective_from/to None → the row is dated by the pack window.
_FY2026_FROM, _FY2026_TO = date(2026, 4, 1), date(2027, 3, 31)

JP_SCALAR_CONTENT = (
    ("jp_supported_pay_frequencies", "Pay frequencies certified for calculation (spec §1)",
     None, None, None, "MONTHLY", "S1", True, None, None),
    ("jp_withholding_method", "National withholding method (computer method for the primary column)",
     None, None, None, "COMPUTER_PRIMARY_TABLES_OTHERS", "S1", True, None, None),
    # JP-006: retroactive pay / correction treatment needs a documented policy.
    ("jp_correction_policy", "Japanese retro-pay and correction policy (JP-006)",
     None, None, None, PENDING, "S2", True, None, None),

    # JP-002: each statutory amount has its own truncation/rounding stage.
    ("jp_wht_rounding", "Withholding tax rounding (per the certified NTA method)",
     None, None, None, PENDING, "S1", True, None, None),
    ("jp_si_employee_share_rounding", "Social-insurance employee share rounding",
     None, None, None, PENDING, "S6", True, None, None),
    ("jp_ei_employee_share_rounding", "Employment-insurance employee share rounding",
     None, None, None, PENDING, "S13", True, None, None),
    ("jp_sba_rounding", "Standard bonus amount rounding (truncate below the unit)",
     None, None, None, "DOWN_1000", "S8", True, None, None),
    ("jp_sba_rounding_unit", "Standard bonus amount rounding unit (JPY)",
     None, None, "1000", None, "S8", True, None, None),

    ("jp_epi_total", "Employees' Pension Insurance total rate (% of SMR / SBA)",
     None, None, "18.3000", None, "S6", True, None, None),
    ("jp_epi_split_rule", "Employees' Pension Insurance employee / employer split",
     None, None, None, "EQUAL", "S6", True, None, None),
    ("jp_epi_sba_monthly_cap", "Pension standard bonus amount cap per month (JPY)",
     None, None, "1500000", None, "S8", True, None, None),

    # Bounds only: the rate itself comes from the insurer + prefecture table.
    ("jp_kyokai_health_total_min", "Kyokai Kenpo FY2026 prefectural health rate — lowest (validation bound)",
     None, None, "9.2100", None, "S10", True, None, None),
    ("jp_kyokai_health_total_max", "Kyokai Kenpo FY2026 prefectural health rate — highest (validation bound)",
     None, None, "10.5500", None, "S10", True, None, None),
    ("jp_health_split_rule", "Health insurance employee / employer split (generally equal)",
     None, None, None, "EQUAL", "S10", True, None, None),
    ("jp_health_sba_annual_cap", "Health standard bonus amount cumulative annual cap (JPY)",
     None, None, "5730000", None, "S8", True, None, None),

    ("jp_kyokai_care_total", "Kyokai Kenpo FY2026 care insurance total rate (ages 40–64)",
     None, None, "1.6200", None, "S12", True, None, None),
    # The specification states no split for care insurance.
    ("jp_care_split_rule", "Care insurance employee / employer split",
     None, None, None, PENDING, "S12", True, None, None),
    ("jp_care_min_age", "Care insurance covered population — from age", None, None, "40", None, "S12", True,
     None, None),
    ("jp_care_max_age", "Care insurance covered population — through age", None, None, "64", None, "S12", True,
     None, None),

    ("jp_kyokai_child_support_total", "Kyokai Kenpo child and childcare support contribution total rate",
     None, None, "0.2300", None, "S11", True, _FY2026_FROM, None),
    ("jp_child_support_split_rule", "Child and childcare support contribution split (labour-management)",
     None, None, None, "EQUAL", "S11", True, _FY2026_FROM, None),

    ("jp_smr_determination_months", "SMR annual determination remuneration months (MM-MM)",
     None, None, None, "04-06", "S7", True, None, None),
    ("jp_smr_report_month", "SMR annual determination report month (MM)",
     None, None, None, "07", "S7", True, None, None),
    ("jp_smr_application_months", "New SMR applies (MM-MM, crossing the year end)",
     None, None, None, "09-08", "S7", True, None, None),
    ("jp_smr_adhoc_revision_from_month", "SMR ad hoc revision applies from this month after the pay change",
     None, None, "4", None, "S7", True, None, None),

    ("jp_ei_general", "Employment insurance FY2026 — general business (employee / employer)",
     "0.5000", "0.8500", None, None, "S13", True, _FY2026_FROM, _FY2026_TO),
    ("jp_ei_agriculture_sake_total", "Employment insurance FY2026 — agriculture/forestry/fishery/sake total",
     None, None, "1.5500", None, "S13", True, _FY2026_FROM, _FY2026_TO),
    # The specification states only the total for this class.
    ("jp_ei_agriculture_sake", "Employment insurance FY2026 — agriculture/sake split (not stated by the spec)",
     None, None, None, None, "S13", True, _FY2026_FROM, _FY2026_TO),
    ("jp_ei_construction_total", "Employment insurance FY2026 — construction total",
     None, None, "1.6500", None, "S13", True, _FY2026_FROM, _FY2026_TO),
    ("jp_ei_construction", "Employment insurance FY2026 — construction split (not stated by the spec)",
     None, None, None, None, "S13", True, _FY2026_FROM, _FY2026_TO),

    ("jp_statutory_hours_per_day", "Statutory working hours per day (baseline)", None, None, "8", None, "S14",
     True, None, None),
    ("jp_statutory_hours_per_week", "Statutory working hours per week (baseline)", None, None, "40", None, "S14",
     True, None, None),
    ("jp_overtime_premium_pct", "Statutory overtime premium — minimum (%)", None, None, "25", None, "S14", True,
     None, None),
    ("jp_overtime_60h_threshold_hours", "Monthly overtime hours above which the higher premium applies",
     None, None, "60", None, "S14", True, None, None),
    ("jp_overtime_over_60h_premium_pct", "Overtime premium above the monthly threshold — minimum (%)",
     None, None, "50", None, "S14", True, None, None),
    ("jp_statutory_holiday_premium_pct", "Statutory day-off work premium — minimum (%)",
     None, None, "35", None, "S14", True, None, None),
    ("jp_night_premium_pct", "Night work premium — minimum (%)", None, None, "25", None, "S14", True,
     None, None),
    ("jp_night_window", "Night work window (HH:MM-HH:MM)", None, None, None, "22:00-05:00", "S14", True,
     None, None),

    # JP-007: amounts come from the municipality notice, never a formula.
    ("jp_resident_tax_collection_months", "Resident tax special collection months (MM-MM, June–May)",
     None, None, None, "06-05", "S16", True, None, None),

    ("jp_wht_remittance_due_day", "Withholding remittance due by day of the month after payment",
     None, None, "10", None, "S4", True, None, None),
    # Spec §2: "holiday adjustment" — the direction is not stated.
    ("jp_wht_due_non_business_day_rule", "Withholding due date on a non-business day",
     None, None, None, PENDING, "S4", True, None, None),
    ("jp_si_remittance_due", "Social-insurance remittance due (employee + employer portions)",
     None, None, None, "LAST_DAY_FOLLOWING_MONTH", "S9", True, None, None),
    ("jp_bonus_report_days", "JPS bonus payment report due within (days of payment)",
     None, None, "5", None, "S8", True, None, None),
    ("jp_statutory_reports_due", "Withholding slips / salary payment reports due (MM-DD, following year)",
     None, None, None, "01-31", "S5", True, None, None),
)

# Rows that are deliberately empty: present so "not configured" is explicit,
# never filled with an assumed value.
JP_EMPTY_BY_DESIGN = frozenset({"jp_ei_agriculture_sake", "jp_ei_construction"})

# ── Authority tables not reproduced by the specification ──────────────────
# Each is filled ONLY from an archived authority artefact (source code in the
# key) and signed at the named gate. Empty → every calculation needing it
# BLOCKS. Nothing here may be back-filled from a range, an average or an
# example in the specification.
JP_EMPTY_TABLES = {
    # NTA 2026 monthly withholding table (S1): columns by declaration class
    # and dependant count; the SECONDARY column always needs the table.
    "wht_monthly_table": {"source": "S1", "gate": "G1", "rows": ()},
    # NTA computer-calculation method parameters for the PRIMARY column (S1).
    "wht_computer_method": {"source": "S1", "gate": "G1", "rows": ()},
    # NTA 2026 bonus rate table (S1): rate by prior-month pay band.
    "wht_bonus_rate_table": {"source": "S1", "gate": "G1", "rows": ()},
    # NTA 2026 year-end adjustment pack (S3) — separate from monthly content.
    "year_end_adjustment": {"source": "S3", "gate": "G1", "rows": ()},
    # Health and pension SMR grade tables (S6/S7).
    "smr_grades_health": {"source": "S7", "gate": "G3", "rows": ()},
    "smr_grades_pension": {"source": "S7", "gate": "G3", "rows": ()},
    # Kyokai Kenpo FY2026 health rate per prefecture (S10).
    "kyokai_health_rates": {"source": "S10", "gate": "G3", "rows": ()},
    # Prefectural minimum wage per effective interval (S15) — an announced
    # future rate is never selected before its date (JP-004).
    "minimum_wage": {"source": "S15", "gate": "G4", "rows": ()},
    # Workers' compensation employer rates by industry (spec §6: separately
    # sourced/certified — no evidence entry yet).
    "workers_comp_rates": {"source": None, "gate": "G4", "rows": ()},
}

# ── Prefectures (JIS X 0401 codes) ────────────────────────────────────────
# The key for insurer branch rates and minimum wage. Codes and names only —
# no statutory value.
JP_PREFECTURES = (
    ("01", "Hokkaido"), ("02", "Aomori"), ("03", "Iwate"), ("04", "Miyagi"), ("05", "Akita"),
    ("06", "Yamagata"), ("07", "Fukushima"), ("08", "Ibaraki"), ("09", "Tochigi"), ("10", "Gunma"),
    ("11", "Saitama"), ("12", "Chiba"), ("13", "Tokyo"), ("14", "Kanagawa"), ("15", "Niigata"),
    ("16", "Toyama"), ("17", "Ishikawa"), ("18", "Fukui"), ("19", "Yamanashi"), ("20", "Nagano"),
    ("21", "Gifu"), ("22", "Shizuoka"), ("23", "Aichi"), ("24", "Mie"), ("25", "Shiga"),
    ("26", "Kyoto"), ("27", "Osaka"), ("28", "Hyogo"), ("29", "Nara"), ("30", "Wakayama"),
    ("31", "Tottori"), ("32", "Shimane"), ("33", "Okayama"), ("34", "Hiroshima"), ("35", "Yamaguchi"),
    ("36", "Tokushima"), ("37", "Kagawa"), ("38", "Ehime"), ("39", "Kochi"), ("40", "Fukuoka"),
    ("41", "Saga"), ("42", "Nagasaki"), ("43", "Kumamoto"), ("44", "Oita"), ("45", "Miyazaki"),
    ("46", "Kagoshima"), ("47", "Okinawa"),
)

# ── Earning classification — TaxSlab rule_type="JP_EARNING_CLASS" ─────────
# (obligation, treatment, component, label, source)
# Components map to PayrollContext (Phase 3): SALARY=basic,
# OVERTIME=overtime, ALLOWANCE / COMMUTING_ALLOWANCE / BONUS = named pay
# components, OTHER_EARNINGS = gross minus every named component.
# Only the treatments the specification states are INCLUDED / BONUS_PATH;
# everything else is REVIEW until G1/G3/G4 sign the per-base interpretation
# (spec §1: "Each earning code has separate income-tax, social-insurance,
# employment-insurance and overtime-base treatment").
JP_COMPONENTS = ("SALARY", "OVERTIME", "ALLOWANCE", "COMMUTING_ALLOWANCE", "BONUS", "OTHER_EARNINGS")

JP_EARNING_CLASSES = (
    # National withholding (spec §2, §3)
    ("WHT", "INCLUDED", "SALARY", "Salary — withholding on the monthly table / computer method", "S1"),
    ("WHT", "REVIEW", "OVERTIME", "Overtime — withholding treatment needs signed evidence", "S1"),
    ("WHT", "REVIEW", "ALLOWANCE", "Allowance — withholding treatment needs signed evidence", "S1"),
    ("WHT", "REVIEW", "COMMUTING_ALLOWANCE", "Commuting allowance — needs the signed non-taxable limit", "S1"),
    ("WHT", "BONUS_PATH", "BONUS", "Bonus — NTA bonus-rate table path, never the monthly table", "S1"),
    ("WHT", "REVIEW", "OTHER_EARNINGS", "Any other earning — needs a classification", "S1"),

    # Social insurance — SMR / SBA, never the income-tax base (spec §5)
    ("SI", "INCLUDED", "SALARY", "Salary — remuneration for SMR determination", "S7"),
    ("SI", "REVIEW", "OVERTIME", "Overtime — SMR treatment needs signed evidence", "S7"),
    ("SI", "REVIEW", "ALLOWANCE", "Allowance — SMR treatment needs signed evidence", "S7"),
    ("SI", "REVIEW", "COMMUTING_ALLOWANCE", "Commuting allowance — SMR treatment needs signed evidence", "S7"),
    ("SI", "BONUS_PATH", "BONUS", "Bonus — standard bonus amount path (SBA)", "S8"),
    ("SI", "REVIEW", "OTHER_EARNINGS", "Any other earning — needs a classification", "S7"),

    # Employment insurance wage base (spec §6)
    ("EI", "INCLUDED", "SALARY", "Salary — employment-insurance wages", "S13"),
    ("EI", "REVIEW", "OVERTIME", "Overtime — employment-insurance treatment needs signed evidence", "S13"),
    ("EI", "REVIEW", "ALLOWANCE", "Allowance — employment-insurance treatment needs signed evidence", "S13"),
    ("EI", "REVIEW", "COMMUTING_ALLOWANCE", "Commuting allowance — employment-insurance treatment needs "
                                            "signed evidence", "S13"),
    ("EI", "REVIEW", "BONUS", "Bonus — employment-insurance treatment needs signed evidence", "S13"),
    ("EI", "REVIEW", "OTHER_EARNINGS", "Any other earning — needs a classification", "S13"),

    # Overtime premium base (spec §6, JP-012)
    ("OT_BASE", "REVIEW", "SALARY", "Salary — overtime base needs the signed hourly-rate rule", "S14"),
    ("OT_BASE", "REVIEW", "OVERTIME", "Overtime — never part of its own base without signed evidence", "S14"),
    ("OT_BASE", "REVIEW", "ALLOWANCE", "Allowance — overtime base treatment needs signed evidence", "S14"),
    ("OT_BASE", "REVIEW", "COMMUTING_ALLOWANCE", "Commuting allowance — overtime base treatment needs signed "
                                                 "evidence", "S14"),
    ("OT_BASE", "REVIEW", "BONUS", "Bonus — overtime base treatment needs signed evidence", "S14"),
    ("OT_BASE", "REVIEW", "OTHER_EARNINGS", "Any other earning — needs a classification", "S14"),

    # Minimum-wage comparison — "compare only wages included by the governing
    # rule" (spec §6): nothing is decided yet.
    ("MIN_WAGE", "REVIEW", "SALARY", "Salary — minimum-wage comparison needs the signed rule", "S15"),
    ("MIN_WAGE", "REVIEW", "OVERTIME", "Overtime — minimum-wage comparison needs the signed rule", "S15"),
    ("MIN_WAGE", "REVIEW", "ALLOWANCE", "Allowance — minimum-wage comparison needs the signed rule", "S15"),
    ("MIN_WAGE", "REVIEW", "COMMUTING_ALLOWANCE", "Commuting allowance — minimum-wage comparison needs the "
                                                  "signed rule", "S15"),
    ("MIN_WAGE", "REVIEW", "BONUS", "Bonus — minimum-wage comparison needs the signed rule", "S15"),
    ("MIN_WAGE", "REVIEW", "OTHER_EARNINGS", "Any other earning — needs a classification", "S15"),
)

# ── Category labels for UI grouping ──────────────────────────────────────
JP_CATEGORIES = {
    "withholding": "National Withholding Income Tax",
    "social_insurance": "Social Insurance (Pension / Health / Care / Child Support)",
    "smr": "Standard Monthly Remuneration & Bonus Amounts",
    "employment_insurance": "Employment Insurance",
    "labour": "Working Time, Premiums & Minimum Wage",
    "resident_tax": "Resident Tax Special Collection",
    "filing": "Remittance & Statutory Reports",
    "policy": "Scope, Rounding & Policy",
}


def _in_force(eff_from, eff_to, as_of: date) -> bool:
    if eff_from is not None and as_of < eff_from:
        return False
    if eff_to is not None and as_of > eff_to:
        return False
    return True


def content_rows_in_force(as_of: date):
    """Scalar content rows legally in force on `as_of`, keyed by component_key."""
    return {row[0]: row for row in JP_SCALAR_CONTENT if _in_force(row[8], row[9], as_of)}


def earning_classes_in_force(as_of: date):
    """Earning classification rows (undated in this Draft)."""
    return JP_EARNING_CLASSES
