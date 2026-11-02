"""Synthetic Japan Phase 4 bonus-path tests (ZP-JP-ENG-001, S1/S8).

Every value here is invented for the test. None is a statutory figure: the
bonus-rate rows, the special-calculation multiple and the signed rounding
choices are test fixtures only.
"""
from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest

from app.modules.payroll.engine.countries import japan
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
from app.modules.payroll.engine.jurisdictions.japan import bonus as bonus_mod
from app.modules.payroll.engine.jurisdictions.japan import social_insurance
from app.modules.payroll.engine.standard import StandardStrategy
from tests.test_japan_engine import D, _base_rate_map, _context, _slabs

BONUS = D(500500)


def _bonus_row(column, dependants, low, high, rate, **kw):
    return SimpleNamespace(rule_type="JP_WHT_BONUS", tax_column=column, tax_table_number=dependants,
                           min_amount=D(low), max_amount=None if high is None else D(high),
                           rate_pct=D(rate), flat_amount=None, tax_regime=None, filing_status=None,
                           effective_from=kw.get("effective_from"), effective_to=kw.get("effective_to"))


def _bonus_slabs(ei="INCLUDED", si="BONUS_PATH", wht="BONUS_PATH", rows=None):
    slabs = _slabs()
    for row in slabs:
        if row.rule_type == "JP_EARNING_CLASS" and row.filing_status == "BONUS":
            row.assessment_basis = {"EI": ei, "SI": si, "WHT": wht}.get(row.tax_regime,
                                                                        row.assessment_basis)
    slabs.extend(rows if rows is not None else [
        _bonus_row("PRIMARY", "0", 0, 200000, "2.042"),
        _bonus_row("PRIMARY", "0", 200000, 400000, "4.084"),
        _bonus_row("SECONDARY", None, 0, None, "10.21"),
    ])
    return slabs


def _bonus_rate_map(multiple="10"):
    rate_map = _base_rate_map()
    rate_map["jp_wht_bonus_special_multiple"].flat_amount = None if multiple is None else D(multiple)
    return rate_map


def _ctx(**overrides):
    kwargs = dict(gross=D(300000) + BONUS, rate_map=_bonus_rate_map(), slabs=_bonus_slabs(),
                  jp_components={"BONUS": BONUS}, jp_prior_month_pay_after_si=D(256050),
                  jp_ytd_health_sba=D(0), jp_month_pension_sba=D(0))
    kwargs.update(overrides)
    return _context(**kwargs)


def _blocked(ctx):
    with pytest.raises(MissingComplianceConfigurationError) as exc:
        japan.calculate(ctx)
    return exc.value.key


# ── the bonus path ──────────────────────────────────────────────────────────
def test_salary_and_bonus_in_one_payment():
    result = japan.calculate(_ctx())
    jp = result["jp_result"]
    bonus = jp["jp_bonus"]

    # The monthly salary path is unchanged by the bonus.
    assert jp["jp_wht"] == "5000" and jp["jp_si_employee_total"] == "42450"
    assert jp["jp_ei_employee"] == "1500" and jp["jp_resident_tax"] == "10000"
    # SBA 500,000: EPI 18.3% / 2 and health 10% / 2 on it.
    assert bonus["jp_bonus_sba"] == "500000"
    assert bonus["jp_bonus_epi_employee"] == "45750" and bonus["jp_bonus_epi_employer"] == "45750"
    assert bonus["jp_bonus_health_employee"] == "25000"
    assert bonus["jp_bonus_si_employee_total"] == "70750"
    # EI on the bonus itself (0.5% of 500,500 = 2,502.5 truncated).
    assert bonus["jp_bonus_ei_employee"] == "2502" and bonus["jp_bonus_ei_employer"] == "4254"
    # The rate is applied to the bonus after its own SI / EI, not the prior pay.
    assert bonus["jp_bonus_wht_base"] == "427248"
    assert bonus["jp_bonus_wht_rate_pct"] == "4.084"
    assert bonus["jp_bonus_wht"] == "17448"
    assert bonus["jp_bonus_report_due"] == "2026-06-20"

    assert result["tds"] == D(5000 + 17448)
    assert jp["jp_wht_total"] == "22448"
    assert result["jp_employee_total"] == D(53950 + 70750 + 2502)
    assert jp["jp_employer_total"] == str(D(42450 + 2550) + D(70750) + D(4254))
    assert jp["trace"]["bonus"]["withholding"]["row"]["rule_type"] == "JP_WHT_BONUS"


def test_bonus_only_payment_skips_the_monthly_obligations():
    result = japan.calculate(_ctx(gross=BONUS, basic=D(0), jp_payment_kind="BONUS"))
    jp = result["jp_result"]
    assert jp["jp_payment_kind"] == "BONUS"
    assert (jp["jp_wht"], jp["jp_si_employee_total"], jp["jp_ei_employee"], jp["jp_resident_tax"]) == \
        ("0", "0", "0", "0")
    assert result["tds"] == D(17448)
    assert result["jp_employee_total"] == D(70750 + 2502)


