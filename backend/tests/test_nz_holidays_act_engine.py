"""New Zealand Holidays Act engine (ZP-NZ-ENG-001 Phase 5, pure).

Worked examples from the P5 plan §8 (content values from the spec, dates
illustrative). The pack comes from tests/_nz_engine_helpers.build_pack: the
spec's own nz_hol_* values with the PENDING marker stripped; public holidays
are TEST rows only.
"""
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.modules.payroll.engine.countries import new_zealand_content as content
from app.modules.payroll.engine.jurisdictions.new_zealand import holidays_act as ha
from app.modules.payroll.engine.jurisdictions.new_zealand.errors import NZCalculationBlockedError
from app.modules.payroll.engine.jurisdictions.new_zealand.pack import NzPack
from tests._nz_engine_helpers import build_pack

D = Decimal
FIXED = {"pattern_type": "FIXED", "weekly_schedule": {"MON": 8, "TUE": 8, "WED": 8, "THU": 8, "FRI": 8,
                                                     "SAT": 0, "SUN": 0}}


def _pack(on=date(2026, 6, 1), **kw):
    rate_map, slabs = build_pack(**kw)
    return NzPack(rate_map, slabs, 1, on)


def _holiday(day, name, region=None):
    return dict(rule_type=content.NZ_PUBLIC_HOLIDAY_RULE, effective_from=day, effective_to=None,
                rate_label=name, jurisdiction_state=region)


# ── worked example 1: annual anniversary ────────────────────────────────────
def test_annual_anniversary():
    pack = _pack()
    assert ha.annual_vests(date(2025, 5, 12), date(2026, 5, 11), [], pack) == []
    vests = ha.annual_vests(date(2025, 5, 12), date(2026, 5, 12), [], pack)
    assert [(v.leave_type, v.entitlement_date, v.unit, v.quantity) for v in vests] == \
        [("ANNUAL", date(2026, 5, 12), "WEEKS", D("4"))]
    assert ha.annual_vests(date(2025, 5, 12), date(2026, 5, 12), [date(2026, 5, 12)], pack) == []


def test_annual_29_february_start():
    pack = _pack()
    dates = [v.entitlement_date for v in ha.annual_vests(date(2024, 2, 29), date(2028, 3, 1), [], pack)]
    assert dates == [date(2025, 2, 28), date(2026, 2, 28), date(2027, 2, 28), date(2028, 2, 29)]


def test_annual_in_weeks_never_hours():
    vest = ha.annual_vests(date(2025, 5, 12), date(2026, 5, 12), [], _pack())[0]
    assert vest.unit == "WEEKS"
    assert not any("hour" in str(step).lower() for step in vest.steps)


# ── worked example 2: sick qualification and carry ──────────────────────────
def test_sick_qualification_and_carry():
    pack = _pack()
    start = date(2026, 1, 5)
    assert ha.sick_vests(start, date(2026, 7, 4), [], pack) == []
    first = ha.sick_vests(start, date(2026, 7, 5), [], pack)
    assert [(v.entitlement_date, v.quantity, v.carried_in) for v in first] == [(date(2026, 7, 5), D("10"), D("0"))]
    year1 = dict(entitlement_date=date(2026, 7, 5), quantity=D("10"), carried_in=D("0"), taken=D("4"), paid_out=0)
    second = ha.sick_vests(start, date(2027, 7, 5), [year1], pack)
    assert [(v.entitlement_date, v.quantity, v.carried_in) for v in second] == [(date(2027, 7, 5), D("10"), D("6"))]
    year2 = dict(entitlement_date=date(2027, 7, 5), quantity=D("10"), carried_in=D("6"), taken=0, paid_out=0)
    third = ha.sick_vests(start, date(2028, 7, 5), [year1, year2], pack)
    assert third[0].carried_in == D("10") and third[0].quantity + third[0].carried_in == D("20")


