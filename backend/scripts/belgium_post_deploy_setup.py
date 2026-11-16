"""Belgium (ZP-BE-ENG-001) Block I5: safe, idempotent post-deploy setup.

    python -m scripts.belgium_post_deploy_setup --environment production --dry-run     # plan + checks, no write
    python -m scripts.belgium_post_deploy_setup --environment production --confirm     # do it

Steps (each create-only, nothing existing is ever changed):
  1. the jurisdiction_service_registry row for BE exists as PLANNED (an existing row is left exactly as it is);
  2. the Draft pack BE-PAYROLL-2026 is seeded if NO Belgian pack exists (every row [PENDING G1], audited);
  3. the evidence register S1-S24 is registered as source artifacts (title + URL, not archived);
  4. the read-only verification of DEPLOY_NOTES.md §3 is printed (exit 1 when a check fails).

It NEVER signs, approves, activates or assigns anything, never sets a setting, never creates the DEMO pack, and
touches no other country. Refused: without --environment; when --environment differs from the process's
ENVIRONMENT / APP_ENV; with BE_DEMO_PACKS_ENABLED in a production environment; writes without --confirm.
It does not create tables: the schema is the deploy migrations' job (run after them).
The workbook import stays a Super Admin console action (Signing status → Content workbook).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PRODUCTION_NAMES = ("production", "prod", "live")
SHARED_COLUMNS = (("payslip_items", "be_calculation_snapshot"), ("payroll_runs", "be_approval_fingerprint"))
EXPECTED_BE_TABLES = 25          # 19 tenant / worker tables (RLS) + 6 platform tables (Blocks K, M-ECWC; no RLS)
PLATFORM_BE_TABLES = ("payroll_be_gate_evidence", "payroll_be_decisions",   # Super Admin records, no organisation
                      "payroll_be_onss_rate_files", "payroll_be_onss_rates", "payroll_be_onss_code_combinations",
                      "payroll_be_onss_type_rules")                       # M-ECWC: pack content, no organisation


class Refused(SystemExit):
    pass


def _refuse(message: str):
    raise Refused(f"Refused: {message}")


def preconditions(environment: str, confirm: bool, dry_run: bool) -> None:
    from app.config import settings

    name = (environment or "").strip().lower()
    if not name:
        _refuse("--environment <name> is required.")
    current = (os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or "").strip().lower()
    if current and current != name:
        _refuse(f"--environment {name} does not match this process's environment ({current}).")
    if bool(getattr(settings, "BE_DEMO_PACKS_ENABLED", False)) and name in PRODUCTION_NAMES:
        _refuse("BE_DEMO_PACKS_ENABLED is set in a production environment; unset it first (DEPLOY_NOTES.md §1).")
    if not dry_run and not confirm:
        _refuse("writing needs --confirm (or use --dry-run to see the plan).")


def plan(db) -> list:
    from app.modules.billing.models import JurisdictionServiceRegistry
    from app.modules.payroll.engine.countries import belgium_content as content
    from app.modules.payroll.models import JurisdictionPack, SourceArtifact

    actions = []
    row = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "BE").first()
    actions.append("registry: create BE row PLANNED" if row is None
                   else f"registry: BE row exists ({row.availability}) — left unchanged")
    packs = db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == "BE").all()
    actions.append(f"pack: seed Draft {content.BE_2026[0]}" if not packs
                   else "pack: Belgian pack(s) exist (" + ", ".join(f"{p.pack_id} {p.status}" for p in packs)
                   + ") — not seeded")
    forms = {f"ZP-BE-ENG-001 {code}" for code, *_rest in content.SOURCE_REFERENCES}
    have = {r[0] for r in db.query(SourceArtifact.form_number).filter(SourceArtifact.form_number.in_(forms))}
    actions.append(f"sources: register {len(forms - have)} of {len(forms)} (S1-S24)" if forms - have
                   else f"sources: all {len(forms)} registered — nothing to do")
    return actions


def apply(db, actor_id=None) -> list:
    from app.modules.payroll import belgium_service as be
    from app.modules.payroll.models import JurisdictionPack
    from app.modules.payroll.service import record_tax_audit

    done = [f"registry: BE availability {be.ensure_be_service_registry_row(db)}"]
    if db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == "BE").first() is None:
        pack = be.seed_belgium_pack(db)
        record_tax_audit(db, actor_id=actor_id, action="create", entity_type="jurisdiction_pack", entity_id=pack.id,
                         jurisdiction_pack_id=pack.id, tax_version=pack.version, legal_reference=be.SPEC,
                         old_value=None, new_value={"status": pack.status},
                         reason=f"Canonical {pack.pack_id} seeded as Draft by scripts/belgium_post_deploy_setup.py "
                                "(every row [PENDING G1]).", auto_commit=False)
        done.append(f"pack: seeded {pack.pack_id} v{pack.version} as {pack.status}")
    else:
        done.append("pack: a Belgian pack exists — not seeded")
    done.append(f"sources: {len(be.be_register_evidence_sources(db))} registered")
    db.flush()
    return done


def verify(db) -> list:
    """(check, ok, detail) — the read-only checks of DEPLOY_NOTES.md §3."""
    import sqlalchemy as sa
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from app.modules.billing.models import JurisdictionServiceRegistry
    from app.modules.payroll.models import JurisdictionPack

    bind = db.get_bind()
    insp = sa.inspect(bind)
    out = []
    heads = set(ScriptDirectory.from_config(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))).get_heads())
    try:
        current = {r[0] for r in db.execute(sa.text("SELECT version_num FROM alembic_version"))}
    except Exception:  # noqa: BLE001 — no alembic_version table
        current = set()
    out.append(("3.1 alembic at the head", current == heads, f"database {sorted(current)} / head {sorted(heads)}"))
    tables = sorted(t for t in insp.get_table_names() if t.startswith("payroll_be_"))
    out.append(("3.2 Belgian tables", len(tables) == EXPECTED_BE_TABLES, f"{len(tables)} payroll_be_* tables"))
    if bind.dialect.name == "postgresql":
        rls = {r[0]: (r[1], r[2]) for r in db.execute(sa.text(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class c JOIN pg_namespace n "
            "ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind = 'r' "
            "AND c.relname LIKE 'payroll\\_be\\_%'"))}
        policies = {r[0] for r in db.execute(sa.text("SELECT tablename FROM pg_policies "
                                                      "WHERE tablename LIKE 'payroll\\_be\\_%'"))}
        bad = [t for t in tables if t not in PLATFORM_BE_TABLES and (rls.get(t) != (True, True) or t not in policies)]
        out.append(("3.3 RLS enabled + forced + policy", not bad, f"missing on {bad}" if bad else "all"))
    else:
        out.append(("3.3 RLS enabled + forced + policy", True, f"n/a on {bind.dialect.name} (PostgreSQL only)"))
    for table, column in SHARED_COLUMNS:
        cols = {c["name"] for c in insp.get_columns(table)} if table in insp.get_table_names() else set()
        used = db.execute(sa.text(f"SELECT count(*) FROM {table} WHERE {column} IS NOT NULL")).scalar() \
            if column in cols else None
        out.append((f"3.4 {table}.{column}", column in cols and used == 0,
                    "missing" if column not in cols else f"{used} non-null"))
    reg = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "BE").first()
    out.append(("3.5 Belgium not available", reg is None or reg.availability == "PLANNED",
                "no row" if reg is None else reg.availability))
    active = [f"{p.pack_id} v{p.version}" for p in db.query(JurisdictionPack).filter(
        JurisdictionPack.jurisdiction_country == "BE", JurisdictionPack.status == "Active")]
    out.append(("3.6 no Belgian pack Active", not active, ", ".join(active) or "none Active"))
    rows = {t: db.execute(sa.text(f'SELECT count(*) FROM "{t}"')).scalar() for t in tables
            if t not in PLATFORM_BE_TABLES}                     # Super Admin evidence / decisions are not payroll data
    filled = {t: n for t, n in rows.items() if n}
    out.append(("3.7 no Belgian data rows", not filled, str(filled) if filled else "all empty"))
    return out


def run(db, environment: str, confirm: bool = False, dry_run: bool = False, echo=print, actor_id=None) -> dict:
    preconditions(environment, confirm, dry_run)
    echo(f"Belgium post-deploy setup — environment {environment.strip().lower()}"
         f"{' (DRY RUN: nothing is written)' if dry_run else ''}")
    url = db.get_bind().url
    echo(f"database: {url.get_backend_name()} @ {url.host or 'local'} / {url.database}")
    planned = plan(db)
    for line in planned:
        echo(("PLAN " if dry_run else "STEP ") + line)
    done = []
    if not dry_run:
        done = apply(db, actor_id)
        db.commit()
        for line in done:
            echo("DONE " + line)
    checks = verify(db)
    for name, ok, detail in checks:
        echo(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")
    return {"planned": planned, "done": done, "checks": checks, "ok": all(ok for _n, ok, _d in checks)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--environment", required=True, help="the environment this runs in (must match ENVIRONMENT)")
    ap.add_argument("--confirm", action="store_true", help="required to write")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and the checks; write nothing")
    a = ap.parse_args()
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        out = run(db, a.environment, a.confirm, a.dry_run)
    except Refused as refused:
        print(refused)
        return 2
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
