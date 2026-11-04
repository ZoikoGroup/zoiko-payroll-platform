"""New Zealand leave pay engine (ZP-NZ-ENG-001 Phase 6, pure; NZ-017, NZ-021).

TEST content only (tests/_nz_engine_helpers.build_p6_pack): the lookback
windows, divisors and methods are not stated by the specification and stay
empty in the shipped pack, which blocks."""
from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll.engine.jurisdictions.new_zealand import leave_pay as lp
from app.modules.payroll.engine.jurisdictions.new_zealand.errors import NZCalculationBlockedError
from app.modules.payroll.engine.jurisdictions.new_zealand.pack import NzPack
from tests._nz_engine_helpers import build_pack, build_p6_pack, ledger_rows

D = Decimal
END = date(2026, 9, 30)


def _pack(**overrides):
    rate_map, slabs = build_p6_pack(overrides)
    return NzPack(rate_map, slabs, 1, date(2026, 10, 5))


def _blocked(fn, *args, code, **kw):
    with pytest.raises(NZCalculationBlockedError) as exc:
        fn(*args, **kw)
    assert exc.value.key.startswith(code), exc.value.key
    return exc.value


# ── annual holidays: greater of OWP and AWE ─────────────────────────────────
def test_awe_beats_owp_worked_example():
    pay = lp.annual_leave_pay(1, D("1200"), ledger_rows(weeks=52, weekly="1300"), END, _pack())
    assert (pay.a.name, pay.a.rate, pay.b.name, pay.b.rate) == ("OWP", D("1200"), "AWE", D("1300"))
    assert (pay.chosen, pay.amount, pay.unit) == ("AWE", D("1300.00"), "WEEKS")
    assert pay.reason.startswith("greater of OWP and AWE")


def test_owp_beats_awe():
    pay = lp.annual_leave_pay(D("1.5"), D("1400"), ledger_rows(weekly="1300"), END, _pack())
    assert (pay.chosen, pay.amount) == ("OWP", D("2100.00"))


def test_equal_prefers_owp_and_records_reason():
    pay = lp.annual_leave_pay(1, D("1300"), ledger_rows(weekly="1300"), END, _pack())
    assert pay.chosen == "OWP" and pay.b.rate == D("1300") and "greater" in pay.reason


def test_owp_fallback_window():
    rows = ledger_rows(weeks=52, weekly="1000")
    rows[0]["amount"] = D("2000")                                   # latest week higher
    pay = lp.annual_leave_pay(1, None, rows, END, _pack())
    assert pay.a.rate == D("5000") / 4                              # 4-week TEST fallback window
    bonus = [dict(rows[0], id=999, component="BONUS", amount=D("9999"))]
    assert lp.owp(None, rows + bonus, END, _pack()).rate == D("1250")    # irregular pay excluded


def test_awe_window_and_divisor_from_content():
    rows = ledger_rows(weeks=60, weekly="1300")

    def inside(months):                                            # period ends in (END - months, END]
        start = date(END.year - (1 if months >= END.month else 0), (END.month - months - 1) % 12 + 1, END.day)
        return len([r for r in rows if start < r["periodEnd"] <= END])

    assert inside(12) == 53                                         # 12 calendar months hold 53 weekly ends here
    assert lp.awe(rows, END, _pack()).rate == D("1300") * inside(12) / 52
    assert lp.awe(rows, END, _pack(nz_hol_awe_divisor_weeks=26)).rate == D("1300") * inside(12) / 26
    assert lp.awe(rows, END, _pack(nz_hol_awe_lookback_months=6)).rate == D("1300") * inside(6) / 52


def test_missing_owp_or_awe_blocks():
    _blocked(lp.annual_leave_pay, 1, D("1200"), [], END, _pack(), code="NZ_LEAVE_EVIDENCE_MISSING:AWE")
    _blocked(lp.annual_leave_pay, 1, None, [], END, _pack(), code="NZ_LEAVE_EVIDENCE_MISSING")


def test_unreviewed_gross_row_blocks():
    rows = ledger_rows()
    rows[3]["treatment"], rows[3]["included"] = "REVIEW", False
    _blocked(lp.annual_leave_pay, 1, D("1200"), rows, END, _pack(), code="NZ_HOL_GROSS_UNREVIEWED")


def test_shipped_content_blocks():
    rate_map, slabs = build_pack()                                  # P3 TEST pack: P6 rows still empty
    pack = NzPack(rate_map, slabs, 1, date(2026, 10, 5))
    _blocked(lp.annual_leave_pay, 1, D("1200"), ledger_rows(), END, pack, code="NZ_ROW_MISSING:nz_hol_owp_method")


# ── daily pay: RDP or ADP ───────────────────────────────────────────────────
def test_rdp_used_when_determinable():
    pay = lp.daily_leave_pay("SICK", 2, D("260"), False, ledger_rows(), END, _pack())
    assert (pay.chosen, pay.amount, pay.b.rate) == ("RDP", D("520.00"), D("260"))   # ADP kept too


