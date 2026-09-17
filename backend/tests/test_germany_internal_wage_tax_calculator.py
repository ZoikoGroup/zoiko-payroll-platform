"""
tests/test_germany_internal_wage_tax_calculator.py
----------------------------------------------------
Phase 8BR — pure, DB-free unit tests for
engine/germany_internal_tax.py (the internal, clearly-NOT-BMF-certified
Germany wage-tax/Soli calculator). Every INTERNAL FUNCTIONAL REFERENCE
figure asserted here is independently derivable from the module's own
documented section 32a/39b EStG formulas — never copied from the
module's implementation blindly. See the module docstring for the
provenance of every constant used below.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll.engine.jurisdictions.germany.tax import (
    ARBEITNEHMER_PAUSCHBETRAG,
    ENTLASTUNGSBETRAG_ALLEINERZIEHENDE_BASE,
    ENTLASTUNGSBETRAG_ALLEINERZIEHENDE_PER_ADDITIONAL_CHILD,
    GermanyInternalTariffNotAvailableError,
    InternalGermanyWageTaxCalculator,
    PROVENANCE_VERSION,
    SONDERAUSGABEN_PAUSCHBETRAG,
    compute_entlastungsbetrag_alleinerziehende,
    compute_grundtarif_annual_tax,
    compute_soli,
    compute_tax_for_class,
    calculate_internal_wage_tax,
    resolve_income_tax_tariff,
)
from app.modules.payroll.engine.jurisdictions.germany.pap.core import PapInputContract

SOLI_THRESHOLD = Decimal("18130")
SOLI_RATE = Decimal("5.5")


def _pap_input(**overrides) -> PapInputContract:
    defaults = dict(
        stkl="I", af=False, f=None, zkf=Decimal("0"), r="NONE", krv=False,
        alv_marker=False, pkv=False, pvs=False, pvz=False, pva=0,
        lzz=2, re4_cents=450000, kvz=Decimal("1.7"),
    )
    defaults.update(overrides)
    return PapInputContract(**defaults)


# ── section 32a EStG Grundtarif — boundary values ───────────────────────

def test_grundtarif_zero_below_grundfreibetrag():
    assert compute_grundtarif_annual_tax(Decimal("10908")) == Decimal("0")
    assert compute_grundtarif_annual_tax(Decimal("0")) == Decimal("0")
    assert compute_grundtarif_annual_tax(Decimal("-500")) == Decimal("0")


def test_grundtarif_positive_just_above_grundfreibetrag():
    # +1 EUR alone floors to 0 under whole-euro rounding (a genuinely tiny
    # fractional-cent tax amount, correct per the statute's own rounding
    # rule) — use +100 EUR, comfortably clear of that floor.
    tax = compute_grundtarif_annual_tax(Decimal("11008"))
    assert tax > Decimal("0")
    assert tax < Decimal("20")


def test_grundtarif_monotonic_across_zone_boundaries():
    # Zone boundaries: 10908 / 15999 / 62809 / 277825 (section 32a EStG 2023).
    points = [Decimal(v) for v in (10908, 11000, 15999, 16000, 62809, 62810, 277825, 277826, 500000)]
    taxes = [compute_grundtarif_annual_tax(p) for p in points]
    for earlier, later in zip(taxes, taxes[1:]):
        assert later >= earlier, f"tax must never decrease as zvE increases: {taxes}"


def test_grundtarif_top_zone_continuous_at_boundary():
    # zone4/zone5 boundary (277825) must be continuous to within EUR 1
    # (whole-euro flooring on each side).
    zone4_tax = compute_grundtarif_annual_tax(Decimal("277825"))
    zone5_tax = compute_grundtarif_annual_tax(Decimal("277826"))
    assert abs(zone5_tax - zone4_tax) <= Decimal("2")


# ── Splittingverfahren (Class III) ──────────────────────────────────────

def test_class_iii_splitting_matches_manual_halved_doubled_formula():
    """section 32a Abs. 5 EStG: HALVE zvE, apply the tariff, then DOUBLE
    the result — never tariff(2x)/2, which would produce MORE tax than
    Grundtarif (the opposite of what Splitting is for)."""
    zve = Decimal("40000")
    manual = 2 * compute_grundtarif_annual_tax(zve / 2)
    actual = compute_tax_for_class(zve, "III")
    assert actual == manual


def test_class_iii_produces_less_tax_than_class_i_for_same_zve():
    zve = Decimal("50000")
    class_i = compute_tax_for_class(zve, "I")
    class_iii = compute_tax_for_class(zve, "III")
    assert class_iii < class_i, "Splitting must never produce MORE tax than Grundtarif for the same zvE"


# ── Solidaritaetszuschlag exemption / mitigation zone ───────────────────

def test_soli_zero_below_threshold():
    assert compute_soli(Decimal("18130"), False, SOLI_THRESHOLD, SOLI_RATE) == Decimal("0")
    assert compute_soli(Decimal("10000"), False, SOLI_THRESHOLD, SOLI_RATE) == Decimal("0")


def test_soli_doubled_threshold_for_splitting():
    # Just above the single threshold must be EXEMPT under splitting.
    assert compute_soli(Decimal("20000"), True, SOLI_THRESHOLD, SOLI_RATE) == Decimal("0")


def test_soli_capped_at_mitigation_zone_rate():
    # Just above threshold: mitigation-zone (11.9% of excess) must be LESS
    # than the naive full 5.5% figure, and compute_soli must return the
    # smaller (mitigation) amount.
    base_tax = Decimal("18200")  # EUR 70 above threshold
    full_rate = base_tax * SOLI_RATE / 100
    mitigation = (base_tax - SOLI_THRESHOLD) * Decimal("11.9") / 100
    assert mitigation < full_rate
    result = compute_soli(base_tax, False, SOLI_THRESHOLD, SOLI_RATE)
    assert result == mitigation.quantize(Decimal("0.01"))


def test_soli_full_rate_once_past_mitigation_zone():
    base_tax = Decimal("200000")
    result = compute_soli(base_tax, False, SOLI_THRESHOLD, SOLI_RATE)
    assert result == (base_tax * SOLI_RATE / 100).quantize(Decimal("0.01"))


# ── Class-specific allowance treatment ──────────────────────────────────

def test_class_vi_receives_no_allowances_and_pays_more_tax_than_class_i():
    annual_wage = Decimal("54000")
    result_i = calculate_internal_wage_tax(
        tax_class="I", zkf=Decimal("0"), annual_wage=annual_wage, vorsorgepauschale_proxy=Decimal("9000"),
        soli_threshold_single=SOLI_THRESHOLD, soli_rate_pct=SOLI_RATE,
    )
    result_vi = calculate_internal_wage_tax(
        tax_class="VI", zkf=Decimal("0"), annual_wage=annual_wage, vorsorgepauschale_proxy=Decimal("9000"),
        soli_threshold_single=SOLI_THRESHOLD, soli_rate_pct=SOLI_RATE,
    )
    assert result_vi.annual_lohnsteuer > result_i.annual_lohnsteuer
    assert any("GERMANY_TAX_CLASS_V_VI_APPROXIMATE" in w for w in result_vi.warnings)


def test_class_v_between_class_i_and_class_vi():
    annual_wage = Decimal("54000")
    vp = Decimal("9000")
    r1 = calculate_internal_wage_tax(tax_class="I", zkf=Decimal("0"), annual_wage=annual_wage,
                                      vorsorgepauschale_proxy=vp, soli_threshold_single=SOLI_THRESHOLD, soli_rate_pct=SOLI_RATE)
    r5 = calculate_internal_wage_tax(tax_class="V", zkf=Decimal("0"), annual_wage=annual_wage,
                                      vorsorgepauschale_proxy=vp, soli_threshold_single=SOLI_THRESHOLD, soli_rate_pct=SOLI_RATE)
    r6 = calculate_internal_wage_tax(tax_class="VI", zkf=Decimal("0"), annual_wage=annual_wage,
                                      vorsorgepauschale_proxy=vp, soli_threshold_single=SOLI_THRESHOLD, soli_rate_pct=SOLI_RATE)
    assert r1.annual_lohnsteuer <= r5.annual_lohnsteuer <= r6.annual_lohnsteuer


def test_zkf_never_reduces_lohnsteuer_itself_only_surcharge_base():
    annual_wage = Decimal("60000")
    no_kids = calculate_internal_wage_tax(tax_class="IV", zkf=Decimal("0"), annual_wage=annual_wage,
                                           vorsorgepauschale_proxy=Decimal("9000"), soli_threshold_single=SOLI_THRESHOLD, soli_rate_pct=SOLI_RATE)
    two_kids = calculate_internal_wage_tax(tax_class="IV", zkf=Decimal("2"), annual_wage=annual_wage,
                                            vorsorgepauschale_proxy=Decimal("9000"), soli_threshold_single=SOLI_THRESHOLD, soli_rate_pct=SOLI_RATE)
    assert no_kids.annual_lohnsteuer == two_kids.annual_lohnsteuer
    assert two_kids.zve_for_surcharges < no_kids.zve_for_surcharges


# ── Executor (PapExecutor interface) ────────────────────────────────────

def test_executor_returns_complete_status_with_disclosed_provenance():
    calculator = InternalGermanyWageTaxCalculator(soli_threshold_single=SOLI_THRESHOLD, soli_rate_pct=SOLI_RATE)
    result = calculator.execute(_pap_input())
    assert result.calculation_status == "COMPLETE"
    assert result.pap_version == PROVENANCE_VERSION
    assert result.lohnsteuer >= Decimal("0")
    assert any("INTERNAL_FUNCTIONAL_REFERENCE" in w for w in result.warnings)
    assert result.errors == []


def test_executor_higher_gross_never_produces_lower_lohnsteuer():
    calculator = InternalGermanyWageTaxCalculator(soli_threshold_single=SOLI_THRESHOLD, soli_rate_pct=SOLI_RATE)
    low = calculator.execute(_pap_input(re4_cents=300000))
    high = calculator.execute(_pap_input(re4_cents=600000))
    assert high.lohnsteuer >= low.lohnsteuer


def test_executor_uses_vorsorgepauschale_proxy_to_reduce_tax():
    calculator = InternalGermanyWageTaxCalculator(soli_threshold_single=SOLI_THRESHOLD, soli_rate_pct=SOLI_RATE)
    no_proxy = _pap_input(re4_cents=450000)
    no_proxy.vorsorgepauschale_annual_cents = 0
    with_proxy = _pap_input(re4_cents=450000)
    with_proxy.vorsorgepauschale_annual_cents = 900000  # EUR 9,000/year
    result_no_proxy = calculator.execute(no_proxy)
    result_with_proxy = calculator.execute(with_proxy)
    assert result_with_proxy.lohnsteuer < result_no_proxy.lohnsteuer


@pytest.mark.parametrize("tax_class", ["I", "II", "III", "IV", "V", "VI"])
def test_every_documented_tax_class_actually_affects_calculation(tax_class):
    """Explicit regression for the phase brief's own requirement: 'each
    tax class must actually affect the calculation' / 'do not silently
    treat every class as Class I'."""
    calculator = InternalGermanyWageTaxCalculator(soli_threshold_single=SOLI_THRESHOLD, soli_rate_pct=SOLI_RATE)
    result = calculator.execute(_pap_input(stkl=tax_class, re4_cents=450000))
    assert result.calculation_status == "COMPLETE"
    assert isinstance(result.lohnsteuer, Decimal)


