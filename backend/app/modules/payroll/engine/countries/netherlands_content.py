"""
modules/payroll/engine/countries/netherlands_content.py
--------------------------------------------------------
Netherlands 2026 statutory content catalog (Draft) — the ONE list of every
rate and parameter the Netherlands engine will read from `rate_map` /
`slabs`. Pure data, no ORM import, so it is safe to import from anywhere and
shared by:

  * scripts/seed_netherlands_canonical_packs.py — writes these rows into the
    NL-PAYROLL-2026 canonical JurisdictionPack (Draft);
  * tests/test_netherlands_content.py — the contract test that pins the rules
    below to ZP-NL-ENG-001 v1.0;
  * the Super Admin Netherlands component picker.

Source: ZP-NL-ENG-001 v1.0 (22 September 2026). Every value is traceable to
the specification's own §2 statutory baseline and cited against the S1–S20
evidence register below. Nothing here is invented: where the specification
does not state a figure the key/value is deliberately ABSENT and the engine
BLOCKS rather than falling back (see the "PENDING" notes).

Critical doctrine (spec §0 "Critical doctrine", NL-005): ordinary withholding
must reproduce the official 2026 wage-tax tables. The annual Box 1 brackets
collected below (`nl_box1_*`) are REFERENCE DATA for validation only — they
are never the ordinary payroll algorithm, so they are plain scalar content,
never a usable MARGINAL_RATE slab.

Conventions:
  * percent-type values are PERCENT numbers (6.10 = 6.10%).
  * amount-type values are euro stored in flat_amount.
  * string parameters (an enum label, an exact fraction such as "1/3") live
    in text_value, never flat_amount (Numeric(14,2) would store 1/3 as 0.33).
  * every row is `needs_g1=True`: the statutory review that must precede live
    payroll (gate G1, spec §19) has this one file to sign off, and nothing may
    be activated until each value has a named source.

Status is Draft throughout; the registry row stays PLANNED.
"""

from datetime import date
from decimal import Decimal

PACK_STATUS = "Draft"

# One calendar-year pack; rows inside it carry their own legal dates (the
# 1 Jul 2026 minimum-wage step is a ROW boundary, not a pack boundary). The
# NL-PAYROLL-2026-07 change-watch pack is a future statutory-review anchor.
NL_2026 = ("NL-PAYROLL-2026", date(2026, 1, 1), date(2026, 12, 31))
NL_2026_07 = ("NL-PAYROLL-2026-07", date(2026, 7, 1), date(2026, 12, 31))

# ── Evidence register (ZP-NL-ENG-001 §20, S1–S20) ─────────────────────────
SOURCE_REFERENCES = (
    ("S1", "Belastingdienst — Handboek Loonheffingen 2026 (primary operating manual for Dutch payroll taxes)"),
    ("S2", "Belastingdienst — Payroll tax tables 2026 (white, green, derivation and special-remuneration tables)"),
    ("S3", "Belastingdienst — 2026 wage-tax/national-insurance brackets (reference annual rates and composition)"),
    ("S4", "Belastingdienst — 2026 rates, amounts and percentages (AWf, Aof, Wko, Whk sector references, "
           "maximum contribution wage, Zvw rates)"),
    ("S5", "Belastingdienst — VCR calculation (progressive cumulative rules for employee-insurance contributions)"),
    ("S6", "Belastingdienst — AWf low/high premium (contract conditions and retrospective revision logic)"),
    ("S7", "Belastingdienst — WKR (2026 free-space percentages and 80% final levy)"),
    ("S8", "Belastingdienst — Expat scheme application / conditions (2026 salary thresholds, 30% facility and cap)"),
    ("S9", "Belastingdienst — Model opgaaf gegevens voor de loonheffingen (employee identity and payroll-tax-credit instruction)"),
    ("S10", "Belastingdienst — 2026 loonaangifte data specifications (authoritative field formats and allowed values)"),
    ("S11", "Belastingdienst — Payroll-tax return (return obligation, nil/zero returns and correction approach)"),
    ("S12", "Belastingdienst — Standard Business Reporting (SBR / Digipoort and PKIoverheid certificate requirement)"),
    ("S13", "ODB Belastingdienst — Salary software support (release artifacts, validation service and Digipoort support)"),
    ("S14", "Rijksoverheid — Minimum wage 2026 (1 January and 1 July 2026 statutory hourly rates)"),
    ("S15", "Rijksoverheid — Vacation allowance (minimum 8% vacation allowance baseline)"),
    ("S16", "Rijksoverheid — Sick-pay continuation (employer wage continuation during illness)"),
    ("S17", "Rijksoverheid — Transition payment (2026 cap and statutory calculation framework)"),
    ("S18", "Rijksoverheid — CAO applicability (when collective agreements apply to employers)"),
    ("S19", "Rijksoverheid — Payslip content (mandatory employee payslip information)"),
    ("S20", "Belastingdienst — Model jaaropgaaf (year-end employee statement obligations)"),
)
SOURCE_CODES = tuple(code for code, _ in SOURCE_REFERENCES)

