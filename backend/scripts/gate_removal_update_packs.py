"""
scripts/gate_removal_update_packs.py
------------------------------------
Gate removal P5 (owner decision 2026-11-25, Spain model): bring the canonical
packs ALREADY SEEDED in a database for JP, NZ, PL, MY, ZA and BE in line with
the current content catalogues, without re-seeding them.

What it does, per canonical pack row (organization_id IS NULL):

  1. Strips the legacy "[PENDING G1]" marker from ContributionRate.label and
     TaxSlab.rate_label (the engine ignores it since P4; this is cosmetic and
     keeps the console honest).
  2. Fills an approved value ONLY where the database row has none yet - every
     value column empty, or text_value still the literal "PENDING_G1" - from
     what a fresh seed of the current catalogue writes for the same key
     (employee/employer %, flat amount, text value, their display columns and,
     when the catalogue dates it, effective_from/effective_to).
  3. Never overwrites a value someone already set: a different existing value
     is reported as KEPT, never changed.

The reference rows come from running each country's own seed function against
a throwaway in-memory SQLite database, so the mapping is exactly the seeder's.

Safety:
  * dry run by default (prints the plan, writes nothing); --apply writes;
  * --apply refuses a non-local database unless the shared guard's explicit
    ZOIKO_ALLOW_NONLOCAL_DB_WRITES override is set (scripts/_local_db_guard);
  * only Draft / In Review / QA packs are touched; Approved packs only with
    --include-approved (their approval should then be repeated); Active,
    Retired and Superseded packs are never touched;
  * one TaxConfigurationAudit row per changed pack.

Usage:
    python -m scripts.gate_removal_update_packs                 # dry run
    python -m scripts.gate_removal_update_packs --apply
    python -m scripts.gate_removal_update_packs --apply --include-approved --country BE
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MARK = "[PENDING G1]"
PENDING = "PENDING_G1"
COUNTRIES = ("JP", "NZ", "PL", "MY", "ZA", "BE")
VALUE_COLS = ("employee_rate_pct", "employer_rate_pct", "flat_amount", "text_value")
DISPLAY_COLS = ("total", "employee_share", "employer_share")
EDITABLE = ("Draft", "In Review", "QA")
REASON = "Gate removal P5 (owner decision 2026-11-25): legacy [PENDING G1] markers stripped and approved values filled"


def _seeders():
    from app.modules.payroll import (belgium_service, japan_service, malaysia_service, new_zealand_service,
                                     poland_service, south_africa_service)

    return {"JP": japan_service.seed_japan_pack, "NZ": new_zealand_service.seed_nz_pack,
            "PL": poland_service.seed_poland_pack, "MY": malaysia_service.seed_malaysia_pack,
            "ZA": south_africa_service.seed_south_africa_pack, "BE": belgium_service.seed_belgium_pack}


def plain(label):
    return " ".join((label or "").replace(MARK, " ").split())


def has_value(row) -> bool:
    if (row.text_value or "") == PENDING:
        return False
    return any(getattr(row, c) not in (None, "") for c in VALUE_COLS)


def value_of(row) -> tuple:
    return tuple(None if getattr(row, c) in (None, "") else str(getattr(row, c)) for c in VALUE_COLS)


def reference_rows(countries) -> dict:
    """{(country, pack_id, component_key): reference ContributionRate snapshot} from a fresh
    seed of the current catalogues into a throwaway in-memory SQLite database."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.database import Base
    from app.modules.payroll.models import ContributionRate, JurisdictionPack

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    out = {}
    try:
        seeders = _seeders()
        for cc in countries:
            seeders[cc](db)
            db.flush()
        for pack in db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country.in_(countries)):
            for r in db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                                       ContributionRate.organization_id.is_(None)):
                out[(pack.jurisdiction_country, pack.pack_id, r.component_key)] = {
                    **{c: getattr(r, c) for c in VALUE_COLS + DISPLAY_COLS},
                    "effective_from": r.effective_from, "effective_to": r.effective_to,
                    "has_value": has_value(r), "value": value_of(r)}
    finally:
        db.close()
        engine.dispose()
    return out


