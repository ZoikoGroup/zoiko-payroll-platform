"""
tests/test_netherlands_premiums.py
----------------------------------
Employee insurance premium tests (ZP-NL-ENG-001 NL-015..NL-018).

Covers:
  F2: AWf €137.00, Aof €313.50, Wko €25.00, Zvw €305.00 (at given base increment)
  F4: AWf at high rate
  Aof small vs large employer
  Whk missing decision fails closed
  Whk employee recoverable split
"""

from decimal import Decimal

import pytest

from app.modules.payroll.engine.jurisdictions.netherlands.premiums import (
    EwPremiumRates,
    AwfContractFacts,
    EmployerPremiumDecision,
    calculate_awf,
    calculate_aof,
    calculate_wko,
    calculate_whk,
    calculate_ei_period,
    round_eur,
    get_rates_from_pack,
    PremiumConfigurationError,
)
from app.modules.payroll.engine.jurisdictions.netherlands.vcr import (
    VcrState,
    VcrInput,
    advance,
    initial_state,
)


class TestPremiumRates:
    def test_get_rates_from_pack_missing_blocks(self):
        """No fallback rate: an unconfigured pack blocks (NL-003/NL-017)."""
        with pytest.raises(PremiumConfigurationError, match="nl_awf_low_pct"):
            get_rates_from_pack({})

    def test_get_rates_from_pack_reads_contribution_rate_rows(self):
        class _Row:
            def __init__(self, employer=None, employee=None):
                self.employer_rate_pct, self.employee_rate_pct = employer, employee
        rate_map = {k: _Row(employer=v) for k, v in {
            "nl_awf_low_pct": "2.7400", "nl_awf_high_pct": "7.7400", "nl_aof_low_pct": "6.2700",
            "nl_aof_high_pct": "7.6300", "nl_wko_pct": "0.5000"}.items()}
        rates = get_rates_from_pack(rate_map)
        assert rates.awf_low_pct == Decimal("2.74")
        assert rates.wko_pct == Decimal("0.50")

    def test_get_rates_from_pack_overrides(self):
        rate_map = {
            "nl_awf_low_pct": "2.50",
            "nl_awf_high_pct": "8.00",
            "nl_aof_low_pct": "6.00",
            "nl_aof_high_pct": "7.50",
            "nl_wko_pct": "0.60",
        }
        rates = get_rates_from_pack(rate_map)
        assert rates.awf_low_pct == Decimal("2.50")
        assert rates.awf_high_pct == Decimal("8.00")
        assert rates.aof_small_pct == Decimal("6.00")
        assert rates.aof_large_pct == Decimal("7.50")
        assert rates.wko_pct == Decimal("0.60")


class TestAwfContractFacts:
    def test_permanent_qualifies_low(self):
        c = AwfContractFacts(
            is_permanent=True,
            fixed_term_months=None,
            has_written_contract=True,
            is_on_call_no_guaranteed_hours=False,
            is_standby_contract=False,
        )
        assert c.qualifies_for_low_rate()

    def test_fixed_term_12_months_written_is_high(self):
        """S6: only a written INDEFINITE contract qualifies — fixed-term of any length is high."""
        c = AwfContractFacts(
            is_permanent=False,
            fixed_term_months=12,
            has_written_contract=True,
            is_on_call_no_guaranteed_hours=False,
            is_standby_contract=False,
        )
        assert not c.qualifies_for_low_rate()

    def test_permanent_unwritten_is_high(self):
        c = AwfContractFacts(is_permanent=True, fixed_term_months=None, has_written_contract=False,
                             is_on_call_no_guaranteed_hours=False, is_standby_contract=False)
        assert not c.qualifies_for_low_rate()

    def test_statutory_exception_qualifies_low(self):
        c = AwfContractFacts(is_permanent=False, fixed_term_months=6, has_written_contract=True,
                             is_on_call_no_guaranteed_hours=False, is_standby_contract=False,
                             statutory_exception_code="BBL")
        assert c.qualifies_for_low_rate()
        assert "BBL" in c.low_rate_reason()

    def test_fixed_term_11_months_fails(self):
        c = AwfContractFacts(
            is_permanent=False,
            fixed_term_months=11,
            has_written_contract=True,
            is_on_call_no_guaranteed_hours=False,
            is_standby_contract=False,
        )
        assert not c.qualifies_for_low_rate()

    def test_fixed_term_no_written_fails(self):
        c = AwfContractFacts(
            is_permanent=False,
            fixed_term_months=12,
            has_written_contract=False,
            is_on_call_no_guaranteed_hours=False,
            is_standby_contract=False,
        )
        assert not c.qualifies_for_low_rate()

    def test_on_call_no_guaranteed_hours_fails(self):
        c = AwfContractFacts(
            is_permanent=True,
            fixed_term_months=None,
            has_written_contract=True,
            is_on_call_no_guaranteed_hours=True,
            is_standby_contract=False,
        )
        assert not c.qualifies_for_low_rate()

    def test_standby_contract_fails(self):
        c = AwfContractFacts(
            is_permanent=True,
            fixed_term_months=None,
            has_written_contract=True,
            is_on_call_no_guaranteed_hours=False,
            is_standby_contract=True,
        )
        assert not c.qualifies_for_low_rate()


