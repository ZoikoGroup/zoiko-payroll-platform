"""
core/authz/generate.py
----------------------
Regenerate the route policy registry and its review inventory from the app
itself (ZP-PRIV A03):

    cd backend && python -m app.core.authz.generate

Writes:
  * app/core/authz/route_registry.json  - one entry per (METHOD, path)
  * docs/privacy/route_policy_inventory.csv - the same data for review

Data class comes from callgraph.py (which tables a handler can reach) plus
path heuristics; principals come from the route's own auth gate. Everything
disagreeing with a deliberate decision lives in route_overrides.py. The
registry CI test re-runs this and diffs against the committed files.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import FrozenSet, List, Optional, Set

from app.core.authz import policy as P
from app.core.authz.principal import ALL_ROLES
from app.core.authz.route_overrides import OVERRIDES, Override

BACKEND = Path(__file__).resolve().parents[3]
REGISTRY = Path(__file__).resolve().parent / "route_registry.json"
CSV_PATH = BACKEND.parent / "docs" / "privacy" / "route_policy_inventory.csv"

AUTH_DEPS = {
    "get_current_user", "get_current_super_admin", "get_current_org_admin",
    "get_current_payroll_operator", "get_organization_id",
    "get_current_org_scoped_principal", "get_current_support_requester",
    "get_current_platform_security", "get_current_security_reader", "get_current_machine_or_user",
}

_EXPORT_SEGS = {"export", "download", "csv", "pdf", "xlsx", "zip"}
_APPROVE_SEGS = {"approve", "finalize", "file", "submit", "commit", "lock",
                 "release", "issue", "accept", "pay"}
_AGGREGATE_HINTS = ("/finance", "/dashboard", "/reports", "/aggregate", "/stats",
                    "/charts", "/monitoring", "/statutory-summary", "/impact-preview",
                    "/bwm", "/command-center")
_SECURITY_HINTS = ("/security", "/audit", "/mfa", "/api-keys", "/api_keys",
                   "/sessions/revoke", "/alert-rules", "/alert-events", "/privileged-inventory",
                   "/machine-clients", "/privacy-assurance")

_PARAM = re.compile(r"\{(\w+)\}")


def _params(path: str) -> List[str]:
    return _PARAM.findall(path)


def _static_segments(path: str) -> List[str]:
    return [s for s in path.split("/") if s and not s.startswith("{")]


def route_auth_deps(route) -> Set[str]:
    """Names of every auth dependency in this route's dependency tree.

    The PDP dependency that install_route_policies injects is skipped, so the
    classification sees the route's own gates only."""
    found: Set[str] = set()

    def walk(dependant) -> None:
        for sub in dependant.dependencies:
            name = getattr(sub.call, "__name__", "")
            if name in ("route_policy", "explicit_policy"):
                continue  # injected by the PDP, not part of the route's gates
            if name in AUTH_DEPS:
                found.add(name)
            walk(sub)

    walk(route.dependant)
    return found


def _is_file_segment(seg: str) -> bool:
    """A GET of a generated document: /download, /bank-transfer-file,
    /xml, /p60.pdf ... (a file leaves the system: export, not read)."""
    return (seg in _EXPORT_SEGS or seg.endswith("-file") or seg.endswith("-export")
            or seg.endswith("-download") or seg.endswith("-xml")
            or seg in ("xml", "file", "files-zip", "certificate")
            or seg.endswith((".pdf", ".csv", ".xml", ".zip", ".xlsx")))


def derive_action(method: str, path: str) -> str:
    segs = [s.lower() for s in _static_segments(path)]
    if method == "GET":
        return P.ACT_EXPORT if any(_is_file_segment(s) for s in segs) else P.ACT_READ
    if method == "POST":
        if any(s in _EXPORT_SEGS for s in segs):
            return P.ACT_EXPORT
        return P.ACT_APPROVE if segs and segs[-1] in _APPROVE_SEGS else P.ACT_CREATE
    if method in ("PUT", "PATCH"):
        return P.ACT_UPDATE
    if method == "DELETE":
        return P.ACT_DELETE
    return P.ACT_READ


def derive_data_class(method: str, path: str, worker_hit: bool,
                      deps: Set[str]) -> str:
    if not deps:
        return P.DC_PUBLIC
    if worker_hit:
        return P.DC_WORKER
    p = path.lower()
    # Hard delete of a whole organization: destroys, discloses nothing.
    if method == "DELETE" and re.fullmatch(r"/api/(super-admin/)?organizations/\{[^}]+\}", path):
        return P.DC_TENANT_LIFECYCLE
    if "/assisted-access" in p or "/support-access" in p:
        return P.DC_SUPPORT
    # Security/audit surfaces are the platform plane only; a tenant assist
    # audit route is tenant data, not platform security.
    if path.startswith("/api/super-admin") and any(k in p for k in _SECURITY_HINTS):
        return P.DC_SECURITY
    # "aggregate" is a platform-plane notion (k-suppressed cross-tenant
    # totals). A tenant's own dashboards and reports are tenant data.
    if path.startswith("/api/super-admin") and any(k in p for k in _AGGREGATE_HINTS):
        return P.DC_AGGREGATE
    # A file a tenant downloads may carry worker data: classify as worker.
    if path.startswith("/api/payroll") and derive_action(method, path) == P.ACT_EXPORT:
        return P.DC_WORKER
    # No role gate and no org gate: a self-service route for any login.
    if deps <= {"get_current_user"}:
        return P.DC_SELF
    # A Super Admin-gated route outside the special classes above is a
    # platform-plane operation (organization management, assist admin, ...).
    if "get_current_super_admin" in deps:
        return P.DC_PLATFORM
    if path.startswith("/api/super-admin"):
        return P.DC_PLATFORM
    return P.DC_TENANT_CONFIG


