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
        # Karnataka Labour Welfare Fund (§15.1, source IN-KA-LWF) —
        # state-scoped scalar keys read via ctx.state_rate_map (india.py's
        # calculate()), same annual-not-monthly mechanism as every other
        # LWF row. Remittance window "1 January - 15 January" gives a real
        # collection month (January = 1), unlike Chennai's PT above, so
        # lwf_deduct_month is safely configurable here.
        dict(component_key="lwf_employee_amt", label="Karnataka LWF — Employee (Annual)",
             employee_share="₹50/year", employer_share="—", total="₹50",
             flat_amount=Decimal("50.00"), jurisdiction_state="Karnataka", sort_order=10),
        dict(component_key="lwf_employer_amt", label="Karnataka LWF — Employer (Annual)",
             employee_share="—", employer_share="₹100/year", total="₹100",
             flat_amount=Decimal("100.00"), jurisdiction_state="Karnataka", sort_order=11),
        dict(component_key="lwf_deduct_month", label="Karnataka LWF — Deduction Month",
             employee_share="—", employer_share="—", total="January",
             flat_amount=Decimal("1"), jurisdiction_state="Karnataka", sort_order=12),
        # Tamil Nadu Labour Welfare Fund (§15.2, source IN-TN-LWF) —
        # employee/employer amounts only; the document's own ₹20
        # State-Government third share has no payroll ledger line in this
        # engine (it's a state top-up, not an employee deduction or
        # employer liability) and is deliberately not modeled.
        # lwf_deduct_month DELIBERATELY NOT SEEDED: unlike Karnataka's
        # explicit "1 January - 15 January" window, this pack gives no
        # collection month for Tamil Nadu — leaving it unconfigured means
        # LWF resolves ₹0 every month (fail-closed), not a guessed month.
        dict(component_key="lwf_employee_amt", label="Tamil Nadu LWF — Employee (Annual)",
             employee_share="₹20/year", employer_share="—", total="₹20",
             flat_amount=Decimal("20.00"), jurisdiction_state="Tamil Nadu", sort_order=13),
        dict(component_key="lwf_employer_amt", label="Tamil Nadu LWF — Employer (Annual)",
             employee_share="—", employer_share="₹40/year", total="₹40",
             flat_amount=Decimal("40.00"), jurisdiction_state="Tamil Nadu", sort_order=14),
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
        # 2026-09-09 gap-closure Phase 1: three figures found reading a
        # bare Python literal with NO rate_map/ContributionRate row at
        # all (unlike every other UK figure) — flat-rate tax-code
        # percentages, the Weekly/Monthly direct-period NI thresholds,
        # and the Student/Postgraduate Loan repayment rates. Seeded here
        # at their current correct 2026-27 values so a Super Admin sees
        # (and can override) them from day one, same treatment as
        # k_code_cap_pct above.
        dict(component_key="flat_br_pct", label="Tax Code BR — Flat Rate",
             employee_share="20%", employer_share="—", total="20%",
             employee_rate_pct=Decimal("20.00"), sort_order=10),
        dict(component_key="flat_d0_pct", label="Tax Code D0 — Flat Rate",
             employee_share="40%", employer_share="—", total="40%",
             employee_rate_pct=Decimal("40.00"), sort_order=11),
        dict(component_key="flat_d1_pct", label="Tax Code D1 — Flat Rate",
             employee_share="45%", employer_share="—", total="45%",
             employee_rate_pct=Decimal("45.00"), sort_order=12),
        dict(component_key="flat_sbr_pct", label="Tax Code SBR — Flat Rate (Scotland)",
             employee_share="20%", employer_share="—", total="20%",
             employee_rate_pct=Decimal("20.00"), sort_order=13),
        dict(component_key="flat_sd0_pct", label="Tax Code SD0 — Flat Rate (Scotland)",
             employee_share="21%", employer_share="—", total="21%",
             employee_rate_pct=Decimal("21.00"), sort_order=14),
        dict(component_key="flat_sd1_pct", label="Tax Code SD1 — Flat Rate (Scotland)",
             employee_share="42%", employer_share="—", total="42%",
             employee_rate_pct=Decimal("42.00"), sort_order=15),
        dict(component_key="flat_sd2_pct", label="Tax Code SD2 — Flat Rate (Scotland)",
             employee_share="45%", employer_share="—", total="45%",
             employee_rate_pct=Decimal("45.00"), sort_order=16),
        dict(component_key="flat_sd3_pct", label="Tax Code SD3 — Flat Rate (Scotland)",
             employee_share="48%", employer_share="—", total="48%",
             employee_rate_pct=Decimal("48.00"), sort_order=17),
        dict(component_key="flat_cbr_pct", label="Tax Code CBR — Flat Rate (Wales)",
             employee_share="20%", employer_share="—", total="20%",
             employee_rate_pct=Decimal("20.00"), sort_order=18),
        dict(component_key="flat_cd0_pct", label="Tax Code CD0 — Flat Rate (Wales)",
             employee_share="40%", employer_share="—", total="40%",
             employee_rate_pct=Decimal("40.00"), sort_order=19),
        dict(component_key="flat_cd1_pct", label="Tax Code CD1 — Flat Rate (Wales)",
             employee_share="45%", employer_share="—", total="45%",
             employee_rate_pct=Decimal("45.00"), sort_order=20),
        dict(component_key="ni_pt_thresh_wk", label="NI Primary Threshold (Weekly)",
             employee_share="—", employer_share="—", total="£242",
             flat_amount=Decimal("242.00"), sort_order=21),
        dict(component_key="ni_pt_thresh_mo", label="NI Primary Threshold (Monthly)",
             employee_share="—", employer_share="—", total="£1,048",
             flat_amount=Decimal("1048.00"), sort_order=22),
        dict(component_key="ni_uel_thresh_wk", label="NI Upper Earnings Limit (Weekly)",
             employee_share="—", employer_share="—", total="£967",
             flat_amount=Decimal("967.00"), sort_order=23),
        dict(component_key="ni_uel_thresh_mo", label="NI Upper Earnings Limit (Monthly)",
             employee_share="—", employer_share="—", total="£4,189",
             flat_amount=Decimal("4189.00"), sort_order=24),
        dict(component_key="ni_st_thresh_wk", label="NI Secondary Threshold (Weekly)",
             employee_share="—", employer_share="—", total="£96",
             flat_amount=Decimal("96.00"), sort_order=25),
        dict(component_key="ni_st_thresh_mo", label="NI Secondary Threshold (Monthly)",
             employee_share="—", employer_share="—", total="£417",
             flat_amount=Decimal("417.00"), sort_order=26),
        dict(component_key="sl_plan1_rate", label="Student Loan Plan 1 Rate",
             employee_share="9%", employer_share="—", total="9%",
             employee_rate_pct=Decimal("9.00"), sort_order=27),
        dict(component_key="sl_plan2_rate", label="Student Loan Plan 2 Rate",
             employee_share="9%", employer_share="—", total="9%",
             employee_rate_pct=Decimal("9.00"), sort_order=28),
        dict(component_key="sl_plan4_rate", label="Student Loan Plan 4 Rate",
             employee_share="9%", employer_share="—", total="9%",
             employee_rate_pct=Decimal("9.00"), sort_order=29),
        dict(component_key="sl_plan5_rate", label="Student Loan Plan 5 Rate",
             employee_share="9%", employer_share="—", total="9%",
             employee_rate_pct=Decimal("9.00"), sort_order=30),
        dict(component_key="pg_loan_rate", label="Postgraduate Loan Rate",
             employee_share="6%", employer_share="—", total="6%",
             employee_rate_pct=Decimal("6.00"), sort_order=31),
        # 2026-09-09 gap-closure Part 4 (§16) — mileage allowance payments
        # (employee-owned vehicles) and company-car advisory fuel rates.
        # Deliberately NO Python hardcoded-default fallback for any of
        # these 16 keys, same "genuinely new statutory data, fails closed
        # until configured" discipline as the Statutory Pay/Employer
        # Charges keys from the first plan — only these seed rows exist;
        # uk.py's calculate_mileage_reimbursement/resolve_advisory_fuel_
        # rate read rate_map.get(key) directly with no fallback constant.
        dict(component_key="mileage_car_first_10k", label="Mileage — Car (first 10,000 miles, tax)",
             employee_share="—", employer_share="—", total="55p/mile",
             flat_amount=Decimal("0.55"), sort_order=32),
        dict(component_key="mileage_car_after_10k", label="Mileage — Car (after 10,000 miles, tax)",
             employee_share="—", employer_share="—", total="25p/mile",
             flat_amount=Decimal("0.25"), sort_order=33),
        dict(component_key="mileage_car_ni", label="Mileage — Car (NI-approved, all miles)",
             employee_share="—", employer_share="—", total="55p/mile",
             flat_amount=Decimal("0.55"), sort_order=34),
        dict(component_key="mileage_motorcycle", label="Mileage — Motorcycle (tax & NI)",
             employee_share="—", employer_share="—", total="24p/mile",
             flat_amount=Decimal("0.24"), sort_order=35),
        dict(component_key="mileage_cycle", label="Mileage — Cycle (tax & NI)",
             employee_share="—", employer_share="—", total="20p/mile",
             flat_amount=Decimal("0.20"), sort_order=36),
        dict(component_key="afr_petrol_le1400", label="Advisory Fuel Rate — Petrol ≤1400cc",
             employee_share="—", employer_share="—", total="14p/mile",
             flat_amount=Decimal("0.14"), sort_order=37),
        dict(component_key="afr_petrol_1401_2000", label="Advisory Fuel Rate — Petrol 1401–2000cc",
             employee_share="—", employer_share="—", total="17p/mile",
             flat_amount=Decimal("0.17"), sort_order=38),
        dict(component_key="afr_petrol_gt2000", label="Advisory Fuel Rate — Petrol >2000cc",
             employee_share="—", employer_share="—", total="26p/mile",
             flat_amount=Decimal("0.26"), sort_order=39),
        dict(component_key="afr_lpg_le1400", label="Advisory Fuel Rate — LPG ≤1400cc",
             employee_share="—", employer_share="—", total="11p/mile",
             flat_amount=Decimal("0.11"), sort_order=40),
        dict(component_key="afr_lpg_1401_2000", label="Advisory Fuel Rate — LPG 1401–2000cc",
             employee_share="—", employer_share="—", total="13p/mile",
             flat_amount=Decimal("0.13"), sort_order=41),
        dict(component_key="afr_lpg_gt2000", label="Advisory Fuel Rate — LPG >2000cc",
             employee_share="—", employer_share="—", total="21p/mile",
             flat_amount=Decimal("0.21"), sort_order=42),
        dict(component_key="afr_diesel_le1600", label="Advisory Fuel Rate — Diesel ≤1600cc",
             employee_share="—", employer_share="—", total="15p/mile",
             flat_amount=Decimal("0.15"), sort_order=43),
        dict(component_key="afr_diesel_1601_2000", label="Advisory Fuel Rate — Diesel 1601–2000cc",
             employee_share="—", employer_share="—", total="17p/mile",
             flat_amount=Decimal("0.17"), sort_order=44),
        dict(component_key="afr_diesel_gt2000", label="Advisory Fuel Rate — Diesel >2000cc",
             employee_share="—", employer_share="—", total="23p/mile",
             flat_amount=Decimal("0.23"), sort_order=45),
        dict(component_key="afr_electric_home", label="Advisory Fuel Rate — Electric (home charger)",
             employee_share="—", employer_share="—", total="7p/mile",
             flat_amount=Decimal("0.07"), sort_order=46),
        dict(component_key="afr_electric_public", label="Advisory Fuel Rate — Electric (public charger)",
             employee_share="—", employer_share="—", total="15p/mile",
             flat_amount=Decimal("0.15"), sort_order=47),
        # 2026-09-09 gap-closure Part 5 (§15) — National Minimum Wage
        # compliance rate table, effective 1 April 2026 (Part 1A's
        # row-level effective dating is what lets this coexist with the
        # tax-year pack's own 6 April window — §15's own instruction:
        # "NMW rates effective 1 April 2026 are not incorrectly tied to
        # PAYE tax-year start 6 April," AC-25). No hardcoded Python
        # fallback — same "genuinely new statutory data, fails closed"
        # discipline as Part 4's mileage/AFR keys. Under-18/apprentice-
        # under-19/apprentice-19-plus-first-year all happen to be £8.00
        # this year but are kept as 3 separate keys — same "don't assume
        # a coincidence is permanent" principle as the document's own
        # "Preserve the C prefix" instruction for Welsh PAYE (§5.4).
        dict(component_key="nmw_age_21_plus", label="NMW — Age 21+ (National Living Wage)",
             employee_share="—", employer_share="—", total="£12.71/hour",
             flat_amount=Decimal("12.71"), sort_order=48),
        dict(component_key="nmw_age_18_20", label="NMW — Age 18 to 20",
             employee_share="—", employer_share="—", total="£10.85/hour",
             flat_amount=Decimal("10.85"), sort_order=49),
        dict(component_key="nmw_under_18", label="NMW — Under 18",
             employee_share="—", employer_share="—", total="£8.00/hour",
             flat_amount=Decimal("8.00"), sort_order=50),
        dict(component_key="nmw_apprentice_under_19", label="NMW — Apprentice under 19",
             employee_share="—", employer_share="—", total="£8.00/hour",
             flat_amount=Decimal("8.00"), sort_order=51),
        dict(component_key="nmw_apprentice_19plus_yr1", label="NMW — Apprentice 19+ (first year)",
             employee_share="—", employer_share="—", total="£8.00/hour",
             flat_amount=Decimal("8.00"), sort_order=52),
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
        dict(component_key="income-tax", label="Income Tax (PAYG)",
             employee_share="As per ATO Schedule 1", employer_share="—", total="See Tax Slabs",
             sort_order=2),
        # componentKey max 20 chars (payroll_contribution_rates.component_key
        # is VARCHAR(20)) — the original 27/34-char keys always 500'd on
        # insert, meaning any AU org whose first-ever seed hit this path
        # (no canonical pack synced yet) silently got ZERO default rates for
        # this whole country, not just these two rows (_seed_contribution_rates
        # commits the batch once at the end). Also renamed in australia.py's
        # resolve_jurisdiction_parameter() calls and fallback_registry.py.
        #
        # ZP-TAX-AU-2026-27-001 build (2026-09-16): the old "medicare-levy"
        # (flat 2.0% employee rate), "medicare_low_inc_thr", "help_threshold"
        # and "help_rate" rows are REMOVED, not merely unused — Medicare
        # Levy proper is now embedded in the Schedule 1 Scale coefficient
        # bands and HELP/HECS now runs on the real Schedule 8 coefficient
        # mechanism (engine/countries/australia.py); neither old flat
        # approximation is read by the engine any more, so seeding them
        # into a new org's own rates would be actively misleading, not
        # just dead weight. super_max_contrib corrected to the real
        # 2026-27 figure ($270,830, §10) — the old $260,280 predates this
        # document and was simply wrong for this income year.
        dict(component_key="super_max_contrib", label="Superannuation Max Contribution Base",
             employee_share="—", employer_share="—", total="A$270,830",
             flat_amount=Decimal("270830.00"), sort_order=3),
        dict(component_key="mls_threshold", label="Medicare Levy Surcharge Threshold",
             employee_share="—", employer_share="—", total="A$97,000",
             flat_amount=Decimal("97000.00"), sort_order=4),
        dict(component_key="mls_rate", label="Medicare Levy Surcharge Rate",
             employee_share="1.0%", employer_share="—", total="1.0%",
             employee_rate_pct=Decimal("1.00"), sort_order=5),
        # Special Payments (Phase 3, §13) — real, document-given caps/
        # formula parameters, not fabricated. The ETP/lump-sum/income-
        # stream WITHHOLDING rate itself is not given anywhere in the
        # source document, so these are classification/reference inputs
        # only — see engine/countries/australia.py's own module docstring
        # for exactly what is and isn't computed from them.
        dict(component_key="etp_life_cap", label="ETP Life Benefit Cap",
             employee_share="—", employer_share="—", total="A$270,000",
             flat_amount=Decimal("270000.00"), sort_order=6),
        dict(component_key="etp_death_cap", label="ETP Death Benefit Cap",
             employee_share="—", employer_share="—", total="A$270,000",
             flat_amount=Decimal("270000.00"), sort_order=7),
        dict(component_key="redundancy_base", label="Genuine Redundancy Tax-Free Base",
             employee_share="—", employer_share="—", total="A$13,598",
             flat_amount=Decimal("13598.00"), sort_order=8),
        dict(component_key="redundancy_per_yr", label="Genuine Redundancy Tax-Free Per Year",
             employee_share="—", employer_share="—", total="A$6,801",
             flat_amount=Decimal("6801.00"), sort_order=9),
        dict(component_key="untaxed_plan_cap", label="Untaxed Plan Cap",
             employee_share="—", employer_share="—", total="A$1,935,000",
             flat_amount=Decimal("1935000.00"), sort_order=10),
        dict(component_key="transfer_balance_cap", label="General Transfer Balance Cap",
             employee_share="—", employer_share="—", total="A$2,100,000",
             flat_amount=Decimal("2100000.00"), sort_order=11),
        dict(component_key="db_income_cap", label="Defined Benefit Income Cap",
             employee_share="—", employer_share="—", total="A$131,250",
             flat_amount=Decimal("131250.00"), sort_order=12),
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
        # Karnataka Professional Tax (§13.1) — source IN-KA-PT-SCHED, seed
        # rule schedule; Karnataka Act No. 22 of 2026 (IN-KA-PT-2026-ACT,
        # effective 1 Apr 2026) amends return mechanics only, not this
        # employee rate, per the document's own note.
        dict(min_amount=Decimal("0"),      max_amount=Decimal("24999"), rate_pct=Decimal("0"), rate_label="PT", tax_formula="", rule_type="PT_FLAT", flat_amount=Decimal("0.00"),   jurisdiction_state="Karnataka", sort_order=34),
        dict(min_amount=Decimal("25000"),  max_amount=None,             rate_pct=Decimal("0"), rate_label="PT", tax_formula="", rule_type="PT_FLAT", flat_amount=Decimal("200.00"), jurisdiction_state="Karnataka", sort_order=35),
        # Maharashtra Professional Tax (§13.2, source IN-MH-PT) — gender-
        # differentiated (filing_status carries gender, MALE/FEMALE, per
        # _resolve_state_pt_bracket's own reuse convention) with a
        # February adjustment (adjustment_amount) so 11×₹200 + ₹300 = the
        # statutory ₹2,500 annual ceiling for both bands' top tier.
        dict(min_amount=Decimal("0"),     max_amount=Decimal("7500"),  rate_pct=Decimal("0"), rate_label="PT", tax_formula="", rule_type="PT_FLAT", flat_amount=Decimal("0.00"),   jurisdiction_state="Maharashtra", filing_status="MALE", sort_order=36),
        dict(min_amount=Decimal("7501"),  max_amount=Decimal("10000"), rate_pct=Decimal("0"), rate_label="PT", tax_formula="", rule_type="PT_FLAT", flat_amount=Decimal("175.00"), jurisdiction_state="Maharashtra", filing_status="MALE", sort_order=37),
        dict(min_amount=Decimal("10001"), max_amount=None,             rate_pct=Decimal("0"), rate_label="PT", tax_formula="", rule_type="PT_FLAT", flat_amount=Decimal("200.00"), adjustment_amount=Decimal("300.00"), jurisdiction_state="Maharashtra", filing_status="MALE", sort_order=38),
        dict(min_amount=Decimal("0"),     max_amount=Decimal("25000"), rate_pct=Decimal("0"), rate_label="PT", tax_formula="", rule_type="PT_FLAT", flat_amount=Decimal("0.00"),   jurisdiction_state="Maharashtra", filing_status="FEMALE", sort_order=39),
        dict(min_amount=Decimal("25001"), max_amount=None,             rate_pct=Decimal("0"), rate_label="PT", tax_formula="", rule_type="PT_FLAT", flat_amount=Decimal("200.00"), adjustment_amount=Decimal("300.00"), jurisdiction_state="Maharashtra", filing_status="FEMALE", sort_order=40),
        # Odisha Professional Tax (§14.2, source IN-OD-PT) — full bracket
        # ladder as published; "Source-age control" note in the document
        # applies (verify no later notification supersedes this before
        # each annual publish), same as every other seeded state here.
        dict(min_amount=Decimal("0"),     max_amount=Decimal("5000"),  rate_pct=Decimal("0"), rate_label="PT", tax_formula="", rule_type="PT_FLAT", flat_amount=Decimal("0.00"),   jurisdiction_state="Odisha", sort_order=41),
        dict(min_amount=Decimal("5001"),  max_amount=Decimal("6000"),  rate_pct=Decimal("0"), rate_label="PT", tax_formula="", rule_type="PT_FLAT", flat_amount=Decimal("30.00"),  jurisdiction_state="Odisha", sort_order=42),
        dict(min_amount=Decimal("6001"),  max_amount=Decimal("8000"),  rate_pct=Decimal("0"), rate_label="PT", tax_formula="", rule_type="PT_FLAT", flat_amount=Decimal("50.00"),  jurisdiction_state="Odisha", sort_order=43),
        dict(min_amount=Decimal("8001"),  max_amount=Decimal("10000"), rate_pct=Decimal("0"), rate_label="PT", tax_formula="", rule_type="PT_FLAT", flat_amount=Decimal("75.00"),  jurisdiction_state="Odisha", sort_order=44),
        dict(min_amount=Decimal("10001"), max_amount=Decimal("15000"), rate_pct=Decimal("0"), rate_label="PT", tax_formula="", rule_type="PT_FLAT", flat_amount=Decimal("100.00"), jurisdiction_state="Odisha", sort_order=45),
        dict(min_amount=Decimal("15001"), max_amount=Decimal("20000"), rate_pct=Decimal("0"), rate_label="PT", tax_formula="", rule_type="PT_FLAT", flat_amount=Decimal("150.00"), jurisdiction_state="Odisha", sort_order=46),
        dict(min_amount=Decimal("20001"), max_amount=None,             rate_pct=Decimal("0"), rate_label="PT", tax_formula="", rule_type="PT_FLAT", flat_amount=Decimal("200.00"), jurisdiction_state="Odisha", sort_order=47),
        # Greater Chennai Corporation local Professional Tax (§14.1,
        # source IN-CHN-PT) — LOCAL authority level under Tamil Nadu, not
        # a statewide Tamil Nadu schedule (the document's own explicit
        # instruction: "Do not create a single statewide Chennai
        # schedule"). assessment_basis="HALF_YEAR_INCOME" — matched
        # against an average HALF-YEARLY income, not monthly gross (see
        # india.py's _pt_assessment_income). Half-yearly schedule
        # effective from II/2024-25 for the lower/middle bands.
        #
        # DELIBERATELY NOT SEEDED: a "pt_half_year_deduct_month_1/_2"
        # collection-month row — the document gives no specific due
        # date/remittance month for Chennai's own collection cycle (only
        # the schedule's effective FY), and §1.1 forbids guessing a due
        # date the source doesn't give. Until Tax Ops configures those
        # two keys from a certified source, this bracket resolves a real
        # amount but _pt_half_year_deduction_active always returns False,
        # so professional_tax stays ₹0 every month — fail-closed, not a
        # silent guess, exactly like an unconfigured LWF deduction month.
        dict(min_amount=Decimal("0"),     max_amount=Decimal("21000"), rate_pct=Decimal("0"), rate_label="PT", tax_formula="", rule_type="PT_FLAT", flat_amount=Decimal("0.00"),    jurisdiction_state="Tamil Nadu", jurisdiction_locality="Chennai", assessment_basis="HALF_YEAR_INCOME", sort_order=48),
        dict(min_amount=Decimal("21001"), max_amount=Decimal("30000"), rate_pct=Decimal("0"), rate_label="PT", tax_formula="", rule_type="PT_FLAT", flat_amount=Decimal("180.00"),  jurisdiction_state="Tamil Nadu", jurisdiction_locality="Chennai", assessment_basis="HALF_YEAR_INCOME", sort_order=49),
        dict(min_amount=Decimal("30001"), max_amount=Decimal("45000"), rate_pct=Decimal("0"), rate_label="PT", tax_formula="", rule_type="PT_FLAT", flat_amount=Decimal("425.00"),  jurisdiction_state="Tamil Nadu", jurisdiction_locality="Chennai", assessment_basis="HALF_YEAR_INCOME", sort_order=50),
        dict(min_amount=Decimal("45001"), max_amount=Decimal("60000"), rate_pct=Decimal("0"), rate_label="PT", tax_formula="", rule_type="PT_FLAT", flat_amount=Decimal("930.00"),  jurisdiction_state="Tamil Nadu", jurisdiction_locality="Chennai", assessment_basis="HALF_YEAR_INCOME", sort_order=51),
        dict(min_amount=Decimal("60001"), max_amount=Decimal("75000"), rate_pct=Decimal("0"), rate_label="PT", tax_formula="", rule_type="PT_FLAT", flat_amount=Decimal("1025.00"), jurisdiction_state="Tamil Nadu", jurisdiction_locality="Chennai", assessment_basis="HALF_YEAR_INCOME", sort_order=52),
        dict(min_amount=Decimal("75001"), max_amount=None,             rate_pct=Decimal("0"), rate_label="PT", tax_formula="", rule_type="PT_FLAT", flat_amount=Decimal("1250.00"), jurisdiction_state="Tamil Nadu", jurisdiction_locality="Chennai", assessment_basis="HALF_YEAR_INCOME", sort_order=53),
        # NOT seeded: Gujarat (§13.4, source IN-GJ-PT) — the document's own
        # instruction is "activate only after current rate-schedule
        # artifact is attached to the production ruleset," which has not
        # happened. Tracked as SOURCE_REQUIRED in
        # StateLocalProgramReadiness instead of a guessed/premature row.
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

        # Form W-4 Step 2 checkbox schedule (ZP-TAX-US-2026-001 §3.3,
        # gap-closure Phase 8, 2026-09-12) — a genuinely DIFFERENT bracket
        # table (narrower bands, taxes sooner) from the standard §3.2
        # table above, used directly when the employee has checked the
        # "Multiple Jobs or Spouse Works" box in Form W-4 Step 2. Tagged
        # with a distinct filing_status suffix ("_STEP2") rather than a
        # new column, matching _calculate_annual_tax's existing exact-
        # match-on-filing_status mechanism — us.py appends this suffix to
        # the employee's own filing_status only when
        # ctx.w4_step2_checkbox is True, so every existing employee
        # (checkbox unset/False) is completely unaffected.
        #
        # Deliberately NOT implemented here: §3.4's separate "2020+
        # standard adjustment" ($12,900 MFJ/$8,600 otherwise, added to
        # wages before applying the STANDARD table when Step 2 is NOT
        # checked) — the real IRS Pub. 15-T Worksheet 1A mechanism for
        # exactly how/where that figure combines with the existing
        # standard_deduction ContributionRate rows already in production
        # use isn't something this implementation is confident enough
        # of to risk silently mis-calculating every US employee's
        # existing federal withholding. This Step 2 table has no such
        # ambiguity — it's applied directly, on its own, with zero
        # interaction with any other adjustment.
        dict(min_amount=Decimal("0"),       max_amount=Decimal("8050"),     rate_pct=Decimal("0"),   rate_label="0%",   tax_formula="No withholding up to $8,050 (Step 2 checked)", filing_status="SINGLE_STEP2", sort_order=200),
        dict(min_amount=Decimal("8050"),    max_amount=Decimal("14250"),    rate_pct=Decimal("10"),  rate_label="10%",  tax_formula="10% of income over $8,050 (Step 2 checked)", filing_status="SINGLE_STEP2", sort_order=201),
        dict(min_amount=Decimal("14250"),   max_amount=Decimal("33250"),    rate_pct=Decimal("12"),  rate_label="12%",  tax_formula="$620 + 12% over $14,250 (Step 2 checked)", filing_status="SINGLE_STEP2", sort_order=202),
        dict(min_amount=Decimal("33250"),   max_amount=Decimal("60900"),    rate_pct=Decimal("22"),  rate_label="22%",  tax_formula="$2,900 + 22% over $33,250 (Step 2 checked)", filing_status="SINGLE_STEP2", sort_order=203),
        dict(min_amount=Decimal("60900"),   max_amount=Decimal("108938"),   rate_pct=Decimal("24"),  rate_label="24%",  tax_formula="$8,983 + 24% over $60,900 (Step 2 checked)", filing_status="SINGLE_STEP2", sort_order=204),
        dict(min_amount=Decimal("108938"),  max_amount=Decimal("136163"),   rate_pct=Decimal("32"),  rate_label="32%",  tax_formula="$20,512 + 32% over $108,938 (Step 2 checked)", filing_status="SINGLE_STEP2", sort_order=205),
        dict(min_amount=Decimal("136163"),  max_amount=Decimal("328350"),   rate_pct=Decimal("35"),  rate_label="35%",  tax_formula="$29,224 + 35% over $136,163 (Step 2 checked)", filing_status="SINGLE_STEP2", sort_order=206),
        dict(min_amount=Decimal("328350"),  max_amount=None,                rate_pct=Decimal("37"),  rate_label="37%",  tax_formula="$96,489.63 + 37% over $328,350 (Step 2 checked)", filing_status="SINGLE_STEP2", sort_order=207),
        # MFS shares the exact same "Single/MFS" combined table as SINGLE
        # above — same duplication convention the base §3.2 table already
        # uses for these two statuses.
        dict(min_amount=Decimal("0"),       max_amount=Decimal("8050"),     rate_pct=Decimal("0"),   rate_label="0%",   tax_formula="No withholding up to $8,050 (Step 2 checked)", filing_status="MFS_STEP2", sort_order=208),
        dict(min_amount=Decimal("8050"),    max_amount=Decimal("14250"),    rate_pct=Decimal("10"),  rate_label="10%",  tax_formula="10% of income over $8,050 (Step 2 checked)", filing_status="MFS_STEP2", sort_order=209),
        dict(min_amount=Decimal("14250"),   max_amount=Decimal("33250"),    rate_pct=Decimal("12"),  rate_label="12%",  tax_formula="$620 + 12% over $14,250 (Step 2 checked)", filing_status="MFS_STEP2", sort_order=210),
        dict(min_amount=Decimal("33250"),   max_amount=Decimal("60900"),    rate_pct=Decimal("22"),  rate_label="22%",  tax_formula="$2,900 + 22% over $33,250 (Step 2 checked)", filing_status="MFS_STEP2", sort_order=211),
        dict(min_amount=Decimal("60900"),   max_amount=Decimal("108938"),   rate_pct=Decimal("24"),  rate_label="24%",  tax_formula="$8,983 + 24% over $60,900 (Step 2 checked)", filing_status="MFS_STEP2", sort_order=212),
        dict(min_amount=Decimal("108938"),  max_amount=Decimal("136163"),   rate_pct=Decimal("32"),  rate_label="32%",  tax_formula="$20,512 + 32% over $108,938 (Step 2 checked)", filing_status="MFS_STEP2", sort_order=213),
        dict(min_amount=Decimal("136163"),  max_amount=Decimal("328350"),   rate_pct=Decimal("35"),  rate_label="35%",  tax_formula="$29,224 + 35% over $136,163 (Step 2 checked)", filing_status="MFS_STEP2", sort_order=214),
        dict(min_amount=Decimal("328350"),  max_amount=None,                rate_pct=Decimal("37"),  rate_label="37%",  tax_formula="$96,489.63 + 37% over $328,350 (Step 2 checked)", filing_status="MFS_STEP2", sort_order=215),
        dict(min_amount=Decimal("0"),       max_amount=Decimal("16100"),    rate_pct=Decimal("0"),   rate_label="0%",   tax_formula="No withholding up to $16,100 (Step 2 checked)", filing_status="MFJ_STEP2", sort_order=216),
        dict(min_amount=Decimal("16100"),   max_amount=Decimal("28500"),    rate_pct=Decimal("10"),  rate_label="10%",  tax_formula="10% of income over $16,100 (Step 2 checked)", filing_status="MFJ_STEP2", sort_order=217),
        dict(min_amount=Decimal("28500"),   max_amount=Decimal("66500"),    rate_pct=Decimal("12"),  rate_label="12%",  tax_formula="$1,240 + 12% over $28,500 (Step 2 checked)", filing_status="MFJ_STEP2", sort_order=218),
        dict(min_amount=Decimal("66500"),   max_amount=Decimal("121800"),   rate_pct=Decimal("22"),  rate_label="22%",  tax_formula="$5,800 + 22% over $66,500 (Step 2 checked)", filing_status="MFJ_STEP2", sort_order=219),
        dict(min_amount=Decimal("121800"),  max_amount=Decimal("217875"),   rate_pct=Decimal("24"),  rate_label="24%",  tax_formula="$17,966 + 24% over $121,800 (Step 2 checked)", filing_status="MFJ_STEP2", sort_order=220),
        dict(min_amount=Decimal("217875"),  max_amount=Decimal("272325"),   rate_pct=Decimal("32"),  rate_label="32%",  tax_formula="$41,024 + 32% over $217,875 (Step 2 checked)", filing_status="MFJ_STEP2", sort_order=221),
        dict(min_amount=Decimal("272325"),  max_amount=Decimal("400450"),   rate_pct=Decimal("35"),  rate_label="35%",  tax_formula="$58,448 + 35% over $272,325 (Step 2 checked)", filing_status="MFJ_STEP2", sort_order=222),
        dict(min_amount=Decimal("400450"),  max_amount=None,                rate_pct=Decimal("37"),  rate_label="37%",  tax_formula="$103,291.75 + 37% over $400,450 (Step 2 checked)", filing_status="MFJ_STEP2", sort_order=223),
        dict(min_amount=Decimal("0"),       max_amount=Decimal("12075"),    rate_pct=Decimal("0"),   rate_label="0%",   tax_formula="No withholding up to $12,075 (Step 2 checked)", filing_status="HOH_STEP2", sort_order=224),
        dict(min_amount=Decimal("12075"),   max_amount=Decimal("20925"),    rate_pct=Decimal("10"),  rate_label="10%",  tax_formula="10% of income over $12,075 (Step 2 checked)", filing_status="HOH_STEP2", sort_order=225),
        dict(min_amount=Decimal("20925"),   max_amount=Decimal("45800"),    rate_pct=Decimal("12"),  rate_label="12%",  tax_formula="$885 + 12% over $20,925 (Step 2 checked)", filing_status="HOH_STEP2", sort_order=226),
        dict(min_amount=Decimal("45800"),   max_amount=Decimal("64925"),    rate_pct=Decimal("22"),  rate_label="22%",  tax_formula="$3,870 + 22% over $45,800 (Step 2 checked)", filing_status="HOH_STEP2", sort_order=227),
        dict(min_amount=Decimal("64925"),   max_amount=Decimal("112950"),   rate_pct=Decimal("24"),  rate_label="24%",  tax_formula="$8,077.50 + 24% over $64,925 (Step 2 checked)", filing_status="HOH_STEP2", sort_order=228),
        dict(min_amount=Decimal("112950"),  max_amount=Decimal("140175"),   rate_pct=Decimal("32"),  rate_label="32%",  tax_formula="$19,603.50 + 32% over $112,950 (Step 2 checked)", filing_status="HOH_STEP2", sort_order=229),
        dict(min_amount=Decimal("140175"),  max_amount=Decimal("332375"),   rate_pct=Decimal("35"),  rate_label="35%",  tax_formula="$28,315.50 + 35% over $140,175 (Step 2 checked)", filing_status="HOH_STEP2", sort_order=230),
        dict(min_amount=Decimal("332375"),  max_amount=None,                rate_pct=Decimal("37"),  rate_label="37%",  tax_formula="$95,585.50 + 37% over $332,375 (Step 2 checked)", filing_status="HOH_STEP2", sort_order=231),
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
        # net of the Grundfreibetrag), matching how this display-only
        # reference table has always been framed — this is a Super Admin
        # compliance-UI reference list, not consumed by any calculation
        # (production Germany tax uses the PAP/internal-tariff path in
        # engine/germany_internal_tax.py, not a slab table).
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
# Fixed 2026-09-13 (ZP-TAX-US-2026-001 §3.1 gap-closure audit): this was
# still 2025's SSA wage base ($176,100). The canonical DB row and the
# sibling seed dict a few hundred lines below (used by
# scripts/populate_us_state_tax_v1.py's Phase 1) were already correct at
# 184,500 — only this engine-level fallback constant, read directly by
# engine/countries/us.py whenever no org-scoped ContributionRate row is
# configured, was stale. This is the exact constant that produced the
# `using hardcoded default 176100` log line caught live this session.
_US_SOCIAL_SECURITY_WAGE_BASE = Decimal("184500")
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