class TestAwfCalculation:
    def _make_vcr_result(self, base_increment: Decimal) -> "VcrResult":
        from app.modules.payroll.engine.jurisdictions.netherlands.vcr import VcrResult
        return VcrResult(
            new_state=initial_state(),
            base_increment=base_increment,
            period_wage=base_increment,
            period_max=Decimal("6617.41"),
        )

    def test_awf_low_rate(self):
        """AWf low rate 2.74% on €5000 base_increment = €137.00 (F2)."""
        rates = EwPremiumRates(
            awf_low_pct=Decimal("2.74"),
            awf_high_pct=Decimal("7.74"),
            aof_small_pct=Decimal("6.27"),
            aof_large_pct=Decimal("7.63"),
            wko_pct=Decimal("0.50"),
        )
        contract = AwfContractFacts(
            is_permanent=True,
            fixed_term_months=None,
            has_written_contract=True,
            is_on_call_no_guaranteed_hours=False,
            is_standby_contract=False,
        )
        vcr_res = self._make_vcr_result(Decimal("5000"))
        res = calculate_awf(vcr_res, contract, rates)
        assert res.rate_pct == Decimal("2.74")
        assert res.amount == Decimal("137.00")

    def test_awf_high_rate(self):
        """AWf high rate 7.74% on €5000 base_increment = €387.00 (F4)."""
        rates = EwPremiumRates(
            awf_low_pct=Decimal("2.74"),
            awf_high_pct=Decimal("7.74"),
            aof_small_pct=Decimal("6.27"),
            aof_large_pct=Decimal("7.63"),
            wko_pct=Decimal("0.50"),
        )
        contract = AwfContractFacts(
            is_permanent=False,
            fixed_term_months=6,
            has_written_contract=True,
            is_on_call_no_guaranteed_hours=False,
            is_standby_contract=False,
        )
        vcr_res = self._make_vcr_result(Decimal("5000"))
        res = calculate_awf(vcr_res, contract, rates)
        assert res.rate_pct == Decimal("7.74")
        assert res.amount == Decimal("387.00")

    def test_awf_rounding_half_up(self):
        """Rounding half-up to cents."""
        rates = EwPremiumRates(
            awf_low_pct=Decimal("2.74"),
            awf_high_pct=Decimal("7.74"),
            aof_small_pct=Decimal("6.27"),
            aof_large_pct=Decimal("7.63"),
            wko_pct=Decimal("0.50"),
        )
        contract = AwfContractFacts(
            is_permanent=True,
            fixed_term_months=None,
            has_written_contract=True,
            is_on_call_no_guaranteed_hours=False,
            is_standby_contract=False,
        )
        # 5001 * 2.74% = 137.0274 → 137.03
        vcr_res = self._make_vcr_result(Decimal("5001"))
        res = calculate_awf(vcr_res, contract, rates)
        assert res.amount == Decimal("137.03")


