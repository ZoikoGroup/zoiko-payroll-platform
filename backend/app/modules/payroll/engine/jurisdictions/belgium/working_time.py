"""Belgium working time and overtime (ZP-BE-ENG-001 §7, BE-022 / BE-023;
Block B1). Pure.

* Overtime is measured against the GOVERNING schedule of the employment line
  (BE-022): EFFECTIVE regime — hours above the schedule's weekly hours in each
  ISO week; AVERAGE regime — hours above weekly hours x the ISO weeks the facts
  cover (the average over the reference period). Daily / weekly statutory limits
  (be_wt_daily_limit_hours / be_wt_weekly_limit_hours) are checked; a breach is
  an exception, never a silent cap.
* Overtime on a Sunday or a public holiday (signed BE_PUBLIC_HOLIDAY rows plus
  the employer's recorded substitute days, D15) uses the Sunday / holiday
  premium; other overtime the weekday premium. Premiums come from signed rows
  (be_ot_premium_*) unless the Joint Committee agreement overrides them
  (modules["overtime"], sector override).
* Compensatory rest earned is the signed formula be_ot_compensatory_rest_rule;
  earned and taken rest are LEDGER FACTS (COMPENSATORY_REST_HOURS), as are the
  overtime hours (OVERTIME_HOURS).
* The overtime premium is verified against the hourly rate when one is known;
  otherwise it is an exception. Paid overtime with no working-time facts blocks
  (the premium cannot be grounded).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from app.modules.payroll.engine.jurisdictions.belgium import errors as E
from app.modules.payroll.engine.jurisdictions.belgium.pack import ZERO, BePack, as_date, dec, field, upper

_PERCENT = Decimal("100")
_SUNDAY = 6                       # date.weekday() of a Sunday (calendar fact)


def _holiday_dates(pack: BePack, days: list, substitute_days) -> set:
    years = sorted({d.year for d in days})
    out = set()
    for year in years:
        out |= {when for when, _name in pack.public_holidays(year)}
    out |= {as_date(d) for d in (substitute_days or [])}
    return out


def _premiums(pack: BePack, agreement) -> dict:
    modules = field(agreement, "modules") if agreement is not None else None
    override = modules.get("overtime") if isinstance(modules, dict) else None
    if isinstance(override, dict) and override.get("weekdayPct") not in (None, "") \
            and override.get("sundayHolidayPct") not in (None, ""):
        return {"source": "SECTOR", "weekday": dec(override["weekdayPct"]),
                "sundayHoliday": dec(override["sundayHolidayPct"])}
    return {"source": "CONTENT", "weekday": pack.pct("be_ot_premium_weekday", "employee"),
            "sundayHoliday": pack.pct("be_ot_premium_sunday_holiday", "employee")}


def compute_be_working_time(pack: BePack, schedule: Optional[dict], facts: Optional[dict], agreement,
                            paid_premium: Decimal, hourly_rate, period_start: Optional[date]) -> dict:
    days = sorted((as_date(d.get("date")), dec(d.get("hours"))) for d in ((facts or {}).get("days") or [])
                  if d.get("date") is not None)
    if not days:
        if paid_premium > ZERO:
            pack.block(E.OVERTIME_FACTS_MISSING, "OVERTIME_PREMIUM",
                       "overtime pay without working-time facts cannot be grounded (BE-022)")
        return {"overtimeHours": ZERO, "restEarned": ZERO, "restTaken": dec((facts or {}).get("restTakenHours")),
                "exceptions": [], "trace": {"facts": False}}
    if schedule is None or schedule.get("weeklyHours") in (None, ""):
        pack.block(E.SCHEDULE_MISSING, "working_time", "overtime needs the governing schedule (BE-022)")
    weekly_hours = dec(schedule["weeklyHours"])
    regime = upper(schedule.get("regime"))
    daily_limit = pack.amount("be_wt_daily_limit_hours")
    weekly_limit = pack.amount("be_wt_weekly_limit_hours")
    pack.text("be_ot_threshold_rule")                              # signed acknowledgement (recorded in used rows)
    holidays = _holiday_dates(pack, [d for d, _h in days], (facts or {}).get("substituteDays"))

    exceptions = []
    weeks = defaultdict(lambda: {"hours": ZERO, "special": ZERO})
    for day, hours in days:
        if hours > daily_limit:
            exceptions.append({"code": E.WORKING_TIME_LIMIT, "detail": f"{day.isoformat()}: daily limit exceeded"})
        week = day - timedelta(days=day.weekday())
        weeks[week]["hours"] += hours
        if day.weekday() == _SUNDAY or day in holidays:
            weeks[week]["special"] += hours
    for week, totals in sorted(weeks.items()):
        if totals["hours"] > weekly_limit:
            exceptions.append({"code": E.WORKING_TIME_LIMIT, "detail": f"week of {week.isoformat()}: weekly limit "
                                                                       "exceeded"})
    overtime_weekday, overtime_special = ZERO, ZERO
    if regime == "AVERAGE":
        # The average over the weeks the facts cover: weekly hours x weeks.
        total = sum((t["hours"] for t in weeks.values()), ZERO)
        expected = weekly_hours * Decimal(len(weeks))
        excess = max(ZERO, total - expected)
        special_total = sum((t["special"] for t in weeks.values()), ZERO)
        overtime_special = min(excess, special_total)
        overtime_weekday = excess - overtime_special
    else:
        for totals in weeks.values():
            excess = max(ZERO, totals["hours"] - weekly_hours)
            special = min(excess, totals["special"])
            overtime_special += special
            overtime_weekday += excess - special
    overtime = overtime_weekday + overtime_special
    premiums = _premiums(pack, agreement) if overtime > ZERO else None
    rest_earned = (max(ZERO, pack.formula("be_ot_compensatory_rest_rule", overtime=overtime))
                   if overtime > ZERO else ZERO)
    expected_premium = None
    if overtime > ZERO:
        if hourly_rate in (None, ""):
            exceptions.append({"code": E.OVERTIME_PREMIUM_UNVERIFIED,
                               "detail": "the hourly rate is not known, so the overtime premium cannot be checked"})
        else:
            rate = dec(hourly_rate)
            expected_premium = (overtime_weekday * rate * premiums["weekday"] / _PERCENT
                                + overtime_special * rate * premiums["sundayHoliday"] / _PERCENT)
            if paid_premium < expected_premium:
                exceptions.append({"code": E.OVERTIME_PREMIUM_SHORT,
                                   "detail": "the overtime premium paid is below the premium due"})
    trace = {"facts": True, "regime": regime, "weeklyHours": str(weekly_hours),
             "overtimeWeekday": str(overtime_weekday), "overtimeSundayHoliday": str(overtime_special),
             "premiums": None if premiums is None else {k: str(v) for k, v in premiums.items()},
             "expectedPremium": None if expected_premium is None else str(expected_premium),
             "restEarned": str(rest_earned), "holidayDates": sorted(d.isoformat() for d in holidays)}
    return {"overtimeHours": overtime, "restEarned": rest_earned,
            "restTaken": dec((facts or {}).get("restTakenHours")), "exceptions": exceptions, "trace": trace}
