"""Japan working-time, premium and minimum-wage helpers (ZP-JP-ENG-001 S14).

Pure functions only: the service loads the facts, the engine calls these
helpers and converts a block into its own coded error. No statutory value is
inferred here - the premium rates, hours and minimum wage all arrive from
signed content rows.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal, ROUND_HALF_UP

from app.modules.payroll.engine.countries import japan_content as content

ZERO = Decimal("0")
MINUTES_PER_HOUR = Decimal("60")
DAILY_STATUTORY_MINUTES = 480
WEEKLY_STATUTORY_MINUTES = 2400
OVER_60_MINUTES = 3600

DEFAULT_PREMIUM_RATES = {
    "within_schedule": Decimal("0.25"),
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
    worked_minutes: int = 0
    scheduled_minutes: int = 0
    night_minutes: int = 0
    is_holiday: bool = False


@dataclass(frozen=True)
class HoursBreakdown:
    ordinary_minutes: int = 0
    within_schedule_extra_minutes: int = 0
    statutory_overtime_minutes: int = 0
    over_60_minutes: int = 0
    statutory_holiday_minutes: int = 0
    night_minutes: int = 0

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


def _day(day) -> DayHours:
    worked = _field(day, "worked_minutes", "workedMinutes", "minutes")
    source = "worked_minutes"
    if worked is None:
        worked = _field(day, "hours")
        source = "hours"
    worked_minutes = _minutes(worked, source, from_hours=(source == "hours"))
    scheduled = _minutes(_field(day, "scheduled_minutes", "scheduledMinutes"), "scheduled_minutes")
    night = _minutes(_field(day, "night_minutes", "nightMinutes"), "night_minutes")
    holiday = _field(day, "is_holiday", "isHoliday", "holiday")
    return DayHours(worked_minutes=worked_minutes, scheduled_minutes=scheduled,
                    night_minutes=min(night, worked_minutes), is_holiday=bool(holiday))


def classify_hours(days, week_start_day: int = 0, *,
                   daily_minutes: int = DAILY_STATUTORY_MINUTES,
                   weekly_minutes: int = WEEKLY_STATUTORY_MINUTES,
                   over60_minutes: int = OVER_60_MINUTES) -> HoursBreakdown:
    """Classify worked minutes into the statutory categories the spec names.

    The daily/weekly/threshold limits are passed in from signed content rows;
    the defaults are only unit-test baselines. Daily overtime starts above
    ``daily_minutes`` even when the schedule is longer. Weekly overtime starts
    above ``weekly_minutes`` of non-holiday work and never counts the daily
    overtime twice. Night minutes are reported separately; the combination
    policy is signed at G1, so the engine refuses to add them by assumption.
    """
    if not isinstance(week_start_day, int) or not 0 <= week_start_day <= 6:
        raise JapanLabourBlockedError("jp_week_start_day",
                                      f"week start {week_start_day!r} is not 0..6")
    limits = (daily_minutes, weekly_minutes, over60_minutes)
    if any(not isinstance(value, int) or value <= 0 for value in limits):
        raise JapanLabourBlockedError(
            "jp_statutory_hours", f"statutory hour limits {limits!r} must be positive minutes")
    ordinary = extra = daily_overtime = holiday = night = 0
    non_holiday_total = 0
    for raw in days or ():
        day = _day(raw)
        night += day.night_minutes
        if day.is_holiday:
            holiday += day.worked_minutes
            continue
        non_holiday_total += day.worked_minutes
        ordinary += min(day.worked_minutes, day.scheduled_minutes, daily_minutes)
        extra += max(0, min(day.worked_minutes, daily_minutes)
                     - min(day.scheduled_minutes, daily_minutes))
        daily_overtime += max(0, day.worked_minutes - daily_minutes)

    weekly_overtime = max(0, non_holiday_total - weekly_minutes - daily_overtime)
    remaining = weekly_overtime
    take = min(extra, remaining)
    extra -= take
    remaining -= take
    take = min(ordinary, remaining)
    ordinary -= take
    remaining -= take
    if remaining:
        raise JapanLabourBlockedError(
            "jp_hours:weekly", "weekly overtime does not reconcile with the daily hours")

    statutory = daily_overtime + weekly_overtime
    over_60 = max(0, statutory - over60_minutes)
    statutory = min(statutory, over60_minutes)
    return HoursBreakdown(
        ordinary_minutes=ordinary,
        within_schedule_extra_minutes=extra,
        statutory_overtime_minutes=statutory,
        over_60_minutes=over_60,
        statutory_holiday_minutes=holiday,
        night_minutes=night,
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
    rates = dict(DEFAULT_PREMIUM_RATES, **(rates or {}))
    hourly = Decimal(str(hourly or 0))
    premium_minutes = (
        breakdown.within_schedule_extra_minutes * rates["within_schedule"]
        + breakdown.statutory_overtime_minutes * rates["statutory"]
        + breakdown.over_60_minutes * rates["over60"]
        + breakdown.statutory_holiday_minutes * rates["holiday"]
        + breakdown.night_minutes * rates["night"]
    )
    return (premium_minutes / MINUTES_PER_HOUR * hourly).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)


def check_premium(paid, floor, key: str = "jp_overtime_premium") -> None:
    paid = Decimal(str(paid or 0))
    floor = Decimal(str(floor or 0))
    if paid < floor:
        raise JapanLabourBlockedError(
            key, f"paid premium {paid} is below the statutory minimum {floor}")


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