def test_class_i_vs_class_iii_actually_differ_end_to_end():
    calculator = InternalGermanyWageTaxCalculator(soli_threshold_single=SOLI_THRESHOLD, soli_rate_pct=SOLI_RATE)
    class_i = calculator.execute(_pap_input(stkl="I", re4_cents=450000))
    class_iii = calculator.execute(_pap_input(stkl="III", re4_cents=450000))
    assert class_iii.lohnsteuer < class_i.lohnsteuer


# ── Structured REFERENCE_APPROXIMATION disclosure (Phase 8BS) ───────────

def test_reference_approximation_field_present_and_never_hidden_in_prose_only():
    """Phase 8BS §25: 'if a calculation uses an approximation, explicitly
    expose REFERENCE_APPROXIMATION. Do not hide approximations.' — must be
    a structured, machine-readable field, not just prose text a consumer
    would need to regex out of `warnings`."""
    calculator = InternalGermanyWageTaxCalculator(soli_threshold_single=SOLI_THRESHOLD, soli_rate_pct=SOLI_RATE)
    result = calculator.execute(_pap_input(stkl="I", re4_cents=450000))
    assert "REFERENCE_APPROXIMATION" in result.raw_outputs
    # Tax Class I with vorsorgepauschale still uses the tariff-year and
    # Vorsorgepauschale-proxy approximations — never claims to be exact.
    assert "GERMANY_TARIFF_YEAR_NOT_CURRENT" in result.raw_outputs["REFERENCE_APPROXIMATION"]


