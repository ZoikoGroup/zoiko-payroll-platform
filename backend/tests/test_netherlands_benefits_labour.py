"""
tests/test_netherlands_benefits_labour.py
-----------------------------------------
Pure helpers for ZP-NL-ENG-001 Phases 6–7: vacation allowance (NL-009), WKR
(NL-022/023), company car (NL-024/025), expat facility (NL-026..028),
minimum wage (NL-041), sickness-pay floor (NL-042), pension (NL-043) and the
transition payment (NL-044). All figures are the spec's own 2026 content.
"""

from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from app.modules.payroll.engine.jurisdictions.netherlands import (
    company_car, expat, minimum_wage, pension, sickness_pay, transition_payment, vacation_allowance, wkr,
)


def _slab(rule, key, *, amount=None, rate="0", lo="0", hi=None, eff_from=None, eff_to=None):
    return SimpleNamespace(rule_type=rule, filing_status=key, flat_amount=None if amount is None else D(amount),
                           rate_pct=D(rate), min_amount=D(lo), max_amount=None if hi is None else D(hi),
                           effective_from=eff_from, effective_to=eff_to)


MIN_WAGE = [_slab("NL_MIN_WAGE", "AGE_21_PLUS", amount="14.71", eff_from=date(2026, 1, 1), eff_to=date(2026, 6, 30)),
            _slab("NL_MIN_WAGE", "AGE_21_PLUS", amount="14.99", eff_from=date(2026, 7, 1)),
            _slab("NL_MIN_WAGE", "AGE_18", amount="7.50", eff_from=date(2026, 7, 1))]
WKR_BANDS = [_slab("NL_WKR_BAND", "FREE_SPACE", rate="2.0000", hi="400000.00"),
             _slab("NL_WKR_BAND", "FREE_SPACE", rate="1.1800", lo="400000.00"),
             _slab("NL_WKR_BAND", "EXCESS_LEVY", rate="80.0000")]
CARS = [_slab("NL_CAR_ADDITION", "STANDARD", rate="22.0000", eff_from=date(2026, 1, 1)),
        _slab("NL_CAR_ADDITION", "ZERO_EMISSION", rate="18.0000", eff_from=date(2026, 1, 1))]


class TestVacationAllowance:
    def test_statutory_minimum_applies_without_override(self):
        assert vacation_allowance.resolve_pct(D("8.00"), None) == D("8.00")

    def test_higher_cao_percentage_wins(self):
        assert vacation_allowance.resolve_pct(D("8.00"), D("8.33")) == D("8.33")

    def test_below_statutory_needs_lawful_alternative(self):
        with pytest.raises(vacation_allowance.VacationAllowanceError):
            vacation_allowance.resolve_pct(D("8.00"), D("6.00"))
        assert vacation_allowance.resolve_pct(D("8.00"), D("6.00"), lawful_alternative_ref="CAO art 12") == D("6.00")

    def test_unconfigured_statutory_minimum_blocks(self):
        with pytest.raises(vacation_allowance.VacationAllowanceError):
            vacation_allowance.resolve_pct(None, None)

    def test_basis_is_earning_code_driven(self):
        cls = {"base_salary": {"vacation_allowance_basis": True}, "expense": {"vacation_allowance_basis": False}}
        assert vacation_allowance.basis({"base_salary": D("5000"), "expense": D("200")}, cls) == D("5000")

    def test_accrual_and_payout_ledger_balance(self):
        r = vacation_allowance.accrue(basis_amount=D("5000"), pct=D("8"), prior_balance=D("2000"), payout=D("2400"))
        assert (r.accrual, r.balance_after) == (D("400.00"), D("0.00"))


class TestWkr:
    def test_free_space_bands(self):
        assert wkr.free_space(D("400000"), WKR_BANDS) == D("8000.00")
        assert wkr.free_space(D("500000"), WKR_BANDS) == D("9180.00")   # 8000 + 1.18% x 100000

    def test_excess_levy_80pct(self):
        pos = wkr.advance(wkr.WkrState(), fiscal_wage=D("100000"), designated=D("2500"), targeted=D("0"), slabs=WKR_BANDS)
        assert (pos.free_space_available, pos.excess_amount, pos.excess_levy) == (D("2000.00"), D("500.00"), D("400.00"))

    def test_targeted_exemptions_do_not_consume_free_space(self):
        pos = wkr.advance(wkr.WkrState(), fiscal_wage=D("100000"), designated=D("0"), targeted=D("5000"), slabs=WKR_BANDS)
        assert pos.excess_amount == D("0.00")

    def test_payslip_components_need_a_treatment(self):
        with pytest.raises(wkr.WkrError, match="no WKR treatment"):
            wkr.payslip_components({"expense": D("10")}, {}, fiscal_wage=D("0"))

    def test_missing_bands_block(self):
        with pytest.raises(wkr.WkrError):
            wkr.free_space(D("1"), [])