# ── TaxSlab rule_type discriminators (all ≤ 30 chars) ─────────────────────
NL_MIN_WAGE_RULE = "NL_MIN_WAGE"
NL_PERIOD_MAX_RULE = "NL_PERIOD_MAX"
NL_WKR_BAND_RULE = "NL_WKR_BAND"
NL_CAR_ADDITION_RULE = "NL_CAR_ADDITION"

# ── Enumerations the engine validates against ─────────────────────────────
# Table colour / derivation / cohort (spec §3): current employment uses the
# WHITE tables; GREEN former-employment flows are separately certified.
TABLE_COLORS = ("WHITE", "GREEN")
PAYROLL_PERIODS = ("DAILY", "WEEKLY", "FOUR_WEEKLY", "MONTHLY", "QUARTERLY", "ANNUAL")
# AOW cohort (spec §3): selected from date of birth and the official statutory
# pension age.
AOW_COHORTS = ("BELOW_AOW", "REACHING_AOW", "AOW_AGE")
Zvw_PATHS = ("EMPLOYER_LEVY", "EMPLOYEE_CONTRIBUTION")
AWF_RATES = ("LOW", "HIGH")
AOF_RATES = ("LOW", "HIGH")
# Minimum-wage age cohorts (spec §2/§14): no universal monthly minimum — the
# Netherlands uses a statutory HOURLY minimum by age.
MIN_WAGE_AGE_COHORTS = ("AGE_21_PLUS", "AGE_20", "AGE_19", "AGE_18", "AGE_17", "AGE_16", "AGE_15")
# WKR band kinds.
WKR_BANDS = ("FREE_SPACE", "EXCESS_LEVY")
# Company-car first-registration / CO2 classes (spec §8, NL-024/NL-025).
CAR_ADDITION_CLASSES = ("STANDARD", "ZERO_EMISSION")

# ── Scalar engine parameter keys ──────────────────────────────────────────
# key -> kind. The engine's NL_PARAMETER_KEYS will be THIS dict (imported).
NL_PARAMETER_KEYS = {
    # Table selection + reference annual Box 1 brackets (spec §2/§3, S3).
    # Reference/validation data only — the payroll algorithm is table-driven.
    "nl_table_color": "text",
    "nl_box1_band1_rate": "employee_pct",
    "nl_box1_band1_ceiling": "amount",
    "nl_box1_band2_rate": "employee_pct",
    "nl_box1_band2_ceiling": "amount",
    "nl_box1_band3_rate": "employee_pct",
    # Anonymous-person rate (spec §3, 52% in 2026).
    "nl_anonymous_rate_pct": "employee_pct",
    # Tax credits (spec §2) — table-driven in payroll, never editable
    # employee amounts (NL-006).
    "nl_general_tax_credit_max": "amount",
    "nl_general_tax_credit_phase_start": "amount",
    "nl_general_tax_credit_phase_end": "amount",
    "nl_employment_tax_credit_max": "amount",
    "nl_employment_tax_credit_phase_end": "amount",
    # Statutory AOW (state pension) age — selects the wage-tax table cohort
    # (spec §3); a missing value BLOCKS the cohort selection.
    "nl_aow_age_years": "amount",
    # Employee-insurance employer premiums (spec §2/§6, S4/S6).
    "nl_awf_low_pct": "employer_pct",
    "nl_awf_high_pct": "employer_pct",
    "nl_aof_low_pct": "employer_pct",
    "nl_aof_high_pct": "employer_pct",
    "nl_wko_pct": "employer_pct",
    # Whk — employer-specific Belastingdienst decision/sector rate, NEVER a
    # universal fallback (spec §2/§6, NL-017). Kept in the key catalog (so the
    # readiness check knows the key exists) but deliberately UNSHED: a missing
    # employer decision BLOCKS.
    "nl_whk_wga_pct": "employer_pct",
    "nl_whk_zwflex_pct": "employer_pct",
    # Zvw (spec §2/§7, S4) — employer levy vs employee contribution paths.
    "nl_zvw_employer_pct": "employer_pct",
    "nl_zvw_employee_pct": "employee_pct",
    # WKR (spec §2/§8, S7).
    "nl_wkr_free_space_pct_first": "employer_pct",
    "nl_wkr_free_space_threshold": "amount",
    "nl_wkr_free_space_pct_above": "employer_pct",
    "nl_wkr_excess_levy_pct": "employer_pct",
    # Expat 30% facility (spec §2/§9, S8).
    "nl_expat_salary_threshold": "amount",
    "nl_expat_salary_threshold_young_master": "amount",
    "nl_expat_max_facility_pct": "employee_pct",
    "nl_expat_allowance_cap": "amount",
    "nl_wnt_cap": "amount",
    # Labor pay (spec §14, S15/S16/S17).
    "nl_vacation_allowance_pct": "employee_pct",
    "nl_vacation_hours_multiplier": "amount",
    "nl_sick_pay_pct": "employee_pct",
    "nl_sick_pay_max_years": "amount",
    "nl_transition_payment_cap": "amount",
    "nl_transition_payment_month_frac": "text",
}