def test_adp_when_rdp_undeterminable():
    pay = lp.daily_leave_pay("SICK", 1, None, False, ledger_rows(weekly="1500"), END, _pack())
    assert (pay.chosen, pay.amount) == ("ADP", D("300.00"))
    assert "cannot be determined" in pay.reason and pay.a.missing


def test_adp_when_daily_pay_varies():
    pay = lp.daily_leave_pay("BEREAVEMENT", 1, D("260"), True, ledger_rows(weekly="1500"), END, _pack())
    assert (pay.chosen, pay.rate) == ("ADP", D("300"))
    assert pay.reason == "average daily pay: daily pay varies"


def test_adp_days_unknown_blocks():
    rows = ledger_rows()
    rows[0]["daysWorked"] = None
    _blocked(lp.daily_leave_pay, "SICK", 1, None, False, rows, END, _pack(), code="NZ_LEAVE_EVIDENCE_MISSING:ADP")


# ── public holidays, pay-as-you-go, cash-up ─────────────────────────────────
def test_public_holiday_worked_time_and_half():
    pay = lp.public_holiday_worked_pay(D("6"), D("30"), _pack())
    assert (pay.rate, pay.amount, pay.unit) == (D("45.0"), D("270.00"), "HOURS")
    _blocked(lp.public_holiday_worked_pay, D("6"), None, _pack(), code="NZ_LEAVE_EVIDENCE_MISSING")


def test_payg_eligible_only():
    _blocked(lp.payg_holiday_pay, D("1000"), False, _pack(), code="NZ_PAYG_NOT_ELIGIBLE")
    assert lp.payg_holiday_pay(D("1000"), True, _pack()).amount == D("80.00")


def test_cash_up_limit_and_balance():
    rows = ledger_rows(weekly="1300")
    assert lp.cash_up_pay(1, D("4"), D("1200"), rows, END, _pack()).amount == D("1300.00")
    _blocked(lp.cash_up_pay, D("1.5"), D("4"), D("1200"), rows, END, _pack(), code="NZ_CASHUP_LIMIT")
    _blocked(lp.cash_up_pay, D("1"), D("0.5"), D("1200"), rows, END, _pack(), code="NZ_CASHUP_LIMIT")


# ── final pay ───────────────────────────────────────────────────────────────
def _ents():
    return [dict(id=1, leave_type="ANNUAL", unit="WEEKS", balance=D("1.5")),
            dict(id=2, leave_type="SICK", unit="DAYS", balance=D("6")),
            dict(id=3, leave_type="FAMILY_VIOLENCE", unit="DAYS", balance=D("10")),
            dict(id=4, leave_type="ALTERNATIVE", unit="DAYS", balance=D("1"))]


def _final(payg=False, advance=0):
    rows = ledger_rows(weeks=52, weekly="1300")
    return lp.final_pay(_ents(), payg_eligible=payg, since=date(2026, 4, 30), termination_date=END, ledger=rows,
                        agreement_weekly=D("1200"), agreement_daily=D("240"), daily_pay_varies=False,
                        advance_paid=D(advance), last_period_end=END, pack=_pack())


def test_final_pay_vested_and_unvested():
    lines = {line.purpose: line for line in _final()}
    assert lines["FINAL_VESTED"].amount == D("1950.00")                         # 1.5 x AWE 1,300
    assert lines["ALTERNATIVE_HOLIDAY"].amount == D("240.00")
    unvested = lines["FINAL_UNVESTED"]
    weeks_since = len([r for r in ledger_rows() if date(2026, 4, 30) <= r["periodEnd"] <= END])
    assert unvested.units == D("1300") * weeks_since and unvested.amount == (unvested.units * 8 / 100).quantize(D("0.01"))
    assert _final(advance=1000)[-1].units == D("1300") * weeks_since - 1000     # advance already paid


def test_final_pay_skips_unvested_when_payg():
    assert "FINAL_UNVESTED" not in {line.purpose for line in _final(payg=True)}


def test_final_pay_sick_not_paid_but_listed():
    lines = {line.purpose: line for line in _final()}
    for kind in ("SICK", "FAMILY_VIOLENCE"):
        assert lines[kind].amount == 0 and lines[kind].reason == "not payable on termination"
        assert lines[kind].units > 0                                             # resolved, never zeroed


def test_every_number_from_content():
    pack = _pack(nz_hol_ph_worked_multiplier=2, nz_hol_payg_pct=10, nz_hol_cashup_max_weeks=2)
    assert lp.public_holiday_worked_pay(D("1"), D("30"), pack).amount == D("60.00")
    assert lp.payg_holiday_pay(D("1000"), True, pack).amount == D("100.00")
    assert lp.cash_up_pay(D("1.5"), D("4"), D("1200"), ledger_rows(), END, pack).units == D("1.5")
