"""New Zealand P3 engine end to end (ZP-NZ-ENG-001 §3–§7).

Covers the guards, the worked example from docs/new_zealand/P3_CODE_ARCHITECTURE.md
§6 (to the cent), the shared-pipeline integration (standard.py), determinism
and hashes, privacy of the result, engine purity and the shipped content's
fail-closed state.
"""
import json
import re
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from app.modules.payroll.engine.countries import new_zealand as engine
from app.modules.payroll.engine.jurisdictions.new_zealand import errors as E
from app.modules.payroll.engine.jurisdictions.new_zealand.errors import NZCalculationBlockedError
from app.modules.payroll.engine.resolver import calculate_payroll
from tests._nz_engine_helpers import build_pack, ctx, employer, kiwisaver, notice, tax_profile


def _blocked(context, key):
    with pytest.raises(NZCalculationBlockedError) as raised:
        engine.calculate(context)
    assert str(raised.value.key).startswith(key), raised.value.key


def _worked_example():
    return ctx(nz_tax_profile=tax_profile(tax_code="M SL"), nz_authority_deductions=[notice()])


# ── worked example (TEST method/rounding rows; spec bands and rates) ─────────
def test_worked_example_fortnightly_m_sl():
    out = engine.calculate(_worked_example())
    r = out["nz_result"]
    assert r["obligations"] == {
        "paye": "600.79", "payeRegular": "600.79", "payeExtra": "0.00", "accLevy": "52.50",
        "payeTotal": "653.29", "studentLoan": "248.64", "studentLoanStandard": "248.64",
        "studentLoanExtra": "0.00", "studentLoanExtraPay": "0.00", "ksEmployee": "105.00",
        "ksEmployerGross": "105.00", "esct": "31.50", "ksEmployerNet": "73.50", "childSupport": "797.22"}
    assert r["netPay"] == "1195.85" and r["employeeTotal"] == "1150.86"
    assert r["childSupport"]["shortfall"] == "102.78" and r["childSupport"]["variationCode"] == "TESTV"
    assert D(r["childSupport"]["protectedNet"]) >= D("1993.07") * D("0.6")
    assert r["minimumWage"]["status"] == "PASS"
    assert [e["code"] for e in r["exceptions"]] == ["NZ_CS_SHORTFALL"]
    assert r["accumulatorDeltas"] == {
        "ACC_LIABLE_EARNINGS": "3000.00", "PAYE_GROSS": "3000.00", "PAYE": "600.79", "ACC_LEVY": "52.50",
        "KS_GROSS": "3000.00", "KS_EMPLOYEE": "105.00", "KS_EMPLOYER_GROSS": "105.00", "ESCT": "31.50",
        "STUDENT_LOAN": "248.64", "CHILD_SUPPORT": "797.22"}
    assert (out["tds"], out["nz_employee_total"], out["employer_pension"]) == (D("653.29"), D("1150.86"), D("105.00"))


def test_standard_pipeline_net_equals_nz_result():
    result = calculate_payroll(_worked_example(), "standard")
    assert result.net_pay == D("1195.85") == D(result.nz_result["netPay"])
    assert result.tds == D("653.29")
    assert result.employer_pension == D("105.00")


@pytest.mark.parametrize("mode", ["simple"])
def test_simple_mode_still_refused(mode):
    with pytest.raises(NZCalculationBlockedError) as raised:
        calculate_payroll(_worked_example(), mode)
    assert raised.value.key == "NZ_SIMPLE_MODE_UNSUPPORTED"


# ── guards ──────────────────────────────────────────────────────────────────
def test_guards():
    _blocked(ctx(pay_date=None), E.PAY_DATE_MISSING)
    _blocked(ctx(pay_frequency="Daily"), E.FREQUENCY_UNSUPPORTED)
    assert engine.calculate(ctx(pay_frequency="FourWeekly"))["nz_result"]["frequency"] == "FOUR_WEEKLY"
    _blocked(ctx(nz_employer_profile=None), E.EMPLOYER_PROFILE_MISSING)
    _blocked(ctx(nz_employer_profile=employer(status="DRAFT")), "NZ_PROFILE_NOT_ACTIVE:employer_profile")
    _blocked(ctx(nz_tax_profile=None), E.TAX_PROFILE_MISSING)
    _blocked(ctx(nz_tax_profile=tax_profile(effective_from=date(2026, 5, 1))), "NZ_PROFILE_NOT_ACTIVE:tax_profile")
    _blocked(ctx(nz_tax_profile=tax_profile(residency_status="NON_RESIDENT")), E.NON_RESIDENT_UNSUPPORTED)
    _blocked(ctx(nz_payment_kind="BONUS_RUN"), E.PAYMENT_KIND_UNSUPPORTED)
    # Phase 6: a lump sum is accepted, then blocks on the unsigned IRD extra-pay method.
    _blocked(ctx(nz_payment_kind="LUMP_SUM"), "NZ_ROW_MISSING:nz_lump_sum_paye_method")
    _blocked(ctx(nz_accumulators=None), E.ACC_ACCUMULATOR_MISSING)


