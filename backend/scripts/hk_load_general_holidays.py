"""
Load one year of Hong Kong GENERAL holidays into a Draft HK rule pack, from an
archived official source.

    python -m scripts.hk_load_general_holidays --pack HK-PAYROLL-2026 --version 1.0 --year 2026 \
        --source-file <archived official list: PDF/HTML from the gazette / gov.hk> --source-url <its URL> \
        --dates-csv <date,name rows transcribed from that file by a person> --actor-id <Super Admin user id>

Why: the MPF contribution-day deferral (pack row mpf_contribution_day_deferral)
skips general holidays. General holidays are a different list from the
Employment Ordinance statutory holidays already in the pack. They are never
typed in from memory: every date must come from the archived source, whose
SHA-256 is recorded on the SourceArtifact the rows cite.

Rules (fail closed):
* the pack must be Draft (a loaded list changes the pack, which then needs its
  four-eyes approval again);
* every date is ISO, inside --year, unique, and has a name;
* a year that already has rows in the pack is refused (correct a list by a new
  Draft version, never by editing in place);
* the rows are labelled [G1]: UNVERIFIED until the Hong Kong specialist
  certifies the list;
* the source file is stored and hashed through the normal Source Evidence
  upload, so the durable-storage guard applies in production.
"""

import argparse
import csv
import hashlib
import mimetypes
import sys
from datetime import date
from pathlib import Path

RULE_TYPE = "HK_GENERAL_HOLIDAY"


class LoadRefused(Exception):
    pass


def read_dates(csv_text: str, year: int) -> list:
    rows, seen = [], set()
    for n, r in enumerate(csv.DictReader(csv_text.splitlines()), start=2):
        raw, name = (r.get("date") or "").strip(), (r.get("name") or "").strip()
        try:
            d = date.fromisoformat(raw)
        except ValueError:
            raise LoadRefused(f"line {n}: {raw!r} is not an ISO date (YYYY-MM-DD)")
        if d.year != year:
            raise LoadRefused(f"line {n}: {d} is not in {year}")
        if not name:
            raise LoadRefused(f"line {n}: {d} has no holiday name")
        if d in seen:
            raise LoadRefused(f"line {n}: {d} appears twice")
        seen.add(d)
        rows.append((d, name))
    if not rows:
        raise LoadRefused("the dates file has no rows")
    return sorted(rows)


def load_general_holidays(db, *, pack_id: str, version: str, year: int, source_file: Path, source_url: str,
                          dates_csv_text: str, actor_id: int) -> dict:
    from app.modules.payroll import service
    from app.modules.payroll.models import JurisdictionPack, TaxSlab
    from app.modules.payroll.schemas import SourceArtifactCreate

    if not actor_id:
        raise LoadRefused("an identified Super Admin (--actor-id) is required")
    pack = (db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == pack_id, JurisdictionPack.version == version,
                                              JurisdictionPack.jurisdiction_country == "HK").first())
    if pack is None:
        raise LoadRefused(f"no HK pack {pack_id} v{version}")
    if pack.status != "Draft":
        raise LoadRefused(f"{pack_id} v{version} is {pack.status}; general holidays are loaded into a Draft only")
    holidays = read_dates(dates_csv_text, year)
    existing = (db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id, TaxSlab.rule_type == RULE_TYPE,
                                         TaxSlab.filing_status == str(year)).count())
    if existing:
        raise LoadRefused(f"{pack_id} v{version} already holds {existing} general holidays for {year}; "
                          "correct the list in a new Draft version")
    data = Path(source_file).read_bytes()
    if not data:
        raise LoadRefused("the source file is empty")
    digest = hashlib.sha256(data).hexdigest()
    art = service.create_source_artifact(db, SourceArtifactCreate(
        agency="HKSAR Government", title=f"[UNVERIFIED — G1] General holidays {year} (archived official list)",
        sourceUrl=source_url or None, checksumSha256=digest), actor_id=actor_id)
    service.upload_source_artifact_file(db, art.id, Path(source_file).name,
                                        mimetypes.guess_type(str(source_file))[0] or "application/octet-stream",
                                        data, actor_id=actor_id)
    order = max([s.sort_order or 0 for s in db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id)] or [0])
    for i, (d, name) in enumerate(holidays, start=1):
        db.add(TaxSlab(jurisdiction_pack_id=pack.id, jurisdiction_country="HK", organization_id=None, rule_type=RULE_TYPE,
                       sort_order=order + i, source_document_id=art.id, min_amount=0, rate_pct=0,
                       filing_status=str(year), tax_formula=d.isoformat(), rate_label=f"{name} [G1]"[:100]))
    db.flush()
    service.record_tax_audit(
        db, actor_id=actor_id, action="create", entity_type="hk_general_holiday_list", entity_id=pack.id,
        jurisdiction_pack_id=pack.id, tax_version=pack.version,
        old_value=None, new_value={"year": year, "count": len(holidays), "sourceArtifactId": art.id, "sha256": digest},
        reason=f"General holidays {year} loaded from an archived official list ({len(holidays)} days, [G1] UNVERIFIED)")
    db.commit()
    return {"pack": f"{pack_id} v{version}", "year": year, "loaded": len(holidays), "sourceArtifactId": art.id,
            "sha256": digest}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Load Hong Kong general holidays from an archived official source")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--source-file", type=Path, required=True)
    ap.add_argument("--source-url", default="")
    ap.add_argument("--dates-csv", type=Path, required=True)
    ap.add_argument("--actor-id", type=int, required=True)
    args = ap.parse_args(argv)
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        out = load_general_holidays(db, pack_id=args.pack, version=args.version, year=args.year,
                                    source_file=args.source_file, source_url=args.source_url,
                                    dates_csv_text=args.dates_csv.read_text(encoding="utf-8"), actor_id=args.actor_id)
    except LoadRefused as exc:
        db.rollback()
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
