"""Japan Phase 6: working-time classification, premium floor and minimum wage
(ZP-JP-ENG-001 S14). Every number here is synthetic."""
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.payroll.engine.countries import japan, japan_content as content
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
from app.modules.payroll.engine.jurisdictions.japan import labour


def D(value):
    return Decimal(str(value))


MONDAY = date(2026, 6, 1)


def _day(worked, scheduled=480, night=0, day_off=False, on=None, in_period=True):
    row = {"worked_minutes": worked, "scheduled_minutes": scheduled,
           "night_minutes": night, "statutory_day_off": day_off, "in_period": in_period}
    if on is not None:
        row["date"] = on
    return row


def _days(count, worked, start=MONDAY, **kw):
    return [_day(worked, on=start + timedelta(days=offset), **kw) for offset in range(count)]


def _ctx(**overrides):
    from tests.test_japan_engine import _context

    return _context(**overrides)


def _blocks(ctx, key):
    with pytest.raises(MissingComplianceConfigurationError) as exc:
        japan.calculate(ctx)
    assert exc.value.key == key
    return exc.value


def _signed_overtime(slabs):
    """Make the synthetic overtime component payable (WHT/SI/EI INCLUDED).

    The real content leaves overtime REVIEW until signed. Overtime pay stays
    EXCLUDED from its own premium base and from the minimum-wage wage.
    """
    out = []
    for row in slabs:
        if (row.rule_type == content.JP_EARNING_CLASS_RULE
                and row.filing_status == "OVERTIME"
                and row.tax_regime not in ("OT_BASE", "MIN_WAGE")):
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


def test_a_normal_month_has_no_overtime():
    # Regression: the weekly limit applies per week, never once per month.
    days, day = [], date(2026, 6, 1)
    while day.month == 6:
        if day.weekday() < 5:
            days.append(_day(480, on=day))
        day += timedelta(days=1)
    got = labour.classify_hours(days, 0, period_end=date(2026, 6, 30))
    assert got.ordinary_minutes == 22 * 480
    assert got.total_overtime_minutes == 0
    assert labour.premium_floor(D(1250), got) == 0


def test_daily_overtime_starts_above_eight_hours():
    got = labour.classify_hours([_day(600)])
    assert got.ordinary_minutes == 480
    assert got.statutory_overtime_minutes == 120
    assert got.scheduled_overtime_minutes == 0


def test_long_schedule_overtime_is_inside_the_schedule():
    got = labour.classify_hours([_day(540, scheduled=600)])
    assert got.ordinary_minutes == 480
    assert got.within_schedule_extra_minutes == 0
    assert got.statutory_overtime_minutes == 60
    assert got.scheduled_overtime_minutes == 60      # the salary already pays its base


def test_short_schedule_extra_and_daily_overtime_split():
    got = labour.classify_hours([_day(540, scheduled=420)])
    assert got.ordinary_minutes == 420
    assert got.within_schedule_extra_minutes == 60
    assert got.statutory_overtime_minutes == 60


def test_weekly_overtime_starts_above_forty_hours():
    got = labour.classify_hours(_days(6, 480))
    assert got.ordinary_minutes == 2400
    assert got.statutory_overtime_minutes == 480
    assert got.scheduled_overtime_minutes == 480     # the 6th scheduled day


def test_weekly_overtime_does_not_double_count_daily_overtime():
    got = labour.classify_hours(_days(5, 600))
    assert got.ordinary_minutes == 2400
    assert got.statutory_overtime_minutes == 600


def test_weekly_and_daily_overtime_combine():
    got = labour.classify_hours(_days(6, 600))
    assert got.ordinary_minutes == 2400
    assert got.statutory_overtime_minutes == 1200


def test_weekly_overtime_eats_extra_schedule_hours_first():
    got = labour.classify_hours(_days(6, 480, scheduled=360))
    assert got.ordinary_minutes == 2160
    assert got.within_schedule_extra_minutes == 240
    assert got.statutory_overtime_minutes == 480
    assert got.scheduled_overtime_minutes == 0


def test_two_weeks_are_assessed_separately():
    # 48h in week one and 32h in week two: 8h weekly overtime, not 0.
    days = _days(6, 480) + _days(4, 480, start=MONDAY + timedelta(days=7))
    got = labour.classify_hours(days)
    assert got.statutory_overtime_minutes == 480


def test_week_start_day_moves_the_week_boundary():
    # Wed..Mon, 6 days of 8h: one week if weeks start on Wednesday (2), two
    # weeks if they start on Monday (0).
    days = _days(6, 480, start=date(2026, 6, 3))
    assert labour.classify_hours(days, 2).statutory_overtime_minutes == 480
    assert labour.classify_hours(days, 0).statutory_overtime_minutes == 0


