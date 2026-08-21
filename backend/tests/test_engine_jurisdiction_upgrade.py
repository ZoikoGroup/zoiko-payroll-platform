"""
tests/test_engine_jurisdiction_upgrade.py
--------------------------------------------
Regression coverage for the configuration-driven jurisdiction upgrade
(2026-08-19): the new resolve_jurisdiction_parameter wrapper, the six new
additive per-country calculations (India state-scoped PT, US FUTA + state
income tax, UK employer NI + Student/Postgraduate Loan + Scotland bands,
Germany church tax, Australia HELP/HECS, Canada CPP2), and — critically —
that none of it changes any EXISTING employee's numbers when the new
optional fields are left unset. Same hand-rolled-dataclass pattern as
test_engine_standard.py — no DB dependency.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.countries.shared import resolve_jurisdiction_parameter
from app.modules.payroll.engine.resolver import calculate_payroll


@dataclass
class Rate:
    component_key: str = ""
    employee_rate_pct: Optional[Decimal] = None
    employer_rate_pct: Optional[Decimal] = None
    flat_amount: Optional[Decimal] = None


@dataclass
class Slab:
    min_amount: Decimal = Decimal("0")
    max_amount: Optional[Decimal] = None
    rate_pct: Decimal = Decimal("0")
    rule_type: str = "MARGINAL_RATE"
    formula_expression: Optional[str] = None
    flat_amount: Optional[Decimal] = None


def calc(country, gross, rate_map=None, slabs=None, basic=None, **extra):
    ctx = PayrollContext(
        gross=Decimal(gross), basic=Decimal(basic if basic is not None else gross),
        country=country, rate_map=rate_map or {}, slabs=slabs or [],
        **extra,
    )
    return calculate_payroll(ctx, "standard")


# ── resolve_jurisdiction_parameter itself ──────────────────────────────────

def test_resolve_jurisdiction_parameter_uses_configured_amount_row():
    rate_map = {"standard_deduction": Rate(flat_amount=Decimal("90000"))}
    value = resolve_jurisdiction_parameter(rate_map, "standard_deduction", Decimal("75000"), country="IN")
    assert value == Decimal("90000")


def test_resolve_jurisdiction_parameter_falls_back_when_unconfigured():
    value = resolve_jurisdiction_parameter({}, "standard_deduction", Decimal("75000"), country="IN")
    assert value == Decimal("75000")


def test_resolve_jurisdiction_parameter_pct_side_employee_vs_employer():
    rate_map = {"national-insurance": Rate(employee_rate_pct=Decimal("8"), employer_rate_pct=Decimal("13.8"))}
    assert resolve_jurisdiction_parameter(rate_map, "national-insurance", Decimal("0"), side="employee", country="UK") == Decimal("8")
    assert resolve_jurisdiction_parameter(rate_map, "national-insurance", Decimal("0"), side="employer", country="UK") == Decimal("13.8")


# ── India: state-scoped Professional Tax ───────────────────────────────────

IN_RATES = {
    "pf": Rate("pf", Decimal("12.00"), Decimal("12.00")),
    "esi": Rate("esi", Decimal("0.75"), Decimal("3.25")),
    "pt": Rate("pt", flat_amount=Decimal("200")),
}
IN_SLABS = [
    Slab(Decimal("0"), Decimal("400000"), Decimal("0")),
    Slab(Decimal("400000"), Decimal("800000"), Decimal("5")),
    Slab(Decimal("800000"), None, Decimal("10")),
]


def test_india_no_state_uses_country_level_pt():
    result = calc("IN", 30000, IN_RATES, IN_SLABS)
    assert result.professional_tax == Decimal("200")


def test_india_state_scoped_pt_overrides_country_level():
    state_rates = {"pt": Rate(flat_amount=Decimal("2500"))}
    result = calc("IN", 30000, IN_RATES, IN_SLABS, work_state="Maharashtra", state_rate_map=state_rates)
    assert result.professional_tax == Decimal("2500")


def test_india_state_with_no_state_scoped_pt_falls_back_to_country_level():
    result = calc("IN", 30000, IN_RATES, IN_SLABS, work_state="SomeStateWithNoOverride", state_rate_map={})
    assert result.professional_tax == Decimal("200")


# ── India: income-bracketed state PT (PT_FLAT TaxSlab rows — PT Slabs feature) ──
# Telangana-shaped: Nil up to ₹15,000/month, ₹150 up to ₹20,000, ₹200 above —
# real law, genuinely bracketed by the employee's own gross, not a single
# flat number. state_rate_map is deliberately empty in these tests (no
# ContributionRate "pt" row) so bracket resolution is proven independently
# of the older single-flat-rate fallback path.
TG_PT_BRACKETS = [
    Slab(Decimal("0"), Decimal("15000"), Decimal("0"), rule_type="PT_FLAT", flat_amount=Decimal("0")),
    Slab(Decimal("15001"), Decimal("20000"), Decimal("0"), rule_type="PT_FLAT", flat_amount=Decimal("150")),
    Slab(Decimal("20001"), None, Decimal("0"), rule_type="PT_FLAT", flat_amount=Decimal("200")),
]


def test_india_pt_bracket_nil_tier():
    result = calc("IN", 12000, IN_RATES, IN_SLABS, work_state="Telangana", state_rate_map={}, state_slabs=TG_PT_BRACKETS)
    assert result.professional_tax == Decimal("0")


def test_india_pt_bracket_middle_tier():
    result = calc("IN", 18000, IN_RATES, IN_SLABS, work_state="Telangana", state_rate_map={}, state_slabs=TG_PT_BRACKETS)
    assert result.professional_tax == Decimal("150")


def test_india_pt_bracket_top_open_ended_tier():
    result = calc("IN", 50000, IN_RATES, IN_SLABS, work_state="Telangana", state_rate_map={}, state_slabs=TG_PT_BRACKETS)
    assert result.professional_tax == Decimal("200")


def test_india_pt_bracket_boundary_values_are_inclusive():
    # Exactly at each boundary — the lower tier still applies (matches
    # TaxSlab's existing min/max-inclusive convention elsewhere).
    at_15000 = calc("IN", 15000, IN_RATES, IN_SLABS, work_state="Telangana", state_rate_map={}, state_slabs=TG_PT_BRACKETS)
    at_20000 = calc("IN", 20000, IN_RATES, IN_SLABS, work_state="Telangana", state_rate_map={}, state_slabs=TG_PT_BRACKETS)
    assert at_15000.professional_tax == Decimal("0")
    assert at_20000.professional_tax == Decimal("150")


def test_india_pt_bracket_takes_priority_over_flat_rate_map():
    # A state with BOTH a legacy flat ContributionRate row AND PT_FLAT
    # bracket rows configured — brackets win, since they're the more
    # specific, more recently-added mechanism.
    state_rates_with_flat = {"pt": Rate(flat_amount=Decimal("9999"))}
    result = calc("IN", 18000, IN_RATES, IN_SLABS, work_state="Telangana", state_rate_map=state_rates_with_flat, state_slabs=TG_PT_BRACKETS)
    assert result.professional_tax == Decimal("150")


def test_india_no_pt_brackets_configured_is_unchanged_maharashtra_karnataka():
    # Maharashtra/Karnataka-shaped: zero PT_FLAT rows — must fall through
    # to the existing single-flat-rate behavior, byte-for-byte unchanged.
    state_rates = {"pt": Rate(flat_amount=Decimal("2500"))}
    result = calc("IN", 30000, IN_RATES, IN_SLABS, work_state="Maharashtra", state_rate_map=state_rates, state_slabs=[])
    assert result.professional_tax == Decimal("2500")


# ── USA: FUTA consumption + state income tax ────────────────────────────────

US_RATES = {
    "social-security": Rate(employee_rate_pct=Decimal("6.2"), employer_rate_pct=Decimal("6.2")),
    "medicare": Rate(employee_rate_pct=Decimal("1.45"), employer_rate_pct=Decimal("1.45")),
    "futa": Rate(employer_rate_pct=Decimal("6.0")),
}
US_SLABS = [Slab(Decimal("0"), Decimal("50000"), Decimal("10")), Slab(Decimal("50000"), None, Decimal("20"))]


def test_us_futa_is_now_actually_consumed():
    result = calc("US", 8000, US_RATES, US_SLABS)
    assert result.employer_futa > 0


def test_us_futa_capped_at_wage_base():
    # $7,000/yr wage base at 6% = $420/yr = $35/mo, regardless of how high gross is.
    result = calc("US", 50000, US_RATES, US_SLABS)
    assert result.employer_futa == Decimal("35.00")


def test_us_no_state_slabs_means_no_state_tax():
    result = calc("US", 8000, US_RATES, US_SLABS)
    federal_only_tds = result.tds
    result_with_empty_state = calc("US", 8000, US_RATES, US_SLABS, work_state="Texas", state_slabs=[])
    assert result_with_empty_state.tds == federal_only_tds


def test_us_state_income_tax_adds_to_federal():
    federal_only = calc("US", 8000, US_RATES, US_SLABS)
    state_slabs = [Slab(Decimal("0"), None, Decimal("9.3"))]
    with_state = calc("US", 8000, US_RATES, US_SLABS, work_state="California", state_slabs=state_slabs)
    assert with_state.tds > federal_only.tds


# ── UK: employer NI + Student Loan + Scotland bands ─────────────────────────

UK_RATES = {
    "national-insurance": Rate(employee_rate_pct=Decimal("8"), employer_rate_pct=Decimal("13.8")),
    "employer-pension": Rate(employer_rate_pct=Decimal("3")),
}
UK_SLABS = [Slab(Decimal("0"), Decimal("37700"), Decimal("20")), Slab(Decimal("37700"), None, Decimal("40"))]


def test_uk_employer_ni_now_actually_consumed():
    result = calc("UK", 5000, UK_RATES, UK_SLABS)
    assert result.employer_ni > 0


def test_uk_no_student_loan_by_default():
    result = calc("UK", 5000, UK_RATES, UK_SLABS)
    assert result.study_loan_deduction == Decimal("0")


def test_uk_student_loan_deducted_when_plan_and_balance_set():
    result = calc("UK", 5000, UK_RATES, UK_SLABS, study_loan_plan="UK_PLAN2", study_loan_balance=Decimal("20000"))
    assert result.study_loan_deduction > 0


def test_uk_student_loan_zero_without_outstanding_balance():
    result = calc("UK", 5000, UK_RATES, UK_SLABS, study_loan_plan="UK_PLAN2", study_loan_balance=Decimal("0"))
    assert result.study_loan_deduction == Decimal("0")


# Student/Postgraduate Loan thresholds are configurable per plan (Statutory
# Thresholds tab in Compliance) — a configured row must override the
# hardcoded default, exactly like every other UK threshold already does.

def test_uk_student_loan_plan1_threshold_configurable():
    default_result = calc("UK", 5000, UK_RATES, UK_SLABS, study_loan_plan="UK_PLAN1", study_loan_balance=Decimal("20000"))
    configured_rates = {**UK_RATES, "sl_plan1_thresh": Rate(flat_amount=Decimal("10000"))}
    configured_result = calc("UK", 5000, configured_rates, UK_SLABS, study_loan_plan="UK_PLAN1", study_loan_balance=Decimal("20000"))
    assert configured_result.study_loan_deduction > default_result.study_loan_deduction


def test_uk_student_loan_plan2_threshold_configurable():
    default_result = calc("UK", 5000, UK_RATES, UK_SLABS, study_loan_plan="UK_PLAN2", study_loan_balance=Decimal("20000"))
    configured_rates = {**UK_RATES, "sl_plan2_thresh": Rate(flat_amount=Decimal("10000"))}
    configured_result = calc("UK", 5000, configured_rates, UK_SLABS, study_loan_plan="UK_PLAN2", study_loan_balance=Decimal("20000"))
    assert configured_result.study_loan_deduction > default_result.study_loan_deduction


def test_uk_postgrad_loan_threshold_configurable():
    default_result = calc("UK", 5000, UK_RATES, UK_SLABS, study_loan_plan="UK_POSTGRAD", study_loan_balance=Decimal("20000"))
    configured_rates = {**UK_RATES, "pg_loan_thresh": Rate(flat_amount=Decimal("5000"))}
    configured_result = calc("UK", 5000, configured_rates, UK_SLABS, study_loan_plan="UK_POSTGRAD", study_loan_balance=Decimal("20000"))
    assert configured_result.study_loan_deduction > default_result.study_loan_deduction


def test_uk_scotland_uses_its_own_bands():
    national = calc("UK", 5000, UK_RATES, UK_SLABS)
    scotland_slabs = [Slab(Decimal("0"), None, Decimal("45"))]
    scottish = calc("UK", 5000, UK_RATES, UK_SLABS, work_state="Scotland", state_slabs=scotland_slabs)
    assert scottish.tds != national.tds


def test_uk_no_state_slabs_falls_back_to_national_regardless_of_state_name():
    # The engine itself no longer compares work_state against a
    # jurisdiction name (Section 5's "no hardcoded if state == Scotland").
    # Whether a sub-jurisdiction's own bands apply is decided upstream by
    # resolve_uk_configuration() — the engine only ever reads whichever
    # slabs actually ended up in ctx.state_slabs. With none supplied at
    # all, any work_state (including a real one like "England") falls
    # back to the national bands.
    national = calc("UK", 5000, UK_RATES, UK_SLABS)
    england_no_state_slabs = calc("UK", 5000, UK_RATES, UK_SLABS, work_state="England")
    assert england_no_state_slabs.tds == national.tds


def test_uk_engine_uses_whatever_state_slabs_it_is_given():
    # Conversely: if the resolver DID populate ctx.state_slabs for some
    # sub-jurisdiction, the engine uses them — it doesn't re-check the
    # jurisdiction's name itself. This is what makes Wales/Northern
    # Ireland genuinely addressable the moment real data exists for them,
    # without any engine change.
    national = calc("UK", 5000, UK_RATES, UK_SLABS)
    wales_with_real_state_slabs = calc(
        "UK", 5000, UK_RATES, UK_SLABS, work_state="Wales",
        state_slabs=[Slab(Decimal("0"), None, Decimal("99"))],
    )
    assert wales_with_real_state_slabs.tds != national.tds


def test_normalize_uk_sub_jurisdiction_recognizes_all_four_nations():
    from app.modules.payroll.service import _normalize_uk_sub_jurisdiction
    assert _normalize_uk_sub_jurisdiction("England") == "England"
    assert _normalize_uk_sub_jurisdiction("scotland") == "Scotland"
    assert _normalize_uk_sub_jurisdiction("WALES") == "Wales"
    assert _normalize_uk_sub_jurisdiction("Northern Ireland") == "Northern Ireland"
    assert _normalize_uk_sub_jurisdiction("Not A Real Place") is None
    assert _normalize_uk_sub_jurisdiction(None) is None


# ── Germany: church tax opt-in ──────────────────────────────────────────────

DE_SLABS = [Slab(Decimal("0"), None, Decimal("20"))]


def test_germany_church_tax_off_by_default():
    result = calc("DE", 5000, {}, DE_SLABS)
    assert result.church_tax == Decimal("0")


def test_germany_church_tax_applied_when_liable():
    result = calc("DE", 5000, {}, DE_SLABS, church_tax_liable=True)
    assert result.church_tax > 0


# ── Australia: HELP/HECS ────────────────────────────────────────────────────

AU_SLABS = [Slab(Decimal("0"), None, Decimal("30"))]


def test_australia_help_zero_without_plan():
    result = calc("AU", 8000, {}, AU_SLABS)
    assert result.study_loan_deduction == Decimal("0")


def test_australia_help_deducted_above_threshold():
    result = calc("AU", 8000, {}, AU_SLABS, study_loan_plan="AU_HELP", study_loan_balance=Decimal("15000"))
    assert result.study_loan_deduction > 0


def test_australia_help_zero_below_threshold():
    # $54,435/yr threshold ÷ 12 ≈ $4,536/mo — a $2,000/mo gross stays under it.
    result = calc("AU", 2000, {}, AU_SLABS, study_loan_plan="AU_HELP", study_loan_balance=Decimal("15000"))
    assert result.study_loan_deduction == Decimal("0")


# ── Canada: CPP2 ─────────────────────────────────────────────────────────────

CA_RATES = {"cpp": Rate(employee_rate_pct=Decimal("5.95"), employer_rate_pct=Decimal("5.95"))}
CA_SLABS = [Slab(Decimal("0"), None, Decimal("15"))]


def test_canada_cpp2_zero_below_ympe():
    # $3,000/mo = $36,000/yr, well under the $71,300 YMPE.
    result = calc("CA", 3000, CA_RATES, CA_SLABS)
    assert result.cpp2 == Decimal("0")


def test_canada_cpp2_nonzero_above_ympe():
    # $9,000/mo = $108,000/yr, above the $71,300 YMPE.
    result = calc("CA", 9000, CA_RATES, CA_SLABS)
    assert result.cpp2 > 0


# ── Cross-cutting: the opt-in fields (study loan, church tax, CPP2) stay
# zero for an "old-style" employee with none of the new optional fields
# set, in every country — the only genuinely NEW mandatory line UK adds
# (employer NI) is intentionally excluded here since it was never opt-in
# to begin with, matching real UK payroll (it's a standard, always-
# computed employer cost) — see test_uk_employer_ni_now_actually_consumed.

def test_opt_in_fields_are_zero_without_explicit_employee_data():
    for country, rates, slabs in [
        ("IN", IN_RATES, IN_SLABS), ("US", US_RATES, US_SLABS), ("UK", UK_RATES, UK_SLABS),
        ("DE", {}, DE_SLABS), ("AU", {}, AU_SLABS), ("CA", CA_RATES, CA_SLABS),
    ]:
        result = calc(country, 5000, rates, slabs)
        assert result.study_loan_deduction == Decimal("0"), country
        assert result.church_tax == Decimal("0"), country
        if country != "CA":
            assert result.cpp2 == Decimal("0"), country


# ── India: Cess, Surcharge, regime-aware Section 87A ────────────────────────
# The Tax Parameters tab work — cess/surcharge didn't exist in this engine
# at all before this; both are wired in now. Unlike every other addition in
# this file, cess is a DELIBERATE, CONFIRMED behavioral change: every real
# Indian org's computed TDS grows by ~4% as of this change (see india.py's
# _IN_CESS_PCT docstring) — there is no "byte-identical without cess"
# variant, since cess has no opt-in flag by design (it's not optional under
# real Indian tax law). Surcharge, by contrast, IS opt-in in effect: with no
# SURCHARGE-tagged TaxSlab rows configured (every org today), it stays 0.


def _make_surcharge_tier(threshold, pct):
    return Slab(Decimal(threshold), None, Decimal(pct), rule_type="SURCHARGE")


def test_india_cess_applied_at_default_4pct():
    result = calc("IN", 200000, IN_RATES, IN_SLABS)  # well above rebate limit, pure slab tax
    assert result.cess > Decimal("0")
    # tds is the FULL monthly liability — base tax + surcharge (0 here) + cess
    # — so it must be strictly greater than the base monthly tax alone.
    assert result.tds > (result.annual_tax / Decimal("12"))


def test_india_cess_zero_when_tax_is_zero():
    result = calc("IN", 10000, IN_RATES, IN_SLABS)  # well under standard deduction, zero base tax
    assert result.cess == Decimal("0")
    assert result.surcharge == Decimal("0")


def test_india_cess_overridable_via_rate_map():
    rates = dict(IN_RATES, cess_pct=Rate(flat_amount=Decimal("10")))
    result_default = calc("IN", 500000, IN_RATES, IN_SLABS)
    result_overridden = calc("IN", 500000, rates, IN_SLABS)
    assert result_overridden.cess > result_default.cess


def test_india_surcharge_zero_with_no_tiers_configured():
    # High income, but zero SURCHARGE-tagged slab rows anywhere — matches
    # every real org today. Surcharge (and therefore tds) must be
    # completely unaffected by the new surcharge mechanism existing.
    high_income_slabs = IN_SLABS  # no SURCHARGE tier rows present
    result = calc("IN", 1000000, IN_RATES, high_income_slabs)
    assert result.surcharge == Decimal("0")


def test_india_surcharge_tier_applies_above_threshold():
    slabs_with_surcharge = IN_SLABS + [_make_surcharge_tier("5000000", "10")]
    below = calc("IN", 400000, IN_RATES, slabs_with_surcharge)   # 48L annual, below 50L tier
    above = calc("IN", 500000, IN_RATES, slabs_with_surcharge)   # 60L annual, above 50L tier
    assert below.surcharge == Decimal("0")
    assert above.surcharge > Decimal("0")


def test_india_surcharge_marginal_relief_caps_at_excess_income():
    # Monthly gross chosen so annual taxable income lands just ₹10,000
    # above the ₹50L surcharge threshold — real marginal relief must cap
    # (tax + surcharge) so it never grows by more than that ₹10,000.
    slabs_with_surcharge = IN_SLABS + [_make_surcharge_tier("5000000", "10")]
    monthly = Decimal("5000000") / Decimal("12") + Decimal("10000") / Decimal("12")
    result = calc("IN", monthly, IN_RATES, slabs_with_surcharge)
    at_threshold = calc("IN", Decimal("5000000") / Decimal("12"), IN_RATES, slabs_with_surcharge)
    # (annual base tax + annual surcharge) at the higher income should not
    # exceed (annual base tax + annual surcharge at the threshold) + 10,000.
    actual_annual_total = (result.annual_tax + result.surcharge * 12)
    threshold_annual_total = (at_threshold.annual_tax + at_threshold.surcharge * 12)
    assert actual_annual_total <= threshold_annual_total + Decimal("10000") + Decimal("1")  # +1 for rounding


def test_india_surcharge_marginal_relief_can_be_disabled():
    rates = dict(IN_RATES, surcharge_marginal_relief=Rate(flat_amount=Decimal("0")))
    slabs_with_surcharge = IN_SLABS + [_make_surcharge_tier("5000000", "10")]
    monthly = Decimal("5000000") / Decimal("12") + Decimal("1000") / Decimal("12")
    relieved = calc("IN", monthly, IN_RATES, slabs_with_surcharge)
    unrelieved = calc("IN", monthly, rates, slabs_with_surcharge)
    assert unrelieved.surcharge >= relieved.surcharge


def test_india_87a_new_regime_marginal_relief_caps_tax_just_above_limit():
    # ₹12,10,000 taxable (post-standard-deduction) under the New Regime is
    # a well-documented real example: tax payable should be exactly the
    # ₹10,000 of income above the ₹12,00,000 limit, not the ~₹61,500 raw
    # slab tax. Standard deduction (₹75,000) means gross must be higher.
    annual_gross = Decimal("1210000") + Decimal("75000")
    monthly = annual_gross / Decimal("12")
    result = calc("IN", monthly, IN_RATES, IN_SLABS, tax_regime="New")
    assert result.annual_tax == Decimal("10000")


def test_india_87a_old_regime_uses_its_own_lower_limit():
    # ₹5,02,000 taxable is ₹2,000 above the Old Regime's ₹5,00,000 limit —
    # with IN_SLABS' 5% bracket there, raw tax (₹5,100) exceeds the ₹2,000
    # excess income, so relief caps it at exactly ₹2,000. Under the New
    # Regime (₹12L limit, ₹75,000 standard deduction) the SAME gross would
    # be fully rebated to zero instead.
    old_annual_gross = Decimal("502000") + Decimal("50000")   # Old Regime's own standard deduction
    new_annual_gross = Decimal("502000") + Decimal("75000")   # New Regime's own standard deduction
    old_result = calc("IN", old_annual_gross / Decimal("12"), IN_RATES, IN_SLABS, tax_regime="Old")
    new_result = calc("IN", new_annual_gross / Decimal("12"), IN_RATES, IN_SLABS, tax_regime="New")
    assert old_result.annual_tax == Decimal("2000")
    assert new_result.annual_tax == Decimal("0")


def test_india_87a_marginal_relief_can_be_disabled():
    rates = dict(IN_RATES, rebate_87a_marginal_relief=Rate(flat_amount=Decimal("0")))
    annual_gross = Decimal("1210000") + Decimal("75000")
    monthly = annual_gross / Decimal("12")
    relieved = calc("IN", monthly, IN_RATES, IN_SLABS, tax_regime="New")
    unrelieved = calc("IN", monthly, rates, IN_SLABS, tax_regime="New")
    assert unrelieved.annual_tax > relieved.annual_tax
    assert relieved.annual_tax == Decimal("10000")


def test_india_tax_regime_defaults_to_new_when_unset():
    # An "old-style" employee with tax_regime unset must keep exactly
    # today's New-Regime-shaped 87A behavior — no behavior change from
    # adding the tax_regime field itself.
    annual_gross = Decimal("1210000") + Decimal("75000")
    monthly = annual_gross / Decimal("12")
    unset = calc("IN", monthly, IN_RATES, IN_SLABS)               # tax_regime not passed at all
    explicit_new = calc("IN", monthly, IN_RATES, IN_SLABS, tax_regime="New")
    assert unset.annual_tax == explicit_new.annual_tax == Decimal("10000")


# ── UK production refactor: tax-code interpretation ─────────────────────

from app.modules.payroll.engine.countries.uk import interpret_tax_code, _resolve_ni_bands, _calculate_ni_from_bands


def test_tax_code_standard_code_sets_allowance_from_digits():
    result = interpret_tax_code("1257L", Decimal("12570"))
    assert result["personal_allowance"] == Decimal("12570")
    assert result["flat_rate_pct"] is None


def test_tax_code_br_is_flat_20pct_no_allowance():
    result = interpret_tax_code("BR", Decimal("12570"))
    assert result["personal_allowance"] == Decimal("0")
    assert result["flat_rate_pct"] == Decimal("20")


def test_tax_code_d0_is_flat_40pct():
    assert interpret_tax_code("D0", Decimal("12570"))["flat_rate_pct"] == Decimal("40")


def test_tax_code_d1_is_flat_45pct():
    assert interpret_tax_code("D1", Decimal("12570"))["flat_rate_pct"] == Decimal("45")


def test_tax_code_nt_means_zero_tax():
    result = interpret_tax_code("NT", Decimal("12570"))
    assert result["flat_rate_pct"] == Decimal("0")


def test_tax_code_k_code_gives_negative_allowance():
    # K475 -> a NEGATIVE allowance of 4750, added to taxable income rather
    # than subtracted from it (an untaxed benefit clawed back via payroll).
    result = interpret_tax_code("K475", Decimal("12570"))
    assert result["personal_allowance"] == Decimal("-4750")
    assert result["flat_rate_pct"] is None


def test_tax_code_unset_falls_back_to_default_allowance():
    result = interpret_tax_code(None, Decimal("12570"))
    assert result["personal_allowance"] == Decimal("12570")
    assert result["basis"] == "CUMULATIVE"


def test_uk_br_code_taxes_full_income_at_20pct_no_allowance():
    with_code = calc("UK", 5000, UK_RATES, UK_SLABS, tax_code="BR")
    without_code = calc("UK", 5000, UK_RATES, UK_SLABS)
    # BR gives up the personal allowance entirely -- strictly different
    # tax than the standard code's allowance-then-slabs calculation.
    assert with_code.annual_tax != without_code.annual_tax


def test_uk_nt_code_means_zero_annual_tax():
    result = calc("UK", 5000, UK_RATES, UK_SLABS, tax_code="NT")
    assert result.annual_tax == Decimal("0")
    assert result.tds == Decimal("0")


# ── UK production refactor: NI category bands (regression guard) ───────

_NI_CAT_A_BANDS = [
    Slab(Decimal("0"), Decimal("9100"), Decimal("0"), rule_type="NI_BAND"),
    Slab(Decimal("9100"), Decimal("12570"), Decimal("0"), rule_type="NI_BAND"),
    Slab(Decimal("12570"), Decimal("50270"), Decimal("8"), rule_type="NI_BAND"),
    Slab(Decimal("50270"), None, Decimal("2"), rule_type="NI_BAND"),
]
# employer_rate_pct/ni_category are not Slab dataclass fields (kept
# engine-only rather than editing the shared test dataclass used by every
# other country's tests) -- set via setattr to mirror the live-DB row shape.
for _band, _empr in zip(_NI_CAT_A_BANDS, [Decimal("0"), Decimal("13.8"), Decimal("13.8"), Decimal("13.8")]):
    _band.employer_rate_pct = _empr
    _band.ni_category = "A"


def test_ni_category_a_bands_match_flat_calculation_exactly():
    # The banded representation is additive (Section D) -- for Category A
    # specifically, it must reproduce today's flat ContributionRate-based
    # NI figures exactly, since the band boundaries are the union of the
    # employee (PT/UEL) and employer (ST) thresholds.
    flat_result = calc("UK", 5000, UK_RATES, UK_SLABS)
    banded_result = calc("UK", 5000, UK_RATES, UK_SLABS + _NI_CAT_A_BANDS, ni_category="A")
    assert banded_result.ni_employee == flat_result.ni_employee
    assert banded_result.employer_ni == flat_result.employer_ni


def test_ni_bands_ignored_without_a_category_set():
    with_bands_no_category = calc("UK", 5000, UK_RATES, UK_SLABS + _NI_CAT_A_BANDS)
    flat_result = calc("UK", 5000, UK_RATES, UK_SLABS)
    assert with_bands_no_category.ni_employee == flat_result.ni_employee


def test_resolve_ni_bands_filters_by_category_and_sorts():
    other_category = Slab(Decimal("0"), None, Decimal("0"), rule_type="NI_BAND")
    other_category.ni_category = "B"
    other_category.employer_rate_pct = Decimal("0")
    all_slabs = _NI_CAT_A_BANDS + [other_category]
    bands = _resolve_ni_bands(all_slabs, "A")
    assert len(bands) == 4
    assert [b.min_amount for b in bands] == [Decimal("0"), Decimal("9100"), Decimal("12570"), Decimal("50270")]


def test_calculate_ni_from_bands_matches_hand_calculation():
    annual_gross = Decimal("60000")
    employee_annual, employer_annual = _calculate_ni_from_bands(annual_gross, _NI_CAT_A_BANDS)
    # Employee: (50270-12570)*8% + (60000-50270)*2% = 3016 + 194.60 = 3210.60
    assert employee_annual == Decimal("3210.60")
    # Employer: (60000-9100)*13.8% = 7024.20
    assert employer_annual == Decimal("7024.20")


# ── UK production refactor: pension (employee + employer, basis-aware) ──

UK_RATES_WITH_EMPLOYEE_PENSION = {
    **UK_RATES,
    "employer-pension": Rate("employer-pension", employee_rate_pct=Decimal("5"), employer_rate_pct=Decimal("3")),
}


def test_uk_employee_pension_zero_when_no_employee_rate_configured():
    # Today's exact behavior: UK_RATES' employer-pension row has no
    # employee_rate_pct at all -- must not silently start deducting.
    result = calc("UK", 5000, UK_RATES, UK_SLABS)
    assert result.employee_pension == Decimal("0")


def test_uk_employee_pension_qualifying_earnings_basis():
    result = calc("UK", 5000, UK_RATES_WITH_EMPLOYEE_PENSION, UK_SLABS)
    qe_lower_monthly = Decimal("6240") / Decimal("12")
    qe_upper_monthly = Decimal("50270") / Decimal("12")
    pensionable = min(Decimal("5000"), qe_upper_monthly) - qe_lower_monthly
    expected = (pensionable * Decimal("5") / Decimal("100")).quantize(Decimal("0.01"))
    assert result.employee_pension == expected
    assert result.employee_pension > Decimal("0")


def test_uk_employee_pension_basic_pay_basis():
    rates = {**UK_RATES_WITH_EMPLOYEE_PENSION, "pension_basis": Rate(flat_amount=None)}
    rates["pension_basis"].text_value = "BASIC_PAY"
    result = calc("UK", 5000, rates, UK_SLABS, basic=Decimal("3000"))
    expected = (Decimal("3000") * Decimal("5") / Decimal("100")).quantize(Decimal("0.01"))
    assert result.employee_pension == expected


def test_uk_employer_pension_still_calculated_independently_of_employee_pension():
    with_employee = calc("UK", 5000, UK_RATES_WITH_EMPLOYEE_PENSION, UK_SLABS)
    without_employee = calc("UK", 5000, UK_RATES, UK_SLABS)
    assert with_employee.employer_pension == without_employee.employer_pension
    assert with_employee.employer_pension > Decimal("0")


# ── UK production refactor: Student Loan Plan 5 ─────────────────────────

def test_uk_student_loan_plan5_deducts_above_threshold():
    result = calc("UK", 5000, UK_RATES, UK_SLABS, study_loan_plan="UK_PLAN5", study_loan_balance=Decimal("20000"))
    assert result.study_loan_deduction > Decimal("0")


def test_uk_student_loan_plan5_threshold_configurable():
    default_result = calc("UK", 5000, UK_RATES, UK_SLABS, study_loan_plan="UK_PLAN5", study_loan_balance=Decimal("20000"))
    configured_rates = {**UK_RATES, "sl_plan5_thresh": Rate(flat_amount=Decimal("10000"))}
    configured_result = calc("UK", 5000, configured_rates, UK_SLABS, study_loan_plan="UK_PLAN5", study_loan_balance=Decimal("20000"))
    assert configured_result.study_loan_deduction > default_result.study_loan_deduction


# ── UK production refactor: pay frequency ────────────────────────────────

def test_uk_weekly_frequency_annualizes_to_same_annual_tax_as_monthly():
    monthly = calc("UK", 5000, UK_RATES, UK_SLABS, pay_frequency="Monthly")
    weekly_equivalent_gross = Decimal("5000") * 12 / 52
    weekly = calc("UK", weekly_equivalent_gross, UK_RATES, UK_SLABS, pay_frequency="Weekly")
    assert abs(weekly.annual_tax - monthly.annual_tax) < Decimal("1")


def test_uk_pay_frequency_defaults_to_monthly_when_unset():
    explicit_monthly = calc("UK", 5000, UK_RATES, UK_SLABS, pay_frequency="Monthly")
    unset = calc("UK", 5000, UK_RATES, UK_SLABS)
    assert explicit_monthly.tds == unset.tds
    assert explicit_monthly.ni_employee == unset.ni_employee
