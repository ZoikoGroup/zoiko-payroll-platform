"""
tests/test_engine_standard.py
------------------------------
Boundary/regression coverage for engine/standard.py's per-country
calculators (Phase 29): below/at/above threshold, bracket boundaries,
zero/high income, and the rate_map-parameter-with-fallback mechanism
Milestone 3 introduced (Super Admin can override a government constant;
absent that override, behavior is unchanged from the hardcoded default).
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

import pytest

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.standard import StandardStrategy, evaluate_tax_formula
from app.modules.payroll.engine.countries import canada as _canada
from app.modules.payroll.engine.countries.canada import _resolve_ca_bpaf
import app.modules.payroll.engine.countries.shared as shared


@dataclass
class Rate:
    """Minimal stand-in for a ContributionRate/TaxSlab row — only the
    attributes the engine actually reads."""
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
    filing_status: Optional[str] = None
    tax_regime: Optional[str] = None


@dataclass
class EmployerTaxProfileStub:
    """Minimal stand-in for models.EmployerTaxProfile — only the
    attributes engine/countries/us.py actually reads."""
    taxable_wage_base: Decimal = Decimal("7000")
    employer_rate_pct: Decimal = Decimal("3.4")


@dataclass
class LocalityRateStub:
    """Minimal stand-in for models.LocalityRate — only the attributes
    engine/countries/us.py actually reads."""
    resident_rate_pct: Optional[Decimal] = None
    nonresident_rate_pct: Optional[Decimal] = None
    flat_amount: Optional[Decimal] = None


STRATEGY = StandardStrategy()


def calc(country, gross, rate_map=None, slabs=None, basic=None, w4_filing_status=None, employer_tax_profiles=None,
         state_slabs=None, reciprocity_suppresses_work_state=False, resident_state_slabs=None, locality_rate=None,
         work_state=None, state_rate_map=None, td1_claim_amount=None, td1_additional_tax=None,
         cpp_qpp_election_status=None, ytd_pensionable_earnings=None, ytd_cpp2_pensionable_earnings=None,
         ytd_insurable_earnings=None, ytd_basic_exemption_used=None,
         provincial_td1_claim_amount=None, qc_tp1015_claim_amount=None,
         on_eht_ytd_remuneration_before=None, bc_eht_ytd_remuneration_before=None,
         mb_he_levy_ytd_remuneration_before=None, nl_hapset_ytd_remuneration_before=None,
         bc_eht_employer_classification=None, qc_hsf_ytd_remuneration_before=None,
         qc_hsf_employer_category=None, date_of_birth=None, pay_date=None,
         lsvcc_investment_amount=None):
    ctx = PayrollContext(
        gross=Decimal(gross), basic=Decimal(basic if basic is not None else gross),
        country=country, rate_map=rate_map or {}, slabs=slabs or [],
        w4_filing_status=w4_filing_status, employer_tax_profiles=employer_tax_profiles or {},
        state_slabs=state_slabs or [],
        reciprocity_suppresses_work_state=reciprocity_suppresses_work_state,
        resident_state_slabs=resident_state_slabs or [],
        locality_rate=locality_rate,
        work_state=work_state, state_rate_map=state_rate_map or {},
        td1_claim_amount=td1_claim_amount, td1_additional_tax=td1_additional_tax,
        cpp_qpp_election_status=cpp_qpp_election_status,
        ytd_pensionable_earnings=ytd_pensionable_earnings, ytd_cpp2_pensionable_earnings=ytd_cpp2_pensionable_earnings,
        ytd_insurable_earnings=ytd_insurable_earnings, ytd_basic_exemption_used=ytd_basic_exemption_used,
        provincial_td1_claim_amount=provincial_td1_claim_amount, qc_tp1015_claim_amount=qc_tp1015_claim_amount,
        on_eht_ytd_remuneration_before=on_eht_ytd_remuneration_before,
        bc_eht_ytd_remuneration_before=bc_eht_ytd_remuneration_before,
        mb_he_levy_ytd_remuneration_before=mb_he_levy_ytd_remuneration_before,
        nl_hapset_ytd_remuneration_before=nl_hapset_ytd_remuneration_before,
        bc_eht_employer_classification=bc_eht_employer_classification,
        qc_hsf_ytd_remuneration_before=qc_hsf_ytd_remuneration_before,
        qc_hsf_employer_category=qc_hsf_employer_category,
        date_of_birth=date_of_birth, pay_date=pay_date,
        lsvcc_investment_amount=lsvcc_investment_amount,
    )
    return STRATEGY.calculate(ctx)


# ── India ────────────────────────────────────────────────────────────────

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


def test_india_esi_applies_below_ceiling():
    result = calc("IN", 20000, IN_RATES, IN_SLABS)
    assert result.employee_esi > 0


def test_india_esi_not_applicable_above_ceiling():
    result = calc("IN", 21001, IN_RATES, IN_SLABS)
    assert result.employee_esi == 0


def test_india_esi_ceiling_override_via_rate_map():
    rates = dict(IN_RATES, esi_wage_ceiling=Rate(flat_amount=Decimal("30000")))
    result = calc("IN", 25000, rates, IN_SLABS)
    assert result.employee_esi > 0  # would be 0 under the default 21000 ceiling


def test_india_zero_income():
    result = calc("IN", 0, IN_RATES, IN_SLABS)
    assert result.net_pay == 0
    assert result.tds == 0


def test_india_pt_is_flat():
    result = calc("IN", 100000, IN_RATES, IN_SLABS)
    assert result.professional_tax == Decimal("200")


def test_india_87a_rebate_zeroes_tax_at_low_income():
    result = calc("IN", 50000, IN_RATES, IN_SLABS)  # well under standard deduction + rebate limit
    assert result.tds == 0


def test_india_high_income_taxed():
    result = calc("IN", 300000, IN_RATES, IN_SLABS)
    assert result.tds > 0


IN_OLD_REGIME_SLABS = [
    Slab(Decimal("0"),       Decimal("250000"),  Decimal("0"),  tax_regime="Old"),
    Slab(Decimal("250000"),  Decimal("500000"),  Decimal("5"),  tax_regime="Old"),
    Slab(Decimal("500000"),  Decimal("1000000"), Decimal("20"), tax_regime="Old"),
    Slab(Decimal("1000000"), None,                Decimal("30"), tax_regime="Old"),
]


def test_india_old_regime_uses_old_regime_brackets_not_new_regime_ones():
    # ₹18,00,000 annual (above both regimes' 87A rebate ceiling, so the
    # comparison isn't swamped to zero by the rebate): New Regime's ₹75k
    # standard deduction + 0/400k/800k brackets vs Old Regime's ₹50k
    # deduction + steeper 5/20/30% brackets starting at ₹2.5L must produce
    # genuinely different tax, proving the OLD table (not the new one) is
    # what actually got consumed once service.py hands the engine an
    # already-disambiguated Old-regime slab list — ctx.tax_regime="Old" is
    # set directly since the calc() helper doesn't expose it.
    from app.modules.payroll.engine.base import PayrollContext as _PC
    old_ctx = _PC(gross=Decimal("150000"), basic=Decimal("150000"), country="IN",
                  rate_map=IN_RATES, slabs=IN_OLD_REGIME_SLABS, tax_regime="Old")
    new_ctx = _PC(gross=Decimal("150000"), basic=Decimal("150000"), country="IN",
                  rate_map=IN_RATES, slabs=IN_SLABS)
    old_result = STRATEGY.calculate(old_ctx)
    new_result = STRATEGY.calculate(new_ctx)
    assert old_result.tds != new_result.tds
    assert old_result.tds > new_result.tds  # old regime's steeper brackets + lower deduction


def test_india_old_regime_standard_deduction_and_rebate_still_apply():
    # ctx.tax_regime is threaded separately from ctx.slabs — PayrollContext
    # doesn't expose tax_regime via the calc() helper's slabs arg, so this
    # confirms _calculate_annual_tax_in's own is_old branch (₹50k std ded,
    # ₹12,500/₹5L rebate) still nets to zero tax for a low old-regime
    # income even when handed the real old-regime bracket table.
    ctx_kwargs = dict(country="IN", gross=Decimal("40000"), basic=Decimal("40000"),
                       rate_map=IN_RATES, slabs=IN_OLD_REGIME_SLABS)
    from app.modules.payroll.engine.base import PayrollContext as _PC
    ctx = _PC(**ctx_kwargs, tax_regime="Old")
    result = STRATEGY.calculate(ctx)
    assert result.tds == 0


def test_india_pf_wage_ceiling_dormant_by_default():
    # ₹30,000 Basic, no ceiling applied by default — PF on the full amount.
    result = calc("IN", 30000, IN_RATES, IN_SLABS, basic=30000)
    assert result.employee_pf == Decimal("3600.00")  # 12% of 30,000 uncapped


def test_india_pf_wage_ceiling_applies_when_enabled():
    shared._IN_PF_WAGE_CEILING_ENABLED_COUNTRIES.add("IN")
    result = calc("IN", 30000, IN_RATES, IN_SLABS, basic=30000)
    assert result.employee_pf == Decimal("1800.00")  # 12% of the ₹15,000 ceiling, not 30,000
    assert result.employer_pf == Decimal("1800.00")


def test_india_pf_wage_ceiling_configurable_via_rate_map():
    shared._IN_PF_WAGE_CEILING_ENABLED_COUNTRIES.add("IN")
    rates = dict(IN_RATES, pf_wage_ceiling=Rate(flat_amount=Decimal("25000")))
    result = calc("IN", 30000, rates, IN_SLABS, basic=30000)
    assert result.employee_pf == Decimal("3000.00")  # 12% of the overridden ₹25,000 ceiling


def test_india_pf_wage_ceiling_does_not_affect_basic_below_ceiling():
    shared._IN_PF_WAGE_CEILING_ENABLED_COUNTRIES.add("IN")
    result = calc("IN", 10000, IN_RATES, IN_SLABS, basic=10000)
    assert result.employee_pf == Decimal("1200.00")  # 12% of 10,000 — below the ceiling, unaffected


# ── United States ────────────────────────────────────────────────────────

US_RATES = {
    "social-security": Rate("social-security", Decimal("6.20"), Decimal("6.20")),
    "medicare": Rate("medicare", Decimal("1.45"), Decimal("1.45")),
}
US_SLABS = [
    Slab(Decimal("0"), Decimal("11925"), Decimal("10")),
    Slab(Decimal("11925"), Decimal("48475"), Decimal("12")),
    Slab(Decimal("48475"), None, Decimal("22")),
]


def test_us_social_security_below_wage_base():
    result = calc("US", 5000, US_RATES, US_SLABS)  # $60k/yr, under $176,100 base
    assert result.social_security == pytest.approx(Decimal("310.00"), abs=Decimal("0.01"))


def test_us_social_security_capped_at_wage_base():
    result = calc("US", 30000, US_RATES, US_SLABS)  # $360k/yr, well above the wage base
    annual_ss = result.social_security * 12
    assert annual_ss < Decimal("360000") * Decimal("0.062")  # capped, not linear


def test_us_medicare_additional_above_threshold():
    below = calc("US", Decimal("16000"), US_RATES, US_SLABS)   # $192k/yr — under $200k
    above = calc("US", Decimal("18000"), US_RATES, US_SLABS)   # $216k/yr — over $200k
    below_rate = below.medicare / (Decimal("16000"))
    above_rate = above.medicare / (Decimal("18000"))
    assert above_rate > below_rate  # additional 0.9% kicked in


def test_us_wage_base_override_via_rate_map():
    rates = dict(US_RATES, ss_wage_base=Rate(flat_amount=Decimal("50000")))
    result = calc("US", 10000, rates, US_SLABS)  # $120k/yr, over the overridden $50k base
    default_result = calc("US", 10000, US_RATES, US_SLABS)
    assert result.social_security < default_result.social_security


def test_us_zero_income():
    result = calc("US", 0, US_RATES, US_SLABS)
    assert result.net_pay == 0


def test_us_federal_state_local_split_sums_to_tds():
    """New fields (Phase 2 of the US blueprint): federal/state/local tax are
    broken out separately for display, but tds must remain their sum — no
    existing caller that reads tds as one combined number should see a
    different total than before this split existed."""
    result = calc("US", 8000, US_RATES, US_SLABS)
    assert result.local_tax == Decimal("0")  # not yet wired — see engine/countries/us.py
    assert result.tds == pytest.approx(
        result.federal_income_tax + result.state_income_tax + result.local_tax, abs=Decimal("0.01")
    )


def test_us_filing_status_no_tagged_slabs_is_a_no_op():
    """No slab in the table carries a filing_status at all — passing
    w4_filing_status must produce IDENTICAL federal tax to not passing one.
    This is the core backward-compatibility guarantee: every existing
    country's slabs (and today's US slabs) are untagged, so this parameter
    must never change their result."""
    without = calc("US", 10000, US_RATES, US_SLABS)
    with_mfj = calc("US", 10000, US_RATES, US_SLABS, w4_filing_status="MFJ")
    assert with_mfj.federal_income_tax == without.federal_income_tax


def test_us_filing_status_selects_matching_bracket_table():
    """Once Super Admin configures separate Single- and MFJ-tagged bracket
    tables, an employee's own w4_filing_status must select the matching
    one — not the other, and not a blend of both."""
    tagged_slabs = [
        Slab(Decimal("0"), None, Decimal("10"), filing_status="SINGLE"),
        Slab(Decimal("0"), None, Decimal("22"), filing_status="MFJ"),
    ]
    single_result = calc("US", 10000, US_RATES, tagged_slabs, w4_filing_status="SINGLE")
    mfj_result = calc("US", 10000, US_RATES, tagged_slabs, w4_filing_status="MFJ")
    assert single_result.federal_income_tax < mfj_result.federal_income_tax
    # Flat-rate tables (0-and-above at 10% vs 22%) on identical taxable
    # income: the MFJ table's tax should be exactly 22/10 = 2.2x the Single
    # table's, up to rounding.
    assert mfj_result.federal_income_tax == pytest.approx(single_result.federal_income_tax * Decimal("2.2"), abs=Decimal("0.02"))


def test_us_futa_full_rate_when_no_sui_profile_configured():
    """No EmployerTaxProfile at all (every org today) — FUTA must compute
    at the full 6.0% statutory rate, exactly as before SUI/credit wiring
    existed. This is the core regression guard for this feature."""
    result = calc("US", 5000, US_RATES, US_SLABS)  # $60k/yr, well above the $7,000 FUTA wage base
    assert result.employer_sui == Decimal("0")
    # Full 6.0% of the $7,000 wage base, annualized then monthly.
    assert result.employer_futa == pytest.approx(Decimal("35.00"), abs=Decimal("0.01"))


def test_us_sui_computed_and_futa_credit_applied_when_profile_exists():
    """Once a real EmployerTaxProfile exists for this employer/state, SUI
    is computed from it directly, and FUTA drops to the standard
    post-credit ~0.6% effective rate — never inferred, only when Super
    Admin has actually configured the profile."""
    profiles = {"SUI": EmployerTaxProfileStub(taxable_wage_base=Decimal("7000"), employer_rate_pct=Decimal("3.4"))}
    result = calc("US", 5000, US_RATES, US_SLABS, employer_tax_profiles=profiles)
    # SUI: 3.4% of $7,000 / 12
    assert result.employer_sui == pytest.approx(Decimal("19.83"), abs=Decimal("0.01"))
    # FUTA: (6.0% - 5.4%) = 0.6% of $7,000 / 12
    assert result.employer_futa == pytest.approx(Decimal("3.50"), abs=Decimal("0.01"))


def test_us_futa_credit_reduction_configurable_via_rate_map():
    """A Super-Admin-configured futa_credit_red_pct (state-scoped) must
    reduce the effective credit — simulating a credit-reduction state —
    without any hardcoded list of which states those are."""
    profiles = {"SUI": EmployerTaxProfileStub()}
    rates = dict(US_RATES, futa_credit_red_pct=Rate(flat_amount=Decimal("0.6")))
    reduced = calc("US", 5000, rates, US_SLABS, employer_tax_profiles=profiles)
    normal = calc("US", 5000, US_RATES, US_SLABS, employer_tax_profiles=profiles)
    assert reduced.employer_futa > normal.employer_futa
    # Effective rate becomes 6.0 - 5.4 + 0.6 = 1.2% instead of 0.6%.
    assert reduced.employer_futa == pytest.approx(normal.employer_futa * 2, abs=Decimal("0.01"))


def test_us_reciprocity_off_uses_work_state_slabs():
    """No reciprocity flagged (every employee today) — state income tax
    must come from work-state slabs, exactly as before reciprocity
    existed. Core regression guard."""
    work_slabs = [Slab(Decimal("0"), None, Decimal("5"))]
    resident_slabs = [Slab(Decimal("0"), None, Decimal("3"))]
    result = calc("US", 10000, US_RATES, US_SLABS, state_slabs=work_slabs, resident_state_slabs=resident_slabs)
    # 5% work-state table, not the 3% resident one.
    assert result.state_income_tax == pytest.approx(Decimal("500.00"), abs=Decimal("0.01"))


def test_us_reciprocity_on_uses_resident_state_slabs_instead():
    """Once reciprocity is flagged as suppressing work-state withholding,
    the RESIDENT state's slabs must be taxed instead — not the work
    state's, and not both."""
    work_slabs = [Slab(Decimal("0"), None, Decimal("5"))]
    resident_slabs = [Slab(Decimal("0"), None, Decimal("3"))]
    result = calc(
        "US", 10000, US_RATES, US_SLABS, state_slabs=work_slabs, resident_state_slabs=resident_slabs,
        reciprocity_suppresses_work_state=True,
    )
    # 3% resident-state table, not the 5% work-state one.
    assert result.state_income_tax == pytest.approx(Decimal("300.00"), abs=Decimal("0.01"))