# Supplemental wages (ZP-TAX-US-2026-001 §3.1, IRS Pub. 15 (2026)) — a
# standalone calculator (service.calculate_us_supplemental_wage_withholding),
# same "not woven into the regular per-period calculate() path" pattern as
# Canada's own special-payment/retiring-allowance calculators, since this
# only applies when an employer has separately identified a payment as a
# supplemental wage (bonus, commission, severance, etc.), not to every
# payslip. 22% applies to qualifying supplemental wages; the 37% rate is
# mandatory (not elective) on the portion of an employee's CUMULATIVE
# calendar-year supplemental wages that exceeds $1,000,000 — regardless of
# which method the employer otherwise elected for amounts under that
# threshold.
_US_SUPPLEMENTAL_FLAT_RATE = Decimal("22.0")
_US_SUPPLEMENTAL_HIGH_RATE = Decimal("37.0")
_US_SUPPLEMENTAL_HIGH_THRESHOLD = Decimal("1000000.00")

# Federal W-4 legacy (pre-2020) allowance amount (ZP-TAX-US-2026-001
# §3.4, gap-closure Plan Phase 2d): "2026 Pub. 15-T uses $4,300 for each
# withholding allowance in the legacy-form calculation path" — a real,
# literal figure the document gives directly, only ever applied when
# ctx.w4_form_vintage == "PRE_2020" AND the employee has a real
# w4_allowances_claimed count on file (None/0 is a complete no-op).
# The NRA (nonresident alien) additional-wage amount the same section
# also requires is deliberately NOT a hardcoded constant here — the
# document only specifies it must be "a configuration value by W-4
# vintage and pay frequency," giving no literal dollar figure at all, so
# it is resolved purely from rate_map (component_key
# "w4_nra_addl_wage_amount", country="US") via the same
# resolve_jurisdiction_parameter mechanism every other Super-Admin-
# configurable US parameter uses, defaulting to $0 (no-op) until Tax Ops
# enters the real current Pub. 15-T figure — never guessed.
_US_W4_PRE_2020_ALLOWANCE_AMOUNT = Decimal("4300.00")

# Federal deposit/filing calendar (ZP-TAX-US-2026-001 §3.5, gap-closure
# Phase 8, 2026-09-12) — a standalone calculator
# (service.calculate_us_federal_deposit_schedule), org-scoped rather than
# employee-scoped (this is an employer obligation, not a per-employee
# calculation). Only the figures §3.5 gives literally are implemented:
# the $50,000 monthly/semiweekly lookback threshold, the $100,000
# next-day rule, the $500 FUTA quarterly deposit trigger, and the
# Form W-2/W-3 January 31 statutory deadline. Form 941's quarterly due
# date is deliberately NOT computed here — §3.5 names the obligation
# ("Quarterly employer federal tax return") but gives no literal day-of-
# month, and the real-world "last day of the month following the
# quarter" figure is general knowledge, not something this document
# sources — consistent with every other place this build has refused to
# assert a number the governing document itself doesn't give.
_US_MONTHLY_SEMIWEEKLY_THRESHOLD = Decimal("50000.00")
_US_NEXT_DAY_DEPOSIT_THRESHOLD = Decimal("100000.00")
_US_FUTA_DEPOSIT_THRESHOLD = Decimal("500.00")

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
# Automatic-enrolment earnings trigger (ZP-TAX-UK-2026-27-001 §13.1) — the
# annual earnings level above which an age-22-to-SPA employee must be
# auto-enrolled. Distinct from _UK_PENSION_QE_LOWER above: an employee
# earning between this figure and the lower qualifying-earnings threshold
# is a non-eligible jobholder (can opt in), not an eligible one.
_UK_PENSION_AE_TRIGGER = Decimal("10000")
# Student/Postgraduate Loan — real UK mechanism. Plan 5 covers post-2023
# starters (in effect from April 2026). Any other/unset study_loan_plan
# value deducts 0, same as having no loan at all. 2026-27 thresholds per
# ZP-TAX-UK-2026-27-001 section 10.1. Both figures in each tuple are
# FALLBACK defaults only — the threshold was already Super-Admin-
# configurable via uk.py's _UK_STUDENT_LOAN_PARAM_KEYS; as of 2026-09-09
# gap-closure Phase 1 the repayment RATE is too, via the new
# _UK_STUDENT_LOAN_RATE_PARAM_KEYS (seed rows above) — it was previously
# the one figure in this tuple with no override path at all.
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
# This dict is the FALLBACK default only — 2026-09-09 gap-closure Phase 1
# made each code's % Super-Admin-configurable via
# uk.py's _UK_FLAT_RATE_CODE_PARAM_KEYS + resolve_jurisdiction_parameter
# (seed rows above), since a code's meaning is genuinely statutory data
# HMRC republishes, not a code-only constant.
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
# FALLBACK default only as of 2026-09-09 gap-closure Phase 1 —
# resolve_direct_period_threshold now checks a rate_map row first (see
# uk.py's _UK_NI_*_THRESH_PARAM_KEYS, seed rows above) before using these.
_UK_NI_PRIMARY_THRESHOLD_BY_FREQUENCY = {"Weekly": Decimal("242"), "Monthly": Decimal("1048")}
_UK_NI_UPPER_THRESHOLD_BY_FREQUENCY = {"Weekly": Decimal("967"), "Monthly": Decimal("4189")}
_UK_NI_SECONDARY_THRESHOLD_BY_FREQUENCY = {"Weekly": Decimal("96"), "Monthly": Decimal("417")}
# NI category derivation (ZP-TAX-UK-2026-27-001 §8.2/§9.1/§9.3 gap-closure
# Part 2, 2026-09-09) — the current real State Pension age. A genuine
# simplification: the real UK State Pension age is a phased schedule that
# varies by birth cohort (and historically by gender), not one flat
# number — this engine uses a single configurable age rather than
# modeling that full schedule.
_UK_STATE_PENSION_AGE = Decimal("66")