def test_week_ending_after_the_period_is_left_for_the_next_period():
    days = _days(6, 480, start=date(2026, 6, 29))           # Mon 29 Jun .. Sat 4 Jul
    in_june = [day for day in days if day["date"] <= date(2026, 6, 30)]
    got = labour.classify_hours(in_june, 0, period_end=date(2026, 6, 30))
    assert got.statutory_overtime_minutes == 0


def test_context_days_count_toward_the_week_but_not_the_period():
    june = [_day(480, on=date(2026, 6, 29), in_period=False),
            _day(480, on=date(2026, 6, 30), in_period=False)]
    july = _days(4, 480, start=date(2026, 7, 1))             # Wed..Sat
    got = labour.classify_hours(june + july, 0, period_end=date(2026, 7, 31))
    assert got.statutory_overtime_minutes == 480             # 48h in the week
    assert got.ordinary_minutes == 4 * 480 - 480             # only July's days


def test_over_sixty_hours_splits_the_higher_premium():
    got = labour.classify_hours(_days(7, 870))
    assert got.statutory_overtime_minutes == 3600
    assert got.over_60_minutes == 90
    assert got.total_worked_minutes == 6090


def test_statutory_day_off_hours_are_their_own_category():
    got = labour.classify_hours([_day(600, day_off=True)])
    assert got.statutory_holiday_minutes == 600
    assert got.ordinary_minutes == 0
    assert got.total_overtime_minutes == 0


def test_night_minutes_are_reported_separately():
    got = labour.classify_hours([_day(480, night=120)])
    assert got.ordinary_minutes == 480
    assert got.night_minutes == 120


def test_hours_hours_field_is_converted_to_minutes():
    got = labour.classify_hours([{"hours": "8", "scheduled_minutes": 480,
                                  "statutory_day_off": False}])
    assert got.ordinary_minutes == 480


@pytest.mark.parametrize("days,key", [
    ([_day(-1)], "jp_hours:worked_minutes"),
    ([_day(480), _day(480)], "jp_hours:date"),                               # undated
    ([_day(480, on=MONDAY), _day(480, on=MONDAY)], "jp_hours:date"),         # duplicated
    ([{"worked_minutes": 480, "scheduled_minutes": None, "statutory_day_off": False}],
     "jp_scheduled_weekdays"),
    ([{"worked_minutes": 480, "scheduled_minutes": 480}], "jp_statutory_day_off_weekday"),
    ([{"worked_minutes": 480, "scheduled_minutes": 480, "is_holiday": True}],
     "jp_statutory_day_off_weekday"),                                        # a holiday is not the day off
    ([dict(_day(480), public_holiday_policy_missing=True)], "jp_public_holidays_off"),
])
def test_missing_or_ambiguous_day_facts_block(days, key):
    with pytest.raises(labour.JapanLabourBlockedError) as exc:
        labour.classify_hours(days)
    assert exc.value.key == key


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


@pytest.mark.parametrize("days,floor", [
    ([_day(600)], "3125"),                      # 2h x 1,250 x 125%
    ([_day(480, day_off=True)], "13500"),       # 8h x 1,250 x 135%
    ([_day(480, night=120)], "625"),            # night premium only: 2h x 1,250 x 25%
    ([_day(600, night=120)], "3750"),           # overtime + night (engine blocks the combination)
    ([_day(540, scheduled=600)], "312.5"),      # overtime inside the schedule: premium only
    ([_day(480, scheduled=420)], "1250"),       # extra time within the limit: 100%, no premium
    (_days(6, 480), "2500"),                    # weekly overtime inside a 6-day schedule
])
def test_premium_floor(days, floor):
    assert labour.premium_floor(D(1250), labour.classify_hours(days)) == D(floor)


def test_premium_floor_for_over_sixty_hours():
    # 2,730 min outside the schedule at 100% + 3,600 min x 25% + 90 min x 50%.
    got = labour.premium_floor(D(1000), labour.classify_hours(_days(7, 870)))
    assert got == D(61250)


def test_premium_floor_is_exact_and_compared_strictly():
    floor = labour.premium_floor(D(1000), labour.classify_hours([_day(481)]))
    assert floor == D(1000) * D("1.25") / 60
    with pytest.raises(labour.JapanLabourBlockedError):
        labour.check_premium(D(20), floor)        # 20 < 20.83...
    labour.check_premium(D(21), floor)


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


def _with_class(slabs, obligation, component, treatment):
    out = []
    for row in slabs:
        if (row.rule_type == content.JP_EARNING_CLASS_RULE and row.tax_regime == obligation
                and row.filing_status == component):
            row = SimpleNamespace(**vars(row))
            row.assessment_basis = treatment
        out.append(row)
    return out