def test_prior_month_pay_selects_the_band_and_is_never_taxed():
    jp = japan.calculate(_ctx(jp_prior_month_pay_after_si=D(150000)))["jp_result"]
    assert jp["jp_bonus"]["jp_bonus_wht_rate_pct"] == "2.042"
    assert jp["jp_bonus"]["jp_bonus_wht"] == "8724"            # 427,248 x 2.042%


def test_secondary_column_ignores_dependants():
    ctx = _ctx(jp_worker_tax_profile=SimpleNamespace(
        status="ACTIVE", effective_from=date(2026, 1, 1), residency_status="RESIDENT",
        declaration_class="SECONDARY", dependants_count=2))
    ctx.slabs.append(SimpleNamespace(
        rule_type="JP_WHT_MONTHLY", tax_column="SECONDARY", tax_table_number="2",
        min_amount=D(0), max_amount=D("100000000"), rate_pct=D(0), flat_amount=D(7000),
        tax_regime=None, filing_status=None))
    jp = japan.calculate(ctx)["jp_result"]
    assert jp["jp_bonus"]["jp_bonus_wht_rate_pct"] == "10.21"


def test_bonus_table_row_out_of_force_is_not_used():
    rows = [_bonus_row("PRIMARY", "0", 0, None, "4.084", effective_to=date(2025, 12, 31))]
    assert _blocked(_ctx(slabs=_bonus_slabs(rows=rows))) == "JP_WHT_BONUS"


@pytest.mark.parametrize("overrides,key", [
    ({"jp_prior_month_pay_after_si": None}, "jp_prior_month_pay_after_si"),
    ({"jp_prior_month_pay_after_si": D(0)}, "JP_WHT_BONUS_SPECIAL"),
    ({"jp_prior_month_pay_after_si": D(40000)}, "JP_WHT_BONUS_SPECIAL"),   # bonus > 10 x prior
    ({"rate_map": None, "_shipped_multiple": True}, "jp_wht_bonus_special_multiple"),
    ({"slabs": "no-rows"}, "JP_WHT_BONUS"),
    ({"jp_ytd_health_sba": None}, "jp_ytd_health_sba"),
    ({"jp_month_pension_sba": None}, "jp_month_pension_sba"),
    ({"jp_ytd_health_sba": D(-1)}, "jp_ytd_health_sba"),
])
def test_bonus_blocks_instead_of_guessing(overrides, key):
    overrides = dict(overrides)
    if overrides.pop("_shipped_multiple", False):
        overrides["rate_map"] = _bonus_rate_map(multiple=None)
    if overrides.get("slabs") == "no-rows":
        overrides["slabs"] = _bonus_slabs(rows=[])
    assert _blocked(_ctx(**overrides)) == key


def test_shipped_bonus_rounding_is_pending_and_blocks():
    rate_map = _bonus_rate_map()
    rate_map["jp_wht_rounding"].text_value = "PENDING_G1"
    assert _blocked(_ctx(rate_map=rate_map)) == "jp_wht_rounding"


# ── standard bonus amount and caps (S8) ────────────────────────────────────
def test_sba_truncates_below_the_signed_unit():
    pack = japan._Pack(_bonus_rate_map(), 7)
    assert social_insurance.standard_bonus_amount(D("500999"), pack) == D(500000)
    assert social_insurance.standard_bonus_amount(D("999"), pack) == D(0)


def test_sba_unit_and_rule_must_agree():
    rate_map = _bonus_rate_map()
    rate_map["jp_sba_rounding_unit"].flat_amount = D(500)
    with pytest.raises(MissingComplianceConfigurationError) as exc:
        social_insurance.standard_bonus_amount(D(500500), japan._Pack(rate_map, 7))
    assert exc.value.key == "jp_sba_rounding"


def test_health_sba_counts_against_the_annual_cap():
    bonus = japan.calculate(_ctx(jp_ytd_health_sba=D(5500000)))["jp_result"]["jp_bonus"]
    assert bonus["jp_bonus_health_sba_base"] == "230000"            # 5,730,000 - 5,500,000
    assert bonus["jp_bonus_health_employee"] == "11500"
    assert bonus["jp_bonus_pension_sba_base"] == "500000"           # pension cap is separate


def test_pension_sba_counts_against_the_monthly_cap():
    bonus = japan.calculate(_ctx(jp_month_pension_sba=D(1200000)))["jp_result"]["jp_bonus"]
    assert bonus["jp_bonus_pension_sba_base"] == "300000"           # 1,500,000 - 1,200,000
    assert bonus["jp_bonus_epi_employee"] == "27450"
    assert bonus["jp_bonus_health_sba_base"] == "500000"


def test_exhausted_caps_charge_nothing_but_still_report():
    bonus = japan.calculate(_ctx(jp_ytd_health_sba=D(5730000),
                                 jp_month_pension_sba=D(1500000)))["jp_result"]["jp_bonus"]
    assert bonus["jp_bonus_si_employee_total"] == "0"
    assert bonus["jp_bonus_sba"] == "500000"
    assert bonus["jp_bonus_report_due"] == "2026-06-20"


