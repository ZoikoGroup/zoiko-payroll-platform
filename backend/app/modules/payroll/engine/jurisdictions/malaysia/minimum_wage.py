"""Minimum wage (ZP-MY-ENG-001 §3 / §9; MY-018).

Tests the BASIC wage (MIN_WAGE_BASIC base, which never includes overtime or
bonuses) against the signed monthly minimum. Only the unambiguous case is
evaluated: a full calendar month, no unpaid leave, no hourly pay and the
territory's full statutory weekly hours. Anything else needs the daily /
hourly / part-time rules, which the specification does not give, and is
reported NOT_EVALUATED. Either outcome other than PASS is a run exception
that stops approval — never a silent pass.
"""
from __future__ import annotations

import calendar
from datetime import date

from app.modules.payroll.engine.jurisdictions.malaysia import errors as E
from app.modules.payroll.engine.jurisdictions.malaysia.pack import MyPack, dec, field, money, upper


def check(pack: MyPack, basic, pay: dict, profile, assignment, start: date, end: date, unpaid_days) -> dict:
    full_month = start.day == 1 and end == date(end.year, end.month, calendar.monthrange(end.year, end.month)[1]) \
        and start.month == end.month and start.year == end.year
    reasons = []
    if not full_month:
        reasons.append("part-month period")
    if dec(unpaid_days) > 0:
        reasons.append("unpaid leave in the period")
    if dec(pay.get("HOURLY_PAY", 0)) > 0:
        reasons.append("hourly pay")
    territory = upper(field(assignment, "labour_territory")) if assignment is not None else ""
    hours = field(profile, "normal_hours_week")
    if not territory:
        reasons.append("no work assignment (labour territory)")
    elif hours in (None, ""):
        reasons.append("normal weekly hours not recorded")
    elif dec(hours) < pack.amount("my_weekly_hours_max", territory):
        reasons.append("part-time hours")
    if reasons:
        return {"status": "NOT_EVALUATED", "reasons": reasons,
                "exception": {"code": E.EXC_MIN_WAGE_NOT_EVALUATED,
                              "detail": "minimum wage not evaluated: " + ", ".join(reasons)}}
    floor = pack.amount("my_min_wage_monthly")
    basic = dec(basic)
    status = "PASS" if basic >= floor else "BREACH"
    exception = None if status == "PASS" else {
        "code": E.EXC_MIN_WAGE_BREACH, "detail": f"basic wage {money(basic)} is below the monthly minimum"}
    return {"status": status, "basic": money(basic), "floor": money(floor), "territory": territory,
            "exception": exception}
