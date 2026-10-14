"""
modules/payroll/engine/countries/saudi_arabia_content.py
---------------------------------------------------------
Saudi Arabia 2026 statutory content catalog (Draft) — the ONE list
of every rate and parameter row engine/countries/saudi_arabia.py
reads from `rate_map` / `slabs`. Pure data, no ORM import, shared by:

  * saudi_arabia_service.seed_saudi_arabia_pack (via
    scripts/seed_saudi_arabia_canonical_packs.py) — writes these rows into
    the SA-PAYROLL-2026 canonical JurisdictionPack (Draft);
  * tests/test_saudi_arabia_content.py — the contract test that pins the
    rules below to ZP-SA-ENG-001;
  * the Super Admin Saudi Arabia component picker.

Conventions (must match saudi_arabia.py):
  * Scalar parameters are ContributionRate rows keyed by component_key:
      kind "employee_pct"/"employer_pct" — a PERCENT number (10.00 = 10%)
        in employee_rate_pct / employer_rate_pct;
      kind "amount" — flat_amount (SAR, hours, days or a multiple);
      kind "text"   — text_value (an enum label, or an exact fraction such
        as "1/3": flat_amount is Numeric(14,2) and would store 1/3 as 0.33).
  * GOSI branch rows are TaxSlab rule_type="SA_GOSI_BRANCH":
      filing_status     = worker class ("SAUDI" | "NON_SAUDI")
      tax_regime        = branch ("PENSION_NEW" | "PENSION_LEGACY" |
                          "SANED" | "OCCUPATIONAL_HAZARDS")
      rate_pct          = employee rate (percent)
      employer_rate_pct = employer rate (percent)
      min_amount        = contributory-wage minimum for the branch (SAR/month)
      max_amount        = contributory-wage maximum for the branch (SAR/month)
      effective_from / effective_to = LEGAL effective dating of the row.
  * Earning classification rows are TaxSlab rule_type="SA_EARNING_CLASS",
    the Hong Kong HK_EARNING_CLASS layout:
      filing_status    = pay component (BASIC, HOUSING, …)
      tax_regime       = obligation ("GOSI" | "WPS" | "EOS")
      assessment_basis = "INCLUDED" | "EXCLUDED" | "REVIEW"
    REVIEW means "not decided by the specification" and BLOCKS any
    calculation that would need it (spec §5: an independent inclusion flag
    and source evidence are required before a component counts).

Scope (spec §1, §3, SA-001, SA-020): only SAUDI and NON_SAUDI ordinary
private-sector workers have rows. GCC nationals and domestic workers have NO
rows on purpose — the engine BLOCKS them, it never computes them.

Status is Draft throughout; the registry row stays PLANNED. Items marked
PENDING_G1 must be signed by a Saudi payroll specialist at gate G1 (spec §18)
before any pack carrying them is activated.
"""

from datetime import date
from decimal import Decimal

PACK_STATUS = "Draft"

# One calendar-year pack; rows inside it carry their own legal dates (the
# 3 Jul 2026 pension step is a ROW boundary, not a pack boundary).
SA_2026 = ("SA-PAYROLL-2026", date(2026, 1, 1), date(2026, 12, 31))

# ── Evidence register (ZP-SA-ENG-001 §19, S1–S16) ─────────────────────────
SOURCE_REFERENCES = (
    ("S1", "GOSI — New Social Insurance Law awareness for employers (new-system coverage, "
           "11% target pension with 0.5-point annual phase-in, SANED 1.5% total, OH 2%)"),
    ("S2", "GOSI — New Social Insurance Law statutory text (wage base and contribution branches)"),
    ("S3", "GOSI — Current-system / non-included cohort awareness (legacy pension 9%, "
           "SANED 0.75% each, OH 2%)"),
    ("S4", "GOSI — Employer FAQ (contributory wage minimum/maximum, payment by the 15th of "
           "the following month, registration operations)"),
    ("S5", "GOSI — Saudi workers / contributory wage (basic + housing, SAR 45,000 maximum)"),
    ("S6", "HRSD — Wage Protection file upload (Mudad channel, compliance processing)"),
    ("S7", "HRSD — Wage Protection Program (WPS pay-file component fields)"),
    ("S8", "HRSD — Employment contract enforceability / Mudad linkage (Qiwa wage clause)"),
    ("S9", "HRSD — Working conditions / Labor Law (wage timing, deductions, hours, overtime, leave)"),
    ("S10", "HRSD — Labor Law amendments effective 19 Feb 2025"),
    ("S11", "HRSD — Women Employment (12-week maternity leave)"),
    ("S12", "HRSD — Sick leave (30 days full, 60 at three-quarters, 30 unpaid)"),
    ("S13", "HRSD — Labor Relations (end-of-service formula and resignation fractions)"),
    ("S14", "SDAIA — Personal Data Protection Law (Article 29 transfers)"),
    ("S15", "SDAIA — Regulation on Personal Data Transfer outside the Kingdom"),
    ("S16", "ZATCA — Income Tax (ordinary employment salary is not a payroll withholding regime)"),
)
SOURCE_CODES = tuple(code for code, _ in SOURCE_REFERENCES)