class TestAofCalculation:
    def _make_vcr_result(self, base_increment: Decimal):
        from app.modules.payroll.engine.jurisdictions.netherlands.vcr import VcrResult
        return VcrResult(
            new_state=initial_state(),
            base_increment=base_increment,
            period_wage=base_increment,
            period_max=Decimal("6617.41"),
        )

    def test_aof_small_employer(self):
        """Aof small 6.27% on €5000 = €313.50 (F2)."""
        rates = EwPremiumRates(
            awf_low_pct=Decimal("2.74"),
            awf_high_pct=Decimal("7.74"),
            aof_small_pct=Decimal("6.27"),
            aof_large_pct=Decimal("7.63"),
            wko_pct=Decimal("0.50"),
        )
        decision = EmployerPremiumDecision(
            aof_size_class="SMALL",
            whk_wga_pct=Decimal("0"),
            whk_wga_employee_recoverable_pct=None,
            whk_zw_flex_pct=Decimal("0"),
        )
        vcr_res = self._make_vcr_result(Decimal("5000"))
        res = calculate_aof(vcr_res, decision, rates)
        assert res.rate_pct == Decimal("6.27")
        assert res.amount == Decimal("313.50")

    def test_aof_large_employer(self):
        """Aof large 7.63% on €5000 = €381.50."""
        rates = EwPremiumRates(
            awf_low_pct=Decimal("2.74"),
            awf_high_pct=Decimal("7.74"),
            aof_small_pct=Decimal("6.27"),
            aof_large_pct=Decimal("7.63"),
            wko_pct=Decimal("0.50"),
        )
        decision = EmployerPremiumDecision(
            aof_size_class="LARGE",
            whk_wga_pct=Decimal("0"),
            whk_wga_employee_recoverable_pct=None,
            whk_zw_flex_pct=Decimal("0"),
        )
        vcr_res = self._make_vcr_result(Decimal("5000"))
        res = calculate_aof(vcr_res, decision, rates)
        assert res.rate_pct == Decimal("7.63")
        assert res.amount == Decimal("381.50")

    def test_aof_invalid_size_class_raises(self):
        rates = EwPremiumRates(
            awf_low_pct=Decimal("2.74"),
            awf_high_pct=Decimal("7.74"),
            aof_small_pct=Decimal("6.27"),
            aof_large_pct=Decimal("7.63"),
            wko_pct=Decimal("0.50"),
        )
        decision = EmployerPremiumDecision(
            aof_size_class="MEDIUM",
            whk_wga_pct=Decimal("0"),
            whk_wga_employee_recoverable_pct=None,
            whk_zw_flex_pct=Decimal("0"),
        )
        vcr_res = self._make_vcr_result(Decimal("5000"))
        with pytest.raises(ValueError, match="Unknown Aof size class"):
            calculate_aof(vcr_res, decision, rates)


class TestWkoCalculation:
    def _make_vcr_result(self, base_increment: Decimal):
        from app.modules.payroll.engine.jurisdictions.netherlands.vcr import VcrResult
        return VcrResult(
            new_state=initial_state(),
            base_increment=base_increment,
            period_wage=base_increment,
            period_max=Decimal("6617.41"),
        )

    def test_wko_fixed_rate(self):
        """Wko fixed 0.50% on €5000 = €25.00 (F2)."""
        rates = EwPremiumRates(
            awf_low_pct=Decimal("2.74"),
            awf_high_pct=Decimal("7.74"),
            aof_small_pct=Decimal("6.27"),
            aof_large_pct=Decimal("7.63"),
            wko_pct=Decimal("0.50"),
        )
        vcr_res = self._make_vcr_result(Decimal("5000"))
        res = calculate_wko(vcr_res, rates)
        assert res.rate_pct == Decimal("0.50")
        assert res.amount == Decimal("25.00")