def derive_principals(deps: Set[str], action: str, data_class: str,
                      path: str) -> FrozenSet[str]:
    if data_class == P.DC_PUBLIC:
        return frozenset()
    if "get_current_platform_security" in deps:
        return frozenset({"platform_security"})
    if "get_current_security_reader" in deps:
        return frozenset({"super_admin", "platform_security"})
    if "get_current_support_requester" in deps:
        return frozenset({"super_admin", "support_operator", "platform_security"})
    if "get_current_super_admin" in deps:
        return frozenset({"super_admin"})
    if "get_current_org_admin" in deps:
        ps = {"org_admin"}
    elif "get_current_payroll_operator" in deps:
        ps = {"org_admin", "payroll_admin"}
    elif "get_organization_id" in deps:
        ps = {"org_admin", "payroll_admin"}
        if action == P.ACT_READ:
            ps.add("support_temp")
    else:
        # get_current_user only -> any authenticated (self) unless the data
        # class says otherwise; the matrix still bounds the action.
        return frozenset(ALL_ROLES)
    if data_class == P.DC_WORKER and action == P.ACT_READ and "employee_id" in _params(path):
        ps.add("employee")
    return frozenset(ps)


def derive_scope_level(data_class: str) -> str:
    if data_class == P.DC_PUBLIC:
        return "public"
    if data_class == P.DC_SELF:
        return "self"
    if data_class in (P.DC_WORKER, P.DC_TENANT_CONFIG, P.DC_SUPPORT):
        return "tenant"
    return "platform"


def derive_resource(path: str) -> str:
    segs = _static_segments(path.lower())
    return segs[-1] if segs else "root"


def build_entries(app, base) -> List[dict]:
    from app.core.authz.callgraph import scan_routes
    from fastapi.routing import APIRoute

    scan = scan_routes(app.routes, base)
    entries: List[dict] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        deps = route_auth_deps(route)
        for method in route.methods:
            m = method.upper()
            if m in ("HEAD", "OPTIONS"):
                continue
            worker_tables = sorted(scan.get((m, route.path_format), set()))
            data_class = derive_data_class(m, route.path_format, bool(worker_tables), deps)
            action = derive_action(m, route.path_format)
            principals = derive_principals(deps, action, data_class, route.path_format)
            note: Optional[str] = None
            retired: Optional[str] = None

            override: Optional[Override] = OVERRIDES.get((m, route.path_format))
            if override is not None:
                if override.data_class:
                    data_class = override.data_class
                if override.action:
                    action = override.action
                if override.principals is not None:
                    principals = frozenset(override.principals)
                retired = override.retired_reason
                note = override.note or None

            entries.append({
                "method": m,
                "path": route.path_format,
                "data_class": data_class,
                "action": action,
                "resource": derive_resource(route.path_format),
                "principals": sorted(principals),
                "scope_level": derive_scope_level(data_class),
                "field_classes": [],
                "retired_reason": retired,
                "note": note,
                "scan_worker_tables": worker_tables,
                "overridden": override is not None,
            })
    entries.sort(key=lambda e: (e["path"], e["method"]))
    return entries


def write_registry(entries: List[dict]) -> None:
    REGISTRY.write_text(json.dumps(
        {"version": 1, "generated_by": "app.core.authz.generate", "entries": entries},
        indent=1, sort_keys=False), encoding="utf-8")


def write_csv(entries: List[dict]) -> None:
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["method", "path", "data_class", "action", "resource",
                         "principals", "scope_level", "field_classes",
                         "retired_reason", "scan_worker_tables", "overridden", "note"])
        for e in entries:
            writer.writerow([
                e["method"], e["path"], e["data_class"], e["action"], e["resource"],
                "|".join(e["principals"]), e["scope_level"], "|".join(e["field_classes"]),
                e["retired_reason"] or "", "|".join(e["scan_worker_tables"]),
                "yes" if e["overridden"] else "no", e["note"] or "",
            ])


def main() -> None:
    from app.database import Base
    from app.main import app

    entries = build_entries(app, Base)
    write_registry(entries)
    write_csv(entries)
    classes = {}
    for e in entries:
        classes[e["data_class"]] = classes.get(e["data_class"], 0) + 1
    print(f"route_registry.json: {len(entries)} entries")
    print("by data_class:", dict(sorted(classes.items())))


if __name__ == "__main__":
    main()
