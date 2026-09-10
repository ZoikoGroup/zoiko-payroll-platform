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
from datetime import date
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


# 2026-09-09 gap-closure Phase 1: the repayment RATE (9%/6%) was the one
# hardcoded-with-no-override-path figure in _UK_STUDENT_LOAN_PLANS — the
# threshold half of each tuple already had a configurable path (above).

def test_uk_student_loan_plan1_rate_configurable():
    default_result = calc("UK", 5000, UK_RATES, UK_SLABS, study_loan_plan="UK_PLAN1", study_loan_balance=Decimal("20000"))
    configured_rates = {**UK_RATES, "sl_plan1_rate": Rate(employee_rate_pct=Decimal("20"))}
    configured_result = calc("UK", 5000, configured_rates, UK_SLABS, study_loan_plan="UK_PLAN1", study_loan_balance=Decimal("20000"))
    assert configured_result.study_loan_deduction > default_result.study_loan_deduction


def test_uk_postgrad_loan_rate_configurable():
    default_result = calc("UK", 5000, UK_RATES, UK_SLABS, study_loan_plan="UK_POSTGRAD", study_loan_balance=Decimal("20000"))
    configured_rates = {**UK_RATES, "pg_loan_rate": Rate(employee_rate_pct=Decimal("15"))}
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


# 2026-09-09 gap-closure Phase 1: each flat-rate code's % used to be a
# bare Python-dict lookup with no rate_map row consulted at all — the
# only UK figure left with no Super-Admin override path after the
# K-code-cap fix (2026-09-07). A configured row must actually change tds.

def test_interpret_tax_code_br_rate_configurable_via_rate_map():
    rate_map = {"flat_br_pct": Rate(employee_rate_pct=Decimal("15"))}
    result = interpret_tax_code("BR", Decimal("12570"), rate_map)
    assert result["flat_rate_pct"] == Decimal("15")


def test_interpret_tax_code_flat_rate_falls_back_without_rate_map():
    # Every existing direct caller (the tests above) passes only 2
    # positional args -- must keep resolving to the hardcoded default.
    result = interpret_tax_code("BR", Decimal("12570"))
    assert result["flat_rate_pct"] == Decimal("20")


def test_uk_flat_rate_code_br_pct_configurable():
    default_result = calc("UK", 5000, UK_RATES, UK_SLABS, tax_code="BR")
    configured_rates = {**UK_RATES, "flat_br_pct": Rate(employee_rate_pct=Decimal("10"))}
    configured_result = calc("UK", 5000, configured_rates, UK_SLABS, tax_code="BR")
    assert default_result.tds == Decimal("1000.00")
    assert configured_result.tds == Decimal("500.00")


def test_uk_flat_rate_code_sd0_pct_configurable():
    # Scottish SD0 (21%) — proves the fix covers the S-prefixed family too,
    # not just the plain BR/D0/D1 codes.
    default_result = calc("UK", 5000, UK_RATES, UK_SLABS, tax_code="SD0")
    configured_rates = {**UK_RATES, "flat_sd0_pct": Rate(employee_rate_pct=Decimal("5"))}
    configured_result = calc("UK", 5000, configured_rates, UK_SLABS, tax_code="SD0")
    assert default_result.tds == Decimal("1050.00")
    assert configured_result.tds == Decimal("250.00")


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


def test_uk_ni_monthly_primary_threshold_configurable():
    # 2026-09-09 gap-closure Phase 1: the Weekly/Monthly direct-period NI
    # thresholds had NO database override path at all — a Super Admin
    # could edit every other UK figure except these. Lowering the
    # Monthly Primary Threshold must actually raise ni_employee.
    default_result = calc("UK", 1048, UK_RATES, UK_SLABS, pay_frequency="Monthly")
    configured_rates = {**UK_RATES, "ni_pt_thresh_mo": Rate(flat_amount=Decimal("500"))}
    configured_result = calc("UK", 1048, configured_rates, UK_SLABS, pay_frequency="Monthly")
    assert default_result.ni_employee == Decimal("0.00")
    assert configured_result.ni_employee == Decimal("43.84")


def test_uk_ni_weekly_secondary_threshold_configurable():
    default_result = calc("UK", 300, UK_RATES, UK_SLABS, pay_frequency="Weekly")
    configured_rates = {**UK_RATES, "ni_st_thresh_wk": Rate(flat_amount=Decimal("50"))}
    configured_result = calc("UK", 300, configured_rates, UK_SLABS, pay_frequency="Weekly")
    assert configured_result.employer_ni > default_result.employer_ni


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


# ── Weekly/Monthly NI_BAND direct-period variant (found 2026-09-10 on a ──
# fresh document re-read: the banded path above always annualizes first,
# which can miss the document's own reference vectors by a penny —
# £242 weekly PT x 52 = £12,584, not the real annual PT £12,570) ─────────

def _make_period_ni_category_a_bands(rule_type):
    bands = [
        Slab(Decimal("0"), Decimal("96"), Decimal("0"), rule_type=rule_type),
        Slab(Decimal("96"), Decimal("242"), Decimal("0"), rule_type=rule_type),
        Slab(Decimal("242"), Decimal("967"), Decimal("8"), rule_type=rule_type),
        Slab(Decimal("967"), None, Decimal("2"), rule_type=rule_type),
    ]
    for b, er in zip(bands, [Decimal("0"), Decimal("15"), Decimal("15"), Decimal("15")]):
        b.employer_rate_pct = er
        b.ni_category = "A"
    return bands


def test_weekly_ni_band_variant_reproduces_document_reference_vector_exactly():
    """Through the REAL engine (not just the pure band-math helper): with
    a genuine NI_BAND_WEEKLY variant present, Category A at £1,000/week
    must match the document's published £58.66/£135.60 exactly — proving
    the annualize-then-divide path's penny drift is gone once real
    per-period bands exist."""
    weekly_bands = _make_period_ni_category_a_bands("NI_BAND_WEEKLY")
    result = calc("UK", 1000, {}, weekly_bands, pay_frequency="Weekly", ni_category="A", tax_code="NT")
    assert result.ni_employee == Decimal("58.66")
    assert result.employer_ni == Decimal("135.60")