class TestWhkCalculation:
    def _make_vcr_result(self, base_increment: Decimal):
        from app.modules.payroll.engine.jurisdictions.netherlands.vcr import VcrResult
        return VcrResult(
            new_state=initial_state(),
            base_increment=base_increment,
            period_wage=base_increment,
            period_max=Decimal("6617.41"),
        )

    def test_whk_employer_total(self):
        """Whk WGA + ZW Flex employer total."""
        decision = EmployerPremiumDecision(
            aof_size_class="LARGE",
            whk_wga_pct=Decimal("1.20"),
            whk_wga_employee_recoverable_pct=Decimal("0.30"),
            whk_zw_flex_pct=Decimal("0.80"),
        )
        vcr_res = self._make_vcr_result(Decimal("5000"))
        res = calculate_whk(vcr_res, decision)
        # WGA: 5000 * 1.20% = 60.00
        # ZW Flex: 5000 * 0.80% = 40.00
        # Employer total: 100.00
        # Employee recoverable: 5000 * 0.30% = 15.00
        assert res.employer_wga == Decimal("60.00")
        assert res.employer_zw_flex == Decimal("40.00")
        assert res.employer_total == Decimal("100.00")
        assert res.employee_recoverable == Decimal("15.00")

    def test_whk_no_employee_recoverable(self):
        """Whk without employee-recoverable part."""
        decision = EmployerPremiumDecision(
            aof_size_class="LARGE",
            whk_wga_pct=Decimal("1.20"),
            whk_wga_employee_recoverable_pct=None,
            whk_zw_flex_pct=Decimal("0.80"),
        )
        vcr_res = self._make_vcr_result(Decimal("5000"))
        res = calculate_whk(vcr_res, decision)
        assert res.employee_recoverable == Decimal("0")

    def test_whk_missing_rates_raises(self):
        """Fails closed if decision missing WGA or ZW Flex rate (NL-018)."""
        decision = EmployerPremiumDecision(
            aof_size_class="LARGE",
            whk_wga_pct=None,
            whk_wga_employee_recoverable_pct=None,
            whk_zw_flex_pct=Decimal("0.80"),
        )
        vcr_res = self._make_vcr_result(Decimal("5000"))
        with pytest.raises(ValueError, match="Whk decision missing WGA"):
            calculate_whk(vcr_res, decision)

        decision2 = EmployerPremiumDecision(
            aof_size_class="LARGE",
            whk_wga_pct=Decimal("1.20"),
            whk_wga_employee_recoverable_pct=None,
            whk_zw_flex_pct=None,
        )
        with pytest.raises(ValueError, match="Whk decision missing WGA"):
            calculate_whk(vcr_res, decision2)


class TestEiPeriodCalculation:
    """Full EI period calculation integration."""

    def _make_vcr_result(self, base_increment: Decimal):
        from app.modules.payroll.engine.jurisdictions.netherlands.vcr import VcrResult
        return VcrResult(
            new_state=initial_state(),
            base_increment=base_increment,
            period_wage=base_increment,
            period_max=Decimal("6617.41"),
        )

    def test_full_ei_period_f2_values(self):
        """F2: AWf €137.00, Aof €313.50, Wko €25.00 at €5000 base_increment."""
        rates = EwPremiumRates(
            awf_low_pct=Decimal("2.74"),
            awf_high_pct=Decimal("7.74"),
            aof_small_pct=Decimal("6.27"),
            aof_large_pct=Decimal("7.63"),
            wko_pct=Decimal("0.50"),
        )
        contract = AwfContractFacts(
            is_permanent=True,
            fixed_term_months=None,
            has_written_contract=True,
            is_on_call_no_guaranteed_hours=False,
            is_standby_contract=False,
        )
        decision = EmployerPremiumDecision(
            aof_size_class="SMALL",
            whk_wga_pct=Decimal("0"),
            whk_wga_employee_recoverable_pct=None,
            whk_zw_flex_pct=Decimal("0"),
        )
        vcr_res = self._make_vcr_result(Decimal("5000"))

        res = calculate_ei_period(vcr_res, contract, decision, rates)

        assert res.awf.amount == Decimal("137.00")   # F2
        assert res.aof.amount == Decimal("313.50")   # F2
        assert res.wko.amount == Decimal("25.00")    # F2
        assert res.whk.employer_total == Decimal("0")  # Whk not in F2 base
        assert res.ei_base_increment == Decimal("5000")

    def test_full_ei_period_with_whk(self):
        """Full EI with Whk WGA+ZW Flex."""
        rates = EwPremiumRates(
            awf_low_pct=Decimal("2.74"),
            awf_high_pct=Decimal("7.74"),
            aof_small_pct=Decimal("6.27"),
            aof_large_pct=Decimal("7.63"),
            wko_pct=Decimal("0.50"),
        )
        contract = AwfContractFacts(
            is_permanent=True,
            fixed_term_months=None,
            has_written_contract=True,
            is_on_call_no_guaranteed_hours=False,
            is_standby_contract=False,
        )
        decision = EmployerPremiumDecision(
            aof_size_class="LARGE",
            whk_wga_pct=Decimal("1.20"),
            whk_wga_employee_recoverable_pct=Decimal("0.30"),
            whk_zw_flex_pct=Decimal("0.80"),
        )
        vcr_res = self._make_vcr_result(Decimal("5000"))

        res = calculate_ei_period(vcr_res, contract, decision, rates)

        assert res.awf.amount == Decimal("137.00")
        assert res.aof.amount == Decimal("381.50")  # LARGE
        assert res.wko.amount == Decimal("25.00")
        assert res.whk.employer_total == Decimal("100.00")
        assert res.whk.employee_recoverable == Decimal("15.00")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])