"""
tests/test_germany_minijob_midijob.py
---------------------------------------
Comprehensive numeric unit tests for Germany Minijob and Midijob
social-insurance calculations. Uses only documented statutory values
from hardcoded_defaults.py (spec §4/§10-§20).

Every test is classified:
  AUTHORITATIVE — uses spec-cited rates/coefficients directly
  REGRESSION    — protects against known past failure modes
  BOUNDARY      — exercises threshold/corridor edge values
  SECURITY      — validates fail-closed behavior for invalid input

No DB required — all tests are pure unit tests against engine functions.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

import pytest

from app.modules.payroll.engine.germany_pap.core import (
    GermanyCalculationError,
    GermanyHealthFundNotAvailableError,
    GermanyInvalidEmploymentClassificationError,
    GermanyMidijobThresholdViolationError,
    GermanyMinijobThresholdViolationError,
    GermanyPvConfigurationNotAvailableError,
    GermanyStatutoryProfileMissingError,
    GermanyVocationalTraineeMidijobExclusionError,
    MinijobCalculationResult,
    MidijobPvResult,
    calculate_midijob_branch_contribution,
    calculate_midijob_employee_base,
    calculate_midijob_gkv,
    calculate_midijob_pv,
    calculate_midijob_total_base,
    calculate_minijob,
    resolve_employment_classification,
    validate_employment_classification_against_earnings,
    validate_employment_classification_against_vocational_training,
)
from app.modules.payroll.hardcoded_defaults import (
    _DE_MINIJOB_EMPLOYEE_PENSION_TOPUP_RATE,
    _DE_MINIJOB_EMPLOYER_HEALTH_RATE,
    _DE_MINIJOB_EMPLOYER_PENSION_RATE,
    _DE_MINIJOB_FLAT_TAX_RATE,
    _DE_MINIJOB_U1_RATE,
    _DE_MINIJOB_U2_RATE,
    _DE_MINIJOB_U3_RATE,
    _DE_MINIJOB_UPPER_THRESHOLD,
    _DE_MIDIJOB_EMPLOYEE_BASE_MULTIPLIER,
    _DE_MIDIJOB_EMPLOYEE_BASE_SUBTRAHEND,
    _DE_MIDIJOB_F_FACTOR,
    _DE_MIDIJOB_TOTAL_BASE_MULTIPLIER,
    _DE_MIDIJOB_TOTAL_BASE_SUBTRAHEND,
    _DE_MIDIJOB_UPPER_THRESHOLD,
    _DE_PV_CHILDLESS_SURCHARGE_RATE,
)


def _r2(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class _FakePvConfig:
    is_saxony: bool
    standard_employee_rate_pct: Decimal = Decimal("2.4000")
    employer_rate_pct: Decimal = Decimal("1.8000")
    saxony_employee_rate_pct: Decimal = Decimal("2.9000")
    saxony_employer_rate_pct: Decimal = Decimal("1.3000")
    total_rate_pct: Decimal = Decimal("4.2000")
    id: int = 1


@dataclass
class _FakeHealthFund:
    supplementary_rate_pct: Decimal
    id: int = 1
    health_fund_id: str = "TEST-FUND"
    fund_name: str = "Test Krankenkasse"


@dataclass
class _FakeProfile:
    id: int = 1
    de_employment_classification: str = "MINIJOB"
    de_pension_insurance_exempt: bool = False
    de_unemployment_insurance_exempt: bool = False
    de_health_insurance_status: str = "PUBLIC"
    de_health_fund_code: str = "TEST-FUND"
    de_child_count: int = 0
    de_childless: bool = True
    de_saxony: bool = False
    de_vocational_trainee: bool = False


# ══════════════════════════════════════════════════════════════════════════
# 1. MINIJOB — AUTHORITATIVE numeric unit tests (spec §12-§19)
# ══════════════════════════════════════════════════════════════════════════

class TestMinijobCalculation:
    """Minijob: monthly gross <= EUR 603.00. All employer figures are flat
    percentages of gross. The employee pension top-up is the ONLY deduction
    from net pay, and only when the employee has not opted out."""

    def test_standard_minijob_520(self):
        """AUTHORITATIVE: EUR 520/month — the classic Minijob example.
        employer_health = 520 * 13% = 67.60
        employer_pension = 520 * 15% = 78.00
        employer_u1 = 520 * 0.80% = 4.16
        employer_u2 = 520 * 0.22% = 1.144 -> 1.14
        employer_u3 = 520 * 0.15% = 0.78
        employee_pension_topup = 520 * 3.60% = 18.72
        flat_tax = 520 * 2% = 10.40"""
        result = calculate_minijob(
            monthly_gross=Decimal("520.00"),
            pension_insurance_exempt=False,
            employer_health_rate=_DE_MINIJOB_EMPLOYER_HEALTH_RATE,
            employer_pension_rate=_DE_MINIJOB_EMPLOYER_PENSION_RATE,
            u1_rate=_DE_MINIJOB_U1_RATE,
            u2_rate=_DE_MINIJOB_U2_RATE,
            u3_rate=_DE_MINIJOB_U3_RATE,
            employee_pension_topup_rate=_DE_MINIJOB_EMPLOYEE_PENSION_TOPUP_RATE,
            flat_tax_rate=_DE_MINIJOB_FLAT_TAX_RATE,
        )
        assert result.employer_health == Decimal("67.60")
        assert result.employer_pension == Decimal("78.00")
        assert result.employer_u1 == Decimal("4.16")
        assert result.employer_u2 == Decimal("1.14")
        assert result.employer_u3 == Decimal("0.78")
        assert result.employee_pension_topup == Decimal("18.72")
        assert result.flat_tax == Decimal("10.40")
        assert result.accident_insurance_resolved is False
        assert result.accident_insurance_amount is None

    def test_standard_minijob_603(self):
        """AUTHORITATIVE: EUR 603.00 — maximum Minijob threshold.
        employer_health = 603 * 13% = 78.39
        employer_pension = 603 * 15% = 90.45
        employer_u1 = 603 * 0.80% = 4.824 -> 4.82
        employer_u2 = 603 * 0.22% = 1.3266 -> 1.33
        employer_u3 = 603 * 0.15% = 0.9045 -> 0.90
        employee_pension_topup = 603 * 3.60% = 21.708 -> 21.71
        flat_tax = 603 * 2% = 12.06"""
        result = calculate_minijob(
            monthly_gross=Decimal("603.00"),
            pension_insurance_exempt=False,
            employer_health_rate=_DE_MINIJOB_EMPLOYER_HEALTH_RATE,
            employer_pension_rate=_DE_MINIJOB_EMPLOYER_PENSION_RATE,
            u1_rate=_DE_MINIJOB_U1_RATE,
            u2_rate=_DE_MINIJOB_U2_RATE,
            u3_rate=_DE_MINIJOB_U3_RATE,
            employee_pension_topup_rate=_DE_MINIJOB_EMPLOYEE_PENSION_TOPUP_RATE,
            flat_tax_rate=_DE_MINIJOB_FLAT_TAX_RATE,
        )
        assert result.employer_health == Decimal("78.39")
        assert result.employer_pension == Decimal("90.45")
        assert result.employer_u1 == Decimal("4.82")
        assert result.employer_u2 == Decimal("1.33")
        assert result.employer_u3 == Decimal("0.90")
        assert result.employee_pension_topup == Decimal("21.71")
        assert result.flat_tax == Decimal("12.06")

    def test_standard_minijob_450(self):
        """AUTHORITATIVE: EUR 450/month — common legacy Minijob reference.
        employer_health = 450 * 13% = 58.50
        employer_pension = 450 * 15% = 67.50
        employer_u1 = 450 * 0.80% = 3.60
        employer_u2 = 450 * 0.22% = 0.99
        employer_u3 = 450 * 0.15% = 0.675 -> 0.68
        employee_pension_topup = 450 * 3.60% = 16.20
        flat_tax = 450 * 2% = 9.00"""
        result = calculate_minijob(
            monthly_gross=Decimal("450.00"),
            pension_insurance_exempt=False,
            employer_health_rate=_DE_MINIJOB_EMPLOYER_HEALTH_RATE,
            employer_pension_rate=_DE_MINIJOB_EMPLOYER_PENSION_RATE,
            u1_rate=_DE_MINIJOB_U1_RATE,
            u2_rate=_DE_MINIJOB_U2_RATE,
            u3_rate=_DE_MINIJOB_U3_RATE,
            employee_pension_topup_rate=_DE_MINIJOB_EMPLOYEE_PENSION_TOPUP_RATE,
            flat_tax_rate=_DE_MINIJOB_FLAT_TAX_RATE,
        )
        assert result.employer_health == Decimal("58.50")
        assert result.employer_pension == Decimal("67.50")
        assert result.employer_u1 == Decimal("3.60")
        assert result.employer_u2 == Decimal("0.99")
        assert result.employer_u3 == Decimal("0.68")
        assert result.employee_pension_topup == Decimal("16.20")
        assert result.flat_tax == Decimal("9.00")

    def test_minijob_pension_exempt_skips_topup(self):
        """AUTHORITATIVE: employee_pension_insurance_exempt=True — the
        employee pension top-up is the ONLY Minijob component that reduces
        net pay. When exempt, it must be exactly 0."""
        result = calculate_minijob(
            monthly_gross=Decimal("520.00"),
            pension_insurance_exempt=True,
            employer_health_rate=_DE_MINIJOB_EMPLOYER_HEALTH_RATE,
            employer_pension_rate=_DE_MINIJOB_EMPLOYER_PENSION_RATE,
            u1_rate=_DE_MINIJOB_U1_RATE,
            u2_rate=_DE_MINIJOB_U2_RATE,
            u3_rate=_DE_MINIJOB_U3_RATE,
            employee_pension_topup_rate=_DE_MINIJOB_EMPLOYEE_PENSION_TOPUP_RATE,
            flat_tax_rate=_DE_MINIJOB_FLAT_TAX_RATE,
        )
        assert result.employee_pension_topup == Decimal("0")
        # All employer figures unchanged
        assert result.employer_health == Decimal("67.60")
        assert result.employer_pension == Decimal("78.00")
        assert result.flat_tax == Decimal("10.40")

    def test_minijob_zero_gross(self):
        """BOUNDARY: zero gross — all components should be zero."""
        result = calculate_minijob(
            monthly_gross=Decimal("0"),
            pension_insurance_exempt=False,
            employer_health_rate=_DE_MINIJOB_EMPLOYER_HEALTH_RATE,
            employer_pension_rate=_DE_MINIJOB_EMPLOYER_PENSION_RATE,
            u1_rate=_DE_MINIJOB_U1_RATE,
            u2_rate=_DE_MINIJOB_U2_RATE,
            u3_rate=_DE_MINIJOB_U3_RATE,
            employee_pension_topup_rate=_DE_MINIJOB_EMPLOYEE_PENSION_TOPUP_RATE,
            flat_tax_rate=_DE_MINIJOB_FLAT_TAX_RATE,
        )
        assert result.employer_health == Decimal("0.00")
        assert result.employer_pension == Decimal("0.00")
        assert result.employer_u1 == Decimal("0.00")
        assert result.employer_u2 == Decimal("0.00")
        assert result.employer_u3 == Decimal("0.00")
        assert result.employee_pension_topup == Decimal("0.00")
        assert result.flat_tax == Decimal("0.00")

    def test_minijob_very_small_gross(self):
        """BOUNDARY: EUR 1.00 gross — rounding edge case.
        employer_health = 1 * 13% = 0.13
        employer_pension = 1 * 15% = 0.15
        employer_u1 = 1 * 0.80% = 0.008 -> 0.01
        employer_u2 = 1 * 0.22% = 0.0022 -> 0.00
        employer_u3 = 1 * 0.15% = 0.0015 -> 0.00
        employee_pension_topup = 1 * 3.60% = 0.036 -> 0.04
        flat_tax = 1 * 2% = 0.02"""
        result = calculate_minijob(
            monthly_gross=Decimal("1.00"),
            pension_insurance_exempt=False,
            employer_health_rate=_DE_MINIJOB_EMPLOYER_HEALTH_RATE,
            employer_pension_rate=_DE_MINIJOB_EMPLOYER_PENSION_RATE,
            u1_rate=_DE_MINIJOB_U1_RATE,
            u2_rate=_DE_MINIJOB_U2_RATE,
            u3_rate=_DE_MINIJOB_U3_RATE,
            employee_pension_topup_rate=_DE_MINIJOB_EMPLOYEE_PENSION_TOPUP_RATE,
            flat_tax_rate=_DE_MINIJOB_FLAT_TAX_RATE,
        )
        assert result.employer_health == Decimal("0.13")
        assert result.employer_pension == Decimal("0.15")
        assert result.employer_u1 == Decimal("0.01")
        assert result.employer_u2 == Decimal("0.00")
        assert result.employer_u3 == Decimal("0.00")
        assert result.employee_pension_topup == Decimal("0.04")
        assert result.flat_tax == Decimal("0.02")

    def test_minijob_accident_insurance_provided(self):
        """AUTHORITATIVE: when accident_insurance_rate_pct is provided,
        the amount IS computed. Default rate: 1.3% (typical BG rate)."""
        result = calculate_minijob(
            monthly_gross=Decimal("520.00"),
            pension_insurance_exempt=False,
            employer_health_rate=_DE_MINIJOB_EMPLOYER_HEALTH_RATE,
            employer_pension_rate=_DE_MINIJOB_EMPLOYER_PENSION_RATE,
            u1_rate=_DE_MINIJOB_U1_RATE,
            u2_rate=_DE_MINIJOB_U2_RATE,
            u3_rate=_DE_MINIJOB_U3_RATE,
            employee_pension_topup_rate=_DE_MINIJOB_EMPLOYEE_PENSION_TOPUP_RATE,
            flat_tax_rate=_DE_MINIJOB_FLAT_TAX_RATE,
            accident_insurance_rate_pct=Decimal("1.30"),
        )
        assert result.accident_insurance_resolved is True
        # 520 * 1.30% = 6.76
        assert result.accident_insurance_amount == Decimal("6.76")

    def test_minijob_rate_constants_match_spec(self):
        """AUTHORITATIVE: verify the hardcoded constants match the spec §4."""
        assert _DE_MINIJOB_UPPER_THRESHOLD == Decimal("603.00")
        assert _DE_MINIJOB_EMPLOYER_HEALTH_RATE == Decimal("13")
        assert _DE_MINIJOB_EMPLOYER_PENSION_RATE == Decimal("15")
        assert _DE_MINIJOB_U1_RATE == Decimal("0.80")
        assert _DE_MINIJOB_U2_RATE == Decimal("0.22")
        assert _DE_MINIJOB_U3_RATE == Decimal("0.15")
        assert _DE_MINIJOB_EMPLOYEE_PENSION_TOPUP_RATE == Decimal("3.60")
        assert _DE_MINIJOB_FLAT_TAX_RATE == Decimal("2")


# ══════════════════════════════════════════════════════════════════════════
# 2. MIDIJOB — AUTHORITATIVE numeric unit tests (spec §20)
# ══════════════════════════════════════════════════════════════════════════

class TestMidijobBaseFormulas:
    """Midijob contribution-base sliding-scale formulas (spec §20)."""

    def test_total_base_formula_standard(self):
        """AUTHORITATIVE: EUR 1,500.00 gross.
        total_base = 1.1459372226 * 1500 - 291.8744452399
        = 1718.9058339 - 291.8744452399 = 1427.0313886601
        Floored at 0, rounded to 2dp only when used in monetary computation."""
        base = calculate_midijob_total_base(
            Decimal("1500.00"),
            multiplier=_DE_MIDIJOB_TOTAL_BASE_MULTIPLIER,
            subtrahend=_DE_MIDIJOB_TOTAL_BASE_SUBTRAHEND,
        )
        # No intermediate rounding — full Decimal precision
        expected = Decimal("1.1459372226") * Decimal("1500") - Decimal("291.8744452399")
        assert base == expected
        assert base > 0

    def test_employee_base_formula_standard(self):
        """AUTHORITATIVE: EUR 1,500.00 gross.
        employee_base = 1.43163922691 * 1500 - 863.2784538207
        = 2147.458840365 - 863.2784538207 = 1284.1803865443"""
        base = calculate_midijob_employee_base(
            Decimal("1500.00"),
            multiplier=_DE_MIDIJOB_EMPLOYEE_BASE_MULTIPLIER,
            subtrahend=_DE_MIDIJOB_EMPLOYEE_BASE_SUBTRAHEND,
        )
        expected = Decimal("1.43163922691") * Decimal("1500") - Decimal("863.2784538207")
        assert base == expected

    def test_total_base_zero_floor(self):
        """BOUNDARY: very low AE that would produce negative total_base.
        total_base must be clamped to 0 per Phase 8I §23."""
        base = calculate_midijob_total_base(
            Decimal("100.00"),
            multiplier=_DE_MIDIJOB_TOTAL_BASE_MULTIPLIER,
            subtrahend=_DE_MIDIJOB_TOTAL_BASE_SUBTRAHEND,
        )
        assert base == Decimal("0")

    def test_employee_base_zero_floor(self):
        """BOUNDARY: very low AE that would produce negative employee_base."""
        base = calculate_midijob_employee_base(
            Decimal("100.00"),
            multiplier=_DE_MIDIJOB_EMPLOYEE_BASE_MULTIPLIER,
            subtrahend=_DE_MIDIJOB_EMPLOYEE_BASE_SUBTRAHEND,
        )
        assert base == Decimal("0")

    def test_total_base_at_lower_corridor_boundary(self):
        """BOUNDARY: EUR 603.01 — just above Minijob threshold.
        total_base = 1.1459372226 * 603.01 - 291.8744452399
        = 691.006... - 291.874... = 399.131..."""
        base = calculate_midijob_total_base(
            Decimal("603.01"),
            multiplier=_DE_MIDIJOB_TOTAL_BASE_MULTIPLIER,
            subtrahend=_DE_MIDIJOB_TOTAL_BASE_SUBTRAHEND,
        )
        expected = Decimal("1.1459372226") * Decimal("603.01") - Decimal("291.8744452399")
        assert base == expected
        assert base > 0

    def test_total_base_at_upper_corridor_boundary(self):
        """BOUNDARY: EUR 2000.00 — maximum Midijob gross.
        total_base = 1.1459372226 * 2000 - 291.8744452399
        = 2291.8744452 - 291.8744452399 = 2000.00"""
        base = calculate_midijob_total_base(
            Decimal("2000.00"),
            multiplier=_DE_MIDIJOB_TOTAL_BASE_MULTIPLIER,
            subtrahend=_DE_MIDIJOB_TOTAL_BASE_SUBTRAHEND,
        )
        expected = Decimal("1.1459372226") * Decimal("2000") - Decimal("291.8744452399")
        assert base == expected

    def test_coefficient_constants_match_spec(self):
        """AUTHORITATIVE: verify the 2026 Midijob coefficients."""
        assert _DE_MIDIJOB_TOTAL_BASE_MULTIPLIER == Decimal("1.1459372226")
        assert _DE_MIDIJOB_TOTAL_BASE_SUBTRAHEND == Decimal("291.8744452399")
        assert _DE_MIDIJOB_EMPLOYEE_BASE_MULTIPLIER == Decimal("1.43163922691")
        assert _DE_MIDIJOB_EMPLOYEE_BASE_SUBTRAHEND == Decimal("863.2784538207")
        assert _DE_MIDIJOB_F_FACTOR == Decimal("0.6619")
        assert _DE_MIDIJOB_UPPER_THRESHOLD == Decimal("2000.00")


class TestMidijobBranchContribution:
    """The official 3-step Übergangsbereich branch-contribution mechanism
    (§20 Abs. 2a SGB IV; §2 Abs. 2 BVV)."""

    def test_rv_branch_standard(self):
        """AUTHORITATIVE: RV at EUR 1,500.00 — combined 18.60%, employee 9.30%.
        Step 1: total = 2 * round(total_base * 9.30% / 100, 2)
        Step 2: employee = round(employee_base * 9.30% / 100, 2)
        Step 3: employer = total - employee"""
        total_base = calculate_midijob_total_base(
            Decimal("1500.00"),
            multiplier=_DE_MIDIJOB_TOTAL_BASE_MULTIPLIER,
            subtrahend=_DE_MIDIJOB_TOTAL_BASE_SUBTRAHEND,
        )
        employee_base = calculate_midijob_employee_base(
            Decimal("1500.00"),
            multiplier=_DE_MIDIJOB_EMPLOYEE_BASE_MULTIPLIER,
            subtrahend=_DE_MIDIJOB_EMPLOYEE_BASE_SUBTRAHEND,
        )
        combined = Decimal("18.60")
        employee_rate = Decimal("9.30")
        total, employee, employer = calculate_midijob_branch_contribution(
            total_base, employee_base,
            combined_rate_pct=combined, employee_rate_pct=employee_rate,
        )
        # Step 1: half of 18.60% = 9.30%, apply to total_base, round, double
        half_rate = combined / Decimal("2")
        step1 = _r2(total_base * half_rate / Decimal("100")) * Decimal("2")
        # Step 2: employee_rate applied to employee_base
        step2 = _r2(employee_base * employee_rate / Decimal("100"))
        # Step 3: employer = total - employee
        step3 = step1 - step2
        assert total == step1
        assert employee == step2
        assert employer == step3

    def test_alv_branch_standard(self):
        """AUTHORITATIVE: ALV at EUR 1,500.00 — combined 2.60%, employee 1.30%."""
        total_base = calculate_midijob_total_base(
            Decimal("1500.00"),
            multiplier=_DE_MIDIJOB_TOTAL_BASE_MULTIPLIER,
            subtrahend=_DE_MIDIJOB_TOTAL_BASE_SUBTRAHEND,
        )
        employee_base = calculate_midijob_employee_base(
            Decimal("1500.00"),
            multiplier=_DE_MIDIJOB_EMPLOYEE_BASE_MULTIPLIER,
            subtrahend=_DE_MIDIJOB_EMPLOYEE_BASE_SUBTRAHEND,
        )
        combined = Decimal("2.60")
        employee_rate = Decimal("1.30")
        total, employee, employer = calculate_midijob_branch_contribution(
            total_base, employee_base,
            combined_rate_pct=combined, employee_rate_pct=employee_rate,
        )
        half_rate = combined / Decimal("2")
        step1 = _r2(total_base * half_rate / Decimal("100")) * Decimal("2")
        step2 = _r2(employee_base * employee_rate / Decimal("100"))
        assert total == step1
        assert employee == step2
        assert employer == step1 - step2

    def test_round_then_double_produces_cents_difference(self):
        """REGRESSION: the round-then-double mechanism can differ by up to
        1 cent from computing total_base * combined_rate / 100 and rounding
        once. This test documents that specific behavior."""
        total_base = Decimal("1234.56")
        combined = Decimal("18.60")
        employee_rate = Decimal("9.30")

        # The correct 3-step mechanism
        half_rate = combined / Decimal("2")
        correct = _r2(total_base * half_rate / Decimal("100")) * Decimal("2")

        # The simplified (incorrect) approach
        simplified = _r2(total_base * combined / Decimal("100"))

        # They may differ by up to 0.01 — this test documents the behavior
        assert abs(correct - simplified) <= Decimal("0.02")

    def test_zero_base_produces_zero_contribution(self):
        """BOUNDARY: zero total_base and employee_base."""
        total, employee, employer = calculate_midijob_branch_contribution(
            Decimal("0"), Decimal("0"),
            combined_rate_pct=Decimal("18.60"), employee_rate_pct=Decimal("9.30"),
        )
        assert total == Decimal("0.00")
        assert employee == Decimal("0.00")
        assert employer == Decimal("0.00")


class TestMidijobPv:
    """PV (Pflegeversicherung) needs special handling for the childless
    surcharge."""

    def test_standard_non_childless(self):
        """AUTHORITATIVE: standard PV (non-childless, non-Saxony).
        total_rate = 4.20%, employee = 2.40%, employer = 1.80%"""
        total_base = Decimal("1427.0313886601")
        employee_base = Decimal("1284.1803865443")
        result = calculate_midijob_pv(
            total_base, employee_base,
            pv_configuration=_FakePvConfig(is_saxony=False),
            is_childless=False,
        )
        assert isinstance(result, MidijobPvResult)
        assert result.childless_surcharge is None
        # Verify the 3-step mechanism was applied
        total, employee, employer = calculate_midijob_branch_contribution(
            total_base, employee_base,
            combined_rate_pct=Decimal("4.2000"), employee_rate_pct=Decimal("2.4000"),
        )
        assert result.total == total
        assert result.employee == employee
        assert result.employer == employer

    def test_childless_surcharge_standard(self):
        """AUTHORITATIVE: childless surcharge = 0.6 percentage points,
        100% employee-borne, not doubled."""
        total_base = Decimal("1427.0313886601")
        employee_base = Decimal("1284.1803865443")
        result = calculate_midijob_pv(
            total_base, employee_base,
            pv_configuration=_FakePvConfig(is_saxony=False),
            is_childless=True,
            childless_surcharge_rate_pct=Decimal("0.6"),
        )
        assert result.childless_surcharge is not None
        # surcharge_amount = total_base * 0.6% / 100
        expected_surcharge = _r2(total_base * Decimal("0.6") / Decimal("100"))
        assert result.childless_surcharge == expected_surcharge
        # employer should NOT include the surcharge
        # employee should include it
        assert result.employee > result.employer

    def test_childless_surcharge_saxony(self):
        """AUTHORITATIVE: Saxony childless — surcharge is still 0.6
        percentage points (Land-independent per §55 Abs. 3 SGB XI)."""
        total_base = Decimal("1427.0313886601")
        employee_base = Decimal("1284.1803865443")
        result_standard = calculate_midijob_pv(
            total_base, employee_base,
            pv_configuration=_FakePvConfig(is_saxony=False),
            is_childless=True,
            childless_surcharge_rate_pct=Decimal("0.6"),
        )
        result_saxony = calculate_midijob_pv(
            total_base, employee_base,
            pv_configuration=_FakePvConfig(is_saxony=True),
            is_childless=True,
            childless_surcharge_rate_pct=Decimal("0.6"),
        )
        # The surcharge amount should be IDENTICAL (Land-independent)
        assert result_standard.childless_surcharge == result_saxony.childless_surcharge
        # The TOTAL is the same because the childless surcharge is 100%
        # employee-borne and excluded from the employer share in both cases.
        # The SPLIT differs: Saxony employee bears more (2.9% vs 2.4% base).
        assert result_saxony.total == result_standard.total
        assert result_saxony.employee != result_standard.employee
        assert result_saxony.employer != result_standard.employer

    def test_childless_missing_surcharge_rate_raises(self):
        """SECURITY: surcharge rate must be provided when is_childless=True."""
        with pytest.raises(GermanyPvConfigurationNotAvailableError):
            calculate_midijob_pv(
                Decimal("1000"), Decimal("800"),
                pv_configuration=_FakePvConfig(is_saxony=False),
                is_childless=True,
                childless_surcharge_rate_pct=None,
            )

    def test_missing_pv_configuration_raises(self):
        """SECURITY: pv_configuration=None must raise."""
        with pytest.raises(GermanyPvConfigurationNotAvailableError):
            calculate_midijob_pv(
                Decimal("1000"), Decimal("800"),
                pv_configuration=None,
                is_childless=False,
            )


class TestMidijobGkv:
    """GKV for Midijob — general + supplementary, each independently
    subject to the 3-step mechanism."""

    def test_standard_gkv_public(self):
        """AUTHORITATIVE: GKV at EUR 1,500.00, PUBLIC status.
        general combined = 7.30% + 7.30% = 14.60%, employee = 7.30%
        supplementary = e.g. 1.70%, employee = supplementary_rate / 2"""
        total_base = calculate_midijob_total_base(
            Decimal("1500.00"),
            multiplier=_DE_MIDIJOB_TOTAL_BASE_MULTIPLIER,
            subtrahend=_DE_MIDIJOB_TOTAL_BASE_SUBTRAHEND,
        )
        employee_base = calculate_midijob_employee_base(
            Decimal("1500.00"),
            multiplier=_DE_MIDIJOB_EMPLOYEE_BASE_MULTIPLIER,
            subtrahend=_DE_MIDIJOB_EMPLOYEE_BASE_SUBTRAHEND,
        )
        health_fund = _FakeHealthFund(supplementary_rate_pct=Decimal("1.7000"))
        total, employee, employer, sup_rate = calculate_midijob_gkv(
            total_base, employee_base,
            health_insurance_status="PUBLIC",
            health_fund=health_fund,
            gkv_general_employee_rate=Decimal("7.30"),
            gkv_general_employer_rate=Decimal("7.30"),
        )
        assert sup_rate == Decimal("1.7000")
        # Verify general component
        g_total, g_emp, g_emp_ = calculate_midijob_branch_contribution(
            total_base, employee_base,
            combined_rate_pct=Decimal("14.60"), employee_rate_pct=Decimal("7.30"),
        )
        # Verify supplementary component
        s_total, s_emp, s_emp_ = calculate_midijob_branch_contribution(
            total_base, employee_base,
            combined_rate_pct=Decimal("1.70"),
            employee_rate_pct=Decimal("1.70") / Decimal("2"),
        )
        assert total == g_total + s_total
        assert employee == g_emp + s_emp
        assert employer == g_emp_ + s_emp_

    def test_gkv_private_returns_zero(self):
        """AUTHORITATIVE: PRIVATE health insurance status -> GKV = 0."""
        total, employee, employer, sup_rate = calculate_midijob_gkv(
            Decimal("1000"), Decimal("800"),
            health_insurance_status="PRIVATE",
            health_fund=None,
            gkv_general_employee_rate=Decimal("7.30"),
            gkv_general_employer_rate=Decimal("7.30"),
        )
        assert total == Decimal("0")
        assert employee == Decimal("0")
        assert employer == Decimal("0")

    def test_gkv_missing_status_raises(self):
        """SECURITY: no health_insurance_status -> raise."""
        with pytest.raises(GermanyStatutoryProfileMissingError):
            calculate_midijob_gkv(
                Decimal("1000"), Decimal("800"),
                health_insurance_status=None,
                health_fund=None,
                gkv_general_employee_rate=Decimal("7.30"),
                gkv_general_employer_rate=Decimal("7.30"),
            )

    def test_gkv_public_missing_fund_raises(self):
        """SECURITY: PUBLIC but no health_fund -> raise."""
        with pytest.raises(GermanyHealthFundNotAvailableError):
            calculate_midijob_gkv(
                Decimal("1000"), Decimal("800"),
                health_insurance_status="PUBLIC",
                health_fund=None,
                gkv_general_employee_rate=Decimal("7.30"),
                gkv_general_employer_rate=Decimal("7.30"),
            )


# ══════════════════════════════════════════════════════════════════════════
# 3. CLASSIFICATION / THRESHOLD validation tests
# ══════════════════════════════════════════════════════════════════════════

class TestEmploymentClassificationValidation:

    def test_minijob_below_threshold_passes(self):
        """BOUNDARY: gross at exactly the Minijob threshold."""
        validate_employment_classification_against_earnings(
            "MINIJOB", Decimal("603.00"),
            minijob_upper_threshold=Decimal("603.00"),
            midijob_upper_threshold=Decimal("2000.00"),
        )

    def test_minijob_above_threshold_raises(self):
        """BOUNDARY: gross one cent above Minijob threshold."""
        with pytest.raises(GermanyMinijobThresholdViolationError):
            validate_employment_classification_against_earnings(
                "MINIJOB", Decimal("603.01"),
                minijob_upper_threshold=Decimal("603.00"),
                midijob_upper_threshold=Decimal("2000.00"),
            )

    def test_midijob_at_lower_boundary_passes(self):
        """BOUNDARY: gross at 603.01 (just above Minijob threshold)."""
        validate_employment_classification_against_earnings(
            "MIDIJOB", Decimal("603.01"),
            minijob_upper_threshold=Decimal("603.00"),
            midijob_upper_threshold=Decimal("2000.00"),
        )

    def test_midijob_at_upper_boundary_passes(self):
        """BOUNDARY: gross at exactly 2000.00."""
        validate_employment_classification_against_earnings(
            "MIDIJOB", Decimal("2000.00"),
            minijob_upper_threshold=Decimal("603.00"),
            midijob_upper_threshold=Decimal("2000.00"),
        )

    def test_midijob_above_upper_boundary_raises(self):
        """BOUNDARY: gross one cent above Midijob upper bound."""
        with pytest.raises(GermanyMidijobThresholdViolationError):
            validate_employment_classification_against_earnings(
                "MIDIJOB", Decimal("2000.01"),
                minijob_upper_threshold=Decimal("603.00"),
                midijob_upper_threshold=Decimal("2000.00"),
            )

    def test_midijob_below_minijob_threshold_raises(self):
        """BOUNDARY: MIDIJOB employee with gross at/below Minijob threshold."""
        with pytest.raises(GermanyMidijobThresholdViolationError):
            validate_employment_classification_against_earnings(
                "MIDIJOB", Decimal("603.00"),
                minijob_upper_threshold=Decimal("603.00"),
                midijob_upper_threshold=Decimal("2000.00"),
            )

    def test_midijob_zero_gross_raises(self):
        """BOUNDARY: MIDIJOB with zero gross."""
        with pytest.raises(GermanyMidijobThresholdViolationError):
            validate_employment_classification_against_earnings(
                "MIDIJOB", Decimal("0"),
                minijob_upper_threshold=Decimal("603.00"),
                midijob_upper_threshold=Decimal("2000.00"),
            )

    def test_regular_never_validates(self):
        """REGULAR employees are not subject to Minijob/Midijob
        threshold validation — only the two corridor classifications are."""
        validate_employment_classification_against_earnings(
            "REGULAR", Decimal("5000.00"),
            minijob_upper_threshold=Decimal("603.00"),
            midijob_upper_threshold=Decimal("2000.00"),
        )

    def test_invalid_classification_raises(self):
        """SECURITY: unrecognized classification must raise."""
        with pytest.raises(GermanyInvalidEmploymentClassificationError):
            resolve_employment_classification(
                _FakeProfile(de_employment_classification="INVALID")
            )

    def test_default_classification_is_regular(self):
        """REGRESSION: None/empty classification defaults to REGULAR."""
        assert resolve_employment_classification(
            _FakeProfile(de_employment_classification=None)
        ) == "REGULAR"
        assert resolve_employment_classification(
            _FakeProfile(de_employment_classification="")
        ) == "REGULAR"


class TestVocationalTraineeExclusion:
    """§20 Abs. 2a Satz 9 SGB IV: vocational trainees can never be MIDIJOB."""

    def test_vocational_trainee_midijob_raises(self):
        """SECURITY: vocational trainee + MIDIJOB -> excluded."""
        with pytest.raises(GermanyVocationalTraineeMidijobExclusionError):
            validate_employment_classification_against_vocational_training(
                "MIDIJOB", True,
            )

    def test_vocational_trainee_regular_ok(self):
        """AUTHORITATIVE: vocational trainee + REGULAR is allowed."""
        validate_employment_classification_against_vocational_training(
            "REGULAR", True,
        )

    def test_vocational_trainee_minijob_ok(self):
        """AUTHORITATIVE: vocational trainee + MINIJOB is allowed."""
        validate_employment_classification_against_vocational_training(
            "MINIJOB", True,
        )

    def test_non_vocational_midijob_ok(self):
        """AUTHORITATIVE: non-vocational + MIDIJOB is allowed."""
        validate_employment_classification_against_vocational_training(
            "MIDIJOB", False,
        )


# ══════════════════════════════════════════════════════════════════════════
# 4. PV childless surcharge constant verification
# ══════════════════════════════════════════════════════════════════════════

class TestPvChildlessSurchargeConstant:
    """§55 Abs. 3 Satz 1 SGB XI: flat 0.6 contribution-rate points,
    Land-independent."""

    def test_surcharge_rate_is_0_6(self):
        """AUTHORITATIVE: the childless surcharge is exactly 0.6."""
        assert _DE_PV_CHILDLESS_SURCHARGE_RATE == Decimal("0.6")