def test_sick_carry_cap_across_unvested_years():
    """Several years vesting at once: each carries the previous (untaken) one."""
    vests = ha.sick_vests(date(2026, 1, 5), date(2029, 7, 5), [], _pack())
    assert [v.carried_in for v in vests] == [D("0"), D("10"), D("10"), D("10")]


def test_sick_not_prorated():
    vest = ha.sick_vests(date(2026, 1, 5), date(2026, 7, 5), [], _pack())[0]
    assert vest.quantity == D("10")


def test_family_violence_no_carry():
    vests = ha.family_violence_vests(date(2026, 1, 5), date(2027, 7, 5), [], _pack())
    assert [(v.entitlement_date, v.quantity, v.carried_in) for v in vests] == \
        [(date(2026, 7, 5), D("10"), D("0")), (date(2027, 7, 5), D("10"), D("0"))]
    assert all(v.leave_type == "FAMILY_VIOLENCE" for v in vests)


def test_bereavement_close_other_and_not_yet_eligible():
    pack = _pack()
    start = date(2026, 1, 5)
    assert ha.bereavement_quantity("CLOSE", start, date(2026, 7, 4), pack)[0] == D("0")
    assert ha.bereavement_quantity("CLOSE", start, date(2026, 7, 5), pack)[0] == D("3")
    assert ha.bereavement_quantity("OTHER", start, date(2026, 7, 5), pack)[0] == D("1")
    with pytest.raises(NZCalculationBlockedError):
        ha.bereavement_quantity("COUSIN", start, date(2026, 7, 5), pack)


def test_balance():
    assert ha.balance(dict(quantity=D("10"), carried_in=D("6"), taken=D("3"), paid_out=D("1"))) == D("12")


# ── worked example 3: otherwise working day ─────────────────────────────────
def test_otherwise_working_day_fixed():
    assert ha.otherwise_working_day(date(2026, 6, 1), FIXED)[:2] == ("YES", "FIXED_PATTERN")    # Monday
    assert ha.otherwise_working_day(date(2026, 6, 6), FIXED)[:2] == ("NO", "FIXED_PATTERN")     # Saturday


def test_roster_week_index():
    roster = {"pattern_type": "ROSTERED", "roster_cycle_weeks": 2, "effective_from": date(2026, 6, 1),
              "roster_schedule": {"0": {"MON": 8}, "1": {"MON": 0}}}
    assert ha.otherwise_working_day(date(2026, 6, 1), roster)[:2] == ("YES", "ROSTER")
    assert ha.otherwise_working_day(date(2026, 6, 8), roster)[:2] == ("NO", "ROSTER")
    assert ha.otherwise_working_day(date(2026, 6, 15), roster)[:2] == ("YES", "ROSTER")


def test_variable_history_mixed_is_undetermined():
    variable = {"pattern_type": "VARIABLE"}
    assert ha.otherwise_working_day(date(2026, 6, 1), variable, [True, True])[0] == "YES"
    assert ha.otherwise_working_day(date(2026, 6, 1), variable, [False, False])[0] == "NO"
    assert ha.otherwise_working_day(date(2026, 6, 1), variable, [True, False])[0] == "UNDETERMINED"
    assert ha.otherwise_working_day(date(2026, 6, 1), None, [])[0] == "UNDETERMINED"


# ── worked example 4: midnight crossing ─────────────────────────────────────
def test_midnight_crossing():
    start, end = datetime(2026, 12, 24, 22), datetime(2026, 12, 25, 6)
    assert ha.hours_on_holiday(start, end, date(2026, 12, 25), "Pacific/Auckland") == D("6.00")
    assert ha.hours_on_holiday(start, end, date(2026, 12, 24), "Pacific/Auckland") == D("2.00")
    assert ha.hours_on_holiday(start, end, date(2026, 12, 26), "Pacific/Auckland") == D("0.00")


