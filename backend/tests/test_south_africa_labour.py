"""South Africa labour controls, non-statutory deductions and approved overrides
(ZP-ZA-ENG-001 §5, ZA-012, ZA-013; Phase 9). "ZA" is South Africa.

The pure module (engine/jurisdictions/south_africa/labour.py) first, then the
same rules through countries/south_africa.calculate() and standard.py's net."""
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.modules.payroll.engine.countries import south_africa as za
from app.modules.payroll.engine.countries import south_africa_content as content
from app.modules.payroll.engine.jurisdictions.south_africa import labour
from app.modules.payroll.hmrc_golden_harness import build_context

F1 = Path(__file__).resolve().parent / "fixtures" / "za_golden" / "f1_monthly_salary_age_40.json"


def _rows(**values):
    """rate_map rows: key -> SimpleNamespace(flat_amount / employee_rate_pct / text_value)."""
    out = {}
    for key, value in values.items():
        kind = content.ZA_PARAMETER_KEYS[key]
        attr = {"amount": "flat_amount", "employee_pct": "employee_rate_pct", "text": "text_value"}[kind]
        out[key] = SimpleNamespace(**{attr: value})
    return out


BASE = dict(za_nmw_hourly="30.23", za_bcea_earnings_threshold="261748.43",
            za_deduction_authority_types="STATUTORY,COURT_ORDER,CONSENT,COLLECTIVE")


def _codes(result):
    return {f["code"] for f in result["findings"]}


# ── validate_za_labour ──────────────────────────────────────────────────────
def test_no_time_record_is_a_warning_not_a_block():
    out = labour.validate_za_labour(hours=None, ordinary_pay="8000", annual_remuneration="96000",
                                    overtime_paid="0", rate_map=_rows(**BASE))
    assert out["status"] == labour.WARN
    assert _codes(out) == {"ZA_NMW_NOT_VERIFIABLE"}


def test_missing_minimum_wage_row_blocks():
    rows = _rows(**{k: v for k, v in BASE.items() if k != "za_nmw_hourly"})
    out = labour.validate_za_labour(hours=None, ordinary_pay="8000", annual_remuneration="96000",
                                    overtime_paid="0", rate_map=rows)
    assert out["status"] == labour.BLOCK and "ZA_NMW_NOT_CONFIGURED" in _codes(out)


def test_below_minimum_wage_blocks():
    out = labour.validate_za_labour(hours={"ordinary": "195"}, ordinary_pay="5000",
                                    annual_remuneration="60000", overtime_paid="0", rate_map=_rows(**BASE))
    assert out["hourly"] == "25.64"
    assert out["status"] == labour.BLOCK and "ZA_BELOW_NMW" in _codes(out)


def test_at_or_above_minimum_wage_passes():
    out = labour.validate_za_labour(hours={"ordinary": "195"}, ordinary_pay="6000",
                                    annual_remuneration="72000", overtime_paid="0", rate_map=_rows(**BASE))
    assert out["status"] == labour.OK and out["hourly"] == "30.77"


def test_premium_multiplier_left_empty_by_design_is_a_warning():
    # The spec does not state the BCEA multipliers; the content row is empty.
    out = labour.validate_za_labour(hours={"ordinary": "195", "overtime": "10"}, ordinary_pay="6000",
                                    annual_remuneration="72000", overtime_paid="0", rate_map=_rows(**BASE))
    assert out["bcea"]["applicable"] is True
    assert out["bcea"]["premiums"] == {"overtime": "NOT_CONFIGURED"}
    assert out["status"] == labour.WARN and "ZA_BCEA_PREMIUM_NOT_CONFIGURED" in _codes(out)


def test_configured_overtime_multiplier_is_enforced():
    rows = _rows(**BASE, za_bcea_overtime_multiplier="1.5")
    hours = {"ordinary": "195", "overtime": "10"}
    under = labour.validate_za_labour(hours=hours, ordinary_pay="6000", annual_remuneration="72000",
                                      overtime_paid="400", rate_map=rows)
    assert under["bcea"]["premiums"]["overtime"] == "461.55"
    assert "ZA_BCEA_PREMIUM_UNDERPAID" in _codes(under)
    paid = labour.validate_za_labour(hours=hours, ordinary_pay="6000", annual_remuneration="72000",
                                     overtime_paid="461.55", rate_map=rows)
    assert paid["status"] == labour.OK


def test_bcea_premiums_do_not_apply_above_the_threshold():
    out = labour.validate_za_labour(hours={"ordinary": "195", "overtime": "10"}, ordinary_pay="30000",
                                    annual_remuneration="360000", overtime_paid="0", rate_map=_rows(**BASE))
    assert out["bcea"]["applicable"] is False and out["status"] == labour.OK


def test_premium_hours_without_a_threshold_row_block():
    rows = _rows(za_nmw_hourly="30.23")
    out = labour.validate_za_labour(hours={"ordinary": "195", "sunday": "8"}, ordinary_pay="6000",
                                    annual_remuneration="72000", overtime_paid="0", rate_map=rows)
    assert "ZA_BCEA_THRESHOLD_UNKNOWN" in _codes(out) and out["status"] == labour.BLOCK


# ── evaluate_za_deductions (ZA-013) ─────────────────────────────────────────
def _order(**kw):
    return {"id": 1, "order_type": "GARNISHEE", "authority_type": "COURT_ORDER", "amount": "500",
            "evidence_ref": "EMOLUMENTS-ATTACHMENT-1", **kw}


def test_authorised_evidenced_order_is_deducted():
    out = labour.evaluate_za_deductions([_order()], "10000", _rows(**BASE))
    assert out["status"] == labour.OK and out["total"] == Decimal("500")
    assert out["lines"] == [{"id": 1, "orderType": "GARNISHEE", "authorityType": "COURT_ORDER",
                             "amount": "500"}]


