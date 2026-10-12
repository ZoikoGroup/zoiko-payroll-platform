"""Hong Kong Statutory Minimum Wage (ZP-HK-ENG-001 §10, Labour Department S5).

* Minimum-wage test for a wage period = Σ (hours worked on each day × the SMW
  hourly rate in force ON THAT DAY), compared with the legally countable
  wages payable for the period. A period crossing 1 May 2026 therefore
  prices earlier hours at HK$42.10 and later hours at HK$43.10 — the rate
  segments come from every pinned-pack row overlapping the period, never a
  single "latest" value.
* The hours-record monetary cap (HK$17,600 per month from 1 May 2026) is a
  RECORD-KEEPING trigger — never a monthly minimum wage (HK-016 / spec §10).
* Contractual overtime premium is not invented; overtime HOURS count where
  they are hours worked (they arrive in the verified hours).

The result is an assessment: payroll never silently tops up pay. A shortfall
is reported (BREACH + top-up amount) for the operator / preflight.
"""

from datetime import date
from decimal import Decimal

from app.modules.payroll.engine.jurisdictions.hong_kong.common import (
    HongKongCalculationBlockedError, ZERO, cents, dec, each_day, to_date,
)


def _segment_for(segments: list, day: date):
    hits = [s for s in segments
            if to_date(s["from"]) <= day and (s.get("to") is None or day <= to_date(s["to"]))]
    if len(hits) > 1:
        raise HongKongCalculationBlockedError(
            "smw_rate_overlap", f"more than one SMW rate row is in force on {day} — the rule pack is inconsistent")
    return hits[0] if hits else None


def minimum_wage_due(hours_by_day: dict, rate_segments: list, period_start: date, period_end: date) -> dict:
    """Σ hours × rate per effective segment. BLOCKS when a worked day has no
    rate row in force (never falls back to another period's rate)."""
    by_segment = {}
    total_hours = ZERO
    for day in each_day(period_start, period_end):
        hours = dec(hours_by_day.get(day.isoformat()))
        if hours <= ZERO:
            continue
        seg = _segment_for(rate_segments, day)
        if seg is None:
            raise HongKongCalculationBlockedError(
                "smw_hourly_rate", f"no Statutory Minimum Wage rate row is in force on {day}")
        key = (seg["from"], seg.get("to"))
        entry = by_segment.setdefault(key, {"from": str(seg["from"]), "to": str(seg["to"]) if seg.get("to") else None,
                                             "rate": str(seg["value"]), "hours": ZERO, "ref": seg.get("ref")})
        entry["hours"] += hours
        total_hours += hours
    lines, due = [], ZERO
    for entry in by_segment.values():
        amount = cents(entry["hours"] * dec(entry["rate"]))
        due += amount
        lines.append({**entry, "hours": str(entry["hours"]), "amount": str(amount)})
    return {"hours": str(total_hours), "segments": lines, "minimumDue": str(cents(due))}


def hours_record_cap(cap_segments: list, period_start: date, period_end: date):
    """The cap applicable to the wage period. When the period crosses a cap
    change the HIGHER cap is used (conservative: more records required)."""
    hits = [s for s in cap_segments
            if to_date(s["from"]) <= period_end and (s.get("to") is None or period_start <= to_date(s["to"]))]
    if not hits:
        raise HongKongCalculationBlockedError(
            "smw_hours_record_cap_monthly", "no hours-record monetary cap row overlaps this wage period")
    best = max(hits, key=lambda s: dec(s["value"]))
    return dec(best["value"]), best, len(hits) > 1


def assess(hours: dict, rate_segments: list, cap_segments: list, countable_wages: Decimal,
           review_wages: Decimal, period_start: date, period_end: date, pay_frequency: str) -> dict:
    """Full SMW assessment for the payslip trace.
    `countable_wages` — wages classified as counting for SMW;
    `review_wages`    — amounts whose SMW treatment needs specialist review."""
    countable, review = dec(countable_wages), dec(review_wages)
    days = (hours or {}).get("days") or {}
    out = {"countableWages": str(cents(countable)), "wagesNeedingClassification": str(cents(review))}

    # Hours-record trigger (record-keeping only).
    if (pay_frequency or "Monthly") == "Monthly":
        cap, cap_seg, crossed = hours_record_cap(cap_segments, period_start, period_end)
        record_required = (countable + review) < cap
        out["hoursRecord"] = {
            "monthlyCap": str(cap), "capRef": cap_seg.get("ref"), "capChangedInPeriod": crossed,
            "required": record_required,
            "basis": "wages payable for the wage period below the monthly monetary cap → total hours worked must be "
                     "recorded (a record-keeping threshold, NOT a monthly minimum wage)",
        }
    else:
        out["hoursRecord"] = {"required": True, "basis": "non-monthly wage period — hours are always recorded "
                                                         "(conservative: the cap is expressed per month)"}

    if not days:
        out["status"] = "HOURS_NOT_RECORDED"
        out["detail"] = ("no verified hours for the period — the minimum-wage test cannot be evaluated"
                         + ("; hours MUST be recorded for this employee" if out["hoursRecord"]["required"] else ""))
        return out
    if not (hours or {}).get("complete", True):
        out["status"] = "HOURS_INCOMPLETE"
        out["detail"] = "verified hours do not cover every day of the wage period — test not evaluated"
        return out

    due = minimum_wage_due(days, rate_segments, period_start, period_end)
    out.update(due)
    minimum = dec(due["minimumDue"])
    if countable >= minimum:
        out["status"] = "COMPLIANT"
    elif countable + review >= minimum:
        out["status"] = "NEEDS_CLASSIFICATION_REVIEW"
        out["detail"] = "compliance depends on amounts whose minimum-wage treatment is not yet certified"
    else:
        out["status"] = "BREACH"
        out["topUpRequired"] = str(cents(minimum - countable))
        out["detail"] = "wages payable are below the statutory minimum for the hours worked — the employer must pay the difference"
    return out
