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

import pytest

from app.modules.payroll.engine.base import PayrollContext, _round2
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
    filing_status: Optional[str] = None
    jurisdiction_state: Optional[str] = None


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


# ── Fallback Removal Fix Plan Phase 3: required-configuration validation ──
# _VALIDATION_ENABLED_COUNTRIES starts empty (Phase 6 is what actually adds
# a country) — these tests exercise the capability directly by adding/
# removing a country themselves, restoring the module-level set afterward
# so this doesn't leak into any other test.

def test_resolve_jurisdiction_parameter_raises_when_country_opted_into_validation():
    from app.modules.payroll.engine.countries import shared as shared_module
    shared_module._VALIDATION_ENABLED_COUNTRIES.add("ZZ")
    try:
        with pytest.raises(shared_module.MissingComplianceConfigurationError):
            resolve_jurisdiction_parameter({}, "standard_deduction", Decimal("75000"), country="ZZ")
    finally:
        shared_module._VALIDATION_ENABLED_COUNTRIES.discard("ZZ")


def test_resolve_jurisdiction_parameter_still_falls_back_for_a_country_not_opted_in():
    from app.modules.payroll.engine.countries import shared as shared_module
    shared_module._VALIDATION_ENABLED_COUNTRIES.add("ZZ")
    try:
        # A DIFFERENT, genuinely-not-enabled country (not "IN" — that's
        # opted in for real as of Phase 6, so it's no longer a valid
        # "not opted in" example) — must still silently fall back exactly
        # as before, proving this is per-country, not a global switch
        # flipped by any one country being enabled.
        value = resolve_jurisdiction_parameter({}, "standard_deduction", Decimal("75000"), country="DE")
        assert value == Decimal("75000")
    finally:
        shared_module._VALIDATION_ENABLED_COUNTRIES.discard("ZZ")


def test_resolve_jurisdiction_parameter_configured_row_never_raises_even_when_opted_in():
    from app.modules.payroll.engine.countries import shared as shared_module
    shared_module._VALIDATION_ENABLED_COUNTRIES.add("ZZ")
    try:
        rate_map = {"standard_deduction": Rate(flat_amount=Decimal("90000"))}
        value = resolve_jurisdiction_parameter(rate_map, "standard_deduction", Decimal("75000"), country="ZZ")
        assert value == Decimal("90000")
    finally:
        shared_module._VALIDATION_ENABLED_COUNTRIES.discard("ZZ")


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
    from app.modules.payroll.engine.countries import shared as shared_module
    federal_only = calc("US", 8000, US_RATES, US_SLABS)
    state_slabs = [Slab(Decimal("0"), None, Decimal("9.3"), jurisdiction_state="CA")]
    shared_module._US_STATE_TAX_ENABLED_STATES.add("CA")
    try:
        with_state = calc("US", 8000, US_RATES, US_SLABS, work_state="California", state_slabs=state_slabs)
    finally:
        shared_module._US_STATE_TAX_ENABLED_STATES.discard("CA")
    assert with_state.tds > federal_only.tds


# ── UK: employer NI + Student Loan + Scotland bands ─────────────────────────