def test_annual_ni_band_path_unchanged_without_a_period_variant():
    """The existing annual-band-then-divide behavior (with its known,
    disclosed penny-level drift for Weekly/Monthly) is completely
    unaffected when no NI_BAND_WEEKLY/MONTHLY rows exist — this is the
    exact pre-existing behavior, not a regression."""
    annual_bands = [
        Slab(Decimal("0"), Decimal("5000"), Decimal("0"), rule_type="NI_BAND"),
        Slab(Decimal("5000"), Decimal("12570"), Decimal("0"), rule_type="NI_BAND"),
        Slab(Decimal("12570"), Decimal("50270"), Decimal("8"), rule_type="NI_BAND"),
        Slab(Decimal("50270"), None, Decimal("2"), rule_type="NI_BAND"),
    ]
    for b, er in zip(annual_bands, [Decimal("0"), Decimal("15"), Decimal("15"), Decimal("15")]):
        b.employer_rate_pct = er
        b.ni_category = "A"
    result = calc("UK", 1000, {}, annual_bands, pay_frequency="Weekly", ni_category="A", tax_code="NT")
    assert result.ni_employee == Decimal("58.67")  # the known drift, unchanged
    assert result.employer_ni == Decimal("135.58")


def test_monthly_ni_band_variant_takes_precedence_over_annual():
    """Both an annual NI_BAND and a NI_BAND_MONTHLY variant present for
    the same category — Monthly pay must use the period-specific variant,
    not silently fall back to the annual one."""
    monthly_bands = [
        Slab(Decimal("0"), Decimal("417"), Decimal("0"), rule_type="NI_BAND_MONTHLY"),
        Slab(Decimal("417"), Decimal("1048"), Decimal("0"), rule_type="NI_BAND_MONTHLY"),
        Slab(Decimal("1048"), Decimal("4189"), Decimal("8"), rule_type="NI_BAND_MONTHLY"),
        Slab(Decimal("4189"), None, Decimal("2"), rule_type="NI_BAND_MONTHLY"),
    ]
    annual_bands = [
        Slab(Decimal("0"), Decimal("5000"), Decimal("0"), rule_type="NI_BAND"),
        Slab(Decimal("5000"), Decimal("12570"), Decimal("0"), rule_type="NI_BAND"),
        Slab(Decimal("12570"), Decimal("50270"), Decimal("8"), rule_type="NI_BAND"),
        Slab(Decimal("50270"), None, Decimal("2"), rule_type="NI_BAND"),
    ]
    for b, er in zip(monthly_bands + annual_bands, [Decimal("0"), Decimal("15"), Decimal("15"), Decimal("15")] * 2):
        b.employer_rate_pct = er
        b.ni_category = "A"
    result_monthly_variant = calc("UK", 4333, {}, monthly_bands + annual_bands, pay_frequency="Monthly", ni_category="A", tax_code="NT")
    result_annual_only = calc("UK", 4333, {}, annual_bands, pay_frequency="Monthly", ni_category="A", tax_code="NT")
    # Different threshold boundaries (monthly £1,048/£4,189 vs annual/12
    # £1,047.50/£4,189.17) produce a genuinely different result — proving
    # the monthly-specific table, not the annual one, actually drove it.
    assert result_monthly_variant.ni_employee != result_annual_only.ni_employee or result_monthly_variant.employer_ni != result_annual_only.employer_ni


def test_period_ni_bands_fail_closed_for_unpublished_frequencies():
    """Fortnightly/FourWeekly have no published per-period table (same
    scope boundary as the flat direct-period path) — a NI_BAND_WEEKLY
    row must never be silently reused for Fortnightly pay."""
    from app.modules.payroll.engine.countries.uk import _resolve_ni_bands_by_frequency
    weekly_bands = _make_period_ni_category_a_bands("NI_BAND_WEEKLY")
    result = _resolve_ni_bands_by_frequency(weekly_bands, "A", "Fortnightly")
    assert result == []


# ── Bug found live 2026-09-10: NI_BAND_WEEKLY/MONTHLY leaking into the ────
# income-tax bracket sum. income_slabs/state_income_slabs in uk.py's
# calculate() only excluded literal rule_type "NI_BAND" — once the two
# per-frequency variants above existed in the same live pack (as they now
# do), every NI band row for every category got silently summed in as an
# extra income-tax bracket, inflating a real £952.67/month PAYE figure
# (£5,000 gross, tax code 1257L) to £2,722.88. Caught only by running the
# real engine against real canonical data, not by any prior unit test —
# every existing NI-band-frequency test above builds a slabs list with NO
# separate MARGINAL_RATE rows in it, so it could never have exposed this.

def test_ni_band_monthly_rows_do_not_inflate_income_tax():
    marginal_rate_only = [
        Slab(Decimal("0"), Decimal("37700"), Decimal("20"), rule_type="MARGINAL_RATE"),
        Slab(Decimal("37700"), None, Decimal("40"), rule_type="MARGINAL_RATE"),
    ]
    monthly_ni_bands = _make_period_ni_category_a_bands("NI_BAND_MONTHLY")

    tax_only_result = calc("UK", 5000, {}, marginal_rate_only, pay_frequency="Monthly", ni_category="A", tax_code="1257L")
    combined_result = calc("UK", 5000, {}, marginal_rate_only + monthly_ni_bands, pay_frequency="Monthly", ni_category="A", tax_code="1257L")

    assert combined_result.tds == tax_only_result.tds
    # £5,000/month, tax code 1257L: (£50,270-£37,700 wait — annual gross
    # £60,000, PA £12,570, taxable £47,430) 20% to £37,700 + 40% above =
    # £7,540 + £3,892 = £11,432/year = £952.67/month.
    assert combined_result.tds == Decimal("952.67")


