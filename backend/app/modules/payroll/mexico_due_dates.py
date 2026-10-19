"""
modules/payroll/mexico_due_dates.py
-----------------------------------
Due dates for Mexico Phase 8 (docs/mexico/MEXICO_PHASE_8_PLAN.md B2, D3). A
date comes ONLY from sourced content:

  * an authority liability / ISN return — an **Active** row of the shared
    filing calendar (payroll_statutory_filing_calendar, seeded only from
    verified mexico_content.MX_FILING_CALENDAR rules) for its report type,
    state and period;
  * an IMSS movement — mexico_content.MX_IMSS_MOVEMENT_DEADLINE counted in
    business days that skip the transcribed MX_OFFICIAL_HOLIDAYS of every
    year the count crosses.

Without that content the answer is (None, "DUE_DATE_UNSOURCED"). Nothing here
falls back to a default deadline, and the shared weekend-only
service._add_business_days is never used (it knows no Mexican holiday).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.modules.payroll.engine.countries import mexico_content as _content

UNSOURCED = "DUE_DATE_UNSOURCED"
DUE_SOON_DAYS = 5                 # display threshold only (amber), not a legal deadline


def liability_due(db: Session, authority: str, period_key: str, state: Optional[str] = None
                  ) -> Tuple[Optional[date], str]:
    from app.modules.payroll.models import StatutoryFilingCalendar as C

    report_type = _content.MX_LIABILITY_REPORT_TYPES.get(authority)
    if report_type is None:
        return None, UNSOURCED
    q = db.query(C).filter(C.jurisdiction_country == "MX", C.report_type == report_type, C.period_key == period_key,
                           C.status == "Active")
    q = q.filter(C.jurisdiction_state == state) if state else q.filter(C.jurisdiction_state.is_(None))
    row = q.order_by(C.id.desc()).first()
    if row is None:
        return None, UNSOURCED
    return row.due_date, f"calendar:{row.id}"


def _holidays(year: int):
    entry = _content.MX_OFFICIAL_HOLIDAYS.get(year)
    return None if entry is None else set(entry[0])


def movement_due(event_date: date) -> Tuple[Optional[date], str]:
    rule = _content.MX_IMSS_MOVEMENT_DEADLINE
    if rule is None or rule.business_days <= 0:
        return None, UNSOURCED
    remaining, current, calendars = rule.business_days, event_date, {}
    while remaining > 0:
        current += timedelta(days=1)
        if current.year not in calendars:
            calendars[current.year] = _holidays(current.year)
        if calendars[current.year] is None:
            return None, UNSOURCED            # the count crosses a year with no transcribed holiday list
        if current.weekday() < 5 and current not in calendars[current.year]:
            remaining -= 1
    return current, f"{rule.source} {rule.source_ref}"


def due_state(due_date: Optional[date], done: bool, today: Optional[date] = None) -> str:
    """UNSOURCED / DONE / OVERDUE / DUE_SOON / OPEN — a display state."""
    if done:
        return "DONE"
    if due_date is None:
        return UNSOURCED
    today = today or date.today()
    if today > due_date:
        return "OVERDUE"
    return "DUE_SOON" if (due_date - today).days <= DUE_SOON_DAYS else "OPEN"
