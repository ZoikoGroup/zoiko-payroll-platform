"""
scripts/regenerate_hk_golden_fixtures.py
-----------------------------------------
Re-embeds the PACK ROWS (rate_map / slabs / hkg_rule_segments) of every Hong
Kong golden vector from the canonical seed, after a seed change.

THE EXPECTED FIGURES ARE NEVER TOUCHED. Each fixture's ``description``,
``source`` and ``expected`` block is read back and written out verbatim; only
the ``context.rate_map`` / ``context.slabs`` / ``context.hkg_rule_segments``
blocks are replaced, exactly as hk_service._pack_rows_for_golden builds them
for the pack-bound check. If a case cannot be re-seeded it is left alone and
reported, so a failed run never silently weakens a golden vector.

The hand-computed expected amounts in these files are the independent
verification of the statutory content (ZP-HK-ENG-001 §16): regenerating the
rows must never regenerate the answers.

Usage (local / disposable databases only — scripts/_local_db_guard):
    python -m scripts.regenerate_hk_golden_fixtures            # check only
    python -m scripts.regenerate_hk_golden_fixtures --write    # rewrite fixtures
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, initialize_database  # noqa: E402
from app.modules.payroll.hk_service import _pack_rows_for_golden  # noqa: E402
from app.modules.payroll.models import JurisdictionPack  # noqa: E402
from scripts._local_db_guard import assert_local_database  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "hk_golden"
# Written back unchanged on every run — the independent verification content.
PRESERVED = ("description", "source", "pack", "expected")
EMBEDDED = ("rate_map", "slabs", "hkg_rule_segments")


def regenerate(db, write: bool) -> int:
    from scripts.seed_hong_kong_canonical_pack import seed_hong_kong_all

    p25, p26 = seed_hong_kong_all(db)
    db.commit()
    packs = [p for p in (p25, p26)]
    changed = 0
    for path in sorted(FIXTURES.glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        ctx = case["context"]
        pay = date.fromisoformat(ctx["pay_date"])
        pack = next((p for p in packs
                     if p.effective_from and p.effective_from <= pay
                     and (p.effective_to is None or pay <= p.effective_to)), None)
        if pack is None:
            print(f"  SKIP {path.stem}: pay date {pay} is outside both pack windows")
            continue
        period = (date.fromisoformat(ctx.get("period_start") or pay.replace(day=1).isoformat()),
                  date.fromisoformat(ctx.get("period_end") or pay.isoformat()))
        rate_map, slabs, segments = _pack_rows_for_golden(db, pack, pay, period)
        before = {k: ctx.get(k) for k in EMBEDDED}
        ctx["rate_map"], ctx["slabs"], ctx["hkg_rule_segments"] = rate_map, slabs, segments
        if before == {"rate_map": rate_map, "slabs": slabs, "hkg_rule_segments": segments}:
            print(f"  ok   {path.stem}: embedded rows already current")
            continue
        changed += 1
        print(f"  {'WROTE' if write else 'STALE'} {path.stem}: {len(rate_map)} rate rows, {len(slabs)} slabs")
        if write:
            out = {k: case[k] for k in PRESERVED if k in case}
            out.update({"context": ctx})
            for k in case:                       # any extra top-level key survives
                if k not in out and k != "context":
                    out[k] = case[k]
            path.write_text(json.dumps(out, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="rewrite the fixtures (default: report only)")
    args = parser.parse_args()
    assert_local_database("regenerate_hk_golden_fixtures")
    initialize_database()
    db = SessionLocal()
    try:
        changed = regenerate(db, args.write)
        db.rollback()
    finally:
        db.close()
    print(f"{changed} fixture(s) {'rewritten' if args.write else 'need rewriting'} (expected figures untouched).")
    if changed and not args.write:
        raise SystemExit("re-run with --write after reviewing the seed change")


if __name__ == "__main__":
    main()