# ── TaxSlab rule_type discriminators (all ≤ 30 chars) ────────────────────
SA_GOSI_BRANCH_RULE = "SA_GOSI_BRANCH"
SA_EARNING_CLASS_RULE = "SA_EARNING_CLASS"

# ── Enumerations the engine validates against ─────────────────────────────
WORKER_CLASSES_SUPPORTED = ("SAUDI", "NON_SAUDI")
# Recorded but never calculated at launch (spec §1/§3, SA-001, SA-020).
WORKER_CLASSES_BLOCKED = ("GCC", "DOMESTIC")
BRANCHES = ("PENSION_NEW", "PENSION_LEGACY", "SANED", "OCCUPATIONAL_HAZARDS")
OBLIGATIONS = ("GOSI", "WPS", "EOS")
TREATMENTS = ("INCLUDED", "EXCLUDED", "REVIEW")
# sa_rate_selection_basis (SA-007): which date inside the contribution month
# selects the branch row. PENDING_G1 = not yet signed — a contribution month
# in which two rows of the same branch are both in force BLOCKS.
RATE_SELECTION_BASES = ("CONTRIBUTION_MONTH_START", "CONTRIBUTION_MONTH_END", "PENDING_G1")
# sa_gosi_below_min_behaviour (SA-010): a registered contributory wage below
# a branch minimum either BLOCKS (default) or is raised to the minimum.
BELOW_MIN_BEHAVIOURS = ("BLOCK", "FLOOR")
ROUNDING_MODES = ("HALF_UP", "DOWN", "UP")

# ── Scalar engine parameter keys ──────────────────────────────────────────
# key -> kind. The engine's SA_PARAMETER_KEYS is THIS dict (imported).
SA_PARAMETER_KEYS = {
    # GOSI rate selection, minimum handling and rounding (SA-007/009/010)
    "sa_rate_selection_basis": "text",
    "sa_gosi_below_min_behaviour": "text",
    "sa_rounding_mode": "text",
    "sa_rounding_precision": "amount",
    # GOSI payment due day (SA-022)
    "sa_gosi_due_day": "amount",
    # Working hours (spec §11)
    "sa_normal_hours_daily": "amount",
    "sa_normal_hours_weekly": "amount",
    "sa_ramadan_hours_daily": "amount",
    "sa_ramadan_hours_weekly": "amount",
    # Overtime (spec §11): hourly wage + premium% × basic hourly wage
    "sa_overtime_basic_premium_pct": "employee_pct",
    "sa_monthly_hours_divisor": "amount",
    # Deduction caps (spec §11, SA-029)
    "sa_loan_cap_pct": "employee_pct",
    "sa_damage_cap_pct": "employee_pct",
    "sa_aggregate_deduction_cap_pct": "employee_pct",
    # Annual leave (spec §12)
    "sa_annual_leave_days_base": "amount",
    "sa_annual_leave_days_after_5_years": "amount",
    # Sick leave (spec §12)
    "sa_sick_leave_full_pay_days": "amount",
    "sa_sick_leave_75_pct_days": "amount",
    "sa_sick_leave_unpaid_days": "amount",
    # Maternity (spec §12)
    "sa_maternity_leave_weeks": "amount",
    "sa_maternity_mandatory_post_birth_weeks": "amount",
    # End of service (spec §13)
    "sa_eos_first_5_years_months": "amount",
    "sa_eos_after_5_years_months": "amount",
    "sa_eos_resign_frac_under_2": "text",
    "sa_eos_resign_frac_2_to_5": "text",
    "sa_eos_resign_frac_5_to_10": "text",
    "sa_eos_resign_frac_10_plus": "text",
    # Settlement deadlines (spec §13)
    "sa_settlement_deadline_termination_days": "amount",
    "sa_settlement_deadline_resignation_days": "amount",
}

