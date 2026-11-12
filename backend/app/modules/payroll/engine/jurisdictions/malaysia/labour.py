"""Overtime by territory (ZP-MY-ENG-001 §9; MY-017).

Pure checks over the pay components and the approved overtime events — they
never add money on their own:

  * eligibility: a manual worker is always within the overtime provisions; a
    non-manual worker is within them only while the OT_RATE_BASE wage does not
    exceed the territory's signed exclusion wage. An excluded worker's
    overtime is contractual: it is traced, not verified;
  * every statutory overtime amount needs the event that created it
    (event_ref, day_type WORKDAY / REST_DAY / PUBLIC_HOLIDAY, hours,
    normal_daily_hours, date). The hourly ordinary rate follows the signed
    my_ot_rate_divisor_rule with the territory's signed days divisor; the
    multiplier is the territory's signed row for the day type;
  * a PUBLIC_HOLIDAY event must fall on a signed holiday of the worker's
    holiday state, and a REST_DAY event on the recorded rest day;
  * the same event never pays twice, and the OVERTIME component must equal
    the events' total (rounded upstream to the sen) — otherwise the LABOUR
    obligation is blocked.
"""
from __future__ import annotations

from decimal import Decimal

from app.modules.payroll.engine.countries import malaysia_content as content
from app.modules.payroll.engine.jurisdictions.malaysia import errors as E
from app.modules.payroll.engine.jurisdictions.malaysia import holidays as _holidays
from app.modules.payroll.engine.jurisdictions.malaysia.pack import ZERO, MyPack, as_date, dec, field, money, upper

_TOLERANCE = Decimal("0.01")     # event amounts arrive from time & attendance rounded to the sen
_WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def overtime(pack: MyPack, territory: str, holiday_state: str, rate_base, pay: dict, profile, events) -> dict:
    claimed = dec(pay.get("OVERTIME", ZERO))
    events = list(events or [])
    if not events:
        if claimed != ZERO:
            pack.block(E.OVERTIME_EVENTS_MISSING, "overtime pay needs the approved events that created it (MY-017)")
        return {"status": "NONE", "events": []}
    manual = field(profile, "manual_worker")
    if manual is None:
        pack.block(E.keyed(E.FACT_MISSING, "manual_worker"), "overtime eligibility needs the manual-worker fact")
    exclusion = pack.amount("my_ot_exclusion_wage", territory)
    rate_base = dec(rate_base)
    if not manual and rate_base > exclusion:
        return {"status": "CONTRACTUAL", "events": [field(e, "event_ref") for e in events],
                "reason": "non-manual worker above the territory's overtime exclusion wage", "territory": territory}
    pack.text("my_ot_rate_divisor_rule", content.OT_RATE_DIVISOR_RULES, territory)
    days = pack.amount("my_ot_rate_days_divisor", territory)
    if days <= ZERO:
        pack.block(E.keyed(E.ROW_MISSING, content.territory_key("my_ot_rate_days_divisor", territory)),
                   "the days divisor must be positive")
    calendar_by_year, seen, lines, expected = {}, set(), [], ZERO
    rest_day = upper(field(profile, "rest_day"))
    for event in events:
        ref = str(field(event, "event_ref") or "").strip()
        day_type = upper(field(event, "day_type"))
        hours, daily = dec(field(event, "hours")), dec(field(event, "normal_daily_hours"))
        on = as_date(field(event, "date"))
        if not ref or day_type not in content.OT_DAY_TYPES or hours <= ZERO or daily <= ZERO or on is None:
            pack.block(E.keyed(E.OVERTIME_EVENT_INVALID, ref or "NONE"),
                       "an overtime event needs a reference, day type, date, hours and normal daily hours")
        if ref in seen:
            pack.block(E.keyed(E.OVERTIME_DOUBLE_EVENT, ref), "the same overtime event cannot be paid twice")
        seen.add(ref)
        if day_type == "PUBLIC_HOLIDAY":
            if on.year not in calendar_by_year:
                calendar_by_year[on.year] = _holidays.calendar(pack, holiday_state, on.year)
            if on not in calendar_by_year[on.year]:
                pack.block(E.keyed(E.OVERTIME_EVENT_INVALID, ref),
                           f"{on.isoformat()} is not a signed public holiday for {holiday_state}")
        if day_type == "REST_DAY" and rest_day and _WEEKDAYS[on.weekday()] != rest_day:
            pack.block(E.keyed(E.OVERTIME_EVENT_INVALID, ref), "the event is not on the recorded rest day")
        multiplier = pack.amount(f"my_ot_multiplier_{day_type.lower()}", territory)
        hourly = rate_base / days / daily
        amount = hours * hourly * multiplier
        expected += amount
        lines.append({"eventRef": ref, "dayType": day_type, "date": on.isoformat(), "hours": str(hours),
                      "hourlyRate": money(hourly), "multiplier": str(multiplier), "amount": money(amount)})
    if abs(expected - claimed) >= _TOLERANCE:
        pack.block(E.OVERTIME_MISMATCH, "overtime pay does not equal the signed rate x multiplier of its events")
    return {"status": "MATCHED", "territory": territory, "events": lines, "expected": money(expected),
            "rateBase": money(rate_base)}

