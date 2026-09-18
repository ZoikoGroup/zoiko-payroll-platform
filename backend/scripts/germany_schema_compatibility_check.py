"""Germany 2026 Schema Compatibility Check (READ-ONLY).

Compares the configured database schema object-by-object against the
repository's head-region migration expectations, classifying each expected
asset as:

  compatible   asset exists in the database and matches expectations
  missing      asset is absent from the database
  conflicting  asset exists but its attributes contradict the migration
               (e.g. present column with a drifted default)
  unknown      cannot be evaluated with the available evidence (I/O error,
               unreadable engine, maintenance window unconfirmed)

Features
--------
* READ-ONLY: runs inside a PostgreSQL READ ONLY transaction and executes only
  fixed `information_schema` / SELECT probes. No DDL, no DML, no writes.
* Per-migration verdicts for the head chain
  b7c8d9e0f2a3 -> d3e4f5a6b7c8 -> e4f5a6b7c8d9 -> f5a6b7c8d9e0 ->
  1a2b3c4d5e6f -> 2b3c4d5e6f70, plus a lineage-ordering cross-check.
  (Phase 8CG: the chain's first revision was renamed from f61cb4b650f4 to
  b7c8d9e0f2a3 — origin/main independently reused f61cb4b650f4 for an
  unrelated migration; see docs/GERMANY_2026_RECONCILIATION_IMPLEMENTATION_REPORT.md.)
* Usable against a restored dump: pass --engine-url to point at a clone of
  production instead of the app's configured DATABASE_URL.
* Never prints credentials (redacts passwords).

Usage
-----
  python scripts/germany_schema_compatibility_check.py [--json-out PATH]
      [--engine-url URL]

Output: JSON report plus a human summary; exit 0 with no writes performed.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

import sqlalchemy as sa

STATUS_COMPATIBLE = "compatible"
STATUS_MISSING = "missing"
STATUS_CONFLICTING = "conflicting"
STATUS_UNKNOWN = "unknown"

# Head region (topological order within the repository).
HEAD_CHAIN = [
    "b7c8d9e0f2a3",
    "d3e4f5a6b7c8",
    "e4f5a6b7c8d9",
    "f5a6b7c8d9e0",
    "1a2b3c4d5e6f",
    "2b3c4d5e6f70",
]


@dataclass
class AssetSpec:
    kind: str  # "table" | "column" | "unique_constraint" | "index"
    name: str
    table: str
    migration: str
    note: str = ""
    expect_default: Optional[str] = None
    columns: List[str] = field(default_factory=list)


# Expected assets derived from the head-region migration files (see
# docs/GERMANY_2026_MIGRATION_FULL_AUDIT.md section 6.2).
EXPECTED_ASSETS: List[AssetSpec] = [
    # d3e4f5a6b7c8 - unique constraint on elstam change list batches
    AssetSpec(
        kind="unique_constraint",
        name="uq_germany_elstam_change_list_batch_org_ref",
        table="payroll_germany_elstam_change_list_batches",
        migration="d3e4f5a6b7c8",
        columns=["organization_id", "batch_reference"],
        note="precondition: batches table exists and has 0 rows",
    ),
    # e4f5a6b7c8d9 - ELSTER boundary tables + index
    AssetSpec(kind="table", name="payroll_germany_elster_certificate_configs",
              table="payroll_germany_elster_certificate_configs", migration="e4f5a6b7c8d9"),
    AssetSpec(kind="table", name="payroll_germany_elster_transmissions",
              table="payroll_germany_elster_transmissions", migration="e4f5a6b7c8d9"),
    AssetSpec(kind="index", name="ix_germany_elster_transmission_org_period",
              table="payroll_germany_elster_transmissions", migration="e4f5a6b7c8d9",
              columns=["organization_id", "period_start"]),
    # f5a6b7c8d9e0 - minijob/midijob parameter table + indexes
    AssetSpec(kind="table", name="payroll_germany_minijob_midijob_parameters",
              table="payroll_germany_minijob_midijob_parameters", migration="f5a6b7c8d9e0"),
    AssetSpec(kind="index", name="ix_payroll_germany_minijob_midijob_parameters_id",
              table="payroll_germany_minijob_midijob_parameters", migration="f5a6b7c8d9e0"),
    AssetSpec(kind="index", name="ix_payroll_germany_minijob_midijob_parameters_parameter_code",
              table="payroll_germany_minijob_midijob_parameters", migration="f5a6b7c8d9e0"),
    AssetSpec(kind="index", name="ix_minijob_midijob_parameter_code_period",
              table="payroll_germany_minijob_midijob_parameters", migration="f5a6b7c8d9e0"),
    AssetSpec(kind="index", name="uq_minijob_midijob_parameter_one_open_period",
              table="payroll_germany_minijob_midijob_parameters", migration="f5a6b7c8d9e0",
              note="partial unique index (effective_to IS NULL)"),
    # 1a2b3c4d5e6f - payslip_items.soli + default
    AssetSpec(kind="column", name="soli", table="payslip_items",
              migration="1a2b3c4d5e6f", expect_default="0",
              note="repo: Numeric(12,2) NULL with server_default='0'"),
    # 2b3c4d5e6f70 - overtime premium tax deltas
    AssetSpec(kind="column", name="applied_wage_tax_delta",
              table="payroll_germany_overtime_premium_components", migration="2b3c4d5e6f70"),
    AssetSpec(kind="column", name="applied_soli_delta",
              table="payroll_germany_overtime_premium_components", migration="2b3c4d5e6f70"),
    AssetSpec(kind="column", name="applied_church_tax_delta",
              table="payroll_germany_overtime_premium_components", migration="2b3c4d5e6f70"),
]


def _redact(url: str) -> str:
    return re.sub(r"(://[^:/@]+):([^@/]+)@", r"\1:***@", url) if url else "<none>"


def _make_engine(engine_url: Optional[str]):
    if engine_url:
        return sa.create_engine(engine_url)
    from app.database import engine  # type: ignore

    return engine


def _tbl_exists(conn, name: str) -> bool:
    return conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=:t"),
        {"t": name},
    ).first() is not None


def _cols(conn, table: str) -> List[str]:
    rows = conn.execute(
        sa.text("SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=:t ORDER BY ordinal_position"),
        {"t": table},
    ).fetchall()
    return [r[0] for r in rows]


def _col_default(conn, table: str, col: str) -> Optional[str]:
    rows = conn.execute(
        sa.text("SELECT column_default FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=:t AND column_name=:c"),
        {"t": table, "c": col},
    ).fetchall()
    return rows[0][0] if rows else None


def _indexes(conn, table: str) -> Dict[str, List[str]]:
    rows = conn.execute(
        sa.text("SELECT i.relname, array_agg(a.attname ORDER BY array_position(ix.indkey, a.attnum)) "
                "FROM pg_class i "
                "JOIN pg_index ix ON i.oid = ix.indexrelid "
                "JOIN pg_class t ON t.oid = ix.indrelid "
                "JOIN pg_namespace n ON n.oid = t.relnamespace "
                "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey) "
                "WHERE n.nspname='public' AND t.relname=:t "
                "GROUP BY i.relname"),
        {"t": table},
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def _constraints(conn, table: str, ctype: str) -> List[str]:
    rows = conn.execute(
        sa.text("SELECT constraint_name FROM information_schema.table_constraints "
                "WHERE table_schema='public' AND table_name=:t AND constraint_type=:c"),
        {"t": table, "c": ctype},
    ).fetchall()
    return [r[0] for r in rows]


def _classify(conn, spec: AssetSpec) -> Dict[str, Any]:
    """Classify a single asset: compatible / missing / conflicting / unknown."""
    try:
        if spec.kind == "table":
            if _tbl_exists(conn, spec.table):
                return {"status": STATUS_COMPATIBLE, "detail": "table exists"}
            return {"status": STATUS_MISSING, "detail": "table absent"}
        if spec.kind == "column":
            if not _tbl_exists(conn, spec.table):
                return {"status": STATUS_MISSING, "detail": "table absent; column cannot exist"}
            cols = _cols(conn, spec.table)
            if spec.name not in cols:
                return {"status": STATUS_MISSING, "detail": "column absent"}
            if spec.expect_default is not None:
                default = _col_default(conn, spec.table, spec.name)
                if default == spec.expect_default:
                    return {"status": STATUS_COMPATIBLE,
                            "detail": f"column present, default '{default}'"}
                return {"status": STATUS_CONFLICTING,
                        "detail": f"column present but default is {(default or '<NULL>')!r} "
                                  f"(repo expects '{spec.expect_default}')"}
            return {"status": STATUS_COMPATIBLE, "detail": "column present"}
        if spec.kind == "unique_constraint":
            if not _tbl_exists(conn, spec.table):
                return {"status": STATUS_MISSING, "detail": "table absent"}
            uq = _constraints(conn, spec.table, "UNIQUE")
            if spec.name in uq:
                return {"status": STATUS_COMPATIBLE, "detail": "unique constraint present"}
            return {"status": STATUS_MISSING, "detail": f"unique constraints present: {uq or 'none'}"}
        if spec.kind == "index":
            if not _tbl_exists(conn, spec.table):
                return {"status": STATUS_MISSING, "detail": "table absent"}
            idx = _indexes(conn, spec.table)
            if spec.name in idx:
                cols = idx.get(spec.name) or []
                return {"status": STATUS_COMPATIBLE,
                        "detail": f"index present on columns {cols}"}
            return {"status": STATUS_MISSING, "detail": f"indexes present: {sorted(idx) or 'none'}"}
        return {"status": STATUS_UNKNOWN, "detail": f"unknown spec kind {spec.kind}"}
    except Exception as exc:
        return {"status": STATUS_UNKNOWN, "detail": f"probe error: {str(exc)[:200]}"}


def _lineage_ordering(conn) -> Dict[str, Any]:
    """Cross-check the lineage coherence of the head region.

    The repository chain is linear in this region. Production current version
    is read-only-compared; a matcher is reported as a WARNING if the live
    version does not exist in the local graph (foreign lineage).
    """
    try:
        rows = conn.execute(sa.text("SELECT version_num FROM alembic_version")).fetchall()
        cur = [r[0] for r in rows]
    except Exception as exc:
        return {"status": STATUS_UNKNOWN, "detail": {"error": str(exc)[:200]}}
    local = set(HEAD_CHAIN) | _local_all_revs()
    if len(cur) != 1:
        return {"status": STATUS_UNKNOWN, "detail": {"db_version": cur, "note": "!=1 alembic_version row"}}
    v = cur[0]
    if v in local:
        return {"status": STATUS_COMPATIBLE, "detail": {"db_version": v, "known_local": True}}
    return {"status": STATUS_UNKNOWN, "detail": {"db_version": v, "known_local": False,
            "note": "foreign revision id not present in local migration graph"}}


def _local_all_revs() -> set:
    versions_dir = os.path.join(_BACKEND_ROOT, "alembic", "versions")
    found = set()
    if not os.path.isdir(versions_dir):
        return found
    REV_RE = re.compile(r"revision\s*[^=]*=\s*['\"]([0-9a-f]{12})['\"]")
    for f in os.listdir(versions_dir):
        if not f.endswith(".py"):
            continue
        try:
            with open(os.path.join(versions_dir, f), "r", encoding="utf-8") as fh:
                txt = fh.read()
        except OSError:
            continue
        m = REV_RE.search(txt)
        if m:
            found.add(m.group(1))
    return found


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="READ-ONLY Germany 2026 schema compatibility check")
    parser.add_argument("--json-out", default="", help="optional path for the JSON report")
    parser.add_argument("--engine-url", default=None,
                        help="override DB URL (e.g. point at a restored dump); else app DATABASE_URL")
    args = parser.parse_args(argv)

    engine = _make_engine(args.engine_url)
    asset_results: List[Dict[str, Any]] = []
    per_migration: Dict[str, List[str]] = {r: [] for r in HEAD_CHAIN}
    try:
        with engine.connect() as conn, conn.begin():
            conn.execute(sa.text("SET TRANSACTION READ ONLY"))
            for spec in EXPECTED_ASSETS:
                r = _classify(conn, spec)
                entry = {"migration": spec.migration, "kind": spec.kind, "name": spec.name,
                         "table": spec.table, **r}
                asset_results.append(entry)
                per_migration[spec.migration].append(r["status"])
            lineage = _lineage_ordering(conn)
    except Exception as exc:
        return _emit_error_report(args, asset_results, per_migration, exc)

    migration_verdicts: List[Dict[str, Any]] = []
    for mig in HEAD_CHAIN:
        statuses = per_migration[mig]
        if not statuses:
            verdict = STATUS_COMPATIBLE
            detail = "no assets checked (no-op revision)"
        elif STATUS_CONFLICTING in statuses:
            verdict = STATUS_CONFLICTING
            detail = "at least one asset conflicts"
        elif all(s == STATUS_COMPATIBLE for s in statuses):
            verdict = STATUS_COMPATIBLE
            detail = "all assets compatible"
        else:
            verdict = STATUS_MISSING
            detail = "one or more assets missing"
        migration_verdicts.append({"migration": mig, "verdict": verdict, "statuses": statuses,
                                   "detail": detail})

    report = {
        "program": "germany_schema_compatibility_check",
        "tier": "read_only",
        "timestamp": _dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "engine_url": _redact(args.engine_url or os.environ.get("DATABASE_URL", "")),
        "head_chain": HEAD_CHAIN,
        "lineage": lineage,
        "per_migration_verdicts": migration_verdicts,
        "assets": asset_results,
    }
    text = json.dumps(report, indent=2, default=str)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"[json] wrote {args.json_out}")
    else:
        print(text)
    print()
    print(_human_summary(migration_verdicts, lineage))
    return 0


def _emit_error_report(args, asset_results, per_migration, exc) -> int:
    lines = ["READ-ONLY Germany 2026 schema compatibility check",
             f"ERROR: DB unreachable/refused ({str(exc)[:300]})",
             "No assets could be classified. No writes were attempted."]
    for line in lines:
        print(line)
    text = json.dumps({
        "program": "germany_schema_compatibility_check", "tier": "read_only",
        "timestamp": _dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "fatal_error": str(exc)[:400],
    }, indent=2, default=str)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0


def _human_summary(migration_verdicts, lineage) -> str:
    lines = ["Germany 2026 schema compatibility (head chain)", "-" * 72]
    for mv in migration_verdicts:
        lines.append(f"  [{mv['verdict']:>11}] {mv['migration']}  ({mv['detail']})")
    lines.append("-" * 72)
    lines.append(f"Lineage / alembic_version: {lineage.get('detail', lineage)}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))