"""
modules/payroll/hardcoded_defaults.py
--------------------------------------
The single, consolidated home for every hardcoded fallback/statutory
default value used anywhere in the payroll module. Previously these were
scattered across three separate locations: service.py's two org-seed
dicts, six separate engine/countries/*.py files' own module-level
constants, and policy/models.py's column defaults. All of it now lives
here — DO NOT add a new hardcoded Decimal/threshold/rate anywhere else in
the payroll module; add it to this file and import it from there.

Plain Python only (Decimal/dict/int) — deliberately zero SQLAlchemy/ORM
imports, no app.database — so this file stays safely importable from the
engine layer (which is itself deliberately isolated from the ORM, see
engine/countries/shared.py's own docstring), the service layer, and the
policy model layer alike.

Every name below is imported back into its ORIGINAL file under its exact
original name (e.g. `from .hardcoded_defaults import _US_STANDARD_DEDUCTION`
inside engine/countries/us.py) — nothing else changes. Every existing
consumer that imports these names FROM those original files (e.g.
engine/standard.py's backward-compat re-exports, engine/fallback_registry.py's
live getattr reads, and several tests that import a country constant
directly from its engine/countries/*.py file) keeps working unchanged,
since Python's import binding makes an imported name a real attribute of
the importing module regardless of where it was originally defined.
"""

from decimal import Decimal


# ═════════════════════════════════════════════════════════════════════
# Org-seed data (previously service.py) — used to populate real
# ContributionRate/TaxSlab DB rows, either on first-use org seeding or
# when Super Admin's canonical packs get seeded via
# scripts/populate_canonical_tax_v1.py.
# ═════════════════════════════════════════════════════════════════════

