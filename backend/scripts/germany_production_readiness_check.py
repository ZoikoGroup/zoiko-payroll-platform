"""Germany 2026 Production Readiness Check (READ-ONLY).

Performs a read-only inspection of the configured payroll database and this
repository to assess production readiness for the Germany 2026 payroll program.

Guarantees
----------
* Executes ONLY fixed SELECT / information_schema / SHOW probes embedded below.
  No writes, no DDL, no DML, no alembic upgrade/stamp.
* Forces the session into a PostgreSQL READ ONLY transaction before querying;
  an accidental write would be rejected by the server.
* Never prints or persists credentials (database URL password is redacted).
* Fails gracefully with explicit UNKNOWN results when the DB is unreachable,
  so static-only use remains possible.

Inspection areas (14)
---------------------
 1. db_connectivity         5. soli_drift                9.  pap_readiness        13. security_posture
 2. alembic_version_current 6. germany_registries_rows   10. registry_seed_status 14. readiness_summary
 3. migration_inventory     7. elstam_readiness          11. hardcoded_defaults_static
 4. head_region_objects     8. elster_readiness          12. model_migration_drift

Usage
-----
  python scripts/germany_production_readiness_check.py [--json-out PATH]
      [--expect-head REV] [--expect-prod-version REV] [--static-only]

Run from the backend/ directory so the app's configured database URL (usually
the shared production database) resolves.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from typing import Any, Dict, List, Tuple

import sqlalchemy as sa

STATUS_OK = "PASS"
STATUS_WARN = "WARN"
STATUS_FAIL = "FAIL"
STATUS_UNKNOWN = "UNKNOWN"

# --------------------------------------------------------------------------- #
# Head-region expected objects (Phase 2 compatibility model)
# --------------------------------------------------------------------------- #
HEAD_REGION_EXPECTATIONS: List[Tuple[str, str]] = [
    ("unique_constraint", "uq_germany_elstam_change_list_batch_org_ref"),
    ("table", "payroll_germany_elster_certificate_configs"),
    ("table", "payroll_germany_elster_transmissions"),
    ("table", "payroll_germany_minijob_midijob_parameters"),
    ("column", "payslip_items.soli"),
    ("delta_columns", "payroll_germany_overtime_premium_components.applied_*_delta"),
]

GERMANY_REGISTRY_TABLES = [
    "payroll_germany_health_funds",
    "payroll_germany_contribution_ceilings",
    "payroll_germany_pv_configurations",
    "payroll_germany_health_fund_u1_tariffs",
    "payroll_germany_earning_taxability_rules",
    "payroll_germany_church_tax_exceptions",
    "payroll_germany_accident_insurance_profiles",
    "payroll_germany_overtime_grundlohn_caps",
    "payroll_germany_overtime_premium_categories",
]

# Tables that will only exist after the missing head-region migrations run.
PENDING_MIGRATION_TABLES = [
    "payroll_germany_minijob_midijob_parameters",
    "payroll_germany_elster_certificate_configs",
    "payroll_germany_elster_transmissions",
]


def _redact(url: str) -> str:
    return re.sub(r"(://[^:/@]+):([^@/]+)@", r"\1:***@", url) if url else "<none>"


def _read_repo_db_url() -> Tuple[str, bool]:
    """Best-effort read of DATABASE_URL/DATABASE_DSN from backend/.env (redacted)."""
    candidates = []
    for root in (os.getcwd(), os.path.dirname(os.path.dirname(os.path.abspath(__file__)))):
        candidates.append(os.path.join(root, ".env"))
    url = None
    for path in candidates:
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line.startswith("DATABASE") and "=" in line:
                            _key, _, val = line.partition("=")
                            if val:
                                url = val.strip().strip('"').strip("'")
                                break
            except OSError:
                pass
        if url:
            break
    if not url:
        return "<not-found>", False
    return _redact(url), "sslmode=" in url.lower() or "?ssl" in url.lower()


_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)


def _app_engine():
    from app.database import engine  # type: ignore

    return engine


def _load_models():
    from app.modules.payroll.models import (  # type: ignore
        GermanyOvertimePremiumComponent,
        PayrollEmployee,
        PayslipItem,
    )

    return PayslipItem, PayrollEmployee, GermanyOvertimePremiumComponent


# --------------------------------------------------------------------------- #
# Static migration inventory (local alembic/versions directory)
# --------------------------------------------------------------------------- #
REV_RE = re.compile(r"revision\s*[^=]*=\s*['\"]([0-9a-f]{12})['\"]")


def _migration_inventory(versions_dir: str) -> Dict[str, Any]:
    files = [f for f in os.listdir(versions_dir) if f.endswith(".py")] if os.path.isdir(versions_dir) else []
    rev_down: Dict[str, List[str]] = {}
    by_file: Dict[str, str] = {}
    for f in files:
        path = os.path.join(versions_dir, f)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                txt = fh.read()
        except OSError:
            continue
        m = REV_RE.search(txt)
        if not m:
            continue
        rev = m.group(1)
        by_file[f] = rev
        idx = txt.find("down_revision")
        if idx == -1:
            rev_down[rev] = []
            continue
        # capture the whole down_revision value (may span multiple lines)
        seg = txt[idx:]
        mid = seg.find("=")
        if mid == -1:
            rev_down[rev] = []
            continue
        val = seg[mid + 1:]
        end = len(val)
        for stop_marker, partial in (("branch_labels", -1), ("depends_on", -1), ("def ", -1)):
            pos = val.find(stop_marker)
            if pos != -1:
                end = min(end, pos)
        head = val[:end]
        down = [t for t in re.findall(r"['\"]([0-9a-f]{12})['\"]", head)]
        if not down and "None" in head.split("\n")[0]:
            down = []
        rev_down[rev] = down
    roots = [r for r, ds in rev_down.items() if not ds]
    reffed = {p for ds in rev_down.values() for p in ds}
    heads = [r for r in rev_down if r not in reffed]
    dangling = [(r, p) for r, ds in rev_down.items() for p in ds if p not in rev_down]
    children = {r: [] for r in rev_down}
    for r, ds in rev_down.items():
        for p in ds:
            if p in children:
                children[p].append(r)
    seen: set = set()
    stack = list(roots)
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(children[cur])
    orphans = sorted(set(rev_down) - seen)
    return {
        "total": len(by_file),
        "roots": roots,
        "heads": heads,
        "dangling_down_references": dangling,
        "orphans": orphans,
    }


# --------------------------------------------------------------------------- #
# DB helpers (fixed SELECT probes only)
# --------------------------------------------------------------------------- #
def _tbl_exists(conn, table: str) -> bool:
    row = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=:t"),
        {"t": table},
    ).first()
    return row is not None


def _count(conn, table: str) -> int:
    row = conn.execute(sa.text(f'SELECT count(*) AS n FROM "{table}"')).one()
    return int(row[0])


def _cols(conn, table: str) -> List[str]:
    rows = conn.execute(
        sa.text("SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=:t ORDER BY ordinal_position"),
        {"t": table},
    ).fetchall()
    return [r[0] for r in rows]


# --------------------------------------------------------------------------- #
# Inspections
# --------------------------------------------------------------------------- #
def inspect_connectivity(conn) -> Dict[str, Any]:
    try:
        row = conn.execute(sa.text("SELECT version() AS v")).one()
        url, _ssl = _read_repo_db_url()
        return {"status": STATUS_OK, "detail": {"postgresql_version": str(row[0])[:120], "db_url": url}}
    except Exception as exc:
        return {"status": STATUS_FAIL, "detail": {"error": str(exc)[:300]}}


def inspect_alembic_current(conn, repo_head: str, expect_prod: str) -> Dict[str, Any]:
    try:
        rows = conn.execute(sa.text("SELECT version_num FROM alembic_version")).fetchall()
        values = [r[0] for r in rows]
        detail = {"db_version": values, "repo_head": repo_head}
        if len(values) != 1:
            detail["note"] = "expected exactly one alembic_version row"
            return {"status": STATUS_FAIL, "detail": detail}
        cur = values[0]
        if cur == repo_head:
            detail["verdict"] = "db matches repo head"
            return {"status": STATUS_OK, "detail": detail}
        detail["expect_prod_version_arg"] = expect_prod or "<not provided>"
        detail["note"] = ("db revision differs from repo head; on the hybrid/foreign lineage "
                          "this alone is expected pre-recovery")
        return {"status": STATUS_WARN, "detail": detail}
    except Exception as exc:
        return {"status": STATUS_UNKNOWN, "detail": {"error": str(exc)[:300]}}


def inspect_head_region_objects(conn) -> Dict[str, Any]:
    tables = _cols_public(conn)
    soli_default = "<absent>"
    if "payslip_items" in tables:
        row = conn.execute(
            sa.text("SELECT COALESCE(column_default, '<NULL>') FROM information_schema.columns "
                    "WHERE table_name='payslip_items' AND column_name='soli'")
        ).first()
        soli_default = row[0] if row else "<absent>"
    deltas: List[str] = []
    if "payroll_germany_overtime_premium_components" in tables:
        rows = conn.execute(
            sa.text("SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='payroll_germany_overtime_premium_components' "
                    "AND column_name IN ('applied_wage_tax_delta','applied_soli_delta','applied_church_tax_delta') "
                    "ORDER BY column_name")
        ).fetchall()
        deltas = [r[0] for r in rows]
    present: List[str] = []
    missing: List[str] = []
    for kind, name in HEAD_REGION_EXPECTATIONS:
        if kind == "table":
            ok = name in tables
        elif kind == "unique_constraint":
            row = conn.execute(
                sa.text("SELECT count(*) FROM information_schema.table_constraints WHERE constraint_name=:n"),
                {"n": name},
            ).first()
            ok = bool(row[0])
        elif kind == "column":
            ok = soli_default != "<absent>"
        else:
            ok = len(deltas) == 3
        (present if ok else missing).append(name)
    status = STATUS_OK if not missing else STATUS_WARN
    return {"status": status, "detail": {
        "present": sorted(present), "missing": sorted(missing),
        "soli_column_default": soli_default,
        "overtime_delta_columns_present": sorted(deltas),
    }}


def _cols_public(conn) -> set:
    rows = conn.execute(
        sa.text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
    ).fetchall()
    return {r[0] for r in rows}


def inspect_germany_registries_rows(conn) -> Dict[str, Any]:
    info: List[Dict[str, Any]] = []
    for t in GERMANY_REGISTRY_TABLES:
        if not _tbl_exists(conn, t):
            info.append({"table": t, "exists": False})
            continue
        try:
            n = _count(conn, t)
        except Exception as exc:
            n = str(exc)[:100]
        info.append({"table": t, "exists": True, "row_count": n})
    nonempty = [i["table"] for i in info if isinstance(i.get("row_count"), int) and i["row_count"] > 0]
    return {"status": STATUS_OK if not nonempty else STATUS_WARN,
            "detail": {"registries": info, "non_empty": nonempty}}


def inspect_germany_feature_tables(conn) -> Dict[str, Any]:
    rows = conn.execute(
        sa.text("SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name LIKE 'payroll_germany%' ORDER BY table_name")
    ).fetchall()
    names = [r[0] for r in rows]
    return {"status": STATUS_OK, "detail": {"count": len(names), "tables": names}}


def inspect_elstam(conn) -> Dict[str, Any]:
    tbl = "payroll_germany_elstam_change_list_batches"
    imp = "payroll_germany_elstam_import_attempts"
    tb = _tbl_exists(conn, tbl)
    ti = _tbl_exists(conn, imp)
    uq: List[str] = []
    if tb:
        rows = conn.execute(
            sa.text("SELECT constraint_name FROM information_schema.table_constraints "
                    "WHERE table_name=:t AND constraint_type='UNIQUE'"),
            {"t": tbl},
        ).fetchall()
        uq = [r[0] for r in rows]
    status = STATUS_OK if (tb and ti and any(n.startswith("uq_germany_elstam") for n in uq)) else STATUS_WARN
    return {"status": status, "detail": {
        "batches_table": tb, "import_attempts_table": ti, "unique_constraints": uq}}


def inspect_elster(conn) -> Dict[str, Any]:
    names = ["payroll_germany_elster_certificate_configs", "payroll_germany_elster_transmissions"]
    present = [n for n in names if _tbl_exists(conn, n)]
    status = STATUS_OK if len(present) == len(names) else STATUS_WARN
    return {"status": status, "detail": {"expected": names, "present": present}}


def inspect_pap(conn) -> Dict[str, Any]:
    names = ["pap_assets", "pap_releases", "payroll_germany_pap_release_governance",
             "payroll_germany_pap_algorithm_assets"]
    return {"status": STATUS_OK, "detail": {"tables": {n: _tbl_exists(conn, n) for n in names}}}


def inspect_soli_drift(conn) -> Dict[str, Any]:
    try:
        rows = conn.execute(
            sa.text("SELECT COALESCE(column_default, '<NULL>'), is_nullable FROM information_schema.columns "
                    "WHERE table_name='payslip_items' AND column_name='soli'")
        ).fetchall()
        if not rows:
            return {"status": STATUS_FAIL, "detail": {"present": False}}
        default, nullable = rows[0][0], rows[0][1]
        status = STATUS_OK if default == "0" else STATUS_WARN
        return {"status": status, "detail": {
            "present": True, "default_expr": default, "nullable": nullable, "repo_expected_default": "0"}}
    except Exception as exc:
        return {"status": STATUS_UNKNOWN, "detail": {"error": str(exc)[:300]}}


def inspect_registry_seed_status(conn) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    for t in GERMANY_REGISTRY_TABLES:
        if not _tbl_exists(conn, t):
            results.append({"table": t, "exists": False})
            continue
        rows = conn.execute(
            sa.text("SELECT status, count(*) AS n FROM {t} GROUP BY status ORDER BY status".format(t=t))
        ).fetchall()
        results.append({"table": t, "exists": True, "by_status": {r[0]: int(r[1]) for r in rows}})
    published = any((r.get("by_status") or {}).get("PUBLISHED") for r in results if r.get("exists"))
    return {"status": STATUS_WARN if published else STATUS_OK,
            "detail": {"registries": results, "any_published": bool(published)}}


_EXPECTED_GERMANY_LAND_CODES = [
    "DE-BW", "DE-BY", "DE-BE", "DE-BB", "DE-HB", "DE-HH", "DE-HE", "DE-MV",
    "DE-NI", "DE-NW", "DE-RP", "DE-SL", "DE-SN", "DE-ST", "DE-SH", "DE-TH",
]


def inspect_germany_land_jurisdiction_packs(conn) -> Dict[str, Any]:
    """All-16-Länder coverage + integrity, read-only. Mirrors the pattern
    every other inspect_* function in this file already uses (fixed
    SELECTs only, no writes) — added for the Germany 2026 all-Länder
    jurisdiction task, since none of the 13 pre-existing inspection areas
    say anything about per-Land JurisdictionPack coverage."""
    if not _tbl_exists(conn, "payroll_jurisdiction_packs"):
        return {"status": STATUS_FAIL, "detail": {"note": "payroll_jurisdiction_packs table missing"}}

    federal_rows = conn.execute(
        sa.text(
            "SELECT id, pack_id, status FROM payroll_jurisdiction_packs "
            "WHERE jurisdiction_country='DE' AND jurisdiction_state IS NULL AND pack_type='tax'"
        )
    ).fetchall()
    active_federal = [r for r in federal_rows if r[2] == "Active"]

    land_rows = conn.execute(
        sa.text(
            "SELECT jurisdiction_state, id, pack_id, status, parent_pack_id "
            "FROM payroll_jurisdiction_packs "
            "WHERE jurisdiction_country='DE' AND jurisdiction_state IS NOT NULL AND pack_type='tax' "
            "ORDER BY jurisdiction_state"
        )
    ).fetchall()
    by_land: Dict[str, List[Any]] = {}
    for r in land_rows:
        by_land.setdefault(r[0], []).append(r)

    laender: List[Dict[str, Any]] = []
    for code in _EXPECTED_GERMANY_LAND_CODES:
        rows = by_land.get(code, [])
        active = [r for r in rows if r[3] == "Active"]
        laender.append({
            "land_code": code,
            "pack_count": len(rows),
            "active_count": len(active),
            "active_pack_id": active[0][2] if len(active) == 1 else None,
            "parent_pack_id": active[0][4] if len(active) == 1 else None,
        })

    missing = [l["land_code"] for l in laender if l["active_count"] == 0]
    duplicate_active = [l["land_code"] for l in laender if l["active_count"] > 1]
    unexpected_codes = sorted(set(by_land) - set(_EXPECTED_GERMANY_LAND_CODES))
    orphan_parent = [
        l["land_code"] for l in laender
        if l["active_pack_id"] and active_federal and l["parent_pack_id"] not in (r[0] for r in active_federal)
    ]

    if not active_federal or missing or duplicate_active or unexpected_codes:
        status = STATUS_FAIL
    elif orphan_parent:
        status = STATUS_WARN
    else:
        status = STATUS_OK

    return {"status": status, "detail": {
        "federal_active_pack_count": len(active_federal),
        "laender": laender,
        "ready_count": sum(1 for l in laender if l["active_count"] == 1),
        "total_expected": len(_EXPECTED_GERMANY_LAND_CODES),
        "missing_active": missing,
        "duplicate_active": duplicate_active,
        "unexpected_land_codes": unexpected_codes,
        "active_pack_with_no_matching_active_federal_parent": orphan_parent,
    }}


def inspect_hardcoded_static(workspace_root: str) -> Dict[str, Any]:
    base = os.path.join(workspace_root, "app", "modules", "payroll")
    files = {
        "hardcoded_defaults.py": os.path.isfile(os.path.join(base, "hardcoded_defaults.py")),
        "engine/fallback_registry.py": os.path.isfile(os.path.join(base, "engine", "fallback_registry.py")),
    }
    pap_adapter = os.path.join(base, "engine", "jurisdictions", "germany", "pap", "adapter.py")
    source_finality: str | None = None
    if os.path.isfile(pap_adapter):
        with open(pap_adapter, "r", encoding="utf-8") as fh:
            for line in fh:
                if "PAP_SOURCE_FINALITY" in line and "=" in line and "def " not in line and ":" not in line:
                    source_finality = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    return {"status": STATUS_OK, "detail": {
        "files": files, "pap_source_finality": source_finality,
        "note": "static presence check only; values audited in Phase 7"}}


def inspect_model_drift(conn) -> Dict[str, Any]:
    try:
        PayslipItem, PayrollEmployee, GermanyOvertimePremiumComponent = _load_models()
    except Exception as exc:
        return {"status": STATUS_UNKNOWN, "detail": {"error": f"model import failed: {str(exc)[:300]}"}}
    models = {
        "payslip_items": PayslipItem.__table__,
        "payroll_employees": PayrollEmployee.__table__,
        "payroll_germany_overtime_premium_components": GermanyOvertimePremiumComponent.__table__,
    }
    drift: List[Dict[str, Any]] = []
    for table_name, tbl in models.items():
        if not _tbl_exists(conn, table_name):
            drift.append({"table": table_name, "problem": "table missing in live"})
            continue
        live = set(_cols(conn, table_name))
        expected = {c.name for c in tbl.columns}
        missing = sorted(expected - live)
        extra = sorted(live - expected)
        drift.append({"table": table_name, "expected_columns": len(expected), "live_columns": len(live),
                      "missing_in_live": missing, "extra_in_live": extra[:20], "extra_total": len(extra)})
    has_missing = any(d.get("missing_in_live") for d in drift)
    return {"status": STATUS_WARN if has_missing else STATUS_OK, "detail": {"tables": drift}}


def inspect_security(conn, url_has_ssl: bool) -> Dict[str, Any]:
    try:
        rows = conn.execute(sa.text("SHOW transaction_read_only")).fetchall()
        tx_ro = str(rows[0][0]) if rows else "<n/a>"
    except Exception:
        tx_ro = "<n/a>"
    return {"status": STATUS_OK, "detail": {
        "session_read_only": tx_ro, "url_has_sslmode": url_has_ssl,
        "password_redacted_in_output": True,
        "maintenance_mode_hint": "confirm app maintenance mode operator-side; not visible from DB"}}


def summarize(areas: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    counts = {STATUS_OK: 0, STATUS_WARN: 0, STATUS_FAIL: 0, STATUS_UNKNOWN: 0}
    for a in areas.values():
        counts[a["status"]] = counts.get(a["status"], 0) + 1
    critical = ["db_connectivity", "alembic_version_current", "head_region_objects",
                "soli_drift", "migration_inventory"]
    blockers = [k for k in critical if areas.get(k, {}).get("status") == STATUS_FAIL]
    if blockers:
        decision = "PRODUCTION_NOT_READY"
    elif counts[STATUS_WARN] or counts[STATUS_UNKNOWN]:
        decision = "EVIDENCE_OR_RECONCILIATION_REQUIRED"
    else:
        decision = "PRODUCTION_READY_OR_OPERATOR_CONFIRM"
    return {"decision": decision, "status_counts": counts, "critical_blockers": blockers}


def _detect_head(workspace_root: str) -> str:
    heads = _migration_inventory(os.path.join(workspace_root, "alembic", "versions")).get("heads", [])
    return heads[0] if heads else ""


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="READ-ONLY Germany 2026 production readiness check")
    parser.add_argument("--json-out", default="", help="optional path for the JSON report")
    parser.add_argument("--expect-head", default="", help="expected alembic head (default: detected)")
    parser.add_argument("--expect-prod-version", default="", help="expected prod alembic_version (optional)")
    parser.add_argument("--static-only", action="store_true", help="skip DB access; static checks only")
    default_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser.add_argument("--workspace-root", default=default_root, help="repo backend root")
    args = parser.parse_args(argv)
    if not args.expect_head:
        args.expect_head = _detect_head(args.workspace_root)

    areas: Dict[str, Dict[str, Any]]
    db_ok = False
    if args.static_only:
        areas = {k: {"status": STATUS_UNKNOWN, "detail": {"note": "static-only run; DB not reached"}}
                 for k in ("db_connectivity", "alembic_version_current", "head_region_objects", "soli_drift",
                           "germany_registries_rows", "germany_feature_tables", "elstam_readiness",
                           "elster_readiness", "pap_readiness", "registry_seed_status",
                           "germany_land_jurisdiction_packs",
                           "model_migration_drift", "security_posture")}
        areas["migration_inventory"] = {
            "status": STATUS_OK, "detail": _migration_inventory(
                os.path.join(args.workspace_root, "alembic", "versions"))}
        areas["hardcoded_defaults_static"] = inspect_hardcoded_static(args.workspace_root)
    else:
        try:
            engine = _app_engine()
            with engine.connect() as conn, conn.begin():
                conn.execute(sa.text("SET TRANSACTION READ ONLY"))
                areas = {
                    "db_connectivity": inspect_connectivity(conn),
                    "alembic_version_current": inspect_alembic_current(conn, args.expect_head,
                                                                       args.expect_prod_version),
                    "migration_inventory": {"status": STATUS_OK, "detail": _migration_inventory(
                        os.path.join(args.workspace_root, "alembic", "versions"))},
                    "head_region_objects": inspect_head_region_objects(conn),
                    "soli_drift": inspect_soli_drift(conn),
                    "germany_registries_rows": inspect_germany_registries_rows(conn),
                    "germany_feature_tables": inspect_germany_feature_tables(conn),
                    "elstam_readiness": inspect_elstam(conn),
                    "elster_readiness": inspect_elster(conn),
                    "pap_readiness": inspect_pap(conn),
                    "registry_seed_status": inspect_registry_seed_status(conn),
                    "germany_land_jurisdiction_packs": inspect_germany_land_jurisdiction_packs(conn),
                    "hardcoded_defaults_static": inspect_hardcoded_static(args.workspace_root),
                    "model_migration_drift": inspect_model_drift(conn),
                }
                _url, url_has_ssl = _read_repo_db_url()
                areas["security_posture"] = inspect_security(conn, url_has_ssl)
            db_ok = True
        except Exception as exc:
            areas = {"db_connectivity": {"status": STATUS_FAIL, "detail": {"error": str(exc)[:400]}}}
            for k in ("alembic_version_current", "head_region_objects", "soli_drift", "germany_registries_rows",
                      "germany_feature_tables", "elstam_readiness", "elster_readiness", "pap_readiness",
                      "registry_seed_status", "germany_land_jurisdiction_packs", "model_migration_drift"):
                areas[k] = {"status": STATUS_UNKNOWN, "detail": {"note": "DB unreachable"}}
            areas["migration_inventory"] = {"status": STATUS_OK, "detail": _migration_inventory(
                os.path.join(args.workspace_root, "alembic", "versions"))}
            areas["hardcoded_defaults_static"] = inspect_hardcoded_static(args.workspace_root)
            areas["security_posture"] = {"status": STATUS_UNKNOWN, "detail": {"note": "DB unreachable"}}
    areas["readiness_summary"] = summarize(areas)

    report = {
        "program": "germany_production_readiness_check",
        "tier": "read_only",
        "read_only": True,
        "timestamp": _dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "db_reached": db_ok,
        "expectations": {"repo_head": args.expect_head,
                         "expect_prod_version": args.expect_prod_version or "<not provided>"},
        "areas": areas,
    }
    text = json.dumps(report, indent=2, default=str)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"[json] wrote {args.json_out}")
    else:
        print(text)
    print()
    print(_human_summary(areas))
    return 0


def _human_summary(areas: Dict[str, Dict[str, Any]]) -> str:
    n_probed = sum(1 for k in areas if k != "readiness_summary")
    lines = [f"Germany 2026 production readiness (inspection areas: {n_probed})", "-" * 72]
    for name, area in areas.items():
        if name == "readiness_summary" or not isinstance(area, dict) or "status" not in area:
            continue
        lines.append(f"  [{area['status']:>7}] {name}")
        if area["status"] != STATUS_OK:
            lines.append(f"          {str(area.get('detail', {}))[:200]}")
    summ = areas.get("readiness_summary", {})
    lines.append("-" * 72)
    lines.append(f"Decision: {summ.get('decision')}   counts={summ.get('status_counts')}   "
                 f"critical blockers={summ.get('critical_blockers')}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))