@pytest.mark.parametrize("order, code", [
    (_order(authority_type="MANAGER"), "ZA_DEDUCTION_UNAUTHORISED"),
    (_order(authority_type=None), "ZA_DEDUCTION_UNAUTHORISED"),
    (_order(evidence_ref=""), "ZA_DEDUCTION_NO_EVIDENCE"),
    (_order(order_type="DAMAGE", authority_type="CONSENT"), "ZA_DAMAGE_LIMIT_NOT_CONFIGURED"),
    (_order(amount="20000"), "ZA_DEDUCTIONS_EXCEED_NET"),
])
def test_deduction_defects_block(order, code):
    out = labour.evaluate_za_deductions([order], "10000", _rows(**BASE))
    assert out["status"] == labour.BLOCK and code in _codes(out)


def test_damage_limit_once_configured():
    rows = _rows(**BASE, za_damage_deduction_limit_pct="25")
    ok = labour.evaluate_za_deductions([_order(order_type="LOSS", amount="2500")], "10000", rows)
    assert ok["status"] == labour.OK
    over = labour.evaluate_za_deductions([_order(order_type="LOSS", amount="2500.01")], "10000", rows)
    assert "ZA_DAMAGE_LIMIT_EXCEEDED" in _codes(over)


def test_no_authority_list_blocks_every_order():
    out = labour.evaluate_za_deductions([_order()], "10000", _rows(za_nmw_hourly="30.23"))
    assert "ZA_DEDUCTION_AUTHORITIES_NOT_CONFIGURED" in _codes(out)


def test_zero_amount_orders_are_ignored():
    out = labour.evaluate_za_deductions([_order(amount="0", evidence_ref="")], "10000", _rows(**BASE))
    assert out == {"status": labour.OK, "total": Decimal("0"), "lines": [], "findings": []}


def test_content_authority_row_matches_the_damage_types():
    assert set(labour.DAMAGE_TYPES) == set(content.DEDUCTION_TYPES_NEEDING_LIMIT)


# ── through the engine ──────────────────────────────────────────────────────
def _case(**overrides):
    case = json.loads(F1.read_text(encoding="utf-8"))["context"]
    case["rate_map"] = {**case["rate_map"],
                        "za_deduction_authority_types": {"text_value": BASE["za_deduction_authority_types"]}}
    case.update(overrides)
    return case


def _calc(**overrides):
    return za.calculate(build_context(_case(**overrides)))


def test_engine_deducts_validated_orders_from_net_only():
    plain = _calc()
    out = _calc(za_deduction_orders=[_order()])
    assert out["za_other_deductions_total"] == Decimal("500")
    assert out["za_result"]["za_other_deductions"] == "500"
    # statutory figures untouched; not part of the statutory employee total
    assert out["tds"] == plain["tds"] and out["employee_esi"] == plain["employee_esi"]
    assert out["za_result"]["za_employee_total"] == plain["za_result"]["za_employee_total"]


def test_engine_blocks_an_unauthorised_order():
    with pytest.raises(za.ZACalculationBlockedError) as exc:
        _calc(za_deduction_orders=[_order(authority_type="MANAGER")])
    assert exc.value.key == "za_deductions"


def test_engine_blocks_below_minimum_wage():
    with pytest.raises(za.ZACalculationBlockedError) as exc:
        _calc(za_hours={"ordinary": "2000"})
    assert exc.value.key == "za_labour"


def test_engine_records_labour_trace_without_hours():
    out = _calc()
    assert out["za_result"]["za_labour_status"] == labour.WARN
    trace = out["za_result"]["trace"]
    assert trace["labour"]["findings"][0]["code"] == "ZA_NMW_NOT_VERIFIABLE"
    assert trace["overrides"] == [] and trace["otherDeductionsTotal"] == "0"
    json.dumps(trace)


def test_engine_net_pay_subtracts_other_deductions():
    from app.modules.payroll.engine.resolver import calculate_payroll
    plain = calculate_payroll(build_context(_case()))
    out = calculate_payroll(build_context(_case(za_deduction_orders=[_order()])))
    assert plain.net_pay - out.net_pay == Decimal("500")


# ── approved overrides (applied last; stale approvals block) ────────────────
def _override(field, computed, amount, **kw):
    return {"id": 9, "field": field, "before": str(computed), "after": str(amount),
            "reason_code": "SARS_CORRESPONDENCE", **kw}


def test_override_replaces_the_computed_figure():
    plain = _calc()
    out = _calc(za_overrides=[_override("za_paye", plain["tds"], "9000")])
    assert out["tds"] == Decimal("9000")
    assert out["za_result"]["za_overrides_applied"] == 1
    assert out["za_result"]["trace"]["overrides"][0]["before"] == str(plain["tds"])
    assert out["za_result"]["za_employee_total"] != plain["za_result"]["za_employee_total"]


def test_stale_override_blocks():
    with pytest.raises(za.ZACalculationBlockedError) as exc:
        _calc(za_overrides=[_override("za_paye", "1.00", "9000")])
    assert exc.value.key == "za_override_stale"


@pytest.mark.parametrize("raw", [
    _override("za_eti", "0", "1"),
    _override("za_paye", "0", "1", reason_code=""),
])
def test_invalid_override_blocks(raw):
    with pytest.raises(za.ZACalculationBlockedError) as exc:
        _calc(za_overrides=[raw])
    assert exc.value.key == "za_override"


def test_override_fields_are_the_content_list():
    assert content.OVERRIDE_FIELDS == ("za_paye", "za_uif_employee", "za_uif_employer", "za_sdl",
                                       "za_other_deductions")
