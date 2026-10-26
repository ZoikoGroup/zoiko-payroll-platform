"""
engine/jurisdictions/mexico/period.py
-------------------------------------
The payment period of one Mexican payslip (MX-004, MX-008, MX-021):

- the ISR tariff period — one of the Art. 96 periods content can carry; any
  other interval (e.g. 14 days) BLOCKS until its regulatory method is
  transcribed (Q3);
- the days paid (ISR / subsidy) and the contribution segments (IMSS /
  INFONAVIT): each segment carries the national rows in force on its own
  dates, so a period spanning a UMA change is computed with the right UMA
  for each part. The service (Phase 6) splits a period wherever a content row
  changes; a single-segment period uses the pay-date rows;
- absence / incapacity days BLOCK until the IMSS contribution-day rules are
  transcribed (Q6) — the SBC is never simply zeroed.

The legal date is always the context's pay date — never the server clock.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal, InvalidOperation

from ...countries import mexico_content as _c
from .content import Content
from .errors import MXBlock


def _days(value, what: str) -> Decimal:
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise MXBlock("MX_PERIOD_INVALID", f"{what} is not a number ({value!r})")
    if not out.is_finite() or out < 0:
        raise MXBlock("MX_PERIOD_INVALID", f"{what} must be zero or more")
    return out


def _date(value, what: str) -> _dt.date:
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, str):
        try:
            return _dt.date.fromisoformat(value)
        except ValueError:
            pass
    raise MXBlock("MX_PERIOD_INVALID", f"{what} is not a date")


def pay_date(ctx) -> _dt.date:
    value = getattr(ctx, "mx_payroll_date", None)
    if not isinstance(value, _dt.date):
        raise MXBlock("MX_PAY_DATE_MISSING", "the pay date selects the law (MX-004) and was not supplied")
    return value.date() if isinstance(value, _dt.datetime) else value


def tariff_period(ctx) -> str:
    period = (getattr(ctx, "mx_payment_period", None) or "").strip().upper()
    if period not in _c.MX_ISR_PERIODS:
        raise MXBlock("MX_PERIOD_UNSUPPORTED",
                      f"payment period {period or '(none)'!r} has no Art. 96 tariff in this release "
                      f"({', '.join(_c.MX_ISR_PERIODS)}); other intervals need their regulatory method (Q3)")
    return period


class Segment:
    def __init__(self, start, end, days, content: Content):
        self.start, self.end, self.days, self.content = start, end, days, content


class Period:
    def __init__(self, start, end, days_paid, segments, tariff, absence_days=Decimal("0"),
                 incapacity_days=Decimal("0")):
        self.start, self.end, self.days_paid, self.segments, self.tariff = start, end, days_paid, segments, tariff
        # W3-3: unpaid absences / incapacity in the period (LSS Art. 31), applied per branch
        self.absence_days, self.incapacity_days = absence_days, incapacity_days

    @property
    def contribution_days(self) -> Decimal:
        return sum((s.days for s in self.segments), Decimal("0"))


def resolve(ctx, pay_content: Content) -> Period:
    facts = getattr(ctx, "mx_period", None)
    if not facts:
        raise MXBlock("MX_PERIOD_MISSING", "no payment-period facts (start, end, days paid)")
    tariff = tariff_period(ctx)
    start, end = _date(facts.get("start"), "period start"), _date(facts.get("end"), "period end")
    if end < start:
        raise MXBlock("MX_PERIOD_INVALID", "the period ends before it starts")
    days_paid = _days(facts.get("days_paid"), "days paid")
    if days_paid <= 0:
        raise MXBlock("MX_PERIOD_INVALID", "days paid must be more than zero")
    absence = _days(facts.get("absence_days") or 0, "absence_days")
    incapacity = _days(facts.get("incapacity_days") or 0, "incapacity_days")
    if (absence > 0 or incapacity > 0) and _c.MX_CONTRIBUTION_DAYS_RULE is None:
        name = "absence days" if absence > 0 else "incapacity days"
        raise MXBlock("MX_ABSENCE_RULES_MISSING",
                      f"{name} in the period — the IMSS contribution-day rules for absences and "
                      f"incapacity are not transcribed yet (Q6)")
    raw = facts.get("segments")
    if not raw:
        segments = [Segment(start, end, days_paid, pay_content)]
    else:
        segments, cursor = [], None
        for i, seg in enumerate(raw):
            s_start, s_end = _date(seg.get("start"), f"segment {i + 1} start"), _date(seg.get("end"), f"segment {i + 1} end")
            if s_end < s_start or s_start < start or s_end > end:
                raise MXBlock("MX_PERIOD_INVALID", f"segment {i + 1} is not inside the period")
            if cursor is not None and s_start <= cursor:
                raise MXBlock("MX_PERIOD_INVALID", f"segment {i + 1} overlaps the previous one")
            cursor = s_end
            if len(raw) > 1 and not seg.get("rate_map"):
                raise MXBlock("MX_SEGMENT_CONTENT_MISSING",
                              f"segment {i + 1} ({s_start.isoformat()}–{s_end.isoformat()}) carries no rows of its own "
                              f"(MX-021: each contribution segment uses the content in force on its dates)")
            content = (Content(seg["rate_map"], seg.get("slabs") or pay_content.slabs, f"segment {s_start.isoformat()}")
                       if seg.get("rate_map") else pay_content)
            segments.append(Segment(s_start, s_end, _days(seg.get("days"), f"segment {i + 1} days"), content))
    if absence > 0 or incapacity > 0:
        _c.MX_CONTRIBUTION_DAYS_RULE.check(absence, incapacity, len(segments))     # W3-3
    return Period(start, end, days_paid, segments, tariff, absence, incapacity)