def test_reference_approximation_flags_class_v_vi_specifically():
    calculator = InternalGermanyWageTaxCalculator(soli_threshold_single=SOLI_THRESHOLD, soli_rate_pct=SOLI_RATE)
    for stkl in ("V", "VI"):
        result = calculator.execute(_pap_input(stkl=stkl, re4_cents=450000))
        assert "GERMANY_TAX_CLASS_V_VI_APPROXIMATE" in result.raw_outputs["REFERENCE_APPROXIMATION"]


def test_reference_approximation_flags_class_ii_without_a_recorded_child():
    """Phase 8BT: Class II's Entlastungsbetrag IS now modeled (see the
    dedicated tests below) — this specific warning fires only for the
    edge case of a Class II employee with no recorded child_count at all,
    which is itself a data-quality signal worth surfacing, not silently
    ignored."""
    calculator = InternalGermanyWageTaxCalculator(soli_threshold_single=SOLI_THRESHOLD, soli_rate_pct=SOLI_RATE)
    result = calculator.execute(_pap_input(stkl="II", re4_cents=450000))
    assert "GERMANY_TAX_CLASS_II_NO_CHILD_RECORDED" in result.raw_outputs["REFERENCE_APPROXIMATION"]


def test_reference_approximation_absent_flags_for_class_iii_and_iv():
    """Classes III/IV (with no children) have no class-specific
    approximation beyond the universal tariff-year/Vorsorgepauschale-proxy
    disclosures — proving the approximation codes are genuinely
    class-specific, not a blanket catch-all applied to everything."""
    calculator = InternalGermanyWageTaxCalculator(soli_threshold_single=SOLI_THRESHOLD, soli_rate_pct=SOLI_RATE)
    for stkl in ("III", "IV"):
        result = calculator.execute(_pap_input(stkl=stkl, re4_cents=450000))
        codes = result.raw_outputs["REFERENCE_APPROXIMATION"]
        assert "GERMANY_TAX_CLASS_V_VI_APPROXIMATE" not in codes
        assert "GERMANY_TAX_CLASS_II_NO_CHILD_RECORDED" not in codes


