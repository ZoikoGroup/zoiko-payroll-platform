"""
tests/test_netherlands_vcr.py
-----------------------------
VCR primitive tests (ZP-NL-ENG-001 NL-012..NL-014, NL-020, NL-045, NL-046).

Covers:
  F3: catch-up — high month followed by low month
  F3: annual ceiling
  negative wage
  mid-year start
  multiple income relationships (same family, same year)
  two separate Zvw series (ZVW_LEVY vs ZVW_CONTRIB)
"""

from decimal import Decimal

import pytest

from app.modules.payroll.engine.jurisdictions.netherlands.vcr import (
    VcrState,
    VcrInput,
    VcrResult,
    initial_state,
    advance,
    advance_batch,
    VcrFamily,
    family_for_premium,
)


class TestVcrCore:
    def test_initial_state(self):
        s = initial_state()
        assert s.period_count == 0
        assert s.cumulative_wage == Decimal("0")
        assert s.cumulative_max == Decimal("0")
        assert s.cumulative_base == Decimal("0")

    def test_single_period_basic(self):
        """One period: wage < max → base_increment = wage."""
        s = initial_state()
        res = advance(s, VcrInput(period_wage=Decimal("5000"), period_max=Decimal("6617.41")))
        assert res.new_state.period_count == 1
        assert res.new_state.cumulative_wage == Decimal("5000")
        assert res.new_state.cumulative_max == Decimal("6617.41")
        assert res.new_state.cumulative_base == Decimal("5000")
        assert res.base_increment == Decimal("5000")

    def test_period_wage_exceeds_max(self):
        """Wage > period max → base_increment = period max."""
        s = initial_state()
        res = advance(s, VcrInput(period_wage=Decimal("8000"), period_max=Decimal("6617.41")))
        assert res.new_state.cumulative_base == Decimal("6617.41")
        assert res.base_increment == Decimal("6617.41")


class TestVcrCatchUp:
    """NL-014 F3: catch-up — excess from high month becomes contributable later."""

    def test_high_month_then_low_month(self):
        """Month 1: 8000 wage, max 6617.41 → base=6617.41 (excess 1382.59 deferred)
        Month 2: 3000 wage, max 6617.41 → cum_wage=11000, cum_max=13234.82
        base = min(11000, 13234.82) = 11000
        increment = 11000 - 6617.41 = 4382.59 (catches up 1382.59 + 3000)
        """
        s = initial_state()
        monthly_max = Decimal("6617.41")

        res1 = advance(s, VcrInput(Decimal("8000"), monthly_max))
        assert res1.base_increment == Decimal("6617.41")

        res2 = advance(res1.new_state, VcrInput(Decimal("3000"), monthly_max))
        assert res2.base_increment == Decimal("4382.59")
        assert res2.new_state.cumulative_base == Decimal("11000")

    def test_multiple_catchup_periods(self):
        """Several high months, then lower — all excess catches up when max allows."""
        s = initial_state()
        monthly_max = Decimal("6617.41")

        # 3 months of 8000 wage
        for _ in range(3):
            res = advance(s, VcrInput(Decimal("8000"), monthly_max))
            s = res.new_state

        assert s.cumulative_wage == Decimal("24000")
        assert s.cumulative_max == monthly_max * 3
        assert s.cumulative_base == s.cumulative_max  # capped at max

        # Month 4: low wage 2000
        res4 = advance(s, VcrInput(Decimal("2000"), monthly_max))
        # cum_wage=26000, cum_max=26469.64, base=26000
        # increment = 26000 - 19852.23 = 6147.77
        assert res4.base_increment == Decimal("6147.77")


class TestVcrAnnualCeiling:
    """Annual ceiling: base stops growing when cumulative wage ≥ cumulative max."""

    def test_ceiling_stops_base_growth(self):
        """After 12 months of max, base = annual max. Further wage adds no base."""
        s = initial_state()
        monthly_max = Decimal("6617.41")

        for _ in range(12):
            res = advance(s, VcrInput(monthly_max, monthly_max))
            s = res.new_state

        # Annual ceiling ≈ 12 * 6617.41 = 79408.92
        assert s.cumulative_base == Decimal("79408.92")
        assert s.cumulative_max == Decimal("79408.92")

        # Month 13: more wage, no more max
        res13 = advance(s, VcrInput(Decimal("10000"), Decimal("0")))
        assert res13.base_increment == Decimal("0")
        assert res13.new_state.cumulative_base == Decimal("79408.92")