_CONTRIBUTION_RATES_BY_COUNTRY = {
    "IN": [
        dict(component_key="pf", label="Employee Provident Fund (EPF)",
             employee_share="12% of Basic", employer_share="12% of Basic", total="24% of Basic",
             employee_rate_pct=Decimal("12.00"), employer_rate_pct=Decimal("12.00"), sort_order=1),
        dict(component_key="esi", label="Employee State Insurance (ESI)",
             employee_share="0.75% of Gross", employer_share="3.25% of Gross", total="4% of Gross",
             employee_rate_pct=Decimal("0.75"), employer_rate_pct=Decimal("3.25"), sort_order=2),
        dict(component_key="pt", label="Professional Tax (PT)",
             employee_share="₹200/month (fixed)", employer_share="—", total="₹200",
             flat_amount=Decimal("200.00"), sort_order=3),
        dict(component_key="tds", label="TDS / Income Tax",
             employee_share="As per income slab", employer_share="—", total="As per slab",
             sort_order=4),
        # Previously never seeded anywhere — every one of these ran on its
        # hardcoded engine/countries/india.py fallback constant for every
        # org, always. Now real, editable ContributionRate rows (amount
        # parameters use flat_amount, consumed via resolve_jurisdiction_parameter).
        dict(component_key="esi_wage_ceiling", label="ESI Wage Ceiling (Monthly)",
             employee_share="—", employer_share="—", total="₹21,000",
             flat_amount=Decimal("21000.00"), sort_order=5),
        dict(component_key="standard_deduction", label="Standard Deduction",
             employee_share="—", employer_share="—", total="₹75,000",
             flat_amount=Decimal("75000.00"), sort_order=6),
        dict(component_key="rebate_87a_limit", label="Section 87A Rebate — Income Limit",
             employee_share="—", employer_share="—", total="₹12,00,000",
             flat_amount=Decimal("1200000.00"), sort_order=7),
        dict(component_key="rebate_87a_max", label="Section 87A Rebate — Max Amount",
             employee_share="—", employer_share="—", total="₹60,000",
             flat_amount=Decimal("60000.00"), sort_order=8),
        # Read behind _IN_PF_WAGE_CEILING_ENABLED_COUNTRIES (dormant by
        # default) — see india.py's calculate() and shared.py's switch
        # comment. Configurable/editable from day one even while dormant,
        # same convention as every other parameter row in this block.
        dict(component_key="pf_wage_ceiling", label="EPF Wage Ceiling (Monthly)",
             employee_share="—", employer_share="—", total="₹15,000",
             flat_amount=Decimal("15000.00"), sort_order=9),
    ],
    "US": [
        dict(component_key="social-security", label="Social Security",
             employee_share="6.2%", employer_share="6.2%", total="12.4%",
             employee_rate_pct=Decimal("6.20"), employer_rate_pct=Decimal("6.20"), sort_order=1),
        dict(component_key="medicare", label="Medicare",
             employee_share="1.45%", employer_share="1.45%", total="2.9%",
             employee_rate_pct=Decimal("1.45"), employer_rate_pct=Decimal("1.45"), sort_order=2),
        dict(component_key="futa", label="Federal Unemployment (FUTA)",
             employee_share="—", employer_share="6.0%", total="6.0%",
             employer_rate_pct=Decimal("6.00"), sort_order=3),
        dict(component_key="federal-income-tax", label="Federal Income Tax",
             employee_share="As per W-4", employer_share="—", total="As per W-4",
             sort_order=4),
        # Previously never seeded — see the India block's comment above,
        # same story. FUTA itself was seeded (row above) but never
        # actually read by the engine until this pass; its wage base
        # never existed as a configurable row at all.
        # 2026: $176,100 (2025) -> $184,500 per ZP-TAX-US-2026-001 §3.1 /
        # SSA 2026 contribution and benefit base determination.
        dict(component_key="ss_wage_base", label="Social Security Wage Base",
             employee_share="—", employer_share="—", total="$184,500",
             flat_amount=Decimal("184500.00"), sort_order=5),
        dict(component_key="medicare_addl_thresh", label="Additional Medicare Threshold",
             employee_share="—", employer_share="—", total="$200,000",
             flat_amount=Decimal("200000.00"), sort_order=6),
        dict(component_key="futa_wage_base", label="FUTA Wage Base",
             employee_share="—", employer_share="—", total="$7,000",
             flat_amount=Decimal("7000.00"), sort_order=7),
        # 2026 federal standard deduction, filing-status-tagged. Was
        # previously seeded under mismatched keys (std_ded_single/
        # std_ded_mfj/std_ded_mfs/std_ded_hoh) that us.py's
        # resolve_jurisdiction_parameter(rate_map, "standard_deduction",
        # ...) never actually looked up — every filing status silently
        # fell back to the hardcoded $15,000 constant regardless. Same
        # values, correct key this time, retagged per filing status. An
        # untagged ($16,100, same as Single) row is included as the
        # fallback for an employee with no w4_filing_status recorded.
        dict(component_key="standard_deduction", label="Standard Deduction",
             employee_share="—", employer_share="—", total="$16,100",
             flat_amount=Decimal("16100.00"), sort_order=8),
        dict(component_key="standard_deduction", label="Standard Deduction (Single)",
             employee_share="—", employer_share="—", total="$16,100",
             flat_amount=Decimal("16100.00"), filing_status="SINGLE", sort_order=9),
        dict(component_key="standard_deduction", label="Standard Deduction (MFJ)",
             employee_share="—", employer_share="—", total="$32,200",
             flat_amount=Decimal("32200.00"), filing_status="MFJ", sort_order=10),
        dict(component_key="standard_deduction", label="Standard Deduction (MFS)",
             employee_share="—", employer_share="—", total="$16,100",
             flat_amount=Decimal("16100.00"), filing_status="MFS", sort_order=11),
        dict(component_key="standard_deduction", label="Standard Deduction (HOH)",
             employee_share="—", employer_share="—", total="$24,150",
             flat_amount=Decimal("24150.00"), filing_status="HOH", sort_order=12),
    ],
    "UK": [
        dict(component_key="national-insurance", label="National Insurance",
             employee_share="8% (primary) / 2% (upper)", employer_share="13.8%", total="21.8% (employee) + 13.8%",
             employee_rate_pct=Decimal("8.00"), employer_rate_pct=Decimal("13.80"), sort_order=1),
        dict(component_key="employer-pension", label="Workplace Pension (Employer)",
             employee_share="—", employer_share="3% minimum", total="3%",
             employer_rate_pct=Decimal("3.00"), sort_order=2),
        # Previously never seeded — see the India block's comment above.
        # The "national-insurance" row's employer_rate_pct (13.8%, above)
        # was ALSO seeded from day one but never read by the engine until
        # this pass added employer NI — it was purely a display value.
        dict(component_key="personal_allowance", label="Personal Allowance",
             employee_share="—", employer_share="—", total="£12,570",
             flat_amount=Decimal("12570.00"), sort_order=3),
        dict(component_key="pa_taper_threshold", label="Personal Allowance Taper Threshold",
             employee_share="—", employer_share="—", total="£100,000",
             flat_amount=Decimal("100000.00"), sort_order=4),
        dict(component_key="ni_primary_thresh", label="NI Primary Threshold",
             employee_share="—", employer_share="—", total="£12,570",
             flat_amount=Decimal("12570.00"), sort_order=5),
        dict(component_key="ni_upper_threshold", label="NI Upper Earnings Limit",
             employee_share="—", employer_share="—", total="£50,270",
             flat_amount=Decimal("50270.00"), sort_order=6),
        # Corrected from £9,100 to the real 2026-27 figure, £5,000
        # (ZP-TAX-UK-2026-27-001 §8.1) — the canonical DB row previously
        # disagreed with this file's own _UK_NI_SECONDARY_THRESHOLD Python
        # constant (already 5000), so a canonical-pack-synced org resolved
        # a different Secondary Threshold than an org running on the
        # Python fallback. Reconciled as part of seeding real NI category
        # band data (rule_type="NI_BAND" rows below) — the two must agree
        # for the Category A band-vs-flat-path equivalence to hold.
        dict(component_key="ni_secondary_thresh", label="NI Secondary Threshold (Employer)",
             employee_share="—", employer_share="—", total="£5,000",
             flat_amount=Decimal("5000.00"), sort_order=7),
        dict(component_key="ni_upper_rate", label="NI Upper Rate (Employee)",
             employee_share="2%", employer_share="—", total="2%",
             employee_rate_pct=Decimal("2.00"), sort_order=8),
        # K-code overriding limit (ZP-TAX-UK-2026-27-001 §6.2) — was a bare
        # inline Decimal("0.5") in uk.py until now; seeded here so it's
        # Super-Admin-editable like every other UK figure.
        dict(component_key="k_code_cap_pct", label="K-Code Overriding Limit",
             employee_share="—", employer_share="—", total="50%",
             employee_rate_pct=Decimal("50.00"), sort_order=9),
    ],
    # Representative defaults — Enterprise Policy jurisdictions. Unlike US/UK
    # above (display-only; the engine's US/UK calculators use hardcoded
    # constants), these component_keys are the actual keys _calc_australia/
    # _calc_germany/_calc_canada read from rate_map — genuinely
    # configuration-driven. Verify/adjust against current statutory rates
    # before relying on these for real payroll.
    "AU": [
        dict(component_key="super", label="Superannuation Guarantee",
             employee_share="—", employer_share="11.5%", total="11.5%",
             employer_rate_pct=Decimal("11.50"), sort_order=1),
        dict(component_key="medicare-levy", label="Medicare Levy",
             employee_share="2.0%", employer_share="—", total="2.0%",
             employee_rate_pct=Decimal("2.00"), sort_order=2),
        dict(component_key="income-tax", label="Income Tax (PAYG)",
             employee_share="As per income slab", employer_share="—", total="As per slab",
             sort_order=3),
        # componentKey max 20 chars (payroll_contribution_rates.component_key
        # is VARCHAR(20)) — the original 27/34-char keys always 500'd on
        # insert, meaning any AU org whose first-ever seed hit this path
        # (no canonical pack synced yet) silently got ZERO default rates for
        # this whole country, not just these two rows (_seed_contribution_rates
        # commits the batch once at the end). Also renamed in australia.py's
        # resolve_jurisdiction_parameter() calls and fallback_registry.py.
        dict(component_key="super_max_contrib", label="Superannuation Max Contribution Base",
             employee_share="—", employer_share="—", total="A$260,280",
             flat_amount=Decimal("260280.00"), sort_order=4),
        dict(component_key="medicare_low_inc_thr", label="Medicare Levy Low-Income Threshold",
             employee_share="—", employer_share="—", total="A$24,276",
             flat_amount=Decimal("24276.00"), sort_order=5),
        dict(component_key="mls_threshold", label="Medicare Levy Surcharge Threshold",
             employee_share="—", employer_share="—", total="A$97,000",
             flat_amount=Decimal("97000.00"), sort_order=6),
        dict(component_key="mls_rate", label="Medicare Levy Surcharge Rate",
             employee_share="1.0%", employer_share="—", total="1.0%",
             employee_rate_pct=Decimal("1.00"), sort_order=7),
        dict(component_key="help_threshold", label="HELP/HECS Repayment Threshold",
             employee_share="—", employer_share="—", total="A$54,435",
             flat_amount=Decimal("54435.00"), sort_order=8),
        dict(component_key="help_rate", label="HELP/HECS Repayment Rate",
             employee_share="4.5%", employer_share="—", total="4.5%",
             employee_rate_pct=Decimal("4.50"), sort_order=9),
    ],
    "DE": [
        dict(component_key="pension", label="Pension Insurance (Rentenversicherung)",
             employee_share="9.3%", employer_share="9.3%", total="18.6%",
             employee_rate_pct=Decimal("9.30"), employer_rate_pct=Decimal("9.30"), sort_order=1),
        dict(component_key="social-insurance", label="Social Insurance (Health / Unemployment / Care)",
             employee_share="9.0%", employer_share="9.0%", total="18.0%",
             employee_rate_pct=Decimal("9.00"), employer_rate_pct=Decimal("9.00"), sort_order=2),
        dict(component_key="income-tax", label="Income Tax (Lohnsteuer)",
             employee_share="As per income slab", employer_share="—", total="As per slab",
             sort_order=3),
        dict(component_key="grundfreibetrag", label="Basic Tax-Free Allowance (Grundfreibetrag)",
             employee_share="—", employer_share="—", total="€11,784",
             flat_amount=Decimal("11784.00"), sort_order=4),
        dict(component_key="soli_threshold", label="Solidarity Surcharge Threshold",
             employee_share="—", employer_share="—", total="€18,130",
             flat_amount=Decimal("18130.00"), sort_order=5),
        dict(component_key="soli_rate", label="Solidarity Surcharge Rate",
             employee_share="5.5%", employer_share="—", total="5.5%",
             employee_rate_pct=Decimal("5.50"), sort_order=6),
        dict(component_key="contribution_ceiling", label="Social Insurance Contribution Ceiling",
             employee_share="—", employer_share="—", total="€96,600",
             flat_amount=Decimal("96600.00"), sort_order=7),
        dict(component_key="church_tax_rate", label="Church Tax Rate (Kirchensteuer)",
             employee_share="9%", employer_share="—", total="9%",
             employee_rate_pct=Decimal("9.00"), sort_order=8),
    ],
    "CA": [
        # 2026 values per ZP-TAX-CA-2026-001 (CRA T4127 122nd/123rd Ed.) —
        # federal-only fallback; provincial tax still excluded (see
        # canada.py). BPA below is the flat statutory default (NI <=
        # $181,440); the income-tapered reduction above that threshold is
        # not yet implemented — flat value only.
        dict(component_key="cpp", label="Canada Pension Plan (CPP)",
             employee_share="5.95%", employer_share="5.95%", total="11.9%",
             employee_rate_pct=Decimal("5.95"), employer_rate_pct=Decimal("5.95"), sort_order=1),
        dict(component_key="ei", label="Employment Insurance (EI)",
             employee_share="1.63%", employer_share="2.282%", total="3.912%",
             employee_rate_pct=Decimal("1.63"), employer_rate_pct=Decimal("2.282"), sort_order=2),
        dict(component_key="income-tax", label="Federal Income Tax",
             employee_share="As per income slab", employer_share="—", total="As per slab",
             sort_order=3),
        # componentKey max 20 chars (payroll_contribution_rates.component_key
        # is VARCHAR(20)) — "basic_personal_amount" (21 chars) always 500'd
        # on insert. Also renamed in canada.py's resolve_jurisdiction_parameter()
        # call and fallback_registry.py.
        dict(component_key="basic_personal_amt", label="Basic Personal Amount",
             employee_share="—", employer_share="—", total="C$16,452",
             flat_amount=Decimal("16452.00"), sort_order=4),
        dict(component_key="cpp_ympe", label="CPP Year's Maximum Pensionable Earnings (YMPE)",
             employee_share="—", employer_share="—", total="C$74,600",
             flat_amount=Decimal("74600.00"), sort_order=5),
        dict(component_key="cpp_basic_exemption", label="CPP Basic Exemption Amount",
             employee_share="—", employer_share="—", total="C$3,500",
             flat_amount=Decimal("3500.00"), sort_order=6),
        dict(component_key="ei_mie", label="EI Maximum Insurable Earnings",
             employee_share="—", employer_share="—", total="C$68,900",
             flat_amount=Decimal("68900.00"), sort_order=7),
        dict(component_key="cpp2_yampe", label="CPP2 Year's Additional Maximum Pensionable Earnings (YAMPE)",
             employee_share="—", employer_share="—", total="C$85,000",
             flat_amount=Decimal("85000.00"), sort_order=8),
        dict(component_key="cpp2_rate", label="CPP2 Rate",
             employee_share="4%", employer_share="—", total="4%",
             employee_rate_pct=Decimal("4.00"), sort_order=9),
        dict(component_key="bpaf_min", label="Federal Basic Personal Amount — Minimum (tapered)",
             employee_share="—", employer_share="—", total="C$14,829",
             flat_amount=Decimal("14829.00"), sort_order=10),
        dict(component_key="bpaf_ni_thresh_lo", label="BPAF Taper — Net Income Threshold (Low)",
             employee_share="—", employer_share="—", total="C$181,440",
             flat_amount=Decimal("181440.00"), sort_order=11),
        dict(component_key="bpaf_ni_thresh_hi", label="BPAF Taper — Net Income Threshold (High)",
             employee_share="—", employer_share="—", total="C$258,482",
             flat_amount=Decimal("258482.00"), sort_order=12),
        dict(component_key="cea", label="Canada Employment Amount (credit)",
             employee_share="—", employer_share="—", total="C$1,501",
             flat_amount=Decimal("1501.00"), sort_order=13),
        dict(component_key="lowest_fed_rate", label="Lowest Federal Rate (credit conversion)",
             employee_share="—", employer_share="—", total="14%",
             employee_rate_pct=Decimal("14.00"), sort_order=14),
        # Prepared but not yet consumed by calculate() — see the
        # corresponding _CA_* constants in this file for why.
        dict(component_key="qc_fed_abatement", label="Quebec Federal Abatement (not yet active)",
             employee_share="—", employer_share="—", total="16.5%",
             employee_rate_pct=Decimal("16.50"), sort_order=15),
        dict(component_key="beyond_prov_surtax", label="Beyond-Province Surtax Factor (not yet active)",
             employee_share="—", employer_share="—", total="48% of T3",
             employee_rate_pct=Decimal("48.00"), sort_order=16),
        dict(component_key="lsvcc_credit_rate", label="Labour-Sponsored Fund Credit Rate (not yet active)",
             employee_share="—", employer_share="—", total="15%",
             employee_rate_pct=Decimal("15.00"), sort_order=17),
        dict(component_key="lsvcc_credit_max", label="Labour-Sponsored Fund Credit Max (not yet active)",
             employee_share="—", employer_share="—", total="C$750",
             flat_amount=Decimal("750.00"), sort_order=18),
    ],
}


