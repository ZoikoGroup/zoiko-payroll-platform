"""Japan Phase 6: working-time classification, premium floor and minimum wage
(ZP-JP-ENG-001 S14). Every number here is synthetic."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.payroll.engine.countries import japan, japan_content as content
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
from app.modules.payroll.engine.jurisdictions.japan import labour


def D(value):
    return Decimal(str(value))


def _day(worked, scheduled=480, night=0, holiday=False):
    return {"worked_minutes": worked, "scheduled_minutes": scheduled,
            "night_minutes": night, "is_holiday": holiday}


def _ctx(**overrides):
    from tests.test_japan_engine import _context

    return _context(**overrides)


def _blocks(ctx, key):
    with pytest.raises(MissingComplianceConfigurationError) as exc:
        japan.calculate(ctx)
    assert exc.value.key == key
    return exc.value


def _signed_overtime(slabs):
    """Make the synthetic overtime earning class INCLUDED for every obligation.

    The real content leaves overtime REVIEW until signed; these engine tests
    need a payable component so the labour-floor check can be reached.
    """
    out = []
    for row in slabs:
        if (row.rule_type == content.JP_EARNING_CLASS_RULE
                and row.filing_status == "OVERTIME"):
            row = SimpleNamespace(**vars(row))
            row.assessment_basis = "INCLUDED"
        out.append(row)
    return out


# ── classification ────────────────────────────────────────────────────────

def test_empty_hours_are_all_zero():
    got = labour.classify_hours([])
    assert got.as_dict()["totalOvertimeMinutes"] == 0
    assert got.total_worked_minutes == 0


def test_eight_hour_day_is_ordinary():
    got = labour.classify_hours([_day(480)])
    assert got.ordinary_minutes == 480
    assert got.total_overtime_minutes == 0


def test_daily_overtime_starts_above_eight_hours():
    got = labour.classify_hours([_day(600)])
    assert got.ordinary_minutes == 480
    assert got.statutory_overtime_minutes == 120


def test_long_schedule_still_overtimes_above_eight_hours():
    got = labour.classify_hours([_day(540, scheduled=600)])
    assert got.ordinary_minutes == 480
    assert got.within_schedule_extra_minutes == 0
    assert got.statutory_overtime_minutes == 60


def test_short_schedule_extra_and_daily_overtime_split():
    got = labour.classify_hours([_day(540, scheduled=420)])
    assert got.ordinary_minutes == 420
    assert got.within_schedule_extra_minutes == 60
    assert got.statutory_overtime_minutes == 60


def test_weekly_overtime_starts_above_forty_hours():
    got = labour.classify_hours([_day(480) for _ in range(6)])
    assert got.ordinary_minutes == 2400
    assert got.statutory_overtime_minutes == 480


def test_weekly_overtime_does_not_double_count_daily_overtime():
    got = labour.classify_hours([_day(600) for _ in range(5)])
    assert got.ordinary_minutes == 2400
    assert got.statutory_overtime_minutes == 600


def test_weekly_and_daily_overtime_combine():
    got = labour.classify_hours([_day(600) for _ in range(6)])
    assert got.ordinary_minutes == 2400
    assert got.statutory_overtime_minutes == 1200


def test_weekly_overtime_eats_extra_schedule_hours_first():
    got = labour.classify_hours([_day(480, scheduled=360) for _ in range(6)])
    assert got.ordinary_minutes == 2160
    assert got.within_schedule_extra_minutes == 240
    assert got.statutory_overtime_minutes == 480


def test_over_sixty_hours_splits_the_higher_premium():
    got = labour.classify_hours([_day(870) for _ in range(7)])
    assert got.statutory_overtime_minutes == 3600
    assert got.over_60_minutes == 90
    assert got.total_worked_minutes == 6090


def test_statutory_holiday_hours_are_their_own_category():
    got = labour.classify_hours([_day(600, holiday=True)])
    assert got.statutory_holiday_minutes == 600
    assert got.ordinary_minutes == 0
    assert got.total_overtime_minutes == 0


def test_night_minutes_are_reported_separately():
    got = labour.classify_hours([_day(480, night=120)])
    assert got.ordinary_minutes == 480
    assert got.night_minutes == 120


def test_hours_hours_field_is_converted_to_minutes():
    got = labour.classify_hours([{"hours": "8", "scheduled_minutes": 480}])
    assert got.ordinary_minutes == 480


def test_negative_hours_block():
    with pytest.raises(labour.JapanLabourBlockedError) as exc:
        labour.classify_hours([_day(-1)])
    assert exc.value.key.startswith("jp_hours:")


def test_invalid_week_start_blocks():
    with pytest.raises(labour.JapanLabourBlockedError) as exc:
        labour.classify_hours([_day(480)], week_start_day=7)
    assert exc.value.key == "jp_week_start_day"


# ── premium floor ─────────────────────────────────────────────────────────

def test_premium_base_hourly_divides_by_scheduled_hours():
    assert labour.premium_base_hourly(D(300000), D(240)) == D(1250)


def test_premium_base_needs_positive_hours():
    with pytest.raises(labour.JapanLabourBlockedError) as exc:
        labour.premium_base_hourly(D(300000), D(0))
    assert exc.value.key == "jp_scheduled_monthly_hours"


def test_premium_floor_for_daily_overtime():
    got = labour.premium_floor(D(1250), labour.classify_hours([_day(600)]))
    assert got == D(625)


def test_premium_floor_for_holiday_work():
    got = labour.premium_floor(D(1250), labour.classify_hours([_day(480, holiday=True)]))
    assert got == D(3500)


def test_premium_floor_for_night_work():
    got = labour.premium_floor(D(1250), labour.classify_hours([_day(480, night=120)]))
    assert got == D(625)


def test_premium_floor_combines_categories():
    got = labour.premium_floor(
        D(1250), labour.classify_hours([_day(600, night=120)]))
    assert got == D(1250)


def test_premium_floor_for_over_sixty_hours():
    got = labour.premium_floor(
        D(1000), labour.classify_hours([_day(870) for _ in range(7)]))
    assert got == D(15750)


def test_paid_premium_below_floor_blocks():
    with pytest.raises(labour.JapanLabourBlockedError) as exc:
        labour.check_premium(D(624), D(625))
    assert exc.value.key == "jp_overtime_premium"


def test_paid_premium_at_the_floor_passes():
    labour.check_premium(D(625), D(625))


# ── minimum wage ──────────────────────────────────────────────────────────

def _wage(state="13", amount="1200", start=date(2026, 1, 1), end=None):
    return SimpleNamespace(rule_type=content.JP_MIN_WAGE_RULE, jurisdiction_state=state,
                           flat_amount=D(amount), effective_from=start, effective_to=end)


def test_minimum_wage_row_for_the_prefecture_and_date():
    row = _wage()
    assert labour.minimum_wage_row([row], "13", date(2026, 6, 1)) is row


def test_minimum_wage_future_row_is_not_in_force():
    row = _wage(start=date(2027, 1, 1))
    assert labour.minimum_wage_row([row], "13", date(2026, 6, 1)) is None


def test_minimum_wage_ended_row_is_not_in_force():
    row = _wage(end=date(2026, 3, 31))
    assert labour.minimum_wage_row([row], "13", date(2026, 6, 1)) is None


def test_minimum_wage_latest_start_wins():
    old = _wage(amount="1100", start=date(2025, 1, 1))
    new = _wage(amount="1200", start=date(2026, 1, 1))
    assert labour.minimum_wage_row([old, new], "13", date(2026, 6, 1)) is new


def test_minimum_wage_tie_blocks():
    one = _wage(amount="1100")
    two = _wage(amount="1200")
    with pytest.raises(labour.JapanLabourBlockedError) as exc:
        labour.minimum_wage_row([one, two], "13", date(2026, 6, 1))
    assert exc.value.key == "jp_minimum_wage"


def test_missing_minimum_wage_blocks():
    with pytest.raises(labour.JapanLabourBlockedError) as exc:
        labour.minimum_wage_check(D(1200), None, "13")
    assert exc.value.key == "jp_minimum_wage"


def test_minimum_wage_row_without_positive_amount_blocks():
    with pytest.raises(labour.JapanLabourBlockedError) as exc:
        labour.minimum_wage_check(D(1200), D(0), "13")
    assert exc.value.key == "jp_minimum_wage"


def test_hourly_wage_below_minimum_blocks():
    with pytest.raises(labour.JapanLabourBlockedError) as exc:
        labour.minimum_wage_check(D(1199), D(1200), "13")
    assert exc.value.key == "jp_minimum_wage:13"


def test_hourly_wage_at_minimum_passes():
    assert labour.minimum_wage_check(D(1200), D(1200), "13") == D(1200)


# ── holidays and night ────────────────────────────────────────────────────

def _holiday(day, name="Synthetic holiday"):
    return SimpleNamespace(rule_type=content.JP_HOLIDAY_RULE, holiday_date=day,
                           rate_label=name)


def test_holidays_for_the_requested_year_only():
    rows = [_holiday(date(2026, 1, 1)), _holiday(date(2027, 1, 1))]
    got = labour.holidays_for_year(rows, 2026)
    assert got == [{"date": "2026-01-01", "name": "Synthetic holiday"}]


def test_holiday_iso_date_string_is_accepted():
    row = SimpleNamespace(rule_type=content.JP_HOLIDAY_RULE,
                          date="2026-05-03", name="Synthetic")
    assert labour.holidays_for_year([row], 2026)[0]["date"] == "2026-05-03"


def test_holidays_from_other_rules_are_ignored():
    row = _wage()
    assert labour.holidays_for_year([row], 2026) == []


def test_night_minutes_inside_one_shift():
    assert labour.night_minutes("21:00", "23:00") == 60


def test_night_minutes_cross_midnight():
    assert labour.night_minutes("22:00", "05:00") == 420


def test_night_minutes_for_a_day_shift_are_zero():
    assert labour.night_minutes("18:00", "22:00") == 0


def test_invalid_clock_pair_returns_zero():
    assert labour.night_minutes("", "05:00") == 0


# ── engine integration ────────────────────────────────────────────────────

def test_salary_without_work_conditions_blocks():
    key = _blocks(_ctx(jp_work_conditions=None), "jp_work_conditions")
    assert "work conditions" in key.args[0]


def test_salary_without_minimum_wage_row_blocks():
    slabs = [row for row in _ctx().slabs if row.rule_type != content.JP_MIN_WAGE_RULE]
    _blocks(_ctx(slabs=slabs), "jp_minimum_wage")


def test_salary_below_the_minimum_wage_blocks():
    slabs = []
    for row in _ctx().slabs:
        if row.rule_type == content.JP_MIN_WAGE_RULE:
            row = SimpleNamespace(**vars(row))
            row.flat_amount = D("2000")
        slabs.append(row)
    _blocks(_ctx(slabs=slabs), "jp_minimum_wage:13")


def test_unapproved_overtime_hours_block():
    _blocks(_ctx(jp_hours=[_day(600)], jp_hours_approved=False), "jp_hours_approved")


def test_paid_overtime_without_hours_blocks():
    _blocks(_ctx(gross=D(301000), basic=D(300000), overtime=D(1000),
                 slabs=_signed_overtime(_ctx().slabs),
                 jp_hours=[], jp_hours_approved=False), "jp_hours_approved")


def test_paid_overtime_below_the_floor_blocks():
    _blocks(_ctx(gross=D(300100), basic=D(300000), overtime=D(100),
                 slabs=_signed_overtime(_ctx().slabs),
                 jp_hours=[_day(600)], jp_hours_approved=True), "jp_overtime_premium")


def test_approved_overtime_at_the_floor_passes_with_trace():
    result = japan.calculate(_ctx(
        gross=D(300625), basic=D(300000), overtime=D(625),
        slabs=_signed_overtime(_ctx().slabs),
        jp_hours=[_day(600)], jp_hours_approved=True))["jp_result"]
    trace = result["trace"]["labour"]
    assert trace["premiumPaid"] == "625"
    assert trace["premiumFloor"] == "625"
    assert trace["hours"]["statutoryOvertimeMinutes"] == 120
    assert trace["hoursApproved"] is True


def test_holiday_premium_is_checked():
    _blocks(_ctx(gross=D(301000), basic=D(300000), overtime=D(1000),
                 slabs=_signed_overtime(_ctx().slabs),
                 jp_hours=[_day(480, holiday=True)], jp_hours_approved=True),
            "jp_overtime_premium")


def test_holiday_premium_at_the_floor_passes():
    result = japan.calculate(_ctx(
        gross=D(303500), basic=D(300000), overtime=D(3500),
        slabs=_signed_overtime(_ctx().slabs),
        jp_hours=[_day(480, holiday=True)], jp_hours_approved=True))["jp_result"]
    trace = result["trace"]["labour"]
    assert trace["hours"]["statutoryHolidayMinutes"] == 480
    assert trace["premiumFloor"] == "3500"


def test_night_minutes_come_from_the_signed_window_and_clock_pair():
    day = {"worked_minutes": 420, "scheduled_minutes": 480,
           "check_in": "22:00", "check_out": "05:00", "is_holiday": False}
    result = japan.calculate(_ctx(
        gross=D(302188), basic=D(300000), overtime=D(2188),
        slabs=_signed_overtime(_ctx().slabs),
        jp_hours=[day], jp_hours_approved=True))["jp_result"]
    trace = result["trace"]["labour"]
    assert trace["nightWindow"] == "22:00-05:00"
    assert trace["hours"]["nightMinutes"] == 420
    assert trace["premiumFloor"] == "2188"


def test_two_premium_categories_need_the_signed_combination_rule():
    day = {"worked_minutes": 600, "scheduled_minutes": 480,
           "night_minutes": 120, "is_holiday": False}
    _blocks(_ctx(gross=D(301000), basic=D(300000), overtime=D(1000),
                 slabs=_signed_overtime(_ctx().slabs),
                 jp_hours=[day], jp_hours_approved=True),
            "jp_premium_combination_rule")


def test_bonus_payment_does_not_need_work_conditions():
    from tests.test_japan_bonus import _bonus_rate_map, _bonus_slabs

    result = japan.calculate(_ctx(
        jp_payment_kind="BONUS", jp_components={"BONUS": D(100000)},
        gross=D(100000), basic=D(0), jp_work_conditions=None,
        rate_map=_bonus_rate_map(),
        jp_prior_month_pay_after_si=D(256050),
        jp_ytd_health_sba=D(0), jp_month_pension_sba=D(0),
        slabs=[row for row in _bonus_slabs()
               if row.rule_type != content.JP_MIN_WAGE_RULE]))["jp_result"]
    assert result["jp_payment_kind"] == "BONUS"
    assert result["trace"]["labour"] is None