def test_us_filing_status_falls_back_to_untagged_row_when_present():
    """A mix of tagged + untagged rows: an employee whose filing_status
    doesn't match any tagged row falls back to the untagged (generic) row
    rather than computing zero tax — this is what lets an org configure
    ONE filing-status-specific override without needing to also retag
    every other bracket."""
    mixed_slabs = [
        Slab(Decimal("0"), None, Decimal("10")),                       # generic, untagged
        Slab(Decimal("0"), None, Decimal("37"), filing_status="MFS"),  # MFS-specific override
    ]
    single_result = calc("US", 10000, US_RATES, mixed_slabs, w4_filing_status="SINGLE")
    mfs_result = calc("US", 10000, US_RATES, mixed_slabs, w4_filing_status="MFS")
    assert single_result.federal_income_tax < mfs_result.federal_income_tax
    assert single_result.federal_income_tax == pytest.approx(mfs_result.federal_income_tax * Decimal("10") / Decimal("37"), abs=Decimal("0.05"))


def test_us_medicare_additional_threshold_defaults_to_200k_for_single_or_unset():
    """No filing status (every employee before w4_filing_status existed)
    and SINGLE/HOH both use the same $200,000 default — no behavior
    change for existing employees."""
    result_unset = calc("US", 20000, US_RATES, US_SLABS)
    result_single = calc("US", 20000, US_RATES, US_SLABS, w4_filing_status="SINGLE")
    # $240,000 annual - $200,000 threshold = $40,000 excess * 0.9% / 12
    expected = Decimal("290.00") + Decimal("30.00")  # base 1.45% + additional 0.9% on excess
    assert result_unset.medicare == pytest.approx(expected, abs=Decimal("0.01"))
    assert result_single.medicare == pytest.approx(expected, abs=Decimal("0.01"))


def test_us_medicare_additional_threshold_is_250k_for_mfj():
    """MFJ's real IRS threshold ($250,000) is higher than Single's — an
    employee whose annual gross falls between the two must owe zero
    Additional Medicare as MFJ, unlike as Single."""
    result = calc("US", 20000, US_RATES, US_SLABS, w4_filing_status="MFJ")
    # $240,000 annual stays under the $250,000 MFJ threshold — base only.
    assert result.medicare == pytest.approx(Decimal("290.00"), abs=Decimal("0.01"))


def test_us_medicare_additional_threshold_is_125k_for_mfs():
    """MFS's real IRS threshold ($125,000) is lower than Single's — more
    of the same income becomes subject to Additional Medicare as MFS."""
    result = calc("US", 20000, US_RATES, US_SLABS, w4_filing_status="MFS")
    # $240,000 annual - $125,000 threshold = $115,000 excess * 0.9% / 12
    expected = Decimal("290.00") + Decimal("86.25")
    assert result.medicare == pytest.approx(expected, abs=Decimal("0.01"))


def test_us_medicare_additional_threshold_configured_row_overrides_filing_status_default():
    """A Super-Admin-configured medicare_addl_thresh row must win over
    ANY filing-status default — same override convention every other
    parameter here follows."""
    rates = dict(US_RATES, medicare_addl_thresh=Rate(flat_amount=Decimal("999999")))
    result = calc("US", 20000, rates, US_SLABS, w4_filing_status="MFS")
    # Configured threshold is far above $240,000 annual gross — no
    # Additional Medicare at all, despite MFS's lower statutory default.
    assert result.medicare == pytest.approx(Decimal("290.00"), abs=Decimal("0.01"))


def test_us_no_locality_rate_is_a_no_op():
    """No LocalityRate resolved (every employee today with no work_locality
    set, or a code nothing is configured for) — local_tax must stay exactly
    zero, never inferred. Core regression guard."""
    result = calc("US", 10000, US_RATES, US_SLABS)
    assert result.local_tax == Decimal("0")


def test_us_locality_rate_pct_applies_to_monthly_gross():
    """A resident_rate_pct-only LocalityRate must be applied against gross
    (annualized then divided back to monthly) — the same wage-based
    convention every other US tax component here already uses."""
    locality = LocalityRateStub(resident_rate_pct=Decimal("3.75"))
    result = calc("US", 5000, US_RATES, US_SLABS, locality_rate=locality)
    # 3.75% of ($5,000 * 12) / 12 == 3.75% of $5,000
    assert result.local_tax == pytest.approx(Decimal("187.50"), abs=Decimal("0.01"))


def test_us_locality_rate_falls_back_to_nonresident_pct_when_resident_unset():
    """No locality-level residence tracking exists yet — nonresident_rate_pct
    is used only when resident_rate_pct is absent, never guessed."""
    locality = LocalityRateStub(nonresident_rate_pct=Decimal("2.00"))
    result = calc("US", 5000, US_RATES, US_SLABS, locality_rate=locality)
    assert result.local_tax == pytest.approx(Decimal("100.00"), abs=Decimal("0.01"))


def test_us_locality_flat_amount_applied_directly_not_annualized():
    """A flat_amount (e.g. an LST-style per-payslip fee) is applied as-is,
    the same convention india.py's Professional Tax flat_amount already
    uses — NOT divided by 12 or otherwise annualized."""
    locality = LocalityRateStub(flat_amount=Decimal("52.00"), resident_rate_pct=Decimal("3.75"))
    result = calc("US", 5000, US_RATES, US_SLABS, locality_rate=locality)
    # flat_amount takes precedence over any configured rate_pct.
    assert result.local_tax == Decimal("52.00")


# ── United Kingdom ───────────────────────────────────────────────────────

UK_RATES = {
    "national-insurance": Rate("national-insurance", Decimal("8.00"), Decimal("13.80")),
    "employer-pension": Rate("employer-pension", employer_rate_pct=Decimal("3.00")),
}
UK_SLABS = [
    Slab(Decimal("0"), Decimal("12570"), Decimal("0")),
    Slab(Decimal("12570"), Decimal("50270"), Decimal("20")),
    Slab(Decimal("50270"), None, Decimal("40")),
]


def test_uk_ni_below_primary_threshold():
    result = calc("UK", 1000, UK_RATES, UK_SLABS)  # £12k/yr, under £12,570 threshold
    assert result.ni_employee == 0


def test_uk_ni_above_primary_threshold():
    result = calc("UK", 2000, UK_RATES, UK_SLABS)  # £24k/yr, over the threshold
    assert result.ni_employee > 0


def test_uk_personal_allowance_taper_reduces_allowance():
    normal = calc("UK", Decimal("6000"), UK_RATES, UK_SLABS)      # £72k/yr, no taper
    tapered = calc("UK", Decimal("10000"), UK_RATES, UK_SLABS)    # £120k/yr, tapered
    normal_rate = normal.tds / Decimal("6000")
    tapered_rate = tapered.tds / Decimal("10000")
    assert tapered_rate > normal_rate


def test_uk_zero_income():
    result = calc("UK", 0, UK_RATES, UK_SLABS)
    assert result.net_pay == 0


# ── Australia / Germany / Canada ─────────────────────────────────────────

def test_australia_super_and_medicare_levy():
    rates = {
        "super": Rate("super", employer_rate_pct=Decimal("11.50")),
        "medicare-levy": Rate("medicare-levy", employee_rate_pct=Decimal("2.00")),
    }
    slabs = [Slab(Decimal("0"), Decimal("18200"), Decimal("0")), Slab(Decimal("18200"), None, Decimal("16"))]
    result = calc("AU", 5000, rates, slabs)
    assert result.employer_pension > 0
    assert result.medicare > 0


def test_germany_pension_and_social_insurance():
    rates = {
        "pension": Rate("pension", Decimal("9.30"), Decimal("9.30")),
        "social-insurance": Rate("social-insurance", Decimal("9.00"), Decimal("9.00")),
    }
    slabs = [Slab(Decimal("0"), Decimal("11000"), Decimal("0")), Slab(Decimal("11000"), None, Decimal("14"))]
    result = calc("DE", 4000, rates, slabs)
    assert result.employee_pf > 0
    assert result.employee_esi > 0


def test_canada_cpp_and_ei():
    rates = {
        "cpp": Rate("cpp", Decimal("5.95"), Decimal("5.95")),
        "ei": Rate("ei", Decimal("1.66"), Decimal("2.32")),
    }
    slabs = [Slab(Decimal("0"), Decimal("55000"), Decimal("15")), Slab(Decimal("55000"), None, Decimal("20.5"))]
    result = calc("CA", 4000, rates, slabs)
    assert result.social_security > 0
    assert result.employee_esi > 0


# ── Australia / Germany / Canada named scalar parameters ────────────────
# Fallback-default thresholds (no override rows): AU medicare_low_inc_thr
# =24276, mls_threshold=97000/mls_rate=1.0%,
# super_max_contrib=260280; DE contribution_ceiling=96600;
# CA cpp_ympe=74600/cpp_basic_exemption=3500/ei_mie=68900 (2026 values,
# ZP-TAX-CA-2026-001). Flat 10% slab used throughout so income-tax math
# never obscures the contribution assertions being tested.

_FLAT_10_SLAB = [Slab(Decimal("0"), None, Decimal("10"))]


def test_australia_medicare_levy_exempt_below_low_income_threshold():
    rates = {"medicare-levy": Rate("medicare-levy", employee_rate_pct=Decimal("2.00"))}
    result = calc("AU", 1500, rates, _FLAT_10_SLAB)  # annual 18,000 < 24,276 threshold
    assert result.medicare == 0


def test_australia_medicare_levy_applies_above_low_income_threshold():
    rates = {"medicare-levy": Rate("medicare-levy", employee_rate_pct=Decimal("2.00"))}
    result = calc("AU", 2100, rates, _FLAT_10_SLAB)  # annual 25,200 > 24,276 threshold
    assert result.medicare == Decimal("42.00")  # 2100 * 2%


def test_australia_medicare_levy_surcharge_above_mls_threshold():
    rates = {"medicare-levy": Rate("medicare-levy", employee_rate_pct=Decimal("2.00"))}
    result = calc("AU", 10000, rates, _FLAT_10_SLAB)  # annual 120,000 > 97,000 MLS threshold
    # base levy 10000*2% = 200.00, + MLS 1% of annual/12 = 100.00
    assert result.medicare == Decimal("300.00")


def test_australia_super_guarantee_capped_at_max_contribution_base():
    rates = {"super": Rate("super", employer_rate_pct=Decimal("11.50"))}
    result = calc("AU", 30000, rates, _FLAT_10_SLAB)  # annual 360,000 > 260,280 cap
    uncapped = Decimal("30000") * Decimal("11.50") / 100
    assert result.employer_pension < uncapped
    assert result.employer_pension == Decimal("2494.35")  # (260280 * 11.5% ) / 12


def test_germany_contributions_capped_at_contribution_ceiling():
    rates = {"pension": Rate("pension", employee_rate_pct=Decimal("9.30"), employer_rate_pct=Decimal("9.30"))}
    result = calc("DE", 10000, rates, _FLAT_10_SLAB)  # annual 120,000 > 96,600 ceiling
    uncapped = Decimal("10000") * Decimal("9.30") / 100
    assert result.employee_pf < uncapped
    assert result.employee_pf == Decimal("748.65")  # (96600 * 9.3%) / 12


def test_canada_cpp_exempts_basic_amount_and_caps_at_ympe_ei_caps_separately():
    rates = {
        "cpp": Rate("cpp", employee_rate_pct=Decimal("5.95"), employer_rate_pct=Decimal("5.95")),
        "ei": Rate("ei", employee_rate_pct=Decimal("1.66"), employer_rate_pct=Decimal("2.32")),
    }
    result = calc("CA", 7000, rates, _FLAT_10_SLAB)  # annual 84,000 > both YMPE (74,600) and MIE (68,900)
    # CPP pensionable = min(84000, 74600) - 3500 = 71100 -> (71100*5.95%)/12
    assert result.social_security == Decimal("352.54")
    # EI insurable = min(84000, 68900) = 68900 -> (68900*1.66%)/12 — capped
    # independently of CPP's own (lower) cap.
    assert result.employee_esi == Decimal("95.31")


def test_canada_bpaf_flat_at_max_below_taper_threshold():
    # NI (60,000) <= the $181,440 low threshold -> flat BPAF max.
    assert _resolve_ca_bpaf(Decimal("60000"), {}) == Decimal("16452")


def test_canada_bpaf_tapers_linearly_between_thresholds():
    # NI (240,000) between the $181,440/$258,482 thresholds:
    # reduction = (240000-181440) * (16452-14829) / (258482-181440)
    assert _resolve_ca_bpaf(Decimal("240000"), {}) == Decimal("15218.35")


