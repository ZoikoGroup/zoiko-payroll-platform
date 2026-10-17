"""Mexico engine (Phase 5) — the orchestrator (countries/mexico.py): an
end-to-end SYNTHETIC payslip → generic keys + mx_result with the MX-063
trace; preflight lists every reason at once; the standard.py dispatch sums
mx_employee_total; no server clock; non-MX contexts untouched."""

import copy
import inspect
from dataclasses import replace
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from tests import _mx_engine_helpers as h


def _calc(**over):
    from app.modules.payroll.engine.countries import mexico

    return mexico.calculate(h.ctx(**over))


def _block(**over):
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    with pytest.raises(MXBlock) as exc:
        _calc(**over)
    return exc.value


def test_end_to_end_result_and_generic_keys():
    out = _calc()
    r = out["mx_result"]
    assert out["tds"] == D(r["isr_withheld"]) == D("450.00")       # synthetic bracket 8: 360 + 999.99 × 9 %
    assert out["mx_employee_total"] == D(r["imss_employee"]) + D(r["infonavit_credit"])
    assert D(r["employer_total"]) == D(r["imss_employer"]) + D(r["infonavit_employer"]) + D(r["isn"]["amount"])
    assert D(r["imss_employee"]) == sum(D(b["amount"]) for b in r["imss"] if b["side"] == "employee")


def test_trace_carries_the_mx063_fields():
    r = _calc()["mx_result"]
    for key in ("engine_version", "pay_date", "tariff_period", "days_paid", "contribution_days", "isr_bracket",
                "subsidy", "sbc", "imss", "risk_premium_pct", "infonavit_employer_lines", "infonavit_credit_lines",
                "isn", "labor", "entitlements", "concepts", "rounding_rule", "content_rows", "pack"):
        assert key in r, key
    assert r["pay_date"] == "2026-06-15" and r["pack"]["pack_id"] == "MX-PAYROLL-2026"
    branches = {(b["branch"], b["side"]) for b in r["imss"]}
    assert ("CEAV", "employer") in branches and ("RIESGOS_TRABAJO", "employer") in branches
    ceav = next(b for b in r["imss"] if b["branch"] == "CEAV" and b["side"] == "employer")
    assert ceav["lines"][0]["band"] == "2.01UMA"
    assert r["concepts"][0]["classification_id"] == 1 and r["concepts"][0]["classification_version"] == 1
    assert {"factor", "fixed", "variable_daily", "aguinaldo_days", "vacation_days"} <= set(r["sbc"]["components"])
    keys = {row["key"] for row in r["content_rows"]}
    assert {"mx_uma_daily", "mx_imss_iv_er_pct", "MX_ISR_TARIFF:QUINCENAL_15", "mx_isn_rate_pct"} <= keys
    assert r["isn"]["pack_id"] == "MX-ISN-CDMX-2026"
    assert "content" not in r["sbc"]["segments"][0]


def test_emitted_amounts_use_the_rounding_quantum():
    out = _calc()
    r = out["mx_result"]
    for value in (out["tds"], out["mx_employee_total"], D(r["imss_employer"]), D(r["isn"]["amount"])):
        assert value == value.quantize(D("0.01"))
    rates = copy.deepcopy(h.SYN_RATES)
    rates["mx_rounding_rule"] = h.txt("DOWN:1")
    whole = _calc(rates=rates)
    assert whole["mx_employee_total"] == whole["mx_employee_total"].quantize(D("1"))


def test_missing_rounding_rule_emits_nothing():
    e = _block(rates=h.without("mx_rounding_rule"))
    assert e.key == "MX_PREFLIGHT_BLOCKED" and ("MX_ROUNDING_RULE_MISSING" in [k for k, _ in e.reasons])


def test_preflight_lists_every_reason_at_once():
    e = _block(rates=h.without("mx_rounding_rule"), mx_payment_period="CATORCENAL_14", mx_profile=None,
               mx_registration=None, mx_risk_premium=None, mx_labor_policy=None, mx_min_wage_zone="UNRESOLVED",
               mx_isn_state_pack=None,
               mx_earnings=[{"code": "SALARY", "kind": "ORDINARY_SALARY", "amount": D("9000")},
                            {"code": "NEW", "kind": "OTHER", "amount": D("0")}])
    codes = {k for k, _ in e.reasons}
    assert {"MX_ROUNDING_RULE_MISSING", "MX_PERIOD_UNSUPPORTED", "MX_PROFILE_MISSING", "MX_NO_REGISTRATION",
            "MX_NO_RISK_PREMIUM", "MX_LABOR_POLICY_MISSING", "MX_MIN_WAGE_ZONE_UNRESOLVED",
            "MX_STATE_UNSUPPORTED", "MX_CLASSIFICATION_MISSING"} <= codes
    assert e.organization_id == 11 and all(k in str(e) for k in ("MX_PROFILE_MISSING", "MX_NO_REGISTRATION"))


