"""
core/authz/callgraph.py
-----------------------
Static data-class derivation for the route policy registry (ZP-PRIV A03/A04).

Two questions, answered from the code itself rather than a hand-kept list:

1. Which tables hold worker-level (identifiable employee) data?
   Derived from ``Base.metadata``: ``payroll_employees`` itself, plus every
   table with a foreign key to it or to ``payslip_items``, or with an
   ``employee_id`` / ``payroll_employee_id`` / ``payslip_item_id`` column.

2. Which route handlers can reach one of those tables?
   An over-approximating call graph built with ``ast`` over every module in
   ``app/``: a call is resolved by its simple name to every function of that
   name defined in the package, transitively, to ``MAX_DEPTH``. Over-
   approximation is deliberate — a false "worker" classification is fixed
   with a reviewed override (route_overrides.py); a false "not worker" would
   be a silent privacy leak.

This module is used by the registry generator and its CI test, never on the
request path.
"""

from __future__ import annotations

import ast
from collections import defaultdict, deque
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

APP_ROOT = Path(__file__).resolve().parents[2]  # .../backend/app

WORKER_ROOT_TABLES = ("payroll_employees", "payslip_items")
WORKER_COLUMN_NAMES = ("employee_id", "payroll_employee_id", "payslip_item_id")
MAX_DEPTH = 8

# Simple names too generic to resolve meaningfully (builtins / ORM / dict
# methods that also happen to be defined somewhere in the package). Following
# them would connect every handler to every model.
_UNRESOLVED_CALLS = frozenset({
    "get", "first", "all", "one", "filter", "filter_by", "query", "add", "commit",
    "flush", "refresh", "rollback", "delete", "update", "append", "extend", "items",
    "keys", "values", "join", "split", "strip", "lower", "upper", "format", "replace",
    "isoformat", "dict", "list", "set", "tuple", "str", "int", "float", "bool", "len",
    "sum", "min", "max", "sorted", "round", "abs", "any", "all", "isinstance",
    "getattr", "setattr", "hasattr", "print", "range", "enumerate", "zip", "map",
    "model_dump", "model_validate", "dumps", "loads", "now", "utcnow", "today",
    "info", "warning", "error", "exception", "debug", "close", "execute", "scalar",
    "scalars", "count", "order_by", "limit", "offset", "group_by", "label", "in_",
    "pop", "setdefault", "copy", "startswith", "endswith", "encode", "decode",
    "validate", "run", "build", "create", "save", "load", "send", "main",
})


def worker_tables(metadata) -> Set[str]:
    """Worker-level table names derived from the SQLAlchemy metadata."""
    out: Set[str] = set()
    for name, table in metadata.tables.items():
        if name in WORKER_ROOT_TABLES:
            out.add(name)
            continue
        for col in table.columns:
            if col.name in WORKER_COLUMN_NAMES:
                out.add(name)
                break
            if any(fk.column.table.name in WORKER_ROOT_TABLES for fk in col.foreign_keys):
                out.add(name)
                break
    return out


def worker_model_names(base) -> Dict[str, str]:
    """Mapped class name -> table name, for every worker-level table."""
    tables = worker_tables(base.metadata)
    out: Dict[str, str] = {}
    for mapper in base.registry.mappers:
        table = getattr(mapper.class_, "__tablename__", None)
        if table in tables:
            out[mapper.class_.__name__] = table
    return out


class _FnInfo:
    __slots__ = ("module", "qualname", "calls", "bare_calls", "attr_calls", "recv_calls", "names", "strings")

    def __init__(self, module: str, qualname: str):
        self.module = module
        self.qualname = qualname
        self.calls: Set[str] = set()
        self.bare_calls: Set[str] = set()   # foo(...)  - Python's normal name lookup
        self.attr_calls: Set[str] = set()   # x.foo(...) - any module's foo
        self.recv_calls: Set[Tuple[str, str]] = set()  # (x, foo) when x is a plain name
        self.names: Set[str] = set()
        self.strings: Set[str] = set()


def _module_name(path: Path) -> str:
    rel = path.relative_to(APP_ROOT.parent).with_suffix("")
    return ".".join(rel.parts)


def _collect(fn_node, info: _FnInfo) -> None:
    for node in ast.walk(fn_node):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                info.calls.add(f.id)
                info.bare_calls.add(f.id)
            elif isinstance(f, ast.Attribute):
                info.calls.add(f.attr)
                if isinstance(f.value, ast.Name):
                    info.recv_calls.add((f.value.id, f.attr))
                else:
                    info.attr_calls.add(f.attr)
        elif isinstance(node, ast.Name):
            info.names.add(node.id)
        elif isinstance(node, ast.Attribute):
            info.names.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) < 80:
            info.strings.add(node.value)


