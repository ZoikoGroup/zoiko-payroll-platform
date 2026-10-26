"""South Africa engine (ZP-ZA-ENG-001 Phase 3) — the rules the golden vectors
cannot express as single result fields: F4's PAYE inclusion, independent bases,
ETI never touching the employee, the dispatch / simple-mode boundary, the
tax-year and age helpers and a JSON-safe trace. "ZA" is South Africa."""
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.payroll.engine.countries import south_africa as za
from app.modules.payroll.engine.countries import south_africa_content as content
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError, _VALIDATION_ENABLED_COUNTRIES
from app.modules.payroll.hmrc_golden_harness import build_context

F1 = Path(__file__).resolve().parent / "fixtures" / "za_golden" / "f1_monthly_salary_age_40.json"


def _f1_context(**overrides):
    case = json.loads(F1.read_text(encoding="utf-8"))["context"]
    case.update(overrides)
    return build_context(case)


def _classes():
    return za._classes(_f1_context().slabs)


# ── F4: fixed travel allowance PAYE inclusion (ZA-008) ──────────────────────
@pytest.mark.parametrize("pct, included", [(Decimal("80"), Decimal("4000")), (Decimal("20"), Decimal("1000"))])
def test_f4_travel_allowance_enters_paye_at_the_configured_share(pct, included):
    pack = za._Pack({}, None)
    out = za.obligation_base("PAYE", [("TRAVEL_FIXED", Decimal("5000"))], _classes(), pack, travel_pct=pct)
    assert out["base"] == included


def test_travel_rule_is_paye_only():
    pack = za._Pack({}, None)
    classes = dict(_classes())
    classes[("UIF", "TRAVEL_FIXED")] = "TRAVEL_RULE"
    with pytest.raises(za.ZACalculationBlockedError) as exc:
        za.obligation_base("UIF", [("TRAVEL_FIXED", Decimal("5000"))], classes, pack)
    assert exc.value.key == "za_earning_class:UIF:TRAVEL_FIXED"


def test_business_use_flag_selects_the_twenty_percent_inclusion():
    ctx = _f1_context(basic="20000", gross="25000", za_components={"TRAVEL_FIXED": "5000"},
                      za_statutory_profile={**_f1_context().za_statutory_profile.__dict__,
                                            "za_travel_business_use_80": True})
    pack = za._Pack(ctx.rate_map, None)
    components = za.pay_components(ctx, pack)
    pct = pack.require_pct("za_travel_inclusion_business_pct", "employee")
    assert za.obligation_base("PAYE", components, za._classes(ctx.slabs), pack, travel_pct=pct)["base"] == \
        Decimal("21000")


# ── independent bases and component checks (spec §4) ────────────────────────
def test_components_exceeding_gross_block():
    ctx = _f1_context(za_components={"BONUS": "60000"})
    with pytest.raises(za.ZACalculationBlockedError) as exc:
        za.calculate(ctx)
    assert exc.value.key == "za_components"


def test_unknown_component_blocks():
    ctx = _f1_context(gross="51000", za_components={"SHARE_OPTIONS": "1000"})
    with pytest.raises(za.ZACalculationBlockedError) as exc:
        za.calculate(ctx)
    assert exc.value.key == "za_components"


def test_unclassified_other_earnings_block_paye_first():
    # gross above basic with no named component -> OTHER_EARNINGS, REVIEW for PAYE
    ctx = _f1_context(gross="52000")
    with pytest.raises(za.ZACalculationBlockedError) as exc:
        za.calculate(ctx)
    assert exc.value.key == "za_earning_class:PAYE:OTHER_EARNINGS"


# ── section 7B timing is derived from structured earned periods (ZA-006) ────
def _variable_context(earned_from, earned_to, amount="10000", item_amount=None):
    return _f1_context(
        gross="60000", basic="50000", za_components={"BONUS": "10000"},
        period_start="2026-09-01", period_end="2026-09-30",
        za_variable_items=[{"component": "BONUS", "amount": item_amount or amount,
                            "earned_from": earned_from, "earned_to": earned_to}],
    )


def test_section_7b_same_period_is_derived_not_claimed():
    ctx = _variable_context("2026-09-01", "2026-09-30")
    pack = za._Pack(ctx.rate_map, None)
    components = za.pay_components(ctx, pack)
    out = za.check_variable_remuneration(ctx, components, pack)
    assert out["samePeriod"] is True
    assert out["items"][0]["earnedFrom"] == "2026-09-01"
    assert out["items"][0]["earnedTo"] == "2026-09-30"


