"""
scripts/convert_hmrc_test_data.py
------------------------------------
One-time conversion helper: turns a downloaded HMRC "Software developers:
payroll test data" spreadsheet into the normalized JSON case format
tests/test_hmrc_golden.py actually runs (ZP-TAX-UK-2026-27-001 §7.2/§22.1/
AC-31 gap-closure Part 10, 2026-09-09).

WHERE TO GET THE REAL FILES (BLOCKED on Venu — this session cannot fetch
them itself): https://www.gov.uk/government/publications/software-
developers-payroll-test-data-2026-to-2027 (URL pattern confirmed stable
across tax years; the underlying asset download links are NOT stable
across years, so always resolve the publication page for the current
year rather than hardcoding an asset URL). PAYE Tax and National
Insurance are typically published as a ZIP of spreadsheets; Student Loan
as a standalone .xls/.xlsx/.ods. Unzip before running this script.

IMPORTANT — VERIFY BEFORE TRUSTING: the sheet names and column headers
below are based on the last confirmed public structure (legacy years'
files) — HMRC's exact layout has shifted across tax years before (e.g.
2024-25 onward changed the bundling from individual files to ZIPs) and
2026-27's precise column names were NOT available to verify against at
implementation time. Open the real downloaded file first, compare its
actual sheet names/headers against the COLUMN MAP constants below, and
adjust them if they've drifted — this script is a working starting
point, not a guarantee-correct parser for a file this session has never
seen.

Usage:
    python scripts/convert_hmrc_test_data.py student-loan path/to/stud-loans-26-27.xlsx tests/fixtures/hmrc_golden/
    python scripts/convert_hmrc_test_data.py income-tax path/to/income-tax-26-27.xlsx tests/fixtures/hmrc_golden/

Each row becomes one normalized JSON case file, written as
<sheet>_<row_number>.json (no leading underscore — real cases run for
real in CI, unlike the "_sample_*.json" illustrative files).
"""
import json
import sys
from pathlib import Path

from openpyxl import load_workbook


# ── Student Loan: a single flat sheet, one row per test case ────────────
# Confirmed structure (legacy years, e.g. stud-loans-14-15.xls):
# columns "Pay (£)", "Frequency", "Threshold", "Student Loan".
STUDENT_LOAN_COLUMNS = {
    "pay": "Pay (£)",
    "frequency": "Frequency",
    "threshold": "Threshold",
    "student_loan": "Student Loan",
}

_FREQUENCY_MAP = {
    "weekly": "Weekly", "2 weekly": "Fortnightly", "fortnightly": "Fortnightly",
    "4 weekly": "FourWeekly", "monthly": "Monthly",
}


def convert_student_loan(path: Path, out_dir: Path) -> int:
    wb = load_workbook(path, data_only=True)
    sheet = wb.active
    header_row = [c.value for c in sheet[1]]
    col_idx = {name: header_row.index(label) for name, label in STUDENT_LOAN_COLUMNS.items() if label in header_row}
    missing = set(STUDENT_LOAN_COLUMNS) - set(col_idx)
    if missing:
        raise SystemExit(
            f"Column(s) {missing} not found in {path.name}'s header row {header_row!r} — "
            "HMRC's layout may have shifted; update STUDENT_LOAN_COLUMNS above after inspecting the real file."
        )

    written = 0
    for i, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        pay = row[col_idx["pay"]]
        frequency_raw = row[col_idx["frequency"]]
        threshold = row[col_idx["threshold"]]
        expected = row[col_idx["student_loan"]]
        if pay is None or expected is None:
            continue
        frequency = _FREQUENCY_MAP.get(str(frequency_raw).strip().lower(), str(frequency_raw).strip())
        case = {
            "description": f"HMRC Student Loan test data, row {i}",
            "source": f"{path.name}, row {i}",
            "context": {
                "gross": str(pay),
                "pay_frequency": frequency,
                "tax_code": "NT",
                "study_loan_plan": "UK_PLAN2",  # ADJUST: HMRC's file may indicate the plan per-row/per-sheet
                "study_loan_balance": "1",       # any positive value — see runner.py's own note on why
                # Override threshold/rate to match EXACTLY what this row assumes,
                # rather than relying on this codebase's own current-year default
                # (which may legitimately differ from whichever year's file this is):
                "rate_map": {
                    "sl_plan2_thresh": {"flat_amount": str(threshold)},
                } if threshold is not None else {},
            },
            "expected": {"study_loan_deduction": str(expected)},
        }
        out_path = out_dir / f"student_loan_row_{i}.json"
        out_path.write_text(json.dumps(case, indent=2), encoding="utf-8")
        written += 1
    return written


# ── Income Tax: one sheet per tax-code family, e.g. "Tax Code L" ────────
# Confirmed structure (legacy years, e.g. income-tax-14-15.xls's BASE
# sheets): "Pay Period", "Frequency", "Pay", "Tax Code", "Tax Basis",
# ..., "Tax due this period". This engine does not implement cumulative
# Week1/Month1-vs-YTD basis (see uk.py's own disclosed scope note) — only
# rows using the non-cumulative/single-period basis this engine actually
# computes can be converted; rows requiring true cumulative YTD tracking
# should be skipped (left as a manual follow-up) rather than converted
# incorrectly.
INCOME_TAX_COLUMNS = {
    "pay": "Pay",
    "frequency": "Frequency",
    "tax_code": "Tax Code",
    "tax_due": "Tax due this period",
}


def convert_income_tax(path: Path, out_dir: Path) -> int:
    wb = load_workbook(path, data_only=True)
    written = 0
    for sheet_name in wb.sheetnames:
        sheet = wb[sheet_name]
        header_row = [c.value for c in sheet[1]]
        col_idx = {name: header_row.index(label) for name, label in INCOME_TAX_COLUMNS.items() if label in header_row}
        if len(col_idx) < len(INCOME_TAX_COLUMNS):
            continue  # not a BASE-shaped sheet (e.g. a notes/summary tab) — skip, don't guess
        for i, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            pay = row[col_idx["pay"]]
            tax_code = row[col_idx["tax_code"]]
            expected = row[col_idx["tax_due"]]
            if pay is None or expected is None:
                continue
            frequency_raw = row[col_idx["frequency"]]
            frequency = _FREQUENCY_MAP.get(str(frequency_raw).strip().lower(), str(frequency_raw).strip())
            case = {
                "description": f"HMRC Income Tax test data, sheet {sheet_name!r}, row {i}",
                "source": f"{path.name}, sheet {sheet_name!r}, row {i}",
                "context": {"gross": str(pay), "pay_frequency": frequency, "tax_code": str(tax_code)},
                "expected": {"tds": str(expected)},
            }
            safe_sheet = sheet_name.replace(" ", "_").lower()
            out_path = out_dir / f"income_tax_{safe_sheet}_row_{i}.json"
            out_path.write_text(json.dumps(case, indent=2), encoding="utf-8")
            written += 1
    return written


_CONVERTERS = {"student-loan": convert_student_loan, "income-tax": convert_income_tax}


def main():
    if len(sys.argv) != 4 or sys.argv[1] not in _CONVERTERS:
        print(__doc__)
        raise SystemExit(1)
    kind, src, out_dir = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    out_dir.mkdir(parents=True, exist_ok=True)
    written = _CONVERTERS[kind](src, out_dir)
    print(f"Wrote {written} case file(s) to {out_dir}")


if __name__ == "__main__":
    main()