def test_ni_band_weekly_rows_excluded_from_shared_bracket_calculator_directly():
    """Second layer of defense: _calculate_annual_tax itself (shared.py)
    must never treat an NI_BAND/NI_BAND_WEEKLY/NI_BAND_MONTHLY row as an
    income-tax bracket, even if a future caller forgets to pre-filter —
    exactly the mistake that caused the live bug above."""
    from app.modules.payroll.engine.countries.shared import _calculate_annual_tax
    marginal_rate_only = [
        Slab(Decimal("0"), Decimal("37700"), Decimal("20"), rule_type="MARGINAL_RATE"),
        Slab(Decimal("37700"), None, Decimal("40"), rule_type="MARGINAL_RATE"),
    ]
    contaminated = marginal_rate_only + _make_period_ni_category_a_bands("NI_BAND_WEEKLY") + [
        Slab(Decimal("0"), Decimal("5000"), Decimal("0"), rule_type="NI_BAND"),
    ]
    assert _calculate_annual_tax(Decimal("47430"), contaminated) == _calculate_annual_tax(Decimal("47430"), marginal_rate_only)


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


# ── NI category derivation from relief-eligibility facts (ZP-TAX-UK- ────
# 2026-27-001 §8.2/§9.1/§9.3 gap-closure Part 2, 2026-09-09) ─────────────

def test_derive_ni_category_returns_none_without_date_of_birth():
    from app.modules.payroll.engine.countries.uk import derive_ni_category
    facts = [{"relief_type": "FREEPORT", "effective_from": date(2026, 1, 1), "effective_to": None}]
    assert derive_ni_category(None, date(2026, 6, 1), facts, {}) is None


def test_derive_ni_category_returns_none_with_no_active_facts():
    from app.modules.payroll.engine.countries.uk import derive_ni_category
    assert derive_ni_category(date(1990, 1, 1), date(2026, 6, 1), [], {}) is None
    # A fact that hasn't started yet is not active.
    future_fact = [{"relief_type": "FREEPORT", "effective_from": date(2027, 1, 1), "effective_to": None}]
    assert derive_ni_category(date(1990, 1, 1), date(2026, 6, 1), future_fact, {}) is None
    # A fact that already ended is not active.
    expired_fact = [{"relief_type": "FREEPORT", "effective_from": date(2020, 1, 1), "effective_to": date(2025, 12, 31)}]
    assert derive_ni_category(date(1990, 1, 1), date(2026, 6, 1), expired_fact, {}) is None


def test_derive_ni_category_freeport_standard():
    from app.modules.payroll.engine.countries.uk import derive_ni_category
    facts = [{"relief_type": "FREEPORT", "effective_from": date(2026, 1, 1), "effective_to": None}]
    assert derive_ni_category(date(1990, 1, 1), date(2026, 6, 1), facts, {}) == "F"


def test_derive_ni_category_freeport_at_state_pension_age():
    from app.modules.payroll.engine.countries.uk import derive_ni_category
    facts = [{"relief_type": "FREEPORT", "effective_from": date(2026, 1, 1), "effective_to": None}]
    # Turns 66 (the default state pension age) exactly on the pay date.
    assert derive_ni_category(date(1960, 6, 1), date(2026, 6, 1), facts, {}) == "S"


def test_derive_ni_category_investment_zone_standard_and_spa():
    from app.modules.payroll.engine.countries.uk import derive_ni_category
    facts = [{"relief_type": "INVESTMENT_ZONE", "effective_from": date(2026, 1, 1), "effective_to": None}]
    assert derive_ni_category(date(1990, 1, 1), date(2026, 6, 1), facts, {}) == "N"
    assert derive_ni_category(date(1955, 1, 1), date(2026, 6, 1), facts, {}) == "K"


def test_derive_ni_category_state_pension_age_without_a_site():
    from app.modules.payroll.engine.countries.uk import derive_ni_category
    facts = [{"relief_type": "VETERAN", "effective_from": date(2026, 1, 1), "effective_to": None}]
    # Even with an active veteran fact, State Pension age takes precedence.
    assert derive_ni_category(date(1955, 1, 1), date(2026, 6, 1), facts, {}) == "C"


def test_derive_ni_category_qualifying_veteran():
    from app.modules.payroll.engine.countries.uk import derive_ni_category
    facts = [{"relief_type": "VETERAN", "effective_from": date(2026, 1, 1), "effective_to": date(2026, 12, 31)}]
    assert derive_ni_category(date(1985, 1, 1), date(2026, 6, 1), facts, {}) == "V"
    # Outside the 12-month qualifying window, the fact is no longer active.
    assert derive_ni_category(date(1985, 1, 1), date(2027, 6, 1), facts, {}) is None


def test_derive_ni_category_apprentice_under_25():
    from app.modules.payroll.engine.countries.uk import derive_ni_category
    facts = [{"relief_type": "APPRENTICE", "effective_from": date(2026, 1, 1), "effective_to": None}]
    assert derive_ni_category(date(2003, 1, 1), date(2026, 6, 1), facts, {}) == "H"  # 23 years old
    # An apprentice who has since turned 25 falls through to standard/under-21 logic.
    assert derive_ni_category(date(1998, 1, 1), date(2026, 6, 1), facts, {}) is None  # 28 years old


def test_derive_ni_category_under_21_standard():
    from app.modules.payroll.engine.countries.uk import derive_ni_category
    # Under 21 alone has no relief fact to trigger derivation at all (it
    # isn't one of the 4 derivable relief types) — this proves the
    # "no active facts -> None" contract, not an under-21 code path.
    assert derive_ni_category(date(2008, 1, 1), date(2026, 6, 1), [], {}) is None


def test_derive_ni_category_veteran_takes_precedence_over_apprentice():
    from app.modules.payroll.engine.countries.uk import derive_ni_category
    facts = [
        {"relief_type": "VETERAN", "effective_from": date(2026, 1, 1), "effective_to": date(2026, 12, 31)},
        {"relief_type": "APPRENTICE", "effective_from": date(2026, 1, 1), "effective_to": None},
    ]
    assert derive_ni_category(date(2003, 1, 1), date(2026, 6, 1), facts, {}) == "V"


def test_derive_ni_category_state_pension_age_configurable():
    from app.modules.payroll.engine.countries.uk import derive_ni_category
    facts = [{"relief_type": "VETERAN", "effective_from": date(2026, 1, 1), "effective_to": date(2026, 12, 31)}]
    # Turns 64 on the pay date — below the default SPA (66), so VETERAN
    # would normally win; lowering the configured SPA to 64 must change
    # the outcome to "C".
    dob = date(1962, 6, 1)
    default_result = derive_ni_category(dob, date(2026, 6, 1), facts, {})
    assert default_result == "V"
    configured_rates = {"state_pension_age": Rate(flat_amount=Decimal("64"))}
    configured_result = derive_ni_category(dob, date(2026, 6, 1), facts, configured_rates)
    assert configured_result == "C"