# ── ContributionRate scalar content ───────────────────────────────────────
# (component_key, label, employee_pct, employer_pct, flat_amount, text_value,
#  source, pending_g1)
SA_SCALAR_CONTENT = (
    ("sa_rate_selection_basis", "GOSI rate selection inside a contribution month (SA-007)",
     None, None, None, "PENDING_G1", "S1", True),
    ("sa_gosi_below_min_behaviour", "Registered wage below a branch minimum (SA-010)",
     None, None, None, "BLOCK", "S4", True),
    ("sa_rounding_mode", "SAR rounding mode, per branch and per side (SA-009)",
     None, None, None, "HALF_UP", "S4", True),
    ("sa_rounding_precision", "SAR rounding precision (decimals)", None, None, "2", None, "S4", True),
    ("sa_gosi_due_day", "GOSI payment due by day of following month", None, None, "15", None, "S4", False),
    ("sa_normal_hours_daily", "Normal daily working hours", None, None, "8", None, "S9", False),
    ("sa_normal_hours_weekly", "Normal weekly working hours", None, None, "48", None, "S9", False),
    ("sa_ramadan_hours_daily", "Ramadan daily working hours (Muslim workers)", None, None, "6", None, "S9", False),
    ("sa_ramadan_hours_weekly", "Ramadan weekly working hours (Muslim workers)", None, None, "36", None, "S9", False),
    ("sa_overtime_basic_premium_pct", "Overtime premium (% of basic hourly wage)",
     "50.0000", None, None, None, "S9", False),
    # The hourly divisor is NOT stated by the specification (30 days x 8h is
    # common practice) — PENDING_G1.
    ("sa_monthly_hours_divisor", "Monthly hours used to derive an hourly wage",
     None, None, "240", None, "S9", True),
    ("sa_loan_cap_pct", "Employer loan recovery cap (% of wage)", "10.0000", None, None, None, "S9", False),
    # The damage-recovery monthly limit is NOT stated by the specification
    # ("special monthly limits apply") — no value until G1 supplies one; a
    # DAMAGE deduction BLOCKS while this row is absent.
    ("sa_aggregate_deduction_cap_pct", "Total deductions cap (% of due wage)",
     "50.0000", None, None, None, "S9", False),
    ("sa_annual_leave_days_base", "Annual leave days (first 5 years)", None, None, "21", None, "S9", False),
    ("sa_annual_leave_days_after_5_years", "Annual leave days (after 5 consecutive years)",
     None, None, "30", None, "S9", False),
    ("sa_sick_leave_full_pay_days", "Sick leave — full pay days", None, None, "30", None, "S12", False),
    ("sa_sick_leave_75_pct_days", "Sick leave — 75% pay days", None, None, "60", None, "S12", False),
    ("sa_sick_leave_unpaid_days", "Sick leave — unpaid days", None, None, "30", None, "S12", False),
    ("sa_maternity_leave_weeks", "Maternity leave (weeks)", None, None, "12", None, "S11", False),
    ("sa_maternity_mandatory_post_birth_weeks", "Maternity mandatory post-birth (weeks)",
     None, None, "6", None, "S11", False),
    ("sa_eos_first_5_years_months", "EOS — months of wage per year, first 5 years",
     None, None, "0.5", None, "S13", False),
    ("sa_eos_after_5_years_months", "EOS — months of wage per year, after 5 years",
     None, None, "1", None, "S13", False),
    # Resignation fractions (spec §13): <2 years nothing; 2–5 one-third;
    # >5 and <10 two-thirds; 10+ the full award. Exact fractions as text.
    ("sa_eos_resign_frac_under_2", "EOS on resignation — under 2 years", None, None, None, "0", "S13", False),
    ("sa_eos_resign_frac_2_to_5", "EOS on resignation — 2 to 5 years", None, None, None, "1/3", "S13", False),
    ("sa_eos_resign_frac_5_to_10", "EOS on resignation — over 5 and under 10 years",
     None, None, None, "2/3", "S13", False),
    ("sa_eos_resign_frac_10_plus", "EOS on resignation — 10 years or more", None, None, None, "1", "S13", False),
    ("sa_settlement_deadline_termination_days", "Final settlement deadline — employer termination (days)",
     None, None, "7", None, "S13", False),
    ("sa_settlement_deadline_resignation_days", "Final settlement deadline — worker termination (days)",
     None, None, "14", None, "S13", False),
)