def test_dst_day_hours():
    # DST starts 2026-09-27 02:00 in Auckland: that local day has 23 hours
    day = date(2026, 9, 27)
    assert ha.hours_on_holiday(datetime(2026, 9, 27, 0), datetime(2026, 9, 28, 0), day, "Pacific/Auckland") == D("23.00")


def test_chatham_timezone():
    # an aware UTC shift lands on a different local window in the Chathams
    from datetime import timezone

    start = datetime(2026, 12, 24, 10, tzinfo=timezone.utc)      # 23:00 Auckland / 23:45 Chatham (NZDT)
    end = datetime(2026, 12, 24, 13, tzinfo=timezone.utc)
    assert ha.hours_on_holiday(start, end, date(2026, 12, 25), "Pacific/Auckland") == D("2.00")
    assert ha.hours_on_holiday(start, end, date(2026, 12, 25), "Pacific/Chatham") == D("2.75")
    with pytest.raises(ValueError):
        ha.hours_on_holiday(start, end, date(2026, 12, 25), "Australia/Sydney")


# ── worked example 5: alternative holiday ───────────────────────────────────
def test_alternative_holiday_due():
    assert ha.alternative_holiday_due(True, "YES") is True
    assert ha.alternative_holiday_due(True, "NO") is False
    assert ha.alternative_holiday_due(False, "YES") is False


# ── public holidays ─────────────────────────────────────────────────────────
def test_public_holidays_empty_blocks_until_g2():
    with pytest.raises(NZCalculationBlockedError) as exc:
        ha.holidays_for(_pack(), 2026, "AUK")
    assert exc.value.key == "NZ_TABLE_EMPTY:public_holidays"


def test_unsigned_public_holiday_blocks():
    rate_map, slabs = build_pack(pending=True, extra_slabs=[_holiday(date(2026, 12, 25), "Christmas Day")])
    with pytest.raises(NZCalculationBlockedError):
        ha.holidays_for(NzPack(rate_map, slabs, 1, None), 2026, None)


def test_regional_holiday_filtered_by_region():
    pack = _pack(extra_slabs=[_holiday(date(2026, 12, 25), "TEST national"),
                              _holiday(date(2026, 1, 26), "TEST Auckland anniversary", "AUK"),
                              _holiday(date(2026, 1, 19), "TEST Wellington anniversary", "WGN"),
                              _holiday(date(2027, 1, 1), "TEST next year")])
    auckland = ha.holidays_for(pack, 2026, "AUK")
    assert [(h["date"], h["region"]) for h in auckland] == [(date(2026, 1, 26), "AUK"), (date(2026, 12, 25), None)]
    assert [h["date"] for h in ha.holidays_for(pack, 2026, None)] == [date(2026, 12, 25)]


# ── every number comes from content ─────────────────────────────────────────
def test_every_number_from_content():
    pack = _pack(overrides={"nz_hol_annual_weeks": 5, "nz_hol_sick_days": 12, "nz_hol_sick_qualifying_months": 3,
                            "nz_hol_family_violence_days": 7, "nz_hol_bereavement_close_days": 4})
    assert ha.annual_vests(date(2025, 5, 12), date(2026, 5, 12), [], pack)[0].quantity == D("5")
    sick = ha.sick_vests(date(2026, 1, 5), date(2026, 4, 5), [], pack)
    assert [(v.entitlement_date, v.quantity) for v in sick] == [(date(2026, 4, 5), D("12"))]
    assert ha.family_violence_vests(date(2026, 1, 5), date(2026, 4, 5), [], pack)[0].quantity == D("7")
    assert ha.bereavement_quantity("CLOSE", date(2026, 1, 5), date(2026, 4, 5), pack)[0] == D("4")


def test_unsigned_holidays_row_blocks():
    rate_map, slabs = build_pack(pending=True)
    with pytest.raises(NZCalculationBlockedError):
        ha.annual_vests(date(2025, 5, 12), date(2026, 5, 12), [], NzPack(rate_map, slabs, 1, date(2026, 6, 1)))