_TAX_SLABS_BY_COUNTRY = {
    "IN": [
        # FY 2025-26 New Regime — standard deduction of ₹75,000 already
        # factored into the effective taxable income passed to the engine.
        dict(min_amount=Decimal("0"),        max_amount=Decimal("400000"),   rate_pct=Decimal("0"),   rate_label="Nil",  tax_formula="Basic exemption (up to ₹4L)", sort_order=1),
        dict(min_amount=Decimal("400000"),   max_amount=Decimal("800000"),   rate_pct=Decimal("5"),   rate_label="5%",   tax_formula="5% of income over ₹4L", sort_order=2),
        dict(min_amount=Decimal("800000"),   max_amount=Decimal("1200000"),  rate_pct=Decimal("10"),  rate_label="10%",  tax_formula="₹20,000 + 10% over ₹8L", sort_order=3),
        dict(min_amount=Decimal("1200000"),  max_amount=Decimal("1600000"),  rate_pct=Decimal("15"),  rate_label="15%",  tax_formula="₹60,000 + 15% over ₹12L", sort_order=4),
        dict(min_amount=Decimal("1600000"),  max_amount=Decimal("2000000"),  rate_pct=Decimal("20"),  rate_label="20%",  tax_formula="₹1,20,000 + 20% over ₹16L", sort_order=5),
        dict(min_amount=Decimal("2000000"),  max_amount=Decimal("2400000"),  rate_pct=Decimal("25"),  rate_label="25%",  tax_formula="₹2,00,000 + 25% over ₹20L", sort_order=6),
        dict(min_amount=Decimal("2400000"),  max_amount=None,                rate_pct=Decimal("30"),  rate_label="30%",  tax_formula="₹3,00,000 + 30% over ₹24L", sort_order=7),
        # Old Regime — non-senior/nonresident bands (ZP-TAX-IN-2026-27-001
        # §4.1). tax_regime="Old" so service.get_tax_slabs returns ONLY
        # this table (not summed with the New Regime rows above) for an
        # employee with ctx.tax_regime=="Old" — see get_tax_slabs' own
        # MARGINAL_RATE-exclusion comment. Senior (60-79) and super-senior
        # (80+) resident bands are NOT included here: they need an
        # employee age/residency fact PayrollContext doesn't carry yet
        # (see india.py's calculate() docstring) — a deliberate, disclosed
        # scope boundary, not an oversight. New sort_order range (11-14)
        # so re-running populate_canonical_tax_v1.py never collides with
        # the New Regime rows' sort_order (1-7) it dedupes by.
        dict(min_amount=Decimal("0"),       max_amount=Decimal("250000"),   rate_pct=Decimal("0"),   rate_label="Nil",  tax_formula="Basic exemption (up to ₹2.5L)", tax_regime="Old", sort_order=11),
        dict(min_amount=Decimal("250000"),  max_amount=Decimal("500000"),   rate_pct=Decimal("5"),   rate_label="5%",   tax_formula="5% of income over ₹2.5L", tax_regime="Old", sort_order=12),
        dict(min_amount=Decimal("500000"),  max_amount=Decimal("1000000"),  rate_pct=Decimal("20"),  rate_label="20%",  tax_formula="₹12,500 + 20% over ₹5L", tax_regime="Old", sort_order=13),
        dict(min_amount=Decimal("1000000"), max_amount=None,                rate_pct=Decimal("30"),  rate_label="30%",  tax_formula="₹1,12,500 + 30% over ₹10L", tax_regime="Old", sort_order=14),
        # Surcharge tiers (§5) — rule_type="SURCHARGE" rows read by
        # india.py's _apply_surcharge (min_amount=income threshold,
        # rate_pct=surcharge % of TAX, not of income). The first three
        # tiers are tax_regime=None (shared — identical for both regimes
        # per the document's own table), so a New Regime employee's tax
        # correctly caps at 25% above ₹5cr (no fourth tier exists for
        # them). The >₹5cr 37% tier is tax_regime="Old" only, per the
        # document's regime split at that top bracket.
        dict(min_amount=Decimal("5000000"),  max_amount=None, rate_pct=Decimal("10"), rate_label="10%", tax_formula="Surcharge on tax, income > ₹50L", rule_type="SURCHARGE", sort_order=21),
        dict(min_amount=Decimal("10000000"), max_amount=None, rate_pct=Decimal("15"), rate_label="15%", tax_formula="Surcharge on tax, income > ₹1Cr", rule_type="SURCHARGE", sort_order=22),
        dict(min_amount=Decimal("20000000"), max_amount=None, rate_pct=Decimal("25"), rate_label="25%", tax_formula="Surcharge on tax, income > ₹2Cr", rule_type="SURCHARGE", sort_order=23),
        dict(min_amount=Decimal("50000000"), max_amount=None, rate_pct=Decimal("37"), rate_label="37%", tax_formula="Surcharge on tax, income > ₹5Cr (Old Regime only)", rule_type="SURCHARGE", tax_regime="Old", sort_order=24),
        # Telangana Professional Tax brackets (§13.3) — rule_type="PT_FLAT",
        # resolved via ctx.state_slabs/_resolve_state_pt_bracket, not the
        # country-level MARGINAL_RATE/SURCHARGE rows above (jurisdiction_
        # state makes these state-scoped; get_state_scoped_config's
        # single-pack fast path applies since no other pack contends for
        # this state/rule_type, so no JurisdictionPack attachment or
        # maker-checker promotion is needed for these to resolve).
        # rate_pct=0 is required (NOT NULL column) but unread for PT_FLAT —
        # flat_amount is what _resolve_state_pt_bracket actually consumes.
        dict(min_amount=Decimal("0"),      max_amount=Decimal("15000"), rate_pct=Decimal("0"), rate_label="PT", tax_formula="", rule_type="PT_FLAT", flat_amount=Decimal("0.00"),   jurisdiction_state="Telangana", sort_order=31),
        dict(min_amount=Decimal("15001"),  max_amount=Decimal("20000"), rate_pct=Decimal("0"), rate_label="PT", tax_formula="", rule_type="PT_FLAT", flat_amount=Decimal("150.00"), jurisdiction_state="Telangana", sort_order=32),
        dict(min_amount=Decimal("20001"),  max_amount=None,             rate_pct=Decimal("0"), rate_label="PT", tax_formula="", rule_type="PT_FLAT", flat_amount=Decimal("200.00"), jurisdiction_state="Telangana", sort_order=33),
    ],
    "US": [
        # Tax Year 2026, IRS Pub 15-T Worksheet 1A annualized schedules
        # (ZP-TAX-US-2026-001 §3.2). The doc publishes one combined
        # "Single/MFS" table, but this codebase's filing_status vocabulary
        # (SINGLE/MFJ/MFS/HOH, matching w4_filing_status and the existing
        # medicare_addl_thresh convention) treats SINGLE and MFS as
        # distinct codes — so the same 8 brackets are tagged under both,
        # plus once more untagged as the fallback for an employee with no
        # w4_filing_status recorded at all (matches how "standard_deduction"
        # above also carries an untagged fallback row). Standard deduction
        # is applied by _calculate_annual_tax_us before these brackets.
        dict(min_amount=Decimal("0"),       max_amount=Decimal("7500"),     rate_pct=Decimal("0"),   rate_label="0%",   tax_formula="No withholding up to $7,500", sort_order=1),
        dict(min_amount=Decimal("7500"),    max_amount=Decimal("19900"),    rate_pct=Decimal("10"),  rate_label="10%",  tax_formula="10% of income over $7,500", sort_order=2),
        dict(min_amount=Decimal("19900"),   max_amount=Decimal("57900"),    rate_pct=Decimal("12"),  rate_label="12%",  tax_formula="$1,240 + 12% over $19,900", sort_order=3),
        dict(min_amount=Decimal("57900"),   max_amount=Decimal("113200"),   rate_pct=Decimal("22"),  rate_label="22%",  tax_formula="$5,800 + 22% over $57,900", sort_order=4),
        dict(min_amount=Decimal("113200"),  max_amount=Decimal("209275"),   rate_pct=Decimal("24"),  rate_label="24%",  tax_formula="$17,966 + 24% over $113,200", sort_order=5),
        dict(min_amount=Decimal("209275"),  max_amount=Decimal("263725"),   rate_pct=Decimal("32"),  rate_label="32%",  tax_formula="$41,024 + 32% over $209,275", sort_order=6),
        dict(min_amount=Decimal("263725"),  max_amount=Decimal("648100"),   rate_pct=Decimal("35"),  rate_label="35%",  tax_formula="$58,448 + 35% over $263,725", sort_order=7),
        dict(min_amount=Decimal("648100"),  max_amount=None,                rate_pct=Decimal("37"),  rate_label="37%",  tax_formula="$192,979.25 + 37% over $648,100", sort_order=8),
        # Single
        dict(min_amount=Decimal("0"),       max_amount=Decimal("7500"),     rate_pct=Decimal("0"),   rate_label="0%",   tax_formula="No withholding up to $7,500", filing_status="SINGLE", sort_order=9),
        dict(min_amount=Decimal("7500"),    max_amount=Decimal("19900"),    rate_pct=Decimal("10"),  rate_label="10%",  tax_formula="10% of income over $7,500", filing_status="SINGLE", sort_order=10),
        dict(min_amount=Decimal("19900"),   max_amount=Decimal("57900"),    rate_pct=Decimal("12"),  rate_label="12%",  tax_formula="$1,240 + 12% over $19,900", filing_status="SINGLE", sort_order=11),
        dict(min_amount=Decimal("57900"),   max_amount=Decimal("113200"),   rate_pct=Decimal("22"),  rate_label="22%",  tax_formula="$5,800 + 22% over $57,900", filing_status="SINGLE", sort_order=12),
        dict(min_amount=Decimal("113200"),  max_amount=Decimal("209275"),   rate_pct=Decimal("24"),  rate_label="24%",  tax_formula="$17,966 + 24% over $113,200", filing_status="SINGLE", sort_order=13),
        dict(min_amount=Decimal("209275"),  max_amount=Decimal("263725"),   rate_pct=Decimal("32"),  rate_label="32%",  tax_formula="$41,024 + 32% over $209,275", filing_status="SINGLE", sort_order=14),
        dict(min_amount=Decimal("263725"),  max_amount=Decimal("648100"),   rate_pct=Decimal("35"),  rate_label="35%",  tax_formula="$58,448 + 35% over $263,725", filing_status="SINGLE", sort_order=15),
        dict(min_amount=Decimal("648100"),  max_amount=None,                rate_pct=Decimal("37"),  rate_label="37%",  tax_formula="$192,979.25 + 37% over $648,100", filing_status="SINGLE", sort_order=16),
        # MFS (same brackets as Single, own tag — the doc publishes one
        # combined "Single/MFS" table, but this codebase's filing_status
        # vocabulary treats them as distinct codes elsewhere too, e.g.
        # medicare_addl_thresh's SINGLE/MFS split).
        dict(min_amount=Decimal("0"),       max_amount=Decimal("7500"),     rate_pct=Decimal("0"),   rate_label="0%",   tax_formula="No withholding up to $7,500", filing_status="MFS", sort_order=17),
        dict(min_amount=Decimal("7500"),    max_amount=Decimal("19900"),    rate_pct=Decimal("10"),  rate_label="10%",  tax_formula="10% of income over $7,500", filing_status="MFS", sort_order=18),
        dict(min_amount=Decimal("19900"),   max_amount=Decimal("57900"),    rate_pct=Decimal("12"),  rate_label="12%",  tax_formula="$1,240 + 12% over $19,900", filing_status="MFS", sort_order=19),
        dict(min_amount=Decimal("57900"),   max_amount=Decimal("113200"),   rate_pct=Decimal("22"),  rate_label="22%",  tax_formula="$5,800 + 22% over $57,900", filing_status="MFS", sort_order=20),
        dict(min_amount=Decimal("113200"),  max_amount=Decimal("209275"),   rate_pct=Decimal("24"),  rate_label="24%",  tax_formula="$17,966 + 24% over $113,200", filing_status="MFS", sort_order=21),
        dict(min_amount=Decimal("209275"),  max_amount=Decimal("263725"),   rate_pct=Decimal("32"),  rate_label="32%",  tax_formula="$41,024 + 32% over $209,275", filing_status="MFS", sort_order=22),
        dict(min_amount=Decimal("263725"),  max_amount=Decimal("648100"),   rate_pct=Decimal("35"),  rate_label="35%",  tax_formula="$58,448 + 35% over $263,725", filing_status="MFS", sort_order=23),
        dict(min_amount=Decimal("648100"),  max_amount=None,                rate_pct=Decimal("37"),  rate_label="37%",  tax_formula="$192,979.25 + 37% over $648,100", filing_status="MFS", sort_order=24),
        # MFJ
        dict(min_amount=Decimal("0"),       max_amount=Decimal("19300"),    rate_pct=Decimal("0"),   rate_label="0%",   tax_formula="No withholding up to $19,300", filing_status="MFJ", sort_order=100),
        dict(min_amount=Decimal("19300"),   max_amount=Decimal("44100"),    rate_pct=Decimal("10"),  rate_label="10%",  tax_formula="10% of income over $19,300", filing_status="MFJ", sort_order=25),
        dict(min_amount=Decimal("44100"),   max_amount=Decimal("120100"),   rate_pct=Decimal("12"),  rate_label="12%",  tax_formula="$2,480 + 12% over $44,100", filing_status="MFJ", sort_order=26),
        dict(min_amount=Decimal("120100"),  max_amount=Decimal("230700"),   rate_pct=Decimal("22"),  rate_label="22%",  tax_formula="$11,600 + 22% over $120,100", filing_status="MFJ", sort_order=27),
        dict(min_amount=Decimal("230700"),  max_amount=Decimal("422850"),   rate_pct=Decimal("24"),  rate_label="24%",  tax_formula="$35,932 + 24% over $230,700", filing_status="MFJ", sort_order=28),
        dict(min_amount=Decimal("422850"),  max_amount=Decimal("531750"),   rate_pct=Decimal("32"),  rate_label="32%",  tax_formula="$82,048 + 32% over $422,850", filing_status="MFJ", sort_order=29),
        dict(min_amount=Decimal("531750"),  max_amount=Decimal("788000"),   rate_pct=Decimal("35"),  rate_label="35%",  tax_formula="$116,896 + 35% over $531,750", filing_status="MFJ", sort_order=30),
        dict(min_amount=Decimal("788000"),  max_amount=None,                rate_pct=Decimal("37"),  rate_label="37%",  tax_formula="$206,583.50 + 37% over $788,000", filing_status="MFJ", sort_order=31),
        # Head of Household
        dict(min_amount=Decimal("0"),       max_amount=Decimal("15550"),    rate_pct=Decimal("0"),   rate_label="0%",   tax_formula="No withholding up to $15,550", filing_status="HOH", sort_order=32),
        dict(min_amount=Decimal("15550"),   max_amount=Decimal("33250"),    rate_pct=Decimal("10"),  rate_label="10%",  tax_formula="10% of income over $15,550", filing_status="HOH", sort_order=33),
        dict(min_amount=Decimal("33250"),   max_amount=Decimal("83000"),    rate_pct=Decimal("12"),  rate_label="12%",  tax_formula="$1,770 + 12% over $33,250", filing_status="HOH", sort_order=34),
        dict(min_amount=Decimal("83000"),   max_amount=Decimal("121250"),   rate_pct=Decimal("22"),  rate_label="22%",  tax_formula="$7,740 + 22% over $83,000", filing_status="HOH", sort_order=35),
        dict(min_amount=Decimal("121250"),  max_amount=Decimal("217300"),   rate_pct=Decimal("24"),  rate_label="24%",  tax_formula="$16,155 + 24% over $121,250", filing_status="HOH", sort_order=36),
        dict(min_amount=Decimal("217300"),  max_amount=Decimal("271750"),   rate_pct=Decimal("32"),  rate_label="32%",  tax_formula="$39,207 + 32% over $217,300", filing_status="HOH", sort_order=37),
        dict(min_amount=Decimal("271750"),  max_amount=Decimal("656150"),   rate_pct=Decimal("35"),  rate_label="35%",  tax_formula="$56,631 + 35% over $271,750", filing_status="HOH", sort_order=38),
        dict(min_amount=Decimal("656150"),  max_amount=None,                rate_pct=Decimal("37"),  rate_label="37%",  tax_formula="$191,171 + 37% over $656,150", filing_status="HOH", sort_order=39),
    ],
    "UK": [
        # Tax Year 2025-26. Personal allowance £12,570 (tapered above
        # £100k — handled in _calculate_annual_tax_uk).
        dict(min_amount=Decimal("0"),       max_amount=Decimal("12570"),    rate_pct=Decimal("0"),   rate_label="0%",   tax_formula="Personal allowance", sort_order=1),
        dict(min_amount=Decimal("12570"),   max_amount=Decimal("50270"),    rate_pct=Decimal("20"),  rate_label="20%",  tax_formula="20% of income above £12,570", sort_order=2),
        dict(min_amount=Decimal("50270"),   max_amount=Decimal("125140"),   rate_pct=Decimal("40"),  rate_label="40%",  tax_formula="£7,540 + 40% above £50,270", sort_order=3),
        dict(min_amount=Decimal("125140"),  max_amount=None,                rate_pct=Decimal("45"),  rate_label="45%",  tax_formula="£37,488 + 45% above £125,140", sort_order=4),
        # National Insurance category bands (ZP-TAX-UK-2026-27-001 §8.3
        # employee / §9.1 employer) — rule_type="NI_BAND", read by
        # uk.py's _resolve_ni_bands/_calculate_ni_from_bands, only behind
        # _UK_NI_CATEGORY_BANDS_ENABLED_COUNTRIES (shared.py; off by
        # default, so every existing employee keeps computing via the
        # flat Category-A-shaped fallback until deliberately enabled).
        # rate_pct is the EMPLOYEE rate, employer_rate_pct the EMPLOYER
        # rate (models.py's own documented convention for NI_BAND rows).
        # Breakpoints used: ST=£5,000, PT=£12,570, FUST/IZUST=£25,000,
        # UEL/UST/AUST/VUST=£50,270 — LEL (£6,708) is deliberately never
        # a breakpoint here: the document's own employer table never
        # changes rate between ST and LEL for any of the 16 categories,
        # matching _resolve_ni_bands' pre-existing docstring note.
        # Category A — standard.
        dict(min_amount=Decimal("0"),     max_amount=Decimal("5000"),  rate_pct=Decimal("0"),    employer_rate_pct=Decimal("0"),  rate_label="0%/0%",     tax_formula="", rule_type="NI_BAND", ni_category="A", sort_order=101),
        dict(min_amount=Decimal("5000"),  max_amount=Decimal("12570"), rate_pct=Decimal("0"),    employer_rate_pct=Decimal("15"), rate_label="0%/15%",    tax_formula="", rule_type="NI_BAND", ni_category="A", sort_order=102),
        dict(min_amount=Decimal("12570"), max_amount=Decimal("50270"), rate_pct=Decimal("8"),    employer_rate_pct=Decimal("15"), rate_label="8%/15%",    tax_formula="", rule_type="NI_BAND", ni_category="A", sort_order=103),
        dict(min_amount=Decimal("50270"), max_amount=None,             rate_pct=Decimal("2"),    employer_rate_pct=Decimal("15"), rate_label="2%/15%",    tax_formula="", rule_type="NI_BAND", ni_category="A", sort_order=104),
        # Category B — married women/widows reduced-rate election.
        dict(min_amount=Decimal("0"),     max_amount=Decimal("5000"),  rate_pct=Decimal("0"),    employer_rate_pct=Decimal("0"),  rate_label="0%/0%",     tax_formula="", rule_type="NI_BAND", ni_category="B", sort_order=105),
        dict(min_amount=Decimal("5000"),  max_amount=Decimal("12570"), rate_pct=Decimal("0"),    employer_rate_pct=Decimal("15"), rate_label="0%/15%",    tax_formula="", rule_type="NI_BAND", ni_category="B", sort_order=106),
        dict(min_amount=Decimal("12570"), max_amount=Decimal("50270"), rate_pct=Decimal("1.85"), employer_rate_pct=Decimal("15"), rate_label="1.85%/15%", tax_formula="", rule_type="NI_BAND", ni_category="B", sort_order=107),
        dict(min_amount=Decimal("50270"), max_amount=None,             rate_pct=Decimal("2"),    employer_rate_pct=Decimal("15"), rate_label="2%/15%",    tax_formula="", rule_type="NI_BAND", ni_category="B", sort_order=108),
        # Category C — at/over State Pension age (no employee NI at all).
        dict(min_amount=Decimal("0"),     max_amount=Decimal("5000"),  rate_pct=Decimal("0"),    employer_rate_pct=Decimal("0"),  rate_label="nil/0%",    tax_formula="", rule_type="NI_BAND", ni_category="C", sort_order=109),
        dict(min_amount=Decimal("5000"),  max_amount=None,             rate_pct=Decimal("0"),    employer_rate_pct=Decimal("15"), rate_label="nil/15%",   tax_formula="", rule_type="NI_BAND", ni_category="C", sort_order=110),
        # Category D — Investment Zone deferment.
        dict(min_amount=Decimal("0"),     max_amount=Decimal("12570"), rate_pct=Decimal("0"),    employer_rate_pct=Decimal("0"),  rate_label="0%/0%",     tax_formula="", rule_type="NI_BAND", ni_category="D", sort_order=111),
        dict(min_amount=Decimal("12570"), max_amount=Decimal("25000"), rate_pct=Decimal("2"),    employer_rate_pct=Decimal("0"),  rate_label="2%/0%",     tax_formula="", rule_type="NI_BAND", ni_category="D", sort_order=112),
        dict(min_amount=Decimal("25000"), max_amount=None,             rate_pct=Decimal("2"),    employer_rate_pct=Decimal("15"), rate_label="2%/15%",    tax_formula="", rule_type="NI_BAND", ni_category="D", sort_order=113),
        # Category E — Investment Zone reduced-rate married women/widows.
        dict(min_amount=Decimal("0"),     max_amount=Decimal("12570"), rate_pct=Decimal("0"),    employer_rate_pct=Decimal("0"),  rate_label="0%/0%",     tax_formula="", rule_type="NI_BAND", ni_category="E", sort_order=114),
        dict(min_amount=Decimal("12570"), max_amount=Decimal("25000"), rate_pct=Decimal("1.85"), employer_rate_pct=Decimal("0"),  rate_label="1.85%/0%",  tax_formula="", rule_type="NI_BAND", ni_category="E", sort_order=115),
        dict(min_amount=Decimal("25000"), max_amount=Decimal("50270"), rate_pct=Decimal("1.85"), employer_rate_pct=Decimal("15"), rate_label="1.85%/15%", tax_formula="", rule_type="NI_BAND", ni_category="E", sort_order=116),
        dict(min_amount=Decimal("50270"), max_amount=None,             rate_pct=Decimal("2"),    employer_rate_pct=Decimal("15"), rate_label="2%/15%",    tax_formula="", rule_type="NI_BAND", ni_category="E", sort_order=117),
        # Category F — Freeport standard.
        dict(min_amount=Decimal("0"),     max_amount=Decimal("12570"), rate_pct=Decimal("0"),    employer_rate_pct=Decimal("0"),  rate_label="0%/0%",     tax_formula="", rule_type="NI_BAND", ni_category="F", sort_order=118),
        dict(min_amount=Decimal("12570"), max_amount=Decimal("25000"), rate_pct=Decimal("8"),    employer_rate_pct=Decimal("0"),  rate_label="8%/0%",     tax_formula="", rule_type="NI_BAND", ni_category="F", sort_order=119),
        dict(min_amount=Decimal("25000"), max_amount=Decimal("50270"), rate_pct=Decimal("8"),    employer_rate_pct=Decimal("15"), rate_label="8%/15%",    tax_formula="", rule_type="NI_BAND", ni_category="F", sort_order=120),
        dict(min_amount=Decimal("50270"), max_amount=None,             rate_pct=Decimal("2"),    employer_rate_pct=Decimal("15"), rate_label="2%/15%",    tax_formula="", rule_type="NI_BAND", ni_category="F", sort_order=121),
        # Category H — apprentice under 25.
        dict(min_amount=Decimal("0"),     max_amount=Decimal("12570"), rate_pct=Decimal("0"),    employer_rate_pct=Decimal("0"),  rate_label="0%/0%",     tax_formula="", rule_type="NI_BAND", ni_category="H", sort_order=122),
        dict(min_amount=Decimal("12570"), max_amount=Decimal("50270"), rate_pct=Decimal("8"),    employer_rate_pct=Decimal("0"),  rate_label="8%/0%",     tax_formula="", rule_type="NI_BAND", ni_category="H", sort_order=123),
        dict(min_amount=Decimal("50270"), max_amount=None,             rate_pct=Decimal("2"),    employer_rate_pct=Decimal("15"), rate_label="2%/15%",    tax_formula="", rule_type="NI_BAND", ni_category="H", sort_order=124),
        # Category I — Freeport reduced-rate married women/widows.
        dict(min_amount=Decimal("0"),     max_amount=Decimal("12570"), rate_pct=Decimal("0"),    employer_rate_pct=Decimal("0"),  rate_label="0%/0%",     tax_formula="", rule_type="NI_BAND", ni_category="I", sort_order=125),
        dict(min_amount=Decimal("12570"), max_amount=Decimal("25000"), rate_pct=Decimal("1.85"), employer_rate_pct=Decimal("0"),  rate_label="1.85%/0%",  tax_formula="", rule_type="NI_BAND", ni_category="I", sort_order=126),
        dict(min_amount=Decimal("25000"), max_amount=Decimal("50270"), rate_pct=Decimal("1.85"), employer_rate_pct=Decimal("15"), rate_label="1.85%/15%", tax_formula="", rule_type="NI_BAND", ni_category="I", sort_order=127),
        dict(min_amount=Decimal("50270"), max_amount=None,             rate_pct=Decimal("2"),    employer_rate_pct=Decimal("15"), rate_label="2%/15%",    tax_formula="", rule_type="NI_BAND", ni_category="I", sort_order=128),
        # Category J — NI deferment (already paying in another job).
        dict(min_amount=Decimal("0"),     max_amount=Decimal("5000"),  rate_pct=Decimal("0"),    employer_rate_pct=Decimal("0"),  rate_label="0%/0%",     tax_formula="", rule_type="NI_BAND", ni_category="J", sort_order=129),
        dict(min_amount=Decimal("5000"),  max_amount=Decimal("12570"), rate_pct=Decimal("0"),    employer_rate_pct=Decimal("15"), rate_label="0%/15%",    tax_formula="", rule_type="NI_BAND", ni_category="J", sort_order=130),
        dict(min_amount=Decimal("12570"), max_amount=None,             rate_pct=Decimal("2"),    employer_rate_pct=Decimal("15"), rate_label="2%/15%",    tax_formula="", rule_type="NI_BAND", ni_category="J", sort_order=131),
        # Category K — Investment Zone, State Pension age (no employee NI).
        dict(min_amount=Decimal("0"),     max_amount=Decimal("25000"), rate_pct=Decimal("0"),    employer_rate_pct=Decimal("0"),  rate_label="nil/0%",    tax_formula="", rule_type="NI_BAND", ni_category="K", sort_order=132),
        dict(min_amount=Decimal("25000"), max_amount=None,             rate_pct=Decimal("0"),    employer_rate_pct=Decimal("15"), rate_label="nil/15%",   tax_formula="", rule_type="NI_BAND", ni_category="K", sort_order=133),
        # Category L — Freeport deferment.
        dict(min_amount=Decimal("0"),     max_amount=Decimal("12570"), rate_pct=Decimal("0"),    employer_rate_pct=Decimal("0"),  rate_label="0%/0%",     tax_formula="", rule_type="NI_BAND", ni_category="L", sort_order=134),
        dict(min_amount=Decimal("12570"), max_amount=Decimal("25000"), rate_pct=Decimal("2"),    employer_rate_pct=Decimal("0"),  rate_label="2%/0%",     tax_formula="", rule_type="NI_BAND", ni_category="L", sort_order=135),
        dict(min_amount=Decimal("25000"), max_amount=None,             rate_pct=Decimal("2"),    employer_rate_pct=Decimal("15"), rate_label="2%/15%",    tax_formula="", rule_type="NI_BAND", ni_category="L", sort_order=136),
        # Category M — under 21 standard.
        dict(min_amount=Decimal("0"),     max_amount=Decimal("12570"), rate_pct=Decimal("0"),    employer_rate_pct=Decimal("0"),  rate_label="0%/0%",     tax_formula="", rule_type="NI_BAND", ni_category="M", sort_order=137),
        dict(min_amount=Decimal("12570"), max_amount=Decimal("50270"), rate_pct=Decimal("8"),    employer_rate_pct=Decimal("0"),  rate_label="8%/0%",     tax_formula="", rule_type="NI_BAND", ni_category="M", sort_order=138),
        dict(min_amount=Decimal("50270"), max_amount=None,             rate_pct=Decimal("2"),    employer_rate_pct=Decimal("15"), rate_label="2%/15%",    tax_formula="", rule_type="NI_BAND", ni_category="M", sort_order=139),
        # Category N — Investment Zone standard.
        dict(min_amount=Decimal("0"),     max_amount=Decimal("12570"), rate_pct=Decimal("0"),    employer_rate_pct=Decimal("0"),  rate_label="0%/0%",     tax_formula="", rule_type="NI_BAND", ni_category="N", sort_order=140),
        dict(min_amount=Decimal("12570"), max_amount=Decimal("25000"), rate_pct=Decimal("8"),    employer_rate_pct=Decimal("0"),  rate_label="8%/0%",     tax_formula="", rule_type="NI_BAND", ni_category="N", sort_order=141),
        dict(min_amount=Decimal("25000"), max_amount=Decimal("50270"), rate_pct=Decimal("8"),    employer_rate_pct=Decimal("15"), rate_label="8%/15%",    tax_formula="", rule_type="NI_BAND", ni_category="N", sort_order=142),
        dict(min_amount=Decimal("50270"), max_amount=None,             rate_pct=Decimal("2"),    employer_rate_pct=Decimal("15"), rate_label="2%/15%",    tax_formula="", rule_type="NI_BAND", ni_category="N", sort_order=143),
        # Category S — Freeport, State Pension age (no employee NI).
        dict(min_amount=Decimal("0"),     max_amount=Decimal("25000"), rate_pct=Decimal("0"),    employer_rate_pct=Decimal("0"),  rate_label="nil/0%",    tax_formula="", rule_type="NI_BAND", ni_category="S", sort_order=144),
        dict(min_amount=Decimal("25000"), max_amount=None,             rate_pct=Decimal("0"),    employer_rate_pct=Decimal("15"), rate_label="nil/15%",   tax_formula="", rule_type="NI_BAND", ni_category="S", sort_order=145),
        # Category V — qualifying veteran.
        dict(min_amount=Decimal("0"),     max_amount=Decimal("12570"), rate_pct=Decimal("0"),    employer_rate_pct=Decimal("0"),  rate_label="0%/0%",     tax_formula="", rule_type="NI_BAND", ni_category="V", sort_order=146),
        dict(min_amount=Decimal("12570"), max_amount=Decimal("50270"), rate_pct=Decimal("8"),    employer_rate_pct=Decimal("0"),  rate_label="8%/0%",     tax_formula="", rule_type="NI_BAND", ni_category="V", sort_order=147),
        dict(min_amount=Decimal("50270"), max_amount=None,             rate_pct=Decimal("2"),    employer_rate_pct=Decimal("15"), rate_label="2%/15%",    tax_formula="", rule_type="NI_BAND", ni_category="V", sort_order=148),
        # Category Z — under 21, deferment.
        dict(min_amount=Decimal("0"),     max_amount=Decimal("12570"), rate_pct=Decimal("0"),    employer_rate_pct=Decimal("0"),  rate_label="0%/0%",     tax_formula="", rule_type="NI_BAND", ni_category="Z", sort_order=149),
        dict(min_amount=Decimal("12570"), max_amount=Decimal("50270"), rate_pct=Decimal("2"),    employer_rate_pct=Decimal("0"),  rate_label="2%/0%",     tax_formula="", rule_type="NI_BAND", ni_category="Z", sort_order=150),
        dict(min_amount=Decimal("50270"), max_amount=None,             rate_pct=Decimal("2"),    employer_rate_pct=Decimal("15"), rate_label="2%/15%",    tax_formula="", rule_type="NI_BAND", ni_category="Z", sort_order=151),
    ],
    # Enterprise Policy jurisdictions — representative/simplified brackets,
    # genuinely read by the engine (see _CONTRIBUTION_RATES_BY_COUNTRY note
    # above). Verify against current statutory brackets before production use.
    "AU": [
        # Resident individual rates, simplified (excludes Medicare Levy,
        # calculated separately in _calc_australia).
        dict(min_amount=Decimal("0"),       max_amount=Decimal("18200"),    rate_pct=Decimal("0"),   rate_label="0%",   tax_formula="Tax-free threshold", sort_order=1),
        dict(min_amount=Decimal("18200"),   max_amount=Decimal("45000"),    rate_pct=Decimal("16"),  rate_label="16%",  tax_formula="16% of income above A$18,200", sort_order=2),
        dict(min_amount=Decimal("45000"),   max_amount=Decimal("135000"),   rate_pct=Decimal("30"),  rate_label="30%",  tax_formula="A$4,288 + 30% above A$45,000", sort_order=3),
        dict(min_amount=Decimal("135000"),  max_amount=Decimal("190000"),   rate_pct=Decimal("37"),  rate_label="37%",  tax_formula="A$31,288 + 37% above A$135,000", sort_order=4),
        dict(min_amount=Decimal("190000"),  max_amount=None,                rate_pct=Decimal("45"),  rate_label="45%",  tax_formula="A$51,638 + 45% above A$190,000", sort_order=5),
    ],
    "DE": [
        # Simplified bracket approximation of Germany's continuous income
        # tax formula (real Lohnsteuer uses a smooth curve, not flat bands).
        # Boundaries are expressed in TAXABLE-income terms (i.e. already
        # net of the Grundfreibetrag) — _calculate_annual_tax_de subtracts
        # the "grundfreibetrag" parameter (engine/standard.py) from annual
        # gross BEFORE applying these slabs, so there is no separate 0%
        # bracket here (that would double-count the same tax-free zone
        # the parameter already represents).
        dict(min_amount=Decimal("0"),       max_amount=Decimal("5216"),     rate_pct=Decimal("14"),  rate_label="14%",  tax_formula="14% of taxable income (after Grundfreibetrag)", sort_order=1),
        dict(min_amount=Decimal("5216"),    max_amount=Decimal("54216"),    rate_pct=Decimal("30"),  rate_label="30%",  tax_formula="€730 + 30% above €5,216 taxable", sort_order=2),
        dict(min_amount=Decimal("54216"),   max_amount=Decimal("265216"),   rate_pct=Decimal("42"),  rate_label="42%",  tax_formula="€15,430 + 42% above €54,216 taxable", sort_order=3),
        dict(min_amount=Decimal("265216"),  max_amount=None,                rate_pct=Decimal("45"),  rate_label="45%",  tax_formula="€104,050 + 45% above €265,216 taxable", sort_order=4),
    ],
    "CA": [
        # 2026 federal brackets per ZP-TAX-CA-2026-001 §6 (CRA T4127 122nd
        # Ed.) — provincial tax still excluded for simplicity (see canada.py).
        dict(min_amount=Decimal("0"),       max_amount=Decimal("58523"),    rate_pct=Decimal("14"),    rate_label="14%",    tax_formula="14% of income", sort_order=1),
        dict(min_amount=Decimal("58523"),   max_amount=Decimal("117045"),   rate_pct=Decimal("20.5"),  rate_label="20.5%",  tax_formula="C$8,193 + 20.5% above C$58,523", sort_order=2),
        dict(min_amount=Decimal("117045"),  max_amount=Decimal("181440"),   rate_pct=Decimal("26"),    rate_label="26%",    tax_formula="C$20,190 + 26% above C$117,045", sort_order=3),
        dict(min_amount=Decimal("181440"),  max_amount=Decimal("258482"),   rate_pct=Decimal("29"),    rate_label="29%",    tax_formula="C$36,933 + 29% above C$181,440", sort_order=4),
        dict(min_amount=Decimal("258482"),  max_amount=None,                rate_pct=Decimal("33"),    rate_label="33%",    tax_formula="C$59,275 + 33% above C$258,482", sort_order=5),
    ],
}


