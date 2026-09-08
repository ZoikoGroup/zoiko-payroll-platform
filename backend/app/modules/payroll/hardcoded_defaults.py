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
        dict(component_key="ni_secondary_thresh", label="NI Secondary Threshold (Employer)",
             employee_share="—", employer_share="—", total="£9,100",
             flat_amount=Decimal("9100.00"), sort_order=7),
        dict(component_key="ni_upper_rate", label="NI Upper Rate (Employee)",
             employee_share="2%", employer_share="—", total="2%",
             employee_rate_pct=Decimal("2.00"), sort_order=8),
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
        dict(component_key="cpp", label="Canada Pension Plan (CPP)",
             employee_share="5.95%", employer_share="5.95%", total="11.9%",
             employee_rate_pct=Decimal("5.95"), employer_rate_pct=Decimal("5.95"), sort_order=1),
        dict(component_key="ei", label="Employment Insurance (EI)",
             employee_share="1.66%", employer_share="2.32%", total="3.98%",
             employee_rate_pct=Decimal("1.66"), employer_rate_pct=Decimal("2.32"), sort_order=2),
        dict(component_key="income-tax", label="Federal Income Tax",
             employee_share="As per income slab", employer_share="—", total="As per slab",
             sort_order=3),
        # componentKey max 20 chars (payroll_contribution_rates.component_key
        # is VARCHAR(20)) — "basic_personal_amount" (21 chars) always 500'd
        # on insert. Also renamed in canada.py's resolve_jurisdiction_parameter()
        # call and fallback_registry.py.
        dict(component_key="basic_personal_amt", label="Basic Personal Amount",
             employee_share="—", employer_share="—", total="C$15,705",
             flat_amount=Decimal("15705.00"), sort_order=4),
        dict(component_key="cpp_ympe", label="CPP Year's Maximum Pensionable Earnings (YMPE)",
             employee_share="—", employer_share="—", total="C$71,300",
             flat_amount=Decimal("71300.00"), sort_order=5),
        dict(component_key="cpp_basic_exemption", label="CPP Basic Exemption Amount",
             employee_share="—", employer_share="—", total="C$3,500",
             flat_amount=Decimal("3500.00"), sort_order=6),
        dict(component_key="ei_mie", label="EI Maximum Insurable Earnings",
             employee_share="—", employer_share="—", total="C$65,700",
             flat_amount=Decimal("65700.00"), sort_order=7),
        dict(component_key="cpp2_yampe", label="CPP2 Year's Additional Maximum Pensionable Earnings (YAMPE)",
             employee_share="—", employer_share="—", total="C$81,200",
             flat_amount=Decimal("81200.00"), sort_order=8),
        dict(component_key="cpp2_rate", label="CPP2 Rate",
             employee_share="4%", employer_share="—", total="4%",
             employee_rate_pct=Decimal("4.00"), sort_order=9),
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
        # Federal brackets only — provincial tax excluded for simplicity.
        dict(min_amount=Decimal("0"),       max_amount=Decimal("55000"),    rate_pct=Decimal("15"),    rate_label="15%",    tax_formula="15% of income", sort_order=1),
        dict(min_amount=Decimal("55000"),   max_amount=Decimal("111000"),   rate_pct=Decimal("20.5"),  rate_label="20.5%",  tax_formula="C$8,250 + 20.5% above C$55,000", sort_order=2),
        dict(min_amount=Decimal("111000"),  max_amount=Decimal("173000"),   rate_pct=Decimal("26"),    rate_label="26%",    tax_formula="C$19,730 + 26% above C$111,000", sort_order=3),
        dict(min_amount=Decimal("173000"),  max_amount=Decimal("246000"),   rate_pct=Decimal("29"),    rate_label="29%",    tax_formula="C$35,850 + 29% above C$173,000", sort_order=4),
        dict(min_amount=Decimal("246000"),  max_amount=None,                rate_pct=Decimal("33"),    rate_label="33%",    tax_formula="C$57,020 + 33% above C$246,000", sort_order=5),
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
# NOTE (Phase 7): this legacy constant/rate model is superseded for the
# production Germany calculation path by
# engine/countries/germany_pap.CHURCH_TAX_LAND_RATES (per-Land 8%/9% table,
# ZP-TAX-DE-2026-001 §8), driven by EmployeeStatutoryProfile.de_church_tax_land
# rather than a single flat rate. Kept here only because
# PayrollEmployee.church_tax_liable / _calculate_legacy_simplified still
# reference it (legacy path, not called by production `calculate()` — see
# germany.py).
_DE_CHURCH_TAX_RATE = Decimal("9")