# ── ContributionRate scalar content ───────────────────────────────────────
# (component_key, label, employee_pct, employer_pct, flat_amount, text_value,
#  source, needs_g1)
NL_SCALAR_CONTENT = (
    # Table colour (spec §3, S2/S9).
    ("nl_table_color", "Wage-tax table colour — current employment", None, None, None, "WHITE", "S9", True),
    # Reference annual Box 1 brackets (spec §2, S3) — validation only.
    ("nl_box1_band1_rate", "Box 1 band 1 rate (below AOW age, reference only)", "35.75", None, None, None, "S3", True),
    ("nl_box1_band1_ceiling", "Box 1 band 1 ceiling (reference only)", None, None, "38883.00", None, "S3", True),
    ("nl_box1_band2_rate", "Box 1 band 2 rate (below AOW age, reference only)", "37.56", None, None, None, "S3", True),
    ("nl_box1_band2_ceiling", "Box 1 band 2 ceiling (reference only)", None, None, "78426.00", None, "S3", True),
    ("nl_box1_band3_rate", "Box 1 band 3 rate (above band 2, reference only)", "49.50", None, None, None, "S3", True),
    # Anonymous-person withholding rate (spec §3).
    ("nl_anonymous_rate_pct", "Anonymous-person withholding rate (spec §3)", "52.00", None, None, None, "S1", True),
    # Tax credits (spec §2).
    ("nl_general_tax_credit_max", "General tax credit (algemene heffingskorting) — maximum", None, None, "3115.00", None, "S1", True),
    ("nl_general_tax_credit_phase_start", "General tax credit — phase-down starts at this income", None, None, "29736.00", None, "S1", True),
    ("nl_general_tax_credit_phase_end", "General tax credit — zero above this income", None, None, "78426.00", None, "S1", True),
    ("nl_employment_tax_credit_max", "Employment tax credit (arbeidskorting) — maximum", None, None, "5685.00", None, "S1", True),
    ("nl_employment_tax_credit_phase_end", "Employment tax credit — zero above this income", None, None, "132920.00", None, "S1", True),
    ("nl_aow_age_years", "Statutory AOW (state pension) age in years — wage-tax table cohort", None, None, "67", None, "S1", True),
    # Employer premiums (spec §2/§6). AWf is contract-dependent (NL-015); Aof
    # depends on employer size (2024 premium wage for 2026, NL-017).
    ("nl_awf_low_pct", "AWf low rate (permanent, non-on-call written contract)", None, "2.7400", None, None, "S6", True),
    ("nl_awf_high_pct", "AWf high rate (low-rate conditions not met)", None, "7.7400", None, None, "S6", True),
    ("nl_aof_low_pct", "Aof low rate (small employer, 2024 premium wage)", None, "6.2700", None, None, "S4", True),
    ("nl_aof_high_pct", "Aof high rate (large employer, 2024 premium wage)", None, "7.6300", None, None, "S4", True),
    ("nl_wko_pct", "Wko surcharge (employer cost on relevant premium wage)", None, "0.5000", None, None, "S4", True),
    # Zvw (spec §2/§7) — two paths, separate VCR series where both occur.
    ("nl_zvw_employer_pct", "Zvw employer levy (up to the maximum contribution wage)", None, "6.1000", None, None, "S4", True),
    ("nl_zvw_employee_pct", "Zvw employee contribution (net-pay withholding path)", "4.8500", None, None, None, "S4", True),
    # WKR (spec §2/§8).
    ("nl_wkr_free_space_pct_first", "WKR free space — first band (% of fiscal wage)", None, "2.0000", None, None, "S7", True),
    ("nl_wkr_free_space_threshold", "WKR free space — band boundary (fiscal wage)", None, None, "400000.00", None, "S7", True),
    ("nl_wkr_free_space_pct_above", "WKR free space — above the band boundary", None, "1.1800", None, None, "S7", True),
    ("nl_wkr_excess_levy_pct", "WKR final levy on the amount above available free space", None, "80.0000", None, None, "S7", True),
    # Expat 30% facility (spec §2/§9).
    ("nl_expat_salary_threshold", "Expat scheme — expertise salary threshold (2026)", None, None, "48013.00", None, "S8", True),
    ("nl_expat_salary_threshold_young_master", "Expat scheme — under-30 qualifying-master threshold (2026)", None, None, "36497.00", None, "S8", True),
    ("nl_expat_max_facility_pct", "Expat scheme — maximum tax-free facility (30%)", "30.00", None, None, None, "S8", True),
    ("nl_expat_allowance_cap", "Expat scheme — maximum 30% allowance (2026)", None, None, "78600.00", None, "S8", True),
    ("nl_wnt_cap", "WNT cap (2026) — governs the maximum full-year facility", None, None, "262000.00", None, "S8", True),
    # Labor pay (spec §14).
    ("nl_vacation_allowance_pct", "Statutory vacation allowance — minimum % of qualifying gross wage", "8.00", None, None, None, "S15", True),
    ("nl_vacation_hours_multiplier", "Statutory vacation entitlement — × weekly working hours", None, None, "4.00", None, "S15", True),
    ("nl_sick_pay_pct", "Statutory sick-pay continuation — minimum %", "70.00", None, None, None, "S16", True),
    ("nl_sick_pay_max_years", "Statutory sick-pay continuation — maximum years (ordinary cases)", None, None, "2.00", None, "S16", True),
    ("nl_transition_payment_cap", "Transition payment — 2026 cap (or one annual salary if higher)", None, None, "102000.00", None, "S17", True),
    ("nl_transition_payment_month_frac", "Transition payment — months of salary per service year", None, None, None, "1/3", "S17", True),
)