def test_payday_selects_rows_not_period_end():
    # Period 26 Mar - 8 Apr, payday 8 Apr: the 1-April KiwiSaver rows apply (NZ-008).
    r = engine.calculate(ctx(period_start=date(2026, 3, 26), period_end=date(2026, 4, 8)))["nz_result"]
    assert r["kiwisaver"]["employeeRate"] == "3.5000"


def test_minimum_wage_failure_is_an_exception_not_a_block():
    r = engine.calculate(ctx(gross=D("900"), basic=D("900"), nz_hours=D("80")))["nz_result"]
    assert r["minimumWage"]["status"] == "FAIL"
    assert r["exceptions"][0]["code"] == E.EXC_MIN_WAGE_FAIL
    assert r["netPay"] != "0.00"


def test_precedence_from_the_pack_is_used():
    r = engine.calculate(ctx())["nz_result"]
    assert r["precedence"] == ["PAYE", "ACC_LEVY", "STUDENT_LOAN", "KS_EMPLOYEE", "CHILD_SUPPORT"]
    _blocked(ctx(pack=build_pack(overrides={"nz_deduction_precedence": "PENDING_G1"})), E.PRECEDENCE_PENDING)


# ── shipped content stays fail-closed ───────────────────────────────────────
def test_shipped_content_blocks_unsigned():
    _blocked(ctx(pack=build_pack(pending=True)), E.PACK_UNSIGNED)


def test_shipped_content_without_pending_still_blocks_on_empty_authority_tables():
    pack = build_pack(drop_tables=("NZ_PAYE_METHOD", "NZ_SECONDARY_RATE", "NZ_ND_RATE", "NZ_IETC",
                                   "NZ_CS_VARIATION"))
    _blocked(ctx(pack=pack), "NZ_TABLE_EMPTY:paye_main_method")


# ── determinism, trace, privacy, purity ─────────────────────────────────────
def test_deterministic_result_and_hashes():
    first = engine.calculate(_worked_example())["nz_result"]
    second = engine.calculate(_worked_example())["nz_result"]
    assert first == second
    assert set(first["hashes"]) == {"inputHash", "packHash", "resultHash"}
    changed = engine.calculate(ctx(nz_tax_profile=tax_profile(tax_code="M SL"), nz_authority_deductions=[notice()],
                                   gross=D("3001"), basic=D("3001")))["nz_result"]
    assert changed["hashes"]["inputHash"] != first["hashes"]["inputHash"]


def test_trace_lists_rows_used_and_rounding():
    r = engine.calculate(_worked_example())["nz_result"]
    ids = {row["id"] for row in r["trace"]["rowsUsed"]}
    assert {"nz_acc_earner_levy_rate", "nz_sl_rate", "nz_paye_rounding"} <= ids
    assert r["trace"]["roundingEvents"] and r["trace"]["periodFactor"] == "26"


def test_result_is_json_and_holds_no_personal_identifiers():
    r = engine.calculate(ctx(nz_date_of_birth=date(1996, 5, 1)))["nz_result"]
    text = json.dumps(r)
    assert "1996-05-01" not in text and "date_of_birth" not in text
    assert not re.search(r"(?<!\d)\d{8,9}(?!\d)", text.replace(r["hashes"]["inputHash"], "")
                         .replace(r["hashes"]["packHash"], "").replace(r["hashes"]["resultHash"], ""))


def test_engine_package_is_pure():
    root = Path(engine.__file__).resolve().parents[1]
    files = [Path(engine.__file__), *sorted((root / "jurisdictions" / "new_zealand").glob("*.py"))]
    forbidden = re.compile(r"date\.today|datetime\.now|datetime\.utcnow|import random|SessionLocal|"
                           r"from app\.config|from app\.database|import requests|import httpx|sqlalchemy")
    for path in files:
        assert not forbidden.search(path.read_text(encoding="utf-8")), path.name


def test_never_falls_through_to_the_generic_calculator():
    from app.modules.payroll.engine import standard

    assert standard._COUNTRY_CALC["NZ"] is engine.calculate