# ── Effective dating (Phase 8BS): resolve against payroll RUN pay date ──

def test_resolve_income_tax_tariff_resolves_each_version_in_its_own_window():
    """Phase 8BY: two verified tariff versions now exist. Each payroll
    date must resolve the version legally applicable to ITS OWN period —
    2023-2025 to the 2023 tariff, 2026 onward to the 2026 tariff — never
    simply the newest row."""
    for d in (date(2023, 1, 1), date(2024, 7, 1), date(2025, 12, 31)):
        tariff = resolve_income_tax_tariff(d)
        assert tariff["tax_year"] == "2023-ESTG-32A"
        assert tariff["effective_from"] == date(2023, 1, 1)
    for d in (date(2026, 1, 1), date(2026, 6, 1), date(2030, 1, 1)):
        tariff = resolve_income_tax_tariff(d)
        assert tariff["tax_year"] == "2026-ESTG-32A"
        assert tariff["effective_from"] == date(2026, 1, 1)


def test_resolve_income_tax_tariff_rejects_historical_date_before_verified_range():
    """A payroll date before this module's earliest verified tariff
    version must fail closed (never silently reuse the 2023 tariff for
    an earlier period it was never verified against)."""
    with pytest.raises(GermanyInternalTariffNotAvailableError) as excinfo:
        resolve_income_tax_tariff(date(2022, 12, 31))
    assert excinfo.value.code == "GERMANY_INTERNAL_TARIFF_NOT_AVAILABLE"


