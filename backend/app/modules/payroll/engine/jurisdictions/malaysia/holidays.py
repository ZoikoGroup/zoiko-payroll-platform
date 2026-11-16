"""Public holidays (ZP-MY-ENG-001 §9; MY-017 / MY-024).

Federal and state calendars come only from signed MY_PUBLIC_HOLIDAY rows:
the ISO date at the start of tax_formula, the name in rate_label,
jurisdiction_state = the holiday-state code (NULL = national). A worker's
calendar is the national rows plus the rows of the holiday state of their
work assignment. No row is ever generated from a guessed list.
"""
from __future__ import annotations

from datetime import date

from app.modules.payroll.engine.countries import malaysia_content as content
from app.modules.payroll.engine.jurisdictions.malaysia import errors as E
from app.modules.payroll.engine.jurisdictions.malaysia.pack import MyPack, field, upper

PENDING_MARK = "[PENDING G1]"


def row_date(row):
    text = str(field(row, "tax_formula") or "").strip()
    try:
        return date.fromisoformat(text.split()[0][:10]) if text else None
    except ValueError:
        return None


def calendar(pack: MyPack, holiday_state: str, year: int) -> dict:
    """{date: name} for the national + state calendar of `year` (signed rows)."""
    out = {}
    for row in pack.table(content.MY_PUBLIC_HOLIDAY_RULE):
        state = upper(field(row, "jurisdiction_state"))
        if state and state != upper(holiday_state):
            continue
        day = row_date(row)
        if day is None:
            pack.block(E.keyed(E.ROW_MISSING, content.MY_PUBLIC_HOLIDAY_RULE), "a holiday row has no valid date")
        if day.year == year:
            out[day] = str(field(row, "rate_label") or "Public holiday")
    return out


def national_rows(slabs, year: int) -> list:
    """Signed national holidays of `year` from raw pack rows (for the platform
    holiday list); unsigned or undated rows are skipped, never guessed."""
    out = {}
    for row in slabs or []:
        if upper(field(row, "rule_type")) != content.MY_PUBLIC_HOLIDAY_RULE or field(row, "jurisdiction_state"):
            continue
        if PENDING_MARK in str(field(row, "rate_label") or ""):
            continue
        day = row_date(row)
        if day is not None and day.year == year:
            out[day] = str(field(row, "rate_label") or "Public holiday")
    return [{"date": d.isoformat(), "name": n} for d, n in sorted(out.items())]