def test_canada_bpaf_flat_at_min_above_taper_threshold():
    # NI (300,000) >= the $258,482 high threshold -> flat BPAF min.
    assert _resolve_ca_bpaf(Decimal("300000"), {}) == Decimal("14829")


def test_canada_cea_credit_reduces_annual_tax_at_lowest_rate():
    rates = {
        "cpp": Rate("cpp", employee_rate_pct=Decimal("5.95"), employer_rate_pct=Decimal("5.95")),
        "ei": Rate("ei", employee_rate_pct=Decimal("1.63"), employer_rate_pct=Decimal("2.282")),
    }
    result = calc("CA", 5000, rates, _FLAT_10_SLAB)  # annual 60,000, BPAF flat at max (16,452)
    # taxable = 60000 - 16452 = 43548; tax_before_credits = 43548 * 10% = 4354.80
    # CEA credit = 1501 * 14% = 210.14; annual_tax = 4354.80 - 210.14 = 4144.66
    assert result.annual_tax == Decimal("4144.66")
    assert result.tds == Decimal("345.39")  # 4144.66 / 12


def test_canada_provincial_tax_zero_when_unconfigured():
    # No state_slabs configured for the resolved province (the situation
    # for every CA province today, until real data is seeded) -> the new
    # state_income_tax field stays exactly 0, federal tax is unaffected.
    result = calc("CA", 5000, {}, _FLAT_10_SLAB, work_state="ON")
    assert result.state_income_tax == Decimal("0")
    assert result.federal_income_tax == result.tds


def test_canada_provincial_tax_added_on_top_of_federal():
    rates = {
        "cpp": Rate("cpp", employee_rate_pct=Decimal("5.95"), employer_rate_pct=Decimal("5.95")),
        "ei": Rate("ei", employee_rate_pct=Decimal("1.63"), employer_rate_pct=Decimal("2.282")),
    }
    provincial_rates = {"provincial_bpa": Rate("provincial_bpa", flat_amount=Decimal("10000"))}
    result = calc(
        "CA", 5000, rates, _FLAT_10_SLAB, work_state="ON",
        state_slabs=_FLAT_10_SLAB, state_rate_map=provincial_rates,
    )
    # Federal: BPA=16452 (60000 NI <= threshold) -> taxable 43548 * 10% =
    # 4354.80, less CEA credit 210.14 = 4144.66 -> federal_income_tax 345.39
    assert result.federal_income_tax == Decimal("345.39")
    # Provincial: taxable = 60000 - 10000 (provincial_bpa) = 50000 * 10% =
    # 5000.00 -> state_income_tax 416.67
    assert result.state_income_tax == Decimal("416.67")
    assert result.tds == result.federal_income_tax + result.state_income_tax
    assert result.annual_tax == Decimal("9144.66")


def test_canada_quebec_provincial_tax_ignores_generic_provincial_bpa_key():
    # Quebec's provincial tax runs through its own dedicated path, not
    # the generic one — the generic "provincial_bpa" key must be
    # completely ignored for a Quebec employee, even if populated.
    state_rates = {"provincial_bpa": Rate("provincial_bpa", flat_amount=Decimal("10000"))}
    result = calc(
        "CA", 5000, {}, _FLAT_10_SLAB, work_state="QC",
        state_slabs=_FLAT_10_SLAB, state_rate_map=state_rates,
    )
    # "quebec_bpa" isn't set -> bpa resolves to 0, not the ignored 10000
    # -> taxable = 60000 * 10% = 6000.00 -> state_income_tax 500.00
    assert result.state_income_tax == Decimal("500.00")


def test_canada_quebec_provincial_tax_uses_quebec_bpa_key():
    state_rates = {"quebec_bpa": Rate("quebec_bpa", flat_amount=Decimal("18952"))}
    result = calc(
        "CA", 5000, {}, _FLAT_10_SLAB, work_state="QC",
        state_slabs=_FLAT_10_SLAB, state_rate_map=state_rates,
    )
    # taxable = max(0, 60000 - 18952) = 41048 * 10% = 4104.80 -> 342.07/mo
    assert result.state_income_tax == Decimal("342.07")


def test_canada_quebec_worker_deduction_reduces_taxable_income():
    state_rates = {
        "quebec_bpa": Rate("quebec_bpa", flat_amount=Decimal("18952")),
        "qc_worker_deduction": Rate("qc_worker_deduction", flat_amount=Decimal("1450")),
    }
    result = calc(
        "CA", 5000, {}, _FLAT_10_SLAB, work_state="QC",
        state_slabs=_FLAT_10_SLAB, state_rate_map=state_rates,
    )
    # taxable = max(0, 60000 - 18952 - 1450) = 39598 * 10% = 3959.80 -> 329.98/mo
    assert result.state_income_tax == Decimal("329.98")


def test_canada_quebec_worker_deduction_capped_by_income_not_negative():
    state_rates = {
        "quebec_bpa": Rate("quebec_bpa", flat_amount=Decimal("18952")),
        "qc_worker_deduction": Rate("qc_worker_deduction", flat_amount=Decimal("1450")),
    }
    # Annual gross (12000) below BPA alone — taxable must floor at 0,
    # never go negative from stacking BPA + worker deduction.
    result = calc(
        "CA", 1000, {}, _FLAT_10_SLAB, work_state="QC",
        state_slabs=_FLAT_10_SLAB, state_rate_map=state_rates,
    )
    assert result.state_income_tax == Decimal("0")


def test_canada_quebec_worker_deduction_absent_defaults_to_zero():
    state_rates = {"quebec_bpa": Rate("quebec_bpa", flat_amount=Decimal("18952"))}
    result = calc(
        "CA", 5000, {}, _FLAT_10_SLAB, work_state="QC",
        state_slabs=_FLAT_10_SLAB, state_rate_map=state_rates,
    )
    # Same as test_canada_quebec_provincial_tax_uses_quebec_bpa_key —
    # unconfigured qc_worker_deduction must not change existing behavior.
    assert result.state_income_tax == Decimal("342.07")


# ── CRA credit method for BPA/BPAF (Phase 6 correctness fix) ────────────
# Dormant behind shared._CA_CREDIT_METHOD_ENABLED_COUNTRIES (empty by
# default) — the legacy "deduct BPA from taxable income" path stays
# byte-for-byte unchanged everywhere above. These tests exercise
# _calculate_annual_tax_ca/_calculate_provincial_tax_ca/
# _calculate_quebec_provincial_tax directly (not via calc()'s monthly/
# annual round-trip) so the bracket arithmetic can be verified to the
# exact cent, matching CRA's real T4127 method.

_CA_FEDERAL_2026_SLABS = [
    Slab(Decimal("0"), Decimal("58523"), Decimal("14.00")),
    Slab(Decimal("58523"), Decimal("117045"), Decimal("20.50")),
    Slab(Decimal("117045"), Decimal("181440"), Decimal("26.00")),
    Slab(Decimal("181440"), Decimal("258482"), Decimal("29.00")),
    Slab(Decimal("258482"), None, Decimal("33.00")),
]


@pytest.fixture(autouse=True)
def _restore_ca_credit_method_switch():
    original_credit = set(shared._CA_CREDIT_METHOD_ENABLED_COUNTRIES)
    original_dynamic_bpa = set(shared._CA_DYNAMIC_PROVINCIAL_BPA_ENABLED_COUNTRIES)
    original_age_gated_cpp = set(shared._CA_AGE_GATED_CPP_ENABLED_COUNTRIES)
    original_cpp_split = set(shared._CA_CPP_COMPONENT_SPLIT_ENABLED_COUNTRIES)
    original_k2_k3 = set(shared._CA_CPP_EI_FEDERAL_CREDIT_ENABLED_COUNTRIES)
    original_ei_multiplier = set(shared._CA_EI_EMPLOYER_MULTIPLIER_ENABLED_COUNTRIES)
    original_lsvcc = set(shared._CA_LSVCC_CREDIT_ENABLED_COUNTRIES)
    original_surtax = set(shared._CA_BEYOND_PROVINCE_SURTAX_ENABLED_COUNTRIES)
    original_bc_reduction = set(shared._CA_BC_TAX_REDUCTION_ENABLED_COUNTRIES)
    original_in_pf_ceiling = set(shared._IN_PF_WAGE_CEILING_ENABLED_COUNTRIES)
    yield
    shared._CA_CREDIT_METHOD_ENABLED_COUNTRIES.clear()
    shared._CA_CREDIT_METHOD_ENABLED_COUNTRIES.update(original_credit)
    shared._CA_DYNAMIC_PROVINCIAL_BPA_ENABLED_COUNTRIES.clear()
    shared._CA_DYNAMIC_PROVINCIAL_BPA_ENABLED_COUNTRIES.update(original_dynamic_bpa)
    shared._CA_AGE_GATED_CPP_ENABLED_COUNTRIES.clear()
    shared._CA_AGE_GATED_CPP_ENABLED_COUNTRIES.update(original_age_gated_cpp)
    shared._CA_CPP_COMPONENT_SPLIT_ENABLED_COUNTRIES.clear()
    shared._CA_CPP_COMPONENT_SPLIT_ENABLED_COUNTRIES.update(original_cpp_split)
    shared._CA_CPP_EI_FEDERAL_CREDIT_ENABLED_COUNTRIES.clear()
    shared._CA_CPP_EI_FEDERAL_CREDIT_ENABLED_COUNTRIES.update(original_k2_k3)
    shared._CA_EI_EMPLOYER_MULTIPLIER_ENABLED_COUNTRIES.clear()
    shared._CA_EI_EMPLOYER_MULTIPLIER_ENABLED_COUNTRIES.update(original_ei_multiplier)
    shared._CA_LSVCC_CREDIT_ENABLED_COUNTRIES.clear()
    shared._CA_LSVCC_CREDIT_ENABLED_COUNTRIES.update(original_lsvcc)
    shared._CA_BEYOND_PROVINCE_SURTAX_ENABLED_COUNTRIES.clear()
    shared._CA_BEYOND_PROVINCE_SURTAX_ENABLED_COUNTRIES.update(original_surtax)
    shared._CA_BC_TAX_REDUCTION_ENABLED_COUNTRIES.clear()
    shared._CA_BC_TAX_REDUCTION_ENABLED_COUNTRIES.update(original_bc_reduction)
    shared._IN_PF_WAGE_CEILING_ENABLED_COUNTRIES.clear()
    shared._IN_PF_WAGE_CEILING_ENABLED_COUNTRIES.update(original_in_pf_ceiling)


def test_lowest_bracket_rate_picks_the_lowest_starting_bracket():
    assert _canada._lowest_bracket_rate(_CA_FEDERAL_2026_SLABS) == Decimal("14.00")


def test_lowest_bracket_rate_zero_when_no_slabs():
    assert _canada._lowest_bracket_rate([]) == Decimal("0")


def test_federal_tax_legacy_and_credit_methods_agree_with_a_single_flat_bracket():
    # With only ONE bracket, there's no higher marginal rate for either
    # method to diverge into — deducting BPA first (legacy) or crediting
    # it at the (only) rate (credit method) must give the identical
    # result, proving the two methods are mathematically equivalent
    # exactly until a second bracket enters the picture (see the next
    # two tests, which use the real multi-bracket table).
    one_bracket = [Slab(Decimal("0"), None, Decimal("14.00"))]
    legacy = _canada._calculate_annual_tax_ca(Decimal("78523"), one_bracket, {})
    shared._CA_CREDIT_METHOD_ENABLED_COUNTRIES.add("CA")
    credit = _canada._calculate_annual_tax_ca(Decimal("78523"), one_bracket, {})
    assert legacy == credit == Decimal("8479.80")  # (78523-16452)*14% - (1501*14%)


def test_federal_tax_legacy_method_understates_tax_once_income_crosses_a_bracket():
    annual_gross = Decimal("78523")  # BPAF-reduced taxable (62,071) crosses into the 20.5% bracket
    legacy = _canada._calculate_annual_tax_ca(annual_gross, _CA_FEDERAL_2026_SLABS, {})
    # taxable = 78523 - 16452 = 62071; tax = 58523*14% + (62071-58523)*20.5%
    #         = 8193.22 + 727.34 = 8920.56; minus CEA (1501*14%=210.14) = 8710.42
    assert legacy == Decimal("8710.42")


def test_federal_tax_credit_method_matches_cra_t4127_formula_when_enabled():
    shared._CA_CREDIT_METHOD_ENABLED_COUNTRIES.add("CA")
    annual_gross = Decimal("78523")  # excess over $58,523 is a clean $20,000
    credit = _canada._calculate_annual_tax_ca(annual_gross, _CA_FEDERAL_2026_SLABS, {})
    # tax_before_credits = 58523*14% + 20000*20.5% = 8193.22 + 4100.00 = 12293.22
    # bpa_credit = 16452*14% = 2303.28; cea_credit = 1501*14% = 210.14
    # tax = 12293.22 - 2303.28 - 210.14 = 9779.80
    assert credit == Decimal("9779.80")
    # Confirms the two methods genuinely diverge once income crosses a
    # bracket — the legacy method (see the test above) computed only
    # 8710.42 for this same income, a $1,069.38/yr understatement.
    assert credit > Decimal("8710.42")


def test_federal_tax_credit_method_honors_td1_claim_amount_override():
    shared._CA_CREDIT_METHOD_ENABLED_COUNTRIES.add("CA")
    credit = _canada._calculate_annual_tax_ca(Decimal("78523"), _CA_FEDERAL_2026_SLABS, {}, td1_claim_amount=Decimal("0"))
    # bpa_credit = 0 -> tax = 12293.22 - 0 - 210.14 = 12083.08
    assert credit == Decimal("12083.08")


def test_provincial_tax_credit_method_uses_the_provinces_own_lowest_rate():
    provincial_slabs = [
        Slab(Decimal("0"), Decimal("50000"), Decimal("10.00")),
        Slab(Decimal("50000"), None, Decimal("20.00")),
    ]
    state_rates = {"provincial_bpa": Rate("provincial_bpa", flat_amount=Decimal("12000"))}
    legacy = _canada._calculate_provincial_tax_ca(Decimal("70000"), "ON", provincial_slabs, state_rates)
    # legacy: taxable = 70000-12000 = 58000; tax = 50000*10% + 8000*20% = 5000+1600 = 6600.00
    assert legacy == Decimal("6600.00")

    shared._CA_CREDIT_METHOD_ENABLED_COUNTRIES.add("CA")
    credit = _canada._calculate_provincial_tax_ca(Decimal("70000"), "ON", provincial_slabs, state_rates)
    # credit: tax_before_credits = 50000*10% + 20000*20% = 5000+4000 = 9000.00
    # bpa_credit = 12000 * PROVINCE's OWN lowest rate (10%, not federal's 14%) = 1200.00
    # tax = 9000.00 - 1200.00 = 7800.00
    assert credit == Decimal("7800.00")


def test_provincial_tax_credit_method_still_zero_for_quebec():
    shared._CA_CREDIT_METHOD_ENABLED_COUNTRIES.add("CA")
    result = _canada._calculate_provincial_tax_ca(Decimal("70000"), "QC", _CA_FEDERAL_2026_SLABS, {})
    assert result == Decimal("0")


