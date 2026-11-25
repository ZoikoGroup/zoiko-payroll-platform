// Tax year vs. effective dates — the same generic, date-based rule as the
// backend (app/modules/payroll/tax_year_rules.py), shown in the New Pack /
// Edit forms before saving. The server applies it again on create and on an
// edit that changes the tax year or a date. Plain JS so the validation
// scripts can evaluate it under Node; both sides are checked against
// backend/tests/data/tax_year_cases.json.
//
//  * dates within ONE calendar year -> a single-year tax year equal to it;
//  * open-ended (no end date) -> a single year equal to the start year, or a
//    split year ("2026-27", "2026-2027", "2026/27") that includes it;
//  * dates spanning two calendar years, or any other text format: not checked.

const SINGLE = /^\s*(\d{4})\s*$/;
const SPLIT = /^\s*(\d{4})\s*[-/–]\s*(\d{2}|\d{4})\s*$/;

export function parseTaxYear(text) {
  if (text === null || text === undefined) return null;
  const s = String(text);
  let m = SINGLE.exec(s);
  if (m) return [Number(m[1])];
  m = SPLIT.exec(s);
  if (!m) return null;
  const first = Number(m[1]);
  let last;
  if (m[2].length === 2) {
    last = Math.floor(first / 100) * 100 + Number(m[2]);
    if (last < first) last += 100;
  } else {
    last = Number(m[2]);
  }
  // Only "next year" is a split tax year ("2026-07" is a half-year window label).
  return last === first + 1 ? [first, last] : null;
}

const yearOf = (iso) => (iso ? Number(String(iso).slice(0, 4)) : null);

// Why `taxYear` does not fit the dates (ISO strings), or null.
export function taxYearDateProblem(taxYear, effectiveFrom, effectiveTo) {
  const years = parseTaxYear(taxYear);
  const start = yearOf(effectiveFrom);
  if (!years || !start) return null;
  const quoted = `"${taxYear}"`;
  if (effectiveTo) {
    if (yearOf(effectiveTo) !== start) return null;
    if (years.length === 2) {
      return `Tax year ${quoted} spans two years, but this pack's dates (${effectiveFrom} → ${effectiveTo}) fall within ${start}. Use the single year ${start}.`;
    }
    if (years[0] !== start) return `Tax year ${quoted} does not match this pack's dates (${effectiveFrom} → ${effectiveTo}). Use ${start}.`;
    return null;
  }
  if (years.length === 1 && years[0] !== start) {
    return `Tax year ${quoted} does not match the start date ${effectiveFrom}. Use ${start}, or a split year that includes ${start}.`;
  }
  if (years.length === 2 && !years.includes(start)) return `Tax year ${quoted} does not include the start date's year (${start}).`;
  return null;
}
