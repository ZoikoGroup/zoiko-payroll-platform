"""
engine/fallback_registry.py
----------------------------
Read-only inventory of every hardcoded fallback value the payroll engine
falls back to when no canonical/org-configured rate exists — powers Super
Admin Compliance's "Engine Fallback Defaults" viewer.

Two genuinely different layers exist (see the viewer's own intro banner):

1. Seed dicts (`_CONTRIBUTION_RATES_BY_COUNTRY`/`_TAX_SLABS_BY_COUNTRY` in
   service.py) — these become real, Super-Admin-editable DB rows the first
   time an org uses that jurisdiction (`_seed_contribution_rates`/
   `_seed_tax_slabs`). Re-exported here as-is, never duplicated.
2. True engine-only constants — module-level constants in
   `engine/countries/*.py`, passed as `resolve_jurisdiction_parameter`'s
   `default=` argument. These have NO database row, ever — the only way to
   see or change one is reading/editing source code. `_ENGINE_CONSTANT_REGISTRY`
   below stores metadata ONLY (which constant, what it means, which
   resolver key it's registered under) — never a literal value. The actual
   value is read live via `getattr(module, attr)` in
   `get_engine_fallback_inventory()`, so this page can never drift from the
   real constant even if it changes in, say, us.py tomorrow.

`skip_discrepancy_check=True` marks the 3 India Old-Regime variants
(_IN_STANDARD_DEDUCTION_OLD etc.) — these deliberately differ from their
New-Regime counterpart's seeded value (a real, intentional regime split,
not a bug), so the viewer's automatic seed-vs-engine mismatch callout
skips them rather than flagging a false positive.
"""

from decimal import Decimal

from app.modules.payroll.engine.countries import australia, canada, germany, hong_kong, india, singapore, sweden, switzerland, uk, us
from app.modules.payroll import hardcoded_defaults

_MODULES = {
    "india": india,
    "us": us,
    "uk": uk,
    "australia": australia,
    "canada": canada,
    "germany": germany,
    "hardcoded_defaults": hardcoded_defaults,
    "singapore": singapore,
    "hong_kong": hong_kong,
    "sweden": sweden,
    "switzerland": switzerland,
}