def test_care_insurance_is_charged_on_the_health_sba():
    ctx = _ctx(jp_date_of_birth=date(1980, 1, 1))
    ctx.jp_social_insurance_enrollment.care_state = "COVERED"
    bonus = japan.calculate(ctx)["jp_result"]["jp_bonus"]
    assert bonus["jp_bonus_care_employee"] == "4050"                # 1.62% / 2 of 500,000


# ── classification and payment kind ────────────────────────────────────────
def test_excluded_employment_insurance_charges_no_bonus_ei():
    bonus = japan.calculate(_ctx(slabs=_bonus_slabs(ei="EXCLUDED")))["jp_result"]["jp_bonus"]
    assert bonus["jp_bonus_ei_employee"] == "0"
    assert bonus["jp_bonus_wht_base"] == "429750"


@pytest.mark.parametrize("kwargs,key", [
    ({"si": "INCLUDED"}, "jp_earning_class:SI:BONUS"),
    ({"wht": "EXCLUDED"}, "jp_earning_class:WHT:BONUS"),
    ({"ei": "BONUS_PATH"}, "jp_earning_class:EI:BONUS"),
])
def test_unsupported_bonus_treatments_block(kwargs, key):
    assert _blocked(_ctx(slabs=_bonus_slabs(**kwargs))) == key


def test_only_bonus_may_use_the_bonus_path():
    slabs = _bonus_slabs()
    for row in slabs:
        if row.rule_type == "JP_EARNING_CLASS" and row.tax_regime == "WHT" and row.filing_status == "ALLOWANCE":
            row.assessment_basis = "BONUS_PATH"
    ctx = _ctx(slabs=slabs, gross=D(310000) + BONUS,
               jp_components={"BONUS": BONUS, "ALLOWANCE": D(10000)})
    assert _blocked(ctx) == "jp_earning_class:WHT:ALLOWANCE"


@pytest.mark.parametrize("overrides", [
    {"jp_payment_kind": "BONUS"},                                   # salary in a bonus payment
    {"jp_payment_kind": "BONUS", "gross": D(0), "basic": D(0), "jp_components": {}},
    {"jp_payment_kind": "RETRO"},
])
def test_payment_kind_is_checked(overrides):
    assert _blocked(_ctx(**overrides)) == "jp_payment_kind"


def test_uninsured_employee_has_no_bonus_report():
    ctx = _ctx()
    ctx.jp_social_insurance_enrollment.health_eligible = False
    ctx.jp_social_insurance_enrollment.pension_eligible = False
    bonus = japan.calculate(ctx)["jp_result"]["jp_bonus"]
    assert bonus["jp_bonus_report_due"] is None
    assert bonus["jp_bonus_si_employee_total"] == "0"


# ── exemptions block (month rules not certified) ───────────────────────────
def test_exemption_event_in_the_pay_month_blocks():
    event = SimpleNamespace(event_type="CHILDCARE_EXEMPTION", submission_status="APPROVED",
                            effective_from=date(2026, 5, 1), effective_to=date(2026, 6, 3))
    assert _blocked(_context(jp_social_insurance_events=[event])) == "JP_SI_EXEMPTION_PENDING"


def test_rejected_or_earlier_exemptions_do_not_block():
    events = [
        SimpleNamespace(event_type="MATERNITY_EXEMPTION", submission_status="REJECTED",
                        effective_from=date(2026, 6, 1), effective_to=None),
        SimpleNamespace(event_type="CHILDCARE_EXEMPTION", submission_status="APPROVED",
                        effective_from=date(2026, 4, 1), effective_to=date(2026, 5, 31)),
    ]
    assert japan.calculate(_context(jp_social_insurance_events=events))["tds"] == D(5000)


# ── wiring, determinism, report due ────────────────────────────────────────
def test_standard_strategy_totals_include_the_bonus():
    result = StandardStrategy().calculate(_ctx())
    assert result.tds == D(22448)
    assert result.total_deductions == D(22448) + D(53950 + 70750 + 2502)
    assert result.net_pay == D(300000) + BONUS - result.total_deductions


def test_bonus_result_is_deterministic_and_json_serialisable():
    ctx = _ctx()
    first, second = japan.calculate(ctx), japan.calculate(ctx)
    assert first == second
    json.dumps(first["jp_result"], sort_keys=True)


def test_salary_only_result_has_no_bonus_section():
    jp = japan.calculate(_context())["jp_result"]
    assert jp["jp_bonus"] is None and jp["trace"]["bonus"] is None
    assert jp["jp_wht_total"] == jp["jp_wht"] == "5000"


def test_bonus_report_due_uses_the_content_days():
    rate_map = _bonus_rate_map()
    assert bonus_mod.bonus_report_due(date(2026, 12, 29), japan._Pack(rate_map, 7)) == date(2027, 1, 3)
    rate_map["jp_bonus_report_days"].flat_amount = D("2.5")
    with pytest.raises(MissingComplianceConfigurationError) as exc:
        bonus_mod.bonus_report_due(date(2026, 12, 29), japan._Pack(rate_map, 7))
    assert exc.value.key == "jp_bonus_report_days"