# ── Minimum wage — TaxSlab rule_type="NL_MIN_WAGE" ────────────────────────
# (age_cohort, hourly_amount, effective_from, effective_to, source, needs_g1)
# Spec §2 gives the 1 Jul 2026 rates by age; F6 confirms the 1 Jan 2026
# 21+ rate (€14.71). The 1 Jan 2026 YOUTH rates are NOT stated by the
# specification, so no January row exists for age < 21: a January payroll
# for a younger worker BLOCKS until gate G1 supplies the official rates —
# never a guessed value.
NL_MIN_WAGE_RATES = (
    ("AGE_21_PLUS", "14.71", date(2026, 1, 1), date(2026, 6, 30), "S14", True),
    ("AGE_21_PLUS", "14.99", date(2026, 7, 1), None, "S14", True),
    ("AGE_20", "11.99", date(2026, 7, 1), None, "S14", True),
    ("AGE_19", "8.99", date(2026, 7, 1), None, "S14", True),
    ("AGE_18", "7.50", date(2026, 7, 1), None, "S14", True),
    ("AGE_17", "5.92", date(2026, 7, 1), None, "S14", True),
    ("AGE_16", "5.17", date(2026, 7, 1), None, "S14", True),
    ("AGE_15", "4.50", date(2026, 7, 1), None, "S14", True),
)

