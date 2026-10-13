"""
tests/test_netherlands_engine.py
--------------------------------
engine/countries/netherlands.py against the ZP-NL-ENG-001 §18 fixtures.

The official 2026 wage-tax tables are NOT in the repository (gate G1), so the
wage-tax rows used here are a SYNTHETIC plumbing fixture: one band whose
amount is the spec's F1 published result (€1,325.08 on €5,000/month with the
credit). They prove the lookup/selection/rounding path, not the table itself.
Employer premiums (F2), VCR (F3), AWf class (F4), expat (F5) and minimum wage
(F6) are computed from the spec's stated rates and are exact.
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.countries.netherlands import (
    NetherlandsCalculationBlockedError, calculate, normalise_period,
)
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
from app.modules.payroll.engine.resolver import calculate_payroll


def _rate(employee=None, employer=None, amount=None, text=None):
    return SimpleNamespace(employee_rate_pct=None if employee is None else Decimal(employee),
                           employer_rate_pct=None if employer is None else Decimal(employer),
                           flat_amount=None if amount is None else Decimal(amount), text_value=text)


RATES = {
    "nl_awf_low_pct": _rate(employer="2.7400"), "nl_awf_high_pct": _rate(employer="7.7400"),
    "nl_aof_low_pct": _rate(employer="6.2700"), "nl_aof_high_pct": _rate(employer="7.6300"),
    "nl_wko_pct": _rate(employer="0.5000"),
    "nl_zvw_employer_pct": _rate(employer="6.1000"), "nl_zvw_employee_pct": _rate(employee="4.8500"),
    "nl_anonymous_rate_pct": _rate(employee="52.00"),
    "nl_vacation_allowance_pct": _rate(employee="8.00"), "nl_sick_pay_pct": _rate(employee="70.00"),
    "nl_expat_salary_threshold": _rate(amount="48013.00"),
    "nl_expat_salary_threshold_young_master": _rate(amount="36497.00"),
    "nl_expat_max_facility_pct": _rate(employee="30.00"),
    "nl_expat_allowance_cap": _rate(amount="78600.00"), "nl_wnt_cap": _rate(amount="262000.00"),
}


def _slab(rule, key, amount=None, rate="0", lo="0", hi=None, eff_from=None, eff_to=None):
    return SimpleNamespace(rule_type=rule, filing_status=key, flat_amount=None if amount is None else Decimal(amount),
                           rate_pct=Decimal(rate), min_amount=Decimal(lo), max_amount=None if hi is None else Decimal(hi),
                           effective_from=eff_from, effective_to=eff_to)


SLABS = [
    _slab("NL_PERIOD_MAX", "MONTHLY", "6617.41"), _slab("NL_PERIOD_MAX", "ANNUAL", "79409.00"),
    _slab("NL_MIN_WAGE", "AGE_21_PLUS", "14.71", eff_from=date(2026, 1, 1), eff_to=date(2026, 6, 30)),
    _slab("NL_MIN_WAGE", "AGE_21_PLUS", "14.99", eff_from=date(2026, 7, 1)),
    _slab("NL_WKR_BAND", "FREE_SPACE", rate="2.0000", hi="400000.00"),
    _slab("NL_WKR_BAND", "FREE_SPACE", rate="1.1800", lo="400000.00"),
    _slab("NL_WKR_BAND", "EXCESS_LEVY", rate="80.0000"),
    _slab("NL_CAR_ADDITION", "STANDARD", rate="22.0000", eff_from=date(2026, 1, 1)),
]

REGULAR = {"remuneration_type": "REGULAR", "wage_tax": True, "employee_insurance_wage": True, "zvw_wage": True,
           "pensionable": True, "wkr_treatment": "WAGE", "vacation_allowance_basis": True,
           "minimum_wage_reckonable": True}

# SYNTHETIC plumbing rows (see module docstring) — not the official table.
SYNTHETIC_ROWS = [
    {"wage_from": Decimal("0"), "wage_to": Decimal("5000"), "aow_cohort": "BELOW_AOW", "with_tax_credit": True,
     "withholding_amount": Decimal("1000.00")},
    {"wage_from": Decimal("5000"), "wage_to": None, "aow_cohort": "BELOW_AOW", "with_tax_credit": True,
     "withholding_amount": Decimal("1325.08")},
    {"wage_from": Decimal("0"), "wage_to": None, "aow_cohort": "BELOW_AOW", "with_tax_credit": False,
     "withholding_amount": Decimal("1900.00")},
]

PROFILE = SimpleNamespace(nl_table_color="WHITE", nl_residence_variant="NL", nl_zvw_path="EMPLOYER_LEVY",
                          nl_ei_insured=True, nl_insurance_exception_code=None, nl_cross_border_status="NONE",
                          nl_voluntary_extra_withholding=None, nl_vacation_allowance_pct=None,
                          nl_contract_hours_per_week=Decimal("40"))

LOW_CONTRACT = {"contract_term": "INDEFINITE", "written_record": True, "on_call": False, "statutory_exception_code": None}
SMALL_EMPLOYER = {"aof_size_class": "SMALL", "whk_wga_pct": Decimal("0.0000"), "whk_zw_flex_pct": Decimal("0.0000"),
                  "whk_wga_employee_recoverable_pct": None}


def _ctx(**over):
    base = dict(gross=Decimal("5000"), basic=Decimal("5000"), country="NL", pay_date=date(2026, 1, 31),
                date_of_birth=date(1990, 5, 15), pay_frequency="Monthly", rate_map=dict(RATES), slabs=list(SLABS),
                nl_statutory_profile=PROFILE, nl_organization_id=1, nl_employee_id=1, nl_with_tax_credit=True,
                nl_wage_tax_table={"fileId": 1, "fileSha256": "synthetic", "rows": SYNTHETIC_ROWS},
                nl_contract=LOW_CONTRACT, nl_premium_decision=SMALL_EMPLOYER, nl_vcr_before={},
                nl_earning_classifications={"base_salary": REGULAR})
    base.update(over)
    return PayrollContext(**base)


def _nl(**over):
    return calculate(_ctx(**over))


class TestF1F2:
    def test_f1_plumbing_and_f2_employer_premiums(self):
        out = _nl()
        nl = out["nl_result"]
        assert out["tds"] == Decimal("1325.08")                 # F1 (synthetic row)
        assert nl["totals"]["netPay"] == "3674.92"               # F1 net before pension/other
        assert nl["employeeInsurance"]["awf"] == "137.00"        # F2
        assert nl["employeeInsurance"]["aof"] == "313.50"        # F2
        assert nl["employeeInsurance"]["wko"] == "25.00"         # F2
        assert nl["zvw"]["employerLevy"] == "305.00"             # F2
        assert nl["employeeInsurance"]["awfClass"] == "LOW"

    def test_employer_premiums_never_reduce_net(self):
        out = _nl()
        assert out["nl_employee_total"] == Decimal("0.00")
        assert out["employer_social_security"] == Decimal("780.50")  # 137 + 313.50 + 25 + 305

    def test_through_standard_strategy(self):
        result = calculate_payroll(_ctx(), "standard")
        assert result.tds == Decimal("1325.08")
        assert result.net_pay == Decimal("3674.92")
        assert result.nl_result["zvw"]["employerLevy"] == "305.00"

    def test_simple_mode_refused(self):
        with pytest.raises(Exception, match="NL_SIMPLE_MODE_UNSUPPORTED"):
            calculate_payroll(_ctx(), "simple")


class TestF3Vcr:
    def test_catch_up_after_high_month(self):
        month1 = _nl(gross=Decimal("8000"), basic=Decimal("8000"))["nl_result"]
        assert month1["vcr"]["increments"]["EI"] == "6617.41"
        month2 = _nl(gross=Decimal("5000"), basic=Decimal("5000"), pay_date=date(2026, 2, 28),
                     nl_vcr_before=month1["vcr"]["after"])["nl_result"]
        # cumulative wage 13000 vs cumulative max 13234.82 -> base 13000 -> increment 6382.59
        assert month2["vcr"]["increments"]["EI"] == "6382.59"
        assert month2["vcr"]["after"]["EI"]["revision"] == 2


class TestF4Awf:
    def test_fixed_term_pays_high(self):
        nl = _nl(nl_contract={**LOW_CONTRACT, "contract_term": "FIXED"})["nl_result"]
        assert nl["employeeInsurance"]["awfClass"] == "HIGH"
        assert nl["employeeInsurance"]["awf"] == "387.00"
        assert any(t["code"] == "AWF_CLASS" and "not met" in t["reason"] for t in nl["trace"])


class TestF5Expat:
    def test_allowance_capped_and_threshold_preserved(self):
        decision = {"status": "VERIFIED", "granted_from": date(2025, 1, 1), "granted_to": None,
                    "method": "FACILITY_30PCT", "threshold_category": "STANDARD", "allowance_pct": Decimal("30"),
                    "decision_reference": "BD-1"}
        nl = _nl(nl_expat_decision=decision)["nl_result"]
        # 30% of 5000 = 1500; threshold/12 = 4001.08 -> headroom 998.92 -> allowance reduced
        assert nl["expat"]["allowance"] == "998.92"
        assert nl["expat"]["taxableWage"] == "4001.08"
        assert any(e["code"] == "EXPAT_THRESHOLD_RISK" for e in nl["exceptions"])

    def test_unverified_decision_is_ignored(self):
        nl = _nl(nl_expat_decision={"status": "PENDING"})["nl_result"]
        assert nl["expat"]["applied"] is False


class TestF6MinimumWage:
    def test_july_rate(self):
        nl = _nl(pay_date=date(2026, 7, 31))["nl_result"]
        assert nl["minimumWage"]["requiredHourly"] == "14.99"

    def test_january_rate_kept_for_history(self):
        assert _nl()["nl_result"]["minimumWage"]["requiredHourly"] == "14.71"

    def test_breach_blocks_approval_not_calculation(self):
        nl = _nl(gross=Decimal("2000"), basic=Decimal("2000"))["nl_result"]
        assert nl["status"] == "BLOCKED_EXCEPTIONS"
        assert any(e["code"] == "MIN_WAGE_BREACH" and e["severity"] == "BLOCK" for e in nl["exceptions"])

    def test_youth_january_rate_missing_is_a_block_exception(self):
        nl = _nl(date_of_birth=date(2007, 6, 1))["nl_result"]  # age 18 in January 2026
        assert any(e["code"] == "MIN_WAGE_UNVERIFIED" for e in nl["exceptions"])


class TestFailClosed:
    def test_block_is_a_compliance_error(self):
        assert issubclass(NetherlandsCalculationBlockedError, MissingComplianceConfigurationError)

    @pytest.mark.parametrize("override,key", [
        ({"nl_wage_tax_table": None}, "nl_wage_tax_table"),
        ({"nl_premium_decision": None}, "nl_premium_decision"),
        ({"nl_contract": None}, "nl_contract"),
        ({"nl_vcr_before": None}, "nl_vcr_before"),
        ({"nl_earning_classifications": {}}, "nl_earning_classification"),
        ({"nl_statutory_profile": None}, "nl_statutory_profile"),
        ({"pay_frequency": "Bi-Weekly"}, "nl_payroll_period"),
    ])
    def test_missing_input_blocks(self, override, key):
        with pytest.raises(NetherlandsCalculationBlockedError) as exc:
            _nl(**override)
        assert exc.value.key == key

    def test_missing_premium_rate_blocks(self):
        rates = dict(RATES)
        rates.pop("nl_awf_low_pct")
        with pytest.raises(NetherlandsCalculationBlockedError, match="nl_awf_low_pct"):
            _nl(rate_map=rates)

    def test_missing_zvw_path_blocks(self):
        profile = SimpleNamespace(**{**vars(PROFILE), "nl_zvw_path": None})
        with pytest.raises(NetherlandsCalculationBlockedError, match="Zvw path"):
            _nl(nl_statutory_profile=profile)

    def test_missing_period_max_blocks(self):
        with pytest.raises(NetherlandsCalculationBlockedError, match="NL_PERIOD_MAX"):
            _nl(pay_frequency="Weekly")

    def test_no_instruction_means_no_credit(self):
        nl = _nl(nl_with_tax_credit=None)["nl_result"]
        assert nl["wageTax"]["total"] == "1900.00"
        assert any(e["code"] == "NO_TAX_CREDIT_INSTRUCTION" for e in nl["exceptions"])

    def test_anonymous_rate_is_statutory_not_zero(self):
        out = _nl(nl_anonymous=True)
        assert out["tds"] == Decimal("2600.00")
        assert any(e["code"] == "ANONYMOUS_RATE" for e in out["nl_result"]["exceptions"])


class TestZvwEmployeePath:
    def test_employee_contribution_reduces_net(self):
        profile = SimpleNamespace(**{**vars(PROFILE), "nl_zvw_path": "EMPLOYEE_CONTRIB"})
        out = _nl(nl_statutory_profile=profile)
        assert out["nl_employee_total"] == Decimal("242.50")  # 4.85% of 5000
        assert out["nl_result"]["zvw"]["employerLevy"] == "0.00"
        assert "ZVW_CONTRIB" in out["nl_result"]["vcr"]["after"]


class TestFrozenInputs:
    def test_inputs_are_json_safe_and_hashed(self):
        import json
        nl = _nl()["nl_result"]
        json.dumps(nl)
        assert nl["inputs"]["wageTaxTable"]["fileId"] == 1
        assert len(nl["inputHash"]) == 64


def test_period_normalisation():
    assert normalise_period("Monthly") == ("MONTHLY", 12, "MONTHLY")
    assert normalise_period("4-weekly") == ("FOUR_WEEKLY", 13, "FOUR_WEEK")
    with pytest.raises(NetherlandsCalculationBlockedError):
        normalise_period("Semi-Monthly")
