"""
scripts/seed_malaysia_canonical_packs.py
-----------------------------------------
Seeds the canonical (organization_id IS NULL) Malaysia content as DRAFT: one
MY-PAYROLL-2026 tax JurisdictionPack with every scalar parameter (national
and one row per labour territory) and every earning-class row from
engine/countries/malaysia_content.py, plus Malaysia's
jurisdiction_service_registry row as PLANNED.

Source: ZP-MY-ENG-001 v1.0. Every row is written UNSIGNED ([PENDING G1]);
contribution schedules, public holidays and PCB tables are NOT seeded — they
are loaded from the official documents through the statutory workbook and
signed in the Super Admin console.

Governance: nothing is ever set Active here — activation follows signing, a
distinct approver and my_pack_activation_refusal. The registry row is created
only when missing (an existing row is never changed). A pack that has left
Draft, or a Draft already being signed (a console edit or signature, a signed
row, or any schedule / holiday / table row), is never re-seeded: that work
would be erased. The Super Admin console offers the same seed
(POST /api/super-admin/compliance/malaysia/seed-draft) while no pack exists —
the preferred production path (no shell, no environment file).

Modes:
    python -m scripts.seed_malaysia_canonical_packs            # DRY RUN (default): writes nothing
    python -m scripts.seed_malaysia_canonical_packs --verify   # read-only status of the seeded content
    python -m scripts.seed_malaysia_canonical_packs --apply    # write (local database guard applies)

The target is printed first with the host masked and never the password.
--apply refuses any non-local database unless the operator deliberately sets
ZOIKO_ALLOW_NONLOCAL_DB_WRITES=I_UNDERSTAND (scripts/_local_db_guard.py). It
also checks the address the APP binds to (PAYROLL_DATABASE_URL from the
environment, else the app settings) — never a DATABASE_URL the app ignores.

Exit codes: 0 done / nothing blocks; 2 refused (guard, or a seed blocker);
1 unexpected error.
"""
import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._local_db_guard import assert_local_database, is_local_database  # noqa: E402

NAME = "seed_malaysia_canonical_packs"
SPEC = "ZP-MY-ENG-001 v1.0"
_OVERRIDE = ("ZOIKO_ALLOW_NONLOCAL_DB_WRITES", "I_UNDERSTAND")


def app_database_url() -> str:
    """The URL app.database binds to: PAYROLL_DATABASE_URL from the
    environment, else the app settings (which read it from the environment
    file). DATABASE_URL is deliberately ignored — the app never uses it."""
    value = (os.environ.get("PAYROLL_DATABASE_URL") or "").strip()
    if value:
        return value
    try:
        from app.config import settings

        return (getattr(settings, "PAYROLL_DATABASE_URL", "") or "").strip()
    except Exception:
        return ""


def describe_target(url: str) -> str:
    """Database kind, host (masked unless local) and database name — never a
    password or the full URL."""
    if not url:
        return "<not configured>"
    try:
        parsed = urlparse(url)
    except Exception:
        return "<unparseable database url>"
    scheme = (parsed.scheme or "?").split("+")[0]
    if scheme.startswith("sqlite"):
        return f"sqlite ({Path(parsed.path).name or 'in-memory'})"
    host = parsed.hostname or ""
    shown = host if is_local_database(url) else (host[:3] + "***" if host else "<socket>")
    return f"{scheme} host={shown} database={parsed.path.lstrip('/') or '?'}"


def refuse_unless_app_target_local(url: str) -> None:
    """Second check on --apply: the app's own target must be local too (the
    shared guard may resolve a different variable). Same operator override."""
    if is_local_database(url) or os.environ.get(_OVERRIDE[0]) == _OVERRIDE[1]:
        return
    print(f"[{NAME}] REFUSING: the app's database ({describe_target(url)}) is not local. "
          f"Use the Super Admin 'seed draft' action in production.", file=sys.stderr)
    raise SystemExit(2)


def seed_malaysia(db) -> dict:
    from app.modules.payroll import malaysia_service
    from app.modules.payroll.service import record_tax_audit

    pack = malaysia_service.seed_malaysia_pack(db)
    availability = malaysia_service.ensure_my_service_registry_row(db)
    record_tax_audit(
        db, actor_id=None, action="update", entity_type="jurisdiction_pack", entity_id=pack.id,
        jurisdiction_pack_id=pack.id, tax_version=pack.version, legal_reference=SPEC,
        old_value=None, new_value={"status": pack.status, "availability": availability},
        reason=f"Canonical Malaysia pack {pack.pack_id} v{pack.version} seeded from {SPEC} "
               "(scripts/seed_malaysia_canonical_packs.py) — Draft, every row unsigned.",
        auto_commit=False,
    )
    db.flush()
    return {"pack": pack, "availability": availability}


def report(summary: dict, out=print) -> None:
    content = summary["content"]
    out(f"Content to seed: {content['rates']} parameter row(s), {content['slabs']} earning-class row(s); "
        f"{len(content['emptyTables'])} tables stay empty until loaded from the official documents "
        f"({', '.join(content['emptyTables'])}).")
    if not summary["packs"]:
        out("Existing packs: none.")
    for p in summary["packs"]:
        out(f"Existing pack {p['packId']} v{p['version']} (id={p['id']}): {p['status']}, {p['rates']} parameter "
            f"row(s), {p['slabs']} table row(s), {p['pending']} pending G1.")
        out(f"  Activation: {p['activationRefusal'] or 'nothing blocks it (approval by a non-editor, then Activate)'}")
    out(f"Service registry: {summary['registry'] or 'no row (seed creates it as PLANNED)'}")
    for blocker in summary["blockers"]:
        out(f"BLOCKED: {blocker}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog=NAME, description="Seed the Draft Malaysia pack.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="write the Draft content (default is a dry run)")
    mode.add_argument("--verify", action="store_true", help="read-only status of the seeded content")
    args = parser.parse_args(argv)

    url = app_database_url()
    print(f"[{NAME}] target: {describe_target(url)}")
    if args.apply:
        assert_local_database(NAME)          # exits 2 for a non-local target without the operator override
        refuse_unless_app_target_local(url)  # and the app's own target must agree

    from app.database import SessionLocal, initialize_database
    from app.modules.payroll import malaysia_service

    if args.apply:
        initialize_database()
    db = SessionLocal()
    try:
        summary = malaysia_service.my_seed_summary(db)
        report(summary)
        if not args.apply:
            print(f"[{NAME}] {'verify' if args.verify else 'dry run'} — nothing written."
                  + ("" if args.verify else " Re-run with --apply to write."))
            return 2 if summary["blockers"] and not args.verify else 0
        if summary["blockers"]:
            print(f"[{NAME}] refused — nothing written.")
            return 2
        out = seed_malaysia(db)
        db.commit()
        pack = out["pack"]
        print(f"[{NAME}] seeded {pack.pack_id} v{pack.version} (id={pack.id}) as {pack.status}; "
              f"service availability={out['availability']}")
        report(malaysia_service.my_seed_summary(db))
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
