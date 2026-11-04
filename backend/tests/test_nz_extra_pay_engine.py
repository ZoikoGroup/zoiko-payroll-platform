"""New Zealand extra pay and payment kinds through the orchestrator
(ZP-NZ-ENG-001 Phase 6, pure). TEST content only: the IRD extra-pay method
and the holiday-advance treatments are empty in the shipped pack (blocks)."""
from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll.engine.countries import new_zealand as engine
from app.modules.payroll.engine.countries import new_zealand_content as content
from app.modules.payroll.engine.jurisdictions.new_zealand import paye as _paye
from app.modules.payroll.engine.jurisdictions.new_zealand.errors import NZCalculationBlockedError
from tests._nz_engine_helpers import P6_TEST_VALUES, build_p6_pack, build_pack, ctx, tax_profile

D = Decimal


def _ctx(**kw):
    kw.setdefault("nz_prior_four_week_gross", D("6000"))
    return ctx(pack=kw.pop("pack", None) or build_p6_pack(), **kw)


def _r(**kw):
    return engine.calculate(_ctx(**kw))["nz_result"]


def _blocked(code, **kw):
    with pytest.raises(NZCalculationBlockedError) as exc:
        engine.calculate(_ctx(**kw))
    assert exc.value.key.startswith(code), exc.value.key


def _band_tax(annual):
    return _paye.band_tax(D(annual), [dict(min_amount=lo, max_amount=hi, rate_pct=r)
                                      for lo, hi, r in content.NZ_PAYE_BANDS])[0]


def test_extra_pay_annualise_difference():
    r = _r(nz_payment_kind="LUMP_SUM", gross=D("5000"), basic=D("0"))
    expected = (_band_tax(6000 * 13 + 5000) - _band_tax(6000 * 13)).quantize(D("0.01"))
    assert r["obligations"]["payeExtra"] == str(expected) == "1647.00"
    assert r["obligations"]["payeRegular"] == "0.00" and r["extraPay"]["bases"]["PAYE"] == "5000.00"
    assert r["minimumWage"]["status"] == "NOT_APPLICABLE" and r["exceptions"] == []
    assert r["accumulatorDeltas"]["PAYE_GROSS"] == "5000.00"


def test_extra_pay_needs_history():
    _blocked("NZ_EXTRA_PAY_HISTORY_MISSING", nz_payment_kind="LUMP_SUM", gross=D("5000"), basic=D("0"),
             nz_prior_four_week_gross=None)


def test_extra_pay_secondary_flat():
    r = _r(nz_payment_kind="LUMP_SUM", gross=D("5000"), basic=D("0"), nz_tax_profile=tax_profile(tax_code="S"))
    assert r["obligations"]["payeExtra"] == "875.00"                      # TEST secondary S rate 17.5%


def test_extra_pay_acc_shares_cap():
    r = _r(gross=D("5000"), basic=D("3000"), nz_components={"SALARY": D("3000"), "BONUS": D("2000")},
           nz_accumulators={"ACC_LIABLE_EARNINGS": D("155000")})
    assert r["acc"]["liable"] == "1641.00" and r["acc"]["capCrossed"] is True
    assert r["bases"]["PAYE"] == "3000.00" and r["extraPay"]["bases"]["PAYE"] == "2000.00"


def test_extra_pay_sl_whole():
    r = _r(nz_payment_kind="LUMP_SUM", gross=D("5000"), basic=D("0"), nz_tax_profile=tax_profile(tax_code="M SL"))
    assert r["obligations"]["studentLoanExtraPay"] == "600.00"            # 12% of the whole payment


def test_lump_sum_mixed_with_salary_blocks():
    _blocked("NZ_LUMP_SUM_MIXED", nz_payment_kind="LUMP_SUM",
             nz_components={"SALARY": D("1000"), "LUMP_SUM": D("2000")})


def test_shipped_lump_sum_table_empty_blocks():
    pack = build_pack(overrides=P6_TEST_VALUES)                           # method signed, table still empty
    _blocked("NZ_TABLE_EMPTY:lump_sum_method", pack=pack, nz_payment_kind="LUMP_SUM", gross=D("5000"), basic=D("0"))


