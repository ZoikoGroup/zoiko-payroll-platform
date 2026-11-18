"""
scripts/be_rebase_content_workbook.py
-------------------------------------
Belgium (ZP-BE-ENG-001): move a filled content workbook onto ANOTHER Belgian pack — OFFLINE, no database.

Why: the workbook import matches rows by rowId (the database id), and ids differ between databases. The AI-drafted
docs/belgium/content/BE_2026_AI_DRAFT.xlsx carries the ids of the local pack it was exported from, so importing it
into the production pack fails ("rowId is not a row of this pack"). The fix is no code change:

  1. a Super Admin exports the TARGET pack's own workbook (Super Admin > Belgium > Signing status > export);
  2. this script copies the filled workbook and replaces only its rowIds with the target's ids, matching each row by
     its natural key (Scalar keys / Parallel tolerances: key; Earning classification: component + obligation);
  3. the Super Admin imports the result — dry run first.

Every value, source reference and note is kept exactly; a sheet whose ids are blank (new rows) is left alone. The
script refuses (exit 1, nothing written) when a filled row has no match in the target, or a natural key is not
unique. It never signs anything: the import marks every changed row PENDING again.

Usage:
    python -m scripts.be_rebase_content_workbook <filled.xlsx> <target-export.xlsx> <out.xlsx>
"""
import sys

ID_SHEETS = {
    "Scalar keys": ("rowId", ("key",)),
    "Parallel tolerances": ("rowId", ("key",)),
    "Earning classification": ("rowId", ("component", "obligation")),
}


def _rows(ws):
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return [], []
    header = [str(h).strip() if h is not None else "" for h in rows[0]]
    return header, rows[1:]


def _text(value):
    return "" if value is None else str(value).strip()


def be_target_ids(target_wb) -> dict:
    """{sheet: {natural key tuple: target id}} from the target pack's export; refuses duplicate keys."""
    out = {}
    for sheet, (id_col, key_cols) in ID_SHEETS.items():
        if sheet not in target_wb.sheetnames:
            raise SystemExit(f"The target export has no '{sheet}' sheet - export the target pack's workbook again.")
        header, rows = _rows(target_wb[sheet])
        mapping = {}
        for row in rows:
            rec = dict(zip(header, row))
            key = tuple(_text(rec.get(k)) for k in key_cols)
            if not any(key):
                continue
            if key in mapping:
                raise SystemExit(f"'{sheet}': the target export holds {key} twice - refusing to guess.")
            mapping[key] = _text(rec.get(id_col))
        out[sheet] = mapping
    return out


def be_rebase(filled_wb, target_ids: dict) -> list:
    """Replace the filled workbook's ids in place; returns [(sheet, changed)] or raises SystemExit on a miss."""
    report, missing = [], []
    for sheet, (id_col, key_cols) in ID_SHEETS.items():
        if sheet not in filled_wb.sheetnames:
            continue
        ws = filled_wb[sheet]
        header, rows = _rows(ws)
        if id_col not in header:
            raise SystemExit(f"'{sheet}' has no '{id_col}' column.")
        id_index = header.index(id_col) + 1
        changed = 0
        for offset, row in enumerate(rows, start=2):
            rec = dict(zip(header, row))
            if not _text(rec.get(id_col)):
                continue                                   # a blank id is a new row: nothing to rebase
            key = tuple(_text(rec.get(k)) for k in key_cols)
            target = target_ids[sheet].get(key)
            if not target:
                missing.append(f"{sheet}!row {offset} {key}")
                continue
            ws.cell(row=offset, column=id_index).value = target
            changed += 1
        report.append((sheet, changed))
    if missing:
        raise SystemExit("No row in the target pack for: " + "; ".join(missing[:10])
                         + (f" (+{len(missing) - 10} more)" if len(missing) > 10 else ""))
    return report


def main(argv) -> int:
    from openpyxl import load_workbook

    if len(argv) != 3:
        print(__doc__.strip().splitlines()[-1].strip())
        return 2
    filled_path, target_path, out_path = argv
    target_ids = be_target_ids(load_workbook(target_path, read_only=True, data_only=True))
    filled = load_workbook(filled_path)
    report = be_rebase(filled, target_ids)
    filled.save(out_path)
    for sheet, changed in report:
        print(f"{sheet}: {changed} row id(s) moved to the target pack")
    print(f"written {out_path} - import it with the DRY RUN first")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
