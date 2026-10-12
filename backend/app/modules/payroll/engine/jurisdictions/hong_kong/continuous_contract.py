"""Hong Kong Employment Ordinance "continuous contract" resolver
(ZP-HK-ENG-001 §9, HK-005, HK-015; Labour Department Concise Guide ch.1, S6).

Two effective-dated algorithms (HK-015), chosen PER WEEK by the week's own
dates — the amendment has no retrospective effect:

  * weeks before the effective date (18 Jan 2026): "4-18" — employed
    continuously for 4 weeks or more and at least 18 hours in each week;
  * weeks on/after it: "4-week 17/68" — employed continuously for 4 weeks or
    more and either at least 17 hours in each week, or (where fewer than 17
    hours in a week) 68 hours or more in the four-week period comprising that
    week and the three weeks next preceding it, during which the employee
    was employed by the same employer.

The thresholds, the effective date and the week start are pack rows (never
constants here). Continuity is replayed from the preserved daily hours
(HK-005/HK-016) for ANY benefit date: a week that fails its test breaks the
contract, and qualification restarts from the following week.

Evidence per week: VERIFIED (recorded hours), CONTRACTUAL (no record — the
recorded contractual weekly hours are used and flagged), MISSING (neither →
the status is UNDETERMINED, never assumed continuous). A partial first week
(employment starting mid-week) is counted toward the 68-hour windows but not
failed on its own — disclosed in the trace (G1 certification item). During the
first `eo_cc_468_first_weeks` weeks of a NEW employment the 68-hour alternative
is unavailable and the weekly 17-hour test alone can be met (LD Education Tool
on the New "Continuous Contract" Requirement, Note 1).
"""

from datetime import date, timedelta
from decimal import Decimal

from app.modules.payroll.engine.jurisdictions.hong_kong.common import (
    HongKongCalculationBlockedError, ZERO, dec, rate_value, row_ref, text_value,
)

_WEEKDAYS = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")


def parameters(rate_map: dict) -> dict:
    values, refs = {}, {}
    for key in ("eo_cc_legacy_weekly_hours", "eo_cc_weekly_hours", "eo_cc_four_week_hours", "eo_cc_min_weeks",
                "eo_cc_468_first_weeks"):
        values[key], row = rate_value(rate_map, key)
        refs[key] = row_ref(row)
    effective, row = text_value(rate_map, "eo_cc_468_effective_date")
    values["effective_date"] = date.fromisoformat(effective)
    refs["eo_cc_468_effective_date"] = row_ref(row)
    week_start, row = text_value(rate_map, "eo_week_start_day")
    if week_start not in _WEEKDAYS:
        raise HongKongCalculationBlockedError("eo_week_start_day", f"invalid week start {week_start!r}")
    values["week_start"] = _WEEKDAYS.index(week_start)
    refs["eo_week_start_day"] = row_ref(row)
    return {"values": values, "refs": refs}


def _week_start_on_or_before(d: date, week_start: int) -> date:
    return d - timedelta(days=(d.weekday() - week_start) % 7)


def weeks_between(start: date, end: date, week_start: int) -> list:
    """Statutory weeks overlapping [start, end] as (week_start, week_end)."""
    out, ws = [], _week_start_on_or_before(start, week_start)
    while ws <= end:
        out.append((ws, ws + timedelta(days=6)))
        ws += timedelta(days=7)
    return out


def _week_hours(ws: date, we: date, employed_from: date, hours_by_day: dict, contractual):
    days = [ws + timedelta(days=i) for i in range(7)]
    employed_days = [d for d in days if d >= employed_from]
    recorded = [d for d in employed_days if d.isoformat() in hours_by_day]
    if recorded:
        return sum((dec(hours_by_day[d.isoformat()]) for d in employed_days if d.isoformat() in hours_by_day), ZERO), "VERIFIED"
    if contractual is not None:
        return dec(contractual), "CONTRACTUAL"
    return None, "MISSING"