def test_identifier_mismatch_and_missing_salary_facts():
    profile = dict(h.facts()["mx_profile"], mx_identifier_validation_status="MISMATCH", mx_daily_salary=None,
                   mx_seniority_date=None)
    codes = {k for k, _ in _block(mx_profile=profile).reasons}
    assert {"MX_IDENTIFIER_MISMATCH", "MX_DAILY_SALARY_MISSING", "MX_SENIORITY_DATE_MISSING"} <= codes


def test_no_salary_line_blocks():
    codes = {k for k, _ in _block(mx_earnings=[], gross=D("0")).reasons}
    assert "MX_SALARY_LINE_MISSING" in codes


@pytest.mark.parametrize("kind", ["AGUINALDO", "VACATION_PREMIUM", "PTU", "SEPARATION"])
def test_special_pays_block_until_phase9(kind):
    earnings = [{"code": "SALARY", "kind": "ORDINARY_SALARY", "amount": D("9000")},
                {"code": "X", "kind": kind, "amount": D("100")}]
    assert "MX_SPECIAL_PAY_PHASE9" in {k for k, _ in _block(mx_earnings=earnings).reasons}


@pytest.mark.parametrize("treatment", ["EXEMPT", "PARTIAL"])
def test_exempt_classification_blocks_without_exemption_content(treatment):
    cls = {"SALARY": h.classification(isr_treatment=treatment, isr_exempt_rule_key="ANY")}
    assert "MX_EXEMPTION_RULE_MISSING" in {k for k, _ in _block(mx_classifications=cls).reasons}


def test_classification_versions_by_pay_date():
    future = {"SALARY": h.classification(effective_from=date(2026, 7, 1))}
    assert "MX_CLASSIFICATION_NOT_IN_FORCE" in {k for k, _ in _block(mx_classifications=future).reasons}
    draft = {"SALARY": h.classification(status="DRAFT")}
    assert "MX_CLASSIFICATION_NOT_IN_FORCE" in {k for k, _ in _block(mx_classifications=draft).reasons}
    historical = {"SALARY": h.classification(status="SUPERSEDED", effective_to=date(2026, 6, 30))}
    assert _calc(mx_classifications=historical)["tds"] == _calc()["tds"]       # MX-006


def test_non_perception_lines_block():
    cls = {"SALARY": h.classification(cfdi_node_type="DEDUCCION")}
    assert "MX_CLASSIFICATION_UNSUPPORTED" in {k for k, _ in _block(mx_classifications=cls).reasons}


def test_gross_must_equal_the_classified_lines():
    assert _block(gross=D("9000.01")).key == "MX_GROSS_MISMATCH"


def test_infonavit_credit_is_an_employee_deduction():
    rates = copy.deepcopy(h.SYN_RATES)
    rates["mx_infonavit_percentage_basis"] = h.txt("SBC_TIMES_DAYS")
    notice = {"id": 1, "credit_number": "C1", "notice_type": "RETENCION", "discount_method": "PERCENTAGE",
              "discount_value": "10", "effective_from": date(2026, 1, 1), "effective_to": None, "status": "RECORDED"}
    with_credit = _calc(rates=rates, mx_infonavit_notices=[notice])
    without = _calc(rates=rates)
    assert with_credit["mx_employee_total"] > without["mx_employee_total"]
    assert with_credit["tds"] == without["tds"]


def test_results_depend_only_on_the_context_never_the_clock():
    """No module reads the server date (MX-004); the same context gives the
    same result, and the law follows the context's pay date."""
    from app.modules.payroll.engine.countries import mexico
    from app.modules.payroll.engine.jurisdictions import mexico as pkg

    sources = [inspect.getsource(mexico)] + [p.read_text(encoding="utf-8") for p in Path(pkg.__file__).parent.glob("*.py")]
    for src in sources:
        for needle in ("today(", ".now(", "utcnow(", "time.time("):
            assert needle not in src, needle
    assert _calc() == _calc()


def test_standard_dispatch_sums_the_mexican_deductions():
    from app.modules.payroll.engine.resolver import calculate_payroll

    ctx = h.ctx()
    res = calculate_payroll(ctx, "standard")
    direct = _calc()
    assert res.mx_result == direct["mx_result"]
    assert res.tds == direct["tds"]
    assert res.total_deductions >= direct["tds"] + direct["mx_employee_total"]


def test_other_countries_are_untouched():
    from app.modules.payroll.engine.countries import mexico

    us = replace(h.ctx(), country="US")
    assert mexico.calculate(us) == {}