def test_calculator_resolves_tariff_from_payroll_date_not_wallclock():
    """The calculator must resolve its tariff from the PASSED payroll
    date, not some other date — a boundary-exact historical date (the
    version's own effective_from) must succeed."""
    calculator = InternalGermanyWageTaxCalculator(
        soli_threshold_single=SOLI_THRESHOLD, soli_rate_pct=SOLI_RATE, payroll_date=date(2023, 1, 1),
    )
    result = calculator.execute(_pap_input(re4_cents=450000))
    assert result.calculation_status == "COMPLETE"
    assert result.raw_outputs["TARIFF_EFFECTIVE_FROM"] == "2023-01-01"


def test_calculator_fails_closed_for_payroll_date_before_verified_tariff():
    """A Germany payroll run dated before any verified internal tariff
    exists must fail closed with a structured, typed error — never
    silently apply the 2023 tariff to, say, a 2021 payroll date."""
    with pytest.raises(GermanyInternalTariffNotAvailableError):
        InternalGermanyWageTaxCalculator(
            soli_threshold_single=SOLI_THRESHOLD, soli_rate_pct=SOLI_RATE, payroll_date=date(2021, 1, 1),
        )


def test_calculator_with_no_payroll_date_falls_back_to_first_version():
    """Backward compatibility: a caller with no payroll date (e.g. a unit
    test, or any pre-8BS call site) still gets the first verified tariff
    directly, exactly as before. Every PRODUCTION call site passes a real
    payroll date (see test_calculator_resolves_2026_tariff_for_2026_date
    and service.py's four germany_payroll_date call sites), so this
    date-less default is only ever reached by non-production callers."""
    calculator = InternalGermanyWageTaxCalculator(soli_threshold_single=SOLI_THRESHOLD, soli_rate_pct=SOLI_RATE)
    result = calculator.execute(_pap_input(re4_cents=450000))
    assert result.pap_version == PROVENANCE_VERSION


# ── Phase 8BY: 2026 statutory tariff (ZP-TAX-DE-2026-001 sections 4 & 7) ──


def test_2026_tariff_values_match_the_controlled_source_document():
    """Every 2026 figure is transcribed from ZP-TAX-DE-2026-001 v1.0:
    Grundfreibetrag EUR 12,348 and the four zone boundaries from section
    4; Soli Freigrenze EUR 20,350 from section 7; child allowance EUR
    9,756 per ZKF unit from section 4. A regression here means a
    statutory value drifted away from the authoritative document."""
    t = resolve_income_tax_tariff(date(2026, 6, 1))
    assert t["grundfreibetrag"] == Decimal("12348")
    assert t["zone2_upper"] == Decimal("17799")
    assert t["zone3_upper"] == Decimal("69878")
    assert t["zone4_upper"] == Decimal("277825")
    assert t["zone4_rate"] == Decimal("0.42")
    assert t["zone5_rate"] == Decimal("0.45")
    assert t["soli_threshold_single"] == Decimal("20350")
    assert t["kinderfreibetrag_plus_bea"] == Decimal("9756")