# ── Australia (previously engine/countries/australia.py) ────────────────
# ZP-TAX-AU-2026-27-001 build: Medicare Levy PROPER is embedded directly
# in the Schedule 1 Scale 1/2/5/6 coefficient bands themselves (that's
# what distinguishes Scale 5/6 "Medicare-exempt" from Scale 1/2 "standard"
# — see engine/countries/australia.py's _calculate_au_payg_schedule1) —
# the old flat-threshold "_AU_MEDICARE_LEVY_LOW_INCOME_THRESHOLD" approach
# this constant backed is superseded, not merely unused, so it is removed
# rather than left as a stale, demonstrably-wrong fallback. MLS (Medicare
# Levy SURCHARGE) is a genuinely separate, still-flat-threshold annual
# calculation and keeps its own constants below.
_AU_MLS_THRESHOLD = Decimal("97000")
_AU_MLS_RATE = Decimal("1.0")
# Corrected to the real ZP-TAX-AU-2026-27-001 §10 2026-27 figure
# ($270,830) — the original pre-document stub's $260,280 was simply
# wrong for this income year, not a deliberate simplification like the
# HELP/HECS one below. A code-constant fix, not a live-data-entry action
# (that stays gated to Phase 8's real Super Admin configuration).
_AU_SUPER_MAX_CONTRIBUTION_BASE = Decimal("270830")
# HELP/HECS's old flat single-threshold-and-rate approximation
# (_AU_HELP_THRESHOLD/_AU_HELP_RATE) is REMOVED, not merely unused —
# superseded by the real ATO Schedule 8 (NAT 3539) coefficient-band
# mechanism (engine/countries/australia.py's _calculate_au_stsl_schedule8),
# which has no single scalar fallback the way a threshold/rate pair does
# (there is no sensible flat-rate substitute for a whole coefficient
# table, same reasoning as Medicare Levy proper above).
# ATO Schedule 1 Scale 4 (no TFN provided) — the ONE genuinely flat,
# non-bracketed PAYG rate in the whole schedule (§6's own table gives it
# as a fixed rate + cents-treatment rule, not a coefficient band), so it
# keeps a simple resolve_jurisdiction_parameter fallback like MLS/Super/
# HELP above rather than needing a TaxSlab coefficient-band row.
_AU_PAYG_SCALE4_RESIDENT_RATE = Decimal("47.0")
_AU_PAYG_SCALE4_NONRESIDENT_RATE = Decimal("45.0")

# Special Payments (ZP-TAX-AU-2026-27-001 §13, Phase 3, 2026-09-16) —
# real, document-given caps and the genuine-redundancy tax-free formula
# parameters. The ETP/lump-sum/income-stream WITHHOLDING rate itself is
# NOT given anywhere in the source document, so these back only the
# classification/reference calculators in engine/countries/australia.py
# (calculate_au_etp_cap_classification, calculate_au_genuine_redundancy_
# tax_free_component) — never a fabricated withholding-tax rate.
_AU_ETP_LIFE_CAP = Decimal("270000")
_AU_ETP_DEATH_CAP = Decimal("270000")
_AU_GENUINE_REDUNDANCY_BASE = Decimal("13598")
_AU_GENUINE_REDUNDANCY_PER_YEAR = Decimal("6801")
_AU_UNTAXED_PLAN_CAP = Decimal("1935000")
_AU_TRANSFER_BALANCE_CAP = Decimal("2100000")
_AU_DEFINED_BENEFIT_INCOME_CAP = Decimal("131250")

# State/territory employer payroll tax (ZP-TAX-AU-2026-27-001 §15/§17,
# Phase 4, 2026-09-16) — real, document-given thresholds/rates for the
# four states whose formula is a "deduction that varies with total
# wages" shape (WA/QLD/VIC/NT), so a scalar resolve_jurisdiction_parameter
# fallback is meaningful the same way it already is for e.g. Canada's
# BPAF taper. NSW/TAS/ACT are modeled as ordinary MARGINAL_RATE TaxSlab
# bracket rows instead (their formulas ARE plain bracket tables once
# expressed as ranges) and deliberately have NO Python-constant fallback
# here — same "genuinely statutory data, no hardcoded fallback" precedent
# already established for Canada's ON_EHT_BAND rows (see canada.py's
# _on_eht_rate_for_total). SA's $1.5m-$1.7m reduced-rate band has no
# fallback of any kind — the source document explicitly forbids inferring/
# approximating it at runtime (§17: "Load RevenueSA's reduced-rate asset
# ... do not infer/approximate a rate at runtime").
_AU_WA_PT_THRESHOLD = Decimal("1000000")
_AU_WA_PT_UPPER_THRESHOLD = Decimal("7500000")
_AU_WA_PT_RATE = Decimal("5.5")
_AU_QLD_PT_THRESHOLD = Decimal("1300000")
_AU_QLD_PT_UPPER_THRESHOLD = Decimal("10400000")
_AU_QLD_PT_RATE_LOW = Decimal("4.75")
_AU_QLD_PT_RATE_HIGH = Decimal("4.95")
_AU_QLD_PT_RATE_SWITCH = Decimal("6500000")
_AU_VIC_PT_PHASE_START = Decimal("3000000")
_AU_VIC_PT_PHASE_END = Decimal("5000000")
_AU_VIC_PT_BASE_DEDUCTION = Decimal("1000000")
_AU_VIC_PT_RATE = Decimal("4.85")
_AU_VIC_PT_REGIONAL_RATE = Decimal("1.2125")
_AU_NT_PT_THRESHOLD = Decimal("2500000")
_AU_NT_PT_RATE = Decimal("5.5")
_AU_NT_PT_RATE_HIGH = Decimal("6.5")
_AU_NT_PT_RATE_SWITCH = Decimal("100000000")
_AU_SA_PT_LOWER_THRESHOLD = Decimal("1500000")
_AU_SA_PT_UPPER_THRESHOLD = Decimal("1700000")
_AU_SA_PT_RATE = Decimal("4.95")

# ── Germany (previously engine/countries/germany.py) ────────────────────
# _DE_GRUNDFREIBETRAG, _DE_CONTRIBUTION_CEILING, and _DE_CHURCH_TAX_RATE
# (a flat representative Kirchensteuer default) were retired in Phase 4
# (docs/PHASE_4_GERMANY_LEGACY_PAP_ARCHITECTURE_DECISION_REPORT.md) along
# with the pre-Phase-7 legacy calculator that was their only consumer —
# the production path uses germany_pap.CHURCH_TAX_LAND_RATES (per-Land
# 8%/9% table) and the dedicated GermanyContributionCeiling registry
# instead. _DE_SOLI_THRESHOLD/_DE_SOLI_RATE remain: the production
# Regular/Midijob paths still pass them to InternalGermanyWageTaxCalculator.
_DE_SOLI_THRESHOLD = Decimal("18130")
_DE_SOLI_RATE = Decimal("5.5")

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
# WSDRF (§13/§15, gap-closure Phase 7) — the document's own "generally
# based on 1% workforce-skills investment requirement" figure, DB-
# configurable like every other rate (state_rate_map "wsdrf_rate"),
# this is only the fallback default. Computed by service.
# calculate_ca_wsdrf_shortfall, a standalone annual calculator, never
# wired into engine/countries/canada.py's calculate().
_CA_WSDRF_RATE_PCT = Decimal("1")


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
    # Incremental build-out (ZP-TAX-US-2026-001 §4 Matrix): the five
    # flat-rate states the document gives a complete literal percentage for.
    # Every new state has allowance_by_filing_status={} because the document
    # says None for all filing statuses (no state standard deduction row is
    # seeded — the full gross is taxed, same as if the row were configured
    # to 0). AZ's 2.0% is the document's stated no-A-4-form default (the
    # statutory per-employee choice spans 0.5%-3.5%, but the engine applies
    # ONE rate — the document's 2.0%). All five read behind the same
    # _US_STATE_TAX_ENABLED_STATES switch; enabled immediately below in
    # shared.py.
    "AZ": dict(
        agency="Arizona DOR",
        source_title="Arizona Form A-4 — statutory flat withholding default (ZP-TAX-US-2026-001 §4 Matrix)",
        rate_pct=Decimal("2.00"),
        allowance_by_filing_status={},
    ),
    "IL": dict(
        agency="Illinois DOR",
        source_title="IL-700-T (2026) percentage method (ZP-TAX-US-2026-001 §4 Matrix)",
        rate_pct=Decimal("4.95"),
        allowance_by_filing_status={},
    ),
    "MA": dict(
        agency="Massachusetts DOR",
        source_title="Massachusetts Circular M — 5.0% base withholding (ZP-TAX-US-2026-001 §4 Matrix)",
        rate_pct=Decimal("5.00"),
        allowance_by_filing_status={},
    ),
    "MI": dict(
        agency="Michigan Treasury",
        source_title="Michigan Form 446 (2026) — ZP-TAX-US-2026-001 §4 Matrix/Appendix A",
        rate_pct=Decimal("4.25"),
        allowance_by_filing_status={},
    ),
    "PA": dict(
        agency="Pennsylvania DOR",
        source_title="Flat state PIT withholding rate (ZP-TAX-US-2026-001 §4 Matrix)",
        rate_pct=Decimal("3.07"),
        allowance_by_filing_status={},
    ),
    # Gap-closure Level 2 batch (2026-09-12): genuine primary-source data
    # (real government URLs, explicit refusal to estimate missing figures)
    # — a materially higher trust tier than the earlier internal tracking
    # sheet these two states were first drafted from.
    #
    # GA supersedes and CORRECTS this state's own earlier PROVISIONAL entry
    # (5.19%, from the untrustworthy tracking sheet — see
    # _US_STATE_TAX_RATES_PROVISIONAL's own comment). The batch's own GA
    # DOR citation (2026 Employer's Tax Guide, revised June 2026,
    # incorporating HB 1199) explicitly flags that competing secondary
    # aggregators showed 5.09%/5.19%/5.29% and resolves the conflict in
    # favor of the actual DOR document's 4.99%. Dependent deduction
    # ($5,000/dependent) is NOT applied here — this engine has no
    # per-employee "number of dependents" field for any US state, so this
    # is a documented simplification (results in slightly MORE withholding
    # than an employee with dependents actually owes — the safe direction,
    # not an under-withholding risk).
    "GA": dict(
        agency="Georgia DOR",
        source_title="2026 Employer's Tax Guide (Revised June 2026, HB 1199) — flat 4.99%",
        rate_pct=Decimal("4.99"),
        allowance_by_filing_status={"MFJ": Decimal("30000.00"), None: Decimal("15000.00")},
    ),
    # Iowa Senate File 2442 completed the state's transition to a flat tax
    # for 2026 — no brackets. Deduction varies by IA W-4 marital-status
    # selection, a concept this engine doesn't track separately from the
    # generic w4_filing_status; MFJ is mapped to the "spouse has earned
    # income" $26,000 figure (the more common two-earner-household case)
    # rather than the $19,500 "spouse has no earned income" alternative —
    # a documented simplification, not a sourced MFJ-specific figure. MFS
    # has no deduction figure in this batch at all (not mentioned in the
    # source) and is left unconfigured (falls back to $0 — over-withholds
    # an MFS filer until sourced). The $40/allowance figure for legacy
    # (pre-2024) IA W-4 filers is NOT applied — no per-employee allowance-
    # count field exists for Iowa.
    "IA": dict(
        agency="Iowa Department of Revenue",
        source_title="Iowa Individual Income Tax Withholding Formula, effective 2026-01-01 (Senate File 2442 flat tax)",
        rate_pct=Decimal("3.80"),
        allowance_by_filing_status={"SINGLE": Decimal("13000.00"), "HOH": Decimal("26000.00"), "MFJ": Decimal("26000.00")},
    ),
    # Gap-closure Level 2, Batch 4/5 (2026-09-13), genuine primary-source
    # data (real government URLs). North Carolina: NCDOR's own NC-30
    # deliberately withholds at 4.09%, not the 3.99% statutory filing
    # rate — a documented 0.1-point buffer built into the withholding
    # tables themselves (confirmed by NC-30's own worked example), NOT a
    # transcription error. MFS standard deduction ($6,375) is half of
    # MFJ's $12,750 per NC-30's own stated convention ("half of MFJ,
    # consistent with NC convention") — not this build's own inference.
    "NC": dict(
        agency="North Carolina Department of Revenue",
        source_title="NCDOR NC-30, Income Tax Withholding Tables and Instructions for Employers, effective 2026-01-01",
        rate_pct=Decimal("4.09"),
        allowance_by_filing_status={
            "SINGLE": Decimal("12750.00"), "MFJ": Decimal("12750.00"),
            "HOH": Decimal("19125.00"), "MFS": Decimal("6375.00"),
        },
    ),
    # Utah: flat rate DROPPED mid-2026 (S.B. 60) from 4.50% to 4.45%
    # effective pay periods on/after 2026-06-01. Only the CURRENT
    # (post-2026-06-01) rate/allowance is modeled — this session's own
    # date is already past that transition, and this engine's TaxSlab
    # lookup for this state has no effective-dating support to represent
    # two packages within one calendar year, so the now-historical
    # Jan-May figures (4.50%, $450/$900 allowances) are deliberately not
    # seeded. Base allowance amounts are FLAT per-filing-status constants
    # per Publication 14's own statement ("no subtraction is made for
    # personal or other withholding allowances... on the federal W-4") —
    # not an allowance-count-dependent figure like every other skipped
    # allowance in this file, so this one genuinely IS fully modeled, not
    # a documented gap. HOH/MFS (not named in the source) mapped to the
    # Single figure ($485) as the conservative default.
    "UT": dict(
        agency="Utah State Tax Commission",
        source_title="Utah Publication 14, Withholding Tax Guide, Rev. 4/26 — 4.45% effective 2026-06-01 (S.B. 60)",
        rate_pct=Decimal("4.45"),
        allowance_by_filing_status={"MFJ": Decimal("970.00"), None: Decimal("485.00")},
    ),
}

# PROVISIONAL / UNVERIFIED — gap-closure Level 2, 2026-09-12. These
# figures come from a SEPARATE internal tracking document
# ("US_2026_State_Local_Tax_Structured_Tracking.pdf") that names
# ZP-TAX-US-2026-001 as its source but does NOT actually match that
# document's own §4 Matrix for any of these states (which gives only
# a calculation-method classification, no literal rate) — meaning these
# numbers were not independently verified against a primary state DOR
# publication the way every other row in _US_STATE_TAX_RATES above was.
# Seeded as real, Active JurisdictionPack/TaxSlab data (so Super Admin
# can see, review and stage them) but DELIBERATELY KEPT OUT of
# _US_STATE_TAX_ENABLED_STATES (shared.py) — zero live-payroll effect
# until a human confirms each figure against that state's own official
# withholding form/publication and someone explicitly adds the state to
# that switch. Do not add a state here to the enabled-states set without
# that confirmation having actually happened.
#
# GA was REMOVED from this dict (2026-09-12, same session): a later batch
# of genuine primary-source data (real GA DOR citation, June-2026-revised
# Employer's Tax Guide, HB 1199) proved this dict's own 5.19% figure
# WRONG — the confirmed rate is 4.99%, now live in _US_STATE_TAX_RATES
# above. This is the exact failure mode provisional/dormant seeding
# exists to catch before it reaches a real payslip.
_US_STATE_TAX_RATES_PROVISIONAL = {
    "ID": dict(
        agency="Idaho State Tax Commission (UNVERIFIED)",
        source_title="Provisional — flat 5.30% per internal tracking sheet; NOT yet confirmed against an Idaho State Tax Commission publication",
        rate_pct=Decimal("5.30"),
        allowance_by_filing_status={},
    ),
    "MS": dict(
        agency="Mississippi DOR (UNVERIFIED)",
        source_title="Provisional — flat 4.00% per internal tracking sheet; NOT yet confirmed against an MS DOR publication",
        rate_pct=Decimal("4.00"),
        allowance_by_filing_status={},
    ),
    "NC": dict(
        agency="North Carolina DOR (UNVERIFIED)",
        source_title="Provisional — flat 3.99% per internal tracking sheet; NOT yet confirmed against an NC DOR publication",
        rate_pct=Decimal("3.99"),
        allowance_by_filing_status={},
    ),
    "UT": dict(
        agency="Utah State Tax Commission (UNVERIFIED)",
        source_title="Provisional — flat 4.50% per internal tracking sheet; NOT yet confirmed against a Utah State Tax Commission publication",
        rate_pct=Decimal("4.50"),
        allowance_by_filing_status={},
    ),
}