# ── GOSI branch content — TaxSlab rule_type="SA_GOSI_BRANCH" ──────────────
# (worker_class, branch, ee_pct, er_pct, min, max, effective_from,
#  effective_to, label, source, pending_g1)
# Spec §4: new-system pension 9.5% to 2 Jul 2026, 10% from 3 Jul 2026 (the
# spec's legal date — some secondary sources cite 1 Jul; G1 confirms, and
# sa_rate_selection_basis decides the crossing month). Legacy pension 9%.
# SANED 0.75%/0.75%. OH 2% employer for every covered worker. Non-Saudi
# ordinary workers: OH ONLY — no Saudi pension and no SANED (spec §3/§4, F4).
_NEW_STEP = date(2026, 7, 3)

SA_GOSI_BRANCHES = (
    ("SAUDI", "PENSION_NEW", "9.5000", "9.5000", "1500", "45000",
     date(2026, 1, 1), date(2026, 7, 2),
     "Pension — Saudi, new system 9.5%", "S1", True),
    ("SAUDI", "PENSION_NEW", "10.0000", "10.0000", "1500", "45000",
     _NEW_STEP, None,
     "Pension — Saudi, new system 10% (from 3 Jul 2026)", "S1", True),
    ("SAUDI", "PENSION_LEGACY", "9.0000", "9.0000", "1500", "45000",
     date(2026, 1, 1), None,
     "Pension — Saudi, current/legacy system 9%", "S3", False),
    # The SANED-specific minimum is not stated separately by the spec; the
    # pension-branch minimum is used pending G1.
    ("SAUDI", "SANED", "0.7500", "0.7500", "1500", "45000",
     date(2026, 1, 1), None,
     "SANED unemployment insurance — Saudi 0.75% / 0.75%", "S1", True),
    ("SAUDI", "OCCUPATIONAL_HAZARDS", "0.0000", "2.0000", "400", "45000",
     date(2026, 1, 1), None,
     "Occupational Hazards — Saudi 2% employer", "S1", False),
    # SA-012: OH-only coverage uses separately certified min/max — PENDING_G1.
    ("NON_SAUDI", "OCCUPATIONAL_HAZARDS", "0.0000", "2.0000", "400", "45000",
     date(2026, 1, 1), None,
     "Occupational Hazards — Non-Saudi 2% employer (OH only)", "S4", True),
)