# ═════════════════════════════════════════════════════════════════════
# Per-country engine fallback constants (previously one block per file
# in engine/countries/*.py). Read via resolve_jurisdiction_parameter()
# only when no DB row (org-scoped or canonical) exists at all for that
# parameter — the deepest fallback layer.
# ═════════════════════════════════════════════════════════════════════

# ── India (previously engine/countries/india.py) ───────────────────────
ESI_MONTHLY_WAGE_CEILING = Decimal("21000")
_IN_STANDARD_DEDUCTION = Decimal("75000")
# Old Regime's own standard deduction — only read when ctx.tax_regime == "Old".
_IN_STANDARD_DEDUCTION_OLD = Decimal("50000")
# New Regime Section 87A defaults (today's only regime, unchanged).
_IN_REBATE_87A_LIMIT = Decimal("1200000")
_IN_REBATE_87A_MAX = Decimal("60000")
# Old Regime Section 87A defaults — only read when ctx.tax_regime == "Old".
_IN_REBATE_87A_LIMIT_OLD = Decimal("500000")
_IN_REBATE_87A_MAX_OLD = Decimal("12500")
# Health & Education Cess — applied on (tax + surcharge).
_IN_CESS_PCT = Decimal("4")
# EPF statutory wage ceiling (ZP-TAX-IN-2026-27-001 §9.1) — only read when
# _IN_PF_WAGE_CEILING_ENABLED_COUNTRIES has "IN" (see shared.py).
_IN_PF_WAGE_CEILING = Decimal("15000")

