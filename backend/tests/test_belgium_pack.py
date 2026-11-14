"""Belgium (ZP-BE-ENG-001) Phase 3A: BePack, the only reader of pack rows.

Pure: rows are plain dicts. Every number below is a SYNTHETIC test value, never
Belgian statutory content."""
from datetime import date
from decimal import Decimal

import pytest

MARK = "[PENDING G1]"


def _pack(rate_map, slabs=(), as_of=date(2026, 7, 15)):
    from app.modules.payroll.engine.jurisdictions.belgium.pack import BePack

    return BePack(rate_map, list(slabs), 1, as_of)


def _row(key, label="signed row", **values):
    return {"component_key": key, "label": label, **values}


def _blocked(code):
    from app.modules.payroll.engine.jurisdictions.belgium.errors import BECalculationBlockedError

    return pytest.raises(BECalculationBlockedError, match=code)


def test_pending_label_blocks_with_content_pending():
    pack = _pack({"be_wage_rmmmg": _row("be_wage_rmmmg", f"RMMMG {MARK}", flat_amount="1000")})
    with _blocked("BE_CONTENT_PENDING:be_wage_rmmmg"):
        pack.amount("be_wage_rmmmg")


@pytest.mark.parametrize("values", [{}, {"flat_amount": None}, {"flat_amount": ""}])
def test_empty_value_blocks_with_content_pending(values):
    pack = _pack({"be_wage_rmmmg": _row("be_wage_rmmmg", **values)})
    with _blocked("BE_CONTENT_PENDING:be_wage_rmmmg"):
        pack.amount("be_wage_rmmmg")


def test_pending_g1_text_blocks():
    pack = _pack({"be_ot_threshold_rule": _row("be_ot_threshold_rule", text_value="PENDING_G1")})
    with _blocked("BE_CONTENT_PENDING:be_ot_threshold_rule"):
        pack.text("be_ot_threshold_rule")


def test_not_supported_blocks_with_feature_blocked():
    pack = _pack({"be_bssc_pending": _row("be_bssc_pending", text_value="NOT_SUPPORTED")})
    with _blocked("BE_FEATURE_BLOCKED:be_bssc_pending"):
        pack.text("be_bssc_pending")


def test_missing_key_blocks():
    with _blocked("BE_ROW_MISSING:be_onss_employee_rate"):
        _pack({}).pct("be_onss_employee_rate", "employee")


def test_mid_year_window_selects_the_row_in_force_on_the_pay_date():
    rows = [_row("be_wage_rmmmg", flat_amount="1000", effective_from=date(2026, 1, 1),
                 effective_to=date(2026, 6, 30)),
            _row("be_wage_rmmmg", flat_amount="1100", effective_from=date(2026, 7, 1), effective_to=None)]
    assert _pack({"be_wage_rmmmg": rows}, as_of=date(2026, 6, 30)).amount("be_wage_rmmmg") == Decimal("1000")
    assert _pack({"be_wage_rmmmg": rows}, as_of=date(2026, 7, 1)).amount("be_wage_rmmmg") == Decimal("1100")
    used = _pack({"be_wage_rmmmg": rows}, as_of=date(2026, 7, 1))
    used.amount("be_wage_rmmmg")
    assert used.used()[0]["effectiveFrom"] == "2026-07-01"


def test_a_pending_successor_blocks_only_after_its_start():
    rows = [_row("be_wage_rmmmg", flat_amount="1000", effective_to=date(2026, 6, 30)),
            _row("be_wage_rmmmg", f"RMMMG {MARK}", flat_amount="1100", effective_from=date(2026, 7, 1))]
    assert _pack({"be_wage_rmmmg": rows}, as_of=date(2026, 6, 30)).amount("be_wage_rmmmg") == Decimal("1000")
    with _blocked("BE_CONTENT_PENDING"):
        _pack({"be_wage_rmmmg": rows}, as_of=date(2026, 7, 1)).amount("be_wage_rmmmg")


def test_overlapping_windows_block():
    rows = [_row("be_wage_rmmmg", flat_amount="1000"), _row("be_wage_rmmmg", flat_amount="1100")]
    with _blocked("BE_CONTENT_PENDING"):
        _pack({"be_wage_rmmmg": rows}).amount("be_wage_rmmmg")


def test_no_row_in_force_blocks():
    rows = [_row("be_wage_rmmmg", flat_amount="1000", effective_to=date(2026, 6, 30))]
    with _blocked("BE_ROW_MISSING"):
        _pack({"be_wage_rmmmg": rows}, as_of=date(2026, 7, 1)).amount("be_wage_rmmmg")