# ── Automatic Enrolment assessment (ZP-TAX-UK-2026-27-001 §13/Layer 5 ────
# gap-closure Part 3, 2026-09-09) ────────────────────────────────────────

def test_assess_auto_enrolment_eligible_jobholder():
    from app.modules.payroll.engine.countries.uk import assess_auto_enrolment
    assert assess_auto_enrolment(30, Decimal("30000"), {}) == "ELIGIBLE_JOBHOLDER"


def test_assess_auto_enrolment_non_eligible_when_under_22_but_above_trigger():
    from app.modules.payroll.engine.countries.uk import assess_auto_enrolment
    assert assess_auto_enrolment(21, Decimal("30000"), {}) == "NON_ELIGIBLE_JOBHOLDER"


def test_assess_auto_enrolment_non_eligible_when_at_or_above_state_pension_age():
    from app.modules.payroll.engine.countries.uk import assess_auto_enrolment
    assert assess_auto_enrolment(67, Decimal("30000"), {}) == "NON_ELIGIBLE_JOBHOLDER"


def test_assess_auto_enrolment_non_eligible_between_lower_qe_and_trigger():
    from app.modules.payroll.engine.countries.uk import assess_auto_enrolment
    # £8,000/year is above the £6,240 lower qualifying earnings threshold
    # but at/below the £10,000 trigger.
    assert assess_auto_enrolment(30, Decimal("8000"), {}) == "NON_ELIGIBLE_JOBHOLDER"


def test_assess_auto_enrolment_exactly_at_trigger_is_non_eligible_not_eligible():
    from app.modules.payroll.engine.countries.uk import assess_auto_enrolment
    # "Above £10,000" per §13.1 — exactly at the trigger does not qualify.
    assert assess_auto_enrolment(30, Decimal("10000"), {}) == "NON_ELIGIBLE_JOBHOLDER"


def test_assess_auto_enrolment_entitled_worker_below_lower_qe():
    from app.modules.payroll.engine.countries.uk import assess_auto_enrolment
    assert assess_auto_enrolment(30, Decimal("5000"), {}) == "ENTITLED_WORKER"


def test_assess_auto_enrolment_exactly_at_lower_qe_is_entitled_worker():
    from app.modules.payroll.engine.countries.uk import assess_auto_enrolment
    assert assess_auto_enrolment(30, Decimal("6240"), {}) == "ENTITLED_WORKER"


def test_assess_auto_enrolment_none_without_age():
    from app.modules.payroll.engine.countries.uk import assess_auto_enrolment
    assert assess_auto_enrolment(None, Decimal("30000"), {}) is None


def test_assess_auto_enrolment_none_outside_16_to_74_age_range():
    from app.modules.payroll.engine.countries.uk import assess_auto_enrolment
    assert assess_auto_enrolment(15, Decimal("30000"), {}) is None
    assert assess_auto_enrolment(75, Decimal("30000"), {}) is None


def test_assess_auto_enrolment_thresholds_configurable():
    from app.modules.payroll.engine.countries.uk import assess_auto_enrolment
    default_result = assess_auto_enrolment(30, Decimal("9000"), {})
    assert default_result == "NON_ELIGIBLE_JOBHOLDER"
    configured_rates = {"pension_ae_trigger": Rate(flat_amount=Decimal("8000"))}
    configured_result = assess_auto_enrolment(30, Decimal("9000"), configured_rates)
    assert configured_result == "ELIGIBLE_JOBHOLDER"


def test_uk_calculate_includes_auto_enrolment_status_when_enabled():
    """UK — enabled by default since 2026-09-10 (see shared.py); still
    force-set here (save/restore, not blind add/discard) so this test
    passes regardless of the current default."""
    from app.modules.payroll.engine.countries import shared as shared_module
    was_enabled = "UK" in shared_module._UK_AUTO_ENROLMENT_ASSESSMENT_ENABLED_COUNTRIES
    shared_module._UK_AUTO_ENROLMENT_ASSESSMENT_ENABLED_COUNTRIES.add("UK")
    try:
        result = calc("UK", 5000, UK_RATES, UK_SLABS, date_of_birth=date(1995, 1, 1), pay_date=date(2026, 6, 1))
    finally:
        if not was_enabled:
            shared_module._UK_AUTO_ENROLMENT_ASSESSMENT_ENABLED_COUNTRIES.discard("UK")
    assert result.auto_enrolment_status == "ELIGIBLE_JOBHOLDER"


def test_uk_calculate_auto_enrolment_status_none_when_switch_off():
    """A deployment that deliberately discards "UK" from this switch must
    still get None — replaces the old dormant-by-default version of this
    test now that UK is enabled by default (2026-09-10)."""
    from app.modules.payroll.engine.countries import shared as shared_module
    was_enabled = "UK" in shared_module._UK_AUTO_ENROLMENT_ASSESSMENT_ENABLED_COUNTRIES
    shared_module._UK_AUTO_ENROLMENT_ASSESSMENT_ENABLED_COUNTRIES.discard("UK")
    try:
        result = calc("UK", 5000, UK_RATES, UK_SLABS, date_of_birth=date(1995, 1, 1), pay_date=date(2026, 6, 1))
    finally:
        if was_enabled:
            shared_module._UK_AUTO_ENROLMENT_ASSESSMENT_ENABLED_COUNTRIES.add("UK")
    assert result.auto_enrolment_status is None


