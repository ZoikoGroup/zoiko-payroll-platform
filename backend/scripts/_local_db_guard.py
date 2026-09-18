"""
scripts/_local_db_guard.py
--------------------------
Phase 8BY — a single, shared "is this actually a local/isolated database?"
guard for every Germany statutory WRITE script in this directory.

WHY THIS EXISTS

`seed_germany_source_evidence.py`, `seed_germany_2026_registries.py` and
`publish_seeded_germany_registries.py` all begin with

    initialize_database()
    db = SessionLocal()

which binds to whatever `PAYROLL_DATABASE_URL` resolves to at that
moment. In this repository that is, by default, the shared remote
PostgreSQL instance configured in `backend/.env`. Nothing in those
scripts previously checked the target. `publish_seeded_germany_registries.py`
in particular walks every DRAFT statutory row through
DRAFT -> VERIFIED -> APPROVED -> PUBLISHED, and a PUBLISHED row is exactly
what `resolve_germany_*` binds production payroll calculations to — so an
accidental run against the shared database would silently promote seed
data into live statutory configuration, under fabricated maker/checker
ids (the scripts use literals such as 901/902 that correspond to no real
approver).

Their docstrings said "run against an isolated database only". A docstring
is not a control. This module turns that instruction into an enforced
precondition.

WHAT COUNTS AS LOCAL

- Any SQLite URL (file or in-memory) — always allowed; it cannot be shared
  infrastructure.
- A PostgreSQL/other server URL ONLY when its host is a loopback address
  (localhost / 127.0.0.1 / ::1) or empty (a UNIX socket).
- Everything else is refused.

DELIBERATE ESCAPE HATCH

A human operator who genuinely intends to run one of these against a
non-local database (a staging restore, say) must set

    ZOIKO_ALLOW_NONLOCAL_DB_WRITES=I_UNDERSTAND

That is intentionally verbose, undocumented in any runbook, and logged
loudly — it exists so this guard can never become the reason a legitimate
operator is blocked, while still making an accidental run impossible.
The guard NEVER auto-detects "probably fine"; absent that exact value it
refuses and exits non-zero.

This module performs no I/O of its own and opens no connection — it only
inspects the configured URL string, so importing it is always safe.
"""

from __future__ import annotations

import os
import sys
from urllib.parse import urlparse

_OVERRIDE_ENV = "ZOIKO_ALLOW_NONLOCAL_DB_WRITES"
_OVERRIDE_VALUE = "I_UNDERSTAND"

_LOOPBACK_HOSTS = {"", "localhost", "127.0.0.1", "::1", "[::1]"}


def _configured_database_url() -> str:
    """The URL these scripts will actually bind to, resolved the same way
    `app.database` resolves it: the environment first, then the app's own
    settings object. Imported lazily so this module stays import-safe even
    when the app package cannot be configured."""
    for env_name in ("PAYROLL_DATABASE_URL", "DATABASE_URL"):
        value = (os.environ.get(env_name) or "").strip()
        if value:
            return value
    try:
        from app.config import settings  # type: ignore[import]

        return (getattr(settings, "PAYROLL_DATABASE_URL", "") or "").strip()
    except Exception:
        return ""


def _redact(url: str) -> str:
    """Never print credentials, even in a refusal message."""
    try:
        parsed = urlparse(url)
    except Exception:
        return "<unparseable database url>"
    if parsed.password:
        netloc = parsed.netloc.replace(f":{parsed.password}", ":***")
        return parsed._replace(netloc=netloc).geturl()
    return url


def describe_target() -> str:
    return _redact(_configured_database_url())


def is_local_database(url: str | None = None) -> bool:
    """True only when the configured target is demonstrably local/isolated.
    Fails CLOSED: an empty or unparseable URL is not treated as local."""
    target = (url if url is not None else _configured_database_url()).strip()
    if not target:
        return False
    try:
        parsed = urlparse(target)
    except Exception:
        return False
    scheme = (parsed.scheme or "").lower()
    if scheme.startswith("sqlite"):
        return True
    host = (parsed.hostname or "").strip().lower()
    return host in _LOOPBACK_HOSTS


def assert_local_database(script_name: str) -> None:
    """Refuse to continue unless the configured database is local/isolated.

    Call this as the FIRST statement of a write script's `main()` — before
    `initialize_database()`, which would otherwise already have created an
    engine (and, on an empty database, run `create_all`) against the remote
    target."""
    target = _configured_database_url()
    if is_local_database(target):
        return

    override = (os.environ.get(_OVERRIDE_ENV) or "").strip()
    if override == _OVERRIDE_VALUE:
        print(
            f"[{script_name}] WARNING: {_OVERRIDE_ENV}={_OVERRIDE_VALUE} is set - proceeding "
            f"against a NON-LOCAL database: {_redact(target)}",
            file=sys.stderr,
        )
        return

    print(
        f"\n[{script_name}] REFUSING TO RUN - the configured database does not look local.\n"
        f"  Target: {_redact(target) or '<not configured>'}\n\n"
        "  This script performs statutory WRITES (and, for the publish script, promotes rows to\n"
        "  PUBLISHED, which production payroll calculations bind to). It may only be run against an\n"
        "  isolated SQLite database or a loopback PostgreSQL instance.\n\n"
        "  To target a local database, set PAYROLL_DATABASE_URL, e.g.:\n"
        "    PAYROLL_DATABASE_URL=sqlite:///./germany_local.sqlite3\n\n"
        f"  If you genuinely intend to write to this non-local database, set {_OVERRIDE_ENV}={_OVERRIDE_VALUE}.\n",
        file=sys.stderr,
    )
    raise SystemExit(2)
