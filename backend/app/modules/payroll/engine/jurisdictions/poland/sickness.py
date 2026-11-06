"""Poland sickness: employer sick pay and the ZUS hand-over (ZP-PL-ENG-001 §9,
PL-017 / PL-018).

For each APPROVED incapacity episode overlapping the pay period (calendar
days, clipped to the period):
  * the employer pays up to the signed yearly limit — the standard limit, or
    the shorter one for an older employee under the signed age rule
    (pl_sick_age_rule: AGE_AT_EPISODE_START / FROM_YEAR_AFTER_REACHING_AGE) —
    counted against the calendar-year SICK_DAYS_EMPLOYER accumulator plus
    earlier episodes in this period (PL-018: the transition point is always
    rebuilt from approved episodes, never stored);
  * days beyond the limit are ZUS sickness-benefit days: traced and posted to
    nobody's pay here — the benefit payer determination is not given by the
    specification, and a non-zero SICKNESS_BENEFIT component is blocked by its
    REVIEW earning class;
  * the rate is the signed full rate for the signed full-rate categories,
    otherwise the signed standard rate;
  * the amount is employer days x the episode's APPROVED daily benefit base
    (BenefitBaseSnapshot, evidenced) x rate, and must equal the
    SICK_PAY_EMPLOYER component.
No medical detail ever reaches the engine (PL-017): the service passes dates,
category and the base only.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.modules.payroll.engine.countries import poland_content as content
from app.modules.payroll.engine.jurisdictions.poland import errors as E
from app.modules.payroll.engine.jurisdictions.poland.pack import (
    HUNDRED, ZERO, PlPack, as_date, dec, field, money, upper)

_TOLERANCE = Decimal("0.01")


def _age_on(born: date, on: date) -> int:
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


def _older(pack: PlPack, rule: str, born, episode_start: date, pay_year: int) -> bool:
    if born is None:
        pack.block(E.keyed(E.FACT_MISSING, "date_of_birth"), "the sick-pay age test needs the date of birth")
    threshold = int(pack.amount("pl_sick_older_age_threshold"))
    if rule == "AGE_AT_EPISODE_START":
        return _age_on(born, episode_start) > threshold
    return pay_year > born.year + threshold          # FROM_YEAR_AFTER_REACHING_AGE


def compute(pack: PlPack, pay: dict, episodes, period_start, period_end, date_of_birth, ytd: dict,
            pay_date: date) -> dict:
    claimed = pay.get("SICK_PAY_EMPLOYER", ZERO)
    start, end = as_date(period_start), as_date(period_end)
    relevant = []
    for episode in episodes or []:
        if upper(field(episode, "status")) not in ("", "APPROVED"):
            continue
        e_from, e_to = as_date(field(episode, "date_from")), as_date(field(episode, "date_to"))
        if start is None or end is None:
            pack.block(E.PERIOD_MISSING, "sick days are counted inside the pay period, which is not known")
        if e_to < start or e_from > end:
            continue
        relevant.append((max(e_from, start), min(e_to, end), episode))
    if not relevant:
        if claimed != ZERO:
            pack.block(E.SICKNESS_EPISODE_MISSING, "employer sick pay needs an approved incapacity episode (spec §9)")
        return {"episodes": [], "employerDays": 0, "zusDays": 0, "amount": ZERO, "status": "NONE"}

    rule = pack.text("pl_sick_age_rule", content.SICK_AGE_RULES)
    full_rate_cases = pack.text_list("pl_sick_full_rate_cases")
    if any(c not in content.INCAPACITY_CATEGORIES for c in full_rate_cases):
        pack.block(E.keyed(E.POLICY_PENDING, "pl_sick_full_rate_cases"), "unknown incapacity category in the list")
    standard_rate = pack.pct("pl_sick_rate_standard", "employee")
    full_rate = pack.pct("pl_sick_rate_full", "employee")
    if ytd is None or ytd.get("SICK_DAYS_EMPLOYER") is None:
        pack.block(E.keyed(E.YTD_MISSING, "SICK_DAYS_EMPLOYER"), "the employer sick-day accumulator is not supplied")
    used = int(dec(ytd["SICK_DAYS_EMPLOYER"]))
    born = as_date(date_of_birth)

    lines, employer_total, zus_total, amount_total = [], 0, 0, ZERO
    for clip_from, clip_to, episode in sorted(relevant, key=lambda r: (r[0], str(field(r[2], "id")))):
        category = upper(field(episode, "category"))
        if category not in content.INCAPACITY_CATEGORIES:
            pack.block(E.keyed(E.SICKNESS_EPISODE_INVALID, category or "NONE"), "unknown incapacity category")
        older = _older(pack, rule, born, as_date(field(episode, "date_from")), pay_date.year)
        limit = int(pack.amount("pl_sick_employer_days_older" if older else "pl_sick_employer_days"))
        days = (clip_to - clip_from).days + 1
        employer_days = min(days, max(limit - used, 0))
        zus_days = days - employer_days
        rate = full_rate if category in full_rate_cases else standard_rate
        amount = ZERO
        base = field(episode, "daily_base_amount")
        if employer_days > 0:
            if base in (None, ""):
                pack.block(E.keyed(E.BENEFIT_BASE_MISSING, str(field(episode, "id"))),
                           "employer sick pay needs the episode's approved daily benefit base")
            amount = Decimal(employer_days) * dec(base) * rate / HUNDRED
        handover = (clip_from + timedelta(days=employer_days)).isoformat() if zus_days else None
        lines.append({"episodeId": field(episode, "id"), "category": category, "from": clip_from.isoformat(),
                      "to": clip_to.isoformat(), "days": days, "limit": limit, "olderLimit": older,
                      "employerDaysUsedBefore": used, "employerDays": employer_days, "zusDays": zus_days,
                      "zusBenefitFrom": handover, "ratePct": str(rate),
                      "dailyBase": None if base in (None, "") else money(base), "amount": money(amount)})
        used += employer_days
        employer_total += employer_days
        zus_total += zus_days
        amount_total += amount

    if abs(amount_total - claimed) >= _TOLERANCE:
        pack.block(E.SICK_PAY_MISMATCH, "employer sick pay does not equal days x approved base x rate")
    return {"episodes": lines, "employerDays": employer_total, "zusDays": zus_total, "amount": amount_total,
            "status": "CALCULATED", "ageRule": rule,
            "payerDetermination": "ZUS-benefit payer rules are not given by the specification (not paid here)"}
