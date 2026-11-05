"""
scripts/seed_nz_canonical_packs.py
----------------------------------
Seeds the canonical (organization_id IS NULL) New Zealand content as DRAFT:
one NZ-PAYROLL-2026-27 tax JurisdictionPack with every scalar parameter, the
PAYE and ESCT bands, the tax-code catalogue and every earning-class row from
engine/countries/new_zealand_content.py; the empty NZ-ELA-2028 staging pack
(Employment Leave Act 2026, never activatable before 6 August 2028); and New
Zealand's jurisdiction_service_registry row as PLANNED.

Source: ZP-NZ-ENG-001 v1.0 — the implementation specification. Every value
is traceable to SOURCE_REFERENCES S1–S10 in new_zealand_content.py and every
row is PENDING G1. The authority tables the specification does not reproduce
(IRD PAYE method, secondary/ND rates, IETC, child-support variation codes,
lump-sum method, official examples, public holidays) write no rows.

Governance: nothing is ever set Active here — activation follows signing in
the Super Admin console, a distinct approver and nz_pack_activation_refusal.
The registry row is created only when missing (an existing row is never
changed). A pack that has left Draft, or a Draft already being signed in the
console, is never re-seeded (that work would be erased). The Super Admin
console offers the same seed (POST .../new-zealand/seed-draft) while no pack
exists.

Modes:
    python -m scripts.seed_nz_canonical_packs            # DRY RUN (default): writes nothing
    python -m scripts.seed_nz_canonical_packs --verify   # read-only status of the seeded content
    python -m scripts.seed_nz_canonical_packs --apply    # write (local database guard applies)

The target is printed first with the host masked and never the password.
--apply refuses any non-local database unless the operator deliberately sets
ZOIKO_ALLOW_NONLOCAL_DB_WRITES=I_UNDERSTAND (scripts/_local_db_guard.py).

Exit codes: 0 done / nothing blocks; 2 refused (guard, or a seed blocker);
1 unexpected error.
"""
import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._local_db_guard import _configured_database_url, assert_local_database, is_local_database  # noqa: E402

NAME = "seed_nz_canonical_packs"
SPEC = "ZP-NZ-ENG-001 v1.0"


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


def seed_new_zealand(db) -> dict:
    from app.modules.payroll import new_zealand_service
    from app.modules.payroll.service import record_tax_audit

    pack = new_zealand_service.seed_nz_pack(db)
    availability = new_zealand_service.ensure_nz_service_registry_row(db)
    record_tax_audit(
        db, actor_id=None, action="update", entity_type="jurisdiction_pack", entity_id=pack.id,
        jurisdiction_pack_id=pack.id, tax_version=pack.version, legal_reference=SPEC,
        old_value=None, new_value={"status": pack.status, "availability": availability},
        reason=f"Canonical New Zealand pack {pack.pack_id} v{pack.version} seeded from {SPEC} "
               "(scripts/seed_nz_canonical_packs.py) — Draft.",
        auto_commit=False,
    )
    db.flush()
    return {"pack": pack, "availability": availability}


def report(summary: dict, out=print) -> None:
    content = summary["content"]
    out(f"Content to seed: {content['rates']} parameter row(s), {content['slabs']} table row(s); "
        f"{len(content['emptyAuthorityTables'])} authority tables stay empty until signed in the console.")
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
    parser = argparse.ArgumentParser(prog=NAME, description="Seed the Draft New Zealand pack.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="write the Draft content (default is a dry run)")
    mode.add_argument("--verify", action="store_true", help="read-only status of the seeded content")
    args = parser.parse_args(argv)

    url = _configured_database_url()
    print(f"[{NAME}] target: {describe_target(url)}")
    if args.apply:
        assert_local_database(NAME)          # exits 2 for a non-local target without the operator override

    from app.database import SessionLocal, initialize_database
    from app.modules.payroll import new_zealand_service

    if args.apply:
        initialize_database()
    db = SessionLocal()
    try:
        summary = new_zealand_service.nz_seed_summary(db)
        report(summary)
        if not args.apply:
            print(f"[{NAME}] {'verify' if args.verify else 'dry run'} — nothing written."
                  + ("" if args.verify else " Re-run with --apply to write."))
            return 2 if summary["blockers"] and not args.verify else 0
        if summary["blockers"]:
            print(f"[{NAME}] refused — nothing written.")
            return 2
        out = seed_new_zealand(db)
        db.commit()
        pack = out["pack"]
        print(f"[{NAME}] seeded {pack.pack_id} v{pack.version} (id={pack.id}) as {pack.status}; "
              f"service availability={out['availability']}")
        report(new_zealand_service.nz_seed_summary(db))
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