def test_rates_and_text_lists():
    pack = _pack({"be_onss_employee_rate": _row("be_onss_employee_rate", employee_rate_pct="10"),
                  "be_supported_pay_frequencies": _row("be_supported_pay_frequencies",
                                                       text_value="monthly, weekly")})
    assert pack.pct("be_onss_employee_rate", "employee") == Decimal("10")
    with _blocked("BE_CONTENT_PENDING"):
        pack.pct("be_onss_employee_rate", "employer")              # the employer side is empty
    assert pack.text_list("be_supported_pay_frequencies") == ["MONTHLY", "WEEKLY"]


def test_rounding_comes_only_from_signed_be_rounding_rows():
    pack = _pack({"be_rounding_onss": _row("be_rounding_onss", text_value="CENT_HALF_UP"),
                  "be_rounding_holiday": _row("be_rounding_holiday", text_value="EURO_DOWN"),
                  "be_rounding_withholding": _row("be_rounding_withholding", f"r {MARK}", text_value="CENT_DOWN"),
                  "be_wage_rmmmg": _row("be_wage_rmmmg", text_value="CENT_HALF_UP")})
    assert pack.rounder("be_rounding_onss")(Decimal("10.005")) == Decimal("10.01")
    assert pack.rounder("be_rounding_holiday")(Decimal("10.99")) == Decimal("10")
    assert pack.rounding_events[0]["key"] == "be_rounding_onss"
    with _blocked("BE_CONTENT_PENDING:be_rounding_withholding"):
        pack.rounder("be_rounding_withholding")                    # unsigned rounding row
    with _blocked("BE_ROUNDING_KEY_INVALID:be_wage_rmmmg"):
        pack.rounder("be_wage_rmmmg")                              # never from a non-rounding row
    with _blocked("BE_ROW_MISSING:be_rounding_missing"):
        pack.rounder("be_rounding_missing")


def test_unknown_rounding_rule_blocks():
    pack = _pack({"be_rounding_onss": _row("be_rounding_onss", text_value="BANKERS")})
    with _blocked("BE_CONTENT_PENDING:be_rounding_onss"):
        pack.rounder("be_rounding_onss")


def test_table_needs_a_signed_slab_rows_marker_and_signed_rows():
    marker = _row("be_public_holidays", text_value="SLAB_ROWS")
    holiday = {"rule_type": "BE_PUBLIC_HOLIDAY", "min_amount": "0", "rate_label": "holiday A",
               "filing_status": "A", "effective_from": date(2026, 1, 1), "effective_to": date(2026, 12, 31)}
    assert len(_pack({"be_public_holidays": marker}, [holiday]).table("be_public_holidays")) == 1
    with _blocked("BE_TABLE_EMPTY:be_public_holidays"):
        _pack({"be_public_holidays": marker}, []).table("be_public_holidays")
    with _blocked("BE_CONTENT_PENDING"):
        _pack({"be_public_holidays": marker}, [dict(holiday, rate_label=f"holiday A {MARK}")]).table(
            "be_public_holidays")
    with _blocked("BE_FEATURE_BLOCKED"):
        _pack({"be_public_holidays": _row("be_public_holidays", text_value="NOT_SUPPORTED")},
              [holiday]).table("be_public_holidays")
    with _blocked("BE_CONTENT_PENDING"):
        _pack({"be_public_holidays": _row("be_public_holidays", text_value="OTHER")}, [holiday]).table(
            "be_public_holidays")


def test_earning_classes_block_while_pending():
    signed = {"rule_type": "BE_EARNING_CLASS", "tax_regime": "ONSS_EMPLOYEE", "filing_status": "SALARY",
              "assessment_basis": "INCLUDED", "rate_label": "ONSS_EMPLOYEE: SALARY"}
    assert _pack({}, [signed]).earning_classes() == {("ONSS_EMPLOYEE", "SALARY"): "INCLUDED"}
    with _blocked("BE_CONTENT_PENDING"):
        _pack({}, [dict(signed, rate_label=f"x {MARK}")]).earning_classes()
    with _blocked("BE_TABLE_EMPTY"):
        _pack({}, []).earning_classes()


def test_used_records_every_row_consumed():
    pack = _pack({"be_wage_rmmmg": _row("be_wage_rmmmg", flat_amount="1000"),
                  "be_onss_employee_rate": _row("be_onss_employee_rate", employee_rate_pct="10")})
    pack.amount("be_wage_rmmmg")
    pack.pct("be_onss_employee_rate", "employee")
    assert [u["id"] for u in pack.used()] == ["be_onss_employee_rate", "be_wage_rmmmg"]