def test_uk_calculate_auto_enrolment_status_never_changes_pension_deduction():
    from app.modules.payroll.engine.countries import shared as shared_module
    was_enabled = "UK" in shared_module._UK_AUTO_ENROLMENT_ASSESSMENT_ENABLED_COUNTRIES
    shared_module._UK_AUTO_ENROLMENT_ASSESSMENT_ENABLED_COUNTRIES.discard("UK")
    try:
        without_switch = calc("UK", 5000, UK_RATES, UK_SLABS, date_of_birth=date(1995, 1, 1), pay_date=date(2026, 6, 1))
    finally:
        if was_enabled:
            shared_module._UK_AUTO_ENROLMENT_ASSESSMENT_ENABLED_COUNTRIES.add("UK")
    shared_module._UK_AUTO_ENROLMENT_ASSESSMENT_ENABLED_COUNTRIES.add("UK")
    try:
        with_switch = calc("UK", 5000, UK_RATES, UK_SLABS, date_of_birth=date(1995, 1, 1), pay_date=date(2026, 6, 1))
    finally:
        if not was_enabled:
            shared_module._UK_AUTO_ENROLMENT_ASSESSMENT_ENABLED_COUNTRIES.discard("UK")
    assert without_switch.employee_pension == with_switch.employee_pension
    assert without_switch.employer_pension == with_switch.employer_pension


# ── Mileage Allowance Payments & Advisory Fuel Rates (ZP-TAX-UK-2026-27- ─
# 001 §16 gap-closure Part 4, 2026-09-09) ────────────────────────────────

_UK_MILEAGE_RATES = {
    "mileage_car_first_10k": Rate(flat_amount=Decimal("0.55")),
    "mileage_car_after_10k": Rate(flat_amount=Decimal("0.25")),
    "mileage_car_ni": Rate(flat_amount=Decimal("0.55")),
    "mileage_motorcycle": Rate(flat_amount=Decimal("0.24")),
    "mileage_cycle": Rate(flat_amount=Decimal("0.20")),
}


def test_mileage_motorcycle_flat_rate():
    from app.modules.payroll.engine.countries.uk import calculate_mileage_reimbursement
    result = calculate_mileage_reimbursement("MOTORCYCLE", Decimal("100"), None, _UK_MILEAGE_RATES)
    assert result["eligible"] is True
    assert result["tax_free_amount"] == Decimal("24.00")
    assert result["ni_free_amount"] == Decimal("24.00")


def test_mileage_cycle_flat_rate():
    from app.modules.payroll.engine.countries.uk import calculate_mileage_reimbursement
    result = calculate_mileage_reimbursement("CYCLE", Decimal("50"), None, _UK_MILEAGE_RATES)
    assert result["tax_free_amount"] == Decimal("10.00")
    assert result["ni_free_amount"] == Decimal("10.00")


def test_mileage_car_entirely_within_first_10000_miles():
    from app.modules.payroll.engine.countries.uk import calculate_mileage_reimbursement
    result = calculate_mileage_reimbursement("CAR", Decimal("1000"), Decimal("0"), _UK_MILEAGE_RATES)
    # 1000 * 0.55 = 550.00 for both tax and NI (still within the threshold)
    assert result["tax_free_amount"] == Decimal("550.00")
    assert result["ni_free_amount"] == Decimal("550.00")


def test_mileage_car_entirely_past_10000_miles_diverges_tax_from_ni():
    from app.modules.payroll.engine.countries.uk import calculate_mileage_reimbursement
    result = calculate_mileage_reimbursement("CAR", Decimal("1000"), Decimal("10000"), _UK_MILEAGE_RATES)
    # Already at the threshold — all 1000 miles at the after-10k tax rate (25p),
    # but the NI-approved rate never steps down (55p for all miles).
    assert result["tax_free_amount"] == Decimal("250.00")
    assert result["ni_free_amount"] == Decimal("550.00")


def test_mileage_car_straddling_the_10000_mile_threshold():
    from app.modules.payroll.engine.countries.uk import calculate_mileage_reimbursement
    # 9,500 miles already claimed this year; this claim is 1,000 more —
    # 500 miles at 55p (up to 10,000) + 500 miles at 25p (the excess).
    result = calculate_mileage_reimbursement("CAR", Decimal("1000"), Decimal("9500"), _UK_MILEAGE_RATES)
    expected_tax = Decimal("500") * Decimal("0.55") + Decimal("500") * Decimal("0.25")
    assert result["tax_free_amount"] == expected_tax
    assert result["ni_free_amount"] == Decimal("1000") * Decimal("0.55")


def test_mileage_unknown_vehicle_type_not_eligible():
    from app.modules.payroll.engine.countries.uk import calculate_mileage_reimbursement
    result = calculate_mileage_reimbursement("SCOOTER", Decimal("100"), None, _UK_MILEAGE_RATES)
    assert result["eligible"] is False


def test_mileage_fails_closed_when_unconfigured():
    from app.modules.payroll.engine.countries.uk import calculate_mileage_reimbursement
    result = calculate_mileage_reimbursement("MOTORCYCLE", Decimal("100"), None, {})
    assert result["eligible"] is False
    assert "not configured" in result["reason"]


_UK_AFR_RATES = {
    "afr_petrol_le1400": Rate(flat_amount=Decimal("0.14")),
    "afr_diesel_1601_2000": Rate(flat_amount=Decimal("0.17")),
    "afr_electric_home": Rate(flat_amount=Decimal("0.07")),
    "afr_electric_public": Rate(flat_amount=Decimal("0.15")),
}


def test_resolve_advisory_fuel_rate_petrol():
    from app.modules.payroll.engine.countries.uk import resolve_advisory_fuel_rate
    result = resolve_advisory_fuel_rate("PETROL", "LE_1400", _UK_AFR_RATES)
    assert result["eligible"] is True
    assert result["rate_per_mile"] == Decimal("0.14")


def test_resolve_advisory_fuel_rate_diesel_uses_its_own_bands():
    from app.modules.payroll.engine.countries.uk import resolve_advisory_fuel_rate
    result = resolve_advisory_fuel_rate("DIESEL", "1601_2000", _UK_AFR_RATES)
    assert result["rate_per_mile"] == Decimal("0.17")


def test_resolve_advisory_fuel_rate_electric_by_charger_type():
    from app.modules.payroll.engine.countries.uk import resolve_advisory_fuel_rate
    home = resolve_advisory_fuel_rate("ELECTRIC", "HOME", _UK_AFR_RATES)
    public = resolve_advisory_fuel_rate("ELECTRIC", "PUBLIC", _UK_AFR_RATES)
    assert home["rate_per_mile"] == Decimal("0.07")
    assert public["rate_per_mile"] == Decimal("0.15")