# ── United States (previously engine/countries/us.py) ──────────────────
_US_STANDARD_DEDUCTION = Decimal("15000")
_US_SOCIAL_SECURITY_WAGE_BASE = Decimal("176100")
_US_SOCIAL_SECURITY_RATE = Decimal("6.2")
_US_MEDICARE_RATE = Decimal("1.45")
_US_MEDICARE_ADDITIONAL_RATE = Decimal("0.9")
# The real IRS thresholds differ by W-4 filing status (only MFJ/MFS
# actually diverge from the Single/HOH figure) — this dict is the
# DEFAULT used when Super Admin hasn't configured a filing-status-tagged
# "medicare_addl_thresh" ContributionRate row (a configured row always
# wins). Falls back to the flat constant below for a missing/unrecognized
# filing_status (None — every employee before w4_filing_status existed,
# and any status outside the four known codes).
_US_MEDICARE_ADDL_THRESHOLD_DEFAULTS = {
    "SINGLE": Decimal("200000"),
    "HOH": Decimal("200000"),
    "MFJ": Decimal("250000"),
    "MFS": Decimal("125000"),
}
_US_MEDICARE_ADDITIONAL_THRESHOLD = Decimal("200000")
# Real FUTA is 6.0% on the first $7,000 of annual wages per employee,
# BEFORE the standard state-unemployment-tax credit.
_US_FUTA_RATE = Decimal("6.0")
_US_FUTA_WAGE_BASE = Decimal("7000")
# The standard federal credit against FUTA for timely-paid state
# unemployment tax — a stable, Congress-set number (IRC §3302). Applied
# only when an employer_tax_profiles["SUI"] entry exists.
_US_FUTA_CREDIT_PCT = Decimal("5.4")