def _module_aliases(tree, module: str) -> Dict[str, str]:
    """name -> dotted module path for every `import a.b as x` /
    `from a import b [as x]` in the file (including imports inside functions,
    which this codebase uses for lazy loading). Non-module imports are kept
    too; resolution only trusts an alias that names a module in the index."""
    out: Dict[str, str] = {}
    package = module.rsplit(".", 1)[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")
                base = ".".join(parts[: len(parts) - node.level + 1] + ([base] if base else []))
            for a in node.names:
                out[a.asname or a.name] = f"{base}.{a.name}" if base else a.name
    return out


_ALIASES: Dict[str, Dict[str, str]] = {}


@lru_cache(maxsize=1)
def _index() -> Tuple[Dict[str, List[_FnInfo]], Dict[Tuple[str, str], _FnInfo]]:
    by_name: Dict[str, List[_FnInfo]] = defaultdict(list)
    by_qual: Dict[Tuple[str, str], _FnInfo] = {}
    for path in sorted(APP_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        module = _module_name(path)
        _ALIASES[module] = _module_aliases(tree, module)

        def visit(body, prefix=""):
            for node in body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qual = f"{prefix}{node.name}"
                    info = _FnInfo(module, qual)
                    _collect(node, info)
                    by_name[node.name].append(info)
                    by_qual[(module, qual)] = info
                elif isinstance(node, ast.ClassDef):
                    # Class bodies (e.g. a model's column list) are not code
                    # paths; only their methods are.
                    visit(node.body, prefix=f"{prefix}{node.name}.")
        visit(tree.body)
    return by_name, by_qual


def _call_targets(info: _FnInfo, by_name, by_qual) -> List[_FnInfo]:
    """Functions a call may reach. Precise where Python's own lookup is
    unambiguous, otherwise every same-named function (conservative):

    * foo(...)    -> the caller module's own foo if it defines one;
    * mod.foo(...) where `mod` is an imported module -> that module's foo;
    * anything else (obj.foo(...), chained calls) -> every function named foo.
    """
    aliases = _ALIASES.get(info.module, {})
    known_modules = {m for m, _ in by_qual}
    out: List[_FnInfo] = []
    for call in info.bare_calls:
        if call in _UNRESOLVED_CALLS:
            continue
        targets = by_name.get(call, ())
        local = [t for t in targets if t.module == info.module]
        imported = aliases.get(call)
        if local:
            targets = local
        elif imported and "." in imported:
            mod, _, fn = imported.rpartition(".")
            if (mod, fn) in by_qual:
                targets = [by_qual[(mod, fn)]]
        out.extend(targets)
    for recv, call in info.recv_calls:
        if call in _UNRESOLVED_CALLS:
            continue
        mod = aliases.get(recv)
        if mod in known_modules and (mod, call) in by_qual:
            out.append(by_qual[(mod, call)])
        else:
            out.extend(by_name.get(call, ()))
    for call in info.attr_calls:
        if call not in _UNRESOLVED_CALLS:
            out.extend(by_name.get(call, ()))
    return out


def reachable_functions(module: str, qualname: str, max_depth: int = MAX_DEPTH) -> List[_FnInfo]:
    by_name, by_qual = _index()
    start = by_qual.get((module, qualname))
    if start is None:
        return []
    seen = {id(start)}
    out = [start]
    queue = deque([(start, 0)])
    while queue:
        info, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for target in _call_targets(info, by_name, by_qual):
                if id(target) in seen:
                    continue
                seen.add(id(target))
                out.append(target)
                queue.append((target, depth + 1))
    return out


def worker_tables_reached(module: str, qualname: str, worker_models: Dict[str, str]) -> Set[str]:
    """Worker-level table names a handler can reach (by model class name or
    by a raw table-name string, e.g. text() SQL)."""
    tables = set(worker_models.values())
    hit: Set[str] = set()
    for info in reachable_functions(module, qualname):
        for name in info.names & worker_models.keys():
            hit.add(worker_models[name])
        for s in info.strings:
            if s in tables:
                hit.add(s)
    return hit


def endpoint_location(endpoint) -> Optional[Tuple[str, str]]:
    module = getattr(endpoint, "__module__", None)
    qual = getattr(endpoint, "__qualname__", None)
    if not module or not qual or not module.startswith("app."):
        return None
    return module, qual


def scan_routes(routes: Iterable, base) -> Dict[Tuple[str, str], Set[str]]:
    """(METHOD, path) -> worker tables reached, for every APIRoute."""
    from fastapi.routing import APIRoute

    models = worker_model_names(base)
    out: Dict[Tuple[str, str], Set[str]] = {}
    for route in routes:
        if not isinstance(route, APIRoute):
            continue
        loc = endpoint_location(route.endpoint)
        hit = worker_tables_reached(*loc, models) if loc else set()
        for method in route.methods:
            out[(method, route.path)] = hit
    return out