# ── Manitoba/Yukon dynamic BPA (Phase 6) ─────────────────────────────────
# Dormant behind shared._CA_DYNAMIC_PROVINCIAL_BPA_ENABLED_COUNTRIES —
# both provinces keep reading the generic flat "provincial_bpa" row
# (same as every other province) until this is deliberately flipped.

_MB_BPA_RATES = {
    "mb_bpa_max": Rate(flat_amount=Decimal("15780")),
    "mb_bpa_ni_thresh_lo": Rate(flat_amount=Decimal("200000")),
    "mb_bpa_ni_thresh_hi": Rate(flat_amount=Decimal("400000")),
}


def test_mb_bpa_flat_at_max_below_taper_threshold():
    assert _canada._resolve_mb_bpa(Decimal("150000"), _MB_BPA_RATES) == Decimal("15780")


def test_mb_bpa_tapers_linearly_between_thresholds():
    # reduction = (300000-200000) * (15780/200000) = 7890.00
    assert _canada._resolve_mb_bpa(Decimal("300000"), _MB_BPA_RATES) == Decimal("7890.00")


def test_mb_bpa_floors_at_zero_at_and_above_high_threshold():
    assert _canada._resolve_mb_bpa(Decimal("400000"), _MB_BPA_RATES) == Decimal("0")
    assert _canada._resolve_mb_bpa(Decimal("450000"), _MB_BPA_RATES) == Decimal("0")


def test_mb_bpa_zero_when_not_configured():
    assert _canada._resolve_mb_bpa(Decimal("150000"), {}) == Decimal("0")


def test_provincial_tax_uses_dynamic_mb_bpa_when_enabled():
    shared._CA_DYNAMIC_PROVINCIAL_BPA_ENABLED_COUNTRIES.add("CA")
    result = _canada._calculate_provincial_tax_ca(Decimal("300000"), "MB", _FLAT_10_SLAB, _MB_BPA_RATES)
    # taxable = 300000 - 7890.00 (tapered) = 292110.00 * 10% = 29211.00
    assert result == Decimal("29211.00")


def test_provincial_tax_mb_dormant_uses_flat_row_instead():
    state_rates = {**_MB_BPA_RATES, "provincial_bpa": Rate("provincial_bpa", flat_amount=Decimal("10000"))}
    result = _canada._calculate_provincial_tax_ca(Decimal("300000"), "MB", _FLAT_10_SLAB, state_rates)
    # Switch is OFF -> flat 10,000 row used, NOT the tapered 7,890.00:
    # taxable = 300000 - 10000 = 290000 * 10% = 29000.00
    assert result == Decimal("29000.00")


def test_provincial_tax_uses_federal_bpaf_for_yukon_when_enabled():
    shared._CA_DYNAMIC_PROVINCIAL_BPA_ENABLED_COUNTRIES.add("CA")
    # NI (100,000) below the federal taper threshold -> flat federal max (16,452).
    result = _canada._calculate_provincial_tax_ca(Decimal("100000"), "YT", _FLAT_10_SLAB, {}, rate_map={})
    # taxable = 100000 - 16452 = 83548 * 10% = 8354.80
    assert result == Decimal("8354.80")


def test_provincial_tax_yt_dormant_uses_flat_row_instead():
    state_rates = {"provincial_bpa": Rate("provincial_bpa", flat_amount=Decimal("12000"))}
    result = _canada._calculate_provincial_tax_ca(Decimal("100000"), "YT", _FLAT_10_SLAB, state_rates, rate_map={})
    # Switch is OFF -> flat 12,000 row used, NOT federal BPAF's 16,452:
    # taxable = 100000 - 12000 = 88000 * 10% = 8800.00
    assert result == Decimal("8800.00")


def test_provincial_tax_td1_override_still_wins_over_dynamic_mb_bpa():
    shared._CA_DYNAMIC_PROVINCIAL_BPA_ENABLED_COUNTRIES.add("CA")
    result = _canada._calculate_provincial_tax_ca(
        Decimal("300000"), "MB", _FLAT_10_SLAB, _MB_BPA_RATES, provincial_td1_claim_amount=Decimal("5000"),
    )
    # An employee's own filed provincial TD1 claim amount overrides the
    # dynamic formula entirely: taxable = 300000-5000 = 295000 * 10% = 29500.00
    assert result == Decimal("29500.00")


# ── BC basic tax reduction (§9, "balance" item) ──────────────────────────
# Dormant behind shared._CA_BC_TAX_REDUCTION_ENABLED_COUNTRIES. Disclosed
# simplification: flat, non-phased-out, using the doc's single annual
# $690 figure (see canada.py's own comment for why H1's $575/H2's $805
# aren't separately resolvable today).

_BC_REDUCTION_RATES = {
    "provincial_bpa": Rate("provincial_bpa", flat_amount=Decimal("12000")),
    "bc_basic_tax_reduction": Rate("bc_basic_tax_reduction", flat_amount=Decimal("690")),
}


def test_bc_tax_reduction_dormant_by_default():
    result = _canada._calculate_provincial_tax_ca(Decimal("70000"), "BC", _FLAT_10_SLAB, _BC_REDUCTION_RATES)
    # taxable = 70000-12000 = 58000 * 10% = 5800.00 — reduction NOT applied
    assert result == Decimal("5800.00")


def test_bc_tax_reduction_applies_when_enabled_legacy_method():
    shared._CA_BC_TAX_REDUCTION_ENABLED_COUNTRIES.add("CA")
    result = _canada._calculate_provincial_tax_ca(Decimal("70000"), "BC", _FLAT_10_SLAB, _BC_REDUCTION_RATES)
    assert result == Decimal("5110.00")  # 5800.00 - 690.00


def test_bc_tax_reduction_applies_when_enabled_credit_method():
    shared._CA_BC_TAX_REDUCTION_ENABLED_COUNTRIES.add("CA")
    shared._CA_CREDIT_METHOD_ENABLED_COUNTRIES.add("CA")
    result = _canada._calculate_provincial_tax_ca(Decimal("70000"), "BC", _FLAT_10_SLAB, _BC_REDUCTION_RATES)
    # tax_before_credits = 70000*10% = 7000.00; bpa_credit = 12000*10% = 1200.00
    # 7000.00 - 1200.00 - 690.00 = 5110.00 (matches legacy — single flat bracket)
    assert result == Decimal("5110.00")


def test_bc_tax_reduction_floors_at_zero_not_negative():
    shared._CA_BC_TAX_REDUCTION_ENABLED_COUNTRIES.add("CA")
    result = _canada._calculate_provincial_tax_ca(
        Decimal("1000"), "BC", _FLAT_10_SLAB, {"bc_basic_tax_reduction": Rate(flat_amount=Decimal("690"))},
    )
    # tax_before = 1000*10% = 100.00; 100.00 - 690.00 would be negative -> 0
    assert result == Decimal("0")


def test_bc_tax_reduction_does_not_apply_to_other_provinces():
    shared._CA_BC_TAX_REDUCTION_ENABLED_COUNTRIES.add("CA")
    result = _canada._calculate_provincial_tax_ca(Decimal("70000"), "ON", _FLAT_10_SLAB, _BC_REDUCTION_RATES)
    # Same rate_map (including a bc_basic_tax_reduction row) but work_state="ON" -> ignored.
    assert result == Decimal("5800.00")


def test_bc_tax_reduction_zero_when_not_configured():
    shared._CA_BC_TAX_REDUCTION_ENABLED_COUNTRIES.add("CA")
    result = _canada._calculate_provincial_tax_ca(
        Decimal("70000"), "BC", _FLAT_10_SLAB, {"provincial_bpa": Rate(flat_amount=Decimal("12000"))},
    )
    assert result == Decimal("5800.00")  # no bc_basic_tax_reduction row -> 0 reduction


def test_quebec_tax_credit_method_keeps_worker_deduction_as_income_deduction():
    qc_slabs = [
        Slab(Decimal("0"), Decimal("54345"), Decimal("14.00")),
        Slab(Decimal("54345"), None, Decimal("19.00")),
    ]
    state_rates = {
        "quebec_bpa": Rate("quebec_bpa", flat_amount=Decimal("18952")),
        "qc_worker_deduction": Rate("qc_worker_deduction", flat_amount=Decimal("1450")),
    }
    shared._CA_CREDIT_METHOD_ENABLED_COUNTRIES.add("CA")
    credit = _canada._calculate_quebec_provincial_tax(Decimal("70000"), qc_slabs, state_rates)
    # worker_deduction STAYS a deduction: taxable = 70000-1450 = 68550
    # tax_before_credits = 54345*14% + (68550-54345)*19% = 7608.30 + 2698.95 = 10307.25
    # bpa_credit = 18952 * 14% (Quebec's own lowest rate) = 2653.28
    # tax = 10307.25 - 2653.28 = 7653.97
    assert credit == Decimal("7653.97")


def test_calc_level_credit_method_switch_flows_through_to_tds():
    """End-to-end confirmation that the switch actually reaches
    StandardStrategy.calculate() -> canada.calculate() -> tds, not just
    the unit-level functions tested directly above."""
    legacy = calc("CA", Decimal("78523") / 12, {}, _CA_FEDERAL_2026_SLABS)
    shared._CA_CREDIT_METHOD_ENABLED_COUNTRIES.add("CA")
    credit = calc("CA", Decimal("78523") / 12, {}, _CA_FEDERAL_2026_SLABS)
    assert credit.tds > legacy.tds


# ── Federal K2/K3 credits — CPP/EI premiums withheld this period ────────
# (§7's "T3 = (R×A) − K − K1 − K2 − K3 − K4"). Only meaningful within the
# credit method above; gated on its OWN switch since it's a genuinely
# NEW credit, not a correction of an existing one.

def test_federal_k2_k3_credit_dormant_even_with_credit_method_on():
    shared._CA_CREDIT_METHOD_ENABLED_COUNTRIES.add("CA")
    result = _canada._calculate_annual_tax_ca(
        Decimal("58523"), _CA_FEDERAL_2026_SLABS, {},
        period_cpp_contribution=Decimal("300"), period_ei_contribution=Decimal("100"),
    )
    # tax_before_credits = 58523*14% = 8193.22; bpa_credit = 16452*14% = 2303.28
    # cea_credit = 1501*14% = 210.14 -> 8193.22-2303.28-210.14 = 5679.80
    # K2/K3 switch OFF -> the passed-in CPP/EI amounts are ignored entirely.
    assert result == Decimal("5679.80")


def test_federal_k2_k3_credit_reduces_tax_when_both_switches_enabled():
    shared._CA_CREDIT_METHOD_ENABLED_COUNTRIES.add("CA")
    shared._CA_CPP_EI_FEDERAL_CREDIT_ENABLED_COUNTRIES.add("CA")
    result = _canada._calculate_annual_tax_ca(
        Decimal("58523"), _CA_FEDERAL_2026_SLABS, {},
        period_cpp_contribution=Decimal("300"), period_ei_contribution=Decimal("100"),
    )
    # k2_k3_credit = (300+100) * 12 * 14% = 672.00 -> 5679.80 - 672.00 = 5007.80
    assert result == Decimal("5007.80")


def test_federal_k2_k3_credit_inert_under_legacy_deduction_method():
    # Credit method itself is OFF -> K2/K3's own switch has nothing to
    # hook into; the legacy path never even looks at the CPP/EI amounts.
    shared._CA_CPP_EI_FEDERAL_CREDIT_ENABLED_COUNTRIES.add("CA")
    result = _canada._calculate_annual_tax_ca(
        Decimal("58523"), _CA_FEDERAL_2026_SLABS, {},
        period_cpp_contribution=Decimal("300"), period_ei_contribution=Decimal("100"),
    )
    assert result == Decimal("5679.80")  # unchanged legacy figure


def test_calc_level_k2_k3_credit_flows_through_to_tds():
    shared._CA_CREDIT_METHOD_ENABLED_COUNTRIES.add("CA")
    rates = {
        "cpp": Rate("cpp", employee_rate_pct=Decimal("5.95"), employer_rate_pct=Decimal("5.95")),
        "ei": Rate("ei", employee_rate_pct=Decimal("1.63"), employer_rate_pct=Decimal("2.282")),
    }
    without_k2_k3 = calc("CA", 5000, rates, _CA_FEDERAL_2026_SLABS)
    shared._CA_CPP_EI_FEDERAL_CREDIT_ENABLED_COUNTRIES.add("CA")
    with_k2_k3 = calc("CA", 5000, rates, _CA_FEDERAL_2026_SLABS)
    assert with_k2_k3.tds < without_k2_k3.tds


# ── Labour-sponsored funds credit (LCF, §6, Phase 8) ─────────────────────
# Dormant behind shared._CA_LSVCC_CREDIT_ENABLED_COUNTRIES — already a
# direct dollar credit by statute, so it applies identically under both
# the legacy and credit-method tax paths (no dependency between the two
# switches). gross=5000/mo on _FLAT_10_SLAB reproduces the exact
# baseline from test_canada_cea_credit_reduces_annual_tax_at_lowest_rate
# (annual_tax 4144.66) so the credit's effect is isolated and obvious.

def test_lsvcc_credit_dormant_by_default():
    result = calc("CA", 5000, {}, _FLAT_10_SLAB, lsvcc_investment_amount=Decimal("5000"))
    assert result.annual_tax == Decimal("4144.66")  # unaffected by switch being off


def test_lsvcc_credit_capped_at_750():
    shared._CA_LSVCC_CREDIT_ENABLED_COUNTRIES.add("CA")
    result = calc("CA", 5000, {}, _FLAT_10_SLAB, lsvcc_investment_amount=Decimal("5000"))
    # 5000*15% = 750, already at the cap -> annual_tax = 4144.66 - 750.00
    assert result.annual_tax == Decimal("3394.66")


def test_lsvcc_credit_below_cap_uses_15_pct():
    shared._CA_LSVCC_CREDIT_ENABLED_COUNTRIES.add("CA")
    result = calc("CA", 5000, {}, _FLAT_10_SLAB, lsvcc_investment_amount=Decimal("2000"))
    # 2000*15% = 300.00 (under the $750 cap) -> 4144.66 - 300.00
    assert result.annual_tax == Decimal("3844.66")


def test_lsvcc_credit_zero_when_no_investment_declared():
    shared._CA_LSVCC_CREDIT_ENABLED_COUNTRIES.add("CA")
    result = calc("CA", 5000, {}, _FLAT_10_SLAB)
    assert result.annual_tax == Decimal("4144.66")


def test_lsvcc_credit_applies_under_credit_method_too():
    shared._CA_CREDIT_METHOD_ENABLED_COUNTRIES.add("CA")
    shared._CA_LSVCC_CREDIT_ENABLED_COUNTRIES.add("CA")
    result = calc("CA", 5000, {}, _FLAT_10_SLAB, lsvcc_investment_amount=Decimal("5000"))
    # tax_before_credits (credit method, single flat bracket) = 60000*10% = 6000.00
    # bpa_credit = 16452*14% = 2303.28; cea_credit = 1501*14% = 210.14; lsvcc = 750.00
    assert result.annual_tax == Decimal("2736.58")