# ── United Kingdom (previously engine/countries/uk.py) ──────────────────
_UK_PERSONAL_ALLOWANCE = Decimal("12570")
_UK_PA_TAPER_THRESHOLD = Decimal("100000")
_UK_NI_PRIMARY_THRESHOLD = Decimal("12570")
_UK_NI_UPPER_THRESHOLD = Decimal("50270")
_UK_NI_PRIMARY_RATE = Decimal("8")
_UK_NI_UPPER_RATE = Decimal("2")
_UK_PENSION_MIN_ENPLOYER = Decimal("3")
# K-code overriding limit (ZP-TAX-UK-2026-27-001 §6.2: "tax deduction
# cannot exceed 50% of pre-tax pay/pension for the pay period"). Was
# briefly inline as a bare Decimal("0.5") in uk.py — moved here so it's
# Super-Admin-editable like every other UK figure, not a code-only value.
_UK_K_CODE_CAP_PCT = Decimal("50")
# Employer NI — Secondary Threshold + standard employer rate. Per
# ZP-TAX-UK-2026-27-001 section 8.1/9.1: ST is £5,000 annual (2026-27),
# below the LEL (£6,708) — that gap is real, not a typo (see uk.py's
# _resolve_ni_bands docstring for why LEL itself never needs to be a
# breakpoint). Standard (Category A/B/C/J) employer rate is 15% for 2026-27.
_UK_NI_SECONDARY_THRESHOLD = Decimal("5000")
_UK_NI_EMPLOYER_RATE = Decimal("15")
# Real 2025/26 Qualifying Earnings band for Workplace Pension auto-enrolment.
_UK_PENSION_QE_LOWER = Decimal("6240")
_UK_PENSION_QE_UPPER = Decimal("50270")
# Student/Postgraduate Loan — real UK mechanism. Plan 5 covers post-2023
# starters (in effect from April 2026). Any other/unset study_loan_plan
# value deducts 0, same as having no loan at all. 2026-27 thresholds per
# ZP-TAX-UK-2026-27-001 section 10.1.
_UK_STUDENT_LOAN_PLANS = {
    "UK_PLAN1": (Decimal("26900"), Decimal("9")),
    "UK_PLAN2": (Decimal("29385"), Decimal("9")),
    "UK_PLAN4": (Decimal("33795"), Decimal("9")),
    "UK_PLAN5": (Decimal("25000"), Decimal("9")),
    "UK_POSTGRAD": (Decimal("21000"), Decimal("6")),
}
# 2026-27 special single-rate PAYE codes (ZP-TAX-UK-2026-27-001 section
# 6.3) — flat percentage on all pay, no Personal Allowance. The S/C prefix
# selects which regional rate a BR/D-family code actually means (Scottish
# SD0-3 have no rUK equivalent letter, Welsh C-codes mirror rUK 2026-27).
_UK_FLAT_RATE_CODES = {
    "BR": Decimal("20"), "D0": Decimal("40"), "D1": Decimal("45"),
    "SBR": Decimal("20"), "SD0": Decimal("21"), "SD1": Decimal("42"), "SD2": Decimal("45"), "SD3": Decimal("48"),
    "CBR": Decimal("20"), "CD0": Decimal("40"), "CD1": Decimal("45"),
}
# Real, independently-published Weekly/Monthly NI thresholds
# (ZP-TAX-UK-2026-27-001 section 8.1) — used only behind
# _UK_NI_DIRECT_PERIOD_CALC_ENABLED_COUNTRIES (shared.py) via
# resolve_direct_period_threshold. These do NOT derive from the annual
# figures above by simple division (e.g. PT annual £12,570 ÷ 12 =
# £1,047.50, not the real published £1,048 monthly figure) — HMRC rounds
# each period's table independently, so both must be stored, not computed.
_UK_NI_PRIMARY_THRESHOLD_BY_FREQUENCY = {"Weekly": Decimal("242"), "Monthly": Decimal("1048")}
_UK_NI_UPPER_THRESHOLD_BY_FREQUENCY = {"Weekly": Decimal("967"), "Monthly": Decimal("4189")}
_UK_NI_SECONDARY_THRESHOLD_BY_FREQUENCY = {"Weekly": Decimal("96"), "Monthly": Decimal("417")}