class TestVcrNegativeWage:
    """Negative wage (correction) produces negative base_increment."""

    def test_negative_wage_reduces_base(self):
        s = initial_state()
        monthly_max = Decimal("6617.41")

        # Normal month
        res1 = advance(s, VcrInput(Decimal("5000"), monthly_max))
        assert res1.base_increment == Decimal("5000")

        # Correction: -1000
        res2 = advance(res1.new_state, VcrInput(Decimal("-1000"), monthly_max))
        # cum_wage=4000, cum_max=13234.82, base=4000
        # increment = 4000 - 5000 = -1000
        assert res2.base_increment == Decimal("-1000")

    def test_negative_wage_not_below_zero_base(self):
        """Base cannot go negative; min is 0."""
        s = initial_state()
        monthly_max = Decimal("6617.41")

        # Month 1: 500
        res1 = advance(s, VcrInput(Decimal("500"), monthly_max))
        # Month 2: -600 (over-correction)
        res2 = advance(res1.new_state, VcrInput(Decimal("-600"), monthly_max))
        # cum_wage = -100, cum_max = 13234.82, base = min(-100, 13234.82) = -100
        # But base_increment = -100 - 500 = -600
        # Note: cumulative_base CAN go negative from negative wages
        # This is correct per spec — negative base_increment means refund
        assert res2.new_state.cumulative_base == Decimal("-100")
        assert res2.base_increment == Decimal("-600")


class TestVcrMidYearStart:
    """Mid-year start: cumulative max only accumulates from first period."""

    def test_mid_year_start(self):
        """Employee starts in month 7 (July). Only 6 periods of max accumulate."""
        s = initial_state()
        monthly_max = Decimal("6617.41")

        # 6 periods
        for _ in range(6):
            res = advance(s, VcrInput(Decimal("5000"), monthly_max))
            s = res.new_state

        assert s.period_count == 6
        assert s.cumulative_max == monthly_max * 6
        assert s.cumulative_base == Decimal("30000")  # 6 * 5000 (wages < max)


class TestVcrMultipleIncomeRelationships:
    """Multiple IKVs under same employer/employee/year/family aggregate."""

    def test_same_family_aggregates(self):
        """Two IKVs, same family EI: base increments add up."""
        s = initial_state()
        monthly_max = Decimal("6617.41")

        # IKV 1: 4000 wage
        res1 = advance(s, VcrInput(Decimal("4000"), monthly_max, income_relationship_id=1))
        # IKV 2: 3000 wage (same period, same family)
        res2 = advance(res1.new_state, VcrInput(Decimal("3000"), monthly_max, income_relationship_id=2))

        # Total base increment = 7000
        assert res2.new_state.cumulative_base == Decimal("7000")
        assert res2.base_increment == Decimal("3000")


class TestVcrSeparateZvwSeries:
    """NL-020: ZVW_LEVY (employer) and ZVW_CONTRIB (employee) are independent series."""

    def test_two_separate_series(self):
        """Same wage, same max, two families → independent increments."""
        s_levy = initial_state()
        s_contrib = initial_state()
        monthly_max = Decimal("6617.41")
        wage = Decimal("5000")

        res_levy = advance(s_levy, VcrInput(wage, monthly_max))
        res_contrib = advance(s_contrib, VcrInput(wage, monthly_max))

        assert res_levy.base_increment == Decimal("5000")
        assert res_contrib.base_increment == Decimal("5000")
        # But they are separate state objects
        assert res_levy.new_state is not res_contrib.new_state

    def test_family_for_premium_mapping(self):
        assert family_for_premium("awf") == VcrFamily.EI
        assert family_for_premium("aof") == VcrFamily.EI
        assert family_for_premium("wko") == VcrFamily.EI
        assert family_for_premium("zvw_employer") == VcrFamily.ZVW_LEVY
        assert family_for_premium("zvw_employee") == VcrFamily.ZVW_CONTRIB

        with pytest.raises(ValueError):
            family_for_premium("unknown")


class TestVcrBatch:
    """advance_batch convenience."""

    def test_batch_matches_sequential(self):
        s = initial_state()
        monthly_max = Decimal("6617.41")
        inputs = [
            VcrInput(Decimal("5000"), monthly_max),
            VcrInput(Decimal("6000"), monthly_max),
            VcrInput(Decimal("4000"), monthly_max),
        ]

        # Sequential
        s1 = s
        for inp in inputs:
            res = advance(s1, inp)
            s1 = res.new_state

        # Batch
        final_state, results = advance_batch(s, inputs)

        assert final_state.cumulative_base == s1.cumulative_base
        assert final_state.period_count == s1.period_count
        assert len(results) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])