# ── Germany — 2026 Social-Insurance Core Rates (Phase 7) ────────────────
# ZP-TAX-DE-2026-001 §9 "2026 Social-Insurance Core Rates and Ceilings" —
# these are the literal published 2026 total/employee/employer splits for
# the four independently-capped branches (RV/ALV/GKV general/PV base is
# handled separately by the Phase 6 GermanyPvConfiguration registry, not
# here). DB-overridable fallbacks, resolved via resolve_jurisdiction_parameter
# exactly like every other DE constant in this file — NOT invented, and
# distinct from GermanyContributionCeiling (Phase 5, the CAP each of these
# rates applies against) and GermanyHealthFund (Phase 4, the fund-specific
# supplementary rate added on top of the GKV general rate below).
_DE_RV_EMPLOYEE_RATE = Decimal("9.30")          # Rentenversicherung, spec §9
_DE_RV_EMPLOYER_RATE = Decimal("9.30")
_DE_ALV_EMPLOYEE_RATE = Decimal("1.30")         # Arbeitslosenversicherung, spec §9
_DE_ALV_EMPLOYER_RATE = Decimal("1.30")
# "Statutory health insurance — general" row, spec §9. The "reduced" row
# (14.00%/7.00%/7.00%, for employees without statutory sick-pay
# entitlement) is NOT selectable from any current EmployeeStatutoryProfile
# field — NOT SPECIFIED IN PROVIDED GERMANY DOCUMENTATION as a
# machine-readable classifier — so only the general rate is implemented;
# see germany_pap.py's module docstring for this disclosed limitation.
_DE_GKV_GENERAL_EMPLOYEE_RATE = Decimal("7.30")
_DE_GKV_GENERAL_EMPLOYER_RATE = Decimal("7.30")

# ── Germany — 2026 Minijob / Midijob (Phase 8I) ─────────────────────────
# Literal values from the supplied Zoiko Germany 2026 statutory
# documentation (this phase's own brief §4) — none invented, none
# extrapolated. Minijob and Midijob are entirely separate mechanisms from
# the RV/ALV/GKV/PV branch rates above: Minijob uses flat employer-paid
# percentages + a flat employee pension top-up + a flat employer-remitted
# tax, never the branch rates; Midijob uses a sliding-scale contribution-
# base formula whose application to the four individually-ceilinged
# branches is NOT fully specified (see germany_pap/core.py's
# calculate_midijob_* docstrings and Phase 8I's own report §11/§31 for the
# disclosed boundary — the two formulas below are implemented exactly as
# given and are NOT, by themselves, applied to produce a contribution
# amount in this phase).

# Corridor boundaries. Minijob is valid for monthly earnings <= this
# threshold; Midijob is valid for earnings strictly greater than it (i.e.
# >= 603.01 at 2-decimal precision) and <= the upper threshold.
_DE_MINIJOB_UPPER_THRESHOLD = Decimal("603.00")
_DE_MIDIJOB_UPPER_THRESHOLD = Decimal("2000.00")

# Minijob employer flat contributions (spec §4) — always employer-paid,
# never deducted from employee net pay.
_DE_MINIJOB_EMPLOYER_HEALTH_RATE = Decimal("13")
_DE_MINIJOB_EMPLOYER_PENSION_RATE = Decimal("15")
_DE_MINIJOB_U1_RATE = Decimal("0.80")
_DE_MINIJOB_U2_RATE = Decimal("0.22")
_DE_MINIJOB_U3_RATE = Decimal("0.15")

# Minijob employee pension top-up — the ONLY Minijob component that
# reduces employee net pay, and only when the employee has not opted out
# (de_pension_insurance_exempt = false, reusing the same statutory-profile
# field the ordinary RV branch already uses for its own exemption).
_DE_MINIJOB_EMPLOYEE_PENSION_TOPUP_RATE = Decimal("3.60")

# Minijob flat tax (Pauschsteuer) — per the supplied specification's own
# three-way grouping (Employer / Employee / Tax, listed as distinct
# categories, spec §4), this is treated as an employer-remitted flat tax,
# consistent with the real-world Minijob-Zentrale pauschal-tax mechanism
# (the employer, not the employee, is liable for and remits this amount) —
# NOT deducted from employee net pay. This is a disclosed interpretation
# of the supplied categorization, not a directly-quoted incidence rule;
# see Phase 8I's own report for the reasoning.
_DE_MINIJOB_FLAT_TAX_RATE = Decimal("2")

# Midijob sliding-scale contribution-base formula coefficients (spec §4),
# applied to AE = the relevant monthly earnings input. Implemented exactly
# as given; see calculate_midijob_total_base/calculate_midijob_employee_base.
_DE_MIDIJOB_TOTAL_BASE_MULTIPLIER = Decimal("1.1459372226")
_DE_MIDIJOB_TOTAL_BASE_SUBTRAHEND = Decimal("291.8744452399")
_DE_MIDIJOB_EMPLOYEE_BASE_MULTIPLIER = Decimal("1.43163922691")
_DE_MIDIJOB_EMPLOYEE_BASE_SUBTRAHEND = Decimal("863.2784538207")
# F-factor, recorded for trace/documentation purposes only — the two
# formulas above already have F folded into their coefficients per the
# supplied specification, so F is not separately applied anywhere in the
# calculation itself.
_DE_MIDIJOB_F_FACTOR = Decimal("0.6619")

