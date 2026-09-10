# HMRC golden-test fixtures

ZP-TAX-UK-2026-27-001 §7.2/§22.1/AC-31 gap-closure Part 10 (2026-09-09).

This directory is where real HMRC test cases go once they're converted
to this harness's JSON format. It currently contains **zero real
cases** — only one illustrative sample (`_sample_student_loan.json`,
leading underscore) that proves the harness mechanism itself works.
That sample is hand-calculated from this codebase's own constants, not
HMRC-sourced, and is not a substitute for the real thing.

## Where to get the real files

HMRC publishes these on GOV.UK under a stable URL pattern per tax year:

```
https://www.gov.uk/government/publications/software-developers-payroll-test-data-2026-to-2027
```

(Substitute the tax year — `-2025-to-2026`, `-2024-to-2025`, etc. all
resolve too.) The actual spreadsheet download links on that page are
**not** stable across years, so always go via the publication page
itself rather than a saved direct link.

As of recent tax years, expect:
- **PAYE Tax** and **National Insurance** — each a ZIP of spreadsheets (unzip first)
- **Student Loan** — a standalone `.xls`/`.xlsx`/`.ods`
- **Directors NI** — its own spreadsheet, several scenario-type sheets

## Converting a downloaded file

```
python scripts/convert_hmrc_test_data.py student-loan path/to/stud-loans-26-27.xlsx tests/fixtures/hmrc_golden/
python scripts/convert_hmrc_test_data.py income-tax path/to/income-tax-26-27.xlsx tests/fixtures/hmrc_golden/
```

**Before trusting the output**: open the real file first and check its
actual column headers against the `*_COLUMNS` constants at the top of
`scripts/convert_hmrc_test_data.py`. HMRC's exact layout has shifted
across tax years before, and the 2026-27 file's precise headers weren't
available to verify against when this converter was written — it's a
working starting point, not a guaranteed-correct parser for a file this
session has never seen.

## Case JSON format

See the full schema and field-by-field explanation in
`tests/hmrc_golden/runner.py`'s module docstring. Every case has a
`context` (the payroll inputs) and an `expected` dict (any subset of
the engine's output fields — `tds`, `ni_employee`, `employer_ni`,
`study_loan_deduction`, etc.). Comparisons are **exact Decimal
equality** — no tolerance, no rounding leniency, per §7.2's own "no
tolerance" rule.

## Running the harness

```
python -m pytest tests/test_hmrc_golden.py -v
```

Real cases (any `*.json` file WITHOUT a leading underscore) run as
`test_hmrc_golden_case[...]`. A mismatch fails the build with every
differing field listed, not just the first. An empty real-case set
shows as a skipped parametrization, not a hidden pass — you'll always
be able to tell whether real cases are actually running.

## Known scope limitation

This engine does not implement true cumulative Week1/Month1-vs-YTD tax
basis tracking (a disclosed, pre-existing scope boundary — see
`engine/countries/uk.py`'s own comment on `interpret_tax_code`). HMRC
test rows that specifically exercise cumulative-basis behavior across
multiple periods can't be converted meaningfully yet; only single-period,
non-cumulative test rows should be pulled in until that's built.