_ENGINE_CONSTANT_REGISTRY = [
    # ── India ────────────────────────────────────────────────────────────
    {"country": "IN", "module": "india", "attr": "ESI_MONTHLY_WAGE_CEILING", "label": "ESI Wage Ceiling (Monthly)", "resolverKey": "esi_wage_ceiling"},
    {"country": "IN", "module": "india", "attr": "_IN_STANDARD_DEDUCTION", "label": "Standard Deduction (New Regime)", "resolverKey": "standard_deduction"},
    {"country": "IN", "module": "india", "attr": "_IN_STANDARD_DEDUCTION_OLD", "label": "Standard Deduction (Old Regime)", "resolverKey": "standard_deduction", "skip_discrepancy_check": True, "note": "Old Regime uses a different code-level default than the seeded (New Regime) value — intentional, not a mismatch."},
    {"country": "IN", "module": "india", "attr": "_IN_REBATE_87A_LIMIT", "label": "Section 87A Rebate — Income Limit (New Regime)", "resolverKey": "rebate_87a_limit"},
    {"country": "IN", "module": "india", "attr": "_IN_REBATE_87A_MAX", "label": "Section 87A Rebate — Max Amount (New Regime)", "resolverKey": "rebate_87a_max"},
    {"country": "IN", "module": "india", "attr": "_IN_REBATE_87A_LIMIT_OLD", "label": "Section 87A Rebate — Income Limit (Old Regime)", "resolverKey": "rebate_87a_limit", "skip_discrepancy_check": True, "note": "Old Regime uses a different code-level default than the seeded (New Regime) value — intentional, not a mismatch."},
    {"country": "IN", "module": "india", "attr": "_IN_REBATE_87A_MAX_OLD", "label": "Section 87A Rebate — Max Amount (Old Regime)", "resolverKey": "rebate_87a_max", "skip_discrepancy_check": True, "note": "Old Regime uses a different code-level default than the seeded (New Regime) value — intentional, not a mismatch."},
    {"country": "IN", "module": "india", "attr": "_IN_CESS_PCT", "label": "Health & Education Cess %", "resolverKey": "cess_pct", "note": "No seedable counterpart — code-only."},

    # ── USA ──────────────────────────────────────────────────────────────
    {"country": "US", "module": "us", "attr": "_US_STANDARD_DEDUCTION", "label": "Federal Standard Deduction", "resolverKey": "standard_deduction", "note": "No seed row exists for US standard_deduction — this is the ONLY fallback if never configured."},
    {"country": "US", "module": "us", "attr": "_US_SOCIAL_SECURITY_WAGE_BASE", "label": "Social Security Wage Base", "resolverKey": "ss_wage_base"},
    {"country": "US", "module": "us", "attr": "_US_SOCIAL_SECURITY_RATE", "label": "Social Security Rate (Employee & Employer)", "resolverKey": "social-security"},
    {"country": "US", "module": "us", "attr": "_US_MEDICARE_RATE", "label": "Medicare Rate (Employee & Employer)", "resolverKey": "medicare"},
    {"country": "US", "module": "us", "attr": "_US_MEDICARE_ADDITIONAL_RATE", "label": "Additional Medicare Surtax Rate", "resolverKey": "medicare_additional", "note": "No seedable counterpart — code-only."},
    {"country": "US", "module": "us", "attr": "_US_MEDICARE_ADDL_THRESHOLD_DEFAULTS", "label": "Additional Medicare Threshold (by Filing Status)", "resolverKey": "medicare_addl_thresh", "kind": "dict", "note": "Only the Single/HOH figure (200000) has a seed row — MFJ/MFS-specific figures are code-only."},
    {"country": "US", "module": "us", "attr": "_US_MEDICARE_ADDITIONAL_THRESHOLD", "label": "Additional Medicare Threshold (fallback, no filing status)", "resolverKey": "medicare_addl_thresh"},
    {"country": "US", "module": "us", "attr": "_US_FUTA_RATE", "label": "FUTA Rate (Employer)", "resolverKey": "futa"},
    {"country": "US", "module": "us", "attr": "_US_FUTA_WAGE_BASE", "label": "FUTA Wage Base", "resolverKey": "futa_wage_base"},
    {"country": "US", "module": "us", "attr": "_US_FUTA_CREDIT_PCT", "label": "FUTA Standard Credit %", "resolverKey": "futa_credit_pct", "note": "No seedable counterpart — code-only."},

    # ── UK ───────────────────────────────────────────────────────────────
    {"country": "UK", "module": "uk", "attr": "_UK_PERSONAL_ALLOWANCE", "label": "Personal Allowance", "resolverKey": "personal_allowance"},
    {"country": "UK", "module": "uk", "attr": "_UK_PA_TAPER_THRESHOLD", "label": "Personal Allowance Taper Threshold", "resolverKey": "pa_taper_threshold"},
    {"country": "UK", "module": "uk", "attr": "_UK_NI_PRIMARY_THRESHOLD", "label": "NI Primary Threshold (Employee)", "resolverKey": "ni_primary_thresh"},
    {"country": "UK", "module": "uk", "attr": "_UK_NI_UPPER_THRESHOLD", "label": "NI Upper Earnings Limit (Employee)", "resolverKey": "ni_upper_threshold"},
    {"country": "UK", "module": "uk", "attr": "_UK_NI_PRIMARY_RATE", "label": "NI Rate Below Upper Threshold (Employee)", "resolverKey": "national-insurance", "side": "employee"},
    {"country": "UK", "module": "uk", "attr": "_UK_NI_UPPER_RATE", "label": "NI Rate Above Upper Threshold (Employee)", "resolverKey": "ni_upper_rate"},
    {"country": "UK", "module": "uk", "attr": "_UK_PENSION_MIN_ENPLOYER", "label": "Workplace Pension Minimum % (Employer)", "resolverKey": "employer-pension"},
    {"country": "UK", "module": "uk", "attr": "_UK_NI_SECONDARY_THRESHOLD", "label": "NI Secondary Threshold (Employer)", "resolverKey": "ni_secondary_thresh"},
    {"country": "UK", "module": "uk", "attr": "_UK_NI_EMPLOYER_RATE", "label": "NI Standard Rate (Employer)", "resolverKey": "national-insurance", "side": "employer"},
    {"country": "UK", "module": "uk", "attr": "_UK_PENSION_QE_LOWER", "label": "Pension Qualifying Earnings — Lower Limit", "resolverKey": "pension_qe_lower", "note": "No seedable counterpart — code-only."},
    {"country": "UK", "module": "uk", "attr": "_UK_PENSION_QE_UPPER", "label": "Pension Qualifying Earnings — Upper Limit", "resolverKey": "pension_qe_upper", "note": "No seedable counterpart — code-only."},
    {"country": "UK", "module": "uk", "attr": "_UK_STUDENT_LOAN_PLANS", "label": "Student Loan Plans — Threshold & Rate", "resolverKey": "sl_plan1_thresh / sl_plan2_thresh / sl_plan4_thresh / sl_plan5_thresh / pg_loan_thresh", "kind": "dict", "note": "No seedable counterpart for any plan — all code-only."},
    {"country": "UK", "module": "uk", "attr": "_UK_FLAT_RATE_CODES", "label": "Flat-Rate PAYE Tax Code Families", "resolverKey": "N/A — not read via resolve_jurisdiction_parameter", "kind": "dict", "note": "Pure code constant, no DB counterpart at all."},

    # ── Australia ────────────────────────────────────────────────────────
    # Medicare Levy PROPER has no scalar fallback here any more — it's
    # embedded in the Schedule 1 Scale 1/2/5/6 AU_PAYG_COEFFICIENT TaxSlab
    # bands themselves, not a single resolve_jurisdiction_parameter value.
    {"country": "AU", "module": "australia", "attr": "_AU_MLS_THRESHOLD", "label": "Medicare Levy Surcharge Threshold", "resolverKey": "mls_threshold"},
    {"country": "AU", "module": "australia", "attr": "_AU_MLS_RATE", "label": "Medicare Levy Surcharge Rate", "resolverKey": "mls_rate"},
    {"country": "AU", "module": "australia", "attr": "_AU_SUPER_MAX_CONTRIBUTION_BASE", "label": "Superannuation Guarantee Max Contribution Base", "resolverKey": "super_max_contrib"},
    # HELP/HECS's old flat threshold+rate fallback is removed along with
    # the constants themselves — superseded by the real ATO Schedule 8
    # coefficient-band mechanism, which has no single-scalar fallback.
    {"country": "AU", "module": "australia", "attr": "_AU_PAYG_SCALE4_RESIDENT_RATE", "label": "PAYG Scale 4 (No TFN) Resident Rate", "resolverKey": "payg_scale4_resident_rate"},
    {"country": "AU", "module": "australia", "attr": "_AU_PAYG_SCALE4_NONRESIDENT_RATE", "label": "PAYG Scale 4 (No TFN) Non-Resident Rate", "resolverKey": "payg_scale4_nonresident_rate"},
    {"country": "AU", "module": "australia", "attr": "_AU_ETP_LIFE_CAP", "label": "ETP Life Benefit Cap", "resolverKey": "etp_life_cap"},
    {"country": "AU", "module": "australia", "attr": "_AU_ETP_DEATH_CAP", "label": "ETP Death Benefit Cap", "resolverKey": "etp_death_cap"},
    {"country": "AU", "module": "australia", "attr": "_AU_GENUINE_REDUNDANCY_BASE", "label": "Genuine Redundancy Tax-Free Base", "resolverKey": "redundancy_base"},
    {"country": "AU", "module": "australia", "attr": "_AU_GENUINE_REDUNDANCY_PER_YEAR", "label": "Genuine Redundancy Tax-Free Per Year", "resolverKey": "redundancy_per_yr"},
    {"country": "AU", "module": "australia", "attr": "_AU_UNTAXED_PLAN_CAP", "label": "Untaxed Plan Cap", "resolverKey": "untaxed_plan_cap"},
    {"country": "AU", "module": "australia", "attr": "_AU_TRANSFER_BALANCE_CAP", "label": "General Transfer Balance Cap", "resolverKey": "transfer_balance_cap"},
    {"country": "AU", "module": "australia", "attr": "_AU_DEFINED_BENEFIT_INCOME_CAP", "label": "Defined Benefit Income Cap", "resolverKey": "db_income_cap"},
    # State/territory employer payroll tax — NSW/TAS/ACT have no scalar
    # fallback here (they're TaxSlab bracket tables instead, same as
    # Canada's ON_EHT_BAND rows); SA's reduced-rate band has none of any
    # kind by the source document's own explicit instruction.
    {"country": "AU", "module": "australia", "attr": "_AU_WA_PT_THRESHOLD", "label": "WA Payroll Tax Threshold", "resolverKey": "wa_pt_threshold"},
    {"country": "AU", "module": "australia", "attr": "_AU_WA_PT_UPPER_THRESHOLD", "label": "WA Payroll Tax Upper Threshold", "resolverKey": "wa_pt_upper_threshold"},
    {"country": "AU", "module": "australia", "attr": "_AU_WA_PT_RATE", "label": "WA Payroll Tax Rate", "resolverKey": "wa_pt_rate"},
    {"country": "AU", "module": "australia", "attr": "_AU_QLD_PT_THRESHOLD", "label": "QLD Payroll Tax Threshold", "resolverKey": "qld_pt_threshold"},
    {"country": "AU", "module": "australia", "attr": "_AU_QLD_PT_UPPER_THRESHOLD", "label": "QLD Payroll Tax Deduction Ceiling", "resolverKey": "qld_pt_upper_threshold"},
    {"country": "AU", "module": "australia", "attr": "_AU_QLD_PT_RATE_LOW", "label": "QLD Payroll Tax Rate (≤$6.5m)", "resolverKey": "qld_pt_rate_low"},
    {"country": "AU", "module": "australia", "attr": "_AU_QLD_PT_RATE_HIGH", "label": "QLD Payroll Tax Rate (>$6.5m)", "resolverKey": "qld_pt_rate_high"},
    {"country": "AU", "module": "australia", "attr": "_AU_QLD_PT_RATE_SWITCH", "label": "QLD Payroll Tax Rate Switch Threshold", "resolverKey": "qld_pt_rate_switch"},
    {"country": "AU", "module": "australia", "attr": "_AU_VIC_PT_PHASE_START", "label": "VIC Payroll Tax Deduction Phase-Out Start", "resolverKey": "vic_pt_phase_start"},
    {"country": "AU", "module": "australia", "attr": "_AU_VIC_PT_PHASE_END", "label": "VIC Payroll Tax Deduction Phase-Out End", "resolverKey": "vic_pt_phase_end"},
    {"country": "AU", "module": "australia", "attr": "_AU_VIC_PT_BASE_DEDUCTION", "label": "VIC Payroll Tax Base Deduction", "resolverKey": "vic_pt_base_deduction"},
    {"country": "AU", "module": "australia", "attr": "_AU_VIC_PT_RATE", "label": "VIC Payroll Tax Rate", "resolverKey": "vic_pt_rate"},
    {"country": "AU", "module": "australia", "attr": "_AU_VIC_PT_REGIONAL_RATE", "label": "VIC Payroll Tax Regional Rate", "resolverKey": "vic_pt_regional_rate"},
    {"country": "AU", "module": "australia", "attr": "_AU_NT_PT_THRESHOLD", "label": "NT Payroll Tax Deduction", "resolverKey": "nt_pt_threshold"},
    {"country": "AU", "module": "australia", "attr": "_AU_NT_PT_RATE", "label": "NT Payroll Tax Rate", "resolverKey": "nt_pt_rate"},
    {"country": "AU", "module": "australia", "attr": "_AU_NT_PT_RATE_HIGH", "label": "NT Payroll Tax Rate (≥$100m group wages)", "resolverKey": "nt_pt_rate_high"},
    {"country": "AU", "module": "australia", "attr": "_AU_NT_PT_RATE_SWITCH", "label": "NT Payroll Tax Rate Switch Threshold", "resolverKey": "nt_pt_rate_switch"},
    {"country": "AU", "module": "australia", "attr": "_AU_SA_PT_LOWER_THRESHOLD", "label": "SA Payroll Tax Lower Threshold", "resolverKey": "sa_pt_lower_threshold"},
    {"country": "AU", "module": "australia", "attr": "_AU_SA_PT_UPPER_THRESHOLD", "label": "SA Payroll Tax Upper Threshold", "resolverKey": "sa_pt_upper_threshold"},
    {"country": "AU", "module": "australia", "attr": "_AU_SA_PT_RATE", "label": "SA Payroll Tax Rate (>$1.7m)", "resolverKey": "sa_pt_rate"},

    # ── Canada ───────────────────────────────────────────────────────────
    {"country": "CA", "module": "canada", "attr": "_CA_CPP_YMPE", "label": "CPP Year's Maximum Pensionable Earnings", "resolverKey": "cpp_ympe"},
    {"country": "CA", "module": "canada", "attr": "_CA_CPP_BASIC_EXEMPTION", "label": "CPP Basic Exemption", "resolverKey": "cpp_basic_exemption"},
    {"country": "CA", "module": "canada", "attr": "_CA_EI_MIE", "label": "EI Maximum Insurable Earnings", "resolverKey": "ei_mie"},
    {"country": "CA", "module": "canada", "attr": "_CA_BASIC_PERSONAL_AMOUNT", "label": "Federal Basic Personal Amount", "resolverKey": "basic_personal_amt"},
    {"country": "CA", "module": "canada", "attr": "_CA_CPP2_YAMPE", "label": "CPP2 Year's Additional Maximum Pensionable Earnings", "resolverKey": "cpp2_yampe"},
    {"country": "CA", "module": "canada", "attr": "_CA_CPP2_RATE", "label": "CPP2 Second-Tier Contribution Rate", "resolverKey": "cpp2_rate"},
    {"country": "CA", "module": "canada", "attr": "_CA_BPAF_MIN", "label": "Federal Basic Personal Amount — Minimum (tapered)", "resolverKey": "bpaf_min"},
    {"country": "CA", "module": "canada", "attr": "_CA_BPAF_NI_THRESHOLD_LOW", "label": "BPAF Taper — Net Income Threshold (Low)", "resolverKey": "bpaf_ni_thresh_lo"},
    {"country": "CA", "module": "canada", "attr": "_CA_BPAF_NI_THRESHOLD_HIGH", "label": "BPAF Taper — Net Income Threshold (High)", "resolverKey": "bpaf_ni_thresh_hi"},
    {"country": "CA", "module": "canada", "attr": "_CA_CEA", "label": "Canada Employment Amount (credit)", "resolverKey": "cea"},
    {"country": "CA", "module": "canada", "attr": "_CA_LOWEST_FEDERAL_RATE", "label": "Lowest Federal Rate (credit conversion)", "resolverKey": "lowest_fed_rate"},
    {"country": "CA", "module": "canada", "attr": "_CA_QUEBEC_FEDERAL_ABATEMENT_PCT", "label": "Quebec Federal Abatement", "resolverKey": "qc_fed_abatement", "note": "Configured but not yet applied — awaits the Quebec/POE calculation branch."},
    {"country": "CA", "module": "canada", "attr": "_CA_BEYOND_PROVINCE_SURTAX_PCT", "label": "Beyond-Province Surtax Factor (% of T3)", "resolverKey": "beyond_prov_surtax", "note": "Configured but not yet applied — awaits the CA-XP/POE calculation branch."},
    {"country": "CA", "module": "canada", "attr": "_CA_LSVCC_CREDIT_RATE", "label": "Labour-Sponsored Fund Credit Rate", "resolverKey": "lsvcc_credit_rate", "note": "Configured but not yet applied — no employee LSVCC-investment declaration is captured yet."},
    {"country": "CA", "module": "canada", "attr": "_CA_LSVCC_CREDIT_MAX", "label": "Labour-Sponsored Fund Credit Max", "resolverKey": "lsvcc_credit_max", "note": "Configured but not yet applied — no employee LSVCC-investment declaration is captured yet."},

    # ── Germany ──────────────────────────────────────────────────────────
    # _DE_GRUNDFREIBETRAG, _DE_CONTRIBUTION_CEILING, and _DE_CHURCH_TAX_RATE
    # were retired in Phase 4 along with the legacy calculator that was
    # their only consumer — see hardcoded_defaults.py's Germany section.
    # _DE_SOLI_THRESHOLD/_DE_SOLI_RATE are not resolved through
    # resolve_jurisdiction_parameter, so a required-parameter check must
    # NOT demand a seed row for them. That is not the same as "not
    # configurable": as of Phase 8BY the Soli Freigrenze IS effective-dated
    # through germany/tax.py's `_TARIFF_VERSIONS` (EUR 18,130 for
    # 2023-2025, EUR 20,350 from 2026-01-01 per ZP-TAX-DE-2026-001 §7), and
    # the module constant is only the fallback. The BMF PAP remains the
    # statutorily-mandated Soli oracle (§7 / acceptance #10) and is still
    # gated — see jurisdictions/germany/pap/core.py resolve_pap_executor().
    {"country": "DE", "module": "germany", "attr": "_DE_SOLI_THRESHOLD", "label": "Solidarity Surcharge Freigrenze (effective-dated in germany/tax.py _TARIFF_VERSIONS; BMF PAP is the statutory oracle)", "resolverKey": "N/A — effective-dated by tariff version, not resolve_jurisdiction_parameter"},
    {"country": "DE", "module": "germany", "attr": "_DE_SOLI_RATE", "label": "Solidarity Surcharge Rate (statutory SolzG 5.5% code constant — BMF PAP is the oracle)", "resolverKey": "N/A — not read via resolve_jurisdiction_parameter"},
    {"country": "DE", "module": "germany", "attr": "_DE_RV_EMPLOYEE_RATE", "label": "Pension Insurance (RV) Rate — Employee", "resolverKey": "rv_employee_rate", "side": "employee"},
    {"country": "DE", "module": "germany", "attr": "_DE_RV_EMPLOYER_RATE", "label": "Pension Insurance (RV) Rate — Employer", "resolverKey": "rv_employer_rate", "side": "employer"},
    {"country": "DE", "module": "germany", "attr": "_DE_ALV_EMPLOYEE_RATE", "label": "Unemployment Insurance (ALV) Rate — Employee", "resolverKey": "alv_employee_rate", "side": "employee"},
    {"country": "DE", "module": "germany", "attr": "_DE_ALV_EMPLOYER_RATE", "label": "Unemployment Insurance (ALV) Rate — Employer", "resolverKey": "alv_employer_rate", "side": "employer"},
    {"country": "DE", "module": "germany", "attr": "_DE_GKV_GENERAL_EMPLOYEE_RATE", "label": "Health Insurance (GKV) General Rate — Employee", "resolverKey": "gkv_general_employee_rate", "side": "employee"},
    {"country": "DE", "module": "germany", "attr": "_DE_GKV_GENERAL_EMPLOYER_RATE", "label": "Health Insurance (GKV) General Rate — Employer", "resolverKey": "gkv_general_employer_rate", "side": "employer"},

    # ── France ──────────────────────────────────────────────────────────
    # France statutory values are pack data (ZP-FR-ENG-001 FR-003):
    # engine/countries/france.py resolves every key below from the active
    # France JurisdictionPack's ContributionRate rows (seeded Draft by
    # scripts/seed_france_canonical_packs.py from
    # engine/countries/france_content.py) and BLOCKS when a key has no row —
    # these constants are the published 2026 fallbacks shown for reference.
    # skip_discrepancy_check: France has no legacy per-country seed dict in
    # service.py, so the viewer's seed-vs-engine callout does not apply.
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_PASS_ANNUAL", "label": "PASS — annual Social Security ceiling (2026)", "resolverKey": "fr_pass_annual", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_PASS_MONTHLY", "label": "PMSS — monthly Social Security ceiling (2026)", "resolverKey": "fr_pmss", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_SMIC_2026_HOURLY_JAN_MAY", "label": "SMIC hourly — Jan–May 2026 (dated pack row)", "resolverKey": "fr_smic_hourly", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_SMIC_2026_HOURLY_JUN", "label": "SMIC hourly — from 1 Jun 2026 (dated pack row)", "resolverKey": "fr_smic_hourly", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_SMIC_2026_MONTHLY_JAN_MAY", "label": "SMIC monthly 35h — Jan–May 2026 (dated pack row)", "resolverKey": "fr_smic_monthly", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_SMIC_2026_MONTHLY_JUN", "label": "SMIC monthly 35h — from 1 Jun 2026 (dated pack row)", "resolverKey": "fr_smic_monthly", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_SMIC_2026_ANNUAL_FROZEN", "label": "RGDU SMIC reference — annual (frozen 1 Jan 2026)", "resolverKey": "fr_smic_rgdu_annual", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_SMIC_2026_HOURLY_FROZEN", "label": "RGDU SMIC reference — hourly (frozen 1 Jan 2026)", "resolverKey": "fr_smic_rgdu_hourly", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_SMIC_2026_FULLTIME_HOURS", "label": "Full-time monthly hours (35h × 52 / 12)", "resolverKey": "fr_fulltime_monthly_hours", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_VIEILLESSE_CAPPED_EE", "label": "Old-age capped (PSS) — employee", "resolverKey": "fr_vieillesse_capped_ee", "side": "employee", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_VIEILLESSE_UNCAPPED_EE", "label": "Old-age uncapped (total) — employee", "resolverKey": "fr_vieillesse_uncapped_ee", "side": "employee", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_VIEILLESSE_CAPPED_ER", "label": "Old-age capped (PSS) — employer", "resolverKey": "fr_vieillesse_capped_er", "side": "employer", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_VIEILLESSE_UNCAPPED_ER", "label": "Old-age uncapped (total) — employer", "resolverKey": "fr_vieillesse_uncapped_er", "side": "employer", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_CHOMAGE_ER", "label": "Unemployment — employer (within 4 PASS)", "resolverKey": "fr_chomage_er", "side": "employer", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_AGS_ER", "label": "AGS — employer (within 4 PASS)", "resolverKey": "fr_ags_er", "side": "employer", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_SANTE_ER_STANDARD", "label": "Health — employer, standard rate [PENDING G1]", "resolverKey": "fr_sante_er", "side": "employer", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_SANTE_ER_REDUCED", "label": "Health — employer, reduced rate [PENDING G1]", "resolverKey": "fr_sante_er_reduced", "side": "employer", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_FAMILLE_ER", "label": "Family allowances — employer [PENDING G1]", "resolverKey": "fr_famille_er", "side": "employer", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_CSA_ER_DEFAULT", "label": "CSA — employer [PENDING G1]", "resolverKey": "fr_csa_er", "side": "employer", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_FNAL_ER_0P10", "label": "FNAL — employer, under 50 employees (capped base)", "resolverKey": "fr_fnal_er_0p10", "side": "employer", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_FNAL_ER_0P50", "label": "FNAL — employer, 50+ employees (total pay)", "resolverKey": "fr_fnal_er_0p50", "side": "employer", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_CFP_ER_0P55", "label": "CFP — employer, under 11 employees", "resolverKey": "fr_cfp_er_0p55", "side": "employer", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_CFP_ER_1P00", "label": "CFP — employer, 11+ employees", "resolverKey": "fr_cfp_er_1p00", "side": "employer", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_APPRENTISSAGE_ER", "label": "Apprenticeship tax — main share", "resolverKey": "fr_apprentissage_er", "side": "employer", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_APPRENTISSAGE_BALANCE_ER", "label": "Apprenticeship tax — balance", "resolverKey": "fr_apprentissage_balance_er", "side": "employer", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_AGIRC_T1_EE", "label": "Agirc-Arrco T1 — employee", "resolverKey": "fr_agirc_t1_ee", "side": "employee", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_AGIRC_T1_ER", "label": "Agirc-Arrco T1 — employer", "resolverKey": "fr_agirc_t1_er", "side": "employer", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_AGIRC_T2_EE", "label": "Agirc-Arrco T2 — employee", "resolverKey": "fr_agirc_t2_ee", "side": "employee", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_AGIRC_T2_ER", "label": "Agirc-Arrco T2 — employer", "resolverKey": "fr_agirc_t2_er", "side": "employer", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_CEG_T1_EE", "label": "CEG T1 — employee", "resolverKey": "fr_ceg_t1_ee", "side": "employee", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_CEG_T1_ER", "label": "CEG T1 — employer", "resolverKey": "fr_ceg_t1_er", "side": "employer", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_CEG_T2_EE", "label": "CEG T2 — employee", "resolverKey": "fr_ceg_t2_ee", "side": "employee", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_CEG_T2_ER", "label": "CEG T2 — employer", "resolverKey": "fr_ceg_t2_er", "side": "employer", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_CET_EE", "label": "CET — employee (on T1+T2 when pay exceeds T1)", "resolverKey": "fr_cet_ee", "side": "employee", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_CET_ER", "label": "CET — employer (on T1+T2 when pay exceeds T1)", "resolverKey": "fr_cet_er", "side": "employer", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_APEC_EE", "label": "Apec — employee (cadres, up to 4 PSS)", "resolverKey": "fr_apec_ee", "side": "employee", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_APEC_ER", "label": "Apec — employer (cadres, up to 4 PSS)", "resolverKey": "fr_apec_er", "side": "employer", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_CSG_EE_DEDUCTIBLE", "label": "CSG — deductible part", "resolverKey": "fr_csg_deductible", "side": "employee", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_CSG_EE_NONDEDUCTIBLE", "label": "CSG — non-deductible part", "resolverKey": "fr_csg_nondeductible", "side": "employee", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_CRDS_EE", "label": "CRDS (non-deductible)", "resolverKey": "fr_crds", "side": "employee", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_CSG_BASE_FACTOR_98_25", "label": "CSG/CRDS base factor (98.25%, within cumulative 4 PSS)", "resolverKey": "fr_csg_base_factor", "side": "employee", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_RGDU_TMIN", "label": "RGDU — Tmin (stored as % in the pack: 2.00 = 0.0200)", "resolverKey": "fr_rgdu_tmin", "side": "employer", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_RGDU_TDELTA_FNAL_0P10", "label": "RGDU — Tdelta, under 50 employees (pack %: 37.81)", "resolverKey": "fr_rgdu_tdelta_lt50", "side": "employer", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_RGDU_TDELTA_FNAL_0P50", "label": "RGDU — Tdelta, 50+ employees (pack %: 38.21)", "resolverKey": "fr_rgdu_tdelta_ge50", "side": "employer", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_RGDU_POWER", "label": "RGDU — exponent", "resolverKey": "fr_rgdu_power", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_RGDU_ELIGIBILITY_MULTIPLE", "label": "RGDU — eligibility envelope (× SMIC)", "resolverKey": "fr_rgdu_smic_multiple", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_PAS_SHORT_CONTRACT_ABATEMENT", "label": "PAS — short-contract base abatement (€ amount)", "resolverKey": "fr_pas_short_contract_abatement", "skip_discrepancy_check": True},
    {"country": "FR", "module": "hardcoded_defaults", "attr": "_FR_PAS_APPRENTICE_THRESHOLD", "label": "PAS — apprentice exemption threshold (€ / year)", "resolverKey": "fr_pas_apprentice_threshold", "skip_discrepancy_check": True},
    # ── Singapore ────────────────────────────────────────────────────────
    # Fail-closed: every constant below is None — listed only so the
    # readiness check (get_required_parameter_keys) knows which keys a
    # Singapore pack must configure. CPF/SHG band tables (CPF_RATE_BAND/
    # SHG_FUND_BAND TaxSlab rows) have no scalar key and are validated by
    # singapore.py itself.
    {"country": "SG", "module": "singapore", "attr": "_SG_CPF_OW_CEILING_MONTHLY", "label": "CPF Ordinary Wage Ceiling (Monthly)", "resolverKey": "cpf_ow_ceiling_monthly", "note": "NO FALLBACK — Singapore is fail-closed (ZP-SG-ENG-001 SG-001); a missing row BLOCKS the calculation."},
    {"country": "SG", "module": "singapore", "attr": "_SG_CPF_ANNUAL_WAGE_CEILING", "label": "CPF Annual Wage Ceiling", "resolverKey": "cpf_annual_wage_ceiling", "note": "NO FALLBACK — Singapore is fail-closed (ZP-SG-ENG-001 SG-001); a missing row BLOCKS the calculation."},
    {"country": "SG", "module": "singapore", "attr": "_SG_SDL_RATE", "label": "Skills Development Levy Rate (Employer)", "resolverKey": "sdl", "side": "employer", "note": "NO FALLBACK — Singapore is fail-closed (ZP-SG-ENG-001 SG-001); a missing row BLOCKS the calculation."},
    {"country": "SG", "module": "singapore", "attr": "_SG_SDL_MIN_MONTHLY", "label": "SDL Minimum (Monthly)", "resolverKey": "sdl_min_monthly", "note": "NO FALLBACK — Singapore is fail-closed (ZP-SG-ENG-001 SG-001); a missing row BLOCKS the calculation."},
    {"country": "SG", "module": "singapore", "attr": "_SG_SDL_MAX_MONTHLY", "label": "SDL Maximum (Monthly)", "resolverKey": "sdl_max_monthly", "note": "NO FALLBACK — Singapore is fail-closed (ZP-SG-ENG-001 SG-001); a missing row BLOCKS the calculation."},

    # ── Hong Kong ────────────────────────────────────────────────────────
    # Fail-closed (ZP-HK-ENG-001): every constant is None; listed so the
    # readiness check knows which scalar keys an HK pack must carry. SMW,
    # continuous-contract, EO and SP/LSP rows are validated by the HK
    # modules themselves (a missing row BLOCKS there).
    {"country": "HK", "module": "hong_kong", "attr": "_HK_MPF_EMPLOYEE_RATE", "label": "MPF Employee Mandatory Rate", "resolverKey": "mpf_employee_rate", "side": "employee", "note": "NO FALLBACK — Hong Kong is fail-closed (ZP-HK-ENG-001); a missing row BLOCKS the calculation."},
    {"country": "HK", "module": "hong_kong", "attr": "_HK_MPF_EMPLOYER_RATE", "label": "MPF Employer Mandatory Rate", "resolverKey": "mpf_employer_rate", "side": "employer", "note": "NO FALLBACK — Hong Kong is fail-closed (ZP-HK-ENG-001); a missing row BLOCKS the calculation."},
    {"country": "HK", "module": "hong_kong", "attr": "_HK_MPF_MIN_RI_MONTHLY", "label": "MPF Minimum Relevant Income (Monthly)", "resolverKey": "mpf_min_relevant_income_monthly", "note": "NO FALLBACK — Hong Kong is fail-closed (ZP-HK-ENG-001); a missing row BLOCKS the calculation."},
    {"country": "HK", "module": "hong_kong", "attr": "_HK_MPF_MAX_RI_MONTHLY", "label": "MPF Maximum Relevant Income (Monthly)", "resolverKey": "mpf_max_relevant_income_monthly", "note": "NO FALLBACK — Hong Kong is fail-closed (ZP-HK-ENG-001); a missing row BLOCKS the calculation."},
    {"country": "HK", "module": "hong_kong", "attr": "_HK_MPF_MIN_RI_DAILY", "label": "MPF Minimum Relevant Income (Daily)", "resolverKey": "mpf_min_relevant_income_daily", "note": "NO FALLBACK — Hong Kong is fail-closed (ZP-HK-ENG-001); a missing row BLOCKS the calculation."},
    {"country": "HK", "module": "hong_kong", "attr": "_HK_MPF_MAX_RI_DAILY", "label": "MPF Maximum Relevant Income (Daily)", "resolverKey": "mpf_max_relevant_income_daily", "note": "NO FALLBACK — Hong Kong is fail-closed (ZP-HK-ENG-001); a missing row BLOCKS the calculation."},
    # ── Sweden ────────────────────────────────────────────────────────────
    # Fail-closed from day one (ZP-SE-ENG-001 §30 + shared.py's
    # _VALIDATION_ENABLED_COUNTRIES): every constant below is None —
    # listed only so the readiness check (get_required_parameter_keys)
    # knows which keys a Sweden pack must configure. The seven component
    # rows sum to the standard employer rate; the tax-table/one-time
    # TaxSlab bands have no scalar key and are validated by sweden.py
    # itself. se_vacation_percentage / se_sick_qualifying_deduction_pct
    # are leave/sick-workspace content (not engine-calculate reads), so
    # they are deliberately NOT registered as required here.
    {"country": "SE", "module": "sweden", "attr": "_SE_ER_AGE_PENSION", "label": "Age Pension Component (Employer)", "resolverKey": "se_er_age_pension", "side": "employer", "note": "NO FALLBACK — Sweden is fail-closed (ZP-SE-ENG-001 §6); a missing row BLOCKS the calculation."},
    {"country": "SE", "module": "sweden", "attr": "_SE_ER_HEALTH_INSURANCE", "label": "Health Insurance Component (Employer)", "resolverKey": "se_er_health_insurance", "side": "employer", "note": "NO FALLBACK — Sweden is fail-closed (ZP-SE-ENG-001 §6); a missing row BLOCKS the calculation."},
    {"country": "SE", "module": "sweden", "attr": "_SE_ER_PARENTAL_INSURANCE", "label": "Parental Insurance Component (Employer)", "resolverKey": "se_er_parental_insurance", "side": "employer", "note": "NO FALLBACK — Sweden is fail-closed (ZP-SE-ENG-001 §6); a missing row BLOCKS the calculation."},
    {"country": "SE", "module": "sweden", "attr": "_SE_ER_LABOUR_MARKET", "label": "Labour Market Component (Employer)", "resolverKey": "se_er_labour_market", "side": "employer", "note": "NO FALLBACK — Sweden is fail-closed (ZP-SE-ENG-001 §6); a missing row BLOCKS the calculation."},
    {"country": "SE", "module": "sweden", "attr": "_SE_ER_WORK_INJURY", "label": "Work Injury Component (Employer)", "resolverKey": "se_er_work_injury", "side": "employer", "note": "NO FALLBACK — Sweden is fail-closed (ZP-SE-ENG-001 §6); a missing row BLOCKS the calculation."},
    {"country": "SE", "module": "sweden", "attr": "_SE_ER_SURVIVOR_PENSION", "label": "Survivor Pension Component (Employer)", "resolverKey": "se_er_survivor_pension", "side": "employer", "note": "NO FALLBACK — Sweden is fail-closed (ZP-SE-ENG-001 §6); a missing row BLOCKS the calculation."},
    {"country": "SE", "module": "sweden", "attr": "_SE_ER_GENERAL_PAYROLL_TAX", "label": "General Payroll Tax Component (Employer)", "resolverKey": "se_er_general_payroll_tax", "side": "employer", "note": "NO FALLBACK — Sweden is fail-closed (ZP-SE-ENG-001 §6); a missing row BLOCKS the calculation."},
    {"country": "SE", "module": "sweden", "attr": "_SE_YOUTH_REDUCED", "label": "Temporary Youth Reduced Employer Rate", "resolverKey": "se_youth_reduced", "side": "employer", "required": False, "note": "NO FALLBACK — windowed 1 Apr 2026 – 30 Sep 2027 on the row's own effective dates (ZP-SE-ENG-001 §3/§6)."},
    {"country": "SE", "module": "sweden", "attr": "_SE_SINK", "label": "SINK Withholding Rate (Employee)", "resolverKey": "se_sink", "side": "employee", "note": "NO FALLBACK — 22.5% for 2026, enacted 20% from 2027; date switch is pack/row governed (ZP-SE-ENG-001 §3 [S5])."},
    {"country": "SE", "module": "sweden", "attr": "_SE_SUPPLEMENTARY_RATE", "label": "Supplementary Income Withholding Rate", "resolverKey": "se_supplementary_rate", "side": "employee", "note": "NO FALLBACK — the 30% path, never blended with the main-income table (ZP-SE-ENG-001 §3 [S3])."},
    {"country": "SE", "module": "sweden", "attr": "_SE_SLP", "label": "Special Payroll Tax on Pension Costs (SLP)", "resolverKey": "se_slp", "side": "employer", "note": "NO FALLBACK — 24.26% of the employer pension-cost ledger, never of employee gross (ZP-SE-ENG-001 SE-007)."},
    {"country": "SE", "module": "sweden", "attr": "_SE_YOUTH_MONTHLY_THRESHOLD", "label": "Youth Relief Monthly Threshold (SEK)", "resolverKey": "se_youth_monthly_threshold", "required": False, "note": "NO FALLBACK — window-conditional with se_youth_reduced; — SEK 25,000 per person per calendar month (ZP-SE-ENG-001 §3)."},
    {"country": "SE", "module": "sweden", "attr": "_SE_OLDER_COHORT_MAX_BIRTH_YEAR", "label": "Older-Worker Cohort — Maximum Birth Year", "resolverKey": "se_older_cohort_max_birth_year", "note": "NO FALLBACK — income-year content (2026: born 1938–1958 pay only the age-pension component); Super Admin updates it per income year."},
    {"country": "SE", "module": "sweden", "attr": "_SE_ZERO_COHORT_MAX_BIRTH_YEAR", "label": "Zero-Rate Cohort — Maximum Birth Year", "resolverKey": "se_zero_cohort_max_birth_year", "note": "NO FALLBACK — income-year content (2026: born 1937 or earlier pay 0%); Super Admin updates it per income year."},

    # ── Italy ─────────────────────────────────────────────────────────────
    # Fail-closed from day one (ZP-IT-ENG-001 §30 + shared.py's
    # _VALIDATION_ENABLED_COUNTRIES): every constant below is None — listed
    # only so the readiness check knows which keys an Italian pack must
    # configure. Italy's INPS matrix is NOT a flat rate per component: rates
    # are ContributionRate rows keyed on jurisdiction_state='CSC_<csc>_CA_<ca>'
    # with tax_regime = worker class, so the matrix itself has no scalar key and
    # is validated by italy.py at calculation time (IT-002: an unconfigured
    # combination BLOCKS rather than falling back to a generic rate).
    #
    # The keys registered here are therefore only the genuinely scalar,
    # whole-of-population parameters — the eleven in italy.IT_PARAMETER_KEYS.
    # Everything else is deliberately absent:
    #   * the INPS IVS/CIGS rates exist only as classification-scoped rows
    #     (jurisdiction_state = "CSC_<csc>" / "CSC_<csc>_CA_<ca>", tax_regime =
    #     worker class). Registering one national key as "required" would
    #     invite exactly the generic fallback IT-002 forbids.
    #   * IRPEF brackets, the §4 deduction/wedge bands and the §5 local surtax
    #     bands are TaxSlab rows keyed by tax_table_number, with no scalar key
    #     — the same exclusion Sweden makes for its tax-table bands. A locality
    #     readiness check should verify domicile COVERAGE, not one flat rate.
    {"country": "IT", "module": "italy", "attr": "_IT_IVS_ADDITIONAL_PCT", "label": "Additional 1% IVS (Employee)", "resolverKey": "it_ivs_additional_pct", "side": "employee", "note": "NO FALLBACK — cumulative above the annual retribution band (ZP-IT-ENG-001 §6 / IT-016); a missing row BLOCKS."},
    {"country": "IT", "module": "italy", "attr": "_IT_IVS_ADDITIONAL_THRESHOLD", "label": "Additional 1% IVS Annual Threshold", "resolverKey": "it_ivs_additional_threshold", "note": "NO FALLBACK — EUR 56,224 for 2026 (§6); threshold content, never a default."},
    {"country": "IT", "module": "italy", "attr": "_IT_CONTRIBUTORY_CEILING", "label": "Annual Contributory Maximum (cohort only)", "resolverKey": "it_contributory_ceiling", "note": "NO FALLBACK — EUR 122,295 for 2026; applied ONLY with cap-cohort evidence (IT-017), never because income is high."},
    {"country": "IT", "module": "italy", "attr": "_IT_TFR_DIVISOR", "label": "TFR Accrual Divisor", "resolverKey": "it_tfr_divisor", "note": "NO FALLBACK — qualifying annual remuneration / 13.5 (§13 / Codice civile art. 2120)."},
    {"country": "IT", "module": "italy", "attr": "_IT_TFR_INPS_OFFSET", "label": "TFR 0.50% INPS Offset", "resolverKey": "it_tfr_inps_offset", "side": "employer", "note": "NO FALLBACK — needs source (L. 297/1982 art. 3); kept as content so the statutory review can correct it without a code change."},
    {"country": "IT", "module": "italy", "attr": "_IT_TESORERIA_HEADCOUNT_THRESHOLD", "label": "Fondo Tesoreria Prior-Year Headcount Threshold", "resolverKey": "it_tesoreria_headcount_threshold", "note": "NO FALLBACK — 60 for 2026-2027, 50 for 2028-2031, 40 from 2032 (§14); determined from the PRIOR-YEAR average (IT-040), never current headcount."},
    {"country": "IT", "module": "italy", "attr": "_IT_DETRAZIONE_MIN_PERMANENT", "label": "Detrazione Lavoro Floor (Permanent Contract)", "resolverKey": "it_detrazione_min_permanent", "note": "NO FALLBACK — needs source (TUIR art. 13); contract-type dependent, so a single default would misstate one of the two cases."},
    {"country": "IT", "module": "italy", "attr": "_IT_DETRAZIONE_MIN_FIXED_TERM", "label": "Detrazione Lavoro Floor (Fixed-Term Contract)", "resolverKey": "it_detrazione_min_fixed_term", "note": "NO FALLBACK — needs source (TUIR art. 13)."},
    {"country": "IT", "module": "italy", "attr": "_IT_MENSILITA_DEFAULT", "label": "Default Mensilita per Year", "resolverKey": "it_mensilita_default", "note": "NO FALLBACK — default 13 until CCNL content lands; a CCNL override is supplied per worker by the service, never a default here."},
    {"country": "IT", "module": "italy", "attr": "_IT_FIS_SMALL_EMPLOYER", "label": "FIS (employers with up to 5 employees)", "resolverKey": "it_fis_small_employer", "side": "employer", "note": "NO FALLBACK — 0.50% total split two-thirds employer / one-third employee where the fund applies (§7 / IT-020); sector funds differ."},
    {"country": "IT", "module": "italy", "attr": "_IT_FIS_LARGE_EMPLOYER", "label": "FIS (employers with more than 5 employees)", "resolverKey": "it_fis_large_employer", "side": "employer", "note": "NO FALLBACK — 0.80% total on the same two-thirds/one-third split (§7 / IT-020)."},
    {"country": "IT", "module": "italy", "attr": "_IT_ADDREG_SALDO_FIRST_MONTH", "label": "Regional Surtax Balance — First Instalment Month", "resolverKey": "it_addreg_saldo_first_month", "note": "NO FALLBACK — pay month opening the prior-year regional balance instalments (§5); a missing row BLOCKS."},
    {"country": "IT", "module": "italy", "attr": "_IT_ADDREG_SALDO_LAST_MONTH", "label": "Regional Surtax Balance — Last Instalment Month", "resolverKey": "it_addreg_saldo_last_month", "note": "NO FALLBACK — last instalment month (November under D.Lgs. 446/1997 art. 50, pending G1 review)."},
    {"country": "IT", "module": "italy", "attr": "_IT_ADDCOM_SALDO_FIRST_MONTH", "label": "Municipal Surtax Balance — First Instalment Month", "resolverKey": "it_addcom_saldo_first_month", "note": "NO FALLBACK — same schedule as the regional balance (§5)."},
    {"country": "IT", "module": "italy", "attr": "_IT_ADDCOM_SALDO_LAST_MONTH", "label": "Municipal Surtax Balance — Last Instalment Month", "resolverKey": "it_addcom_saldo_last_month", "note": "NO FALLBACK — last instalment month for the municipal balance (§5)."},
    {"country": "IT", "module": "italy", "attr": "_IT_ADDCOM_ACCONTO_PCT", "label": "Municipal Surtax Advance (% of prior-year amount)", "resolverKey": "it_addcom_acconto_pct", "side": "employee", "note": "NO FALLBACK — 30% under D.Lgs. 360/1998 art. 1, pending G1 review; determined once a year, withheld separately from the balance (§5)."},
    {"country": "IT", "module": "italy", "attr": "_IT_ADDCOM_ACCONTO_FIRST_MONTH", "label": "Municipal Surtax Advance — First Instalment Month", "resolverKey": "it_addcom_acconto_first_month", "note": "NO FALLBACK — March under D.Lgs. 360/1998 art. 1, pending G1 review."},
    {"country": "IT", "module": "italy", "attr": "_IT_ADDCOM_ACCONTO_LAST_MONTH", "label": "Municipal Surtax Advance — Last Instalment Month", "resolverKey": "it_addcom_acconto_last_month", "note": "NO FALLBACK — November under D.Lgs. 360/1998 art. 1, pending G1 review."},
    {"country": "IT", "module": "italy", "attr": "_IT_INPS_DAILY_MINIMUM", "label": "INPS Contributory Daily Minimum", "resolverKey": "it_inps_daily_minimum", "note": "NO FALLBACK — EUR 58.13 for 2026 (§2/§6). Raises the INPS base only; it is NOT a minimum wage (IT-004)."},
    {"country": "IT", "module": "italy", "attr": "_IT_INPS_FULL_MONTH_DAYS", "label": "Contributory Days in a Full Month", "resolverKey": "it_inps_full_month_days", "note": "NO FALLBACK — 26 for monthly-paid workers, pending G1 review."},
    {"country": "IT", "module": "italy", "attr": "_IT_INPS_PARTTIME_HOURLY_FACTOR", "label": "Part-time Hourly Minimum Factor", "resolverKey": "it_inps_parttime_hourly_factor", "note": "NO FALLBACK — hourly minimum = daily minimum x factor / CCNL weekly hours (IT-018), never / 8."},
    {"country": "IT", "module": "italy", "attr": "_IT_FRINGE_EXEMPT_LIMIT", "label": "Fringe Benefits Annual Exemption", "resolverKey": "it_fringe_exempt_limit", "note": "NO FALLBACK — EUR 1,000 (2025-2027); crossing it makes the WHOLE amount taxable (IT-031)."},
    {"country": "IT", "module": "italy", "attr": "_IT_FRINGE_EXEMPT_LIMIT_CHILDREN", "label": "Fringe Benefits Annual Exemption (child declaration)", "resolverKey": "it_fringe_exempt_limit_children", "note": "NO FALLBACK — EUR 2,000, only with the employee's own declaration (IT-032)."},
    {"country": "IT", "module": "italy", "attr": "_IT_MEAL_ELECTRONIC_EXEMPT", "label": "Electronic Meal Voucher Exemption (per voucher)", "resolverKey": "it_meal_electronic_exempt", "note": "NO FALLBACK — EUR 10 per electronic voucher in 2026 (§11)."},
    {"country": "IT", "module": "italy", "attr": "_IT_MEAL_PAPER_EXEMPT", "label": "Paper Meal Voucher Exemption (per voucher)", "resolverKey": "it_meal_paper_exempt", "note": "NO FALLBACK — separate limit, never the electronic one (§11), pending G1 review."},
    {"country": "IT", "module": "italy", "attr": "_IT_WEDGE_RECOVERY_THRESHOLD", "label": "Wedge Sum Recovery Instalment Threshold", "resolverKey": "it_wedge_recovery_threshold", "note": "NO FALLBACK — a recovery above EUR 60 is spread over instalments (IT-011)."},
    {"country": "IT", "module": "italy", "attr": "_IT_WEDGE_RECOVERY_INSTALMENTS", "label": "Wedge Sum Recovery Instalments", "resolverKey": "it_wedge_recovery_instalments", "note": "NO FALLBACK — ten equal instalments from the first affected pay (IT-011)."},
    {"country": "IT", "module": "italy", "attr": "_IT_TFR_REVALUATION_FIXED_PCT", "label": "TFR Revaluation — Fixed Part", "resolverKey": "it_tfr_revaluation_fixed_pct", "side": "employer", "note": "NO FALLBACK — 1.5% a year, pro-rated by month (§13 / c.c. art. 2120)."},
    {"country": "IT", "module": "italy", "attr": "_IT_TFR_REVALUATION_ISTAT_SHARE", "label": "TFR Revaluation — Share of ISTAT FOI Increase", "resolverKey": "it_tfr_revaluation_istat_share", "side": "employer", "note": "NO FALLBACK — 75% of the ISTAT FOI increase (§13); the index itself is authority data supplied per run."},
    {"country": "IT", "module": "italy", "attr": "_IT_TFR_REVALUATION_TAX_PCT", "label": "TFR Revaluation — Substitute Tax", "resolverKey": "it_tfr_revaluation_tax_pct", "side": "employee", "note": "NO FALLBACK — 17%, pending G1 review."},

    # ── Switzerland ──────────────────────────────────────────────────────────
    # Fail-closed from day one (CH spec + shared.py's _VALIDATION_ENABLED_COUNTRIES):
    # every constant below is None — listed so the readiness check knows which
    # keys a Swiss federal pack must configure. Switzerland has NO engine fallback;
    # a missing row BLOCKS the calculation. Canton-scaffold keys are not registered
    # here (they are inert NULL rows on canton packs until the canton publishes).
    {"country": "CH", "module": "switzerland", "attr": "CH_PARAMETER_KEYS", "label": "Federal AHV Rate (Employee/Employer)", "resolverKey": "ch_ahv", "side": "employee", "note": "NO FALLBACK — federal AHV 8.7% (4.35%/4.35%) from Active CH-PAYROLL-2026 pack; a missing row BLOCKS."},
    {"country": "CH", "module": "switzerland", "attr": "CH_PARAMETER_KEYS", "label": "Federal IV Rate (Employee/Employer)", "resolverKey": "ch_iv", "side": "employee", "note": "NO FALLBACK — federal IV 1.4% (0.70%/0.70%) from Active CH-PAYROLL-2026 pack; a missing row BLOCKS."},
    {"country": "CH", "module": "switzerland", "attr": "CH_PARAMETER_KEYS", "label": "Federal EO Rate (Employee/Employer)", "resolverKey": "ch_eo", "side": "employee", "note": "NO FALLBACK — federal EO 0.5% (0.25%/0.25%) from Active CH-PAYROLL-2026 pack; a missing row BLOCKS."},
    {"country": "CH", "module": "switzerland", "attr": "CH_PARAMETER_KEYS", "label": "Federal ALV Rate (Employee/Employer)", "resolverKey": "ch_alv", "side": "employee", "note": "NO FALLBACK — federal ALV 2.2% (1.10%/1.10%) from Active CH-PAYROLL-2026 pack; a missing row BLOCKS."},
    {"country": "CH", "module": "switzerland", "attr": "CH_PARAMETER_KEYS", "label": "ALV Max Insured Annual Salary", "resolverKey": "ch_alv_ceiling", "note": "NO FALLBACK — CHF 148,200 from Active federal pack; ALV cap with YTD accumulator."},
    {"country": "CH", "module": "switzerland", "attr": "CH_PARAMETER_KEYS", "label": "Compensation Office Admin Cost %", "resolverKey": "ch_admin_cost_pct", "side": "employer", "note": "NO FALLBACK — from LIVE COMPENSATION_OFFICE scheme rules; employer-only line."},
    {"country": "CH", "module": "switzerland", "attr": "CH_PARAMETER_KEYS", "label": "ALV Proration Method", "resolverKey": "ch_alv_proration_rule", "note": "NO FALLBACK — 'monthly' or 'annual' from content rule; determines cap tracking."},
    {"country": "CH", "module": "switzerland", "attr": "CH_PARAMETER_KEYS", "label": "FAK Federal Child Minimum (Monthly)", "resolverKey": "ch_fak_child_min", "note": "NO FALLBACK — CHF 215 from Active federal pack; added to net pay."},
    {"country": "CH", "module": "switzerland", "attr": "CH_PARAMETER_KEYS", "label": "FAK Federal Education Minimum (Monthly)", "resolverKey": "ch_fak_education_min", "note": "NO FALLBACK — CHF 268 from Active federal pack; added to net pay."},
    {"country": "CH", "module": "switzerland", "attr": "CH_PARAMETER_KEYS", "label": "BVG Entry Threshold (Annual)", "resolverKey": "ch_bvg_entry_threshold", "note": "NO FALLBACK — BVG Eintrittsschwelle CHF 22,680 (2026) from Active federal pack; annual salary at/above it and age 17+ makes a worker BVG-insured."},
    {"country": "CH", "module": "switzerland", "attr": "CH_PARAMETER_KEYS", "label": "BVG Coordination Deduction (Annual)", "resolverKey": "ch_bvg_coordination_deduction", "note": "NO FALLBACK — BVG Koordinationsabzug CHF 26,460 (2026) from Active federal pack; deducted from annual salary for the coordinated (insured) salary."},
    {"country": "CH", "module": "switzerland", "attr": "CH_PARAMETER_KEYS", "label": "BVG Upper Insurable Salary (Annual)", "resolverKey": "ch_bvg_upper_salary", "note": "NO FALLBACK — max mandatory-BVG annual insurable salary CHF 90,720 (2026) from Active federal pack; compensation above it is only insurable via EXTRA_MANDATORY."},
    {"country": "CH", "module": "switzerland", "attr": "CH_PARAMETER_KEYS", "label": "BVG Minimum Coordinated Salary (Annual)", "resolverKey": "ch_bvg_min_coordinated", "note": "NO FALLBACK — statutory minimum coordinated salary CHF 3,780 (2026) from Active federal pack; a low coordinated result is floored here."},
    {"country": "CH", "module": "switzerland", "attr": "CH_PARAMETER_KEYS", "label": "Swiss Rounding Rule", "resolverKey": "ch_rounding_rule", "note": "NO FALLBACK — nearest CHF 0.05 (5 Rappen) from Active federal pack."},
]