@pytest.mark.parametrize("obligation", ["OT_BASE", "MIN_WAGE"])
def test_overtime_pay_can_never_be_in_its_own_base(obligation):
    slabs = _with_class(_signed_overtime(_ctx().slabs), obligation, "OVERTIME", "INCLUDED")
    _blocks(_ctx(slabs=slabs), f"jp_earning_class:{obligation}:OVERTIME")


def test_premium_base_follows_the_signed_ot_base_class():
    # An allowance the OT_BASE class includes raises the hourly base; the
    # minimum-wage wage only counts what MIN_WAGE includes.
    slabs = _with_class(_ctx().slabs, "OT_BASE", "ALLOWANCE", "INCLUDED")
    for obligation in ("WHT", "SI", "EI", "MIN_WAGE"):
        slabs = _with_class(slabs, obligation, "ALLOWANCE", "EXCLUDED")
    result = japan.calculate(_ctx(slabs=slabs, gross=D(324000),
                                  jp_components={"ALLOWANCE": D(24000)}))["jp_result"]
    labour_trace = result["trace"]["labour"]
    assert D(labour_trace["hourlyBase"]) == D(1350)               # 324,000 / 240
    assert D(labour_trace["minimumWageHourly"]) == D(1250)        # 300,000 / 240


def test_unapproved_overtime_hours_block():
    _blocks(_ctx(jp_hours=[_day(600)], jp_hours_approved=False), "jp_hours_approved")


def test_paid_overtime_without_hours_blocks():
    _blocks(_ctx(gross=D(301000), basic=D(300000), overtime=D(1000),
                 slabs=_signed_overtime(_ctx().slabs),
                 jp_hours=[], jp_hours_approved=False), "jp_hours_approved")


def test_paid_overtime_below_the_floor_blocks():
    _blocks(_ctx(gross=D(303124), basic=D(300000), overtime=D(3124),
                 slabs=_signed_overtime(_ctx().slabs),
                 jp_hours=[_day(600)], jp_hours_approved=True), "jp_overtime_premium")


def test_approved_overtime_at_the_floor_passes_with_trace():
    result = japan.calculate(_ctx(
        gross=D(303125), basic=D(300000), overtime=D(3125),
        slabs=_signed_overtime(_ctx().slabs),
        jp_hours=[_day(600)], jp_hours_approved=True))["jp_result"]
    trace = result["trace"]["labour"]
    assert trace["premiumPaid"] == "3125"
    assert D(trace["premiumFloor"]) == D(3125)                     # 2h x 1,250 x 125%
    assert trace["hours"]["statutoryOvertimeMinutes"] == 120
    assert trace["hoursApproved"] is True


def test_statutory_day_off_premium_is_checked():
    _blocks(_ctx(gross=D(313499), basic=D(300000), overtime=D(13499),
                 slabs=_signed_overtime(_ctx().slabs),
                 jp_hours=[_day(480, day_off=True)], jp_hours_approved=True),
            "jp_overtime_premium")


def test_statutory_day_off_premium_at_the_floor_passes():
    result = japan.calculate(_ctx(
        gross=D(313500), basic=D(300000), overtime=D(13500),
        slabs=_signed_overtime(_ctx().slabs),
        jp_hours=[_day(480, day_off=True)], jp_hours_approved=True))["jp_result"]
    trace = result["trace"]["labour"]
    assert trace["hours"]["statutoryHolidayMinutes"] == 480
    assert D(trace["premiumFloor"]) == D(13500)                    # 8h x 1,250 x 135%


def test_night_minutes_come_from_the_signed_window_and_clock_pair():
    day = {"worked_minutes": 420, "scheduled_minutes": 480, "statutory_day_off": False,
           "check_in": "22:00", "check_out": "05:00"}
    result = japan.calculate(_ctx(
        gross=D(302188), basic=D(300000), overtime=D(2188),
        slabs=_signed_overtime(_ctx().slabs),
        jp_hours=[day], jp_hours_approved=True))["jp_result"]
    trace = result["trace"]["labour"]
    assert trace["nightWindow"] == "22:00-05:00"
    assert trace["hours"]["nightMinutes"] == 420
    assert D(trace["premiumFloor"]) == D("2187.5")                 # 7h x 1,250 x 25%


def test_two_premium_categories_need_the_signed_combination_rule():
    day = {"worked_minutes": 600, "scheduled_minutes": 480, "statutory_day_off": False,
           "night_minutes": 120}
    _blocks(_ctx(gross=D(305000), basic=D(300000), overtime=D(5000),
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
