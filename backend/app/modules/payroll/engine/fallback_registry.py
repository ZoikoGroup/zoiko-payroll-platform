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

from app.modules.payroll.engine.countries import australia, canada, germany, india, uk, us

_MODULES = {
    "india": india,
    "us": us,
    "uk": uk,
    "australia": australia,
    "canada": canada,
    "germany": germany,
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