# ── Beyond-province/outside-Canada surtax (§6/§7, Phase 8) ──────────────
# Dormant behind shared._CA_BEYOND_PROVINCE_SURTAX_ENABLED_COUNTRIES —
# applies only to a "XP" work_state employee (ZP-TAX-CA-2026-001 §3's
# CA-XP code), the same formula slot the Quebec abatement uses, just an
# increase instead of a reduction.

def test_beyond_province_surtax_dormant_by_default():
    result = calc("CA", 5000, {}, _FLAT_10_SLAB, work_state="XP")
    assert result.annual_tax == Decimal("4144.66")  # unaffected by switch being off


def test_beyond_province_surtax_increases_federal_tax_by_48_pct():
    shared._CA_BEYOND_PROVINCE_SURTAX_ENABLED_COUNTRIES.add("CA")
    result = calc("CA", 5000, {}, _FLAT_10_SLAB, work_state="XP")
    # 4144.66 * 148% = 6134.0968 -> 6134.10
    assert result.annual_tax == Decimal("6134.10")
    assert result.state_income_tax == Decimal("0")  # no province to tax


def test_beyond_province_surtax_does_not_apply_to_a_normal_province():
    shared._CA_BEYOND_PROVINCE_SURTAX_ENABLED_COUNTRIES.add("CA")
    result = calc("CA", 5000, {}, _FLAT_10_SLAB, work_state="ON")
    assert result.annual_tax == Decimal("4144.66")  # only "XP" triggers the surtax


def test_beyond_province_surtax_and_quebec_abatement_are_mutually_exclusive():
    shared._CA_BEYOND_PROVINCE_SURTAX_ENABLED_COUNTRIES.add("CA")
    # is_quebec branch wins even if the surtax switch is also on — the
    # two adjustments occupy the same formula slot and are for disjoint
    # jurisdictions, never both true for the same employee in practice.
    # Confirms the surtax switch doesn't leak into Quebec's own (already
    # pre-existing, Phase 2) federal-abatement branch: still exactly the
    # abated figure, not the surtaxed one.
    result = calc("CA", 5000, {}, _FLAT_10_SLAB, work_state="QC")
    # qc_fed_abatement unconfigured -> falls back to 16.5%: 4144.66 * 83.5% = 3460.79
    assert result.annual_tax == Decimal("3460.79")


# ── EI/QPIP employer 1.4x-default premium (§11, Phase 7) ────────────────
# Dormant behind shared._CA_EI_EMPLOYER_MULTIPLIER_ENABLED_COUNTRIES —
# gross=5000/mo keeps annual (60,000) comfortably under the default MIE
# (68,900) so period_insurable is a clean 5,000.00, isolating the rate
# logic from any cap-related rounding.

def test_ei_employer_rate_dormant_by_default_uses_configured_row():
    rates = {"ei": Rate("ei", employee_rate_pct=Decimal("1.63"), employer_rate_pct=Decimal("3.00"))}
    result = calc("CA", 5000, rates, _FLAT_10_SLAB)
    assert result.employee_esi == Decimal("81.50")    # 5000 * 1.63%
    assert result.employer_esi == Decimal("150.00")   # 5000 * 3.00% (the configured row, NOT 1.4x)


def test_ei_employer_rate_defaults_to_1_4x_employee_rate_when_enabled():
    shared._CA_EI_EMPLOYER_MULTIPLIER_ENABLED_COUNTRIES.add("CA")
    # employer_rate_pct=3.00 is deliberately inconsistent with 1.4x —
    # proving the switch IGNORES it entirely once enabled.
    rates = {"ei": Rate("ei", employee_rate_pct=Decimal("1.63"), employer_rate_pct=Decimal("3.00"))}
    result = calc("CA", 5000, rates, _FLAT_10_SLAB)
    assert result.employee_esi == Decimal("81.50")    # unaffected — always the employee's own rate
    assert result.employer_esi == Decimal("114.10")   # 5000 * (1.63 * 1.4)% = 5000 * 2.282%


def test_ei_employer_rate_reduced_authorization_overrides_1_4x_default():
    shared._CA_EI_EMPLOYER_MULTIPLIER_ENABLED_COUNTRIES.add("CA")
    rates = {"ei": Rate("ei", employee_rate_pct=Decimal("1.63"), employer_rate_pct=Decimal("3.00"))}
    profiles = {"EI_REDUCED": EmployerTaxProfileStub(employer_rate_pct=Decimal("1.00"))}
    result = calc("CA", 5000, rates, _FLAT_10_SLAB, employer_tax_profiles=profiles)
    assert result.employer_esi == Decimal("50.00")  # 5000 * 1.00% (the reduced-rate authorization)


def test_qpip_employer_rate_also_defaults_to_1_4x_when_enabled():
    shared._CA_EI_EMPLOYER_MULTIPLIER_ENABLED_COUNTRIES.add("CA")
    state_rates = {
        "qpip": Rate("qpip", employee_rate_pct=Decimal("1.30"), employer_rate_pct=Decimal("3.00")),
        "qpip_mie": Rate("qpip_mie", flat_amount=Decimal("103000")),
    }
    result = calc("CA", 5000, {}, _FLAT_10_SLAB, work_state="QC", state_rate_map=state_rates)
    assert result.employer_esi == Decimal("91.00")  # 5000 * (1.30 * 1.4)% = 5000 * 1.82%


def test_ei_employer_rate_multiplier_zero_when_ei_not_configured():
    shared._CA_EI_EMPLOYER_MULTIPLIER_ENABLED_COUNTRIES.add("CA")
    result = calc("CA", 5000, {}, _FLAT_10_SLAB)
    assert result.employer_esi == Decimal("0")


def test_canada_quebec_uses_qpp_instead_of_cpp():
    cpp_rates = {"cpp": Rate("cpp", employee_rate_pct=Decimal("5.95"), employer_rate_pct=Decimal("5.95"))}
    state_rates = {"qpp": Rate("qpp", employee_rate_pct=Decimal("6.30"), employer_rate_pct=Decimal("6.30"))}
    result = calc("CA", 5000, cpp_rates, _FLAT_10_SLAB, work_state="QC", state_rate_map=state_rates)
    # annual 60000 <= YMPE (74600); pensionable = 60000 - 3500 = 56500.
    # QPP's 6.30% must apply, NOT CPP's 5.95% from rate_map: 56500*6.30%
    # = 3559.50 -> /12 = 296.625 -> 296.63.
    assert result.social_security == Decimal("296.63")
    assert result.employer_social_security == Decimal("296.63")


def test_canada_non_quebec_still_uses_cpp_not_qpp():
    cpp_rates = {"cpp": Rate("cpp", employee_rate_pct=Decimal("5.95"), employer_rate_pct=Decimal("5.95"))}
    state_rates = {"qpp": Rate("qpp", employee_rate_pct=Decimal("6.30"), employer_rate_pct=Decimal("6.30"))}
    result = calc("CA", 5000, cpp_rates, _FLAT_10_SLAB, work_state="ON", state_rate_map=state_rates)
    # A stray "qpp" row in state_rate_map must never leak into a non-QC
    # calculation: 56500*5.95%/12 = 3361.75/12 = 280.1458 -> 280.15.
    assert result.social_security == Decimal("280.15")


def test_canada_quebec_uses_qpip_instead_of_ei():
    ei_rates = {"ei": Rate("ei", employee_rate_pct=Decimal("1.63"), employer_rate_pct=Decimal("2.282"))}
    state_rates = {
        "qpip": Rate("qpip", employee_rate_pct=Decimal("0.430"), employer_rate_pct=Decimal("0.602")),
        "qpip_mie": Rate("qpip_mie", flat_amount=Decimal("103000")),
    }
    result = calc("CA", 5000, ei_rates, _FLAT_10_SLAB, work_state="QC", state_rate_map=state_rates)
    # annual 60000 < QPIP MIE (103000) -> insurable = 60000.
    # QPIP must apply, NOT EI's rates from rate_map:
    # employee 60000*0.430%/12 = 21.50; employer 60000*0.602%/12 = 30.10.
    assert result.employee_esi == Decimal("21.50")
    assert result.employer_esi == Decimal("30.10")


def test_canada_quebec_qpip_zero_when_cap_not_configured():
    # Rate alone isn't enough — QPIP requires both its rate AND its MIE
    # cap configured before computing anything, never inferring one.
    state_rates = {"qpip": Rate("qpip", employee_rate_pct=Decimal("0.430"), employer_rate_pct=Decimal("0.602"))}
    result = calc("CA", 5000, {}, _FLAT_10_SLAB, work_state="QC", state_rate_map=state_rates)
    assert result.employee_esi == Decimal("0")
    assert result.employer_esi == Decimal("0")


def test_canada_quebec_federal_abatement_reduces_federal_tax():
    result_qc = calc("CA", 5000, {}, _FLAT_10_SLAB, work_state="QC")
    result_on = calc("CA", 5000, {}, _FLAT_10_SLAB, work_state="ON")
    assert result_qc.federal_income_tax < result_on.federal_income_tax
    # Pre-abatement annual federal tax is 4144.66 (same inputs as the CEA
    # credit test above); 16.5% abatement -> 4144.66*0.835 = 3460.7911
    # -> 3460.79 -> /12 = 288.40.
    assert result_qc.federal_income_tax == Decimal("288.40")
    assert result_on.federal_income_tax == Decimal("345.39")


def test_canada_territorial_payroll_tax_nwt():
    state_rates = {"nwt_payroll_tax": Rate("nwt_payroll_tax", employee_rate_pct=Decimal("2"))}
    result = calc("CA", 5000, {}, _FLAT_10_SLAB, work_state="NT", state_rate_map=state_rates)
    # annual 60000 * 2% / 12 = 100.00
    assert result.local_tax == Decimal("100.00")
    # Must be folded into tds (and therefore net_pay) — not left orphaned.
    assert result.tds == result.federal_income_tax + result.local_tax
    assert result.net_pay == Decimal("4554.61")  # 5000 - (345.39 + 100.00)


def test_canada_territorial_payroll_tax_nunavut():
    state_rates = {"nu_payroll_tax": Rate("nu_payroll_tax", employee_rate_pct=Decimal("2"))}
    result = calc("CA", 5000, {}, _FLAT_10_SLAB, work_state="NU", state_rate_map=state_rates)
    assert result.local_tax == Decimal("100.00")


def test_canada_territorial_payroll_tax_zero_outside_territories():
    # A stray nwt_payroll_tax row must never leak into a non-territory
    # province's calculation.
    state_rates = {"nwt_payroll_tax": Rate("nwt_payroll_tax", employee_rate_pct=Decimal("2"))}
    result = calc("CA", 5000, {}, _FLAT_10_SLAB, work_state="ON", state_rate_map=state_rates)
    assert result.local_tax == Decimal("0")


def test_canada_wcb_employer_levy_via_employer_tax_profile():
    profiles = {"WCB": EmployerTaxProfileStub(taxable_wage_base=Decimal("50000"), employer_rate_pct=Decimal("2.5"))}
    result = calc("CA", 5000, {}, _FLAT_10_SLAB, employer_tax_profiles=profiles)
    # annual 60000 capped at wage base 50000 -> 50000 * 2.5% / 12 = 104.17
    assert result.employer_sui == Decimal("104.17")


def test_canada_wcb_zero_when_no_profile_configured():
    result = calc("CA", 5000, {}, _FLAT_10_SLAB)
    assert result.employer_sui == Decimal("0")


def test_canada_td1_claim_amount_overrides_dynamic_bpaf():
    result = calc("CA", 5000, {}, _FLAT_10_SLAB, td1_claim_amount=Decimal("20000"))
    # taxable = 60000 - 20000 (TD1, not the default 16452 BPAF) = 40000
    # * 10% = 4000.00, less CEA credit 210.14 = 3789.86 -> /12 = 315.82
    assert result.federal_income_tax == Decimal("315.82")


def test_canada_td1_claim_amount_zero_is_honored_not_treated_as_unset():
    # An employee who explicitly claims $0 must get $0 BPA, not silently
    # fall back to the dynamic default — only a real TD1 of None means
    # "no TD1 on file."
    result = calc("CA", 5000, {}, _FLAT_10_SLAB, td1_claim_amount=Decimal("0"))
    # taxable = 60000 - 0 = 60000 * 10% = 6000.00, less CEA 210.14 =
    # 5789.86 -> /12 = 482.49
    assert result.federal_income_tax == Decimal("482.49")


def test_canada_no_td1_falls_back_to_dynamic_bpaf():
    result_no_td1 = calc("CA", 5000, {}, _FLAT_10_SLAB, td1_claim_amount=None)
    result_default = calc("CA", 5000, {}, _FLAT_10_SLAB)
    assert result_no_td1.federal_income_tax == result_default.federal_income_tax == Decimal("345.39")


# ── ZP-TAX-CA-2026-001 §18: provincial TD1 / Quebec TP-1015.3-V overrides ──

def test_canada_provincial_td1_claim_amount_overrides_provincial_bpa():
    provincial_rates = {"provincial_bpa": Rate("provincial_bpa", flat_amount=Decimal("12989"))}
    result = calc(
        "CA", 5000, {}, _FLAT_10_SLAB, work_state="ON",
        state_slabs=_FLAT_10_SLAB, state_rate_map=provincial_rates,
        provincial_td1_claim_amount=Decimal("15000"),
    )
    # taxable = 60000 - 15000 (TD1, not the configured 12989 BPA) = 45000
    # * 10% = 4500.00 -> /12 = 375.00
    assert result.state_income_tax == Decimal("375.00")


def test_canada_provincial_td1_claim_amount_zero_is_honored():
    provincial_rates = {"provincial_bpa": Rate("provincial_bpa", flat_amount=Decimal("12989"))}
    result = calc(
        "CA", 5000, {}, _FLAT_10_SLAB, work_state="ON",
        state_slabs=_FLAT_10_SLAB, state_rate_map=provincial_rates,
        provincial_td1_claim_amount=Decimal("0"),
    )
    # taxable = 60000 - 0 = 60000 * 10% = 6000.00 -> /12 = 500.00
    assert result.state_income_tax == Decimal("500.00")


def test_canada_no_provincial_td1_falls_back_to_provincial_bpa():
    provincial_rates = {"provincial_bpa": Rate("provincial_bpa", flat_amount=Decimal("10000"))}
    result_no_td1 = calc(
        "CA", 5000, {}, _FLAT_10_SLAB, work_state="ON",
        state_slabs=_FLAT_10_SLAB, state_rate_map=provincial_rates, provincial_td1_claim_amount=None,
    )
    result_default = calc(
        "CA", 5000, {}, _FLAT_10_SLAB, work_state="ON",
        state_slabs=_FLAT_10_SLAB, state_rate_map=provincial_rates,
    )
    assert result_no_td1.state_income_tax == result_default.state_income_tax == Decimal("416.67")


def test_canada_qc_tp1015_claim_amount_overrides_quebec_bpa():
    state_rates = {"quebec_bpa": Rate("quebec_bpa", flat_amount=Decimal("18952"))}
    result = calc(
        "CA", 5000, {}, _FLAT_10_SLAB, work_state="QC",
        state_slabs=_FLAT_10_SLAB, state_rate_map=state_rates,
        qc_tp1015_claim_amount=Decimal("10000"),
    )
    # taxable = 60000 - 10000 (TP-1015.3-V, not the configured 18952 BPA)
    # = 50000 * 10% = 5000.00 -> /12 = 416.67
    assert result.state_income_tax == Decimal("416.67")