# ── Australia (previously engine/countries/australia.py) ────────────────
_AU_MEDICARE_LEVY_LOW_INCOME_THRESHOLD = Decimal("24276")
_AU_MLS_THRESHOLD = Decimal("97000")
_AU_MLS_RATE = Decimal("1.0")
_AU_SUPER_MAX_CONTRIBUTION_BASE = Decimal("260280")
# HELP/HECS is a real multi-band repayment schedule (0% up to ~10% as
# income rises); simplified here to its lowest real band as a single
# threshold+rate — a genuine multi-band HELP schedule is a larger
# follow-on, not this pass's scope.
_AU_HELP_THRESHOLD = Decimal("54435")
_AU_HELP_RATE = Decimal("4.5")

# ── Germany (previously engine/countries/germany.py) ────────────────────
_DE_GRUNDFREIBETRAG = Decimal("11784")
_DE_CONTRIBUTION_CEILING = Decimal("96600")
_DE_SOLI_THRESHOLD = Decimal("18130")
_DE_SOLI_RATE = Decimal("5.5")
# Kirchensteuer (church tax) — a % surcharge on the base income tax
# (before Soli), only for employees who opt in (church_tax_liable). Real
# rate varies by federal state (8% in Bavaria/Baden-Württemberg, 9%
# elsewhere); 9% is used as the representative default.
_DE_CHURCH_TAX_RATE = Decimal("9")

# ── Canada (previously engine/countries/canada.py) ──────────────────────
# 2026 values per ZP-TAX-CA-2026-001 (CRA T4127 122nd Ed., effective
# Jan 1 2026). _CA_BASIC_PERSONAL_AMOUNT is BPAF at NI <= $181,440 (the
# income-tapered reduction between $181,440 and $258,482 down to
# _CA_BPAF_MIN is implemented in canada.py's _resolve_ca_bpaf()).
_CA_CPP_YMPE = Decimal("74600")
_CA_CPP_BASIC_EXEMPTION = Decimal("3500")
_CA_EI_MIE = Decimal("68900")
_CA_BASIC_PERSONAL_AMOUNT = Decimal("16452")
# CPP2 — the real, current (2024+) second-tier CPP contribution on
# earnings between the YMPE and the Year's Additional Maximum
# Pensionable Earnings (YAMPE), employee and employer each.
_CA_CPP2_YAMPE = Decimal("85000")
_CA_CPP2_RATE = Decimal("4")
# BPAF income-taper bounds (doc §6): BPAF = BPAF_MAX below the low
# threshold, linearly reduced to BPAF_MIN by the high threshold, flat
# BPAF_MIN above it.
_CA_BPAF_MIN = Decimal("14829")
_CA_BPAF_NI_THRESHOLD_LOW = Decimal("181440")
_CA_BPAF_NI_THRESHOLD_HIGH = Decimal("258482")
# Canada Employment Amount — non-refundable credit converted to a tax
# reduction at the lowest federal rate (doc §6), wired into
# _calculate_annual_tax_ca.
_CA_CEA = Decimal("1501")
_CA_LOWEST_FEDERAL_RATE = Decimal("14")
# Quebec abatement is wired into calculate() unconditionally (Phase 2).
# The beyond-province surtax and LSVCC credit are ALSO wired in now
# (Phase 8), each behind its own dormant rollout switch — see
# shared._CA_BEYOND_PROVINCE_SURTAX_ENABLED_COUNTRIES /
# _CA_LSVCC_CREDIT_ENABLED_COUNTRIES — since the surtax needs an
# employee's work_state manually set to the CA-XP code "XP" (no
# automated POE path produces it yet — that's Phase 9's scope) and the
# credit needs an employee LSVCC-investment declaration most orgs won't
# have entered.
_CA_QUEBEC_FEDERAL_ABATEMENT_PCT = Decimal("16.5")
_CA_BEYOND_PROVINCE_SURTAX_PCT = Decimal("48")
_CA_LSVCC_CREDIT_RATE = Decimal("15")
_CA_LSVCC_CREDIT_MAX = Decimal("750")


# ═════════════════════════════════════════════════════════════════════
# US state-level canonical seed data (ZP-TAX-US-2026-001) — consumed by
# scripts/populate_us_state_tax_v1.py, a SEPARATE script from
# populate_canonical_tax_v1.py: that script only ever seeds the
# country-level (jurisdiction_state IS NULL) pack for each country and
# upserts ContributionRate rows by component_key alone, with no
# jurisdiction_state in its matching filter — feeding it state-scoped data
# would either attach state rows to the wrong (country-level) pack or let
# two different states' same-keyed rows silently overwrite each other.
# Kept in this file anyway per this file's own rule (see module docstring):
# every hardcoded statutory default value lives here, regardless of which
# script/module eventually consumes it.
# ═════════════════════════════════════════════════════════════════════

# Phase 1 (ZP-TAX-US-2026-001 §4): states with confirmed no individual wage
# income tax. Seeded as an Active JurisdictionPack with ZERO TaxSlab rows —
# this changes no calculated number (an unconfigured state already
# resolves state_income_tax=0 today; see us.py's own comment on
# ctx.state_slabs) — it only makes "confirmed no tax" distinguishable from
# "nobody has built this state yet" via an evidenced, Active pack record.
_US_NO_INCOME_TAX_STATES = {
    "AK": "Alaska Department of Revenue / Tax Division",
    "FL": "Florida Department of Revenue",
    "NV": "Nevada Department of Taxation",
    "NH": "New Hampshire DRA",
    "SD": "South Dakota DOR",
    "TN": "Tennessee DOR",
    "TX": "Texas Comptroller / TWC",
    # WA has no wage income tax but DOES have its own statutory programs
    # (Paid Family & Medical Leave, WA Cares Fund) — those are Phase 3
    # scope (_US_STATE_PROGRAM_ENABLED_STATES), tracked separately from
    # this "no income tax" pack, same reasoning as the module comment above
    # explaining why the two rollout switches are independent.
    "WA": "WA ESD / WA Cares Fund",
    "WY": "Wyoming DWS / DOR",
}

# Phase 2 (ZP-TAX-US-2026-001 §3.1's Colorado example, §4, Appendix A): the
# only two "official tables/formula" states with a COMPLETE, literal
# formula given in that document rather than just a method classification
# — every other "official tables" state's actual bracket values are
# explicitly out of scope until their real published tables are supplied
# (see the plan's "Explicitly out of scope" section). Read behind
# _US_STATE_TAX_ENABLED_STATES (shared.py) — dormant by default.
#
# allowance_by_filing_status: a state-level standard-deduction-equivalent,
# resolved via ContributionRate component_key="state_standard_deduction"
# (us.py's calculate()), filing_status=None meaning "applies regardless of
# filing status" — same NULL-is-the-fallback convention as the federal
# standard_deduction rows above. Colorado's own filing-status label is
# "MFJ_OR_QSS" (DR 1098) — mapped to this codebase's "MFJ" tag, since
# Qualifying Surviving Spouse isn't a status USEmployeeValidation's
# w4_filing_status vocabulary supports at all (a pre-existing gap,
# unrelated to this build).
_US_STATE_TAX_RATES = {
    "CO": dict(
        agency="Colorado DOR",
        source_title="DR 1098 - Colorado Withholding Worksheet for Employers (2026)",
        rate_pct=Decimal("4.40"),
        allowance_by_filing_status={"MFJ": Decimal("11000.00"), None: Decimal("5500.00")},
    ),
    "KY": dict(
        agency="Kentucky DOR",
        source_title="2026 Kentucky Withholding Tax Formula 42A003 (TCF)",
        rate_pct=Decimal("3.50"),
        allowance_by_filing_status={None: Decimal("3360.00")},
    ),
}