class TestCompanyCar:
    CAR = {"id": 1, "vehicle_class": "STANDARD", "catalog_value": "36000", "first_admission_date": "2026-03-01",
           "private_use_status": "PRIVATE", "employee_own_contribution": "50"}

    def test_standard_addition_spread_over_periods(self):
        r = company_car.period_addition(self.CAR, slabs=CARS, periods_per_year=12)
        assert (r.annual_addition, r.period_addition) == (D("7920.00"), D("610.00"))   # 660 - 50 own contribution

    def test_older_car_without_its_own_window_blocks(self):
        with pytest.raises(company_car.CompanyCarError, match="older vehicles"):
            company_car.period_addition({**self.CAR, "first_admission_date": "2019-05-01"}, slabs=CARS,
                                        periods_per_year=12)

    def test_zero_emission_needs_the_cap(self):
        with pytest.raises(company_car.CompanyCarError, match="cap"):
            company_car.period_addition({**self.CAR, "vehicle_class": "ZERO_EMISSION"}, slabs=CARS, periods_per_year=12)

    def test_no_private_use_needs_evidence(self):
        with pytest.raises(company_car.CompanyCarError, match="evidence"):
            company_car.period_addition({**self.CAR, "private_use_status": "NO_PRIVATE_USE_500KM"}, slabs=CARS,
                                        periods_per_year=12)
        r = company_car.period_addition({**self.CAR, "private_use_status": "NO_PRIVATE_USE_500KM",
                                         "no_private_use_evidence_ref": "rittenregistratie-2026"}, slabs=CARS,
                                        periods_per_year=12)
        assert r.period_addition == D("0.00") and r.no_private_use


class TestExpat:
    PARAMS = {"nl_expat_salary_threshold": D("48013"), "nl_expat_salary_threshold_young_master": D("36497"),
              "nl_expat_allowance_cap": D("78600"), "nl_wnt_cap": D("262000"), "nl_expat_max_facility_pct": D("30")}
    DECISION = {"status": "VERIFIED", "granted_from": date(2026, 1, 1), "granted_to": date(2030, 12, 31),
                "method": "FACILITY_30PCT", "threshold_category": "STANDARD", "allowance_pct": D("30"),
                "decision_reference": "BD-30-1"}

    def _apply(self, package, **over):
        return expat.apply({**self.DECISION, **over}, package=D(package), on=date(2026, 3, 31), periods_per_year=12,
                           params=self.PARAMS)

    def test_f5_full_30pct_when_threshold_and_cap_allow(self):
        r = self._apply("10000")
        assert (r.allowance, r.taxable_wage, r.risk) == (D("3000.00"), D("7000.00"), None)

    def test_wnt_cap_limits_the_package(self):
        assert self._apply("30000").allowance == D("6550.00")                    # 78600 / 12

    def test_threshold_preserved(self):
        r = self._apply("5000")
        assert r.taxable_wage == D("4001.08") and r.risk

    def test_below_threshold_not_applied(self):
        r = self._apply("3500")
        assert r.applied is False and r.allowance == D("0.00") and r.risk

    def test_research_category_has_no_salary_norm(self):
        assert self._apply("3500", threshold_category="RESEARCH_MEDICAL").allowance == D("1050.00")

    def test_hr_checkbox_is_not_a_decision(self):
        assert self._apply("10000", status="PENDING").applied is False

    def test_decision_above_statutory_maximum_blocks(self):
        with pytest.raises(expat.ExpatError):
            self._apply("10000", allowance_pct=D("35"))


class TestMinimumWage:
    def test_f6_july_rate_and_january_history(self):
        july = minimum_wage.check(slabs=MIN_WAGE, date_of_birth=date(1990, 1, 1), pay_date=date(2026, 7, 31),
                                  reckonable_wage=D("2600"), hours=D("173.33"))
        jan = minimum_wage.check(slabs=MIN_WAGE, date_of_birth=date(1990, 1, 1), pay_date=date(2026, 1, 31),
                                 reckonable_wage=D("2600"), hours=D("173.33"))
        assert (july.required_hourly, jan.required_hourly) == (D("14.99"), D("14.71"))
        assert july.compliant and jan.compliant

    def test_breach_reports_shortfall(self):
        r = minimum_wage.check(slabs=MIN_WAGE, date_of_birth=date(1990, 1, 1), pay_date=date(2026, 7, 31),
                               reckonable_wage=D("2000"), hours=D("173.33"))
        assert not r.compliant and r.shortfall == D("598.22")

    def test_hours_required(self):
        with pytest.raises(minimum_wage.MinimumWageError, match="hours"):
            minimum_wage.check(slabs=MIN_WAGE, date_of_birth=date(1990, 1, 1), pay_date=date(2026, 7, 31),
                               reckonable_wage=D("2600"), hours=None)

    def test_missing_january_youth_rate_blocks(self):
        with pytest.raises(minimum_wage.MinimumWageError, match="AGE_18"):
            minimum_wage.check(slabs=MIN_WAGE, date_of_birth=date(2008, 1, 1), pay_date=date(2026, 1, 31),
                               reckonable_wage=D("1200"), hours=D("150"))

    def test_period_hours(self):
        assert minimum_wage.period_hours(D("40"), 12) == D("173.33")