def plan_and_apply(db, reference: dict, countries, *, include_approved: bool, apply: bool) -> dict:
    """Walk the target database's canonical packs; return a report. Writes only when apply=True."""
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab
    from app.modules.payroll.service import record_tax_audit

    allowed = EDITABLE + (("Approved",) if include_approved else ())
    report = {"packs": [], "skipped": []}
    packs = (db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country.in_(countries))
             .order_by(JurisdictionPack.jurisdiction_country, JurisdictionPack.pack_id, JurisdictionPack.id).all())
    for pack in packs:
        if pack.status not in allowed:
            report["skipped"].append({"pack": f"{pack.pack_id} v{pack.version}", "id": pack.id, "status": pack.status})
            continue
        entry = {"pack": f"{pack.pack_id} v{pack.version}", "id": pack.id, "status": pack.status,
                 "labelsStripped": 0, "filled": [], "kept": [], "noReference": []}
        rates = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                                  ContributionRate.organization_id.is_(None)).all()
        slabs = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id,
                                         TaxSlab.organization_id.is_(None)).all()
        for row in rates:
            if MARK in (row.label or ""):
                entry["labelsStripped"] += 1
                if apply:
                    row.label = plain(row.label)[:100]
            ref = reference.get((pack.jurisdiction_country, pack.pack_id, row.component_key))
            if ref is None:
                entry["noReference"].append(row.component_key)
                continue
            if not ref["has_value"]:
                continue
            if has_value(row):
                if value_of(row) != ref["value"]:
                    entry["kept"].append(row.component_key)          # someone set a value: never overwritten
                continue
            entry["filled"].append(row.component_key)
            if apply:
                for column in VALUE_COLS + DISPLAY_COLS:
                    setattr(row, column, ref[column])
                if ref["effective_from"] is not None:
                    row.effective_from = ref["effective_from"]
                if ref["effective_to"] is not None:
                    row.effective_to = ref["effective_to"]
        for slab in slabs:
            if MARK in (slab.rate_label or ""):
                entry["labelsStripped"] += 1
                if apply:
                    slab.rate_label = plain(slab.rate_label)[:150]
        changed = entry["labelsStripped"] or entry["filled"]
        if apply and changed:
            record_tax_audit(db, actor_id=None, action="update", entity_type="jurisdiction_pack", entity_id=pack.id,
                             jurisdiction_pack_id=pack.id, tax_version=pack.version, legal_reference="gate removal P5",
                             old_value={"labelsWithMarker": entry["labelsStripped"]},
                             new_value={"labelsStripped": entry["labelsStripped"], "filled": entry["filled"]},
                             reason=REASON, auto_commit=False)          # one transaction: all or nothing
        report["packs"].append(entry)
    return report


def print_report(report: dict, apply: bool) -> None:
    verb = "CHANGED" if apply else "WOULD CHANGE"
    for e in report["packs"]:
        print(f"[{verb}] {e['pack']} (id={e['id']}, {e['status']}): {e['labelsStripped']} label(s) stripped, "
              f"{len(e['filled'])} value(s) filled, {len(e['kept'])} existing value(s) kept")
        if e["filled"]:
            print("    filled: " + ", ".join(e["filled"]))
        if e["kept"]:
            print("    kept (differs from the catalogue, not overwritten): " + ", ".join(e["kept"]))
        if e["noReference"]:
            print("    not in the current catalogue (left alone): " + ", ".join(e["noReference"]))
    for s in report["skipped"]:
        print(f"[SKIPPED] {s['pack']} (id={s['id']}): status {s['status']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    parser.add_argument("--include-approved", action="store_true", help="also update Approved packs")
    parser.add_argument("--country", action="append", choices=COUNTRIES, help="limit to these countries")
    args = parser.parse_args(argv)
    countries = tuple(args.country or COUNTRIES)

    from scripts._local_db_guard import assert_local_database, describe_target

    if args.apply:
        assert_local_database("gate_removal_update_packs")
    print(f"Target database: {describe_target()}  mode={'APPLY' if args.apply else 'DRY RUN'}")

    reference = reference_rows(countries)

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        report = plan_and_apply(db, reference, countries, include_approved=args.include_approved, apply=args.apply)
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
