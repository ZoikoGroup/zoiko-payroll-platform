"""Holidays Act 2003 — entitlement side (spec "Holidays Act", NZ-016; Phase 5). Pure.

Entitlements are LEGAL quantities: annual holidays in WEEKS vesting on each
anniversary, sick / family-violence leave in DAYS vesting on the qualifying
date and every year after, bereavement per event. Nothing here is an hours
accrual and nothing is pro-rated. Every number (weeks, days, months, carry
cap) is read from the pack's nz_hol_* rows; an unsigned row blocks.

Pay for leave and public holidays (OWP / AWE / RDP / ADP, time-and-a-half)
is Phase 6. Family-violence identity never appears in any step.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field as dc_field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from zoneinfo import ZoneInfo

from app.modules.payroll.engine.countries import new_zealand_content as content
from . import errors as E
from .pack import CENT, ZERO, NzPack, as_date, dec, field, upper

LEAVE_TYPES = ("ANNUAL", "SICK", "BEREAVEMENT_CLOSE", "BEREAVEMENT_OTHER", "FAMILY_VIOLENCE", "ALTERNATIVE")
OWD_YES, OWD_NO, OWD_UNDETERMINED = "YES", "NO", "UNDETERMINED"
WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
TIMEZONES = ("Pacific/Auckland", "Pacific/Chatham")
WEEKS, DAYS = "WEEKS", "DAYS"
_SECONDS_PER_HOUR = Decimal(3600)


@dataclass
class Vest:
    leave_type: str
    qualifying_date: date
    entitlement_date: date
    unit: str
    quantity: Decimal
    carried_in: Decimal = ZERO
    expires_on: Optional[date] = None
    steps: list = dc_field(default_factory=list)


# ── calendar helpers (calendar arithmetic, not statutory content) ──────────
def add_months(d: date, months: int) -> date:
    """Calendar-safe: 29 Feb + 12 months -> 28 Feb in a non-leap year."""
    total = d.month - 1 + months
    year, month = d.year + total // 12, total % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _months(pack: NzPack, key: str) -> int:
    value = pack.amount(key)
    if value != value.to_integral_value() or value <= ZERO:
        pack.block(E.keyed(E.ROW_MISSING, key), "the qualifying period must be a whole number of months")
    return int(value)


def _yearly_from(first: date, as_of: date) -> list:
    """first, first + 1 year, ... up to and including as_of (each from `first`
    so a 29-Feb anchor keeps returning to 29 Feb in leap years)."""
    out, k = [], 0
    while True:
        on = add_months(first, 12 * k)
        if on > as_of:
            return out
        out.append(on)
        k += 1


# ── vesting ─────────────────────────────────────────────────────────────────
def annual_vests(anchor: date, as_of: date, already, pack: NzPack) -> list:
    """Annual holidays: the stated number of WEEKS after each completed
    qualifying period of continuous employment (each anniversary)."""
    weeks = pack.amount("nz_hol_annual_weeks")
    months = _months(pack, "nz_hol_annual_qualifying_months")
    already = {as_date(d) for d in already or ()}
    out, k = [], 1
    while True:
        on = add_months(anchor, months * k)
        if on > as_of:
            return out
        if on not in already:
            out.append(Vest("ANNUAL", on, on, WEEKS, weeks, steps=[
                {"step": "annual", "anchor": anchor.isoformat(), "anniversary": on.isoformat(),
                 "keys": ["nz_hol_annual_weeks", "nz_hol_annual_qualifying_months"], "weeks": str(weeks)}]))
        k += 1


def _remaining(row) -> Decimal:
    return (dec(field(row, "quantity")) + dec(field(row, "carried_in"))
            - dec(field(row, "taken")) - dec(field(row, "paid_out")))


def sick_vests(anchor: date, as_of: date, existing, pack: NzPack) -> list:
    """Sick leave: the stated days on the qualifying date and every year
    after, never pro-rated. The unused balance carries into the new year so
    that carried + new never exceeds the carry maximum. `existing` = the SICK
    rows already vested for this employment (dicts or rows)."""
    days = pack.amount("nz_hol_sick_days")
    cap = pack.amount("nz_hol_sick_carry_max")
    qualify = add_months(anchor, _months(pack, "nz_hol_sick_qualifying_months"))
    by_date = {as_date(field(r, "entitlement_date")): r for r in existing or ()}
    out, prior = [], None
    for on in _yearly_from(qualify, as_of):
        if on in by_date:
            prior = by_date[on]
            continue
        carried = ZERO
        if prior is not None:
            carried = max(ZERO, min(_remaining(prior), cap - days))
        vest = Vest("SICK", qualify, on, DAYS, days, carried_in=carried, steps=[
            {"step": "sick", "qualifyingDate": qualify.isoformat(), "entitlementDate": on.isoformat(),
             "keys": ["nz_hol_sick_days", "nz_hol_sick_qualifying_months", "nz_hol_sick_carry_max"],
             "days": str(days), "carriedIn": str(carried)}])
        out.append(vest)
        prior = {"quantity": vest.quantity, "carried_in": vest.carried_in, "taken": ZERO, "paid_out": ZERO}
    return out


def family_violence_vests(anchor: date, as_of: date, already, pack: NzPack) -> list:
    """Family-violence leave: the stated days on the same qualifying date and
    yearly cadence as sick leave (the spec states no separate period), with
    NO carry-over. Steps name only the content keys used."""
    days = pack.amount("nz_hol_family_violence_days")
    qualify = add_months(anchor, _months(pack, "nz_hol_sick_qualifying_months"))
    already = {as_date(d) for d in already or ()}
    return [Vest("FAMILY_VIOLENCE", qualify, on, DAYS, days, steps=[
                {"step": "restricted", "keys": ["nz_hol_family_violence_days", "nz_hol_sick_qualifying_months"]}])
            for on in _yearly_from(qualify, as_of) if on not in already]


def bereavement_quantity(kind: str, anchor: date, on: date, pack: NzPack) -> tuple:
    """(days, steps) for one bereavement event: zero before the qualifying
    period is met; CLOSE (immediate family) or OTHER."""
    kind = upper(kind)
    if kind not in ("CLOSE", "OTHER"):
        pack.block(E.LEAVE_TYPE_UNSUPPORTED, f"bereavement kind {kind!r} is not CLOSE or OTHER")
    qualify = add_months(anchor, _months(pack, "nz_hol_sick_qualifying_months"))
    if on < qualify:
        return ZERO, [{"step": "bereavement", "eligible": False, "qualifyingDate": qualify.isoformat()}]
    key = "nz_hol_bereavement_close_days" if kind == "CLOSE" else "nz_hol_bereavement_other_days"
    days = pack.amount(key)
    return days, [{"step": "bereavement", "eligible": True, "key": key, "days": str(days)}]


def balance(entitlement) -> Decimal:
    return _remaining(entitlement)


# ── public holidays ─────────────────────────────────────────────────────────
def holidays_for(pack: NzPack, year: int, region: Optional[str]) -> list:
    """National holidays plus the region's own anniversary day for `year`,
    from NZ_PUBLIC_HOLIDAY rows (effective_from = the date, jurisdiction_state
    = ISO region or NULL, rate_label = the name). Blocks until G2 signs them."""
    region = upper(region) or None
    out = []
    for row in pack.dated_rows(content.NZ_PUBLIC_HOLIDAY_RULE, "public_holidays"):
        day = as_date(field(row, "effective_from"))
        row_region = upper(field(row, "jurisdiction_state")) or None
        if day is None or day.year != year or (row_region is not None and row_region != region):
            continue
        out.append({"date": day, "name": str(field(row, "rate_label") or "").strip(), "region": row_region})
    return sorted(out, key=lambda h: (h["date"], h["region"] or ""))


def _hours(value) -> Decimal:
    try:
        return dec(value)
    except Exception:
        return ZERO


def otherwise_working_day(holiday: date, pattern, history=None) -> tuple:
    """(decision, basis, steps). FIXED / ROSTERED patterns decide from the
    schedule; otherwise the caller's history (worked? on each same weekday in
    its lookback) decides only when unanimous — anything else is
    UNDETERMINED and needs an evidenced operator decision."""
    weekday = WEEKDAYS[holiday.weekday()]
    kind = upper(field(pattern, "pattern_type"))
    if kind == "FIXED" and isinstance(field(pattern, "weekly_schedule"), dict):
        hours = _hours(field(pattern, "weekly_schedule").get(weekday))
        return (OWD_YES if hours > ZERO else OWD_NO), "FIXED_PATTERN", [
            {"step": "owd", "basis": "FIXED_PATTERN", "weekday": weekday, "hours": str(hours)}]
    cycle = field(pattern, "roster_cycle_weeks")
    schedule = field(pattern, "roster_schedule")
    start = as_date(field(pattern, "effective_from"))
    if kind == "ROSTERED" and cycle and isinstance(schedule, dict) and start is not None and holiday >= start:
        week = ((holiday - start).days // len(WEEKDAYS)) % int(cycle)
        hours = _hours((schedule.get(str(week)) or {}).get(weekday))
        return (OWD_YES if hours > ZERO else OWD_NO), "ROSTER", [
            {"step": "owd", "basis": "ROSTER", "rosterWeek": week, "weekday": weekday, "hours": str(hours)}]
    seen = [bool(x) for x in (history or ())]
    if seen and all(seen):
        decision = OWD_YES
    elif seen and not any(seen):
        decision = OWD_NO
    else:
        decision = OWD_UNDETERMINED
    return decision, "HISTORY", [{"step": "owd", "basis": "HISTORY", "weekday": weekday,
                                  "observations": len(seen), "worked": sum(seen)}]


def _aware(value: datetime, zone: ZoneInfo) -> datetime:
    return value.replace(tzinfo=zone) if value.tzinfo is None else value


def hours_on_holiday(shift_start: datetime, shift_end: datetime, holiday: date, tz: str) -> Decimal:
    """Hours of the shift inside the holiday's local calendar day (DST-correct;
    a shift may cross midnight in either direction). Naive times are local."""
    if tz not in TIMEZONES:
        raise ValueError(f"timezone must be one of {', '.join(TIMEZONES)}")
    zone = ZoneInfo(tz)
    start = _aware(shift_start, zone).astimezone(timezone.utc)
    end = _aware(shift_end, zone).astimezone(timezone.utc)
    day_start = datetime.combine(holiday, time(0), tzinfo=zone).astimezone(timezone.utc)
    day_end = datetime.combine(holiday + timedelta(days=1), time(0), tzinfo=zone).astimezone(timezone.utc)
    overlap = (min(end, day_end) - max(start, day_start)).total_seconds()
    if overlap <= 0:
        return ZERO.quantize(CENT)
    return (Decimal(str(overlap)) / _SECONDS_PER_HOUR).quantize(CENT, rounding=ROUND_HALF_UP)


def alternative_holiday_due(worked: bool, owd: str) -> bool:
    """Working a public holiday that would otherwise be a working day earns an
    alternative holiday (spec "Holidays Act")."""
    return bool(worked) and upper(owd) == OWD_YES
