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
    {"country": "AU", "module": "australia", "attr": "_AU_MEDICARE_LEVY_LOW_INCOME_THRESHOLD", "label": "Medicare Levy Low-Income Threshold", "resolverKey": "medicare_low_inc_thr"},
    {"country": "AU", "module": "australia", "attr": "_AU_MLS_THRESHOLD", "label": "Medicare Levy Surcharge Threshold", "resolverKey": "mls_threshold"},
    {"country": "AU", "module": "australia", "attr": "_AU_MLS_RATE", "label": "Medicare Levy Surcharge Rate", "resolverKey": "mls_rate"},
    {"country": "AU", "module": "australia", "attr": "_AU_SUPER_MAX_CONTRIBUTION_BASE", "label": "Superannuation Guarantee Max Contribution Base", "resolverKey": "super_max_contrib"},
    {"country": "AU", "module": "australia", "attr": "_AU_HELP_THRESHOLD", "label": "HELP/HECS Repayment Threshold", "resolverKey": "help_threshold"},
    {"country": "AU", "module": "australia", "attr": "_AU_HELP_RATE", "label": "HELP/HECS Repayment Rate", "resolverKey": "help_rate"},

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
    {"country": "DE", "module": "germany", "attr": "_DE_GRUNDFREIBETRAG", "label": "Basic Tax-Free Allowance (Grundfreibetrag)", "resolverKey": "grundfreibetrag"},
    {"country": "DE", "module": "germany", "attr": "_DE_CONTRIBUTION_CEILING", "label": "Social Insurance Contribution Ceiling", "resolverKey": "contribution_ceiling"},
    {"country": "DE", "module": "germany", "attr": "_DE_SOLI_THRESHOLD", "label": "Solidarity Surcharge Threshold", "resolverKey": "soli_threshold"},
    {"country": "DE", "module": "germany", "attr": "_DE_SOLI_RATE", "label": "Solidarity Surcharge Rate", "resolverKey": "soli_rate"},
    {"country": "DE", "module": "germany", "attr": "_DE_CHURCH_TAX_RATE", "label": "Church Tax Rate (Kirchensteuer, representative default)", "resolverKey": "church_tax_rate"},
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
