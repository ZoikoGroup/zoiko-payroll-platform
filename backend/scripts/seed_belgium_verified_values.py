"""
scripts/seed_belgium_verified_values.py
---------------------------------------
Load VERIFIED Belgian values from a file into a Draft Belgian pack, through the
SAME governed import the Super Admin "Import from file" button uses
(be_content_workbook.be_content_workbook_import): the same validation, the same
all-or-nothing behaviour and a source for every changed row. Since the gate removal
(owner decision 2026-11-25) an imported row is in force as saved: there is no signing
step and no "[PENDING G1]" marker. There is no other write path here. Nothing is
approved or activated (see scripts/README_BELGIUM_VERIFIED_SEED.md for those steps).

On top of the import's own checks this script refuses, before anything runs:
  * the AI-drafted workbook BE_2026_AI_DRAFT.xlsx, by file name;
  * any row whose source (sourceDocumentId) is empty, or contains SAMPLE, DRAFT
    or NOT VERIFIED, or the word AI (case-insensitive) - also when the source
    document it names has such a title or reference, or is marked [UNVERIFIED];
  * a "Draft sources" sheet with rows (it would create unverified sources).
"Every row" means every non-blank row of a CSV / JSON file (each line is content),
and, for an XLSX workbook, every row the import would change or that names a
source.

The file uses the existing import template (GET /compliance/belgium/
content-import-template, scripts/templates/be_content_import_template.csv|json)
or the workbook exported from the pack. No Belgian figure is held here.

Usage (from backend/):
    python -m scripts.seed_belgium_verified_values --pack BE-PAYROLL-2026 \\
        --file verified.csv --actor-id 12                 # dry run (default): writes nothing
    python -m scripts.seed_belgium_verified_values --pack BE-PAYROLL-2026 \\
        --file verified.csv --actor-id 12 --apply         # writes, if the dry run is clean

--apply writes only to a local database unless the operator sets the shared
override of scripts/_local_db_guard.py. Exit code: 0 clean, 1 refused or errors.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SCRIPT_NAME = "seed_belgium_verified_values"
REFUSED_FILE_NAMES = ("be_2026_ai_draft.xlsx",)
# Substrings that mark a source as not verified; "AI" is matched as a word so a real
# reference such as "Circulaire ... detail" is not refused for containing the letters.
_BANNED = re.compile(r"SAMPLE|DRAFT|NOT\s+VERIFIED|UNVERIFIED|\bAI\b", re.IGNORECASE)


class Refused(Exception):
    """The file or one of its rows is refused before the import runs."""


def _wb():
    from app.modules.payroll import be_content_workbook

    return be_content_workbook


def _content():
    from app.modules.payroll.engine.countries import belgium_content

    return belgium_content


def banned_source(text) -> bool:
    return text is None or str(text).strip() == "" or bool(_BANNED.search(str(text)))


def _find_pack(db, pack_id: str, version=None):
    from app.modules.payroll.models import JurisdictionPack as P

    q = db.query(P).filter(P.jurisdiction_country == "BE", P.pack_type == "tax", P.pack_id == pack_id)
    if version:
        q = q.filter(P.version == version)
    packs = q.order_by(P.id).all()
    if not packs:
        raise Refused(f"No Belgian tax pack {pack_id}{f' v{version}' if version else ''}.")
    drafts = [p for p in packs if p.status == "Draft"]
    if len(packs) > 1 and len(drafts) != 1:
        versions = ", ".join(f"v{p.version} ({p.status})" for p in packs)
        raise Refused(f"{pack_id} has several versions ({versions}): name one with --version.")
    return drafts[0] if drafts else packs[0]


def _row_value_cells(sheet: str, row: dict) -> bool:
    wb = _wb()
    cols = {wb.SHEET_SCALAR: wb.SCALAR_EDIT, wb.SHEET_TOLERANCE: ("flatAmount",),
            wb.SHEET_SLAB: tuple(set(wb.SLAB_NEW) | set(wb.SLAB_EDIT_EXISTING)),
            wb.SHEET_CLASS: ("treatment",), wb.SHEET_SCHEMA: ("version", "effectiveFrom", "effectiveTo"),
            wb.SHEET_CALENDAR: ("dueDate", "paymentDueDate", "reportType", "periodKey")}.get(sheet, ())
    return any(wb._norm(row.get(c)) for c in cols)


def _rows(sheets: dict):
    """(sheet, row number, row) of every row of the import sheets."""
    wb = _wb()
    for sheet in wb.IMPORT_SHEETS:
        _header, rows = sheets.get(sheet, ([], []))
        for n, row in rows:
            if any(wb._norm(v) for v in row.values()):
                yield sheet, n, row


def _row_group(sheet: str, row: dict) -> str:
    wb, c = _wb(), _content()
    if sheet == wb.SHEET_CLASS:
        return "earning_class"
    if sheet == wb.SHEET_CALENDAR:
        return "filing calendar"
    key = row.get("key")
    return c.KEYS[key][0] if key in c.KEYS else "(unknown key)"


def _action(sheet: str, row: dict) -> str:
    wb = _wb()
    if sheet == wb.SHEET_CALENDAR:
        return "add"
    if sheet in (wb.SHEET_SLAB, wb.SHEET_SCHEMA) and wb._norm(row.get("rowId")) is None:
        return "add"
    return "update"


def check_file(db, data: bytes, filename: str) -> tuple:
    """Refusals of this script (list of strings) and the parsed sheets. Reads only."""
    from app.modules.payroll.models import SourceArtifact

    wb = _wb()
    if os.path.basename(filename or "").lower() in REFUSED_FILE_NAMES:
        raise Refused(f"{os.path.basename(filename)} is the AI-drafted workbook: it is never loaded as verified values.")
    sheets = wb._read(data, filename)
    refusals = []
    _h, draft_rows = sheets.get(wb.SHEET_DRAFT_SOURCES, ([], []))
    if any(any(wb._norm(v) for v in row.values()) for _n, row in draft_rows):
        refusals.append(f"sheet '{wb.SHEET_DRAFT_SOURCES}' has rows: it creates UNVERIFIED sources; register and "
                        "review the real sources first, then reference them by id or reference")
    xlsx = wb._format(data, filename) == "xlsx"
    for sheet, n, row in _rows(sheets):
        source = wb._norm(row.get("sourceDocumentId"))
        relevant = (not xlsx) or source is not None or _row_value_cells(sheet, row)
        if not relevant:
            continue
        where = f"{sheet} row {n} ({row.get('key') or row.get('component') or row.get('reportType') or 'row'})"
        if banned_source(source):
            refusals.append(f"{where}: source is {'empty' if not source else repr(source)}: a verified value needs "
                            "a verified source (not empty, SAMPLE, AI, DRAFT or NOT VERIFIED)")
            continue
        artifact_id = wb._source_id(db, source)
        artifact = db.get(SourceArtifact, artifact_id) if artifact_id else None
        if artifact is not None and any(t and _BANNED.search(t) for t in (artifact.title, artifact.form_number)):
            refusals.append(f"{where}: source document #{artifact.id} ({artifact.form_number or artifact.title!r}) is "
                            "marked as not verified")
    return refusals, sheets


def summarize(sheets: dict, report: dict) -> dict:
    """Rows to add / update per group, the import's validation errors, and the
    catalogue keys the file does not mention."""
    wb, c = _wb(), _content()
    changed_rows = set()
    for item in report["items"]:
        if item["status"] == "OK":
            m = re.match(r"^(?P<sheet>[^!]+)!(?:[A-Z]+(?P<row>\d+)|row (?P<row2>\d+))$", item["cell"])
            if m:
                changed_rows.add((m["sheet"], int(m["row"] or m["row2"])))
    per_group = defaultdict(Counter)
    mentioned = set()
    for sheet, n, row in _rows(sheets):
        if row.get("key") in c.KEYS:
            mentioned.add(row["key"])
        if sheet == wb.SHEET_CLASS:
            mentioned.update(c.keys_in_group("earning_class"))
        if (sheet, n) in changed_rows:
            per_group[_row_group(sheet, row)][_action(sheet, row)] += 1
    errors = [f"{i['cell']}: {i['reason']}" for i in report["items"] if i["status"] == "ERROR"]
    missing = sorted(k for k in c.KEYS if k not in mentioned)
    return {"perGroup": {g: dict(v) for g, v in sorted(per_group.items())}, "errors": errors, "missingKeys": missing}


def run(db, *, pack_id: str, data: bytes, filename: str, actor_id: int, apply: bool, reason=None,
        version=None) -> dict:
    """The whole procedure, for the CLI and the tests. Never commits unless
    `apply` and both this script's checks and the import's dry run are clean."""
    wb = _wb()
    pack = _find_pack(db, pack_id, version)
    refusals, sheets = check_file(db, data, filename)
    reason = (reason or f"Verified values loaded from {os.path.basename(filename)} ({SCRIPT_NAME})").strip()
    preview = wb.be_content_workbook_import(db, pack.id, data, actor_id, reason=reason, dry_run=True,
                                            filename=filename)
    summary = summarize(sheets, preview)
    out = {"pack": f"{pack.pack_id} v{pack.version}", "packRowId": pack.id, "status": pack.status,
           "refusals": refusals, **summary, "applied": False, "changes": preview["changes"]}
    if not apply or refusals or preview["errors"]:
        return out
    result = wb.be_content_workbook_import(db, pack.id, data, actor_id, reason=reason, dry_run=False,
                                           filename=filename)
    if result["written"]:
        db.commit()                                      # exactly what the import route does
        out.update(applied=True, changes=result["changes"])
    return out


def _print(out: dict, apply: bool) -> None:
    print(f"[{SCRIPT_NAME}] pack {out['pack']} (id={out['packRowId']}, {out['status']}) - "
          f"{'APPLY' if apply else 'DRY RUN (nothing written)'}")
    print("Rows to add / update per group:")
    for group, counts in out["perGroup"].items():
        print(f"  {group}: add {counts.get('add', 0)}, update {counts.get('update', 0)}")
    if not out["perGroup"]:
        print("  (no change)")
    for title, lines in (("Refused by this script", out["refusals"]), ("Validation errors", out["errors"])):
        print(f"{title}: {len(lines)}")
        for line in lines:
            print(f"  - {line}")
    print(f"Catalogue keys not in the file: {len(out['missingKeys'])}")
    for key in out["missingKeys"]:
        print(f"  - {key}")
    if apply:
        print("Written: the rows are in force (no signing step); approve and activate the pack next." if out["applied"]
              else "NOT written: fix the refusals / errors above (all-or-nothing).")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Load verified Belgian values into a Draft pack (governed import).")
    parser.add_argument("--pack", required=True, help="Pack id, e.g. BE-PAYROLL-2026.")
    parser.add_argument("--version", help="Pack version, when the pack id has several.")
    parser.add_argument("--file", required=True, help="CSV / JSON / XLSX in the import template format.")
    parser.add_argument("--actor-id", type=int, required=True, help="The Super Admin doing the import.")
    parser.add_argument("--reason", help="Audit reason (default names the file).")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True, help="Preview only (the default).")
    mode.add_argument("--apply", action="store_true", help="Write, if the dry run is clean.")
    args = parser.parse_args(argv)

    path = Path(args.file)
    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        return 1
    if args.apply:
        from scripts._local_db_guard import assert_local_database

        assert_local_database(SCRIPT_NAME)
    from app.core.exceptions import BadRequestException, NotFoundException
    from app.database import SessionLocal, initialize_database
    from scripts._actor_authorization import require_super_admin_actor

    initialize_database()
    db = SessionLocal()
    try:
        require_super_admin_actor(db, args.actor_id, "importer")
        out = run(db, pack_id=args.pack, data=path.read_bytes(), filename=path.name, actor_id=args.actor_id,
                  apply=args.apply, reason=args.reason, version=args.version)
    except (Refused, BadRequestException, NotFoundException) as error:
        db.rollback()
        print(f"[{SCRIPT_NAME}] REFUSED: {getattr(error, 'detail', None) or error}", file=sys.stderr)
        return 1
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    _print(out, args.apply)
    ok = not out["refusals"] and not out["errors"]
    return 0 if ok and (out["applied"] or not args.apply) else 1


if __name__ == "__main__":
    sys.exit(main())
