"""
tests/privacy/test_route_registry.py
------------------------------------
ZP-PRIV A03: the route policy registry is complete, in sync with a fresh
generation, and every Super Admin worker route is de-privileged.

Static (no request) checks, re-derived from the code so drift fails CI.

NOTE: app.main is imported lazily inside the tests, never at module scope.
Collection order puts tests/privacy/ before tests/test_assist.py, and
test_assist.py binds the app's global DB engine to its own SQLite file at
module scope; importing app.main here first would bind it to the real URL.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
REGISTRY_PATH = BACKEND / "app" / "core" / "authz" / "route_registry.json"
CSV_PATH = BACKEND.parent / "docs" / "privacy" / "route_policy_inventory.csv"

# The only routes reachable without a token (ZP-PRIV A01). Anything else with
# no auth dependency is a leak and fails here.
KNOWN_PUBLIC = {
    ("GET", "/"),
    ("GET", "/health"),
    ("GET", "/health/celery"),
    ("GET", "/api/health/celery"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/register"),
    ("POST", "/api/auth/register-trial"),
    ("POST", "/api/auth/refresh"),
    ("GET", "/api/auth/accept-invite"),
    ("POST", "/api/auth/forgot-password"),
    ("GET", "/api/auth/reset-password"),
    ("POST", "/api/auth/reset-password"),
    ("GET", "/api/jurisdictions/tax-schemas"),
    ("GET", "/api/payroll/public/employee-forms/{token}"),
    ("POST", "/api/payroll/public/employee-forms/{token}/submit"),
    ("POST", "/api/assist/public/sessions"),
    ("GET", "/api/assist/public/sessions/{session_id}/messages"),
    ("POST", "/api/assist/public/sessions/{session_id}/messages"),
    ("GET", "/api/billing/plans"),
    ("POST", "/api/billing/webhooks/stripe"),
    # Second sign-in step: reachable only with the single-use, 5-minute
    # mfa_token that /auth/login returns instead of a session (ZP-PRIV B08).
    ("POST", "/api/auth/mfa/challenge"),
    ("POST", "/api/auth/mfa/enroll/begin"),
    ("POST", "/api/auth/mfa/enroll/confirm"),
    # Zoiko One federation (D05): reachable only with an IdP-signed token.
    ("POST", "/api/auth/federation/exchange"),
}


def _import_app():
    from app.main import app
    return app


def _app_route_methods():
    from fastapi.routing import APIRoute

    for route in _import_app().routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods:
            m = method.upper()
            if m in ("HEAD", "OPTIONS"):
                continue
            yield m, route.path_format, route


def _registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_registry_file_exists():
    assert REGISTRY_PATH.exists(), "route_registry.json missing - run python -m app.core.authz.generate"


def test_every_route_is_registered():
    entries = {(e["method"], e["path"]) for e in _registry()["entries"]}
    missing = [(m, p) for m, p, _ in _app_route_methods() if (m, p) not in entries]
    assert not missing, f"unregistered routes (fail closed at runtime): {missing}"


def test_no_extra_registry_entries():
    live = {(m, p) for m, p, _ in _app_route_methods()}
    registered = {(e["method"], e["path"]) for e in _registry()["entries"]}
    assert not (registered - live), f"registry entries with no live route: {registered - live}"


def test_registry_matches_fresh_generation():
    from app.core.authz.generate import build_entries
    from app.database import Base

    fresh = build_entries(_import_app(), Base)
    assert fresh == _registry()["entries"], (
        "route_registry.json is stale - run python -m app.core.authz.generate")


def test_csv_in_sync_with_registry():
    assert CSV_PATH.exists(), "route_policy_inventory.csv missing - run the generator"
    with open(CSV_PATH, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    entries = _registry()["entries"]
    assert len(rows) == len(entries)
    for row, entry in zip(rows, entries):
        assert row["method"] == entry["method"]
        assert row["path"] == entry["path"]
        assert row["data_class"] == entry["data_class"]
        assert row["action"] == entry["action"]
        assert row["principals"] == "|".join(entry["principals"])
        assert row["retired_reason"] == (entry["retired_reason"] or "")
        assert row["overridden"] == ("yes" if entry["overridden"] else "no")


def test_public_routes_are_exactly_known():
    from app.core.authz.generate import route_auth_deps

    public = set()
    for m, p, route in _app_route_methods():
        if not route_auth_deps(route):
            public.add((m, p))
    assert public == KNOWN_PUBLIC, (
        "public route set changed:\n"
        f"  unexpected: {sorted(public - KNOWN_PUBLIC)}\n"
        f"  missing:    {sorted(KNOWN_PUBLIC - public)}")


def test_no_worker_route_allows_super_admin():
    from app.core.authz import policy as P

    bad = [(e["method"], e["path"]) for e in _registry()["entries"]
           if e["data_class"] == P.DC_WORKER and "super_admin" in e["principals"]]
    assert not bad, f"worker routes reachable by super_admin: {bad}"


def test_no_worker_route_allows_any_platform_role():
    from app.core.authz import policy as P

    platform = {"super_admin", "platform_security", "support_operator"}
    bad = [(e["method"], e["path"]) for e in _registry()["entries"]
           if e["data_class"] == P.DC_WORKER and platform & set(e["principals"])]
    assert not bad, f"worker routes reachable by a platform role: {bad}"


def test_worker_data_class_follows_scan_unless_overridden():
    from app.core.authz import policy as P

    for e in _registry()["entries"]:
        if e["scan_worker_tables"] and e["data_class"] != P.DC_WORKER:
            assert e["overridden"] and e["note"], (
                f"{e['method']} {e['path']} scan reaches worker tables but is "
                f"{e['data_class']} without a reviewed override+rationale")


def test_every_live_route_is_usable_by_a_listed_principal():
    """No route may be accidental deny-all: at least one listed principal must
    pass the role matrix for the route's data class and action."""
    from app.core.authz import policy as P

    problems = []
    for e in _registry()["entries"]:
        if e["retired_reason"] or e["data_class"] in (P.DC_PUBLIC, P.DC_UNREGISTERED):
            continue
        ok = any(
            e["action"] in P.MATRIX.get(role, {}).get(e["data_class"], frozenset())
            for role in e["principals"])
        if not ok:
            problems.append((e["method"], e["path"], e["data_class"], e["action"],
                             e["principals"]))
    assert not problems, (
        "routes no listed principal can use (likely a data_class/action bug): "
        f"{problems}")


def test_retired_routes_have_a_reason():
    for e in _registry()["entries"]:
        if e["retired_reason"]:
            assert e["principals"] == [], "retired routes must list no principals"
            assert e["note"], "retired routes need a rationale"


def test_every_override_has_a_note_and_a_live_route():
    from app.core.authz.route_overrides import OVERRIDES

    live = {(m, p) for m, p, _ in _app_route_methods()}
    for (method, path), override in OVERRIDES.items():
        assert override.note, f"override {method} {path} needs a rationale note"
        assert (method, path) in live, f"override {method} {path} has no live route"


@pytest.mark.parametrize("method,path", sorted(KNOWN_PUBLIC))
def test_public_routes_have_no_registry_principals(method, path):
    from app.core.authz import policy as P

    entry = next(e for e in _registry()["entries"]
                 if e["method"] == method and e["path"] == path)
    assert entry["data_class"] == P.DC_PUBLIC
    assert entry["principals"] == []