# Graduated (multi-bracket) state PIT — gap-closure Level 2 batch
# (2026-09-12), genuine primary-source data (real government URLs,
# explicit refusal to estimate missing figures — the same batch that
# corrected GA's rate above). Structurally different from
# _US_STATE_TAX_RATES (one flat rate) — each state here is a real list of
# MARGINAL_RATE brackets per filing status, seeded by
# scripts/populate_us_state_graduated_tax_v1.py, gated by the SAME
# _US_STATE_TAX_ENABLED_STATES switch as every other state.
#
# Known, documented simplifications shared across this whole dict (none
# of these require a NEW data model this engine doesn't have — each is a
# real per-employee fact this engine has no field for anywhere, for any
# US state, so implementing it correctly requires that field to exist
# first, not just this batch of data):
#   - No per-employee "number of dependents"/"number of allowances
#     claimed" field exists for any state. Every credit/allowance/
#     dependent-deduction figure in the source batch that depends on a
#     COUNT (CA's $168.30/allowance credit, DC's $4,150/dependent
#     allowance, HI's $1,144/allowance + $4,350 lump sum, DE's
#     $110/exemption credit) is NOT applied here. This is a strictly
#     OVER-withholding simplification (an employee who has claimed
#     allowances/dependents will see MORE withheld than their real
#     liability, never less) — the safe direction, not an under-
#     withholding risk.
#   - CA's Table 1 "Low Income Exemption" (a hard $0-withholding cliff
#     below a gross-wage threshold, separate from and in addition to the
#     standard deduction) is NOT implemented — this engine's bracket/
#     standard-deduction mechanism has no "exemption gate" concept at
#     all; adding one is real new engine architecture, not a data-entry
#     task, and is out of scope for this batch. A CA employee at/just
#     above the exemption threshold will be over-withheld a small,
#     bounded amount until this gate exists.
#   - CA's Married-filing-status standard deduction genuinely depends on
#     NUMBER OF ALLOWANCES claimed (0-1 vs 2+), which this engine has no
#     field for; MFJ is mapped to the 2+-allowances figure ($11,412) as
#     the more common default — a documented approximation, not the
#     $5,706 that a true 0-1-allowance MFJ filer should get.
#   - DE's standard deduction has no HOH figure in this batch at all (not
#     captured from the source) — left unconfigured (defaults to $0,
#     over-withholds a DE HOH filer) rather than guessed.
_US_STATE_GRADUATED_TAX_RATES = {
    "CA": dict(
        agency="California EDD",
        source_title="California Withholding Schedules for 2026, Method B (Exact Calculation) — 26methb.pdf",
        # Table 5 (Single/Dual-Income Married/Multiple Employers) is
        # mapped to both SINGLE and MFS (the closest analog for a
        # separate-filing status); Table 6 (Married) to MFJ; Table 7
        # (Unmarried/HOH) to HOH.
        standard_deduction_by_filing_status={
            "SINGLE": Decimal("5706.00"), "MFS": Decimal("5706.00"),
            "MFJ": Decimal("11412.00"), "HOH": Decimal("11412.00"),
        },
        brackets_by_filing_status={
            "SINGLE": [
                (Decimal("0"), Decimal("11079"), Decimal("1.10")),
                (Decimal("11079"), Decimal("26264"), Decimal("2.20")),
                (Decimal("26264"), Decimal("41452"), Decimal("4.40")),
                (Decimal("41452"), Decimal("57542"), Decimal("6.60")),
                (Decimal("57542"), Decimal("72724"), Decimal("8.80")),
                (Decimal("72724"), Decimal("371479"), Decimal("10.23")),
                (Decimal("371479"), Decimal("445771"), Decimal("11.33")),
                (Decimal("445771"), Decimal("742953"), Decimal("12.43")),
                (Decimal("742953"), Decimal("1000000"), Decimal("13.53")),
                (Decimal("1000000"), None, Decimal("14.63")),
            ],
            "MFJ": [
                (Decimal("0"), Decimal("22158"), Decimal("1.10")),
                (Decimal("22158"), Decimal("52528"), Decimal("2.20")),
                (Decimal("52528"), Decimal("82904"), Decimal("4.40")),
                (Decimal("82904"), Decimal("115084"), Decimal("6.60")),
                (Decimal("115084"), Decimal("145448"), Decimal("8.80")),
                (Decimal("145448"), Decimal("742958"), Decimal("10.23")),
                (Decimal("742958"), Decimal("891542"), Decimal("11.33")),
                (Decimal("891542"), Decimal("1000000"), Decimal("12.43")),
                (Decimal("1000000"), Decimal("1485906"), Decimal("13.53")),
                (Decimal("1485906"), None, Decimal("14.63")),
            ],
            "HOH": [
                (Decimal("0"), Decimal("22173"), Decimal("1.10")),
                (Decimal("22173"), Decimal("52530"), Decimal("2.20")),
                (Decimal("52530"), Decimal("67716"), Decimal("4.40")),
                (Decimal("67716"), Decimal("83805"), Decimal("6.60")),
                (Decimal("83805"), Decimal("98990"), Decimal("8.80")),
                (Decimal("98990"), Decimal("505208"), Decimal("10.23")),
                (Decimal("505208"), Decimal("606251"), Decimal("11.33")),
                (Decimal("606251"), Decimal("1000000"), Decimal("12.43")),
                (Decimal("1000000"), Decimal("1010417"), Decimal("13.53")),
                (Decimal("1010417"), None, Decimal("14.63")),
            ],
        },
    ),
    "DC": dict(
        agency="DC Office of Tax and Revenue",
        source_title="DC OTR Individual and Fiduciary Income Tax Rates; 2026 D-40ES booklet (standard deduction)",
        standard_deduction_by_filing_status={
            "SINGLE": Decimal("16100.00"), "MFS": Decimal("16100.00"),
            "HOH": Decimal("24150.00"), "MFJ": Decimal("32200.00"),
        },
        # DC uses ONE bracket table regardless of filing status (unlike
        # every other jurisdiction in this batch) — seeded with
        # filing_status=None so it applies uniformly (see
        # _calculate_annual_tax's own untagged-row convention).
        brackets_by_filing_status={
            None: [
                (Decimal("0"), Decimal("10000"), Decimal("4.00")),
                (Decimal("10000"), Decimal("40000"), Decimal("6.00")),
                (Decimal("40000"), Decimal("60000"), Decimal("6.50")),
                (Decimal("60000"), Decimal("250000"), Decimal("8.50")),
                (Decimal("250000"), Decimal("500000"), Decimal("9.25")),
                (Decimal("500000"), Decimal("1000000"), Decimal("9.75")),
                (Decimal("1000000"), None, Decimal("10.75")),
            ],
        },
    ),
    "DE": dict(
        agency="Delaware Division of Revenue",
        source_title="DE Division of Revenue Employer's Guide §17, Tax Computation Table effective 2025-01-01 (unchanged into 2026)",
        # Bracket thresholds are identical regardless of filing status per
        # the source; HOH has no standard-deduction figure in this batch
        # (not captured) and is deliberately left unconfigured.
        standard_deduction_by_filing_status={
            "SINGLE": Decimal("3250.00"), "MFS": Decimal("3250.00"), "MFJ": Decimal("6500.00"),
        },
        brackets_by_filing_status={
            None: [
                (Decimal("0"), Decimal("2000"), Decimal("0.00")),
                (Decimal("2000"), Decimal("5000"), Decimal("2.20")),
                (Decimal("5000"), Decimal("10000"), Decimal("3.90")),
                (Decimal("10000"), Decimal("20000"), Decimal("4.80")),
                (Decimal("20000"), Decimal("25000"), Decimal("5.20")),
                (Decimal("25000"), Decimal("60000"), Decimal("5.55")),
                (Decimal("60000"), None, Decimal("6.60")),
            ],
        },
    ),
    "HI": dict(
        agency="Hawaii Department of Taxation",
        source_title="Appendix 2: Income Tax Withholding Tables for Taxable Years Beginning After 2025-12-31 (Announcement 2025-07, Act 46)",
        # No separate standard-deduction figure in this batch — HI's own
        # deduction mechanism is the per-allowance/lump-sum amounts
        # (skipped per this dict's own "no allowance-count field" note
        # above), not a flat standard deduction on top of that.
        standard_deduction_by_filing_status={},
        # "Single Persons – Including Unmarried Heads of Household" is one
        # combined table (SINGLE + HOH); "Married Persons" is mapped to
        # both MFJ and MFS (the source names only one "Married" table,
        # not split by Joint/Separate).
        brackets_by_filing_status={
            "SINGLE": [
                (Decimal("0"), Decimal("9600"), Decimal("1.40")),
                (Decimal("9600"), Decimal("14400"), Decimal("3.20")),
                (Decimal("14400"), Decimal("19200"), Decimal("5.50")),
                (Decimal("19200"), Decimal("24000"), Decimal("6.40")),
                (Decimal("24000"), Decimal("36000"), Decimal("6.80")),
                (Decimal("36000"), Decimal("48000"), Decimal("7.20")),
                (Decimal("48000"), Decimal("125000"), Decimal("7.60")),
                (Decimal("125000"), None, Decimal("7.90")),
            ],
            "HOH": [
                (Decimal("0"), Decimal("9600"), Decimal("1.40")),
                (Decimal("9600"), Decimal("14400"), Decimal("3.20")),
                (Decimal("14400"), Decimal("19200"), Decimal("5.50")),
                (Decimal("19200"), Decimal("24000"), Decimal("6.40")),
                (Decimal("24000"), Decimal("36000"), Decimal("6.80")),
                (Decimal("36000"), Decimal("48000"), Decimal("7.20")),
                (Decimal("48000"), Decimal("125000"), Decimal("7.60")),
                (Decimal("125000"), None, Decimal("7.90")),
            ],
            "MFJ": [
                (Decimal("0"), Decimal("19200"), Decimal("1.40")),
                (Decimal("19200"), Decimal("28800"), Decimal("3.20")),
                (Decimal("28800"), Decimal("38400"), Decimal("5.50")),
                (Decimal("38400"), Decimal("48000"), Decimal("6.40")),
                (Decimal("48000"), Decimal("72000"), Decimal("6.80")),
                (Decimal("72000"), Decimal("96000"), Decimal("7.20")),
                (Decimal("96000"), Decimal("250000"), Decimal("7.60")),
                (Decimal("250000"), None, Decimal("7.90")),
            ],
            "MFS": [
                (Decimal("0"), Decimal("19200"), Decimal("1.40")),
                (Decimal("19200"), Decimal("28800"), Decimal("3.20")),
                (Decimal("28800"), Decimal("38400"), Decimal("5.50")),
                (Decimal("38400"), Decimal("48000"), Decimal("6.40")),
                (Decimal("48000"), Decimal("72000"), Decimal("6.80")),
                (Decimal("72000"), Decimal("96000"), Decimal("7.20")),
                (Decimal("96000"), Decimal("250000"), Decimal("7.60")),
                (Decimal("250000"), None, Decimal("7.90")),
            ],
        },
    ),
    # Alabama (gap-closure Level 2 batch, primary source: ALDOR Withholding
    # Tax Tables and Instructions, revised January 2026). The bracket
    # table itself is COMPLETE and literal — only the SEPARATE graduated
    # standard-deduction schedule, the graduated dependent exemption, and
    # AL's own unique "deduct your federal tax liability" mechanism are
    # incomplete/unsupported and deliberately NOT modeled here (all three
    # would REDUCE Alabama taxable income further, so omitting them is an
    # over-withholding-direction simplification, not an under-withholding
    # risk). What IS modeled as state_standard_deduction is ONLY Alabama's
    # flat personal exemption ($1,500 Single/MFS, $3,000 Married Joint/
    # Head of Family) — a real, complete, literal figure, just a smaller
    # deduction than an actual AL employee's full entitlement.
    #
    # Structural quirk, modeled deliberately: Head of Family shares the
    # SAME rate brackets as Single/MFS (a 3-band $500/$3,000 schedule) but
    # gets the LARGER $3,000 exemption that Married Joint gets — these are
    # two independently-tagged lookups (TaxSlab.filing_status vs
    # ContributionRate.filing_status), so HOH is tagged into the Single/
    # MFS bracket group while separately getting the MFJ-level exemption
    # amount.
    "AL": dict(
        agency="Alabama Department of Revenue",
        source_title="ALDOR Withholding Tax Tables and Instructions for Employers and Withholding Agents, Revised January 2026",
        standard_deduction_by_filing_status={
            "SINGLE": Decimal("1500.00"), "MFS": Decimal("1500.00"),
            "HOH": Decimal("3000.00"), "MFJ": Decimal("3000.00"),
        },
        brackets_by_filing_status={
            "SINGLE": [
                (Decimal("0"), Decimal("500"), Decimal("2.00")),
                (Decimal("500"), Decimal("3000"), Decimal("4.00")),
                (Decimal("3000"), None, Decimal("5.00")),
            ],
            "MFS": [
                (Decimal("0"), Decimal("500"), Decimal("2.00")),
                (Decimal("500"), Decimal("3000"), Decimal("4.00")),
                (Decimal("3000"), None, Decimal("5.00")),
            ],
            "HOH": [
                (Decimal("0"), Decimal("500"), Decimal("2.00")),
                (Decimal("500"), Decimal("3000"), Decimal("4.00")),
                (Decimal("3000"), None, Decimal("5.00")),
            ],
            "MFJ": [
                (Decimal("0"), Decimal("1000"), Decimal("2.00")),
                (Decimal("1000"), Decimal("6000"), Decimal("4.00")),
                (Decimal("6000"), None, Decimal("5.00")),
            ],
        },
    ),
    # Arkansas (gap-closure Level 2, resolved batch, primary source: AR
    # DFA Withholding Tax Formula, effective 2026-01-01). The source's own
    # "rate × income − adjustment" presentation is algebraically
    # equivalent to a marginal bracket sum (verified by hand against the
    # DFA's own worked example: monthly $2,127/2 exemptions -> this
    # engine's marginal conversion produces $495.84 vs. the source's own
    # $495.73 before its final $50-rounding step — a one-cent-scale
    # rounding difference, not a real discrepancy). One unified schedule
    # for every filing status (filing_status=None, applies uniformly).
    #
    # Two deliberate simplifications, both DOCUMENTED, both in the
    # over-withholding (never under-withholding) direction:
    #   - The source's own $50-midrange rounding of taxable income below
    #     $100,001 is NOT applied — this engine computes on the exact
    #     dollar amount instead. Effect is at most a few cents either way,
    #     not worth new bracket-independent rounding logic for.
    #   - The $29.00-per-exemption tax CREDIT (subtracted from computed
    #     tax, not from income) is NOT applied — no per-employee
    #     "number of AR exemptions" field exists in this engine.
    #   - The source's own "$94,701 and over, fine-grained $100 bands,
    #     adjustment decreasing by $10 per band" tier was NOT
    #     reconstructed — that description is internally inconsistent
    #     (starts at $94,701 but references "$97,701+"/"$97,601+") and a
    #     decreasing adjustment at ever-higher income doesn't fit a
    #     normal progressive schedule; treated instead as a continuation
    #     of the prior 3.70%/$367.16 band, which is the FTA table's own
    #     published top marginal rate anyway — only the exact cent-level
    #     transition in that narrow ~$3,000 band is approximated.
    "AR": dict(
        agency="Arkansas Department of Finance and Administration",
        source_title="State of Arkansas Withholding Tax Formula Method, effective 2026-01-01",
        standard_deduction_by_filing_status={None: Decimal("2470.00")},
        brackets_by_filing_status={
            None: [
                (Decimal("0"), Decimal("5600"), Decimal("0.00")),
                (Decimal("5600"), Decimal("11200"), Decimal("2.00")),
                (Decimal("11200"), Decimal("16000"), Decimal("3.00")),
                (Decimal("16000"), Decimal("26400"), Decimal("3.40")),
                (Decimal("26400"), None, Decimal("3.70")),
            ],
        },
    ),
    # Minnesota (gap-closure Level 2, resolved batch, primary source: MN
    # DOR 2026 Withholding Tax Instructions and Tables, p.34 Computer
    # Formula). IMPORTANT: this is the WITHHOLDING-specific chart, a
    # genuinely different, independently-calibrated table from the
    # annual-filing brackets MN DOR's own press release gives (which this
    # engine does NOT use for payroll withholding — using those would be
    # wrong, per the source's own explicit clarification). No standard-
    # deduction phase-out exists at the withholding-formula level at all
    # (resolves the earlier open question from Batch 1).
    #
    # The chart only names "Single" and "Married" — mapped SINGLE->Single,
    # MFJ and MFS both ->Married (the source gives no separate MFS
    # withholding chart, and state W-4 elections are commonly this
    # coarse). HOH has NO row in this withholding-specific chart (unlike
    # the annual-filing brackets, which do have one) — mapped to the
    # Single table here as the more common real-world default when a
    # state withholding certificate has no distinct HOH option, rather
    # than left at $0 (which would UNDER-withhold, the wrong-direction
    # risk for an unconfigured mapping, unlike every other gap in this
    # batch).
    #
    # The formula's own Step 3 ($5,300 × number of W-4MN allowances,
    # subtracted from wages) is NOT applied — no per-employee "number of
    # MN allowances" field exists in this engine; an unconfigured
    # state_standard_deduction (this dict leaves it empty for MN,
    # correctly, since MN's real formula has no separate flat deduction
    # component at all beyond that allowance subtraction) means every MN
    # employee is over-withheld by whatever their real allowance count
    # would have saved them — the safe direction.
    "MN": dict(
        agency="Minnesota Department of Revenue",
        source_title="2026 Minnesota Withholding Tax Instructions and Tables, p.34 Computer Formula (effective 2026-01-01)",
        standard_deduction_by_filing_status={},
        brackets_by_filing_status={
            "SINGLE": [
                (Decimal("0"), Decimal("4700"), Decimal("0.00")),
                (Decimal("4700"), Decimal("38010"), Decimal("5.35")),
                (Decimal("38010"), Decimal("114130"), Decimal("6.80")),
                (Decimal("114130"), Decimal("207850"), Decimal("7.85")),
                (Decimal("207850"), None, Decimal("9.85")),
            ],
            "HOH": [
                (Decimal("0"), Decimal("4700"), Decimal("0.00")),
                (Decimal("4700"), Decimal("38010"), Decimal("5.35")),
                (Decimal("38010"), Decimal("114130"), Decimal("6.80")),
                (Decimal("114130"), Decimal("207850"), Decimal("7.85")),
                (Decimal("207850"), None, Decimal("9.85")),
            ],
            "MFJ": [
                (Decimal("0"), Decimal("14700"), Decimal("0.00")),
                (Decimal("14700"), Decimal("63400"), Decimal("5.35")),
                (Decimal("63400"), Decimal("208180"), Decimal("6.80")),
                (Decimal("208180"), Decimal("352630"), Decimal("7.85")),
                (Decimal("352630"), None, Decimal("9.85")),
            ],
            "MFS": [
                (Decimal("0"), Decimal("14700"), Decimal("0.00")),
                (Decimal("14700"), Decimal("63400"), Decimal("5.35")),
                (Decimal("63400"), Decimal("208180"), Decimal("6.80")),
                (Decimal("208180"), Decimal("352630"), Decimal("7.85")),
                (Decimal("352630"), None, Decimal("9.85")),
            ],
        },
    ),
    # Mississippi (gap-closure Level 2, Batch 4, 2026-09-13). Rate
    # conflict resolved in favor of MS DOR's own Jan-2026 publication
    # (4.0%, continuing MS's legislated phase-down). ONE unified bracket
    # (filing_status=None) — only the exemption+deduction combination
    # differs by status. MFS not separately given (the source only notes
    # the $12,000 joint exemption "may be split... in multiples of $500"
    # between spouses with no stated default split) — mapped to Single's
    # combined figure ($8,300) as the conservative default. Dependent/
    # age/blind add-ons ($1,500 each) NOT applied — no per-employee count
    # field for any of the three exists in this engine.
    "MS": dict(
        agency="Mississippi Department of Revenue",
        source_title="MS DOR Pub 89-700-25-1 (Rev. 1/13/2026), Withholding Income Tax Tables and Employer Instructions",
        standard_deduction_by_filing_status={
            "SINGLE": Decimal("8300.00"), "MFS": Decimal("8300.00"),
            "HOH": Decimal("12900.00"), "MFJ": Decimal("16600.00"),
        },
        brackets_by_filing_status={
            None: [
                (Decimal("0"), Decimal("10000"), Decimal("0.00")),
                (Decimal("10000"), None, Decimal("4.00")),
            ],
        },
    ),
    # Montana (gap-closure Level 2, Batch 4, 2026-09-13). Genuinely
    # different mechanic confirmed from primary source: MT eliminated its
    # own exemption/deduction system for 2026 (HB 337) and now uses the
    # FEDERAL standard deduction amount by federal filing status directly
    # — so the figures below are NOT Montana-specific numbers, they are
    # this engine's own already-live federal standard_deduction values
    # (see hardcoded_defaults._US_STANDARD_DEDUCTION callers / the
    # federal ContributionRate rows fixed earlier this session),
    # reused here per MT DOR's own explicit instruction. MFS mapped to
    # the "all other statuses" bracket group per MT's own grouping.
    "MT": dict(
        agency="Montana Department of Revenue",
        source_title="MT DOR 2026 Withholding Updates (2025-12-08) / Montana Employer and Information Agent Guide (HB 337)",
        standard_deduction_by_filing_status={
            "SINGLE": Decimal("16100.00"), "MFS": Decimal("16100.00"),
            "HOH": Decimal("24150.00"), "MFJ": Decimal("32200.00"),
        },
        brackets_by_filing_status={
            "SINGLE": [(Decimal("0"), Decimal("47500"), Decimal("4.70")), (Decimal("47500"), None, Decimal("5.65"))],
            "MFS": [(Decimal("0"), Decimal("47500"), Decimal("4.70")), (Decimal("47500"), None, Decimal("5.65"))],
            "HOH": [(Decimal("0"), Decimal("71250"), Decimal("4.70")), (Decimal("71250"), None, Decimal("5.65"))],
            "MFJ": [(Decimal("0"), Decimal("95000"), Decimal("4.70")), (Decimal("95000"), None, Decimal("5.65"))],
        },
    ),
    # Nebraska (gap-closure Level 2, Batch 4, 2026-09-13). "Single
    # (including Head of Household)" per the source's own table naming
    # — SINGLE and HOH share one table. MFS not separately given —
    # mapped to the Single/HOH table (narrower thresholds, the
    # conservative/over-withholding default used throughout this batch
    # for any status the source doesn't name). The $2,440/allowance
    # figure is NOT applied — the source itself flags it as only
    # "per secondary corroboration," not primary-confirmed, and even if
    # it were, no per-employee NE allowance-count field exists anyway.
    "NE": dict(
        agency="Nebraska Department of Revenue",
        source_title="NE DOR 2026 Nebraska Circular EN, Percentage Method Tables, Table 7 (Annual), effective 2026-01-01",
        standard_deduction_by_filing_status={},
        brackets_by_filing_status={
            "SINGLE": [
                (Decimal("0"), Decimal("3430"), Decimal("0.00")),
                (Decimal("3430"), Decimal("6710"), Decimal("2.26")),
                (Decimal("6710"), Decimal("21810"), Decimal("3.22")),
                (Decimal("21810"), Decimal("31610"), Decimal("4.21")),
                (Decimal("31610"), Decimal("40130"), Decimal("4.35")),
                (Decimal("40130"), Decimal("75370"), Decimal("4.48")),
                (Decimal("75370"), None, Decimal("4.60")),
            ],
            "HOH": [
                (Decimal("0"), Decimal("3430"), Decimal("0.00")),
                (Decimal("3430"), Decimal("6710"), Decimal("2.26")),
                (Decimal("6710"), Decimal("21810"), Decimal("3.22")),
                (Decimal("21810"), Decimal("31610"), Decimal("4.21")),
                (Decimal("31610"), Decimal("40130"), Decimal("4.35")),
                (Decimal("40130"), Decimal("75370"), Decimal("4.48")),
                (Decimal("75370"), None, Decimal("4.60")),
            ],
            "MFS": [
                (Decimal("0"), Decimal("3430"), Decimal("0.00")),
                (Decimal("3430"), Decimal("6710"), Decimal("2.26")),
                (Decimal("6710"), Decimal("21810"), Decimal("3.22")),
                (Decimal("21810"), Decimal("31610"), Decimal("4.21")),
                (Decimal("31610"), Decimal("40130"), Decimal("4.35")),
                (Decimal("40130"), Decimal("75370"), Decimal("4.48")),
                (Decimal("75370"), None, Decimal("4.60")),
            ],
            "MFJ": [
                (Decimal("0"), Decimal("8190"), Decimal("0.00")),
                (Decimal("8190"), Decimal("13010"), Decimal("2.26")),
                (Decimal("13010"), Decimal("32400"), Decimal("3.22")),
                (Decimal("32400"), Decimal("50400"), Decimal("4.21")),
                (Decimal("50400"), Decimal("62530"), Decimal("4.35")),
                (Decimal("62530"), Decimal("82920"), Decimal("4.48")),
                (Decimal("82920"), None, Decimal("4.60")),
            ],
        },
    ),
    # New Mexico (gap-closure Level 2, Batch 4, 2026-09-13). Single, MFJ,
    # HOH all given explicitly; MFS not named — mapped to Single (the
    # conservative default). No standard deduction beyond the bracket's
    # own 0% floor (NM's percentage method has no separate flat
    # deduction figure in this source).
    "NM": dict(
        agency="New Mexico Taxation and Revenue Department",
        source_title="NM TRD FYI-104, New Mexico Withholding Tax (Rev. 11/2024, rates continuing per Rev. 11/2025 edition)",
        standard_deduction_by_filing_status={},
        brackets_by_filing_status={
            "SINGLE": [
                (Decimal("0"), Decimal("7500"), Decimal("0.00")),
                (Decimal("7500"), Decimal("13000"), Decimal("1.50")),
                (Decimal("13000"), Decimal("24000"), Decimal("3.20")),
                (Decimal("24000"), Decimal("41000"), Decimal("4.30")),
                (Decimal("41000"), Decimal("74000"), Decimal("4.70")),
                (Decimal("74000"), Decimal("217500"), Decimal("4.90")),
                (Decimal("217500"), None, Decimal("5.90")),
            ],
            "MFS": [
                (Decimal("0"), Decimal("7500"), Decimal("0.00")),
                (Decimal("7500"), Decimal("13000"), Decimal("1.50")),
                (Decimal("13000"), Decimal("24000"), Decimal("3.20")),
                (Decimal("24000"), Decimal("41000"), Decimal("4.30")),
                (Decimal("41000"), Decimal("74000"), Decimal("4.70")),
                (Decimal("74000"), Decimal("217500"), Decimal("4.90")),
                (Decimal("217500"), None, Decimal("5.90")),
            ],
            "MFJ": [
                (Decimal("0"), Decimal("15000"), Decimal("0.00")),
                (Decimal("15000"), Decimal("23000"), Decimal("1.50")),
                (Decimal("23000"), Decimal("40000"), Decimal("3.20")),
                (Decimal("40000"), Decimal("65000"), Decimal("4.30")),
                (Decimal("65000"), Decimal("101000"), Decimal("4.70")),
                (Decimal("101000"), Decimal("330000"), Decimal("4.90")),
                (Decimal("330000"), None, Decimal("5.90")),
            ],
            "HOH": [
                (Decimal("0"), Decimal("11250"), Decimal("0.00")),
                (Decimal("11250"), Decimal("19250"), Decimal("1.50")),
                (Decimal("19250"), Decimal("36250"), Decimal("3.20")),
                (Decimal("36250"), Decimal("61250"), Decimal("4.30")),
                (Decimal("61250"), Decimal("97250"), Decimal("4.70")),
                (Decimal("97250"), Decimal("326250"), Decimal("4.90")),
                (Decimal("326250"), None, Decimal("5.90")),
            ],
        },
    ),
    # North Dakota (gap-closure Level 2, Batch 4, 2026-09-13). Genuinely
    # different tables depending on the employee's OWN Form W-4 vintage
    # (a real, live-but-previously-unused field, models.PayrollEmployee.
    # w4_form_vintage — the first state this batch's own logic actually
    # consumes it for). Tagged as composite keys ("SINGLE_ND2020"/
    # "SINGLE_NDPRE2020"/etc) built by engine/countries/us.py's own
    # ND-specific branch, NOT a plain filing_status — see that file's
    # own comment. MFS not given for either vintage; mapped to the
    # narrower Single/HOH-equivalent table for that same vintage.
    "ND": dict(
        agency="ND Office of State Tax Commissioner",
        source_title="ND Withholding Rates & Instructions for wages paid in 2026",
        standard_deduction_by_filing_status={},
        brackets_by_filing_status={
            # 2020+ Form W-4 (annual percentage method, by federal filing status)
            "SINGLE_ND2020": [
                (Decimal("0"), Decimal("57625"), Decimal("0.00")),
                (Decimal("57625"), Decimal("258450"), Decimal("1.95")),
                (Decimal("258450"), None, Decimal("2.50")),
            ],
            "MFS_ND2020": [
                (Decimal("0"), Decimal("57625"), Decimal("0.00")),
                (Decimal("57625"), Decimal("258450"), Decimal("1.95")),
                (Decimal("258450"), None, Decimal("2.50")),
            ],
            "MFJ_ND2020": [
                (Decimal("0"), Decimal("57500"), Decimal("0.00")),
                (Decimal("57500"), Decimal("168525"), Decimal("1.95")),
                (Decimal("168525"), None, Decimal("2.50")),
            ],
            "HOH_ND2020": [
                (Decimal("0"), Decimal("78475"), Decimal("0.00")),
                (Decimal("78475"), Decimal("289675"), Decimal("1.95")),
                (Decimal("289675"), None, Decimal("2.50")),
            ],
            # Pre-2020 Form W-4 (allowance already subtracted before this
            # table applies per the source's own note — but no per-
            # employee ND allowance-count field exists in this engine, so
            # this path is only reachable via an employee explicitly
            # flagged w4_form_vintage="PRE_2020" with NO allowance
            # subtraction applied, i.e. taxed on full annual wages against
            # these lower (already-allowance-adjusted-in-the-source)
            # thresholds — a documented over-withholding-direction gap
            # for any pre-2020-vintage ND employee who'd have claimed a
            # real allowance.
            "SINGLE_NDPRE2020": [
                (Decimal("0"), Decimal("14406"), Decimal("0.00")),
                (Decimal("14406"), Decimal("64613"), Decimal("1.95")),
                (Decimal("64613"), None, Decimal("2.50")),
            ],
            "HOH_NDPRE2020": [
                (Decimal("0"), Decimal("14406"), Decimal("0.00")),
                (Decimal("14406"), Decimal("64613"), Decimal("1.95")),
                (Decimal("64613"), None, Decimal("2.50")),
            ],
            "MFS_NDPRE2020": [
                (Decimal("0"), Decimal("14375"), Decimal("0.00")),
                (Decimal("14375"), Decimal("42131"), Decimal("1.95")),
                (Decimal("42131"), None, Decimal("2.50")),
            ],
            "MFJ_NDPRE2020": [
                (Decimal("0"), Decimal("14375"), Decimal("0.00")),
                (Decimal("14375"), Decimal("42131"), Decimal("1.95")),
                (Decimal("42131"), None, Decimal("2.50")),
            ],
        },
    ),
    # New Jersey (gap-closure Level 2, Batch 4, 2026-09-13). NJ selects
    # one of FIVE Rate Tables (A-E) via Form NJ-W4 — a genuinely
    # different election from federal filing status (models.
    # PayrollEmployee.nj_rate_table). Tagged directly as "A"/"B"/"C"/"D"/
    # "E" (not composited with filing status) and selected by engine/
    # countries/us.py's own NJ-specific branch. The $1,000/year allowance
    # (same figure for every table) is NOT applied — no per-employee NJ
    # allowance-count field exists. An employee with work_state="NJ" but
    # no nj_rate_table on file resolves to $0, never a guessed table.
    "NJ": dict(
        agency="NJ Division of Taxation",
        source_title="NJ Division of Taxation, Tables for Percentage Method of Withholding (effective for wages paid on/after 2020-10-01, unchanged into 2026)",
        standard_deduction_by_filing_status={},
        brackets_by_filing_status={
            "A": [
                (Decimal("0"), Decimal("20000"), Decimal("1.5")),
                (Decimal("20000"), Decimal("35000"), Decimal("2.0")),
                (Decimal("35000"), Decimal("40000"), Decimal("3.9")),
                (Decimal("40000"), Decimal("75000"), Decimal("6.1")),
                (Decimal("75000"), Decimal("500000"), Decimal("7.0")),
                (Decimal("500000"), Decimal("1000000"), Decimal("9.9")),
                (Decimal("1000000"), None, Decimal("11.8")),
            ],
            "B": [
                (Decimal("0"), Decimal("20000"), Decimal("1.5")),
                (Decimal("20000"), Decimal("50000"), Decimal("2.0")),
                (Decimal("50000"), Decimal("70000"), Decimal("2.7")),
                (Decimal("70000"), Decimal("80000"), Decimal("3.9")),
                (Decimal("80000"), Decimal("150000"), Decimal("6.1")),
                (Decimal("150000"), Decimal("500000"), Decimal("7.0")),
                (Decimal("500000"), Decimal("1000000"), Decimal("9.9")),
                (Decimal("1000000"), None, Decimal("11.8")),
            ],
            "C": [
                (Decimal("0"), Decimal("20000"), Decimal("1.5")),
                (Decimal("20000"), Decimal("40000"), Decimal("2.3")),
                (Decimal("40000"), Decimal("50000"), Decimal("2.8")),
                (Decimal("50000"), Decimal("60000"), Decimal("3.5")),
                (Decimal("60000"), Decimal("150000"), Decimal("5.6")),
                (Decimal("150000"), Decimal("500000"), Decimal("6.6")),
                (Decimal("500000"), Decimal("1000000"), Decimal("9.9")),
                (Decimal("1000000"), None, Decimal("11.8")),
            ],
            "D": [
                (Decimal("0"), Decimal("20000"), Decimal("1.5")),
                (Decimal("20000"), Decimal("40000"), Decimal("2.7")),
                (Decimal("40000"), Decimal("50000"), Decimal("3.4")),
                (Decimal("50000"), Decimal("60000"), Decimal("4.3")),
                (Decimal("60000"), Decimal("150000"), Decimal("5.6")),
                (Decimal("150000"), Decimal("500000"), Decimal("6.5")),
                (Decimal("500000"), Decimal("1000000"), Decimal("9.9")),
                (Decimal("1000000"), None, Decimal("11.8")),
            ],
            "E": [
                (Decimal("0"), Decimal("20000"), Decimal("1.5")),
                (Decimal("20000"), Decimal("35000"), Decimal("2.0")),
                (Decimal("35000"), Decimal("100000"), Decimal("5.8")),
                (Decimal("100000"), Decimal("500000"), Decimal("6.5")),
                (Decimal("500000"), Decimal("1000000"), Decimal("9.9")),
                (Decimal("1000000"), None, Decimal("11.8")),
            ],
        },
    ),
    # Oklahoma (gap-closure Level 2, Batch 5, 2026-09-13). Brackets given
    # AFTER allowance subtraction, which is NOT applied here (no per-
    # employee OK allowance-count field) — brackets applied directly to
    # gross, an over-withholding-direction gap same as everywhere else.
    # HOH/MFS not named — mapped to Single (conservative default).
    "OK": dict(
        agency="Oklahoma Tax Commission",
        source_title="OTC Packet OW-2, 2026 Oklahoma Income Tax Withholding Tables (Rev. 11-2025), Table 7 (Annual)",
        standard_deduction_by_filing_status={},
        brackets_by_filing_status={
            "SINGLE": [
                (Decimal("0"), Decimal("7500"), Decimal("0.00")),
                (Decimal("7500"), Decimal("8350"), Decimal("2.5")),
                (Decimal("8350"), Decimal("10050"), Decimal("3.5")),
                (Decimal("10050"), None, Decimal("4.5")),
            ],
            "HOH": [
                (Decimal("0"), Decimal("7500"), Decimal("0.00")),
                (Decimal("7500"), Decimal("8350"), Decimal("2.5")),
                (Decimal("8350"), Decimal("10050"), Decimal("3.5")),
                (Decimal("10050"), None, Decimal("4.5")),
            ],
            "MFS": [
                (Decimal("0"), Decimal("7500"), Decimal("0.00")),
                (Decimal("7500"), Decimal("8350"), Decimal("2.5")),
                (Decimal("8350"), Decimal("10050"), Decimal("3.5")),
                (Decimal("10050"), None, Decimal("4.5")),
            ],
            "MFJ": [
                (Decimal("0"), Decimal("15000"), Decimal("0.00")),
                (Decimal("15000"), Decimal("16700"), Decimal("2.5")),
                (Decimal("16700"), Decimal("20100"), Decimal("3.5")),
                (Decimal("20100"), None, Decimal("4.5")),
            ],
        },
    ),
    # Rhode Island (gap-closure Level 2, Batch 5, 2026-09-13). ONE
    # bracket table for every filing status (filing_status=None,
    # confirmed explicitly: "Rhode Island's brackets are uniform across
    # all filing statuses"). The $1,000/year exemption is NOT applied —
    # no per-employee RI exemption-count field exists.
    "RI": dict(
        agency="RI Division of Taxation",
        source_title="RI Division of Taxation, 2026 Employer's Income Tax Withholding Tables (Draft 11/07/2025), effective 2026-01-01",
        standard_deduction_by_filing_status={},
        brackets_by_filing_status={
            None: [
                (Decimal("0"), Decimal("82050"), Decimal("3.75")),
                (Decimal("82050"), Decimal("186450"), Decimal("4.75")),
                (Decimal("186450"), None, Decimal("5.99")),
            ],
        },
    ),
    # South Carolina (gap-closure Level 2, Batch 5, 2026-09-13). Brackets
    # applied to gross wages directly — SC's own formula additionally
    # subtracts a $5,000/allowance personal allowance AND a "10% of
    # gross, capped at $7,500" standard deduction, but ONLY when the
    # employee has claimed 1+ allowances; an employee with ZERO
    # allowances claimed gets $0 for both per the source's own formula.
    # This engine has no per-employee SC allowance-count field, so what's
    # implemented here is EXACTLY SC's own "zero allowances claimed"
    # case — not an approximation of it. An employee who has actually
    # claimed allowances will be over-withheld relative to their real SC
    # liability (documented, same-direction gap as everywhere else).
    # ONE bracket table for every filing status (SC's formula doesn't
    # vary by filing status at all, only by allowances/income).
    "SC": dict(
        agency="South Carolina Department of Revenue",
        source_title="SCDOR WH-1603F, Formula for Computing South Carolina 2026 Withholding Tax (Rev. 11/4/25)",
        standard_deduction_by_filing_status={},
        brackets_by_filing_status={
            None: [
                (Decimal("0"), Decimal("3640"), Decimal("0.00")),
                (Decimal("3640"), Decimal("18230"), Decimal("3.00")),
                (Decimal("18230"), None, Decimal("6.00")),
            ],
        },
    ),
    # Vermont (gap-closure Level 2, Batch 6, 2026-09-13). Single and
    # Married tables given explicitly; HOH/MFS not named — mapped to
    # Single (the conservative default used throughout this build-out
    # for any status a source doesn't name). The $5,400/year allowance
    # is NOT applied — no per-employee VT allowance-count field exists.
    # Vermont's own Child Care Contribution (0.44% employer-only, same
    # wage base) is modeled separately as a state program, not here —
    # see _US_STATE_PROGRAMS["VT"].
    "VT": dict(
        agency="Vermont Department of Taxes",
        source_title="VT GB-1210, 2026 Income Tax Withholding Instructions, Tables, and Charts",
        standard_deduction_by_filing_status={},
        brackets_by_filing_status={
            "SINGLE": [
                (Decimal("0"), Decimal("3925"), Decimal("0.00")),
                (Decimal("3925"), Decimal("54675"), Decimal("3.35")),
                (Decimal("54675"), Decimal("126775"), Decimal("6.60")),
                (Decimal("126775"), Decimal("260225"), Decimal("7.60")),
                (Decimal("260225"), None, Decimal("8.75")),
            ],
            "HOH": [
                (Decimal("0"), Decimal("3925"), Decimal("0.00")),
                (Decimal("3925"), Decimal("54675"), Decimal("3.35")),
                (Decimal("54675"), Decimal("126775"), Decimal("6.60")),
                (Decimal("126775"), Decimal("260225"), Decimal("7.60")),
                (Decimal("260225"), None, Decimal("8.75")),
            ],
            "MFS": [
                (Decimal("0"), Decimal("3925"), Decimal("0.00")),
                (Decimal("3925"), Decimal("54675"), Decimal("3.35")),
                (Decimal("54675"), Decimal("126775"), Decimal("6.60")),
                (Decimal("126775"), Decimal("260225"), Decimal("7.60")),
                (Decimal("260225"), None, Decimal("8.75")),
            ],
            "MFJ": [
                (Decimal("0"), Decimal("11775"), Decimal("0.00")),
                (Decimal("11775"), Decimal("96475"), Decimal("3.35")),
                (Decimal("96475"), Decimal("216525"), Decimal("6.60")),
                (Decimal("216525"), Decimal("323825"), Decimal("7.60")),
                (Decimal("323825"), None, Decimal("8.75")),
            ],
        },
    ),
    # Virginia (gap-closure Level 2, Batch 6, 2026-09-13). ONE bracket
    # table for every filing status (VA's own source: "the same bracket
    # thresholds regardless of filing status — only the standard
    # deduction... differ"). Standard deduction uses the CURRENT (2026)
    # temporarily-increased figures ($8,750/$17,500) — the source itself
    # flags these as scheduled to sunset after Taxable Year 2026 back to
    # $3,000/$6,000; this engine has no effective-dating support for this
    # lookup, so only the figure applicable for all of TY2026 (the year
    # this whole build targets) is modeled — revisit for TY2027. The
    # additional $930/exemption and $800/age-blind-exemption reductions
    # are NOT applied — no per-employee VA exemption-count field exists.
    # HOH/MFS not named — mapped to Single's deduction figure.
    "VA": dict(
        agency="Virginia Department of Taxation",
        source_title="VA Income Tax Withholding Guide for Employers, Rev. 05/25 (wages paid after 2025-07-01, continuing through 2026)",
        standard_deduction_by_filing_status={
            "SINGLE": Decimal("8750.00"), "HOH": Decimal("8750.00"), "MFS": Decimal("8750.00"),
            "MFJ": Decimal("17500.00"),
        },
        brackets_by_filing_status={
            None: [
                (Decimal("0"), Decimal("3000"), Decimal("2.00")),
                (Decimal("3000"), Decimal("5000"), Decimal("3.00")),
                (Decimal("5000"), Decimal("17000"), Decimal("5.00")),
                (Decimal("17000"), None, Decimal("5.75")),
            ],
        },
    ),
    # West Virginia (gap-closure Level 2, Batch 6, 2026-09-13). WV
    # selects between "Two Earner/Two or More Jobs" and "Optional One
    # Earner/One Job" tables based on a real fact this engine doesn't
    # track for any employee (whether a MFJ employee's spouse also
    # works, or the employee holds multiple jobs) — NOT simply filing
    # status. Mapped: SINGLE/HOH/MFS -> One-Earner (matches the source's
    # own grouping exactly); MFJ -> Two-Earner, the CONSERVATIVE default
    # (WV's own source notes the Two-Earner table is deliberately higher
    # at each income level specifically "to reduce under-withholding
    # risk for dual-income households" — and dual-income marriages are
    # also the more common real-world case) rather than guessing every
    # WV MFJ employee has a nonworking spouse. The
    # $2,000/exemption allowance is NOT applied — no per-employee WV
    # allowance-count field exists.
    "WV": dict(
        agency="WV State Tax Division",
        source_title="WV IT-100.2A, Tables for Percentage Method of Withholding, March 2026",
        standard_deduction_by_filing_status={},
        brackets_by_filing_status={
            "SINGLE": [
                (Decimal("0"), Decimal("10000"), Decimal("2.11")),
                (Decimal("10000"), Decimal("25000"), Decimal("2.81")),
                (Decimal("25000"), Decimal("40000"), Decimal("3.16")),
                (Decimal("40000"), Decimal("60000"), Decimal("4.22")),
                (Decimal("60000"), None, Decimal("4.58")),
            ],
            "HOH": [
                (Decimal("0"), Decimal("10000"), Decimal("2.11")),
                (Decimal("10000"), Decimal("25000"), Decimal("2.81")),
                (Decimal("25000"), Decimal("40000"), Decimal("3.16")),
                (Decimal("40000"), Decimal("60000"), Decimal("4.22")),
                (Decimal("60000"), None, Decimal("4.58")),
            ],
            "MFS": [
                (Decimal("0"), Decimal("10000"), Decimal("2.11")),
                (Decimal("10000"), Decimal("25000"), Decimal("2.81")),
                (Decimal("25000"), Decimal("40000"), Decimal("3.16")),
                (Decimal("40000"), Decimal("60000"), Decimal("4.22")),
                (Decimal("60000"), None, Decimal("4.58")),
            ],
            "MFJ": [
                (Decimal("0"), Decimal("7500"), Decimal("2.11")),
                (Decimal("7500"), Decimal("18750"), Decimal("2.81")),
                (Decimal("18750"), Decimal("30000"), Decimal("3.16")),
                (Decimal("30000"), Decimal("45000"), Decimal("4.22")),
                (Decimal("45000"), None, Decimal("4.58")),
            ],
        },
    ),
    # Missouri (gap-closure Level 2, Batch 7 "Group B", 2026-09-13): one
    # bracket table applies to every filing status per MO DOR's own
    # formula — only the standard deduction differs. MO's MFJ standard
    # deduction genuinely depends on a "spouse works" checkbox on MO's own
    # W-4 (Form MO W-4), a fact this engine has no dedicated field for
    # (same class of gap as WV's One-Earner/Two-Earner table selection) —
    # defaults to the SPOUSE-WORKS amount ($16,100, same as Single/MFS),
    # the smaller deduction and therefore the conservative, over- (never
    # under-) withholding choice versus the $32,200 spouse-does-not-work
    # amount. MO's own "Federal Tax Deduction" subtraction step was
    # eliminated from the 2026 formula per the source's explicit note —
    # deliberately not carried forward from any older logic.
    "MO": dict(
        agency="Missouri Department of Revenue",
        source_title="MO DOR, 2026 Missouri Withholding Tax Formula; Form 4282 (Rev. 03-2026)",
        standard_deduction_by_filing_status={
            "SINGLE": Decimal("16100.00"), "MFS": Decimal("16100.00"),
            "MFJ": Decimal("16100.00"), "HOH": Decimal("24150.00"),
        },
        brackets_by_filing_status={
            fs: [
                (Decimal("0"), Decimal("1348"), Decimal("0.00")),
                (Decimal("1348"), Decimal("2696"), Decimal("2.00")),
                (Decimal("2696"), Decimal("4044"), Decimal("2.50")),
                (Decimal("4044"), Decimal("5392"), Decimal("3.00")),
                (Decimal("5392"), Decimal("6740"), Decimal("3.50")),
                (Decimal("6740"), Decimal("8088"), Decimal("4.00")),
                (Decimal("8088"), Decimal("9436"), Decimal("4.50")),
                (Decimal("9436"), None, Decimal("4.70")),
            ]
            for fs in ("SINGLE", "MFS", "MFJ", "HOH")
        },
    ),
    # Ohio (gap-closure Level 2, Batch 7 "Group B", 2026-09-13): ODT's
    # percentage-method table does NOT differentiate by filing status at
    # all (a single unified table) — filing_status key is None, same
    # convention RI/SC already use for their own filing-status-agnostic
    # tables. Genuine mid-year 2026 table transition (per House Bill 96):
    # only the August 1, 2026-onward table is seeded here, matching the
    # already-established Utah precedent (populate the CURRENT rate only
    # rather than building a second, earlier-2026 package) — this
    # platform is used for current/future payroll, not a historical
    # replay of pre-August-2026 Ohio pay periods, so the superseded
    # Oct-2025-Jul-2026 table is deliberately not reproduced. The
    # $12.50/week ($650.00/year) per-allowance value is NOT applied — it
    # depends on the employee's own claimed allowance COUNT, the same
    # "no per-employee allowance-count field" gap documented everywhere
    # else in this build (skipping it only ever over-withholds).
    "OH": dict(
        agency="Ohio Department of Taxation",
        source_title="ODT, Employer Withholding Taxes — Percentage Method, effective August 1, 2026 (HB 96)",
        standard_deduction_by_filing_status={},
        brackets_by_filing_status={
            None: [
                (Decimal("0"), Decimal("26050"), Decimal("0.00")),
                (Decimal("26050"), Decimal("100000"), Decimal("2.75")),
            ],
        },
    ),
    # New York (gap-closure Level 2, Batch 7 "Group B", 2026-09-13): the
    # source batch only fully specified Single and Married bracket
    # tables — Head of Household and Married Filing Separately tables
    # were not given. Rather than leave HOH/MFS employees resolving to
    # $0 (silently under-withholding, by far the worse failure mode),
    # both conservatively fall back to the SINGLE table, documented here
    # exactly like every other approximate filing-status mapping in this
    # build (e.g. NC's MFS=half-of-MFJ) — to be corrected once NY's own
    # HOH/MFS tables are sourced. The deduction/exemption allowance used
    # is the 0-exemptions figure per filing status (Single $7,400 /
    # Married $7,950) — the SMALLEST allowance NY's own Table A gives,
    # since the actual number of exemptions claimed isn't tracked (same
    # gap class as every other state's allowance/dependent-count figure,
    # always the conservative/over-withholding choice). The ultra-high-
    # earner "Method III" tiers (>$1,077,550: a FLAT rate on TOTAL
    # annualized wages, not a marginal continuation of the table below —
    # note every one of those rows' own "Base tax (Plus)" column is "—",
    # not a number) cannot be expressed as ordinary MARGINAL_RATE slab
    # rows at all; see us.py's post-processing override right after this
    # table's generic bracket-sum result. NYC's own resident tax is
    # DELIBERATELY NOT implemented — the source batch gave only 4 rate
    # figures and a single ($50,000 single-filer top-rate) threshold, not
    # the complete set of bracket breakpoints NYC's own NYS-50-T-NYC
    # table actually uses, and inventing the missing thresholds would be
    # exactly the fabrication this whole build has refused to do
    # everywhere else — flagged as needing that complete table before
    # implementation. Yonkers (both the resident 16.75%-of-NYS-liability
    # surcharge and the nonresident 0.50% flat earnings tax) IS fully
    # specified and implemented — see us.py.
    "NY": dict(
        agency="NYS Department of Taxation and Finance",
        source_title="NYS-50-T-NYS (1/26), Method II Exact Calculation",
        standard_deduction_by_filing_status={
            "SINGLE": Decimal("7400.00"), "MFS": Decimal("7400.00"), "HOH": Decimal("7400.00"),
            "MFJ": Decimal("7950.00"),
        },
        brackets_by_filing_status={
            "SINGLE": [
                (Decimal("0"), Decimal("8500"), Decimal("3.90")),
                (Decimal("8500"), Decimal("11700"), Decimal("4.40")),
                (Decimal("11700"), Decimal("13900"), Decimal("5.15")),
                (Decimal("13900"), Decimal("80650"), Decimal("5.40")),
                (Decimal("80650"), Decimal("96800"), Decimal("5.90")),
                (Decimal("96800"), Decimal("107650"), Decimal("7.03")),
                (Decimal("107650"), Decimal("157650"), Decimal("7.53")),
                (Decimal("157650"), Decimal("215400"), Decimal("6.40")),
                (Decimal("215400"), Decimal("265400"), Decimal("11.44")),
                (Decimal("265400"), Decimal("1077550"), Decimal("7.35")),
            ],
            "MFS": [
                (Decimal("0"), Decimal("8500"), Decimal("3.90")),
                (Decimal("8500"), Decimal("11700"), Decimal("4.40")),
                (Decimal("11700"), Decimal("13900"), Decimal("5.15")),
                (Decimal("13900"), Decimal("80650"), Decimal("5.40")),
                (Decimal("80650"), Decimal("96800"), Decimal("5.90")),
                (Decimal("96800"), Decimal("107650"), Decimal("7.03")),
                (Decimal("107650"), Decimal("157650"), Decimal("7.53")),
                (Decimal("157650"), Decimal("215400"), Decimal("6.40")),
                (Decimal("215400"), Decimal("265400"), Decimal("11.44")),
                (Decimal("265400"), Decimal("1077550"), Decimal("7.35")),
            ],
            "HOH": [
                (Decimal("0"), Decimal("8500"), Decimal("3.90")),
                (Decimal("8500"), Decimal("11700"), Decimal("4.40")),
                (Decimal("11700"), Decimal("13900"), Decimal("5.15")),
                (Decimal("13900"), Decimal("80650"), Decimal("5.40")),
                (Decimal("80650"), Decimal("96800"), Decimal("5.90")),
                (Decimal("96800"), Decimal("107650"), Decimal("7.03")),
                (Decimal("107650"), Decimal("157650"), Decimal("7.53")),
                (Decimal("157650"), Decimal("215400"), Decimal("6.40")),
                (Decimal("215400"), Decimal("265400"), Decimal("11.44")),
                (Decimal("265400"), Decimal("1077550"), Decimal("7.35")),
            ],
            "MFJ": [
                (Decimal("0"), Decimal("8500"), Decimal("3.90")),
                (Decimal("8500"), Decimal("11700"), Decimal("4.40")),
                (Decimal("11700"), Decimal("13900"), Decimal("5.15")),
                (Decimal("13900"), Decimal("80650"), Decimal("5.40")),
                (Decimal("80650"), Decimal("96800"), Decimal("5.90")),
                (Decimal("96800"), Decimal("107650"), Decimal("6.57")),
                (Decimal("107650"), Decimal("157650"), Decimal("7.07")),
                (Decimal("157650"), Decimal("211550"), Decimal("8.01")),
                (Decimal("211550"), Decimal("323200"), Decimal("6.40")),
                (Decimal("323200"), Decimal("373200"), Decimal("13.49")),
                (Decimal("373200"), Decimal("1077550"), Decimal("7.35")),
            ],
        },
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
    # Vermont Child Care Contribution (gap-closure Level 2, Batch 6,
    # 2026-09-13) — a real, distinct, employer-only payroll tax on the
    # SAME wage base as VT income tax withholding, effective since
    # 2024-07-01, fully literal (0.44%, no wage cap given in source).
    "VT": {
        "vt_ccc": dict(
            agency="Vermont Department of Taxes", source_title="VT GB-1210, 2026 Income Tax Withholding Instructions — Child Care Contribution",
            employee_rate_pct=None, employer_rate_pct=Decimal("0.44"), wage_cap=None, annual_max=None,
        ),
    },
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
    # - Massachusetts: added 2026-09-11 — the document's split (EE 0.44% /
    #   ER 0.44% at 25+) is complete, so it is no longer deferred (see the
    #   MA entry below).
    # - Minnesota: gives "large" vs "qualifying small employer" rate
    #   splits but NO numeric headcount threshold distinguishing them.
    # - Oregon: gives the large-employer split (60/40) but no numeric
    #   threshold defining "large", and no split at all for its
    #   small-employer exception.
    # MN/OR remain deferred — building them would require inventing a
    # number the source document doesn't give.
    "CO": {
        "famli": dict(
            agency="Colorado CDLE", source_title="FAMLI program",
            employee_rate_pct=Decimal("0.44"), employer_rate_pct=Decimal("0.44"),
            employer_headcount_min=10, employer_component_code="FAMLI",
            wage_cap=Decimal("184500.00"),
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
        # remitted regardless). wage_cap added 2026-09-13 (ZP-TAX-US-2026-001
        # §5 gap-closure audit) — the document's own $184,500 (SS) cap for
        # this program was never carried over when this entry was first
        # seeded, unlike every sibling capped program (CO/CT/MN above)
        # which already had one; without it this program was being applied
        # to uncapped annual gross, over-withholding any WA employee above
        # the cap on both the employee and employer side.
        "pfml": dict(
            agency="Employment Security Department (WA)", source_title="Washington programs — 2026 Paid Leave total premium",
            employee_rate_pct=Decimal("0.8069"), employer_rate_pct=Decimal("0.3228"),
            employer_headcount_min=50, employer_component_code="PFML",
            wage_cap=Decimal("184500.00"),
        ),
    },
    # Massachusetts PFML (ZP-TAX-US-2026-001 §5) — added 2026-09-11 with
    # the incremental flat-state build-out. The document gives a complete
    # split: total 0.88% (medical 0.61% + family 0.27% per the program's
    # own breakdown), employee 0.44% unconditional, employer 0.44% at 25+
    # covered individuals. The <25 case ("no employer share required") is
    # the absence-of-gate's normal behavior — the employer's own
    # covered_employee_count in EmployerTaxProfile is the gate. The
    # document lists no wage cap ("annual program wage limit" only), so no
    # wage_cap companion row is seeded.
    "MA": {
        "ma_pfml": dict(
            agency="Massachusetts DOR", source_title="Massachusetts PFML — 2026 contribution rates",
            employee_rate_pct=Decimal("0.44"), employer_rate_pct=Decimal("0.44"),
            employer_headcount_min=25, employer_component_code="MA_PFML",
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
    wage_cap=Decimal("184500.00"),
)

_CA_PROVINCIAL_BRACKETS = {
    # Canada provincial/territorial income tax brackets (ZP-TAX-CA-2026-001
    # §8) — consumed by scripts/populate_ca_provincial_v1.py, NOT
    # populate_canonical_tax_v1.py (same reason as the US state-level data:
    # that script only ever seeds the country-level, jurisdiction_state IS
    # NULL pack). One flat bracket set per jurisdiction: federal and these
    # 9 have IDENTICAL H1 and H2 figures per the document itself (§9's
    # mid-year override table lists ONLY BC/NL/PE — every other jurisdiction
    # here is confirmed to have no real split). BC/NL/PE's genuine H1-vs-H2
    # data lives in _CA_H1_H2_PROVINCES below instead, as two real packages
    # — an earlier pass here used a single-annual-figure simplification for
    # those three, based on a since-corrected belief that the pack
    # disambiguation mechanism couldn't tell H1 and H2 apart (it does: see
    # service.py's _resolve_pack_scoped_rows).
    # Each tuple: (min, max_or_None, rate_pct).
    "AB": [(0, 61200, "8"), (61200, 154259, "10"), (154259, 185111, "12"), (185111, 246813, "13"), (246813, 370220, "14"), (370220, None, "15")],
    "MB": [(0, 47000, "10.80"), (47000, 100000, "12.75"), (100000, None, "17.40")],
    "NB": [(0, 52333, "9.40"), (52333, 104666, "14"), (104666, 193861, "16"), (193861, None, "19.50")],
    "NS": [(0, 30995, "8.79"), (30995, 61991, "14.95"), (61991, 97417, "16.67"), (97417, 157124, "17.50"), (157124, None, "21")],
    "NT": [(0, 53003, "5.90"), (53003, 106009, "8.60"), (106009, 172346, "12.20"), (172346, None, "14.05")],
    "NU": [(0, 55801, "4"), (55801, 111602, "7"), (111602, 181439, "9"), (181439, None, "11.50")],
    "ON": [(0, 53891, "5.05"), (53891, 107785, "9.15"), (107785, 150000, "11.16"), (150000, 220000, "12.16"), (220000, None, "13.16")],
    "SK": [(0, 54532, "10.50"), (54532, 155805, "12.50"), (155805, None, "14.50")],
    "YT": [(0, 58523, "6.40"), (58523, 117045, "9"), (117045, 181440, "10.90"), (181440, 500000, "12.80"), (500000, None, "15")],
}

# Provincial Basic Personal Amount (§8's rightmost column), read via
# component_key="provincial_bpa" — every province EXCEPT Manitoba (dynamic
# formula, own parameter set below), Yukon (mirrors the federal BPAF
# exactly via canada.py's own YT branch, no separate row needed), and
# BC/NL (their own H1/H2-specific BPA lives in _CA_H1_H2_PROVINCES).
_CA_PROVINCIAL_BPA = {
    "AB": "22769", "NB": "13664", "NS": "11932",
    "NT": "18198", "NU": "19659", "ON": "12989", "SK": "20381",
}

# Manitoba's dynamic BPA (§8 "DYNAMIC BASIC AMOUNTS"): $15,780 if
# NI <= $200,000; linear taper to $0 at NI >= $400,000. Read via
# canada.py's mb_bpa_max/mb_bpa_ni_thresh_lo/mb_bpa_ni_thresh_hi.
_CA_MB_DYNAMIC_BPA = dict(max="15780", ni_thresh_lo="200000", ni_thresh_hi="400000")

# BC, Newfoundland & Labrador, and Prince Edward Island (§9's mid-year
# override table) — the ONLY 3 jurisdictions this document gives a real
# H1-vs-H2 difference for. Built as two genuine JurisdictionPacks each
# (effective 2026-01-01/06-30 and 2026-07-01/12-31), using Option 1's
# real per-half prorated figures (the document's own primary method, §7)
# rather than Option 2's single annual figure — that's the whole point of
# having two packages instead of one.
#
# BC: only the LOWEST bracket rate and the basic tax reduction amount
# change between halves — every other bracket (7.70/10.50/12.29/14.70/
# 16.80/20.50%) and the provincial BPA ($13,216) are identical both
# halves, so they're simply duplicated into both packages (required
# anyway: TaxSlab disambiguation groups by rule_type, not by which row
# changed, so a partial bracket set on one pack would silently lose the
# unchanged brackets for that half — see populate_ca_provincial_v1.py's
# own comment on this).
#
# NL: only the provincial_bpa changes; all 8 brackets are identical both
# halves and are duplicated into both packages for the same reason.
#
# PE: the new >$200,000 bracket does not exist in the H1 withholding
# asset at all (§9: "No separate >$200,000 bracket in H1") — H1 is a
# genuinely shorter, 5-bracket table ending at 17.62% with no ceiling;
# H2 has the full 6-bracket table with the new top bracket at its
# Option-1 prorated 21% (not the annual 20%).
_CA_H1_H2_PROVINCES = {
    "BC": dict(
        h1=dict(
            brackets=[(0, 50363, "5.06"), (50363, 100728, "7.70"), (100728, 115648, "10.50"), (115648, 140430, "12.29"), (140430, 190405, "14.70"), (190405, 265545, "16.80"), (265545, None, "20.50")],
            provincial_bpa="13216", bc_basic_tax_reduction="575",
        ),
        h2=dict(
            brackets=[(0, 50363, "6.14"), (50363, 100728, "7.70"), (100728, 115648, "10.50"), (115648, 140430, "12.29"), (140430, 190405, "14.70"), (190405, 265545, "16.80"), (265545, None, "20.50")],
            provincial_bpa="13216", bc_basic_tax_reduction="805",
        ),
    ),
    "NL": dict(
        h1=dict(
            brackets=[(0, 44678, "8.70"), (44678, 89354, "14.50"), (89354, 159528, "15.80"), (159528, 223340, "17.80"), (223340, 285319, "19.80"), (285319, 570638, "20.80"), (570638, 1141275, "21.30"), (1141275, None, "21.80")],
            provincial_bpa="11188",
        ),
        h2=dict(
            brackets=[(0, 44678, "8.70"), (44678, 89354, "14.50"), (89354, 159528, "15.80"), (159528, 223340, "17.80"), (223340, 285319, "19.80"), (285319, 570638, "20.80"), (570638, 1141275, "21.30"), (1141275, None, "21.80")],
            provincial_bpa="15000",
        ),
    ),
    "PE": dict(
        h1=dict(
            brackets=[(0, 33928, "9.50"), (33928, 65820, "13.47"), (65820, 106890, "16.60"), (106890, 142520, "17.62"), (142520, None, "19")],
            provincial_bpa="15000",
        ),
        h2=dict(
            brackets=[(0, 33928, "9.50"), (33928, 65820, "13.47"), (65820, 106890, "16.60"), (106890, 142520, "17.62"), (142520, 200000, "19"), (200000, None, "21")],
            provincial_bpa="15000",
        ),
    ),
}

# Ontario Employer Health Tax (§15/§16): $1,000,000 exemption + 9
# remuneration-band employer rates. Each tuple: (min, max_or_None, employer_rate_pct).
_CA_ON_EHT_EXEMPTION = "1000000"
_CA_ON_EHT_BANDS = [
    (0, 200000, "0.980"), (200000, 230000, "1.101"), (230000, 260000, "1.223"),
    (260000, 290000, "1.344"), (290000, 320000, "1.465"), (320000, 350000, "1.586"),
    (350000, 380000, "1.708"), (380000, 400000, "1.829"), (400000, None, "1.950"),
]

# BC/Manitoba/NL employer levies (§15) — the shared "exemption / notch /
# flat-on-total" shape canada.py's _annual_notch_levy_amount implements.
# NL HAPSET has no upper/flat tier (its own comment: "no second band") —
# only exemption_threshold/flat_rate are seeded for it, matching the key
# canada.py actually reads ("nl_hapset_flat_rate" — used as the notch
# rate; a naming quirk in the existing code, not mine to rename here).
_CA_EMPLOYER_LEVIES = {
    "bc_eht": dict(exemption_threshold="1000000", upper_threshold="1500000", notch_rate="5.85", flat_rate="1.95"),
    "bc_eht_charity": dict(exemption_threshold="1500000", upper_threshold="4500000", notch_rate="2.925", flat_rate="1.95"),
    "mb_he_levy": dict(exemption_threshold="2500000", upper_threshold="5000000", notch_rate="4.3", flat_rate="2.15"),
    "nl_hapset": dict(exemption_threshold="2000000", flat_rate="2.0"),
}

# Territorial employee payroll tax (§14): 2% each, employee-side only.
_CA_TERRITORIAL_PAYROLL_TAX = {"NT": "2.0", "NU": "2.0"}

# Quebec (§12/§13) — its own independent module per canada.py's
# _calculate_quebec_provincial_tax/_qc_hsf_rate_for_total/
# _calculate_qc_labour_standards. qc_labour_standards_RATE is deliberately
# NOT included: the document explicitly withholds it ("rate maintained as
# sourced statutory parameter") — only the $103,000 cap is given.
_CA_QUEBEC_BRACKETS = [(0, 54345, "14"), (54345, 108680, "19"), (108680, 132245, "24"), (132245, None, "25.75")]
_CA_QUEBEC_PARAMS = dict(
    quebec_bpa="18952", qc_worker_deduction="1450", qc_labour_standards_cap="103000",
    qpp=dict(employee="6.30", employer="6.30"),
    qpip=dict(employee="0.430", employer="0.602"), qpip_mie="103000",
    qc_hsf_threshold_low="1000000", qc_hsf_threshold_high="7800000",
    qc_hsf_general_low_rate="1.65", qc_hsf_general_high_rate="4.26",
    qc_hsf_general_mid_base="1.2662", qc_hsf_general_mid_slope="0.3838",
    qc_hsf_primary_low_rate="1.25", qc_hsf_primary_high_rate="4.26",
    qc_hsf_primary_mid_base="0.8074", qc_hsf_primary_mid_slope="0.4426",
    qc_hsf_public_rate="4.26",
)

# Connecticut withholding (gap-closure Level 2, fully resolved batch,
# primary source: CT DRS TPG-211, 2026 Withholding Calculation Rules,
# pages 2/4/5/6). Structurally unlike every other US state in this file —
# CT eliminated allowances entirely in favor of an employee-selected
# CT-W4 "Withholding Code" (A/B/C/D/F, models.PayrollEmployee.
# ct_withholding_code), and its own calculation is a genuinely different
# shape (exemption subtraction, THEN a base tax + two additive add-backs,
# THEN a multiplicative credit reduction) — not a plain marginal bracket
# sum, so it is NOT modeled via TaxSlab/_US_STATE_GRADUATED_TAX_RATES at
# all. Consumed by engine/countries/us.py's own dedicated
# _calculate_ct_annual_tax, gated by the SAME _US_STATE_TAX_ENABLED_STATES
# switch as every other state (a CT employee with no
# ct_withholding_code on file resolves to $0, same as an employee in any
# other unconfigured state).
#
# Every band below is read as (more-than-floor, less-than-or-equal-to-
# ceiling, value) per the source document's own column headers — a None
# ceiling means "and up" (the last, open-ended band). Table A (exemption)
# is transcribed as the literal step table given, NOT the "smooth linear"
# formula the source batch also suggested — that formula does not
# actually match its own literal table (it produces a continuously
# declining exemption within each $1,000 band, e.g. $11,999 at an
# annualized salary of $24,001, where the literal table requires a FLAT
# $11,000 for the entire $24,000-$25,000 band) — the literal table is
# authoritative here, consistent with this file's own "no estimation"
# discipline. Table D's own Table-B base-tax figures are used directly
# (floor/ceiling/rate/base) rather than re-derived via marginal-bracket
# summing from $0, since the literal base-tax figures are already given.
# Wisconsin withholding (gap-closure Level 2, Batch 6, 2026-09-13,
# primary source: WI DOR Publication W-166, 1/26). Genuinely NOT a plain
# marginal bracket sum on its own — WI's Alternate Method first computes
# a CONTINUOUS, income-dependent deduction (linearly phasing from a
# maximum down to $0 as earnings rise), unlike every other state's flat
# per-status deduction in this file. Unlike Connecticut's Table A (whose
# source ALSO suggested a formula but whose own literal table proved
# that formula wrong), this batch gives the formula directly and backs
# it with two full worked examples — both independently verified by hand
# against engine/countries/us.py's own _calculate_wi_annual_tax before
# enabling (see that function's docstring). Consumed by a dedicated
# function, not the generic TaxSlab bracket path, since the deduction
# step has no bracket-table representation at all.
#
# The $400/exemption reduction (step 3 of the source's own formula) is
# NOT applied — no per-employee WI exemption-count field exists; this is
# the one documented gap in an otherwise fully-modeled state. MFS/HOH
# (not named by the source, which only gives "Single"/"Married") use the
# Single-group deduction — the conservative default this whole build-out
# uses for any status a source doesn't name.
_US_WI_WITHHOLDING_PARAMS = dict(
    agency="Wisconsin Department of Revenue",
    source_title="WI DOR Publication W-166, Withholding Tax Guide (1/26), Alternate Method",
    single_deduction_max=Decimal("6702.00"), single_threshold=Decimal("17780.00"),
    single_zero_point=Decimal("73630.00"), single_slope=Decimal("0.12"),
    married_deduction_max=Decimal("9461.00"), married_threshold=Decimal("25727.00"),
    married_zero_point=Decimal("73032.00"), married_slope=Decimal("0.20"),
    brackets=[
        (Decimal("0"), Decimal("12760"), Decimal("3.54"), Decimal("0")),
        (Decimal("12760"), Decimal("25520"), Decimal("4.65"), Decimal("451.70")),
        (Decimal("25520"), Decimal("280950"), Decimal("5.30"), Decimal("1045.04")),
        (Decimal("280950"), None, Decimal("7.65"), Decimal("14582.83")),
    ],
)

_US_CT_WITHHOLDING_TABLES = {
    "A": dict(
        exemption=[
            (Decimal("0"), Decimal("24000"), Decimal("12000")), (Decimal("24000"), Decimal("25000"), Decimal("11000")),
            (Decimal("25000"), Decimal("26000"), Decimal("10000")), (Decimal("26000"), Decimal("27000"), Decimal("9000")),
            (Decimal("27000"), Decimal("28000"), Decimal("8000")), (Decimal("28000"), Decimal("29000"), Decimal("7000")),
            (Decimal("29000"), Decimal("30000"), Decimal("6000")), (Decimal("30000"), Decimal("31000"), Decimal("5000")),
            (Decimal("31000"), Decimal("32000"), Decimal("4000")), (Decimal("32000"), Decimal("33000"), Decimal("3000")),
            (Decimal("33000"), Decimal("34000"), Decimal("2000")), (Decimal("34000"), Decimal("35000"), Decimal("1000")),
            (Decimal("35000"), None, Decimal("0")),
        ],
        table_b=[
            (Decimal("0"), Decimal("10000"), Decimal("2.00"), Decimal("0")),
            (Decimal("10000"), Decimal("50000"), Decimal("4.50"), Decimal("200")),
            (Decimal("50000"), Decimal("100000"), Decimal("5.50"), Decimal("2000")),
            (Decimal("100000"), Decimal("200000"), Decimal("6.00"), Decimal("4750")),
            (Decimal("200000"), Decimal("250000"), Decimal("6.50"), Decimal("10750")),
            (Decimal("250000"), Decimal("500000"), Decimal("6.90"), Decimal("14000")),
            (Decimal("500000"), None, Decimal("6.99"), Decimal("31250")),
        ],
        table_c=[
            (Decimal("0"), Decimal("50250"), Decimal("0")), (Decimal("50250"), Decimal("52750"), Decimal("25")),
            (Decimal("52750"), Decimal("55250"), Decimal("50")), (Decimal("55250"), Decimal("57750"), Decimal("75")),
            (Decimal("57750"), Decimal("60250"), Decimal("100")), (Decimal("60250"), Decimal("62750"), Decimal("125")),
            (Decimal("62750"), Decimal("65250"), Decimal("150")), (Decimal("65250"), Decimal("67750"), Decimal("175")),
            (Decimal("67750"), Decimal("70250"), Decimal("200")), (Decimal("70250"), Decimal("72750"), Decimal("225")),
            (Decimal("72750"), None, Decimal("250")),
        ],
        table_d=[
            (Decimal("0"), Decimal("105000"), Decimal("0")), (Decimal("105000"), Decimal("110000"), Decimal("25")),
            (Decimal("110000"), Decimal("115000"), Decimal("50")), (Decimal("115000"), Decimal("120000"), Decimal("75")),
            (Decimal("120000"), Decimal("125000"), Decimal("100")), (Decimal("125000"), Decimal("130000"), Decimal("125")),
            (Decimal("130000"), Decimal("135000"), Decimal("150")), (Decimal("135000"), Decimal("140000"), Decimal("175")),
            (Decimal("140000"), Decimal("145000"), Decimal("200")), (Decimal("145000"), Decimal("150000"), Decimal("225")),
            (Decimal("150000"), Decimal("200000"), Decimal("250")), (Decimal("200000"), Decimal("205000"), Decimal("340")),
            (Decimal("205000"), Decimal("210000"), Decimal("430")), (Decimal("210000"), Decimal("215000"), Decimal("520")),
            (Decimal("215000"), Decimal("220000"), Decimal("610")), (Decimal("220000"), Decimal("225000"), Decimal("700")),
            (Decimal("225000"), Decimal("230000"), Decimal("790")), (Decimal("230000"), Decimal("235000"), Decimal("880")),
            (Decimal("235000"), Decimal("240000"), Decimal("970")), (Decimal("240000"), Decimal("245000"), Decimal("1060")),
            (Decimal("245000"), Decimal("250000"), Decimal("1150")), (Decimal("250000"), Decimal("255000"), Decimal("1240")),
            (Decimal("255000"), Decimal("260000"), Decimal("1330")), (Decimal("260000"), Decimal("265000"), Decimal("1420")),
            (Decimal("265000"), Decimal("270000"), Decimal("1510")), (Decimal("270000"), Decimal("275000"), Decimal("1600")),
            (Decimal("275000"), Decimal("280000"), Decimal("1690")), (Decimal("280000"), Decimal("285000"), Decimal("1780")),
            (Decimal("285000"), Decimal("290000"), Decimal("1870")), (Decimal("290000"), Decimal("295000"), Decimal("1960")),
            (Decimal("295000"), Decimal("300000"), Decimal("2050")), (Decimal("300000"), Decimal("305000"), Decimal("2140")),
            (Decimal("305000"), Decimal("310000"), Decimal("2230")), (Decimal("310000"), Decimal("315000"), Decimal("2320")),
            (Decimal("315000"), Decimal("320000"), Decimal("2410")), (Decimal("320000"), Decimal("325000"), Decimal("2500")),
            (Decimal("325000"), Decimal("330000"), Decimal("2590")), (Decimal("330000"), Decimal("335000"), Decimal("2680")),
            (Decimal("335000"), Decimal("340000"), Decimal("2770")), (Decimal("340000"), Decimal("345000"), Decimal("2860")),
            (Decimal("345000"), Decimal("500000"), Decimal("2950")), (Decimal("500000"), Decimal("505000"), Decimal("3000")),
            (Decimal("505000"), Decimal("510000"), Decimal("3050")), (Decimal("510000"), Decimal("515000"), Decimal("3100")),
            (Decimal("515000"), Decimal("520000"), Decimal("3150")), (Decimal("520000"), Decimal("525000"), Decimal("3200")),
            (Decimal("525000"), Decimal("530000"), Decimal("3250")), (Decimal("530000"), Decimal("535000"), Decimal("3300")),
            (Decimal("535000"), Decimal("540000"), Decimal("3350")), (Decimal("540000"), None, Decimal("3400")),
        ],
        table_e=[
            (Decimal("12000"), Decimal("15000"), Decimal("0.75")), (Decimal("15000"), Decimal("15500"), Decimal("0.70")),
            (Decimal("15500"), Decimal("16000"), Decimal("0.65")), (Decimal("16000"), Decimal("16500"), Decimal("0.60")),
            (Decimal("16500"), Decimal("17000"), Decimal("0.55")), (Decimal("17000"), Decimal("17500"), Decimal("0.50")),
            (Decimal("17500"), Decimal("18000"), Decimal("0.45")), (Decimal("18000"), Decimal("18500"), Decimal("0.40")),
            (Decimal("18500"), Decimal("20000"), Decimal("0.35")), (Decimal("20000"), Decimal("20500"), Decimal("0.30")),
            (Decimal("20500"), Decimal("21000"), Decimal("0.25")), (Decimal("21000"), Decimal("21500"), Decimal("0.20")),
            (Decimal("21500"), Decimal("25000"), Decimal("0.15")), (Decimal("25000"), Decimal("25500"), Decimal("0.14")),
            (Decimal("25500"), Decimal("26000"), Decimal("0.13")), (Decimal("26000"), Decimal("26500"), Decimal("0.12")),
            (Decimal("26500"), Decimal("27000"), Decimal("0.11")), (Decimal("27000"), Decimal("48000"), Decimal("0.10")),
            (Decimal("48000"), Decimal("48500"), Decimal("0.09")), (Decimal("48500"), Decimal("49000"), Decimal("0.08")),
            (Decimal("49000"), Decimal("49500"), Decimal("0.07")), (Decimal("49500"), Decimal("50000"), Decimal("0.06")),
            (Decimal("50000"), Decimal("50500"), Decimal("0.05")), (Decimal("50500"), Decimal("51000"), Decimal("0.04")),
            (Decimal("51000"), Decimal("51500"), Decimal("0.03")), (Decimal("51500"), Decimal("52000"), Decimal("0.02")),
            (Decimal("52000"), Decimal("52500"), Decimal("0.01")), (Decimal("52500"), None, Decimal("0.00")),
        ],
    ),
    "B": dict(
        exemption=[
            (Decimal("0"), Decimal("38000"), Decimal("19000")), (Decimal("38000"), Decimal("39000"), Decimal("18000")),
            (Decimal("39000"), Decimal("40000"), Decimal("17000")), (Decimal("40000"), Decimal("41000"), Decimal("16000")),
            (Decimal("41000"), Decimal("42000"), Decimal("15000")), (Decimal("42000"), Decimal("43000"), Decimal("14000")),
            (Decimal("43000"), Decimal("44000"), Decimal("13000")), (Decimal("44000"), Decimal("45000"), Decimal("12000")),
            (Decimal("45000"), Decimal("46000"), Decimal("11000")), (Decimal("46000"), Decimal("47000"), Decimal("10000")),
            (Decimal("47000"), Decimal("48000"), Decimal("9000")), (Decimal("48000"), Decimal("49000"), Decimal("8000")),
            (Decimal("49000"), Decimal("50000"), Decimal("7000")), (Decimal("50000"), Decimal("51000"), Decimal("6000")),
            (Decimal("51000"), Decimal("52000"), Decimal("5000")), (Decimal("52000"), Decimal("53000"), Decimal("4000")),
            (Decimal("53000"), Decimal("54000"), Decimal("3000")), (Decimal("54000"), Decimal("55000"), Decimal("2000")),
            (Decimal("55000"), Decimal("56000"), Decimal("1000")), (Decimal("56000"), None, Decimal("0")),
        ],
        table_b=[
            (Decimal("0"), Decimal("16000"), Decimal("2.00"), Decimal("0")),
            (Decimal("16000"), Decimal("80000"), Decimal("4.50"), Decimal("320")),
            (Decimal("80000"), Decimal("160000"), Decimal("5.50"), Decimal("3200")),
            (Decimal("160000"), Decimal("320000"), Decimal("6.00"), Decimal("7600")),
            (Decimal("320000"), Decimal("400000"), Decimal("6.50"), Decimal("17200")),
            (Decimal("400000"), Decimal("800000"), Decimal("6.90"), Decimal("22400")),
            (Decimal("800000"), None, Decimal("6.99"), Decimal("50000")),
        ],
        table_c=[
            (Decimal("0"), Decimal("78500"), Decimal("0")), (Decimal("78500"), Decimal("82500"), Decimal("40")),
            (Decimal("82500"), Decimal("86500"), Decimal("80")), (Decimal("86500"), Decimal("90500"), Decimal("120")),
            (Decimal("90500"), Decimal("94500"), Decimal("160")), (Decimal("94500"), Decimal("98500"), Decimal("200")),
            (Decimal("98500"), Decimal("102500"), Decimal("240")), (Decimal("102500"), Decimal("106500"), Decimal("280")),
            (Decimal("106500"), Decimal("110500"), Decimal("320")), (Decimal("110500"), Decimal("114500"), Decimal("360")),
            (Decimal("114500"), None, Decimal("400")),
        ],
        table_d=[
            (Decimal("0"), Decimal("168000"), Decimal("0")), (Decimal("168000"), Decimal("176000"), Decimal("40")),
            (Decimal("176000"), Decimal("184000"), Decimal("80")), (Decimal("184000"), Decimal("192000"), Decimal("120")),
            (Decimal("192000"), Decimal("200000"), Decimal("160")), (Decimal("200000"), Decimal("208000"), Decimal("200")),
            (Decimal("208000"), Decimal("216000"), Decimal("240")), (Decimal("216000"), Decimal("224000"), Decimal("280")),
            (Decimal("224000"), Decimal("232000"), Decimal("320")), (Decimal("232000"), Decimal("240000"), Decimal("360")),
            (Decimal("240000"), Decimal("320000"), Decimal("400")), (Decimal("320000"), Decimal("328000"), Decimal("540")),
            (Decimal("328000"), Decimal("336000"), Decimal("680")), (Decimal("336000"), Decimal("344000"), Decimal("820")),
            (Decimal("344000"), Decimal("352000"), Decimal("960")), (Decimal("352000"), Decimal("360000"), Decimal("1100")),
            (Decimal("360000"), Decimal("368000"), Decimal("1240")), (Decimal("368000"), Decimal("376000"), Decimal("1380")),
            (Decimal("376000"), Decimal("384000"), Decimal("1520")), (Decimal("384000"), Decimal("392000"), Decimal("1660")),
            (Decimal("392000"), Decimal("400000"), Decimal("1800")), (Decimal("400000"), Decimal("408000"), Decimal("1940")),
            (Decimal("408000"), Decimal("416000"), Decimal("2080")), (Decimal("416000"), Decimal("424000"), Decimal("2220")),
            (Decimal("424000"), Decimal("432000"), Decimal("2360")), (Decimal("432000"), Decimal("440000"), Decimal("2500")),
            (Decimal("440000"), Decimal("448000"), Decimal("2640")), (Decimal("448000"), Decimal("456000"), Decimal("2780")),
            (Decimal("456000"), Decimal("464000"), Decimal("2920")), (Decimal("464000"), Decimal("472000"), Decimal("3060")),
            (Decimal("472000"), Decimal("480000"), Decimal("3200")), (Decimal("480000"), Decimal("488000"), Decimal("3340")),
            (Decimal("488000"), Decimal("496000"), Decimal("3480")), (Decimal("496000"), Decimal("504000"), Decimal("3620")),
            (Decimal("504000"), Decimal("512000"), Decimal("3760")), (Decimal("512000"), Decimal("520000"), Decimal("3900")),
            (Decimal("520000"), Decimal("528000"), Decimal("4040")), (Decimal("528000"), Decimal("536000"), Decimal("4180")),
            (Decimal("536000"), Decimal("544000"), Decimal("4320")), (Decimal("544000"), Decimal("552000"), Decimal("4460")),
            (Decimal("552000"), Decimal("800000"), Decimal("4600")), (Decimal("800000"), Decimal("808000"), Decimal("4680")),
            (Decimal("808000"), Decimal("816000"), Decimal("4760")), (Decimal("816000"), Decimal("824000"), Decimal("4840")),
            (Decimal("824000"), Decimal("832000"), Decimal("4920")), (Decimal("832000"), Decimal("840000"), Decimal("5000")),
            (Decimal("840000"), Decimal("848000"), Decimal("5080")), (Decimal("848000"), Decimal("856000"), Decimal("5160")),
            (Decimal("856000"), Decimal("864000"), Decimal("5240")), (Decimal("864000"), None, Decimal("5320")),
        ],
        table_e=[
            (Decimal("19000"), Decimal("24000"), Decimal("0.75")), (Decimal("24000"), Decimal("24500"), Decimal("0.70")),
            (Decimal("24500"), Decimal("25000"), Decimal("0.65")), (Decimal("25000"), Decimal("25500"), Decimal("0.60")),
            (Decimal("25500"), Decimal("26000"), Decimal("0.55")), (Decimal("26000"), Decimal("26500"), Decimal("0.50")),
            (Decimal("26500"), Decimal("27000"), Decimal("0.45")), (Decimal("27000"), Decimal("27500"), Decimal("0.40")),
            (Decimal("27500"), Decimal("34000"), Decimal("0.35")), (Decimal("34000"), Decimal("34500"), Decimal("0.30")),
            (Decimal("34500"), Decimal("35000"), Decimal("0.25")), (Decimal("35000"), Decimal("35500"), Decimal("0.20")),
            (Decimal("35500"), Decimal("44000"), Decimal("0.15")), (Decimal("44000"), Decimal("44500"), Decimal("0.14")),
            (Decimal("44500"), Decimal("45000"), Decimal("0.13")), (Decimal("45000"), Decimal("45500"), Decimal("0.12")),
            (Decimal("45500"), Decimal("46000"), Decimal("0.11")), (Decimal("46000"), Decimal("74000"), Decimal("0.10")),
            (Decimal("74000"), Decimal("74500"), Decimal("0.09")), (Decimal("74500"), Decimal("75000"), Decimal("0.08")),
            (Decimal("75000"), Decimal("75500"), Decimal("0.07")), (Decimal("75500"), Decimal("76000"), Decimal("0.06")),
            (Decimal("76000"), Decimal("76500"), Decimal("0.05")), (Decimal("76500"), Decimal("77000"), Decimal("0.04")),
            (Decimal("77000"), Decimal("77500"), Decimal("0.03")), (Decimal("77500"), Decimal("78000"), Decimal("0.02")),
            (Decimal("78000"), Decimal("78500"), Decimal("0.01")), (Decimal("78500"), None, Decimal("0.00")),
        ],
    ),
    "C": dict(
        exemption=[
            (Decimal("0"), Decimal("48000"), Decimal("24000")), (Decimal("48000"), Decimal("49000"), Decimal("23000")),
            (Decimal("49000"), Decimal("50000"), Decimal("22000")), (Decimal("50000"), Decimal("51000"), Decimal("21000")),
            (Decimal("51000"), Decimal("52000"), Decimal("20000")), (Decimal("52000"), Decimal("53000"), Decimal("19000")),
            (Decimal("53000"), Decimal("54000"), Decimal("18000")), (Decimal("54000"), Decimal("55000"), Decimal("17000")),
            (Decimal("55000"), Decimal("56000"), Decimal("16000")), (Decimal("56000"), Decimal("57000"), Decimal("15000")),
            (Decimal("57000"), Decimal("58000"), Decimal("14000")), (Decimal("58000"), Decimal("59000"), Decimal("13000")),
            (Decimal("59000"), Decimal("60000"), Decimal("12000")), (Decimal("60000"), Decimal("61000"), Decimal("11000")),
            (Decimal("61000"), Decimal("62000"), Decimal("10000")), (Decimal("62000"), Decimal("63000"), Decimal("9000")),
            (Decimal("63000"), Decimal("64000"), Decimal("8000")), (Decimal("64000"), Decimal("65000"), Decimal("7000")),
            (Decimal("65000"), Decimal("66000"), Decimal("6000")), (Decimal("66000"), Decimal("67000"), Decimal("5000")),
            (Decimal("67000"), Decimal("68000"), Decimal("4000")), (Decimal("68000"), Decimal("69000"), Decimal("3000")),
            (Decimal("69000"), Decimal("70000"), Decimal("2000")), (Decimal("70000"), Decimal("71000"), Decimal("1000")),
            (Decimal("71000"), None, Decimal("0")),
        ],
        table_b=[
            (Decimal("0"), Decimal("20000"), Decimal("2.00"), Decimal("0")),
            (Decimal("20000"), Decimal("100000"), Decimal("4.50"), Decimal("400")),
            (Decimal("100000"), Decimal("200000"), Decimal("5.50"), Decimal("4000")),
            (Decimal("200000"), Decimal("400000"), Decimal("6.00"), Decimal("9500")),
            (Decimal("400000"), Decimal("500000"), Decimal("6.50"), Decimal("21500")),
            (Decimal("500000"), Decimal("1000000"), Decimal("6.90"), Decimal("28000")),
            (Decimal("1000000"), None, Decimal("6.99"), Decimal("62500")),
        ],
        table_c=[
            (Decimal("0"), Decimal("100500"), Decimal("0")), (Decimal("100500"), Decimal("105500"), Decimal("50")),
            (Decimal("105500"), Decimal("110500"), Decimal("100")), (Decimal("110500"), Decimal("115500"), Decimal("150")),
            (Decimal("115500"), Decimal("120500"), Decimal("200")), (Decimal("120500"), Decimal("125500"), Decimal("250")),
            (Decimal("125500"), Decimal("130500"), Decimal("300")), (Decimal("130500"), Decimal("135500"), Decimal("350")),
            (Decimal("135500"), Decimal("140500"), Decimal("400")), (Decimal("140500"), Decimal("145500"), Decimal("450")),
            (Decimal("145500"), None, Decimal("500")),
        ],
        table_d=[
            (Decimal("0"), Decimal("210000"), Decimal("0")), (Decimal("210000"), Decimal("220000"), Decimal("50")),
            (Decimal("220000"), Decimal("230000"), Decimal("100")), (Decimal("230000"), Decimal("240000"), Decimal("150")),
            (Decimal("240000"), Decimal("250000"), Decimal("200")), (Decimal("250000"), Decimal("260000"), Decimal("250")),
            (Decimal("260000"), Decimal("270000"), Decimal("300")), (Decimal("270000"), Decimal("280000"), Decimal("350")),
            (Decimal("280000"), Decimal("290000"), Decimal("400")), (Decimal("290000"), Decimal("300000"), Decimal("450")),
            (Decimal("300000"), Decimal("400000"), Decimal("500")), (Decimal("400000"), Decimal("410000"), Decimal("680")),
            (Decimal("410000"), Decimal("420000"), Decimal("860")), (Decimal("420000"), Decimal("430000"), Decimal("1040")),
            (Decimal("430000"), Decimal("440000"), Decimal("1220")), (Decimal("440000"), Decimal("450000"), Decimal("1400")),
            (Decimal("450000"), Decimal("460000"), Decimal("1580")), (Decimal("460000"), Decimal("470000"), Decimal("1760")),
            (Decimal("470000"), Decimal("480000"), Decimal("1940")), (Decimal("480000"), Decimal("490000"), Decimal("2120")),
            (Decimal("490000"), Decimal("500000"), Decimal("2300")), (Decimal("500000"), Decimal("510000"), Decimal("2480")),
            (Decimal("510000"), Decimal("520000"), Decimal("2660")), (Decimal("520000"), Decimal("530000"), Decimal("2840")),
            (Decimal("530000"), Decimal("540000"), Decimal("3020")), (Decimal("540000"), Decimal("550000"), Decimal("3200")),
            (Decimal("550000"), Decimal("560000"), Decimal("3380")), (Decimal("560000"), Decimal("570000"), Decimal("3560")),
            (Decimal("570000"), Decimal("580000"), Decimal("3740")), (Decimal("580000"), Decimal("590000"), Decimal("3920")),
            (Decimal("590000"), Decimal("600000"), Decimal("4100")), (Decimal("600000"), Decimal("610000"), Decimal("4280")),
            (Decimal("610000"), Decimal("620000"), Decimal("4460")), (Decimal("620000"), Decimal("630000"), Decimal("4640")),
            (Decimal("630000"), Decimal("640000"), Decimal("4820")), (Decimal("640000"), Decimal("650000"), Decimal("5000")),
            (Decimal("650000"), Decimal("660000"), Decimal("5180")), (Decimal("660000"), Decimal("670000"), Decimal("5360")),
            (Decimal("670000"), Decimal("680000"), Decimal("5540")), (Decimal("680000"), Decimal("690000"), Decimal("5720")),
            (Decimal("690000"), Decimal("1000000"), Decimal("5900")), (Decimal("1000000"), Decimal("1010000"), Decimal("6000")),
            (Decimal("1010000"), Decimal("1020000"), Decimal("6100")), (Decimal("1020000"), Decimal("1030000"), Decimal("6200")),
            (Decimal("1030000"), Decimal("1040000"), Decimal("6300")), (Decimal("1040000"), Decimal("1050000"), Decimal("6400")),
            (Decimal("1050000"), Decimal("1060000"), Decimal("6500")), (Decimal("1060000"), Decimal("1070000"), Decimal("6600")),
            (Decimal("1070000"), Decimal("1080000"), Decimal("6700")), (Decimal("1080000"), None, Decimal("6800")),
        ],
        table_e=[
            (Decimal("24000"), Decimal("30000"), Decimal("0.75")), (Decimal("30000"), Decimal("30500"), Decimal("0.70")),
            (Decimal("30500"), Decimal("31000"), Decimal("0.65")), (Decimal("31000"), Decimal("31500"), Decimal("0.60")),
            (Decimal("31500"), Decimal("32000"), Decimal("0.55")), (Decimal("32000"), Decimal("32500"), Decimal("0.50")),
            (Decimal("32500"), Decimal("33000"), Decimal("0.45")), (Decimal("33000"), Decimal("33500"), Decimal("0.40")),
            (Decimal("33500"), Decimal("40000"), Decimal("0.35")), (Decimal("40000"), Decimal("40500"), Decimal("0.30")),
            (Decimal("40500"), Decimal("41000"), Decimal("0.25")), (Decimal("41000"), Decimal("41500"), Decimal("0.20")),
            (Decimal("41500"), Decimal("50000"), Decimal("0.15")), (Decimal("50000"), Decimal("50500"), Decimal("0.14")),
            (Decimal("50500"), Decimal("51000"), Decimal("0.13")), (Decimal("51000"), Decimal("51500"), Decimal("0.12")),
            (Decimal("51500"), Decimal("52000"), Decimal("0.11")), (Decimal("52000"), Decimal("96000"), Decimal("0.10")),
            (Decimal("96000"), Decimal("96500"), Decimal("0.09")), (Decimal("96500"), Decimal("97000"), Decimal("0.08")),
            (Decimal("97000"), Decimal("97500"), Decimal("0.07")), (Decimal("97500"), Decimal("98000"), Decimal("0.06")),
            (Decimal("98000"), Decimal("98500"), Decimal("0.05")), (Decimal("98500"), Decimal("99000"), Decimal("0.04")),
            (Decimal("99000"), Decimal("99500"), Decimal("0.03")), (Decimal("99500"), Decimal("100000"), Decimal("0.02")),
            (Decimal("100000"), Decimal("100500"), Decimal("0.01")), (Decimal("100500"), None, Decimal("0.00")),
        ],
    ),
    "F": dict(
        exemption=[
            (Decimal("0"), Decimal("30000"), Decimal("15000")), (Decimal("30000"), Decimal("31000"), Decimal("14000")),
            (Decimal("31000"), Decimal("32000"), Decimal("13000")), (Decimal("32000"), Decimal("33000"), Decimal("12000")),
            (Decimal("33000"), Decimal("34000"), Decimal("11000")), (Decimal("34000"), Decimal("35000"), Decimal("10000")),
            (Decimal("35000"), Decimal("36000"), Decimal("9000")), (Decimal("36000"), Decimal("37000"), Decimal("8000")),
            (Decimal("37000"), Decimal("38000"), Decimal("7000")), (Decimal("38000"), Decimal("39000"), Decimal("6000")),
            (Decimal("39000"), Decimal("40000"), Decimal("5000")), (Decimal("40000"), Decimal("41000"), Decimal("4000")),
            (Decimal("41000"), Decimal("42000"), Decimal("3000")), (Decimal("42000"), Decimal("43000"), Decimal("2000")),
            (Decimal("43000"), Decimal("44000"), Decimal("1000")), (Decimal("44000"), None, Decimal("0")),
        ],
        table_b=[
            (Decimal("0"), Decimal("10000"), Decimal("2.00"), Decimal("0")),
            (Decimal("10000"), Decimal("50000"), Decimal("4.50"), Decimal("200")),
            (Decimal("50000"), Decimal("100000"), Decimal("5.50"), Decimal("2000")),
            (Decimal("100000"), Decimal("200000"), Decimal("6.00"), Decimal("4750")),
            (Decimal("200000"), Decimal("250000"), Decimal("6.50"), Decimal("10750")),
            (Decimal("250000"), Decimal("500000"), Decimal("6.90"), Decimal("14000")),
            (Decimal("500000"), None, Decimal("6.99"), Decimal("31250")),
        ],
        table_c=[
            (Decimal("0"), Decimal("56500"), Decimal("0")), (Decimal("56500"), Decimal("61500"), Decimal("25")),
            (Decimal("61500"), Decimal("66500"), Decimal("50")), (Decimal("66500"), Decimal("71500"), Decimal("75")),
            (Decimal("71500"), Decimal("76500"), Decimal("100")), (Decimal("76500"), Decimal("81500"), Decimal("125")),
            (Decimal("81500"), Decimal("86500"), Decimal("150")), (Decimal("86500"), Decimal("91500"), Decimal("175")),
            (Decimal("91500"), Decimal("96500"), Decimal("200")), (Decimal("96500"), Decimal("101500"), Decimal("225")),
            (Decimal("101500"), None, Decimal("250")),
        ],
        # Table D for Code F is the SAME table as Code A/D (per the
        # source's own "Withholding Code A, D, or F" header) — reused
        # here rather than duplicated verbatim.
        table_d="SAME_AS_A",
        table_e=[
            (Decimal("15000"), Decimal("18800"), Decimal("0.75")), (Decimal("18800"), Decimal("19300"), Decimal("0.70")),
            (Decimal("19300"), Decimal("19800"), Decimal("0.65")), (Decimal("19800"), Decimal("20300"), Decimal("0.60")),
            (Decimal("20300"), Decimal("20800"), Decimal("0.55")), (Decimal("20800"), Decimal("21300"), Decimal("0.50")),
            (Decimal("21300"), Decimal("21800"), Decimal("0.45")), (Decimal("21800"), Decimal("22300"), Decimal("0.40")),
            (Decimal("22300"), Decimal("25000"), Decimal("0.35")), (Decimal("25000"), Decimal("25500"), Decimal("0.30")),
            (Decimal("25500"), Decimal("26000"), Decimal("0.25")), (Decimal("26000"), Decimal("26500"), Decimal("0.20")),
            (Decimal("26500"), Decimal("31300"), Decimal("0.15")), (Decimal("31300"), Decimal("31800"), Decimal("0.14")),
            (Decimal("31800"), Decimal("32300"), Decimal("0.13")), (Decimal("32300"), Decimal("32800"), Decimal("0.12")),
            (Decimal("32800"), Decimal("33300"), Decimal("0.11")), (Decimal("33300"), Decimal("60000"), Decimal("0.10")),
            (Decimal("60000"), Decimal("60500"), Decimal("0.09")), (Decimal("60500"), Decimal("61000"), Decimal("0.08")),
            (Decimal("61000"), Decimal("61500"), Decimal("0.07")), (Decimal("61500"), Decimal("62000"), Decimal("0.06")),
            (Decimal("62000"), Decimal("62500"), Decimal("0.05")), (Decimal("62500"), Decimal("63000"), Decimal("0.04")),
            (Decimal("63000"), Decimal("63500"), Decimal("0.03")), (Decimal("63500"), Decimal("64000"), Decimal("0.02")),
            (Decimal("64000"), Decimal("64500"), Decimal("0.01")), (Decimal("64500"), None, Decimal("0.00")),
        ],
    ),
    "D": dict(
        exemption=[(Decimal("0"), None, Decimal("0"))],
        table_b=[
            (Decimal("0"), Decimal("10000"), Decimal("2.00"), Decimal("0")),
            (Decimal("10000"), Decimal("50000"), Decimal("4.50"), Decimal("200")),
            (Decimal("50000"), Decimal("100000"), Decimal("5.50"), Decimal("2000")),
            (Decimal("100000"), Decimal("200000"), Decimal("6.00"), Decimal("4750")),
            (Decimal("200000"), Decimal("250000"), Decimal("6.50"), Decimal("10750")),
            (Decimal("250000"), Decimal("500000"), Decimal("6.90"), Decimal("14000")),
            (Decimal("500000"), None, Decimal("6.99"), Decimal("31250")),
        ],
        # Table C isn't separately given for Code D — the source states
        # Code D's Personal Exemption AND Personal Tax Credit are both
        # fixed at $0/0.00, and Code D shares Table B/D with Code A per
        # the source's own "A, D, or F" headers. Table C's own header
        # only lists "A or D" for the SAME table as Code A, so reused here.
        table_c="SAME_AS_A",
        table_d="SAME_AS_A",
        table_e=[(Decimal("0"), None, Decimal("0.00"))],
    ),
}

# ── Oregon: computer formula method (Production-Readiness Plan Phase 4,
# 2026-09-15) ─────────────────────────────────────────────────────────
# Oregon DOR Pub. 150-206-436, "Oregon Withholding Tax Formulas, Effective
# January 1, 2026" — independently fetched and extracted (pypdf, all 8
# pages) directly from oregon.gov, not transcribed from a secondary
# source. Every figure below was cross-checked against the PDF's own
# literal formula tables (pages 6-7), not its narrative text or worked
# examples, because the source document itself contains THREE internal
# inconsistencies the formula tables resolve authoritatively:
#   - The federal-tax-subtraction cap is stated as "$8,500... in 2025" in
#     the narrative (page 5) and FAQ Q3, but the actual formula box and
#     phase-out table (pages 6-7) and FAQ Q11 both use $8,750 for 2026 —
#     used here, since it's what the computational formula runs on.
#   - The page 5 worked example states "the base is $21,165" in its
#     prose, then computes with BASE=$21,090 in every subsequent step —
#     $21,090 is arithmetically correct ($25,000-$1,000-$2,910); not
#     propagated.
#   - Step 9 of that same example computes "$256 × allowances" but the
#     formula tables (pages 6-7) and FAQ both give $263/allowance —
#     $263 used here, matching the operative formula.
# Oregon is NOT a marginal-bracket state in the TaxSlab sense — BASE
# (wages minus a capped/phased-out federal-withholding subtraction minus
# a flat standard deduction) feeds a 4-band table that differs by BOTH
# filing status AND whether annual wages are under/over $50,000, with the
# personal exemption credit subtracted AFTER the bracket lookup, not
# folded into the deduction. Allowances are NOT modeled — no Oregon-
# specific allowance field exists (Form OR-W-4 allowances are a genuinely
# separate concept from federal W-4 allowances per the source's own
# "Oregon Employer Update" section) — same documented limitation
# _US_WI_WITHHOLDING_PARAMS already has for its own per-exemption count.
# Every OR employee is therefore treated as 0 allowances: always uses the
# "fewer than 3 allowances" bracket set (correct, since 0 < 3), never
# gets the $263/allowance credit, and the allowance-zeroing rule at
# $100k/$200k is a no-op (there are never any allowances to zero).
_US_OR_WITHHOLDING_PARAMS = dict(
    agency="Oregon Department of Revenue",
    source_title="Oregon Withholding Tax Formulas, Pub. 150-206-436 (Rev. 12-31-25), effective 1/1/2026",
    single_standard_deduction=Decimal("2910.00"),
    married_standard_deduction=Decimal("5820.00"),
    exemption_credit_per_allowance=Decimal("263.00"),
    fed_subtraction_cap_default=Decimal("8750.00"),
    # (floor inclusive, ceiling exclusive or None, capped subtraction) —
    # identical structure for wages under $50,000 (flat $8,750 cap, no
    # phase-out row needed since the under-$50k formula itself already
    # says "not to exceed $8,750").
    single_fed_subtraction_phaseout=[
        (Decimal("0"), Decimal("125000"), Decimal("8750.00")),
        (Decimal("125000"), Decimal("130000"), Decimal("7000.00")),
        (Decimal("130000"), Decimal("135000"), Decimal("5250.00")),
        (Decimal("135000"), Decimal("140000"), Decimal("3500.00")),
        (Decimal("140000"), Decimal("145000"), Decimal("1750.00")),
        (Decimal("145000"), None, Decimal("0.00")),
    ],
    married_fed_subtraction_phaseout=[
        (Decimal("0"), Decimal("250000"), Decimal("8750.00")),
        (Decimal("250000"), Decimal("260000"), Decimal("7000.00")),
        (Decimal("260000"), Decimal("270000"), Decimal("5250.00")),
        (Decimal("270000"), Decimal("280000"), Decimal("3500.00")),
        (Decimal("280000"), Decimal("290000"), Decimal("1750.00")),
        (Decimal("290000"), None, Decimal("0.00")),
    ],
    # (floor, ceiling, rate%, base-tax-at-floor) — same 4-tuple shape
    # _ct_table_b_tax already reads. "Single, fewer than 3 allowances" set
    # doubles as the only Single set used here (allowances always 0).
    single_brackets_under_50k=[
        (Decimal("0"), Decimal("4550"), Decimal("4.75"), Decimal("263")),
        (Decimal("4550"), Decimal("11400"), Decimal("6.75"), Decimal("479")),
        (Decimal("11400"), Decimal("50000"), Decimal("8.75"), Decimal("941")),
    ],
    single_brackets_50k_plus=[
        (Decimal("38340"), Decimal("125000"), Decimal("8.75"), Decimal("678")),
        (Decimal("125000"), None, Decimal("9.90"), Decimal("10618")),
    ],
    married_brackets_under_50k=[
        (Decimal("0"), Decimal("9100"), Decimal("4.75"), Decimal("263")),
        (Decimal("9100"), Decimal("22800"), Decimal("6.75"), Decimal("695")),
        (Decimal("22800"), Decimal("50000"), Decimal("8.75"), Decimal("1620")),
    ],
    married_brackets_50k_plus=[
        (Decimal("35430"), Decimal("250000"), Decimal("8.75"), Decimal("1357")),
        (Decimal("250000"), None, Decimal("9.90"), Decimal("21237")),
    ],
    # HB 2119 (2019): flat rate when no OR-W-4/exemption certificate is on
    # file. Also the alternative flat rate for supplemental wages.
    no_certificate_flat_rate=Decimal("8.00"),
)

# ── Maine: percentage method with a phased-out standard deduction
# (Production-Readiness Plan Phase 4, 2026-09-15) ───────────────────────
# Maine Revenue Services 2026 withholding tables, independently fetched
# and extracted from maine.gov. Bracket rates/thresholds match a plain
# marginal TaxSlab table (5.80% / 6.75% / 7.15%) and ARE entered that way
# via the Bulk State Tax Import tool — only the STANDARD DEDUCTION needs
# bespoke logic here, since it is NOT the flat $15,300 (single) / $30,600
# (married) figure MRS publishes as its general "basic standard
# deduction" (a different, income-tax-return concept) — the WITHHOLDING
# formula's own Step 3 uses a lower, separately-phased-out figure:
# $12,450 (single) / $27,750 (married) flat below a threshold, phasing
# linearly to $0 by a second threshold. Entering the general $15,300/
# $30,600 figure as a flat state_standard_deduction would under-withhold
# every Maine employee, more so as income rises — this function is what
# makes that NOT happen.
_US_ME_WITHHOLDING_PARAMS = dict(
    agency="Maine Revenue Services",
    source_title="Maine Income Tax Withholding — Percentage Method — 2026 (26_wh_tab_instr.pdf)",
    personal_exemption_per_allowance=Decimal("5300.00"),
    single_deduction_full=Decimal("12450.00"), single_deduction_full_ceiling=Decimal("102250.00"),
    single_deduction_zero_floor=Decimal("177250.00"), single_deduction_phaseout_span=Decimal("75000.00"),
    married_deduction_full=Decimal("27750.00"), married_deduction_full_ceiling=Decimal("204550.00"),
    married_deduction_zero_floor=Decimal("354550.00"), married_deduction_phaseout_span=Decimal("150000.00"),
    backup_withholding_flat_rate=Decimal("5.00"),
)

# Kansas (Production-Readiness Plan Phase 4, KW-100 Rev. 10-24,
# independently verified against the source PDF's own text 2026-09-16 —
# every one of the 16 published per-pay-period bracket rows checks out
# arithmetically (bracket-width * 5.2% == published base-tax figure) and
# the Monthly table x12 cross-validates the annualized structure below to
# within a few cents/dollars of rounding). KW-100's own formula is genuinely
# two separate layers, not one: (1) a personal-exemption-style deduction —
# $9,160 (Single/HOH/MFS) or $18,320 (MFJ), plus a further flat $2,320 if
# Head of Household, plus $2,320 per dependent certified on Form K-4 — see
# _ks_personal_exemption_for_status; and (2) an ordinary 2-bracket marginal
# table applied to what's left, which — because it needs no bespoke
# phase-out/subtraction math of its own — is entered as real DB TaxSlab
# rows (see scripts/seed_us_phase4_kansas_2026.py) and consumed by the
# existing generic _calculate_annual_tax path, not a bespoke function.
_US_KS_WITHHOLDING_PARAMS = dict(
    agency="Kansas Department of Revenue",
    source_title="KW-100 Kansas Withholding Tax Guide (Rev. 10-24)",
    personal_exemption_single=Decimal("9160.00"),
    personal_exemption_mfj=Decimal("18320.00"),
    hoh_additional_allowance=Decimal("2320.00"),
    dependent_allowance=Decimal("2320.00"),
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
    # Missouri (gap-closure Level 2, Batch 7, 2026-09-13): Kansas City and
    # St. Louis Earnings Tax — a genuinely SEPARATE municipal filing from
    # MO DOR's own state withholding (St. Louis Form E-1/W-10, Kansas City
    # Form RD-109/RD-113), but structurally a plain flat-rate local tax
    # this engine's existing LocalityRate mechanism already models exactly
    # (see MI/Detroit above) — no engine change needed. Both cities' 1%
    # rate applies identically to residents (regardless of work location)
    # and nonresidents who work there; since resident_rate_pct and
    # nonresident_rate_pct are equal here, an employee whose work_locality
    # is set to one of these codes is taxed correctly regardless of which
    # of the two groups they're in. The one gap this does NOT cover: a
    # city resident who works OUTSIDE the city (elsewhere in MO, or out of
    # state) still owes this tax but has no locality-residence field to
    # trigger it from — the same pre-existing "this module does not yet
    # track locality-level residence" limitation us.py's own local-tax
    # comment already documents, not something newly introduced here.
    "MO": dict(
        agency="St. Louis Collector of Revenue / Kansas City, MO Finance Department",
        source_title="St. Louis Earnings Tax (Form E-1/W-10) and Kansas City Earnings Tax (Form RD-109/RD-113), current-year rate confirmation",
        rates=[
            dict(locality_code="STLOUIS", locality_type="MUNICIPAL", locality_name="St. Louis",
                 resident_rate_pct=Decimal("1.00"), nonresident_rate_pct=Decimal("1.00")),
            dict(locality_code="KANSASCITY", locality_type="MUNICIPAL", locality_name="Kansas City",
                 resident_rate_pct=Decimal("1.00"), nonresident_rate_pct=Decimal("1.00")),
        ],
    ),
    # New York (gap-closure Level 2, Batch 7, 2026-09-13): Yonkers'
    # NONRESIDENT earnings tax only (flat 0.50% of Yonkers-source wages,
    # Form Y-203) — modeled as an ordinary work-locality LocalityRate row
    # with only nonresident_rate_pct set (no resident_rate_pct at all),
    # since the RESIDENT side of Yonkers tax is fundamentally NOT a
    # wage-based rate (it's 16.75% of the employee's own NYS tax
    # liability, a completely different calculation) and is instead
    # handled by dedicated bespoke code in us.py, gated on the new
    # ctx.residence_locality field — see that code's own comment for how
    # the two are kept mutually exclusive for a Yonkers resident who also
    # works in Yonkers.
    "NY": dict(
        agency="NYS Department of Taxation and Finance",
        source_title="NYS-50-T-Y (1/26)",
        rates=[
            dict(locality_code="YONKERS", locality_type="MUNICIPAL", locality_name="Yonkers",
                 resident_rate_pct=None, nonresident_rate_pct=Decimal("0.50")),
        ],
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