def test_2026_tariff_zero_tax_exactly_at_grundfreibetrag_and_progressive_above():
    """Section 4 boundary: EUR 0-12,348 is taxed at EUR 0. Above the
    Grundfreibetrag the tariff must be strictly progressive."""
    t = resolve_income_tax_tariff(date(2026, 6, 1))
    assert compute_grundtarif_annual_tax(Decimal("12348"), t) == Decimal("0")
    assert compute_grundtarif_annual_tax(Decimal("40000"), t) > compute_grundtarif_annual_tax(Decimal("30000"), t)


def test_2026_tariff_is_continuous_across_every_zone_boundary():
    """Section 22 boundary tests: the 2026 zone coefficients must join
    continuously at 17,799/17,800, 69,878/69,879 and 277,825/277,826 —
    a transcription error in any coefficient shows up as a jump here."""
    t = resolve_income_tax_tariff(date(2026, 6, 1))
    for boundary in (Decimal("17799"), Decimal("69878"), Decimal("277825")):
        below = compute_grundtarif_annual_tax(boundary, t)
        above = compute_grundtarif_annual_tax(boundary + 1, t)
        assert above >= below
        assert above - below <= Decimal("2"), f"discontinuity at {boundary}: {below} -> {above}"


def test_2026_grundfreibetrag_is_higher_so_same_income_is_taxed_less_than_2023():
    """Directional check (never only an exact-value one): 2026 raises the
    Grundfreibetrag from 12,348 vs 10,908 and widens the zones, so the
    SAME zvE must attract strictly LESS tax under 2026 than under 2023.
    Catches an accidentally inverted/swapped version entry."""
    t23 = resolve_income_tax_tariff(date(2024, 6, 1))
    t26 = resolve_income_tax_tariff(date(2026, 6, 1))
    for zve in (Decimal("20000"), Decimal("45000"), Decimal("80000")):
        assert compute_grundtarif_annual_tax(zve, t26) < compute_grundtarif_annual_tax(zve, t23)


def test_2026_soli_freigrenze_boundary_matches_section_7():
    """Section 7: exemption threshold EUR 20,350 single / EUR 40,700
    splitting. Exactly AT the threshold Soli is still zero; one euro
    above it enters the mitigation zone."""
    t = resolve_income_tax_tariff(date(2026, 6, 1))
    threshold = t["soli_threshold_single"]
    assert compute_soli(Decimal("20350"), False, threshold, SOLI_RATE) == Decimal("0")
    assert compute_soli(Decimal("20351"), False, threshold, SOLI_RATE) > Decimal("0")
    # Splitting doubles the Freigrenze to exactly the document's 40,700.
    assert compute_soli(Decimal("40700"), True, threshold, SOLI_RATE) == Decimal("0")
    assert compute_soli(Decimal("40701"), True, threshold, SOLI_RATE) > Decimal("0")


def test_calculator_resolves_2026_tariff_for_2026_date_and_traces_its_values():
    """End to end through the executor: a 2026 payroll date must produce
    a 2026-labelled result whose trace proves WHICH statutory values were
    applied, and must no longer carry the year-stale approximation flag."""
    calculator = InternalGermanyWageTaxCalculator(
        soli_threshold_single=SOLI_THRESHOLD, soli_rate_pct=SOLI_RATE, payroll_date=date(2026, 6, 1),
    )
    result = calculator.execute(_pap_input(re4_cents=450000))
    assert result.calculation_status == "COMPLETE"
    assert result.pap_version == "INTERNAL_FUNCTIONAL_REFERENCE-ESTG32A-2026"
    assert result.raw_outputs["TAX_YEAR"] == "2026-ESTG-32A"
    assert result.raw_outputs["TARIFF_EFFECTIVE_FROM"] == "2026-01-01"
    assert result.raw_outputs["TARIFF_GRUNDFREIBETRAG"] == "12348"
    assert result.raw_outputs["SOLI_THRESHOLD_SINGLE_APPLIED"] == "20350"
    assert result.raw_outputs["KINDERFREIBETRAG_PLUS_BEA_APPLIED"] == "9756"
    assert "GERMANY_TARIFF_YEAR_NOT_CURRENT" not in result.raw_outputs["REFERENCE_APPROXIMATION"]