# ── Earning classification — TaxSlab rule_type="SA_EARNING_CLASS" ─────────
# (obligation, treatment, component, label, source)
# Components map to PayrollContext: BASIC=basic, HOUSING=hra,
# HOUSING_IN_KIND=profile.sa_in_kind_housing_value,
# ALLOWANCE_REGULAR=special_allowance, OVERTIME=overtime,
# OTHER_EARNINGS=gross minus every named component.
SA_EARNING_CLASSES = (
    # GOSI contributory wage (spec §5, SA-012): basic + housing (cash, or
    # in-kind at the GOSI valuation). Everything else needs a signed
    # interpretation first (REVIEW blocks).
    ("GOSI", "INCLUDED", "BASIC", "Basic salary — primary contributory-wage component", "S5"),
    ("GOSI", "INCLUDED", "HOUSING", "Cash housing allowance — contractual cash value", "S5"),
    ("GOSI", "INCLUDED", "HOUSING_IN_KIND", "Employer-provided housing — GOSI valuation", "S5"),
    ("GOSI", "REVIEW", "ALLOWANCE_REGULAR", "Other allowances — rule-specific, needs signed evidence", "S2"),
    ("GOSI", "REVIEW", "COMMISSION", "Commission treated as basic — needs signed GOSI interpretation", "S2"),
    ("GOSI", "REVIEW", "OVERTIME", "Overtime — rule-specific, needs signed evidence", "S2"),
    ("GOSI", "REVIEW", "BONUS", "Bonus — not automatically pensionable", "S2"),
    ("GOSI", "REVIEW", "OTHER_EARNINGS", "Any other earning — needs a classification", "S2"),
    ("GOSI", "EXCLUDED", "EOS_AWARD", "End-of-service award — a statutory liability, not wage", "S13"),
    ("GOSI", "EXCLUDED", "LEAVE_ENCASHMENT", "Unused-leave payment on termination", "S9"),

    # WPS reporting classification (spec §6, S7): basic / housing / other
    # allowances / deductions / net. These are reporting buckets, not bases.
    ("WPS", "INCLUDED", "BASIC", "WPS basic salary field", "S7"),
    ("WPS", "INCLUDED", "HOUSING", "WPS housing allowance field", "S7"),
    ("WPS", "INCLUDED", "ALLOWANCE_REGULAR", "WPS other allowances field", "S7"),
    ("WPS", "INCLUDED", "OVERTIME", "WPS other allowances field", "S7"),
    ("WPS", "INCLUDED", "BONUS", "WPS other allowances field", "S7"),
    ("WPS", "INCLUDED", "COMMISSION", "WPS other allowances field", "S7"),
    ("WPS", "INCLUDED", "OTHER_EARNINGS", "WPS other allowances field", "S7"),
    ("WPS", "EXCLUDED", "HOUSING_IN_KIND", "In-kind housing is not a cash wage", "S7"),

    # EOS basis (spec §13): the last wage is the default basis; only
    # commission / sales-percentage elements may be excluded, and only with a
    # valid arrangement (REVIEW).
    ("EOS", "INCLUDED", "BASIC", "Last wage — basic", "S13"),
    ("EOS", "INCLUDED", "HOUSING", "Last wage — housing allowance", "S13"),
    ("EOS", "INCLUDED", "ALLOWANCE_REGULAR", "Last wage — fixed allowances", "S13"),
    ("EOS", "REVIEW", "HOUSING_IN_KIND", "In-kind housing — needs a signed valuation rule", "S13"),
    ("EOS", "REVIEW", "COMMISSION", "Commission — excludable only with a valid arrangement", "S13"),
    ("EOS", "EXCLUDED", "OVERTIME", "Overtime is not part of the fixed last wage", "S13"),
    ("EOS", "EXCLUDED", "BONUS", "One-off bonus is not part of the fixed last wage", "S13"),
)

# ── Category labels for UI grouping ──────────────────────────────────────
SA_CATEGORIES = {
    "gosi_branches": "GOSI Branches (pension, SANED, OH)",
    "earning_classes": "Earning Classification (GOSI / WPS / EOS)",
    "gosi_rules": "GOSI Rules (rate selection, minimum, rounding, due day)",
    "working_hours": "Working Hours & Overtime",
    "caps": "Deduction Caps",
    "leave": "Leave Entitlements",
    "eos": "End of Service",
    "settlement": "Settlement Deadlines",
}


def content_rows_in_force(as_of: date):
    """Scalar content rows (undated in this Draft — the pack window dates them)."""
    return {row[0]: row for row in SA_SCALAR_CONTENT}


def gosi_branches_in_force(as_of: date):
    """GOSI branch rows legally in force on `as_of`."""
    selected = []
    for (worker_class, branch, ee_pct, er_pct, min_amt, max_amt,
         eff_from, eff_to, label, src, pending) in SA_GOSI_BRANCHES:
        if eff_from is not None and as_of < eff_from:
            continue
        if eff_to is not None and as_of > eff_to:
            continue
        selected.append((worker_class, branch, Decimal(ee_pct), Decimal(er_pct),
                         Decimal(min_amt), Decimal(max_amt), eff_from, eff_to, label, src, pending))
    return selected


def earning_classes_in_force(as_of: date):
    """Earning classification rows (undated in this Draft)."""
    return SA_EARNING_CLASSES