# ── Germany — Additional 2026 reference thresholds (spec §9 "Additional
# 2026 threshold" table) — Phase 8M gap-closure audit found these were
# never captured anywhere in this codebase (no matches for JAEG,
# Bezugsgröße or the €13.90 minimum wage in any prior phase's code).
#
# JAEG (Jahresarbeitsentgeltgrenze) — the GKV compulsory-insurance
# threshold. Distinct, per spec's own acceptance criterion #20 ("JAEG 2026
# coverage threshold is represented separately from the contribution
# ceiling"), from GermanyContributionCeiling's GKV_PV branch ceiling
# (€69,750/€5,812.50 — the CAP applied to an already-PUBLIC employee's
# contribution base) — JAEG instead governs whether GKV membership is
# compulsory (at/below) or optional/PKV-eligible (above) in the first
# place. Used only for the non-blocking coverage-status warning in
# core.check_gkv_coverage_threshold() — spec §22's boundary-test list does
# not name a JAEG boundary test the way it explicitly does for Saxony
# ("validation must fail before payroll finalization"), so this is
# deliberately advisory (a trace warning), not a hard reject; inventing a
# blocking rule the spec never states would itself be a fabricated
# statutory rule.
_DE_JAEG_ANNUAL_THRESHOLD = Decimal("77400")
_DE_JAEG_MONTHLY_THRESHOLD = Decimal("6450")

# Bezugsgröße (social-insurance reference value) — spec §9 states only that
# it is "used by multiple social-insurance calculations/classifications"
# without naming which ones or how. No calculation in this codebase reads
# it (NOT SPECIFIED IN PROVIDED GERMANY DOCUMENTATION beyond the bare
# value) — stored here only as a cited reference constant so it is at
# least representable/traceable, never wired into a fabricated formula.
_DE_BEZUGSGROESSE_ANNUAL = Decimal("47460")
_DE_BEZUGSGROESSE_MONTHLY = Decimal("3955")

# Statutory minimum wage — spec §1/§9 lists this under "Compliance"
# scope, not the "Rule family" calculation scope, and no employee
# hours-worked data model exists anywhere in this codebase to compute an
# effective hourly rate against it (payroll here runs on period gross, not
# timesheets) — NOT_APPLICABLE for enforcement today; kept only as a cited
# reference value, per this phase's "do not invent a compliance engine
# the architecture cannot support" judgment call.
_DE_MINIMUM_WAGE_HOURLY = Decimal("13.90")

# Insolvency levy (U3, Insolvenzgeldumlage) — spec §14 "Insolvency levy /
# U3 || 0.15% statutory rate for 2026 ... || Federal statutory package"
# — explicitly the one employer levy the spec itself separates out as a
# flat FEDERAL rate (unlike U1/U2, which DE-D06 calls "generally
# health-fund/tariff specific" and therefore not extendable here without
# inventing per-employer tariff data). Phase 8I already implemented this
# exact 0.15% rate for Minijob only (_DE_MINIJOB_U3_RATE, same value,
# left untouched to avoid touching working code/tests); this constant is
# the general, classification-independent rate this phase wires into
# REGULAR and MIDIJOB too. Applied as a flat percentage of the period
# gross with no additional ceiling — spec states only the bare rate, no
# assessment-base cap for U3 specifically, so no cap is invented; this
# mirrors exactly how the already-shipped Minijob U1/U2/U3 computation
# itself applies its rates (flat % of monthly gross, no cap).
_DE_INSOLVENCY_LEVY_RATE = Decimal("0.15")

# PV (Pflegeversicherung) childless surcharge — §55 Abs. 3 Satz 1 SGB XI:
# "Der Beitragssatz nach Absatz 1 Satz 1 und 3 erhöht sich für Mitglieder
# ... um einen Beitragszuschlag in Höhe von 0,6 Beitragssatzpunkten."
# Confirmed live (Phase 8L) against the official law text
# (gesetze-im-internet.de/sgb_11/__55.html) and cross-corroborated as
# unchanged for 2026 (in force since 2023-07-01) via GKV-Spitzenverband's
# published 2026 Rechengrößen factsheet and multiple health-fund
# publications (TK, DAK). §58 Abs. 1 SGB XI ("Den Beitragszuschlag für
# Kinderlose ... tragen die Beschäftigten") confirms it is borne 100% by
# the employee EVERYWHERE, including Saxony — Saxony's own separate
# employee/employer split adjustment (§58 Abs. 3) governs only the BASE
# rate's allocation and does not touch this surcharge. This constant is
# therefore Land-independent by law, not an assumption; see
# calculate_midijob_pv() and Phase 8L's report §5 for the full reasoning.
_DE_PV_CHILDLESS_SURCHARGE_RATE = Decimal("0.6")

# ── Canada (previously engine/countries/canada.py) ──────────────────────
_CA_CPP_YMPE = Decimal("71300")
_CA_CPP_BASIC_EXEMPTION = Decimal("3500")
_CA_EI_MIE = Decimal("65700")
_CA_BASIC_PERSONAL_AMOUNT = Decimal("15705")
# CPP2 — the real, current (2024+) second-tier CPP contribution on
# earnings between the YMPE and the Year's Additional Maximum
# Pensionable Earnings (YAMPE), employee and employer each.
_CA_CPP2_YAMPE = Decimal("81200")
_CA_CPP2_RATE = Decimal("4")


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
