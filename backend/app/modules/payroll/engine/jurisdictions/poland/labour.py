"""Poland wage and working-time controls (ZP-PL-ENG-001 §8, PL-015 / PL-016).

Pure checks over the bases, components and approved facts — they never add
money on their own:

  * minimum wage (PL-015): tested on the MIN_WAGE earning-class base only
    (overtime, night supplement and seniority allowance are EXCLUDED there),
    against the signed monthly minimum x FTE. A breach is a run exception that
    stops approval ("noncompliant case blocked", spec §14). A month with
    unpaid absence is NOT evaluated: the specification gives no proration rule
    for absence, so the reviewer must look at it (warning, never a guess);
  * overtime (PL-016): every overtime amount needs the event that created it
    (DAILY / WEEKLY / NIGHT / SUNDAY_HOLIDAY / COMP_TIME_FAILED with hours and
    the hourly rate). The event -> premium mapping is a signed policy
    (pl_overtime_premium_map); the same legal excess (event reference) never
    earns two premiums; the components must equal normal pay + premium of the
    events they claim to be;
  * night supplement: the formula is not in the specification — a non-zero
    supplement blocks until a signed rule exists;
  * pay timing: monthly pay is due by the signed day of the following month.
    The "preceding working day" shift needs the Polish holiday calendar
    (signed content, not yet seeded), so only the outer deadline is checked.
"""
from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

from app.modules.payroll.engine.countries import poland_content as content
from app.modules.payroll.engine.jurisdictions.poland import errors as E
from app.modules.payroll.engine.jurisdictions.poland.pack import HUNDRED, ZERO, PlPack, as_date, dec, field, money, upper

_OVERTIME_COMPONENTS = ("OVERTIME_50", "OVERTIME_100")
_TOLERANCE = Decimal("0.01")     # amounts come from time & attendance already rounded to the grosz


def fte(pack: PlPack, profile) -> tuple:
    numerator, denominator = field(profile, "fte_numerator"), field(profile, "fte_denominator")
    if numerator in (None, "") or denominator in (None, ""):
        pack.block(E.keyed(E.FACT_MISSING, "fte"), "working time (FTE) is not recorded on the worker profile")
    numerator, denominator = dec(numerator), dec(denominator)
    if denominator <= ZERO or numerator <= ZERO or numerator > denominator:
        pack.block(E.keyed(E.FACT_MISSING, "fte"), "the recorded FTE is not a fraction of full time")
    return numerator, denominator


def minimum_wage(pack: PlPack, bases: dict, profile, unpaid_leave_days) -> dict:
    numerator, denominator = fte(pack, profile)
    floor = pack.amount("pl_min_wage_monthly") * numerator / denominator
    base = bases["MIN_WAGE"]["base"]
    trace = {"base": money(base), "minimumWage": money(floor), "fte": f"{numerator}/{denominator}"}
    if unpaid_leave_days and dec(unpaid_leave_days) > ZERO:
        return {**trace, "status": "NOT_EVALUATED",
                "exception": {"code": E.EXC_MIN_WAGE_NOT_EVALUATED,
                              "detail": "unpaid absence this month: the minimum-wage proration is not signed"}}
    if base < floor:
        return {**trace, "status": "BREACH",
                "exception": {"code": E.EXC_MIN_WAGE_BREACH,
                              "detail": f"minimum-wage base {money(base)} is below {money(floor)}"}}
    return {**trace, "status": "PASS", "exception": None}


def _premium_map(pack: PlPack) -> dict:
    allowed = {pack.pct("pl_overtime_premium_standard", "employee"), pack.pct("pl_overtime_premium_high", "employee")}
    out = {}
    for part in pack.text_list("pl_overtime_premium_map"):
        kind, _, pct = part.partition("=")
        kind = kind.strip().upper()
        try:
            value = Decimal(pct.strip())
        except Exception:
            value = None
        if kind not in content.OVERTIME_EVENT_KINDS or value not in allowed:
            pack.block(E.keyed(E.POLICY_PENDING, "pl_overtime_premium_map"),
                       "the overtime premium map names an unknown event or premium")
        out[kind] = value
    return out


def overtime(pack: PlPack, pay: dict, events) -> dict:
    claimed = {c: pay.get(c, ZERO) for c in _OVERTIME_COMPONENTS}
    if not events:
        if any(v != ZERO for v in claimed.values()):
            pack.block(E.OVERTIME_EVENTS_MISSING, "overtime pay needs the events that created it (PL-016)")
        return {"events": [], "status": "NONE"}
    premiums = _premium_map(pack)
    standard = pack.pct("pl_overtime_premium_standard", "employee")
    expected = {c: ZERO for c in _OVERTIME_COMPONENTS}
    seen, lines = set(), []
    for event in events:
        kind = upper(field(event, "kind"))
        ref = str(field(event, "event_ref") or "").strip()
        hours, rate = dec(field(event, "hours")), dec(field(event, "hourly_rate"))
        if kind not in premiums:
            pack.block(E.keyed(E.OVERTIME_EVENT_INVALID, kind or "NONE"), "the event kind has no signed premium")
        if not ref or hours <= ZERO or rate <= ZERO:
            pack.block(E.keyed(E.OVERTIME_EVENT_INVALID, kind), "an overtime event needs a reference, hours and rate")
        if ref in seen:
            pack.block(E.keyed(E.OVERTIME_DOUBLE_PREMIUM, ref), "the same legal excess cannot earn two premiums")
        seen.add(ref)
        premium = premiums[kind]
        component = "OVERTIME_50" if premium == standard else "OVERTIME_100"
        amount = hours * rate * (HUNDRED + premium) / HUNDRED
        expected[component] += amount
        lines.append({"eventRef": ref, "kind": kind, "hours": str(hours), "hourlyRate": str(rate),
                      "premiumPct": str(premium), "component": component, "amount": money(amount)})
    for component in _OVERTIME_COMPONENTS:
        if abs(expected[component] - claimed[component]) >= _TOLERANCE:
            pack.block(E.keyed(E.OVERTIME_MISMATCH, component),
                       "overtime pay does not equal normal pay plus the premium of its events")
    return {"events": lines, "status": "MATCHED", "expected": {k: money(v) for k, v in expected.items()}}


def night_supplement(pack: PlPack, pay: dict) -> None:
    if pay.get("NIGHT_SUPPLEMENT", ZERO) != ZERO:
        pack.text("pl_night_supplement_basis", content.NIGHT_SUPPLEMENT_RULES)


def pay_timing(pack: PlPack, pay_date: date, period_end) -> dict:
    end = as_date(period_end)
    if end is None:
        return {"status": "NOT_EVALUATED", "reason": "no pay period end on the run", "exception": None}
    day = int(pack.amount("pl_pay_deadline_day"))
    year, month = (end.year + 1, 1) if end.month == 12 else (end.year, end.month + 1)
    deadline = date(year, month, min(day, calendar.monthrange(year, month)[1]))
    if pay_date > deadline:
        return {"status": "LATE", "deadline": deadline.isoformat(),
                "exception": {"code": E.EXC_PAY_DATE_LATE,
                              "detail": f"monthly pay is due by {deadline.isoformat()} (spec §8)"}}
    return {"status": "OK", "deadline": deadline.isoformat(), "exception": None,
            "note": "the preceding-working-day shift needs the signed holiday calendar"}