def test_canada_no_qc_tp1015_falls_back_to_quebec_bpa():
    state_rates = {"quebec_bpa": Rate("quebec_bpa", flat_amount=Decimal("18952"))}
    result_no_claim = calc(
        "CA", 5000, {}, _FLAT_10_SLAB, work_state="QC",
        state_slabs=_FLAT_10_SLAB, state_rate_map=state_rates, qc_tp1015_claim_amount=None,
    )
    result_default = calc(
        "CA", 5000, {}, _FLAT_10_SLAB, work_state="QC",
        state_slabs=_FLAT_10_SLAB, state_rate_map=state_rates,
    )
    assert result_no_claim.state_income_tax == result_default.state_income_tax == Decimal("342.07")


def test_canada_td1_additional_tax_added_to_tds():
    result = calc("CA", 5000, {}, _FLAT_10_SLAB, td1_additional_tax=Decimal("50"))
    # 345.39 (federal, unchanged from the plain default-BPAF test) + 50
    # flat additional withholding, never touching the statutory base.
    assert result.tds == Decimal("395.39")
    assert result.federal_income_tax == Decimal("345.39")


def test_canada_td1_additional_tax_zero_when_unset():
    result = calc("CA", 5000, {}, _FLAT_10_SLAB)
    assert result.tds == Decimal("345.39")


def test_canada_cpt30_stopped_suppresses_cpp_and_cpp2():
    rates = {"cpp": Rate("cpp", employee_rate_pct=Decimal("5.95"), employer_rate_pct=Decimal("5.95"))}
    result = calc("CA", 7000, rates, _FLAT_10_SLAB, cpp_qpp_election_status="STOPPED")
    assert result.social_security == Decimal("0")
    assert result.employer_social_security == Decimal("0")
    assert result.cpp2 == Decimal("0")
    assert result.employer_cpp2 == Decimal("0")


def test_canada_cpt30_active_does_not_suppress_cpp():
    rates = {"cpp": Rate("cpp", employee_rate_pct=Decimal("5.95"), employer_rate_pct=Decimal("5.95"))}
    result = calc("CA", 7000, rates, _FLAT_10_SLAB, cpp_qpp_election_status="ACTIVE")
    assert result.social_security > Decimal("0")


def test_canada_cpt30_stopped_does_not_affect_ei():
    # CPT30 is a CPP/QPP-specific election — EI must be untouched.
    rates = {
        "cpp": Rate("cpp", employee_rate_pct=Decimal("5.95"), employer_rate_pct=Decimal("5.95")),
        "ei": Rate("ei", employee_rate_pct=Decimal("1.63"), employer_rate_pct=Decimal("2.282")),
    }
    result = calc("CA", 7000, rates, _FLAT_10_SLAB, cpp_qpp_election_status="STOPPED")
    assert result.social_security == Decimal("0")
    assert result.employee_esi > Decimal("0")


def test_canada_cpp2_employer_side_computed_from_own_rate():
    # $8,000/month = $96,000/year, crosses YMPE ($74,600) and sits inside
    # the CPP2 corridor up to YAMPE ($85,000) -> full $10,400 corridor.
    # Employee and employer rates configured independently (rate_pair),
    # matching how CPP's own first-tier rate is already split.
    rates = {"cpp2_rate": Rate("cpp2_rate", employee_rate_pct=Decimal("4.00"), employer_rate_pct=Decimal("4.00"))}
    result = calc("CA", 8000, rates, _FLAT_10_SLAB)
    assert result.cpp2 == Decimal("34.67")           # 10400 * 4% / 12
    assert result.employer_cpp2 == Decimal("34.67")


def test_canada_cpp2_employee_and_employer_rates_resolved_independently():
    rates = {"cpp2_rate": Rate("cpp2_rate", employee_rate_pct=Decimal("4.00"), employer_rate_pct=Decimal("3.50"))}
    result = calc("CA", 8000, rates, _FLAT_10_SLAB)
    assert result.cpp2 == Decimal("34.67")            # 10400 * 4.00% / 12
    assert result.employer_cpp2 == Decimal("30.33")   # 10400 * 3.50% / 12


def test_canada_cpp2_employer_side_never_reduces_net_pay():
    # employer_cpp2 is an employer-side contribution, not an employee
    # deduction — engine/standard.py's total_employee_deductions must
    # never include it (mirrors employer_social_security's own contract).
    # Two very different employer rates, same employee rate: net_pay must
    # be identical regardless, since only the employee side can affect it.
    rates_low = {"cpp2_rate": Rate("cpp2_rate", employee_rate_pct=Decimal("4.00"), employer_rate_pct=Decimal("4.00"))}
    rates_high = {"cpp2_rate": Rate("cpp2_rate", employee_rate_pct=Decimal("4.00"), employer_rate_pct=Decimal("20.00"))}
    result_low = calc("CA", 8000, rates_low, _FLAT_10_SLAB)
    result_high = calc("CA", 8000, rates_high, _FLAT_10_SLAB)
    assert result_low.net_pay == result_high.net_pay
    assert result_low.cpp2 == result_high.cpp2 == Decimal("34.67")
    assert result_low.employer_cpp2 == Decimal("34.67")
    assert result_high.employer_cpp2 == Decimal("173.33")  # 10400 * 20% / 12


# ── Canada CPP/CPP2/EI real YTD accumulator (ctx.ytd_* fields) ──────────
# Dormant in production behind engine/countries/shared.py's
# _YTD_ACCUMULATOR_ENABLED_COUNTRIES (empty today) — these tests exercise
# the engine directly via ctx.ytd_* fields, independent of that
# service-layer rollout switch, proving the calculation itself is correct
# whenever it IS wired.

def test_canada_ytd_pensionable_room_mid_period_crossing():
    # Employee already has $74,000 YTD pensionable (room: $600 left to
    # YMPE $74,600) and $1,100 of a $1,200 (overridden, clean) annual
    # basic exemption already used ($100/mo remaining). A $8,000 gross
    # period both fills the remaining first-layer room AND crosses into
    # the CPP2 corridor within the SAME period.
    rates = {
        "cpp": Rate("cpp", employee_rate_pct=Decimal("5.95"), employer_rate_pct=Decimal("5.95")),
        "cpp_basic_exemption": Rate("cpp_basic_exemption", flat_amount=Decimal("1200")),
    }
    result = calc(
        "CA", 8000, rates, _FLAT_10_SLAB,
        ytd_pensionable_earnings=Decimal("74000"), ytd_cpp2_pensionable_earnings=Decimal("0"),
        ytd_insurable_earnings=Decimal("0"), ytd_basic_exemption_used=Decimal("1100"),
    )
    # period_first_layer_pensionable = min(8000, room=600) - exemption(100) = 500
    assert result.social_security == Decimal("29.75")             # 500 * 5.95%
    assert result.employer_social_security == Decimal("29.75")
    assert result.ytd_pensionable_earnings == Decimal("74500.00")  # 74000 + 500
    assert result.ytd_basic_exemption_used == Decimal("1200.00")   # 1100 + 100
    # period_gross_over_ympe = 8000 - 600(room) = 7400, fits inside the
    # full $10,400 CPP2 corridor (ytd_cpp2 before = 0) with room to spare.
    assert result.cpp2 == Decimal("296.00")                        # 7400 * 4% (fallback rate)
    assert result.ytd_cpp2_pensionable_earnings == Decimal("7400.00")


def test_canada_ytd_cpp2_corridor_fills_exactly_at_boundary():
    # First layer already fully maxed (YTD == YMPE); CPP2 corridor has
    # exactly $400 of its $10,400 remaining — this period's $8,000 gross
    # must cap CPP2 pensionable at exactly that $400, not spill over.
    result = calc(
        "CA", 8000, {}, _FLAT_10_SLAB,
        ytd_pensionable_earnings=Decimal("74600"), ytd_cpp2_pensionable_earnings=Decimal("10000"),
        ytd_insurable_earnings=Decimal("0"), ytd_basic_exemption_used=Decimal("3500"),
    )
    assert result.social_security == Decimal("0")           # first-layer room is 0
    assert result.cpp2 == Decimal("16.00")                   # 400 * 4% (fallback rate)
    assert result.ytd_cpp2_pensionable_earnings == Decimal("10400.00")  # exactly the $10,400 cap


def test_canada_ytd_ei_stays_zero_after_mie_reached_regardless_of_raise():
    # EI already at its $68,900 MIE for the year; a raise to $10,000/mo
    # must not reopen room — EI stays $0. CPP is a SEPARATE accumulator
    # and must be completely unaffected by EI being maxed out.
    rates = {
        "cpp": Rate("cpp", employee_rate_pct=Decimal("5.95"), employer_rate_pct=Decimal("5.95")),
        "ei": Rate("ei", employee_rate_pct=Decimal("1.63"), employer_rate_pct=Decimal("2.282")),
        "cpp_basic_exemption": Rate("cpp_basic_exemption", flat_amount=Decimal("1200")),
    }
    result = calc(
        "CA", 10000, rates, _FLAT_10_SLAB,
        ytd_pensionable_earnings=Decimal("50000"), ytd_cpp2_pensionable_earnings=Decimal("0"),
        ytd_insurable_earnings=Decimal("68900"), ytd_basic_exemption_used=Decimal("1100"),
    )
    assert result.employee_esi == Decimal("0")
    assert result.employer_esi == Decimal("0")
    assert result.ytd_insurable_earnings == Decimal("68900.00")  # unchanged, still capped
    # CPP unaffected by EI's own accumulator being maxed:
    # room = 74600-50000=24600, period_pensionable = min(10000,24600)-100 = 9900
    assert result.social_security == Decimal("589.05")  # 9900 * 5.95%
    assert result.ytd_pensionable_earnings == Decimal("59900.00")  # 50000 + 9900


def test_canada_ytd_cpt30_stopped_freezes_accumulator_not_just_withheld_amounts():
    # CPT30-stopped must not just zero the withheld $, it must also leave
    # YTD unchanged — a later un-stopped period must see the SAME room as
    # if the stopped period never happened, not room reduced by earnings
    # nothing was ever collected against.
    rates = {
        "cpp": Rate("cpp", employee_rate_pct=Decimal("5.95"), employer_rate_pct=Decimal("5.95")),
        "ei": Rate("ei", employee_rate_pct=Decimal("1.63"), employer_rate_pct=Decimal("2.282")),
    }
    result = calc(
        "CA", 7000, rates, _FLAT_10_SLAB, cpp_qpp_election_status="STOPPED",
        ytd_pensionable_earnings=Decimal("50000"), ytd_cpp2_pensionable_earnings=Decimal("0"),
        ytd_insurable_earnings=Decimal("30000"), ytd_basic_exemption_used=Decimal("3500"),
    )
    assert result.social_security == Decimal("0")
    assert result.cpp2 == Decimal("0")
    assert result.ytd_pensionable_earnings == Decimal("50000")   # unchanged, not grown
    assert result.ytd_cpp2_pensionable_earnings == Decimal("0")  # unchanged
    # EI is untouched by CPT30 (a CPP/QPP-only election) — continues normally.
    assert result.employee_esi > Decimal("0")
    assert result.ytd_insurable_earnings == Decimal("37000.00")  # 30000 + 7000


# ── CPP/QPP age 18/70 mandatory window (Phase 7) ─────────────────────────
# Dormant behind shared._CA_AGE_GATED_CPP_ENABLED_COUNTRIES — reuses the
# same "freeze, don't just zero the withheld $" mechanism CPT30 already
# proved above.

def test_age_gated_cpp_stopped_below_min_age():
    assert _canada._is_age_gated_cpp_stopped(date(2010, 6, 15), date(2026, 1, 1)) is True  # age 15


def test_age_gated_cpp_not_stopped_exactly_at_18th_birthday():
    assert _canada._is_age_gated_cpp_stopped(date(2008, 1, 1), date(2026, 1, 1)) is False  # turns 18 on pay_date


def test_age_gated_cpp_not_stopped_between_18_and_70():
    assert _canada._is_age_gated_cpp_stopped(date(1980, 6, 15), date(2026, 1, 1)) is False  # age 45


def test_age_gated_cpp_stopped_exactly_at_70th_birthday():
    assert _canada._is_age_gated_cpp_stopped(date(1956, 1, 1), date(2026, 1, 1)) is True  # turns 70 on pay_date


def test_age_gated_cpp_stopped_above_70():
    assert _canada._is_age_gated_cpp_stopped(date(1950, 6, 15), date(2026, 1, 1)) is True  # age 75


def test_age_gated_cpp_false_when_inputs_missing():
    assert _canada._is_age_gated_cpp_stopped(None, date(2026, 1, 1)) is False
    assert _canada._is_age_gated_cpp_stopped(date(2010, 1, 1), None) is False


def test_calc_age_gating_dormant_by_default():
    rates = {"cpp": Rate("cpp", employee_rate_pct=Decimal("5.95"), employer_rate_pct=Decimal("5.95"))}
    result = calc("CA", 5000, rates, _FLAT_10_SLAB, date_of_birth=date(2015, 1, 1), pay_date=date(2026, 1, 1))
    assert result.social_security > Decimal("0")  # switch off -> date_of_birth never consumed


def test_calc_age_gating_stops_cpp_for_minor_when_enabled():
    shared._CA_AGE_GATED_CPP_ENABLED_COUNTRIES.add("CA")
    rates = {"cpp": Rate("cpp", employee_rate_pct=Decimal("5.95"), employer_rate_pct=Decimal("5.95"))}
    result = calc("CA", 5000, rates, _FLAT_10_SLAB, date_of_birth=date(2015, 1, 1), pay_date=date(2026, 1, 1))
    assert result.social_security == Decimal("0")
    assert result.employer_social_security == Decimal("0")


def test_calc_age_gating_stops_cpp_for_senior_when_enabled():
    shared._CA_AGE_GATED_CPP_ENABLED_COUNTRIES.add("CA")
    rates = {"cpp": Rate("cpp", employee_rate_pct=Decimal("5.95"), employer_rate_pct=Decimal("5.95"))}
    result = calc("CA", 5000, rates, _FLAT_10_SLAB, date_of_birth=date(1950, 1, 1), pay_date=date(2026, 1, 1))
    assert result.social_security == Decimal("0")


def test_calc_age_gating_does_not_affect_working_age_employee():
    shared._CA_AGE_GATED_CPP_ENABLED_COUNTRIES.add("CA")
    rates = {"cpp": Rate("cpp", employee_rate_pct=Decimal("5.95"), employer_rate_pct=Decimal("5.95"))}
    result = calc("CA", 5000, rates, _FLAT_10_SLAB, date_of_birth=date(1980, 1, 1), pay_date=date(2026, 1, 1))
    assert result.social_security > Decimal("0")