def test_section_7b_outside_period_blocks_while_the_basis_is_pending():
    ctx = _variable_context("2026-08-01", "2026-08-31")
    with pytest.raises(za.ZACalculationBlockedError) as exc:
        za.calculate(ctx)
    assert exc.value.key == "za_variable_remuneration_basis"


def test_section_7b_item_without_an_earned_period_blocks():
    ctx = _f1_context(gross="60000", basic="50000", za_components={"BONUS": "10000"},
                      period_start="2026-09-01", period_end="2026-09-30",
                      za_variable_items=[{"component": "BONUS", "amount": "10000"}])
    with pytest.raises(za.ZACalculationBlockedError) as exc:
        za.calculate(ctx)
    assert exc.value.key == "za_variable_remuneration_basis"


def test_section_7b_items_must_account_for_the_paid_component():
    ctx = _variable_context("2026-09-01", "2026-09-30", item_amount="9000")
    with pytest.raises(za.ZACalculationBlockedError) as exc:
        za.calculate(ctx)
    assert exc.value.key == "za_variable_remuneration_basis"


# ── ETI and employer-only levies never reach the employee (ZA-010) ──────────
def _eti_slabs():
    from types import SimpleNamespace

    return [SimpleNamespace(rule_type=content.ZA_ETI_BAND_RULE, filing_status=period,
                            tax_regime=formula, min_amount=lo, max_amount=hi,
                            rate_pct=rate, flat_amount=flat)
            for period, formula, lo, hi, rate, flat, _l, _s in content.ZA_ETI_BANDS]


def _eti_context(**overrides):
    base = _f1_context()
    registration = {**base.za_employer_registration.__dict__, "eti_registered": True}
    profile = {**base.za_statutory_profile.__dict__, "za_eti_eligible": True}
    case = {
        "date_of_birth": "2000-01-01", "date_of_joining": "2026-01-15",
        "za_eti_paid_hours": "160", "za_eti_qualifying_month_no": 1,
        "za_statutory_profile": profile,
        "za_employer_registration": registration,
    }
    case.update(overrides)
    ctx = _f1_context(**case)
    ctx.slabs = list(ctx.slabs) + _eti_slabs()
    return ctx


def test_eti_is_not_an_employee_line_and_sdl_is_employer_only():
    ctx = _f1_context(za_statutory_profile={**_f1_context().za_statutory_profile.__dict__, "za_eti_eligible": True})
    out = za.calculate(ctx)
    assert out["za_result"]["trace"]["eti"]["status"] == "NOT_REGISTERED"
    assert out["za_result"]["za_eti_amount"] == "0.00"
    employee_keys = {"tds", "employee_esi", "employee_pension"}
    assert out["employer_payroll_tax"] == Decimal("500.00")
    assert Decimal(out["za_result"]["za_employee_total"]) == sum(out[k] for k in employee_keys)


def test_eti_eligible_r5000_incentive_is_r1500_and_pay_is_unchanged():
    ctx = _eti_context(gross="5000", basic="5000")
    out = za.calculate(ctx)
    assert out["za_result"]["za_eti_amount"] == "1500.00"
    assert out["za_result"]["trace"]["eti"]["status"] == "ELIGIBLE"
    assert out["tds"] == Decimal("0.00")
    assert out["employee_esi"] == Decimal("50.00")
    assert Decimal(out["za_result"]["za_employee_total"]) == out["tds"] + out["employee_esi"]


def test_eti_broken_configuration_never_stops_the_employee_pay():
    # ETI-registered and eligible, but the hours fact is missing -> ETI BLOCKED,
    # while PAYE / UIF / SDL still calculate (the incentive is not employee pay).
    ctx = _eti_context(za_eti_paid_hours=None)
    out = za.calculate(ctx)
    assert out["za_result"]["trace"]["eti"]["status"] == "BLOCKED"
    assert out["za_result"]["za_eti_amount"] == "0.00"
    assert out["tds"] == Decimal("11075.58")


# ── tax directives (ZA-007) ─────────────────────────────────────────────────
def _directive(**overrides):
    row = {"id": 1, "directive_number": "D-2026-001", "directive_type": "FIXED_PERCENTAGE",
           "rate_pct": "25", "amount": None, "status": "APPROVED", "employee_id": 7,
           "tax_year": "2027", "effective_from": "2026-03-01", "effective_to": "2027-02-28"}
    row.update(overrides)
    return row