# Phase 3 (ZP-TAX-US-2026-001 §5): state-level statutory payroll programs
# beyond plain income-tax withholding, for the states/programs the
# document gives a COMPLETE, literal rate/cap for. Read behind
# _US_STATE_PROGRAM_ENABLED_STATES (shared.py) — dormant by default; see
# us.py's calculate() for the generic per-state-program loop that consumes
# this. Headcount/employer-split-conditional programs (CO FAMLI, DE Paid
# Leave, MA/ME/MN/OR Paid Leave, WA PFML) need a new employer
# covered-headcount primitive and are explicitly a separate, later phase
# — not included here.
#
# wage_cap: caps the ANNUAL TAXABLE WAGE the rate applies to (None =
# uncapped) — several of these coincide with the SS wage base ($184,500)
# today, but are stored as their own independent figure since the document
# sources them independently and they could diverge in a future year.
# annual_max: caps the resulting DOLLAR AMOUNT itself (None = uncapped) —
# a distinct concept from wage_cap (see NY PFL, which has no wage_cap but
# does have a $411.91 annual dollar maximum).
_US_STATE_PROGRAMS = {
    "CA": {
        "sdi": dict(
            agency="California EDD", source_title="EDD 2026 SDI contribution rate release",
            employee_rate_pct=Decimal("1.30"), employer_rate_pct=None, wage_cap=None, annual_max=None,
        ),
    },
    "CT": {
        "paid_leave": dict(
            agency="Connecticut Paid Leave", source_title="Connecticut Paid Leave — 2026 contributions",
            employee_rate_pct=Decimal("0.50"), employer_rate_pct=None, wage_cap=Decimal("184500.00"), annual_max=None,
        ),
    },
    "DC": {
        "paid_leave": dict(
            agency="DC DOES", source_title="2026 Paid Family Leave tax calculator/rates",
            employee_rate_pct=None, employer_rate_pct=Decimal("0.75"), wage_cap=None, annual_max=None,
        ),
    },
    "NY": {
        "paid_leave": dict(
            agency="New York Tax", source_title="NYS-50-T-NYS (1/26)",
            employee_rate_pct=Decimal("0.432"), employer_rate_pct=None, wage_cap=None, annual_max=Decimal("411.91"),
        ),
    },
    "RI": {
        "tdi": dict(
            agency="Rhode Island DLT", source_title="2026 UI and TDI Quick Reference",
            employee_rate_pct=Decimal("1.10"), employer_rate_pct=None, wage_cap=Decimal("100000.00"), annual_max=Decimal("1100.00"),
        ),
    },
    "WA": {
        "wa_cares": dict(
            agency="WA ESD / WA Cares Fund", source_title="WA Cares Fund — 2026 employee premium",
            employee_rate_pct=Decimal("0.58"), employer_rate_pct=None, wage_cap=None, annual_max=None,
        ),
    },
    "NJ": {
        "worker_ui": dict(
            agency="New Jersey Treasury/DOL", source_title="2026 wage and worker contribution reporting notice",
            employee_rate_pct=Decimal("0.3825"), employer_rate_pct=None, wage_cap=Decimal("44800.00"), annual_max=None,
        ),
        "worker_di": dict(
            agency="New Jersey Treasury/DOL", source_title="2026 wage and worker contribution reporting notice",
            employee_rate_pct=Decimal("0.19"), employer_rate_pct=None, wage_cap=Decimal("171100.00"), annual_max=Decimal("325.09"),
        ),
        "workforce_dev": dict(
            agency="New Jersey Treasury/DOL", source_title="2026 wage and worker contribution reporting notice",
            employee_rate_pct=Decimal("0.0425"), employer_rate_pct=None, wage_cap=Decimal("44800.00"), annual_max=None,
        ),
        "fli": dict(
            agency="New Jersey Treasury/DOL", source_title="2026 wage and worker contribution reporting notice",
            employee_rate_pct=Decimal("0.23"), employer_rate_pct=None, wage_cap=Decimal("171100.00"), annual_max=Decimal("393.53"),
        ),
    },
}

# Phase 4 (ZP-TAX-US-2026-001 §7): local (county/municipal/school-district)
# tax data — structural, not a full register. Detroit's own two rates are
# given directly in the document's Appendix A, so those are seeded as real
# LocalityRate rows; Indiana's dataset is created EMPTY on purpose — the
# document requires an effective-dated locality dataset mechanism for
# Indiana's 92 counties (not a free-text county field) but does not itself
# reproduce the real Departmental Notice #1 county-rate table, so no county
# rate is fabricated here. No engine change needed: get_locality_rate/
# LocalityRate already exist and are read unconditionally by us.py (no
# rollout switch — a locality only ever applies when an employee's own
# work_locality is explicitly set to a matching code, so seeding real data
# here cannot silently change any existing employee's number).
_US_STATE_HEADCOUNT_PROGRAMS = {
    # Phase 3C (ZP-TAX-US-2026-001 §5): headcount-conditional state
    # programs — the EMPLOYEE rate always applies; the EMPLOYER rate only
    # applies once EmployerTaxProfile.covered_employee_count (a real Tax
    # Ops entry, never inferred) meets employer_headcount_min for this
    # (org, jurisdiction, employer_component_code). Read by us.py's
    # dedicated headcount-gated block, behind
    # _US_STATE_PROGRAM_ENABLED_STATES (shared.py) same as every other
    # state program.
    #
    # Only states where the document gives a COMPLETE numeric threshold
    # AND a complete employee/employer split are included:
    # - Massachusetts: gives the 25-employee threshold but explicitly says
    #   "contribution split must be configured" — no split given.
    # - Minnesota: gives "large" vs "qualifying small employer" rate
    #   splits but NO numeric headcount threshold distinguishing them.
    # - Oregon: gives the large-employer split (60/40) but no numeric
    #   threshold defining "large", and no split at all for its
    #   small-employer exception.
    # All three are deferred — building them would require inventing a
    # number the source document doesn't give.
    "CO": {
        "famli": dict(
            agency="Colorado CDLE", source_title="FAMLI program",
            employee_rate_pct=Decimal("0.44"), employer_rate_pct=Decimal("0.44"),
            employer_headcount_min=10, employer_component_code="FAMLI",
        ),
    },
    "ME": {
        "paid_leave": dict(
            agency="Maine DOL", source_title="Maine Paid Family and Medical Leave",
            employee_rate_pct=Decimal("0.50"), employer_rate_pct=Decimal("0.50"),
            employer_headcount_min=15, employer_component_code="PAID_LEAVE",
        ),
    },
    "WA": {
        # 1.13% total; employee share 71.43%, employer 28.57% at 50+
        # employees. 1.13 * 71.43% = 0.8069% (employee, unconditional);
        # 1.13 * 28.57% = 0.3228% (employer, only at 50+ — "generally no
        # employer premium obligation" below 50, employee share still
        # remitted regardless).
        "pfml": dict(
            agency="Employment Security Department (WA)", source_title="Washington programs — 2026 Paid Leave total premium",
            employee_rate_pct=Decimal("0.8069"), employer_rate_pct=Decimal("0.3228"),
            employer_headcount_min=50, employer_component_code="PFML",
        ),
    },
}

# Delaware Paid Leave (ZP-TAX-US-2026-001 §5) — a genuinely different
# shape from the simple gated-employer-share programs above: headcount
# SELECTS which of two employer-side coverage tiers applies (not just
# on/off), so it's modeled and read separately in us.py rather than
# through the generic headcount-gate loop. <=9 employees: exempt (0, not
# modeled — absence of any configured tier IS the correct $0 outcome).
# Employee share: the document permits the employer to pass up to 50% to
# employees but gives no specific elected fraction, so this defaults to
# 0% employee / 100% employer-funded — the document's own stated baseline
# ("Employer; employee share PERMITTED"), not a fabricated split.
_US_DE_PAID_LEAVE = dict(
    agency="Delaware DOL", source_title="Delaware Paid Leave",
    parental_only_rate_pct=Decimal("0.32"), parental_only_min=10,
    full_coverage_rate_pct=Decimal("0.80"), full_coverage_min=25,
    employer_component_code="PAID_LEAVE",
)

_US_LOCALITY_DATA = {
    "MI": dict(
        agency="Michigan Treasury", source_title="2026 City of Detroit Income Tax Withholding Guide",
        rates=[
            dict(locality_code="DETROIT", locality_type="MUNICIPAL", locality_name="Detroit",
                 resident_rate_pct=Decimal("2.40"), nonresident_rate_pct=Decimal("1.20")),
        ],
    ),
    "IN": dict(
        agency="Indiana DOR", source_title="Departmental Notice #1 (2026)",
        rates=[],
    ),
}


# ═════════════════════════════════════════════════════════════════════
# Payroll Policy defaults (previously policy/models.py column defaults) —
# organizational compensation-structure/attendance choices, not
# statutory tax data, but hardcoded defaults all the same.
# ═════════════════════════════════════════════════════════════════════

# PayrollPolicy.basic_pct/hra_pct — what share of monthly gross becomes
# Basic vs HRA (Special Allowance is always the remainder). Only applies
# to employees who don't have their own explicit Basic/HRA amounts set.
_POLICY_DEFAULT_BASIC_PCT = 40
_POLICY_DEFAULT_HRA_PCT = 20

# service.py's _resolve_salary_split_pct fallback — used at PAYROLL RUN
# time when an org has no PayrollPolicy row at all (or organization_id is
# unavailable). Every org with its own PayrollPolicy.basic_pct/hra_pct is
# unaffected by this constant either way; see _POLICY_DEFAULT_BASIC_PCT/
# _POLICY_DEFAULT_HRA_PCT above for that path. Deliberately a different
# value (50/40, not 40/20) — set directly by Venu in this file's previous
# location; not the same default as the PayrollPolicy column default.
_DEFAULT_BASIC_PCT = Decimal("50")
_DEFAULT_HRA_PCT = Decimal("40")

# PolicyEmployeeCategory defaults (Full Time, Part Time, Intern, ...).
_POLICY_DEFAULT_WORKING_DAYS = 5
_POLICY_DEFAULT_EXPECTED_HOURS = 8
_POLICY_DEFAULT_MINIMUM_HOURS = 4
_POLICY_DEFAULT_GRACE_TIME_MINUTES = 10

# PolicyOvertimeRule default.
_POLICY_DEFAULT_MINIMUM_OVERTIME_MINUTES = 30