def test_calc_age_gating_freezes_ytd_when_stopped():
    shared._CA_AGE_GATED_CPP_ENABLED_COUNTRIES.add("CA")
    rates = {"cpp": Rate("cpp", employee_rate_pct=Decimal("5.95"), employer_rate_pct=Decimal("5.95"))}
    result = calc(
        "CA", 5000, rates, _FLAT_10_SLAB, date_of_birth=date(1950, 1, 1), pay_date=date(2026, 1, 1),
        ytd_pensionable_earnings=Decimal("50000"), ytd_basic_exemption_used=Decimal("1500"),
    )
    assert result.ytd_pensionable_earnings == Decimal("50000")  # unchanged, not advanced


# ── CPP/QPP first-layer base/first-additional breakdown (AC-11, Phase 7) ─
# Dormant behind shared._CA_CPP_COMPONENT_SPLIT_ENABLED_COUNTRIES — the
# combined "cpp"/"qpp" row remains the sole source of truth for the
# actual deduction (social_security/employer_social_security) in every
# case; these tests confirm the breakdown never changes that deduction,
# only proportions it after the fact.

def test_cpp_component_split_dormant_by_default():
    rates = {
        "cpp": Rate("cpp", employee_rate_pct=Decimal("5.95"), employer_rate_pct=Decimal("5.95")),
        "cpp_base": Rate(employee_rate_pct=Decimal("4.00"), employer_rate_pct=Decimal("4.00")),
        "cpp_first_additional": Rate(employee_rate_pct=Decimal("1.00"), employer_rate_pct=Decimal("1.00")),
    }
    result = calc("CA", 7000, rates, _FLAT_10_SLAB)
    assert result.social_security == Decimal("352.54")  # unaffected by switch being off
    assert result.cpp_base_amount == Decimal("0")
    assert result.cpp_first_additional_amount == Decimal("0")


def test_cpp_component_split_proportions_combined_amount_when_enabled():
    shared._CA_CPP_COMPONENT_SPLIT_ENABLED_COUNTRIES.add("CA")
    rates = {
        "cpp": Rate("cpp", employee_rate_pct=Decimal("5.95"), employer_rate_pct=Decimal("5.95")),
        "cpp_base": Rate(employee_rate_pct=Decimal("4.00"), employer_rate_pct=Decimal("4.00")),
        "cpp_first_additional": Rate(employee_rate_pct=Decimal("1.00"), employer_rate_pct=Decimal("1.00")),
    }
    result = calc("CA", 7000, rates, _FLAT_10_SLAB)
    assert result.social_security == Decimal("352.54")  # combined deduction UNCHANGED
    assert result.cpp_base_amount == Decimal("282.03")
    assert result.cpp_first_additional_amount == Decimal("70.51")
    assert result.cpp_base_amount + result.cpp_first_additional_amount == result.social_security
    assert result.employer_cpp_base == Decimal("282.03")
    assert result.employer_cpp_first_additional == Decimal("70.51")


def test_cpp_component_split_zero_when_split_rows_not_configured():
    shared._CA_CPP_COMPONENT_SPLIT_ENABLED_COUNTRIES.add("CA")
    rates = {"cpp": Rate("cpp", employee_rate_pct=Decimal("5.95"), employer_rate_pct=Decimal("5.95"))}
    result = calc("CA", 7000, rates, _FLAT_10_SLAB)
    assert result.social_security == Decimal("352.54")
    assert result.cpp_base_amount == Decimal("0")
    assert result.cpp_first_additional_amount == Decimal("0")


def test_cpp_component_split_zero_when_cpt30_stopped():
    shared._CA_CPP_COMPONENT_SPLIT_ENABLED_COUNTRIES.add("CA")
    rates = {
        "cpp": Rate("cpp", employee_rate_pct=Decimal("5.95"), employer_rate_pct=Decimal("5.95")),
        "cpp_base": Rate(employee_rate_pct=Decimal("4.00"), employer_rate_pct=Decimal("4.00")),
        "cpp_first_additional": Rate(employee_rate_pct=Decimal("1.00"), employer_rate_pct=Decimal("1.00")),
    }
    result = calc("CA", 7000, rates, _FLAT_10_SLAB, cpp_qpp_election_status="STOPPED")
    assert result.social_security == Decimal("0")
    assert result.cpp_base_amount == Decimal("0")
    assert result.cpp_first_additional_amount == Decimal("0")


def test_qpp_component_split_uses_qpp_prefixed_keys_for_quebec():
    shared._CA_CPP_COMPONENT_SPLIT_ENABLED_COUNTRIES.add("CA")
    state_rates = {
        "qpp": Rate("qpp", employee_rate_pct=Decimal("6.30"), employer_rate_pct=Decimal("6.30")),
        "qpp_base": Rate(employee_rate_pct=Decimal("5.00"), employer_rate_pct=Decimal("5.00")),
        "qpp_first_additional": Rate(employee_rate_pct=Decimal("1.00"), employer_rate_pct=Decimal("1.00")),
    }
    result = calc("CA", 7000, {}, _FLAT_10_SLAB, work_state="QC", state_rate_map=state_rates)
    assert result.social_security == Decimal("373.28")
    assert result.cpp_base_amount == Decimal("311.07")
    assert result.cpp_first_additional_amount == Decimal("62.21")


def test_canada_ytd_basic_exemption_never_exceeds_annual_total():
    # Only $50 of the $1,200 annual exemption remains (irregular pay
    # history) — this period's exemption must be capped at that $50, not
    # the usual $100/mo pro-rata share.
    rates = {"cpp_basic_exemption": Rate("cpp_basic_exemption", flat_amount=Decimal("1200"))}
    result = calc(
        "CA", 8000, rates, _FLAT_10_SLAB,
        ytd_pensionable_earnings=Decimal("0"), ytd_cpp2_pensionable_earnings=Decimal("0"),
        ytd_insurable_earnings=Decimal("0"), ytd_basic_exemption_used=Decimal("1150"),
    )
    assert result.ytd_basic_exemption_used == Decimal("1200.00")  # capped, not 1250


def test_canada_ytd_quebec_qpp_qpip_share_the_same_accumulator_mechanism():
    # Same ctx.ytd_* fields drive QPP/QPIP for a Quebec employee —
    # confirms the mechanism isn't CPP-name-specific. QPIP already at its
    # (Quebec-specific) MIE cap; QPP still has first-layer room.
    state_rates = {
        "qpp": Rate("qpp", employee_rate_pct=Decimal("6.30"), employer_rate_pct=Decimal("6.30")),
        "qpip": Rate("qpip", employee_rate_pct=Decimal("0.430"), employer_rate_pct=Decimal("0.602")),
        "qpip_mie": Rate("qpip_mie", flat_amount=Decimal("103000")),
    }
    result = calc(
        "CA", 8000, {}, _FLAT_10_SLAB, work_state="QC", state_rate_map=state_rates,
        ytd_pensionable_earnings=Decimal("74000"), ytd_cpp2_pensionable_earnings=Decimal("0"),
        ytd_insurable_earnings=Decimal("103000"), ytd_basic_exemption_used=Decimal("3500"),
    )
    assert result.employee_esi == Decimal("0")           # QPIP already at its MIE cap
    assert result.ytd_insurable_earnings == Decimal("103000.00")  # unchanged
    assert result.social_security > Decimal("0")          # QPP still has first-layer room


# ── Ontario EHT — org-level aggregate remuneration accumulator ──────────
# Dormant behind engine/countries/shared.py's
# _ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES (empty today) — these tests
# exercise canada.py directly via ctx.on_eht_ytd_remuneration_before,
# independent of that service-layer switch.

_ON_EHT_BANDS = [
    Slab(Decimal("0"), Decimal("200000"), Decimal("0.980"), rule_type="ON_EHT_BAND"),
    Slab(Decimal("200000"), Decimal("230000"), Decimal("1.101"), rule_type="ON_EHT_BAND"),
    Slab(Decimal("230000"), Decimal("260000"), Decimal("1.223"), rule_type="ON_EHT_BAND"),
    Slab(Decimal("260000"), Decimal("290000"), Decimal("1.344"), rule_type="ON_EHT_BAND"),
    Slab(Decimal("290000"), Decimal("320000"), Decimal("1.465"), rule_type="ON_EHT_BAND"),
    Slab(Decimal("320000"), Decimal("350000"), Decimal("1.586"), rule_type="ON_EHT_BAND"),
    Slab(Decimal("350000"), Decimal("380000"), Decimal("1.708"), rule_type="ON_EHT_BAND"),
    Slab(Decimal("380000"), Decimal("400000"), Decimal("1.829"), rule_type="ON_EHT_BAND"),
    Slab(Decimal("400000"), None, Decimal("1.950"), rule_type="ON_EHT_BAND"),
]


def test_on_eht_incremental_amount_above_exemption():
    state_rates = {"on_eht_exemption": Rate("on_eht_exemption", flat_amount=Decimal("1000000"))}
    result = calc(
        "CA", 50000, {}, _FLAT_10_SLAB, work_state="ON",
        state_slabs=_ON_EHT_BANDS, state_rate_map=state_rates,
        on_eht_ytd_remuneration_before=Decimal("1200000"),
    )
    # before: (1,200,000-1,000,000)*1.95% = 3900.00
    # after:  (1,250,000-1,000,000)*1.95% = 4875.00 -> period = 975.00
    assert result.employer_eht == Decimal("975.00")
    assert result.on_eht_ytd_remuneration_after == Decimal("1250000")


def test_on_eht_exemption_cliff_when_crossing_5m_phaseout():
    state_rates = {"on_eht_exemption": Rate("on_eht_exemption", flat_amount=Decimal("1000000"))}
    result = calc(
        "CA", 50000, {}, _FLAT_10_SLAB, work_state="ON",
        state_slabs=_ON_EHT_BANDS, state_rate_map=state_rates,
        on_eht_ytd_remuneration_before=Decimal("4980000"),
    )
    # before: total 4,980,000 < 5,000,000 -> exemption applies: (4,980,000-1,000,000)*1.95% = 77610.00
    # after:  total 5,030,000 >= 5,000,000 -> exemption phased out entirely: 5,030,000*1.95% = 98085.00
    assert result.employer_eht == Decimal("20475.00")


def test_on_eht_zero_for_non_ontario_employee():
    state_rates = {"on_eht_exemption": Rate("on_eht_exemption", flat_amount=Decimal("1000000"))}
    result = calc(
        "CA", 50000, {}, _FLAT_10_SLAB, work_state="BC",
        state_slabs=_ON_EHT_BANDS, state_rate_map=state_rates,
        on_eht_ytd_remuneration_before=Decimal("1200000"),
    )
    assert result.employer_eht == Decimal("0")
    assert result.on_eht_ytd_remuneration_after is None


def test_on_eht_zero_when_accumulator_not_wired():
    state_rates = {"on_eht_exemption": Rate("on_eht_exemption", flat_amount=Decimal("1000000"))}
    result = calc(
        "CA", 50000, {}, _FLAT_10_SLAB, work_state="ON",
        state_slabs=_ON_EHT_BANDS, state_rate_map=state_rates,
        on_eht_ytd_remuneration_before=None,
    )
    assert result.employer_eht == Decimal("0")
    assert result.on_eht_ytd_remuneration_after is None


def test_on_eht_zero_when_no_bands_configured():
    result = calc(
        "CA", 50000, {}, _FLAT_10_SLAB, work_state="ON",
        state_slabs=[], state_rate_map={},
        on_eht_ytd_remuneration_before=Decimal("1200000"),
    )
    assert result.employer_eht == Decimal("0")


# ── BC EHT, Manitoba HE Levy, NL HAPSET — same org-level accumulator,   ──
# ── generic exemption/notch/flat-on-total shape (ZP-TAX-CA-2026-001 §15) ─
# Dormant behind the same _ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES switch
# as Ontario EHT above — these exercise canada.py directly via each
# ctx.*_ytd_remuneration_before field.

_BC_EHT_RATES = {
    "bc_eht_exemption_threshold": Rate(flat_amount=Decimal("1000000")),
    "bc_eht_upper_threshold": Rate(flat_amount=Decimal("1500000")),
    "bc_eht_notch_rate": Rate(employer_rate_pct=Decimal("5.85")),
    "bc_eht_flat_rate": Rate(employer_rate_pct=Decimal("1.95")),
}
_BC_EHT_CHARITY_RATES = {
    "bc_eht_charity_exemption_threshold": Rate(flat_amount=Decimal("1500000")),
    "bc_eht_charity_upper_threshold": Rate(flat_amount=Decimal("4500000")),
    "bc_eht_charity_notch_rate": Rate(employer_rate_pct=Decimal("2.925")),
    "bc_eht_charity_flat_rate": Rate(employer_rate_pct=Decimal("1.95")),
}
_MB_HE_LEVY_RATES = {
    "mb_he_levy_exemption_threshold": Rate(flat_amount=Decimal("2500000")),
    "mb_he_levy_upper_threshold": Rate(flat_amount=Decimal("5000000")),
    "mb_he_levy_notch_rate": Rate(employer_rate_pct=Decimal("4.3")),
    "mb_he_levy_flat_rate": Rate(employer_rate_pct=Decimal("2.15")),
}
_NL_HAPSET_RATES = {
    "nl_hapset_exemption_threshold": Rate(flat_amount=Decimal("2000000")),
    "nl_hapset_flat_rate": Rate(employer_rate_pct=Decimal("2.0")),
}


def test_bc_eht_zero_below_exemption():
    result = calc(
        "CA", 50000, {}, _FLAT_10_SLAB, work_state="BC", state_rate_map=_BC_EHT_RATES,
        bc_eht_ytd_remuneration_before=Decimal("900000"),
    )
    # before=900,000, after=950,000 — both <= $1M exemption
    assert result.employer_bc_eht == Decimal("0")
    assert result.bc_eht_ytd_remuneration_after == Decimal("950000")


def test_bc_eht_notch_tier_amount():
    result = calc(
        "CA", 50000, {}, _FLAT_10_SLAB, work_state="BC", state_rate_map=_BC_EHT_RATES,
        bc_eht_ytd_remuneration_before=Decimal("1100000"),
    )
    # before: (1,100,000-1,000,000)*5.85% = 5,850.00
    # after:  (1,150,000-1,000,000)*5.85% = 8,775.00 -> period = 2,925.00
    assert result.employer_bc_eht == Decimal("2925.00")


def test_bc_eht_crossing_1_5m_switches_to_flat_on_total():
    result = calc(
        "CA", 50000, {}, _FLAT_10_SLAB, work_state="BC", state_rate_map=_BC_EHT_RATES,
        bc_eht_ytd_remuneration_before=Decimal("1480000"),
    )
    # before: (1,480,000-1,000,000)*5.85% = 28,080.00
    # after:  1,530,000 > $1.5M -> flat 1.95% * 1,530,000 = 29,835.00 -> period = 1,755.00
    assert result.employer_bc_eht == Decimal("1755.00")


def test_bc_eht_charity_variant_uses_its_own_thresholds():
    combined_rates = {**_BC_EHT_RATES, **_BC_EHT_CHARITY_RATES}
    result = calc(
        "CA", 200000, {}, _FLAT_10_SLAB, work_state="BC", state_rate_map=combined_rates,
        bc_eht_ytd_remuneration_before=Decimal("2000000"),
        bc_eht_employer_classification="CHARITY_NONPROFIT",
    )
    # Ordinary thresholds would already be in the flat 1.95%-of-total tier
    # at $2M — proving this used the CHARITY notch tier instead:
    # before: (2,000,000-1,500,000)*2.925% = 14,625.00
    # after:  (2,200,000-1,500,000)*2.925% = 20,475.00 -> period = 5,850.00
    assert result.employer_bc_eht == Decimal("5850.00")