def test_holiday_advance_standard_vs_alternative():
    per_period = _r(gross=D("1500"), basic=D("1500"))["obligations"]["paye"]
    standard = _r(nz_payment_kind="HOLIDAY_PAY_ADVANCE", gross=D("3000"), basic=D("0"),
                  nz_run_options={"holidayAdvanceMethod": "STANDARD", "advancePeriods": 2})
    assert standard["obligations"]["payeRegular"] == str(D(per_period) * 2)
    alternative = _r(nz_payment_kind="HOLIDAY_PAY_ADVANCE", gross=D("3000"), basic=D("0"),
                     nz_run_options={"holidayAdvanceMethod": "ALTERNATIVE"})
    assert alternative["obligations"]["payeRegular"] == "0.00" and alternative["extraPay"]["bases"]["PAYE"] == "3000.00"
    _blocked("NZ_ADVANCE_METHOD_INVALID", nz_payment_kind="HOLIDAY_PAY_ADVANCE", gross=D("3000"), basic=D("0"),
             nz_run_options={"holidayAdvanceMethod": "GUESS"})
    _blocked("NZ_ADVANCE_METHOD_INVALID", nz_payment_kind="HOLIDAY_PAY_ADVANCE", gross=D("3000"), basic=D("0"),
             nz_run_options={"holidayAdvanceMethod": "STANDARD"})


def test_out_of_cycle_method():
    extra = _r(nz_payment_kind="OUT_OF_CYCLE")
    assert extra["obligations"]["payeRegular"] == "0.00" and extra["extraPay"]["bases"]["PAYE"] == "3000.00"
    main = _r(nz_payment_kind="OUT_OF_CYCLE", pack=build_p6_pack({"nz_out_of_cycle_paye_method": "PERIOD_MAIN"}))
    assert main["obligations"]["paye"] == _r()["obligations"]["paye"] and main["extraPay"] is None


def test_leave_lines_replace_displaced_pay():
    line = {"calculationId": 7, "purpose": "ANNUAL_LEAVE", "amount": "1300.00", "displaced": "1200.00"}
    r = _r(gross=D("3100"), nz_leave_lines=[line])                       # top-up of 100 is in gross
    lines = {l["component"]: l["amount"] for l in r["baseLines"]["PAYE"]}
    assert lines == {"SALARY": "1800.00", "HOLIDAY_PAY": "1300.00"} and r["leavePay"] == [line]
    _blocked("NZ_LEAVE_TOP_UP_NOT_IN_GROSS", nz_leave_lines=[line])        # gross 3000: top-up missing
    _blocked("NZ_EARNING_CLASS_REVIEW", pack=build_p6_pack(holiday_pay="REVIEW"), gross=D("3100"),
             nz_leave_lines=[line])                                        # shipped HOLIDAY_PAY treatment


def test_final_pay_lines_taxed_as_extra():
    final = [{"calculationId": 9, "purpose": "FINAL_VESTED", "amount": "4030.00"}]
    r = _r(nz_payment_kind="FINAL", gross=D("7030"), nz_final_pay_lines=final)
    assert r["bases"]["PAYE"] == "3000.00" and r["extraPay"]["bases"]["PAYE"] == "4030.00"
    assert r["finalPay"] == final and r["minimumWage"]["status"] != "NOT_APPLICABLE"


def test_extra_pay_is_deterministic():
    first = _r(nz_payment_kind="LUMP_SUM", gross=D("5000"), basic=D("0"))
    second = _r(nz_payment_kind="LUMP_SUM", gross=D("5000"), basic=D("0"))
    assert first["hashes"] == second["hashes"]
    assert _r(nz_payment_kind="LUMP_SUM", gross=D("5000"), basic=D("0"),
              nz_prior_four_week_gross=D("6001"))["hashes"]["inputHash"] != first["hashes"]["inputHash"]