def test_resolve_advisory_fuel_rate_unknown_combination():
    from app.modules.payroll.engine.countries.uk import resolve_advisory_fuel_rate
    result = resolve_advisory_fuel_rate("PETROL", "LE_1600", _UK_AFR_RATES)  # diesel's band, not petrol's
    assert result["eligible"] is False


def test_resolve_advisory_fuel_rate_fails_closed_when_unconfigured():
    from app.modules.payroll.engine.countries.uk import resolve_advisory_fuel_rate
    result = resolve_advisory_fuel_rate("PETROL", "GT_2000", {})
    assert result["eligible"] is False
    assert "not configured" in result["reason"]


# ── National Minimum Wage compliance validation (ZP-TAX-UK-2026-27-001 ──
# §15 gap-closure Part 5, 2026-09-09) ────────────────────────────────────

_UK_NMW_RATES = {
    "nmw_age_21_plus": Rate(flat_amount=Decimal("12.71")),
    "nmw_age_18_20": Rate(flat_amount=Decimal("10.85")),
    "nmw_under_18": Rate(flat_amount=Decimal("8.00")),
    "nmw_apprentice_under_19": Rate(flat_amount=Decimal("8.00")),
    "nmw_apprentice_19plus_yr1": Rate(flat_amount=Decimal("8.00")),
}


def test_resolve_nmw_rate_age_21_plus():
    from app.modules.payroll.engine.countries.uk import resolve_nmw_rate
    result = resolve_nmw_rate(25, False, None, date(2026, 6, 1), _UK_NMW_RATES)
    assert result["eligible"] is True
    assert result["rate_per_hour"] == Decimal("12.71")


def test_resolve_nmw_rate_age_18_to_20():
    from app.modules.payroll.engine.countries.uk import resolve_nmw_rate
    result = resolve_nmw_rate(19, False, None, date(2026, 6, 1), _UK_NMW_RATES)
    assert result["rate_per_hour"] == Decimal("10.85")


def test_resolve_nmw_rate_under_18():
    from app.modules.payroll.engine.countries.uk import resolve_nmw_rate
    result = resolve_nmw_rate(17, False, None, date(2026, 6, 1), _UK_NMW_RATES)
    assert result["rate_per_hour"] == Decimal("8.00")


def test_resolve_nmw_rate_apprentice_under_19_regardless_of_apprenticeship_length():
    from app.modules.payroll.engine.countries.uk import resolve_nmw_rate
    # No apprenticeship_start_date at all -- an under-19 apprentice always
    # gets the apprentice rate, not time-limited like the 19+ case.
    result = resolve_nmw_rate(18, True, None, date(2026, 6, 1), _UK_NMW_RATES)
    assert result["rate_per_hour"] == Decimal("8.00")


def test_resolve_nmw_rate_apprentice_19plus_first_year():
    from app.modules.payroll.engine.countries.uk import resolve_nmw_rate
    result = resolve_nmw_rate(22, True, date(2026, 1, 1), date(2026, 6, 1), _UK_NMW_RATES)
    assert result["rate_per_hour"] == Decimal("8.00")


def test_resolve_nmw_rate_apprentice_19plus_after_first_year_reverts_to_age_band():
    from app.modules.payroll.engine.countries.uk import resolve_nmw_rate
    # Apprenticeship started more than 365 days before the as_of date.
    result = resolve_nmw_rate(22, True, date(2024, 1, 1), date(2026, 6, 1), _UK_NMW_RATES)
    assert result["rate_per_hour"] == Decimal("12.71")


def test_resolve_nmw_rate_none_without_age():
    from app.modules.payroll.engine.countries.uk import resolve_nmw_rate
    result = resolve_nmw_rate(None, False, None, date(2026, 6, 1), _UK_NMW_RATES)
    assert result["eligible"] is False


def test_validate_nmw_compliance_compliant():
    from app.modules.payroll.engine.countries.uk import validate_nmw_compliance
    # 160 hours at exactly the 21+ rate -> fully compliant, no shortfall.
    pay = Decimal("12.71") * 160
    result = validate_nmw_compliance(pay, Decimal("160"), 25, False, None, date(2026, 6, 1), _UK_NMW_RATES)
    assert result["eligible"] is True
    assert result["compliant"] is True
    assert result["shortfall_amount"] == Decimal("0")


def test_validate_nmw_compliance_underpaid_reports_shortfall():
    from app.modules.payroll.engine.countries.uk import validate_nmw_compliance
    # Paid £10/hour equivalent for 160 hours (£1,600) but the 21+ rate is
    # £12.71 -> shortfall = (12.71*160) - 1600.
    result = validate_nmw_compliance(Decimal("1600"), Decimal("160"), 25, False, None, date(2026, 6, 1), _UK_NMW_RATES)
    assert result["compliant"] is False
    assert result["effective_hourly_rate"] == Decimal("10.00")
    expected_shortfall = (Decimal("12.71") * 160) - Decimal("1600")
    assert result["shortfall_amount"] == expected_shortfall.quantize(Decimal("0.01"))


def test_validate_nmw_compliance_fails_closed_with_zero_hours():
    from app.modules.payroll.engine.countries.uk import validate_nmw_compliance
    result = validate_nmw_compliance(Decimal("1000"), Decimal("0"), 25, False, None, date(2026, 6, 1), _UK_NMW_RATES)
    assert result["eligible"] is False


def test_validate_nmw_compliance_fails_closed_when_rate_unconfigured():
    from app.modules.payroll.engine.countries.uk import validate_nmw_compliance
    result = validate_nmw_compliance(Decimal("1000"), Decimal("100"), 25, False, None, date(2026, 6, 1), {})
    assert result["eligible"] is False


# ── Tax-week/month calendar + week 53/54/56 (ZP-TAX-UK-2026-27-001 §7.2/ ─
# §18.1 gap-closure Part 6, 2026-09-09) ──────────────────────────────────