def test_approved_fixed_percentage_directive_replaces_paye_and_trace_records_both():
    ctx = _f1_context(za_employee_id=7, za_directives=[_directive()])
    out = za.calculate(ctx)
    assert out["tds"] == Decimal("12500.00")
    assert out["za_result"]["za_paye"] == "12500.00"
    assert out["za_result"]["za_paye_computed"] == "11075.58"
    directive_trace = out["za_result"]["trace"]["directive"]
    assert directive_trace["computedPaye"] == "11075.58"
    assert directive_trace["paye"] == "12500.00"
    assert directive_trace["applied"]["type"] == "FIXED_PERCENTAGE"


def test_directive_survives_the_json_trace():
    ctx = _f1_context(za_employee_id=7, za_directives=[_directive()])
    trace = json.loads(json.dumps(za.calculate(ctx)["za_result"]["trace"]))
    assert trace["directive"]["applied"]["directiveNumber"] == "D-2026-001"


def test_trace_is_json_safe_and_explains_every_step():
    out = za.calculate(_f1_context())
    trace = json.loads(json.dumps(out["za_result"]["trace"]))
    paye = trace["paye"]
    assert paye["method"] == "ANNUALISED_MONTHLY"
    assert Decimal(paye["annualTaxable"]) == Decimal("600000")
    assert Decimal(paye["annualTaxBeforeRebates"]) == Decimal("150727")
    assert paye["ageAtTaxYearEnd"] == 40
    assert set(trace["bases"]) == {"PAYE", "UIF", "SDL"}
    assert trace["uif"]["ceilingApplied"] is True and trace["taxYearEnd"] == "2027-02-28"


def test_medical_credit_never_makes_paye_negative():
    ctx = _f1_context(gross="7000", basic="7000",
                      za_statutory_profile={**_f1_context().za_statutory_profile.__dict__,
                                            "za_medical_scheme_member": True, "za_medical_dependants": 2})
    out = za.calculate(ctx)
    assert out["tds"] == Decimal("0.00")
    assert out["za_result"]["trace"]["paye"]["medicalCreditApplied"] == "0.00"


def test_dependants_without_membership_block():
    ctx = _f1_context(za_statutory_profile={**_f1_context().za_statutory_profile.__dict__,
                                            "za_medical_dependants": 2})
    with pytest.raises(za.ZACalculationBlockedError) as exc:
        za.calculate(ctx)
    assert exc.value.key == "za_medical_dependants"


# ── dates (ZA-006) ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("on, end", [
    (date(2026, 3, 1), date(2027, 2, 28)), (date(2027, 2, 28), date(2027, 2, 28)),
    (date(2027, 3, 1), date(2028, 2, 29)), (date(2026, 2, 28), date(2026, 2, 28)),
])
def test_tax_year_end(on, end):
    assert za.tax_year_end(on) == end


def test_age_65_reached_on_the_last_day_of_the_tax_year_earns_the_secondary_rebate():
    born = date(1962, 2, 28)
    assert za.age_on(born, date(2027, 2, 28)) == 65
    assert za.age_on(date(1962, 3, 1), date(2027, 2, 28)) == 64


def test_signed_payment_date_basis_resolves_a_cross_year_payment():
    ctx = _f1_context(pay_date="2027-03-01", period_end="2027-02-28")
    ctx.rate_map["za_paye_tax_year_date_basis"].text_value = "PAYMENT_DATE"
    out = za.calculate(ctx)
    assert out["za_result"]["trace"]["taxYearEnd"] == "2028-02-29"


# ── platform wiring ─────────────────────────────────────────────────────────
def test_dispatch_and_fail_closed_registration():
    from app.modules.payroll.engine import standard

    assert standard._COUNTRY_CALC["ZA"] is za.calculate
    assert "ZA" in _VALIDATION_ENABLED_COUNTRIES
    assert issubclass(za.ZACalculationBlockedError, MissingComplianceConfigurationError)
    assert za.ZA_PARAMETER_KEYS is content.ZA_PARAMETER_KEYS


def test_simple_mode_is_refused():
    from app.modules.payroll.engine.resolver import calculate_payroll

    with pytest.raises(za.ZACalculationBlockedError) as exc:
        calculate_payroll(_f1_context(), "simple")
    assert exc.value.key == "ZA_SIMPLE_MODE_UNSUPPORTED"


def test_standard_strategy_carries_the_za_result():
    from app.modules.payroll.engine.resolver import calculate_payroll

    result = calculate_payroll(_f1_context(), "standard")
    assert result.za_result["za_paye"] == "11075.58"
    assert result.sa_result is None
