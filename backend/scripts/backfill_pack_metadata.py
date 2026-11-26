"""
scripts/backfill_pack_metadata.py
---------------------------------
Fills the empty DESCRIPTIVE fields of canonical jurisdiction packs, including
Active ones, and applies a short list of owner-approved corrections. Owner
decision 2026-11-26.

Why a script: the Super Admin UI cannot edit an Active pack, and a new pack
version is far too heavy for a label (re-approval, re-activation, a window
with no Active pack). None of the fields below feeds a calculation, payslip,
report, filing or content fingerprint. They are only displayed, searched,
counted on the dashboard and used in change emails. So they can be set in
place, with an audit row, without re-approving the pack.

The values come from a checked-in CSV (default:
scripts/data/pack_metadata_backfill_2026_11.csv), one row per pack and field:

    pack_id, version, country, state, field, mode, expected_old, value, basis

  mode=fill     sets the value only when the field is empty (NULL or blank).
                An existing different value is reported as KEPT and never
                overwritten.
  mode=correct  overwrites only when the field still equals expected_old
                exactly. Anything else is reported as MISMATCH and left alone.

Only the fields in ALLOWED_FIELDS can be written. Status, dates, tax regime,
tax year, approvals, policy defaults, the source document and every rate or
slab are out of reach.

Safety:
  * dry run by default (prints the plan, writes nothing); --apply writes;
  * --apply refuses a non-local database unless the shared guard's explicit
    ZOIKO_ALLOW_NONLOCAL_DB_WRITES override is set (scripts/_local_db_guard);
  * one transaction for the whole run: any error rolls everything back;
  * one TaxConfigurationAudit row per changed pack (before/after per field),
    and updated_by_id set to --actor-id.

Usage:
    python -m scripts.backfill_pack_metadata                       # dry run
    python -m scripts.backfill_pack_metadata --apply --actor-id 17
    python -m scripts.backfill_pack_metadata --apply --actor-id 17 --country UK
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_CSV = Path(__file__).resolve().parent / "data" / "pack_metadata_backfill_2026_11.csv"
ALLOWED_FIELDS = ("regulatory_authority", "compliance_category", "compliance_owner", "engineering_owner",
                  "source_references", "change_summary", "next_review_date", "currency")
DATE_FIELDS = ("next_review_date",)
MODES = ("fill", "correct")
REASON = "Pack metadata backfill (owner-approved 2026-11-26): descriptive fields only, no calculation impact"
LEGAL_REFERENCE = "pack metadata backfill 2026-11"


class ValueTableError(ValueError):
    pass


def _max_length(field: str):
    from app.modules.payroll.models import JurisdictionPack

    return getattr(JurisdictionPack.__table__.c[field].type, "length", None)


def load_rows(path=DEFAULT_CSV) -> list[dict]:
    """Read and validate the value table. Any bad row stops the run before the database is touched."""
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    problems, seen = [], set()
    for n, row in enumerate(rows, start=2):
        where = f"line {n} ({row.get('pack_id')} v{row.get('version')} {row.get('field')})"
        field, mode, value = row.get("field"), row.get("mode"), row.get("value") or ""
        if field not in ALLOWED_FIELDS:
            problems.append(f"{where}: field is not an allowed descriptive field")
            continue
        if mode not in MODES:
            problems.append(f"{where}: mode must be fill or correct")
        if not value.strip():
            problems.append(f"{where}: empty value")
        if mode == "correct" and not (row.get("expected_old") or ""):
            problems.append(f"{where}: a correction needs expected_old")
        if field in DATE_FIELDS:
            try:
                row["value"] = dt.date.fromisoformat(value)
            except ValueError:
                problems.append(f"{where}: not an ISO date")
        else:
            limit = _max_length(field)
            if limit and len(value) > limit:
                problems.append(f"{where}: {len(value)} characters, column allows {limit}")
        key = (row.get("pack_id"), row.get("version"), field)
        if key in seen:
            problems.append(f"{where}: duplicate pack/field")
        seen.add(key)
    if problems:
        raise ValueTableError("value table rejected:\n  " + "\n  ".join(problems))
    return rows


def _is_empty(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _json(value):
    return value.isoformat() if isinstance(value, dt.date) else value


def plan_and_apply(db, rows: list[dict], *, countries=None, actor_id=None, apply: bool) -> dict:
    """Walk the value table against the target database; return a report. Writes only when apply=True."""
    from app.modules.payroll.models import JurisdictionPack
    from app.modules.payroll.service import record_tax_audit

    wanted = {c.upper() for c in countries} if countries else None
    by_pack: dict = {}
    for row in rows:
        if wanted and (row.get("country") or "").upper() not in wanted:
            continue
        by_pack.setdefault((row["pack_id"], row["version"]), []).append(row)

    report = {"packs": [], "missing": []}
    for (pack_id, version), pack_rows in sorted(by_pack.items()):
        pack = (db.query(JurisdictionPack)
                .filter(JurisdictionPack.pack_id == pack_id, JurisdictionPack.version == version).one_or_none())
        if pack is None:
            report["missing"].append(f"{pack_id} v{version}")
            continue
        entry = {"pack": f"{pack_id} v{version}", "id": pack.id, "status": pack.status,
                 "changed": [], "kept": [], "mismatch": [], "already": []}
        old_values, new_values = {}, {}
        for row in pack_rows:
            field, value = row["field"], row["value"]
            current = getattr(pack, field)
            if current == value:
                entry["already"].append(field)
                continue
            if row["mode"] == "fill" and not _is_empty(current):
                entry["kept"].append(field)                 # someone set a value: never overwritten
                continue
            if row["mode"] == "correct" and current != row["expected_old"]:
                entry["mismatch"].append(field)             # changed since the table was approved
                continue
            entry["changed"].append(field)
            old_values[field], new_values[field] = _json(current), _json(value)
            if apply:
                setattr(pack, field, value)
        if apply and entry["changed"]:
            if actor_id is not None:
                pack.updated_by_id = actor_id
            record_tax_audit(db, actor_id=actor_id, action="update", entity_type="jurisdiction_pack",
                             entity_id=pack.id, jurisdiction_pack_id=pack.id, tax_version=pack.version,
                             legal_reference=LEGAL_REFERENCE, old_value=old_values, new_value=new_values,
                             reason=REASON, auto_commit=False)    # one transaction: all or nothing
        report["packs"].append(entry)
    return report


def print_report(report: dict, apply: bool) -> None:
    verb = "CHANGED" if apply else "WOULD CHANGE"
    totals = {"changed": 0, "kept": 0, "mismatch": 0, "already": 0}
    for e in report["packs"]:
        for k in totals:
            totals[k] += len(e[k])
        if not (e["changed"] or e["kept"] or e["mismatch"]):
            continue
        print(f"[{verb}] {e['pack']} (id={e['id']}, {e['status']}): " + ", ".join(e["changed"]) if e["changed"]
              else f"[NO CHANGE] {e['pack']} (id={e['id']}, {e['status']})")
        if e["kept"]:
            print("    kept (already has a different value, not overwritten): " + ", ".join(e["kept"]))
        if e["mismatch"]:
            print("    correction skipped (value is no longer the approved old value): " + ", ".join(e["mismatch"]))
    for m in report["missing"]:
        print(f"[NOT FOUND] {m}")
    print(f"Packs: {len(report['packs'])}  fields {verb.lower()}: {totals['changed']}  kept: {totals['kept']}  "
          f"mismatch: {totals['mismatch']}  already set: {totals['already']}  packs not found: {len(report['missing'])}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    parser.add_argument("--actor-id", type=int, help="Super Admin user id recorded on the audit rows (required with --apply)")
    parser.add_argument("--country", action="append", help="limit to these country codes (repeatable)")
    parser.add_argument("--csv", default=str(DEFAULT_CSV), help="value table (default: the checked-in 2026-11 table)")
    args = parser.parse_args(argv)

    from scripts._local_db_guard import assert_local_database, describe_target

    if args.apply:
        assert_local_database("backfill_pack_metadata")
        if args.actor_id is None:
            parser.error("--apply needs --actor-id (the Super Admin recorded on the audit rows)")
    rows = load_rows(args.csv)
    print(f"Target database: {describe_target()}  mode={'APPLY' if args.apply else 'DRY RUN'}  rows={len(rows)}")

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        if args.apply:
            from app.modules.auth.models import User

            actor = db.get(User, args.actor_id)
            if actor is None:
                raise SystemExit(f"--actor-id {args.actor_id}: no such user")
        report = plan_and_apply(db, rows, countries=args.country, actor_id=args.actor_id, apply=args.apply)
        if args.apply:
            db.commit()
        else:
            db.rollback()
        print_report(report, args.apply)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