class TestSickness:
    POLICY = {"year1_pct": "70", "year2_pct": "70", "year1_min_wage_floor": True, "cao_enhancements": {}}

    def test_year_one_min_wage_floor(self):
        f = sickness_pay.floor(policy=self.POLICY, statutory_pct=D("70"), first_sick_day=date(2026, 1, 10),
                               on=date(2026, 3, 31), contractual_wage=D("2000"), min_wage_period=D("2549.68"))
        assert f.sickness_year == 1 and f.floor == D("2549.68")

    def test_cao_topup_and_year_two(self):
        policy = {**self.POLICY, "cao_enhancements": {"year1_pct_topup": 30, "year2_pct_topup": 0}}
        y1 = sickness_pay.floor(policy=policy, statutory_pct=D("70"), first_sick_day=date(2026, 1, 1),
                                on=date(2026, 2, 28), contractual_wage=D("5000"), min_wage_period=D("2549.68"))
        y2 = sickness_pay.floor(policy=policy, statutory_pct=D("70"), first_sick_day=date(2025, 1, 1),
                                on=date(2026, 3, 31), contractual_wage=D("5000"), min_wage_period=None)
        assert (y1.pct, y1.floor) == (D("100"), D("5000.00"))
        assert (y2.sickness_year, y2.floor) == (2, D("3500.00"))

    def test_policy_below_statutory_blocks(self):
        with pytest.raises(sickness_pay.SicknessPayError):
            sickness_pay.floor(policy={**self.POLICY, "year1_pct": "60"}, statutory_pct=D("70"),
                               first_sick_day=date(2026, 1, 1), on=date(2026, 2, 1), contractual_wage=D("5000"),
                               min_wage_period=D("1"))

    def test_after_two_years_no_statutory_floor(self):
        assert sickness_pay.floor(policy=self.POLICY, statutory_pct=D("70"), first_sick_day=date(2023, 1, 1),
                                  on=date(2026, 1, 31), contractual_wage=D("5000"), min_wage_period=None) is None


class TestPension:
    SCHEME = {"scheme_code": "PFZW-TEST", "basis_rule": "GROSS_MINUS_FRANCHISE", "franchise_amount": "18000",
              "employee_pct": "7.5", "employer_pct": "15"}

    def test_franchise_spread_over_periods(self):
        r = pension.contributions(self.SCHEME, pensionable_earnings=D("5000"), periods_per_year=12)
        assert (r.basis, r.employee, r.employer) == (D("3500.00"), D("262.50"), D("525.00"))

    def test_capped_pensionable_salary(self):
        r = pension.contributions({**self.SCHEME, "basis_rule": "CAPPED_PENSIONABLE", "max_pensionable_salary": "60000"},
                                  pensionable_earnings=D("9000"), periods_per_year=12)
        assert r.basis == D("3500.00")

    def test_no_scheme(self):
        assert pension.contributions(None, pensionable_earnings=D("5000"), periods_per_year=12) is None

    def test_unknown_rule_blocks(self):
        with pytest.raises(pension.PensionError):
            pension.contributions({**self.SCHEME, "basis_rule": "NOT_IN_FORCE"}, pensionable_earnings=D("1"),
                                  periods_per_year=12)


class TestTransitionPayment:
    def test_one_third_month_per_year_pro_rata(self):
        r = transition_payment.calculate(initiated_by="EMPLOYER", service_months=30, monthly_salary=D("6000"),
                                         annual_salary=D("72000"), statutory_cap=D("102000"), month_fraction="1/3")
        assert r.eligible and r.amount == D("5000.00")                       # 6000 x 1/3 x 2.5 years

    def test_cap_is_max_of_statutory_and_annual_salary(self):
        r = transition_payment.calculate(initiated_by="EMPLOYER", service_months=480, monthly_salary=D("20000"),
                                         annual_salary=D("240000"), statutory_cap=D("102000"), month_fraction="1/3")
        assert r.cap_applied and r.amount == D("240000.00")

    def test_resignation_has_no_statutory_entitlement(self):
        r = transition_payment.calculate(initiated_by="EMPLOYEE", service_months=60, monthly_salary=D("5000"),
                                         annual_salary=D("60000"), statutory_cap=D("102000"), month_fraction="1/3")
        assert not r.eligible and r.amount == D("0.00")

    def test_four_eyes(self):
        with pytest.raises(transition_payment.FourEyesError):
            transition_payment.validate_four_eyes(5, 5)