# ── VCR time-period maxima — TaxSlab rule_type="NL_PERIOD_MAX" ────────────
# (period_code, max_amount, source, needs_g1)
# Spec §5 requires the official daily/weekly/4-weekly/monthly/quarterly
# maxima; §2 states the annual maximum (€79,409) and the monthly maximum
# (€6,617.41) only. The other periods' published figures are NOT restated by
# the specification, so they are absent: a payroll whose period has no row
# BLOCKS rather than being capped against an invented figure.
NL_PERIOD_MAXIMA = (
    ("ANNUAL", "79409.00", "S4", True),
    ("MONTHLY", "6617.41", "S4", True),
)

# ── WKR bands — TaxSlab rule_type="NL_WKR_BAND" ───────────────────────────
# (band_kind, min_amount, max_amount, rate_pct, source, needs_g1)
# Free space: 2.00% of fiscal wage up to €400,000, then 1.18% above; the
# final levy on the excess is 80% (spec §2/§8, S7).
NL_WKR_BANDS = (
    ("FREE_SPACE", "0", "400000.00", "2.0000", "S7", True),
    ("FREE_SPACE", "400000.00", None, "1.1800", "S7", True),
    ("EXCESS_LEVY", "0", None, "80.0000", "S7", True),
)

# ── Company-car addition — TaxSlab rule_type="NL_CAR_ADDITION" ────────────
# (car_class, rate_pct, effective_from, effective_to, source, needs_g1)
# The 2026 headline bijtelling rates are 22% (standard) and 18%
# (zero-emission). NL-025 is explicit that these are NOT a universal fleet
# rule — older vehicles keep their own effective-dated percentages/caps, so
# these two rows are the 2026 default window only; the catalog-value and
# first-admission caps are additional benefit-in-kind inputs (NL-024).
NL_CAR_ADDITION_BANDS = (
    ("STANDARD", "22.0000", date(2026, 1, 1), None, "S1", True),
    ("ZERO_EMISSION", "18.0000", date(2026, 1, 1), None, "S1", True),
)

# ── Category labels for UI grouping ──────────────────────────────────────
NL_CATEGORIES = {
    "reference_brackets": "Reference Box 1 Brackets (validation only)",
    "tax_credits": "Tax Credits (loonheffingskorting)",
    "employee_insurance": "Employee-Insurance Premiums (AWf / Aof / Wko)",
    "whk": "Whk (employer-specific)",
    "zvw": "Zvw (Zorgverzekeringswet)",
    "wkr": "WKR (Werkkostenregeling)",
    "expat": "Expat Scheme (30% facility)",
    "labor_pay": "Labor Pay (vacation, sick pay, transition payment)",
    "minimum_wage": "Statutory Minimum Wage (hourly, by age)",
    "period_maxima": "VCR Time-Period Maxima",
    "car_addition": "Company-Car Addition (bijtelling)",
}


def _row_in_window(eff_from, eff_to, as_of):
    if eff_from is not None and as_of < eff_from:
        return False
    if eff_to is not None and as_of > eff_to:
        return False
    return True


def content_rows_in_force(as_of: date):
    """Scalar content rows (undated in this Draft — the pack window dates them)."""
    return {row[0]: row for row in NL_SCALAR_CONTENT}


def min_wage_rates_in_force(as_of: date):
    """Minimum-wage rows legally in force on `as_of`."""
    return [
        (cohort, Decimal(amount), eff_from, eff_to, source)
        for (cohort, amount, eff_from, eff_to, source, _g1) in NL_MIN_WAGE_RATES
        if _row_in_window(eff_from, eff_to, as_of)
    ]


def period_maxima_in_force(as_of: date):
    """VCR period-maximum rows (undated in this Draft)."""
    return {code: Decimal(amount) for (code, amount, _source, _g1) in NL_PERIOD_MAXIMA}


def wkr_bands_in_force(as_of: date):
    """WKR band rows (undated in this Draft)."""
    return [(kind, Decimal(lo), (Decimal(hi) if hi is not None else None), Decimal(rate))
            for (kind, lo, hi, rate, _source, _g1) in NL_WKR_BANDS]


def car_addition_bands_in_force(as_of: date):
    """Company-car addition rows legally in force on `as_of`."""
    return [
        (car_class, Decimal(rate), eff_from, eff_to)
        for (car_class, rate, eff_from, eff_to, _source, _g1) in NL_CAR_ADDITION_BANDS
        if _row_in_window(eff_from, eff_to, as_of)
    ]