def test_resolve_uk_tax_week_and_month_week_1_starts_6_april():
    from app.modules.payroll.engine.countries.uk import resolve_uk_tax_week_and_month
    result = resolve_uk_tax_week_and_month(date(2026, 4, 6))
    assert result["tax_week"] == 1
    assert result["tax_month"] == 1
    assert result["tax_year_start"] == date(2026, 4, 6)
    assert result["tax_year_end"] == date(2027, 4, 5)


def test_resolve_uk_tax_week_and_month_day_before_new_tax_year_is_week_53():
    from app.modules.payroll.engine.countries.uk import resolve_uk_tax_week_and_month
    result = resolve_uk_tax_week_and_month(date(2027, 4, 5))
    assert result["tax_week"] == 53
    assert result["tax_year_start"] == date(2026, 4, 6)


def test_resolve_uk_tax_week_and_month_week_capped_at_53_even_in_leap_year():
    from app.modules.payroll.engine.countries.uk import resolve_uk_tax_week_and_month
    # 2027-28 tax year contains the 2028 leap day (29 Feb 2028), giving it
    # 366 days -> still must cap at week 53, never 54.
    result = resolve_uk_tax_week_and_month(date(2028, 4, 5))
    assert result["tax_week"] == 53
    assert result["tax_year_start"] == date(2027, 4, 6)


def test_resolve_uk_tax_week_and_month_week_7_starts_18_may():
    from app.modules.payroll.engine.countries.uk import resolve_uk_tax_week_and_month
    # Week 1: 6-12 Apr, Week 2: 13-19 Apr, ... Week 7: 18-24 May.
    result = resolve_uk_tax_week_and_month(date(2026, 5, 18))
    assert result["tax_week"] == 7


def test_resolve_uk_tax_week_and_month_tax_month_boundary_5th_vs_6th():
    from app.modules.payroll.engine.countries.uk import resolve_uk_tax_week_and_month
    assert resolve_uk_tax_week_and_month(date(2026, 5, 5))["tax_month"] == 1
    assert resolve_uk_tax_week_and_month(date(2026, 5, 6))["tax_month"] == 2


def test_resolve_uk_tax_week_and_month_tax_month_12_is_march():
    from app.modules.payroll.engine.countries.uk import resolve_uk_tax_week_and_month
    result = resolve_uk_tax_week_and_month(date(2027, 3, 10))
    assert result["tax_month"] == 12
    assert result["tax_year_start"] == date(2026, 4, 6)


def test_resolve_uk_tax_week_and_month_before_6_april_belongs_to_prior_tax_year():
    from app.modules.payroll.engine.countries.uk import resolve_uk_tax_week_and_month
    result = resolve_uk_tax_week_and_month(date(2026, 4, 5))
    assert result["tax_year_start"] == date(2025, 4, 6)
    assert result["tax_year_end"] == date(2026, 4, 5)


def test_detect_uk_extra_payday_weekly_period_53():
    from app.modules.payroll.engine.countries.uk import detect_uk_extra_payday
    result = detect_uk_extra_payday("Weekly", 53)
    assert result["is_extra_payday"] is True
    assert result["reporting_identifier"] == 53


def test_detect_uk_extra_payday_fortnightly_period_27():
    from app.modules.payroll.engine.countries.uk import detect_uk_extra_payday
    result = detect_uk_extra_payday("Fortnightly", 27)
    assert result["is_extra_payday"] is True
    assert result["reporting_identifier"] == 54


def test_detect_uk_extra_payday_four_weekly_period_14():
    from app.modules.payroll.engine.countries.uk import detect_uk_extra_payday
    result = detect_uk_extra_payday("FourWeekly", 14)
    assert result["is_extra_payday"] is True
    assert result["reporting_identifier"] == 56


def test_detect_uk_extra_payday_false_for_ordinary_period():
    from app.modules.payroll.engine.countries.uk import detect_uk_extra_payday
    result = detect_uk_extra_payday("Weekly", 30)
    assert result["is_extra_payday"] is False
    assert result["reporting_identifier"] is None


def test_detect_uk_extra_payday_monthly_has_no_extra_payday_concept():
    from app.modules.payroll.engine.countries.uk import detect_uk_extra_payday
    result = detect_uk_extra_payday("Monthly", 12)
    assert result["is_extra_payday"] is False
    assert result["reporting_identifier"] is None


def test_uk_calculate_includes_tax_week_and_month_unconditionally():
    # Part 6 is pure calendar metadata with zero calculation impact — no
    # rollout switch, always populated when a pay_date is present.
    result = calc("UK", 5000, UK_RATES, UK_SLABS, pay_date=date(2026, 6, 1))
    assert result.tax_week == 9
    assert result.tax_month == 2


def test_uk_calculate_tax_week_and_month_none_without_pay_date():
    result = calc("UK", 5000, UK_RATES, UK_SLABS)
    assert result.tax_week is None
    assert result.tax_month is None


def test_uk_calculate_tax_week_and_month_never_changes_net_pay():
    with_date = calc("UK", 5000, UK_RATES, UK_SLABS, pay_date=date(2026, 6, 1))
    without_date = calc("UK", 5000, UK_RATES, UK_SLABS)
    assert with_date.net_pay == without_date.net_pay


# ── Court-Ordered Deductions (ZP-TAX-UK-2026-27-001 §17 gap-closure ──────
# Part 8, 2026-09-09) ─────────────────────────────────────────────────────

def test_aeo_ew_fails_closed_with_no_order_specific_rate_and_no_band_table():
    from app.modules.payroll.engine.countries.uk import calculate_court_order_deduction_england_wales
    result = calculate_court_order_deduction_england_wales(Decimal("2000"), None, None, None, [])
    assert result["eligible"] is False
    assert "AEO_EW_STANDARD" in result["reason"]


def test_aeo_ew_order_specific_fixed_amount_takes_precedence_over_band_table():
    from app.modules.payroll.engine.countries.uk import calculate_court_order_deduction_england_wales
    band = Slab(min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("20"), rule_type="AEO_EW_STANDARD")
    result = calculate_court_order_deduction_england_wales(Decimal("2000"), None, Decimal("150"), None, [band])
    assert result["eligible"] is True
    assert result["deduction_amount"] == Decimal("150")


