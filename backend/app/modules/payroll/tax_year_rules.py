"""Tax year vs. effective dates — a generic, date-based rule (no country list).

  * A pack whose effective dates fall within ONE calendar year must use a
    single-year tax year equal to that year ("2027" for 2027-01-01 → 2027-12-31,
    never "2027-2028").
  * An open-ended pack (no end date): a single-year tax year must equal the start
    date's year; a split year ("2026-27", "2026-2027", "2026/27") must include it.
  * Packs spanning two calendar years (e.g. 6 Apr → 5 Apr) and tax-year text in
    any other format are not checked here.

Applied by upsert_jurisdiction_pack on create, and on edit only when the tax
year or a date is changed — an existing record is never rejected or altered
for a value it already holds. The form applies the same rule
(frontend/src/components/jurisdiction/taxYear.js); both are checked against
the same case table (tests/test_tax_year_rules.py + the frontend validation).
Pure: no database access.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional, Tuple

_SINGLE = re.compile(r"^\s*(\d{4})\s*$")
_SPLIT = re.compile(r"^\s*(\d{4})\s*[-/–]\s*(\d{2}|\d{4})\s*$")


def parse_tax_year(text) -> Optional[Tuple[int, ...]]:
    """(2026,) for "2026"; (2026, 2027) for "2026-27" / "2026-2027" / "2026/27";
    None for empty text or any other format (not checked) — including text whose
    second part is not the next year ("2026-07" is a half-year window label in
    the NL / CH packs, not a split tax year)."""
    if text is None:
        return None
    m = _SINGLE.match(str(text))
    if m:
        return (int(m.group(1)),)
    m = _SPLIT.match(str(text))
    if m:
        first, second = int(m.group(1)), m.group(2)
        if len(second) == 2:
            last = first // 100 * 100 + int(second)
            if last < first:
                last += 100
        else:
            last = int(second)
        return (first, last) if last == first + 1 else None
    return None


def tax_year_date_refusal(tax_year, effective_from: Optional[date], effective_to: Optional[date]) -> Optional[str]:
    """Why `tax_year` does not fit the pack's dates, or None."""
    years = parse_tax_year(tax_year)
    if years is None or effective_from is None:
        return None
    start = effective_from.year
    if effective_to is not None:
        if effective_to.year != start:
            return None                                   # spans two calendar years: not checked here
        if len(years) == 2:
            return (f"Tax year \"{tax_year}\" spans two years, but this pack's dates ({effective_from} → "
                    f"{effective_to}) fall within {start}. Use the single year {start}.")
        if years[0] != start:
            return (f"Tax year \"{tax_year}\" does not match this pack's dates ({effective_from} → {effective_to}). "
                    f"Use {start}.")
        return None
    # open-ended
    if len(years) == 1 and years[0] != start:
        return (f"Tax year \"{tax_year}\" does not match the start date {effective_from}. Use {start}, or a split "
                f"year that includes {start}.")
    if len(years) == 2 and start not in years:
        return f"Tax year \"{tax_year}\" does not include the start date's year ({start})."
    return None