def resolve(employment_start: date, as_of: date, hours_by_day: dict, params: dict,
            contractual_weekly_hours=None) -> dict:
    """Continuous-contract status on `as_of` (a benefit / reference date).

    Returns {status: CONTINUOUS | NOT_CONTINUOUS | UNDETERMINED,
             continuousSince, weeksOfContinuity, weeks: [...]}. Only COMPLETE
    weeks up to `as_of` are evaluated."""
    v = params["values"]
    hours_by_day = hours_by_day or {}
    legacy_h, new_h = v["eo_cc_legacy_weekly_hours"], v["eo_cc_weekly_hours"]
    window_h, min_weeks = v["eo_cc_four_week_hours"], int(v["eo_cc_min_weeks"])
    weeks = [w for w in weeks_between(employment_start, as_of, v["week_start"]) if w[1] <= as_of]
    rows, streak_start, streak_weeks, undetermined = [], None, 0, False
    history = []    # (hours or None) per evaluated week, for 4-week windows
    for ws, we in weeks:
        hours, basis = _week_hours(ws, we, employment_start, hours_by_day, contractual_weekly_hours)
        partial = ws < employment_start
        history.append(hours)
        rule = "4_18" if we < v["effective_date"] else "4_WEEK_17_68"
        row = {"weekStart": ws.isoformat(), "weekEnd": we.isoformat(), "hours": None if hours is None else str(hours),
               "evidence": basis, "rule": rule, "partialWeek": partial}
        if hours is None:
            row["result"], undetermined = "MISSING_HOURS", True
            streak_start, streak_weeks = None, 0
            rows.append(row)
            continue
        if rule == "4_18":
            ok = hours >= legacy_h
            row["test"] = f"≥{legacy_h}h in the week"
        elif hours >= new_h:
            ok = True
            row["test"] = f"≥{new_h}h in the week"
        else:
            weeks_of_employment = weeks.index((ws, we)) + 1
            if weeks_of_employment <= int(v["eo_cc_468_first_weeks"]):
                # LD Education Tool, Note 1: the employee must have been employed
                # by this employer throughout the four-week period, so the
                # alternative test is unavailable in the first weeks of a NEW
                # employment — the 17-hours-each-week test alone can be met.
                ok = False
                row["fourWeekHours"] = f"468 rule unavailable — week {weeks_of_employment} of the new employment"
            else:
                window = history[-4:]
                if len(window) < 4:
                    ok = False
                    row["fourWeekHours"] = f"only {len(window)} week(s) of employment"
                elif any(h is None for h in window):
                    ok = None
                else:
                    total = sum(window, ZERO)
                    ok = total >= window_h
                    row["fourWeekHours"] = str(total)
            row["test"] = f"<{new_h}h — 4-week window ≥{window_h}h"
        if partial and not ok:
            ok, row["test"] = True, "partial first week — not failed on its own (disclosed)"
        if ok is None:
            row["result"], undetermined = "WINDOW_INCOMPLETE", True
            streak_start, streak_weeks = None, 0
        elif ok:
            row["result"] = "MET"
            if streak_start is None:
                streak_start = max(ws, employment_start)
            streak_weeks += 1
        else:
            row["result"] = "NOT_MET"
            streak_start, streak_weeks = None, 0
        rows.append(row)

    if streak_weeks >= min_weeks and not (undetermined and streak_start is None):
        status = "CONTINUOUS"
    elif undetermined and streak_start is None:
        status = "UNDETERMINED"
    else:
        status = "NOT_CONTINUOUS"
    return {
        "status": status, "asOf": as_of.isoformat(),
        "continuousSince": streak_start.isoformat() if streak_start and status == "CONTINUOUS" else None,
        "weeksOfContinuity": streak_weeks, "weeks": rows,
        "rules": {"legacyWeeklyHours": str(legacy_h), "weeklyHours": str(new_h), "fourWeekHours": str(window_h),
                  "effectiveDate": v["effective_date"].isoformat(),
                  "newEmploymentWeeksWithout468Rule": int(v["eo_cc_468_first_weeks"]), "refs": params["refs"]},
    }


def continuous_for_at_least(result: dict, as_of: date, weeks: int = None, months: int = None) -> bool:
    """Has the CURRENT continuous contract lasted ≥ N weeks / months at as_of?
    (e.g. holiday pay: 3 months immediately preceding; maternity / paternity
    pay: 40 weeks immediately before)."""
    if result["status"] != "CONTINUOUS" or not result.get("continuousSince"):
        return False
    since = date.fromisoformat(result["continuousSince"])
    if weeks is not None:
        return (as_of - since).days >= weeks * 7
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import add_months
    return add_months(since, months) <= as_of