UK_RATES = {
    # 2026-27 figures per ZP-TAX-UK-2026-27-001 section 9.1 (Category A).
    "national-insurance": Rate(employee_rate_pct=Decimal("8"), employer_rate_pct=Decimal("15")),
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


def test_uk_plan5_plus_postgrad_matches_document_worked_example():
    # ZP-TAX-UK-2026-27-001 §10.2's own reference test vectors: Plan 5
    # (£82) + Postgraduate (£75) = £157, as two separate components — the
    # round-down-to-pound rule (§10.2) is now the shipped default.
    result = calc(
        "UK", 3000, UK_RATES, UK_SLABS,
        study_loan_plan="UK_PLAN5", study_loan_balance=Decimal("20000"),
        has_postgrad_loan=True,
    )
    assert result.study_loan_deduction == Decimal("82")
    assert result.postgrad_loan_deduction == Decimal("75")
    assert result.study_loan_deduction + result.postgrad_loan_deduction == Decimal("157")


def test_uk_standalone_postgrad_plan_unaffected_by_unset_flag():
    # A standalone Postgraduate-only employee (study_loan_plan=="UK_POSTGRAD")
    # with has_postgrad_loan left at its default (False) must produce
    # exactly today's single deduction, with the new field at 0.
    result = calc("UK", 3000, UK_RATES, UK_SLABS, study_loan_plan="UK_POSTGRAD", study_loan_balance=Decimal("20000"))
    assert result.study_loan_deduction == Decimal("75.00")
    assert result.postgrad_loan_deduction == Decimal("0")


def test_uk_postgrad_flag_does_not_double_deduct_for_standalone_postgrad_plan():
    # Guard: even if has_postgrad_loan were somehow set True alongside
    # study_loan_plan=="UK_POSTGRAD" (should be rejected earlier at
    # employee_validation.py), the engine itself must never double-apply
    # the Postgraduate deduction.
    result = calc(
        "UK", 3000, UK_RATES, UK_SLABS,
        study_loan_plan="UK_POSTGRAD", study_loan_balance=Decimal("20000"),
        has_postgrad_loan=True,
    )
    assert result.postgrad_loan_deduction == Decimal("0")
    assert result.study_loan_deduction == Decimal("75.00")


def test_uk_postgrad_loan_zero_when_flag_not_set():
    result = calc("UK", 3000, UK_RATES, UK_SLABS, study_loan_plan="UK_PLAN5", study_loan_balance=Decimal("20000"))
    assert result.postgrad_loan_deduction == Decimal("0")


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
    rates = dict(IN_RATES, surcharge_mrelief=Rate(flat_amount=Decimal("0")))
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
    #
    # Old Regime ALSO deducts annual Professional Tax from taxable salary
    # (§4.2's "Critical regime separation" — IN_RATES' "pt" flat_amount of
    # 200/month = 2,400/year), so the gross must additionally cover that
    # to land taxable income at exactly the same ₹5,02,000 target; New
    # Regime never deducts PT, so its gross is unaffected.
    old_annual_gross = Decimal("502000") + Decimal("50000") + Decimal("2400")   # + Old Regime's std deduction + annual PT
    new_annual_gross = Decimal("502000") + Decimal("75000")   # New Regime's own standard deduction
    old_result = calc("IN", old_annual_gross / Decimal("12"), IN_RATES, IN_SLABS, tax_regime="Old")
    new_result = calc("IN", new_annual_gross / Decimal("12"), IN_RATES, IN_SLABS, tax_regime="New")
    assert old_result.annual_tax == Decimal("2000")
    assert new_result.annual_tax == Decimal("0")


def test_india_old_regime_deducts_professional_tax_from_taxable_salary():
    # ZP-TAX-IN-2026-27-001 §4.2 / AC-08 / IN-TAX-004: PT is deductible
    # from salary income under the Old Regime's own salary-deduction
    # framework — this deduction did not exist at all before this fix
    # (taxable was always just gross minus standard_deduction).
    # IN_RATES' "pt" flat_amount is 200/month = 2,400/year.
    annual_gross = Decimal("502400") + Decimal("50000")  # std deduction only; PT comes out of taxable, not gross
    result = calc("IN", annual_gross / Decimal("12"), IN_RATES, IN_SLABS, tax_regime="Old")
    # Taxable before PT: 502,400. After PT (-2,400): exactly 500,000 —
    # AT the Old Regime rebate limit, so rebate should fully cancel tax.
    assert result.annual_tax == Decimal("0")


def test_india_new_regime_never_deducts_professional_tax():
    # Same critical regime separation, the other direction: New Regime's
    # taxable salary must NOT be reduced by PT at all (§4.2, §3.2's own
    # "Professional tax deduction: Not allowed in section 202 computation").
    annual_gross = Decimal("1200000") + Decimal("75000")
    result = calc("IN", annual_gross / Decimal("12"), IN_RATES, IN_SLABS, tax_regime="New")
    # If PT (2,400) were wrongly subtracted, taxable would drop below the
    # 1,200,000 rebate ceiling and still be zero — so instead assert taxable
    # income is exactly at the ceiling by checking annual_tax matches the
    # zero-TDS document example (slab tax 60,000, rebate 60,000, net 0)
    # AND that a taxable income 1 rupee above the ceiling is NOT zero,
    # proving PT truly wasn't subtracted.
    assert result.annual_tax == Decimal("0")
    just_above = calc("IN", (annual_gross + Decimal("12")) / Decimal("12"), IN_RATES, IN_SLABS, tax_regime="New")
    assert just_above.annual_tax > Decimal("0")


def test_india_wage_deduction_cap_flags_when_exceeded():
    # ZP-TAX-IN-2026-27-001 §8.3 / AC-18 / IN-CAP-001: authorized
    # deductions above 50% of wages must raise a compliance flag — the
    # engine must NEVER silently reduce a statutory levy to make net pay
    # positive, so this is a flag, not a recalculation. Force it with an
    # extreme PT override well above what any real employee would see.
    heavy_rates = dict(IN_RATES, pt=Rate(flat_amount=Decimal("100000")))
    result = calc("IN", 30000, heavy_rates, IN_SLABS)
    assert result.wage_deduction_cap_exceeded is True
    # Still deducted in full — never silently reduced to fit under the cap.
    assert result.professional_tax == Decimal("100000")


def test_india_wage_deduction_cap_not_flagged_under_normal_deductions():
    result = calc("IN", 30000, IN_RATES, IN_SLABS)
    assert result.wage_deduction_cap_exceeded is False


def test_wage_deduction_cap_never_flagged_outside_india():
    # India's own Labour Code — must not spuriously apply to any other
    # country, even one with the exact same (heavy) rate configuration
    # that trips the flag for India above.
    heavy_rates = dict(IN_RATES, pt=Rate(flat_amount=Decimal("100000")))
    result = calc("UK", 30000, heavy_rates, IN_SLABS)
    assert result.wage_deduction_cap_exceeded is False


def test_india_employer_nps_zero_until_configured():
    # §3.2's employer NPS contribution — no hardcoded fallback, resolves
    # to 0 until Tax Ops configures "nps_employer_pct".
    result = calc("IN", 30000, IN_RATES, IN_SLABS, basic=15000, tax_regime="New")
    assert result.employer_nps == Decimal("0")


def test_india_employer_nps_new_regime_computed_and_reduces_taxable_income():
    # 14% of Basic (§3.2's "14% path... under new regime"), and this
    # amount must ALSO reduce New Regime taxable salary. Income set well
    # above the 1,200,000 rebate ceiling so the reduction is actually
    # visible in annual_tax (otherwise §3.2's own rebate would fully
    # cancel tax either way, masking the difference).
    rates = dict(IN_RATES, nps_employer_pct=Rate(employer_rate_pct=Decimal("14.00")))
    annual_basic = Decimal("2000000")
    result = calc("IN", annual_basic / Decimal("12"), rates, IN_SLABS, basic=annual_basic / Decimal("12"), tax_regime="New")
    assert result.employer_nps == _round2(annual_basic / Decimal("12") * Decimal("0.14"))

    baseline = calc("IN", annual_basic / Decimal("12"), IN_RATES, IN_SLABS, basic=annual_basic / Decimal("12"), tax_regime="New")
    assert result.annual_tax < baseline.annual_tax, "employer NPS must reduce New Regime taxable income, not just be a cost"


def test_india_employer_nps_never_reduces_old_regime_taxable_income():
    # §3.2 places this deduction only under the New Regime's own table —
    # the document gives no old-regime figure for it at all, so it must
    # never reduce Old Regime taxable salary even if the rate is
    # untagged (applies to both regimes as a COST, per the rate's own
    # scope, but never as an Old-regime taxable-income reduction).
    rates = dict(IN_RATES, nps_employer_pct=Rate(employer_rate_pct=Decimal("14.00")))
    annual_basic = Decimal("600000")
    with_nps = calc("IN", annual_basic / Decimal("12"), rates, IN_SLABS, basic=annual_basic / Decimal("12"), tax_regime="Old")
    without_nps = calc("IN", annual_basic / Decimal("12"), IN_RATES, IN_SLABS, basic=annual_basic / Decimal("12"), tax_regime="Old")
    assert with_nps.employer_nps > Decimal("0"), "employer still incurs the cost under Old regime"
    assert with_nps.annual_tax == without_nps.annual_tax, "but it must not change Old Regime taxable income"


def test_india_87a_marginal_relief_can_be_disabled():
    rates = dict(IN_RATES, rebate_87a_mrelief=Rate(flat_amount=Decimal("0")))
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


# ── ZP-TAX-UK-2026-27-001 correctness fixes (all dormant by default) ───

def test_uk_pa_taper_still_reachable_if_explicitly_reverted():
    # Phase 1 shipped 2026-09-07: _UK_NO_INDEPENDENT_PA_TAPER_ENABLED_COUNTRIES
    # now defaults to {"UK"} (see shared.py). The OLD, superseded independent-
    # taper behavior remains reachable only by explicitly discarding "UK"
    # from the set — proving the fix is a genuine toggle, not a one-way
    # rewrite with dead code left behind.
    from app.modules.payroll.engine.countries import shared as shared_module
    from app.modules.payroll.engine.countries.uk import _calculate_annual_tax_uk
    shared_module._UK_NO_INDEPENDENT_PA_TAPER_ENABLED_COUNTRIES.discard("UK")
    try:
        annual_gross = Decimal("120000")
        tax = _calculate_annual_tax_uk(annual_gross, UK_SLABS, UK_RATES)
        taper = (annual_gross - Decimal("100000")) / Decimal("2")
        taxable = annual_gross - (Decimal("12570") - taper)
        expected = Decimal("37700") * Decimal("0.20") + (taxable - Decimal("37700")) * Decimal("0.40")
        assert tax == expected
    finally:
        shared_module._UK_NO_INDEPENDENT_PA_TAPER_ENABLED_COUNTRIES.add("UK")


def test_uk_pa_taper_disabled_by_default():
    # ZP-TAX-UK-2026-27-001 §5.1: HMRC bakes any real taper into the code
    # itself — the full parsed allowance now survives regardless of income,
    # with no independent recompute at all, as the shipped default.
    from app.modules.payroll.engine.countries.uk import _calculate_annual_tax_uk
    annual_gross = Decimal("120000")
    tax = _calculate_annual_tax_uk(annual_gross, UK_SLABS, UK_RATES)
    taxable = annual_gross - Decimal("12570")
    expected = Decimal("37700") * Decimal("0.20") + (taxable - Decimal("37700")) * Decimal("0.40")
    assert tax == expected


def test_uk_pa_taper_setting_never_affects_a_k_code():
    # A K-code's negative allowance has nothing to taper either way — the
    # setting must be a genuine no-op for it, in both directions.
    from app.modules.payroll.engine.countries import shared as shared_module
    from app.modules.payroll.engine.countries.uk import _calculate_annual_tax_uk
    annual_gross = Decimal("120000")
    enabled_result = _calculate_annual_tax_uk(annual_gross, UK_SLABS, UK_RATES, tax_code="K475")
    shared_module._UK_NO_INDEPENDENT_PA_TAPER_ENABLED_COUNTRIES.discard("UK")
    try:
        disabled_result = _calculate_annual_tax_uk(annual_gross, UK_SLABS, UK_RATES, tax_code="K475")
    finally:
        shared_module._UK_NO_INDEPENDENT_PA_TAPER_ENABLED_COUNTRIES.add("UK")
    assert enabled_result == disabled_result


def test_uk_k_code_uncapped_if_explicitly_reverted():
    # Phase 2 shipped 2026-09-07: _UK_K_CODE_50PCT_CAP_ENABLED_COUNTRIES now
    # defaults to {"UK"}. The old, superseded uncapped behavior remains
    # reachable only by explicitly discarding "UK" from the set.
    from app.modules.payroll.engine.countries import shared as shared_module
    shared_module._UK_K_CODE_50PCT_CAP_ENABLED_COUNTRIES.discard("UK")
    try:
        result = calc("UK", 1000, UK_RATES, UK_SLABS, tax_code="K2000")
        assert result.tds == Decimal("533.33")
    finally:
        shared_module._UK_K_CODE_50PCT_CAP_ENABLED_COUNTRIES.add("UK")


def test_uk_k_code_50pct_cap_applies_by_default():
    # ZP-TAX-UK-2026-27-001 §6.2: capped at 50% of THIS PERIOD'S pre-tax pay.
    result = calc("UK", 1000, UK_RATES, UK_SLABS, tax_code="K2000")
    assert result.tds == Decimal("500.00")


def test_uk_k_code_cap_pct_configurable():
    # Was a bare inline Decimal("0.5") until moved to hardcoded_defaults.py's
    # k_code_cap_pct — a Super Admin-configured row must actually change the
    # cap, not just the unconfigured default.
    configured_rates = {**UK_RATES, "k_code_cap_pct": Rate(employee_rate_pct=Decimal("30"))}
    result = calc("UK", 1000, UK_RATES, UK_SLABS, tax_code="K2000")
    configured_result = calc("UK", 1000, configured_rates, UK_SLABS, tax_code="K2000")
    assert result.tds == Decimal("500.00")       # default 50% cap
    assert configured_result.tds == Decimal("300.00")  # configured 30% cap


def test_uk_k_code_cap_is_noop_when_comfortably_under_50pct():
    # A cap, not a recompute — must not change an already-under-50% figure,
    # in either direction.
    from app.modules.payroll.engine.countries import shared as shared_module
    enabled_result = calc("UK", 5000, UK_RATES, UK_SLABS, tax_code="K100")
    shared_module._UK_K_CODE_50PCT_CAP_ENABLED_COUNTRIES.discard("UK")
    try:
        disabled_result = calc("UK", 5000, UK_RATES, UK_SLABS, tax_code="K100")
    finally:
        shared_module._UK_K_CODE_50PCT_CAP_ENABLED_COUNTRIES.add("UK")
    assert enabled_result.tds == disabled_result.tds


def test_uk_ni_direct_period_calc_diverges_from_annualize_then_divide():
    # ZP-TAX-UK-2026-27-001 §8.1's real Monthly PT/UEL/ST (£1,048/£4,189/
    # £417) don't derive from the annual figures by division (£12,570/12
    # = £1,047.50, not £1,048) — so even under perfectly uniform monthly
    # pay, annualize-then-divide and true per-period calculation diverge.
    # _UK_NI_DIRECT_PERIOD_CALC_ENABLED_COUNTRIES defaults to {"UK"} since
    # Phase 4 (2026-09-07) — the direct-period result is the shipped default.
    from app.modules.payroll.engine.countries import shared as shared_module
    enabled_result = calc("UK", 1048, UK_RATES, UK_SLABS, pay_frequency="Monthly")
    shared_module._UK_NI_DIRECT_PERIOD_CALC_ENABLED_COUNTRIES.discard("UK")
    try:
        disabled_result = calc("UK", 1048, UK_RATES, UK_SLABS, pay_frequency="Monthly")
    finally:
        shared_module._UK_NI_DIRECT_PERIOD_CALC_ENABLED_COUNTRIES.add("UK")
    assert disabled_result.ni_employee == Decimal("0.04")
    assert enabled_result.ni_employee == Decimal("0.00")
    assert disabled_result.employer_ni == Decimal("94.70")
    assert enabled_result.employer_ni == Decimal("94.65")


def test_uk_ni_fortnightly_unaffected_by_direct_period_setting():
    # The document doesn't publish a Fortnightly table — that frequency
    # must keep today's annualize-then-divide fallback either way.
    from app.modules.payroll.engine.countries import shared as shared_module
    enabled_result = calc("UK", 2096, UK_RATES, UK_SLABS, pay_frequency="Fortnightly")
    shared_module._UK_NI_DIRECT_PERIOD_CALC_ENABLED_COUNTRIES.discard("UK")
    try:
        disabled_result = calc("UK", 2096, UK_RATES, UK_SLABS, pay_frequency="Fortnightly")
    finally:
        shared_module._UK_NI_DIRECT_PERIOD_CALC_ENABLED_COUNTRIES.add("UK")
    assert enabled_result.ni_employee == disabled_result.ni_employee
    assert enabled_result.employer_ni == disabled_result.employer_ni


def test_uk_round_down_pound_helper_matches_hmrc_rule():
    from app.modules.payroll.engine.countries.uk import _round_down_pound
    assert _round_down_pound(Decimal("68.34")) == Decimal("68")
    assert _round_down_pound(Decimal("68.00")) == Decimal("68")
    assert _round_down_pound(Decimal("68.99")) == Decimal("68")


def test_uk_student_loan_penny_rounding_if_explicitly_reverted():
    # Phase 5 shipped 2026-09-07: _UK_STUDENT_LOAN_ROUND_DOWN_ENABLED_COUNTRIES
    # now defaults to {"UK"}. The old, superseded penny-rounding behavior
    # remains reachable only by explicitly discarding "UK".
    from app.modules.payroll.engine.countries import shared as shared_module
    shared_module._UK_STUDENT_LOAN_ROUND_DOWN_ENABLED_COUNTRIES.discard("UK")
    try:
        result = calc("UK", 3001, UK_RATES, UK_SLABS, study_loan_plan="UK_PLAN1", study_loan_balance=Decimal("1000"))
        assert result.study_loan_deduction == Decimal("68.34")
    finally:
        shared_module._UK_STUDENT_LOAN_ROUND_DOWN_ENABLED_COUNTRIES.add("UK")


def test_uk_student_loan_rounds_down_to_pound_by_default():
    # ZP-TAX-UK-2026-27-001 §10.2: round down to the nearest whole pound.
    result = calc("UK", 3001, UK_RATES, UK_SLABS, study_loan_plan="UK_PLAN1", study_loan_balance=Decimal("1000"))
    assert result.study_loan_deduction == Decimal("68")


# ── UK production refactor: NI category bands (regression guard) ───────

_NI_CAT_A_BANDS = [
    Slab(Decimal("0"), Decimal("5000"), Decimal("0"), rule_type="NI_BAND"),
    Slab(Decimal("5000"), Decimal("12570"), Decimal("0"), rule_type="NI_BAND"),
    Slab(Decimal("12570"), Decimal("50270"), Decimal("8"), rule_type="NI_BAND"),
    Slab(Decimal("50270"), None, Decimal("2"), rule_type="NI_BAND"),
]
# employer_rate_pct/ni_category are not Slab dataclass fields (kept
# engine-only rather than editing the shared test dataclass used by every
# other country's tests) -- set via setattr to mirror the live-DB row shape.
for _band, _empr in zip(_NI_CAT_A_BANDS, [Decimal("0"), Decimal("15"), Decimal("15"), Decimal("15")]):
    _band.employer_rate_pct = _empr
    _band.ni_category = "A"


def test_ni_category_a_bands_match_flat_calculation_exactly():
    # The banded representation is additive (Section D) -- for Category A
    # specifically, it must reproduce today's flat ContributionRate-based
    # NI figures exactly, since the band boundaries are the union of the
    # employee (PT/UEL) and employer (ST) thresholds.
    # _UK_NI_CATEGORY_BANDS_ENABLED_COUNTRIES defaults to {"UK"} since
    # Phase 3 (2026-09-07) — no toggling needed, this is the shipped default.
    # Uses Fortnightly explicitly: Phase 4's direct-period NI calc (also
    # enabled by default) only touches Weekly/Monthly on the FLAT path,
    # leaving the banded path's own frequency-awareness a disclosed
    # follow-up — so Monthly would now show a small, expected divergence
    # between the two paths that isn't what this test exists to check.
    flat_result = calc("UK", 5000, UK_RATES, UK_SLABS, pay_frequency="Fortnightly")
    banded_result = calc("UK", 5000, UK_RATES, UK_SLABS + _NI_CAT_A_BANDS, ni_category="A", pay_frequency="Fortnightly")
    assert banded_result.ni_employee == flat_result.ni_employee
    assert banded_result.employer_ni == flat_result.employer_ni


def test_ni_bands_ignored_without_a_category_set():
    with_bands_no_category = calc("UK", 5000, UK_RATES, UK_SLABS + _NI_CAT_A_BANDS)
    flat_result = calc("UK", 5000, UK_RATES, UK_SLABS)
    assert with_bands_no_category.ni_employee == flat_result.ni_employee


def test_resolve_ni_bands_returns_empty_if_explicitly_reverted():
    # Phase 3 shipped 2026-09-07: _UK_NI_CATEGORY_BANDS_ENABLED_COUNTRIES now
    # defaults to {"UK"}. The old, superseded "always flat, ignore real
    # bands" behavior remains reachable only by explicitly discarding "UK".
    from app.modules.payroll.engine.countries import shared as shared_module
    shared_module._UK_NI_CATEGORY_BANDS_ENABLED_COUNTRIES.discard("UK")
    try:
        bands = _resolve_ni_bands(_NI_CAT_A_BANDS, "A")
        assert bands == []
    finally:
        shared_module._UK_NI_CATEGORY_BANDS_ENABLED_COUNTRIES.add("UK")


def test_resolve_ni_bands_filters_by_category_and_sorts():
    other_category = Slab(Decimal("0"), None, Decimal("0"), rule_type="NI_BAND")
    other_category.ni_category = "B"
    other_category.employer_rate_pct = Decimal("0")
    all_slabs = _NI_CAT_A_BANDS + [other_category]
    bands = _resolve_ni_bands(all_slabs, "A")
    assert len(bands) == 4
    assert [b.min_amount for b in bands] == [Decimal("0"), Decimal("5000"), Decimal("12570"), Decimal("50270")]


def test_calculate_ni_from_bands_matches_hand_calculation():
    annual_gross = Decimal("60000")
    employee_annual, employer_annual = _calculate_ni_from_bands(annual_gross, _NI_CAT_A_BANDS)
    # Employee: (50270-12570)*8% + (60000-50270)*2% = 3016 + 194.60 = 3210.60
    assert employee_annual == Decimal("3210.60")
    # Employer: (60000-5000)*15% = 8250.00
    assert employer_annual == Decimal("8250.00")


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


# ── ZP-TAX-UK-2026-27-001 gap closure: tax-code region prefix ───────────

def test_tax_code_scottish_prefix_detected_and_allowance_still_parsed():
    result = interpret_tax_code("S1257L", Decimal("12570"))
    assert result["region_prefix"] == "S"
    assert result["personal_allowance"] == Decimal("12570")


def test_tax_code_welsh_prefix_detected_and_allowance_still_parsed():
    result = interpret_tax_code("C1257L", Decimal("12570"))
    assert result["region_prefix"] == "C"
    assert result["personal_allowance"] == Decimal("12570")


def test_tax_code_plain_code_has_no_region_prefix():
    assert interpret_tax_code("1257L", Decimal("12570"))["region_prefix"] is None


def test_tax_code_nt_never_carries_a_region_prefix():
    # Section 6.1: "NT is not given S/C prefix; treat as UK-wide code."
    assert interpret_tax_code("NT", Decimal("12570"))["region_prefix"] is None


def test_tax_code_scottish_k_code_prefix_and_allowance_both_parsed():
    result = interpret_tax_code("SK475", Decimal("12570"))
    assert result["region_prefix"] == "S"
    assert result["personal_allowance"] == Decimal("-4750")


def test_tax_code_0t_zero_allowance_no_flat_rate():
    result = interpret_tax_code("0T", Decimal("12570"))
    assert result["personal_allowance"] == Decimal("0")
    assert result["flat_rate_pct"] is None
    assert result["region_prefix"] is None


def test_tax_code_c0t_zero_allowance_with_welsh_prefix():
    result = interpret_tax_code("C0T", Decimal("12570"))
    assert result["personal_allowance"] == Decimal("0")
    assert result["region_prefix"] == "C"


# ── ZP-TAX-UK-2026-27-001 section 6.3: special single-rate code families ──

def test_tax_code_sbr_is_flat_20pct_with_scottish_prefix():
    result = interpret_tax_code("SBR", Decimal("12570"))
    assert result["flat_rate_pct"] == Decimal("20")
    assert result["region_prefix"] == "S"


def test_tax_code_sd0_is_flat_21pct_scottish_intermediate():
    # Distinct from rUK's D0 (40%) -- confirms the full code, not the
    # stripped body, is what selects the rate.
    result = interpret_tax_code("SD0", Decimal("12570"))
    assert result["flat_rate_pct"] == Decimal("21")
    assert result["region_prefix"] == "S"


def test_tax_code_sd1_is_flat_42pct_scottish_higher():
    assert interpret_tax_code("SD1", Decimal("12570"))["flat_rate_pct"] == Decimal("42")


def test_tax_code_sd2_is_flat_45pct_scottish_advanced():
    assert interpret_tax_code("SD2", Decimal("12570"))["flat_rate_pct"] == Decimal("45")


def test_tax_code_sd3_is_flat_48pct_scottish_top():
    assert interpret_tax_code("SD3", Decimal("12570"))["flat_rate_pct"] == Decimal("48")


def test_tax_code_cbr_is_flat_20pct_with_welsh_prefix():
    result = interpret_tax_code("CBR", Decimal("12570"))
    assert result["flat_rate_pct"] == Decimal("20")
    assert result["region_prefix"] == "C"


def test_tax_code_cd0_is_flat_40pct():
    assert interpret_tax_code("CD0", Decimal("12570"))["flat_rate_pct"] == Decimal("40")


def test_tax_code_cd1_is_flat_45pct():
    assert interpret_tax_code("CD1", Decimal("12570"))["flat_rate_pct"] == Decimal("45")


# ── ZP-TAX-UK-2026-27-001 section 10.1: corrected 2026-27 thresholds ─────

def test_uk_student_loan_plan1_2026_27_threshold_is_26900():
    from app.modules.payroll.engine.countries.uk import _UK_STUDENT_LOAN_PLANS
    assert _UK_STUDENT_LOAN_PLANS["UK_PLAN1"][0] == Decimal("26900")


def test_uk_student_loan_plan2_2026_27_threshold_is_29385():
    from app.modules.payroll.engine.countries.uk import _UK_STUDENT_LOAN_PLANS
    assert _UK_STUDENT_LOAN_PLANS["UK_PLAN2"][0] == Decimal("29385")


def test_uk_student_loan_plan4_2026_27_threshold_is_33795():
    from app.modules.payroll.engine.countries.uk import _UK_STUDENT_LOAN_PLANS
    assert _UK_STUDENT_LOAN_PLANS["UK_PLAN4"][0] == Decimal("33795")


def test_uk_student_loan_plan4_threshold_now_configurable():
    # Section 10.1 -- Plan 4 previously had no ContributionRate override
    # key at all; sl_plan4_thresh closes that gap.
    default_result = calc("UK", 5000, UK_RATES, UK_SLABS, study_loan_plan="UK_PLAN4", study_loan_balance=Decimal("20000"))
    configured_rates = {**UK_RATES, "sl_plan4_thresh": Rate(flat_amount=Decimal("10000"))}
    configured_result = calc("UK", 5000, configured_rates, UK_SLABS, study_loan_plan="UK_PLAN4", study_loan_balance=Decimal("20000"))
    assert configured_result.study_loan_deduction > default_result.study_loan_deduction


# ── ZP-TAX-UK-2026-27-001 section 22.2: official reference NIC vectors ───
# Weekly earnings £1,000, using the doc's own worked examples (not
# hand-derived) -- proves the corrected ST=£5,000/employer-15% defaults
# against an authoritative external result, not just internal consistency.

_CAT_A_WEEKLY_BANDS = [
    Slab(Decimal("0"), Decimal("96"), Decimal("0"), rule_type="NI_BAND"),
    Slab(Decimal("96"), Decimal("242"), Decimal("0"), rule_type="NI_BAND"),
    Slab(Decimal("242"), Decimal("967"), Decimal("8"), rule_type="NI_BAND"),
    Slab(Decimal("967"), None, Decimal("2"), rule_type="NI_BAND"),
]
for _b, _er in zip(_CAT_A_WEEKLY_BANDS, [Decimal("0"), Decimal("15"), Decimal("15"), Decimal("15")]):
    _b.employer_rate_pct = _er
    _b.ni_category = "A"


def test_reference_vector_category_a_weekly_1000():
    employee_annual, employer_annual = _calculate_ni_from_bands(Decimal("1000"), _CAT_A_WEEKLY_BANDS)
    assert employee_annual == Decimal("58.66")
    assert employer_annual == Decimal("135.60")


_CAT_M_WEEKLY_BANDS = [
    Slab(Decimal("0"), Decimal("242"), Decimal("0"), rule_type="NI_BAND"),
    Slab(Decimal("242"), Decimal("967"), Decimal("8"), rule_type="NI_BAND"),
    Slab(Decimal("967"), None, Decimal("2"), rule_type="NI_BAND"),
]
for _b, _er in zip(_CAT_M_WEEKLY_BANDS, [Decimal("0"), Decimal("0"), Decimal("15")]):
    _b.employer_rate_pct = _er
    _b.ni_category = "M"


def test_reference_vector_category_m_weekly_1000():
    employee_annual, employer_annual = _calculate_ni_from_bands(Decimal("1000"), _CAT_M_WEEKLY_BANDS)
    assert employee_annual == Decimal("58.66")
    assert employer_annual == Decimal("4.95")


_CAT_C_WEEKLY_BANDS = [
    Slab(Decimal("0"), Decimal("96"), Decimal("0"), rule_type="NI_BAND"),
    Slab(Decimal("96"), None, Decimal("0"), rule_type="NI_BAND"),
]
for _b, _er in zip(_CAT_C_WEEKLY_BANDS, [Decimal("0"), Decimal("15")]):
    _b.employer_rate_pct = _er
    _b.ni_category = "C"


def test_reference_vector_category_c_weekly_1000():
    employee_annual, employer_annual = _calculate_ni_from_bands(Decimal("1000"), _CAT_C_WEEKLY_BANDS)
    assert employee_annual == Decimal("0")
    assert employer_annual == Decimal("135.60")


# ── ZP-TAX-UK-2026-27-001 AC-04: tax-code prefix beats work_state ────────

def test_region_resolution_prefers_tax_code_prefix_over_work_state():
    from app.modules.payroll.service import _resolve_uk_sub_jurisdiction_with_source
    # Employee's own worksite says England, but their HMRC code says
    # Scotland -- the code must win (the doc's non-negotiable control).
    sub_jurisdiction, source = _resolve_uk_sub_jurisdiction_with_source("S1257L", "England")
    assert sub_jurisdiction == "Scotland"
    assert source == "TAX_CODE_PREFIX"


def test_region_resolution_falls_back_to_work_state_without_a_code():
    from app.modules.payroll.service import _resolve_uk_sub_jurisdiction_with_source
    sub_jurisdiction, source = _resolve_uk_sub_jurisdiction_with_source(None, "Scotland")
    assert sub_jurisdiction == "Scotland"
    assert source == "WORK_STATE_FALLBACK"


def test_region_resolution_welsh_prefix_overrides_english_work_state():
    from app.modules.payroll.service import _resolve_uk_sub_jurisdiction_with_source
    sub_jurisdiction, source = _resolve_uk_sub_jurisdiction_with_source("C1257L", "England")
    assert sub_jurisdiction == "Wales"
    assert source == "TAX_CODE_PREFIX"