def test_aeo_ew_order_specific_rate_takes_precedence_over_band_table():
    from app.modules.payroll.engine.countries.uk import calculate_court_order_deduction_england_wales
    band = Slab(min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("20"), rule_type="AEO_EW_STANDARD")
    result = calculate_court_order_deduction_england_wales(Decimal("2000"), Decimal("10"), None, None, [band])
    assert result["eligible"] is True
    assert result["deduction_amount"] == Decimal("200.00")


def test_aeo_ew_fixed_amount_capped_by_protected_earnings_headroom():
    from app.modules.payroll.engine.countries.uk import calculate_court_order_deduction_england_wales
    result = calculate_court_order_deduction_england_wales(Decimal("2000"), None, Decimal("500"), Decimal("1800"), [])
    # headroom = 2000 - 1800 = 200, less than the fixed 500.
    assert result["eligible"] is True
    assert result["deduction_amount"] == Decimal("200")


def test_aeo_ew_uses_band_table_when_no_order_specific_value():
    from app.modules.payroll.engine.countries.uk import calculate_court_order_deduction_england_wales
    bands = [
        Slab(min_amount=Decimal("0"), max_amount=Decimal("1000"), rate_pct=Decimal("5"), rule_type="AEO_EW_STANDARD"),
        Slab(min_amount=Decimal("1000.01"), max_amount=None, rate_pct=Decimal("15"), rule_type="AEO_EW_STANDARD"),
    ]
    result = calculate_court_order_deduction_england_wales(Decimal("2000"), None, None, None, bands)
    assert result["eligible"] is True
    assert result["deduction_amount"] == Decimal("300.00")


def test_aeo_ew_ignores_bands_for_other_rule_types():
    from app.modules.payroll.engine.countries.uk import calculate_court_order_deduction_england_wales
    other = Slab(min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("20"), rule_type="ARREST_SCOT_WK")
    result = calculate_court_order_deduction_england_wales(Decimal("2000"), None, None, None, [other])
    assert result["eligible"] is False


def test_scottish_arrestment_fails_closed_for_unsupported_frequency():
    from app.modules.payroll.engine.countries.uk import calculate_court_order_deduction_scotland
    result = calculate_court_order_deduction_scotland(Decimal("2000"), "Daily", None, None, None, [])
    assert result["eligible"] is False
    assert "not defined" in result["reason"]


def test_scottish_arrestment_uses_frequency_specific_band_table():
    from app.modules.payroll.engine.countries.uk import calculate_court_order_deduction_scotland
    weekly_band = Slab(min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("10"), rule_type="ARREST_SCOT_WK")
    monthly_band = Slab(min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("25"), rule_type="ARREST_SCOT_MO")
    result = calculate_court_order_deduction_scotland(Decimal("1000"), "Weekly", None, None, None, [weekly_band, monthly_band])
    assert result["eligible"] is True
    assert result["deduction_amount"] == Decimal("100.00")


def test_scottish_arrestment_order_specific_rate_takes_precedence():
    from app.modules.payroll.engine.countries.uk import calculate_court_order_deduction_scotland
    result = calculate_court_order_deduction_scotland(Decimal("1000"), "Weekly", Decimal("12"), None, None, [])
    assert result["eligible"] is True
    assert result["deduction_amount"] == Decimal("120.00")


def test_northern_ireland_order_fails_closed_without_band_table():
    from app.modules.payroll.engine.countries.uk import calculate_court_order_deduction_northern_ireland
    result = calculate_court_order_deduction_northern_ireland(Decimal("2000"), None, None, None, [])
    assert result["eligible"] is False
    assert "AEO_NI_STANDARD" in result["reason"]


def test_northern_ireland_order_specific_amount_takes_precedence():
    from app.modules.payroll.engine.countries.uk import calculate_court_order_deduction_northern_ireland
    result = calculate_court_order_deduction_northern_ireland(Decimal("2000"), None, Decimal("80"), None, [])
    assert result["eligible"] is True
    assert result["deduction_amount"] == Decimal("80")


def test_calculate_court_ordered_deductions_applies_priority_sequentially():
    from app.modules.payroll.engine.countries.uk import calculate_court_ordered_deductions
    orders = [
        {"id": 1, "jurisdiction": "ENGLAND_WALES", "fixed_deduction_amount": Decimal("300"), "fixed_deduction_rate_pct": None, "protected_earnings_amount": None},
        {"id": 2, "jurisdiction": "ENGLAND_WALES", "fixed_deduction_amount": Decimal("1800"), "fixed_deduction_rate_pct": None, "protected_earnings_amount": None},
    ]
    result = calculate_court_ordered_deductions(orders, Decimal("2000"), "Monthly", [])
    # Order 1 takes 300, leaving 1700 remaining -> order 2's 1800 is capped at 1700.
    assert result["total_deduction"] == Decimal("2000.00")
    assert result["orders"][0]["deduction_amount"] == Decimal("300")
    assert result["orders"][1]["deduction_amount"] == Decimal("1700")


def test_calculate_court_ordered_deductions_reports_per_order_ineligibility():
    from app.modules.payroll.engine.countries.uk import calculate_court_ordered_deductions
    orders = [
        {"id": 1, "jurisdiction": "SCOTLAND", "fixed_deduction_amount": None, "fixed_deduction_rate_pct": None, "protected_earnings_amount": None},
    ]
    result = calculate_court_ordered_deductions(orders, Decimal("2000"), "Weekly", [])
    assert result["total_deduction"] == Decimal("0")
    assert result["orders"][0]["eligible"] is False
    assert result["orders"][0]["order_id"] == 1


def test_calculate_court_ordered_deductions_unknown_jurisdiction():
    from app.modules.payroll.engine.countries.uk import calculate_court_ordered_deductions
    orders = [
        {"id": 1, "jurisdiction": "WALES_ONLY", "fixed_deduction_amount": Decimal("100"), "fixed_deduction_rate_pct": None, "protected_earnings_amount": None},
    ]
    result = calculate_court_ordered_deductions(orders, Decimal("2000"), "Weekly", [])
    assert result["orders"][0]["eligible"] is False
    assert "unknown jurisdiction" in result["orders"][0]["reason"]