def test_bc_eht_charity_crossing_4_5m_switches_to_flat_on_total():
    result = calc(
        "CA", 200000, {}, _FLAT_10_SLAB, work_state="BC", state_rate_map=_BC_EHT_CHARITY_RATES,
        bc_eht_ytd_remuneration_before=Decimal("4400000"),
        bc_eht_employer_classification="CHARITY_NONPROFIT",
    )
    # before: (4,400,000-1,500,000)*2.925% = 84,825.00
    # after:  4,600,000 > $4.5M -> flat 1.95% * 4,600,000 = 89,700.00 -> period = 4,875.00
    assert result.employer_bc_eht == Decimal("4875.00")


def test_bc_eht_default_classification_is_ordinary_not_charity():
    combined_rates = {**_BC_EHT_RATES, **_BC_EHT_CHARITY_RATES}
    result = calc(
        "CA", 50000, {}, _FLAT_10_SLAB, work_state="BC", state_rate_map=combined_rates,
        bc_eht_ytd_remuneration_before=Decimal("1100000"),
        bc_eht_employer_classification=None,
    )
    assert result.employer_bc_eht == Decimal("2925.00")  # ordinary notch, not charity's


def test_bc_eht_zero_for_non_bc_employee():
    result = calc(
        "CA", 50000, {}, _FLAT_10_SLAB, work_state="ON", state_rate_map=_BC_EHT_RATES,
        bc_eht_ytd_remuneration_before=Decimal("1100000"),
    )
    assert result.employer_bc_eht == Decimal("0")
    assert result.bc_eht_ytd_remuneration_after is None


def test_bc_eht_zero_when_accumulator_not_wired():
    result = calc(
        "CA", 50000, {}, _FLAT_10_SLAB, work_state="BC", state_rate_map=_BC_EHT_RATES,
        bc_eht_ytd_remuneration_before=None,
    )
    assert result.employer_bc_eht == Decimal("0")


def test_mb_he_levy_zero_below_exemption():
    result = calc(
        "CA", 200000, {}, _FLAT_10_SLAB, work_state="MB", state_rate_map=_MB_HE_LEVY_RATES,
        mb_he_levy_ytd_remuneration_before=Decimal("2300000"),
    )
    # before=2,300,000, after=2,500,000 — after is exactly at the exemption
    # threshold, which is still "<=" (exempt), so both resolve to 0.
    assert result.employer_mb_he_levy == Decimal("0")


def test_mb_he_levy_notch_tier_amount():
    result = calc(
        "CA", 200000, {}, _FLAT_10_SLAB, work_state="MB", state_rate_map=_MB_HE_LEVY_RATES,
        mb_he_levy_ytd_remuneration_before=Decimal("3000000"),
    )
    # before: (3,000,000-2,500,000)*4.3% = 21,500.00
    # after:  (3,200,000-2,500,000)*4.3% = 30,100.00 -> period = 8,600.00
    assert result.employer_mb_he_levy == Decimal("8600.00")


def test_mb_he_levy_crossing_5m_switches_to_flat_on_total():
    result = calc(
        "CA", 200000, {}, _FLAT_10_SLAB, work_state="MB", state_rate_map=_MB_HE_LEVY_RATES,
        mb_he_levy_ytd_remuneration_before=Decimal("4900000"),
    )
    # before: (4,900,000-2,500,000)*4.3% = 103,200.00
    # after:  5,100,000 > $5M -> flat 2.15% * 5,100,000 = 109,650.00 -> period = 6,450.00
    assert result.employer_mb_he_levy == Decimal("6450.00")


def test_mb_he_levy_zero_for_non_mb_employee():
    result = calc(
        "CA", 200000, {}, _FLAT_10_SLAB, work_state="ON", state_rate_map=_MB_HE_LEVY_RATES,
        mb_he_levy_ytd_remuneration_before=Decimal("3000000"),
    )
    assert result.employer_mb_he_levy == Decimal("0")
    assert result.mb_he_levy_ytd_remuneration_after is None


def test_nl_hapset_zero_below_exemption():
    result = calc(
        "CA", 100000, {}, _FLAT_10_SLAB, work_state="NL", state_rate_map=_NL_HAPSET_RATES,
        nl_hapset_ytd_remuneration_before=Decimal("1800000"),
    )
    # before=1,800,000, after=1,900,000 — both <= $2M exemption
    assert result.employer_nl_hapset == Decimal("0")


def test_nl_hapset_flat_rate_on_excess_no_upper_tier():
    result = calc(
        "CA", 200000, {}, _FLAT_10_SLAB, work_state="NL", state_rate_map=_NL_HAPSET_RATES,
        nl_hapset_ytd_remuneration_before=Decimal("2200000"),
    )
    # before: (2,200,000-2,000,000)*2% = 4,000.00
    # after:  (2,400,000-2,000,000)*2% = 8,000.00 -> period = 4,000.00
    assert result.employer_nl_hapset == Decimal("4000.00")


def test_nl_hapset_zero_for_non_nl_employee():
    result = calc(
        "CA", 200000, {}, _FLAT_10_SLAB, work_state="NS", state_rate_map=_NL_HAPSET_RATES,
        nl_hapset_ytd_remuneration_before=Decimal("2200000"),
    )
    assert result.employer_nl_hapset == Decimal("0")
    assert result.nl_hapset_ytd_remuneration_after is None


# ── Quebec HSF and labour standards — Phase 5 org/employer contributions ─
# HSF is a DIFFERENT shape from the notch levies above: the rate itself
# slides with total, and applies to the WHOLE total from $0 — there is no
# exemption tier. Labour standards is a per-employee capped contribution,
# no org accumulator at all.

_QC_HSF_GENERAL_RATES = {
    "qc_hsf_threshold_low": Rate(flat_amount=Decimal("1000000")),
    "qc_hsf_threshold_high": Rate(flat_amount=Decimal("7800000")),
    "qc_hsf_general_low_rate": Rate(employer_rate_pct=Decimal("1.65")),
    "qc_hsf_general_mid_base": Rate(employer_rate_pct=Decimal("1.2662")),
    "qc_hsf_general_mid_slope": Rate(employer_rate_pct=Decimal("0.3838")),
    "qc_hsf_general_high_rate": Rate(employer_rate_pct=Decimal("4.26")),
}
_QC_HSF_PRIMARY_RATES = {
    "qc_hsf_threshold_low": Rate(flat_amount=Decimal("1000000")),
    "qc_hsf_threshold_high": Rate(flat_amount=Decimal("7800000")),
    "qc_hsf_primary_low_rate": Rate(employer_rate_pct=Decimal("1.25")),
    "qc_hsf_primary_mid_base": Rate(employer_rate_pct=Decimal("0.8074")),
    "qc_hsf_primary_mid_slope": Rate(employer_rate_pct=Decimal("0.4426")),
    "qc_hsf_primary_high_rate": Rate(employer_rate_pct=Decimal("4.26")),
}
_QC_HSF_PUBLIC_RATES = {"qc_hsf_public_rate": Rate(employer_rate_pct=Decimal("4.26"))}
_QC_LABOUR_STANDARDS_RATES = {
    "qc_labour_standards_cap": Rate(flat_amount=Decimal("103000")),
    "qc_labour_standards_rate": Rate(employer_rate_pct=Decimal("0.07")),
}


def test_qc_hsf_low_tier_applies_flat_rate_to_whole_total():
    result = calc(
        "CA", 100000, {}, _FLAT_10_SLAB, work_state="QC", state_rate_map=_QC_HSF_GENERAL_RATES,
        qc_hsf_ytd_remuneration_before=Decimal("500000"),
    )
    # No exemption tier — 1.65% applies to the WHOLE total, not an excess.
    # before: 500,000*1.65% = 8,250.00; after: 600,000*1.65% = 9,900.00
    assert result.employer_qc_hsf == Decimal("1650.00")
    assert result.qc_hsf_ytd_remuneration_after == Decimal("600000")


def test_qc_hsf_crossing_into_sliding_mid_tier():
    result = calc(
        "CA", 200000, {}, _FLAT_10_SLAB, work_state="QC", state_rate_map=_QC_HSF_GENERAL_RATES,
        qc_hsf_ytd_remuneration_before=Decimal("900000"),
    )
    # before: 900,000*1.65% = 14,850.00
    # after: rate = 1.2662 + 0.3838*(1,100,000/1,000,000) = 1.68838%
    #        1,100,000*1.68838% = 18,572.18 -> period = 3,722.18
    assert result.employer_qc_hsf == Decimal("3722.18")


def test_qc_hsf_crossing_into_high_flat_tier_at_7_8m():
    result = calc(
        "CA", 200000, {}, _FLAT_10_SLAB, work_state="QC", state_rate_map=_QC_HSF_GENERAL_RATES,
        qc_hsf_ytd_remuneration_before=Decimal("7700000"),
    )
    # before: rate = 1.2662 + 0.3838*7.7 = 4.22146% -> 7,700,000*4.22146% = 325,052.42
    # after: 7,900,000 > $7.8M -> flat 4.26% * 7,900,000 = 336,540.00
    # period = 11,487.58
    assert result.employer_qc_hsf == Decimal("11487.58")


def test_qc_hsf_public_sector_uses_one_flat_rate_regardless_of_total():
    result = calc(
        "CA", 100000, {}, _FLAT_10_SLAB, work_state="QC", state_rate_map=_QC_HSF_PUBLIC_RATES,
        qc_hsf_ytd_remuneration_before=Decimal("500000"), qc_hsf_employer_category="PUBLIC_SECTOR",
    )
    # before: 500,000*4.26% = 21,300.00; after: 600,000*4.26% = 25,560.00
    assert result.employer_qc_hsf == Decimal("4260.00")


def test_qc_hsf_primary_manufacturing_uses_its_own_rates():
    result = calc(
        "CA", 100000, {}, _FLAT_10_SLAB, work_state="QC", state_rate_map=_QC_HSF_PRIMARY_RATES,
        qc_hsf_ytd_remuneration_before=Decimal("500000"), qc_hsf_employer_category="PRIMARY_MANUFACTURING",
    )
    # General's 1.65% would give 1,650.00 — proving PRIMARY's 1.25% was used:
    # before: 500,000*1.25% = 6,250.00; after: 600,000*1.25% = 7,500.00
    assert result.employer_qc_hsf == Decimal("1250.00")


def test_qc_hsf_default_category_is_general():
    result = calc(
        "CA", 100000, {}, _FLAT_10_SLAB, work_state="QC", state_rate_map=_QC_HSF_GENERAL_RATES,
        qc_hsf_ytd_remuneration_before=Decimal("500000"), qc_hsf_employer_category=None,
    )
    assert result.employer_qc_hsf == Decimal("1650.00")


def test_qc_hsf_zero_for_non_quebec_employee():
    result = calc(
        "CA", 100000, {}, _FLAT_10_SLAB, work_state="ON", state_rate_map=_QC_HSF_GENERAL_RATES,
        qc_hsf_ytd_remuneration_before=Decimal("500000"),
    )
    assert result.employer_qc_hsf == Decimal("0")
    assert result.qc_hsf_ytd_remuneration_after is None


def test_qc_hsf_zero_when_accumulator_not_wired():
    result = calc(
        "CA", 100000, {}, _FLAT_10_SLAB, work_state="QC", state_rate_map=_QC_HSF_GENERAL_RATES,
        qc_hsf_ytd_remuneration_before=None,
    )
    assert result.employer_qc_hsf == Decimal("0")


def test_qc_hsf_zero_when_not_configured():
    result = calc(
        "CA", 100000, {}, _FLAT_10_SLAB, work_state="QC", state_rate_map={},
        qc_hsf_ytd_remuneration_before=Decimal("500000"),
    )
    assert result.employer_qc_hsf == Decimal("0")


def test_qc_labour_standards_below_cap():
    result = calc("CA", 5000, {}, _FLAT_10_SLAB, work_state="QC", state_rate_map=_QC_LABOUR_STANDARDS_RATES)
    # annual 60,000 (< $103,000 cap) * 0.07% = 42.00 -> /12 = 3.50
    assert result.employer_qc_labour_standards == Decimal("3.50")


def test_qc_labour_standards_capped_at_103000():
    result = calc("CA", 10000, {}, _FLAT_10_SLAB, work_state="QC", state_rate_map=_QC_LABOUR_STANDARDS_RATES)
    # annual 120,000 > $103,000 cap -> subject capped at 103,000 * 0.07% = 72.10 -> /12 = 6.01
    assert result.employer_qc_labour_standards == Decimal("6.01")


def test_qc_labour_standards_zero_for_non_quebec_employee():
    result = calc("CA", 5000, {}, _FLAT_10_SLAB, work_state="ON", state_rate_map=_QC_LABOUR_STANDARDS_RATES)
    assert result.employer_qc_labour_standards == Decimal("0")


def test_qc_labour_standards_zero_when_not_configured():
    result = calc("CA", 5000, {}, _FLAT_10_SLAB, work_state="QC", state_rate_map={})
    assert result.employer_qc_labour_standards == Decimal("0")


def test_unknown_country_falls_back_to_generic():
    slabs = [Slab(Decimal("0"), None, Decimal("10"))]
    result = calc("ZZ", 1000, {}, slabs)
    assert result.tds > 0
    assert result.employee_pf == 0


# ── Formula-based tax rule (Germany-style continuous formula) ───────────

def test_formula_rule_overrides_bracket_loop():
    slabs = [Slab(rule_type="FORMULA", formula_expression="income * 0.2")]
    result = calc("DE", 10000, {}, slabs)
    # DE income tax now goes through _calculate_annual_tax_de, which
    # subtracts the Grundfreibetrag (11,784) before the formula runs, then
    # adds the Solidarity Surcharge (5.5%) since the resulting tax exceeds
    # the Soli threshold (18,130) — both use fallback defaults here since
    # no override rows were given (rate_map={}):
    #   taxable = 120000 - 11784 = 108216
    #   formula tax = 108216 * 0.2 = 21643.20
    #   + Soli (21643.20 > 18130 threshold, so +5.5%) = 22833.576
    #   tds = 22833.576 / 12 = 1902.80
    assert result.tds == pytest.approx(Decimal("1902.80"), abs=Decimal("0.01"))


def test_evaluate_tax_formula_supports_min_max_and_arithmetic():
    assert evaluate_tax_formula("min(income, 1000) * 0.1", Decimal("5000")) == Decimal("100")
    assert evaluate_tax_formula("max(income - 500, 0) * 0.1", Decimal("300")) == Decimal("0")


def test_evaluate_tax_formula_rejects_unsafe_expressions():
    with pytest.raises(Exception):
        evaluate_tax_formula("__import__('os').system('echo hi')", Decimal("1000"))
    with pytest.raises(Exception):
        evaluate_tax_formula("income.__class__", Decimal("1000"))