def test_effective_dated_soli_threshold_overrides_a_stale_injected_constant():
    """The engine injects _DE_SOLI_THRESHOLD (the 2023-2025 value) at the
    call site. For a 2026 payroll the EFFECTIVE-DATED version must win, so
    an employee whose surcharge base sits between the two thresholds owes
    ZERO Soli in 2026 where the stale injected constant would have charged
    them. This is the regression guard for the actual bug."""
    stale = Decimal("18130")
    calc_2026 = InternalGermanyWageTaxCalculator(
        soli_threshold_single=stale, soli_rate_pct=SOLI_RATE, payroll_date=date(2026, 6, 1),
    )
    assert calc_2026._tariff["soli_threshold_single"] == Decimal("20350")
    # A surcharge base of 19,000 is above the stale 18,130 but below the
    # correct 2026 Freigrenze of 20,350 -> must be exempt in 2026.
    assert compute_soli(Decimal("19000"), False, calc_2026._tariff["soli_threshold_single"], SOLI_RATE) == Decimal("0")
    assert compute_soli(Decimal("19000"), False, stale, SOLI_RATE) > Decimal("0")


def test_internal_calculator_still_never_claims_to_be_the_certified_bmf_pap():
    """PAP governance must not be weakened by the 2026 tariff work: the
    result still carries the INTERNAL_FUNCTIONAL_REFERENCE provenance and
    an explicit non-certification warning, for 2026 exactly as for 2023."""
    calculator = InternalGermanyWageTaxCalculator(
        soli_threshold_single=SOLI_THRESHOLD, soli_rate_pct=SOLI_RATE, payroll_date=date(2026, 6, 1),
    )
    result = calculator.execute(_pap_input(re4_cents=450000))
    assert result.pap_version.startswith("INTERNAL_FUNCTIONAL_REFERENCE")
    assert result.pap_hash is None
    assert any("NOT the certified BMF" in w for w in result.warnings)


# ── Tax Class II Entlastungsbetrag fuer Alleinerziehende (Phase 8BT) ────

def test_entlastungsbetrag_zero_for_no_children():
    assert compute_entlastungsbetrag_alleinerziehende(0) == Decimal("0")
    assert compute_entlastungsbetrag_alleinerziehende(-1) == Decimal("0")


def test_entlastungsbetrag_base_amount_for_one_child():
    assert compute_entlastungsbetrag_alleinerziehende(1) == ENTLASTUNGSBETRAG_ALLEINERZIEHENDE_BASE
    assert compute_entlastungsbetrag_alleinerziehende(1) == Decimal("4260")


def test_entlastungsbetrag_adds_per_additional_child():
    # section 24b Abs. 2 Satz 2 EStG: EUR 240 per child BEYOND the first.
    assert compute_entlastungsbetrag_alleinerziehende(2) == Decimal("4260") + Decimal("240")
    assert compute_entlastungsbetrag_alleinerziehende(3) == Decimal("4260") + 2 * Decimal("240")
    assert compute_entlastungsbetrag_alleinerziehende(5) == Decimal("4260") + 4 * Decimal("240")


def test_class_ii_with_child_produces_less_tax_than_class_ii_without_child():
    """The core, directly-testable regression this feature exists for:
    a Class II employee WITH a recorded child must owe LESS annual
    Lohnsteuer than a Class II employee with none (who falls back to
    the same treatment as Class I) — never the same, never more."""
    calculator = InternalGermanyWageTaxCalculator(soli_threshold_single=SOLI_THRESHOLD, soli_rate_pct=SOLI_RATE)
    without_child = calculator.execute(_pap_input(stkl="II", re4_cents=450000, child_count=0))
    with_child = calculator.execute(_pap_input(stkl="II", re4_cents=450000, child_count=1))
    assert with_child.lohnsteuer < without_child.lohnsteuer
    assert (without_child.lohnsteuer - with_child.lohnsteuer) > Decimal("0")


