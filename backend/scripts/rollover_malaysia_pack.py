"""
scripts/rollover_malaysia_pack.py
---------------------------------
Creates next tax year's Malaysia pack as a DRAFT copy of an existing one
(malaysia_service.rollover_malaysia_pack): MY-PAYROLL-2026 -> MY-PAYROLL-2027.

Every copied row is re-marked [PENDING G1] — values are prefilled, but nothing
calculates until a Super Admin re-signs each row against the new year's
official source and a distinct approver activates the pack. Public holidays,
PCB tables and authority examples are NOT copied (year-specific: load them
fresh). Rows that expired before the new year are dropped. The source pack is
never changed. Refused when the target year's pack already exists.

The Super Admin console offers the same action
(POST /api/super-admin/compliance/malaysia/packs/{id}/rollover) — the
preferred production path (no shell, no environment file).

Modes:
    python -m scripts.rollover_malaysia_pack --from MY-PAYROLL-2026            # DRY RUN (default)
    python -m scripts.rollover_malaysia_pack --from MY-PAYROLL-2026 --apply    # write (local database guard)

Same database checks as scripts/seed_malaysia_canonical_packs.py: the target
is printed masked; --apply refuses a non-local database (shared guard AND the
app's own PAYROLL_DATABASE_URL) unless the operator sets
ZOIKO_ALLOW_NONLOCAL_DB_WRITES=I_UNDERSTAND.

Exit codes: 0 done / nothing blocks; 2 refused; 1 unexpected error.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._local_db_guard import assert_local_database  # noqa: E402
from scripts.seed_malaysia_canonical_packs import (  # noqa: E402
    app_database_url, describe_target, refuse_unless_app_target_local,
)

NAME = "rollover_malaysia_pack"


def report(plan: dict, out=print) -> None:
    if plan.get("targetPackId"):
        out(f"Roll {plan['sourcePackId']} ({plan['sourceStatus']}) -> {plan['targetPackId']} Draft, "
            f"{plan['effectiveFrom']} to {plan['effectiveTo']}: {plan['rates']} parameter row(s), "
            f"{plan['slabs']} table row(s), every one PENDING G1.")
        out(f"Not copied (load fresh for the new year): {', '.join(plan['notCopied'])}.")
    if plan["refusal"]:
        out(f"BLOCKED: {plan['refusal']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog=NAME, description="Roll a Malaysia pack into the next tax year (Draft).")
    parser.add_argument("--from", dest="source", required=True, help="source pack id, e.g. MY-PAYROLL-2026")
    parser.add_argument("--version", default="1.0", help="source pack version (default 1.0)")
    parser.add_argument("--apply", action="store_true", help="write the Draft pack (default is a dry run)")
    args = parser.parse_args(argv)

    url = app_database_url()
    print(f"[{NAME}] target: {describe_target(url)}")
    if args.apply:
        assert_local_database(NAME)
        refuse_unless_app_target_local(url)

    from app.database import SessionLocal, initialize_database
    from app.modules.payroll import malaysia_service
    from app.modules.payroll.models import JurisdictionPack

    if args.apply:
        initialize_database()
    db = SessionLocal()
    try:
        source = (db.query(JurisdictionPack)
                  .filter(JurisdictionPack.jurisdiction_country == "MY", JurisdictionPack.pack_id == args.source,
                          JurisdictionPack.version == args.version).first())
        if source is None:
            print(f"[{NAME}] no Malaysia pack {args.source} v{args.version} — nothing written.")
            return 2
        plan = malaysia_service.my_rollover_plan(db, source)
        report(plan)
        if plan["refusal"]:
            print(f"[{NAME}] refused — nothing written.")
            return 2
        if not args.apply:
            print(f"[{NAME}] dry run — nothing written. Re-run with --apply to write.")
            return 0
        pack = malaysia_service.rollover_malaysia_pack(db, source, None, "scripts/rollover_malaysia_pack.py")
        db.commit()
        print(f"[{NAME}] created {pack.pack_id} v{pack.version} (id={pack.id}) as {pack.status}.")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
