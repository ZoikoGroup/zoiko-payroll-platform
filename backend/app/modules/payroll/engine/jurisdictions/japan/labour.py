"""Japan working-time, premium and minimum-wage helpers (ZP-JP-ENG-001 S14).

Pure functions only: the service loads the facts, the engine calls these
helpers and converts a block into its own coded error. No statutory value is
inferred here - the premium rates, hours and minimum wage all arrive from
signed content rows.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from app.modules.payroll.engine.countries import japan_content as content

ZERO = Decimal("0")
MINUTES_PER_HOUR = Decimal("60")
DAILY_STATUTORY_MINUTES = 480
WEEKLY_STATUTORY_MINUTES = 2400
OVER_60_MINUTES = 3600

# Unit-test baselines only; the engine always passes the signed content rates.
# Each is the PREMIUM on top of the hourly base; an over-60 hour takes the
# over-60 premium instead of the statutory one, never both.
DEFAULT_PREMIUM_RATES = {
    "statutory": Decimal("0.25"),
    "over60": Decimal("0.50"),
    "holiday": Decimal("0.35"),
    "night": Decimal("0.25"),
}


class JapanLabourBlockedError(ValueError):
    def __init__(self, key: str, reason: str):
        self.key = key
        self.reason = reason
        super().__init__(f"{key}: {reason}")


@dataclass(frozen=True)
class DayHours:
    day: date | None = None
    worked_minutes: int = 0
    scheduled_minutes: int = 0
    night_minutes: int = 0
    statutory_day_off: bool = False
    in_period: bool = True


@dataclass(frozen=True)
class HoursBreakdown:
    """Minutes worked in the pay period, by statutory category.

    ``scheduled_overtime_minutes`` is the part of the statutory overtime
    (statutory + over-60) that falls inside the employee's own schedule: the
    salary already pays its base, so only the premium is owed on it.
    """
    ordinary_minutes: int = 0
    within_schedule_extra_minutes: int = 0
    statutory_overtime_minutes: int = 0
    over_60_minutes: int = 0
    statutory_holiday_minutes: int = 0
    night_minutes: int = 0
    scheduled_overtime_minutes: int = 0

    @property
    def total_worked_minutes(self) -> int:
        return (self.ordinary_minutes + self.within_schedule_extra_minutes
                + self.statutory_overtime_minutes + self.over_60_minutes
                + self.statutory_holiday_minutes)

    @property
    def total_overtime_minutes(self) -> int:
        return self.within_schedule_extra_minutes + self.statutory_overtime_minutes \
            + self.over_60_minutes

    def as_dict(self) -> dict:
        return {
            "ordinaryMinutes": self.ordinary_minutes,
            "withinScheduleExtraMinutes": self.within_schedule_extra_minutes,
            "statutoryOvertimeMinutes": self.statutory_overtime_minutes,
            "over60Minutes": self.over_60_minutes,
            "statutoryHolidayMinutes": self.statutory_holiday_minutes,
            "nightMinutes": self.night_minutes,
            "scheduledOvertimeMinutes": self.scheduled_overtime_minutes,
            "totalOvertimeMinutes": self.total_overtime_minutes,
        }


def _field(value, *names):
    for name in names:
        if isinstance(value, dict):
            if name in value:
                return value.get(name)
        elif hasattr(value, name):
            return getattr(value, name)
    return None


def _minutes(value, field: str, *, from_hours: bool = False) -> int:
    if value is None or value == "":
        return 0
    try:
        amount = Decimal(str(value))
    except Exception:
        raise JapanLabourBlockedError(f"jp_hours:{field}", f"{field} is not a number")
    if from_hours:
        amount *= MINUTES_PER_HOUR
    if amount < ZERO:
        raise JapanLabourBlockedError(f"jp_hours:{field}", f"{field} cannot be negative")
    return int(amount)


def _date(value):
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise JapanLabourBlockedError("jp_hours:date", f"attendance date {value!r} is not ISO")


def _day(raw) -> DayHours:
    """One attendance day. The service states the schedule and the statutory
    day off for the day; a fact it could not state is None and BLOCKS here."""
    worked = _field(raw, "worked_minutes", "workedMinutes", "minutes")
    source = "worked_minutes"
    if worked is None:
        worked = _field(raw, "hours")
        source = "hours"
    worked_minutes = _minutes(worked, source, from_hours=(source == "hours"))
    if _field(raw, "public_holiday_policy_missing") is True:
        raise JapanLabourBlockedError(
            "jp_public_holidays_off",
            "work on a national holiday, but the work rules do not record whether "
            "national holidays are days off")
    scheduled = _field(raw, "scheduled_minutes", "scheduledMinutes")
    if scheduled is None:
        raise JapanLabourBlockedError("jp_scheduled_weekdays",
                                      "the scheduled working days are not recorded")
    day_off = _field(raw, "statutory_day_off", "statutoryDayOff")
    if day_off is None:
        if _field(raw, "is_holiday", "isHoliday", "holiday") is not None:
            # A national holiday is not the statutory weekly day off; the
            # caller must state the day off itself.
            raise JapanLabourBlockedError(
                "jp_statutory_day_off_weekday",
                "a holiday flag is not a statutory day off; state statutory_day_off")
        raise JapanLabourBlockedError("jp_statutory_day_off_weekday",
                                      "the statutory weekly day off is not recorded")
    night = _minutes(_field(raw, "night_minutes", "nightMinutes"), "night_minutes")
    in_period = _field(raw, "in_period", "inPeriod")
    return DayHours(day=_date(_field(raw, "date", "day")), worked_minutes=worked_minutes,
                    scheduled_minutes=_minutes(scheduled, "scheduled_minutes"),
                    night_minutes=min(night, worked_minutes),
                    statutory_day_off=bool(day_off),
                    in_period=True if in_period is None else bool(in_period))


def _week_key(day: date | None, week_start_day: int):
    if day is None:
        return None
    return day - timedelta(days=(day.weekday() - week_start_day) % 7)


def classify_hours(days, week_start_day: int = 0, *,
                   daily_minutes: int = DAILY_STATUTORY_MINUTES,
                   weekly_minutes: int = WEEKLY_STATUTORY_MINUTES,
                   over60_minutes: int = OVER_60_MINUTES,
                   period_end: date | None = None) -> HoursBreakdown:
    """Classify the pay period's worked minutes into the statutory categories.

    * Daily: above ``daily_minutes`` is statutory overtime; up to it but
      beyond the day's schedule is extra time within the legal limit.
    * Weekly: days are grouped into weeks starting on ``week_start_day``
      (0 = Monday). Work on non-day-off days above ``weekly_minutes`` in a
      week, not already daily overtime, is statutory overtime.
    * A week that ends after ``period_end`` is not assessed weekly in this
      period; the next period loads its earlier days as context
      (``in_period`` False) and assesses it there. Context days count only
      toward their week's total, never toward this period's categories.
    * Statutory overtime above ``over60_minutes`` in the period is over-60.
    * Work on the statutory weekly day off is its own category, outside the
      daily and weekly limits. Night minutes are reported alongside.
    """
    if not isinstance(week_start_day, int) or not 0 <= week_start_day <= 6:
        raise JapanLabourBlockedError("jp_week_start_day",
                                      f"week start {week_start_day!r} is not 0..6")
    limits = (daily_minutes, weekly_minutes, over60_minutes)
    if any(not isinstance(value, int) or value <= 0 for value in limits):
        raise JapanLabourBlockedError(
            "jp_statutory_hours", f"statutory hour limits {limits!r} must be positive minutes")
    parsed = [_day(raw) for raw in (days or ())]
    if len(parsed) > 1 and any(day.day is None for day in parsed):
        raise JapanLabourBlockedError("jp_hours:date",
                                      "every attendance day needs its date to group weeks")
    dated = [day.day for day in parsed if day.day is not None]
    if len(dated) != len(set(dated)):
        raise JapanLabourBlockedError("jp_hours:date", "an attendance date appears twice")

    weeks = {}
    for day in parsed:
        weeks.setdefault(_week_key(day.day, week_start_day), []).append(day)

    ordinary = extra = statutory = scheduled_overtime = holiday = night = 0
    for key in sorted(weeks, key=lambda value: value or date.min):
        week_total = week_daily_overtime = 0
        week_ordinary = week_extra = 0
        for day in weeks[key]:
            if day.in_period:
                night += day.night_minutes
            if day.statutory_day_off:
                if day.in_period:
                    holiday += day.worked_minutes
                continue
            day_overtime = max(0, day.worked_minutes - daily_minutes)
            week_total += day.worked_minutes
            week_daily_overtime += day_overtime
            if not day.in_period:
                continue
            week_ordinary += min(day.worked_minutes, day.scheduled_minutes, daily_minutes)
            week_extra += max(0, min(day.worked_minutes, daily_minutes)
                              - min(day.scheduled_minutes, daily_minutes))
            statutory += day_overtime
            # Daily overtime the schedule itself covers (a schedule above 8h).
            scheduled_overtime += max(0, min(day.worked_minutes, day.scheduled_minutes)
                                      - daily_minutes)

        assess = key is None or period_end is None or key + timedelta(days=6) <= period_end
        weekly = max(0, week_total - weekly_minutes - week_daily_overtime) if assess else 0
        take = min(week_extra, weekly)
        week_extra -= take
        remaining = weekly - take
        take = min(week_ordinary, remaining)
        week_ordinary -= take
        scheduled_overtime += take
        remaining -= take
        if remaining:
            raise JapanLabourBlockedError(
                "jp_hours:weekly",
                f"weekly overtime for the week of {key} falls on days outside this period")
        statutory += weekly
        ordinary += week_ordinary
        extra += week_extra

    over_60 = max(0, statutory - over60_minutes)
    return HoursBreakdown(
        ordinary_minutes=ordinary,
        within_schedule_extra_minutes=extra,
        statutory_overtime_minutes=statutory - over_60,
        over_60_minutes=over_60,
        statutory_holiday_minutes=holiday,
        night_minutes=night,
        scheduled_overtime_minutes=scheduled_overtime,
    )


def premium_base_hourly(monthly_base, scheduled_monthly_hours) -> Decimal:
    try:
        base = Decimal(str(monthly_base or 0))
        hours = Decimal(str(scheduled_monthly_hours or 0))
    except Exception:
        raise JapanLabourBlockedError("jp_scheduled_monthly_hours",
                                      "monthly base or scheduled hours is not a number")
    if hours <= ZERO:
        raise JapanLabourBlockedError("jp_scheduled_monthly_hours",
                                      "scheduled monthly hours must be greater than zero")
    if base < ZERO:
        raise JapanLabourBlockedError("jp_premium_base", "the premium base cannot be negative")
    return base / hours


def premium_floor(hourly, breakdown: HoursBreakdown, rates: dict | None = None) -> Decimal:
    """The least the OVERTIME pay may be for the period (S14).

    OVERTIME is all pay for time outside the schedule plus every statutory
    premium; the salary pays the scheduled time. So the floor is:
      * extra time within the legal limit      x 100% (no statutory premium);
      * statutory overtime outside the schedule x (100% + premium);
      * statutory overtime inside the schedule  x premium only;
      * the statutory day off                   x (100% + day-off premium);
      * night time                              x night premium only.
    Over-60 minutes take the over-60 premium instead of the statutory one.
    Exact: no rounding rule is applied here (none is signed); the comparison
    is strict.
    """
    rates = dict(DEFAULT_PREMIUM_RATES, **(rates or {}))
    hourly = Decimal(str(hourly or 0))
    overtime = breakdown.statutory_overtime_minutes + breakdown.over_60_minutes
    unpaid_base = (breakdown.within_schedule_extra_minutes
                   + max(0, overtime - breakdown.scheduled_overtime_minutes)
                   + breakdown.statutory_holiday_minutes)
    premium = (breakdown.statutory_overtime_minutes * rates["statutory"]
               + breakdown.over_60_minutes * rates["over60"]
               + breakdown.statutory_holiday_minutes * rates["holiday"]
               + breakdown.night_minutes * rates["night"])
    return (Decimal(unpaid_base) + premium) / MINUTES_PER_HOUR * hourly


def check_premium(paid, floor, key: str = "jp_overtime_premium") -> None:
    paid = Decimal(str(paid or 0))
    floor = Decimal(str(floor or 0))
    if paid < floor:
        raise JapanLabourBlockedError(
            key, f"paid overtime {paid} is below the statutory minimum "
                 f"{floor.quantize(Decimal('0.01'), rounding=ROUND_CEILING)}")


def _in_force(row, as_of: date) -> bool:
    start = _field(row, "effective_from")
    end = _field(row, "effective_to")
    if start is not None and as_of < start:
        return False
    if end is not None and as_of > end:
        return False
    return True


def minimum_wage_row(rows, prefecture: str, as_of: date):
    """The one minimum-wage row in force for a prefecture on a date.

    A missing row or two rows starting on the same day blocks: neither the
    announced future rate nor an arbitrary tie-break may be used.
    """
    candidates = []
    for row in rows or ():
        if str(_field(row, "rule_type") or "").upper() != content.JP_MIN_WAGE_RULE:
            continue
        state = _field(row, "jurisdiction_state")
        if state is not None and str(state) != str(prefecture):
            continue
        if not _in_force(row, as_of):
            continue
        candidates.append(row)
    if not candidates:
        return None
    latest = max(_field(row, "effective_from") or date.min for row in candidates)
    same = [row for row in candidates
            if (_field(row, "effective_from") or date.min) == latest]
    if len(same) > 1:
        raise JapanLabourBlockedError(
            "jp_minimum_wage",
            f"{len(same)} minimum-wage rows start on {latest} for prefecture {prefecture}")
    return same[0]


def minimum_wage_check(hourly, minimum, prefecture: str) -> Decimal:
    if minimum is None:
        raise JapanLabourBlockedError(
            "jp_minimum_wage",
            f"no minimum-wage row is in force for prefecture {prefecture}")
    minimum = Decimal(str(minimum))
    if minimum <= ZERO:
        raise JapanLabourBlockedError(
            "jp_minimum_wage",
            f"minimum-wage row for prefecture {prefecture} has no positive hourly amount")
    hourly = Decimal(str(hourly or 0))
    if hourly < minimum:
        raise JapanLabourBlockedError(
            f"jp_minimum_wage:{prefecture}",
            f"hourly wage {hourly.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)} "
            f"is below the prefectural minimum {minimum}")
    return minimum


def holidays_for_year(rows, year: int) -> list[dict]:
    """Dated statutory holidays for one year, straight from signed rows."""
    out = []
    for row in rows or ():
        if str(_field(row, "rule_type") or "").upper() != content.JP_HOLIDAY_RULE:
            continue
        day = _field(row, "holiday_date", "date", "effective_from")
        if isinstance(day, str):
            try:
                day = date.fromisoformat(day[:10])
            except ValueError:
                continue
        if not isinstance(day, date) or day.year != year:
            continue
        name = _field(row, "rate_label", "name") or "Statutory holiday"
        out.append({"date": day.isoformat(), "name": str(name)})
    return sorted(out, key=lambda item: (item["date"], item["name"]))


def _clock(value) -> time | None:
    if value in (None, ""):
        return None
    text = str(value)[:5]
    try:
        hour, minute = text.split(":")
        return time(int(hour), int(minute))
    except (TypeError, ValueError):
        return None


def night_minutes(check_in, check_out, window_start="22:00", window_end="05:00") -> int:
    """Minutes of a shift inside the night window, including a crossing shift.

    A missing or invalid clock pair returns 0 rather than guessing a break.
    """
    start, end = _clock(check_in), _clock(check_out)
    win_start, win_end = _clock(window_start), _clock(window_end)
    if start is None or end is None or win_start is None or win_end is None:
        return 0

    def mins(t: time) -> int:
        return t.hour * 60 + t.minute

    start_m, end_m = mins(start), mins(end)
    if end_m <= start_m:
        end_m += 24 * 60
    windows = [(mins(win_start), 24 * 60), (24 * 60, 24 * 60 + mins(win_end))]
    total = 0
    for w_start, w_end in windows:
        total += max(0, min(end_m, w_end) - max(start_m, w_start))
    return total