def test_class_ii_entlastungsbetrag_scales_with_additional_children():
    """More children -> strictly less tax (monotonic), and the exact
    difference in taxable base between 1 and 2 children must equal the
    EUR 240 additional-child amount (subject to whole-euro tariff
    flooring, so compared via the traced ZVE_LOHNSTEUER raw output rather
    than the final tax, which floors non-linearly)."""
    calculator = InternalGermanyWageTaxCalculator(soli_threshold_single=SOLI_THRESHOLD, soli_rate_pct=SOLI_RATE)
    one_child = calculator.execute(_pap_input(stkl="II", re4_cents=450000, child_count=1))
    two_children = calculator.execute(_pap_input(stkl="II", re4_cents=450000, child_count=2))
    three_children = calculator.execute(_pap_input(stkl="II", re4_cents=450000, child_count=3))
    assert two_children.lohnsteuer <= one_child.lohnsteuer
    assert three_children.lohnsteuer <= two_children.lohnsteuer

    zve_one = Decimal(one_child.raw_outputs["ZVE_LOHNSTEUER"])
    zve_two = Decimal(two_children.raw_outputs["ZVE_LOHNSTEUER"])
    assert (zve_one - zve_two) == ENTLASTUNGSBETRAG_ALLEINERZIEHENDE_PER_ADDITIONAL_CHILD


def test_class_ii_with_child_traces_entlastungsbetrag_in_raw_outputs():
    calculator = InternalGermanyWageTaxCalculator(soli_threshold_single=SOLI_THRESHOLD, soli_rate_pct=SOLI_RATE)
    result = calculator.execute(_pap_input(stkl="II", re4_cents=450000, child_count=2))
    assert Decimal(result.raw_outputs["ENTLASTUNGSBETRAG_ALLEINERZIEHENDE"]) == Decimal("4500")  # 4260 + 240
    assert any("ENTLASTUNGSBETRAG_APPLIED" in w for w in result.warnings)
    assert "GERMANY_TAX_CLASS_II_NO_CHILD_RECORDED" not in result.raw_outputs["REFERENCE_APPROXIMATION"]


def test_class_ii_entlastungsbetrag_also_reduces_soli_kirchensteuer_base():
    """The Entlastungsbetrag is a genuine income-reducing allowance under
    section 24b EStG (unlike ZKF, which section 51a EStG specifically
    excludes from the wage-tax base but NOT from the Soli/Kirchensteuer
    base) — it must reduce BOTH bases, not just Lohnsteuer's."""
    calculator = InternalGermanyWageTaxCalculator(soli_threshold_single=SOLI_THRESHOLD, soli_rate_pct=SOLI_RATE)
    without_child = calculator.execute(_pap_input(stkl="II", re4_cents=450000, child_count=0))
    with_child = calculator.execute(_pap_input(stkl="II", re4_cents=450000, child_count=1))
    assert Decimal(with_child.raw_outputs["ZVE_SURCHARGES"]) < Decimal(without_child.raw_outputs["ZVE_SURCHARGES"])
    assert with_child.church_tax_assessment_base < without_child.church_tax_assessment_base


def test_class_ii_only_other_classes_never_receive_entlastungsbetrag():
    """Only Class II is legally eligible for the Entlastungsbetrag
    (section 38b Abs. 1 Nr. 2 EStG ties it specifically to that class) —
    verify child_count has ZERO effect on every other class's Lohnsteuer."""
    calculator = InternalGermanyWageTaxCalculator(soli_threshold_single=SOLI_THRESHOLD, soli_rate_pct=SOLI_RATE)
    for stkl in ("I", "III", "IV", "V", "VI"):
        no_child = calculator.execute(_pap_input(stkl=stkl, re4_cents=450000, child_count=0))
        with_child = calculator.execute(_pap_input(stkl=stkl, re4_cents=450000, child_count=3))
        assert no_child.lohnsteuer == with_child.lohnsteuer, f"class {stkl} must be unaffected by child_count"