def get_required_parameter_keys(country: str) -> list[dict]:
    """The generic, per-jurisdiction list of resolver keys the engine
    actually reads via resolve_jurisdiction_parameter for this country —
    derived live from _ENGINE_CONSTANT_REGISTRY (the same metadata that
    already powers the Super Admin 'Engine Fallback Defaults' viewer
    above), not a second, hand-maintained catalog. Adding a required
    parameter for a country means adding one registry row, same as it
    already does today for that viewer.

    Compound `resolverKey` values (e.g. UK's student loan plans — one
    registry row covering 5 distinct keys) are split into individual
    entries. Entries whose resolverKey isn't actually resolver-backed
    (marked "N/A..." — a pure code constant with no DB counterpart at
    all) are excluded, since a readiness check has nothing to verify for
    them. Deduplicates by (key, side) — India's Old/New Regime variants of
    the same parameter collapse to one required entry, since at runtime
    there is only ever one "standard_deduction" key being resolved,
    regardless of which regime's hardcoded default backs it."""
    seen = set()
    required = []
    for entry in _ENGINE_CONSTANT_REGISTRY:
        if entry["country"] != country:
            continue
        resolver_key = entry["resolverKey"]
        if resolver_key.startswith("N/A"):
            continue
        # Window-conditional content (e.g. Sweden's temporary youth relief,
        # present only for payment dates inside its statutory window) is
        # listed for the viewer but is not a readiness requirement: the
        # date-filtered resolver legitimately omits it outside the window,
        # and the engine itself blocks on a half-configured window.
        if entry.get("required") is False:
            continue
        side = entry.get("side")
        for key in (k.strip() for k in resolver_key.split("/")):
            dedupe_key = (key, side)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            required.append({
                "key": key,
                "side": side,
                "label": entry["label"],
                "constantName": entry["attr"],
            })
    return required


def _jsonable(value):
    """Recursively converts Decimal (and tuples/dicts containing them) into
    plain JSON-safe types, without altering the live constant object itself."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def get_engine_fallback_inventory() -> dict:
    """Read-only snapshot for the Super Admin 'Engine Fallback Defaults'
    viewer. Every engineConstants[].value is read live via getattr — never a
    literal copied into this file — so the page can't drift from the real
    constant. seeded.* are the actual seed dicts from service.py, imported
    directly (zero duplication, not modified)."""
    from app.modules.payroll.service import _CONTRIBUTION_RATES_BY_COUNTRY, _TAX_SLABS_BY_COUNTRY

    engine_constants = []
    for entry in _ENGINE_CONSTANT_REGISTRY:
        module = _MODULES[entry["module"]]
        raw_value = getattr(module, entry["attr"], None)
        engine_constants.append({
            "country": entry["country"],
            "constantName": entry["attr"],
            "label": entry["label"],
            "resolverKey": entry["resolverKey"],
            "kind": entry.get("kind", "scalar"),
            "value": _jsonable(raw_value),
            "note": entry.get("note"),
            "skipDiscrepancyCheck": entry.get("skip_discrepancy_check", False),
            "side": entry.get("side"),
        })

    def _rate_row(country, row):
        return {
            "componentKey": row.get("component_key"),
            "label": row.get("label"),
            "employeeRatePct": _jsonable(row.get("employee_rate_pct")),
            "employerRatePct": _jsonable(row.get("employer_rate_pct")),
            "flatAmount": _jsonable(row.get("flat_amount")),
        }

    def _slab_row(row):
        return {
            "minAmount": _jsonable(row.get("min_amount")),
            "maxAmount": _jsonable(row.get("max_amount")),
            "ratePct": _jsonable(row.get("rate_pct")),
            "rateLabel": row.get("rate_label"),
        }

    seeded_contribution_rates = {
        country: [_rate_row(country, r) for r in rows]
        for country, rows in _CONTRIBUTION_RATES_BY_COUNTRY.items()
    }
    seeded_tax_slabs = {
        country: [_slab_row(s) for s in rows]
        for country, rows in _TAX_SLABS_BY_COUNTRY.items()
    }

    return {
        "seeded": {"contributionRates": seeded_contribution_rates, "taxSlabs": seeded_tax_slabs},
        "engineConstants": engine_constants,
    }
