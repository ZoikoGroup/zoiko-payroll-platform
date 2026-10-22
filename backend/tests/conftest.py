"""
tests/conftest.py
------------------
Test setup shared by every module under backend/tests/.

Two scopes of coverage live here:

1. Pure calculation-engine tests (engine/standard.py, engine/base.py,
   engine/resolver.py) exercise the engine directly with lightweight
   in-memory rate/slab objects — no database is touched. The engine is
   pure (input dataclass in, output dataclass out), so this gives full
   coverage of the per-country tax math and the safe formula evaluator
   without needing a test database. See test_engine_standard.py and
   test_engine_jurisdiction_upgrade.py.

2. DB-integration tests (canonical/org/fallback rate resolution, state-
   scoped lookups, payslip generation, historical reproducibility) use
   the `db` fixture below — an isolated SQLite in-memory database, fresh
   per test. SQLite (not the live Neon Postgres dev database) so tests
   never touch real org data and stay fast/hermetic; models.py's two
   partial-unique indexes on ContributionRate carry a matching
   `sqlite_where` alongside `postgresql_where` specifically so this test
   database enforces the same canonical/org uniqueness semantics as
   production Postgres, not a looser approximation of it. See
   test_engine_jurisdiction_db_integration.py.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Two-step verification is off by default (DEC-11). The suite keeps testing
# the enforced path, which is still supported via MFA_ENFORCEMENT=enforce;
# tests/privacy/test_mfa_sessions.py covers the default (off) path.
os.environ.setdefault("MFA_ENFORCEMENT", "enforce")

import pytest
from sqlalchemy import event as _sa_event
from sqlalchemy.engine import Engine as _Engine

import app.modules.payroll.engine.countries.shared as _rollout_shared

_LOCAL_DB_HOSTS = {None, "", "localhost", "127.0.0.1", "::1"}


@_sa_event.listens_for(_Engine, "do_connect")
def _refuse_non_local_databases(dialect, conn_rec, cargs, cparams):
    """Tests may only ever reach SQLite or a loopback Postgres (the
    disposable ZP_TEST_POSTGRES_URL container). A code path that falls back
    to the app's configured engine (backend/.env -> a shared remote
    database) fails here instead of reading or writing real data."""
    if dialect.name == "sqlite":
        return None
    host = cparams.get("host")
    if host not in _LOCAL_DB_HOSTS:
        raise RuntimeError(f"tests must not connect to a non-local database (host {host!r})")
    return None


@pytest.fixture(autouse=True)
def _reset_rollout_switches():
    """Snapshot every per-country rollout switch (the module-level
    `_..._ENABLED_COUNTRIES` sets in engine/countries/shared.py) before
    each test and restore its exact prior contents after, regardless of
    what the test itself does to it.

    These sets are deliberately mutable global state so a test can flip
    one on/off inline without touching a database - but many existing
    tests call `.add("CA")` (or similar) with no matching cleanup,
    historically relying on file ordering (a "dormant" test placed before
    the test that flips a switch on) to avoid cross-test pollution within
    one pytest session. That ordering trick stopped being enough the
    moment any of these switches got a real default of `{"CA"}` instead
    of `set()` (see CA gap-closure Phase 1, 2026-09-11, which flipped 9 of
    them on) - a test running anywhere else in the suite could otherwise
    observe whatever an earlier, unrelated test happened to leave behind.
    This fixture makes every test's switch state isolated regardless of
    order or another test's cleanup discipline, without changing any
    module's actual default.
    """
    switch_names = [
        name for name in dir(_rollout_shared)
        if name.endswith("_ENABLED_COUNTRIES") and isinstance(getattr(_rollout_shared, name), set)
    ]
    snapshot = {name: set(getattr(_rollout_shared, name)) for name in switch_names}
    yield
    for name, original in snapshot.items():
        current = getattr(_rollout_shared, name)
        current.clear()
        current.update(original)


@pytest.fixture(autouse=True, scope="session")
def _cheap_bcrypt_rounds():
    """Hash test passwords with bcrypt's minimum cost (4 rounds) instead of
    the production default (12). Every user a test creates, and every login
    it makes, otherwise spends ~0.25s per hash on purpose-built slowness that
    proves nothing a cheaper real bcrypt hash doesn't. Production hashing in
    app/core/security.py is untouched; verify() reads the cost from the hash
    itself, so these hashes still verify normally.

    Imported here, at first-test setup, not at module scope: importing
    app.core.security pulls in app.config, which must not load before
    test_assist.py sets its own PAYROLL_DATABASE_URL during collection (see
    the `db` fixture's docstring)."""
    from passlib.context import CryptContext

    from app.core import security

    original = security.pwd_context
    security.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=4)
    yield
    security.pwd_context = original


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "attendance_gate: run with the real payroll attendance gate (off by default in tests).",
    )


@pytest.fixture(autouse=True)
def _attendance_gate_off_by_default(request, monkeypatch):
    """The payroll attendance gate (service.enforce_attendance_readiness,
    2026-10-06) refuses any run whose employees lack attendance for every
    working day. Production keeps it on by default; but hundreds of engine
    tests (Germany/Singapore/HK/CA/...) create runs purely to exercise
    calculations and never record attendance, so it is neutralised here
    unless a test opts in with @pytest.mark.attendance_gate
    (tests/test_attendance_gate.py). Patching the module attribute covers
    every caller: service.py resolves the name from its module globals at
    call time, and router.py calls it as service.enforce_attendance_readiness."""
    if request.node.get_closest_marker("attendance_gate"):
        yield
        return
    from app.modules.payroll import service as payroll_service

    monkeypatch.setattr(payroll_service, "enforce_attendance_readiness", lambda *args, **kwargs: None)
    yield


@pytest.fixture(autouse=True)
def _isolated_redis_cache():
    """Start and end every test with no memoized Redis client and a closed
    circuit breaker.

    get_redis_client() memoizes its client in a module global, and a
    connection failure opens a 30s breaker. Neither is undone by
    monkeypatch: a test that sets REDIS_URL and reaches the cache (e.g. an
    eager Celery task resolving tax config) would otherwise leave a real
    client to a dead host, and an open breaker, for every test after it.
    """
    from app.core import cache as cache_module

    cache_module.reset_redis_client()
    yield
    cache_module.reset_redis_client()


@pytest.fixture(autouse=True)
def _no_real_smtp(monkeypatch):
    """Guarantee no test ever opens a real SMTP connection.

    backend/.env carries live SMTP credentials (the company's real
    mailbox on its hosted SMTP server) and the app reads them eagerly via
    app.config at first import. Several auth flows (reset link, invite,
    and now the notification sends) fire through email_service at normal
    call sites; without this neutralizer a single unpatched test would
    attempt — and routinely succeed at — delivering mail through the real
    outbound server. Everyone's tests: forbid it, globally.

    The mechanism: `_get_smtp_settings()` is the one chokepoint every
    email_service send path resolves its SMTP endpoint through, and a
    falsy `host` makes send_approval_email log "Mock sending email ..." and
    return True without opening a socket. Patching it (not `settings`) keeps
    `settings.SMTP_HOST` untouched, so tests that assert on the loaded
    configuration still see the real env value. Tests that want to prove
    delivery mechanics monkeypatch the service/auth-level `_send_*_email`
    wrappers or `smtplib` directly on top of this."""

    def _fake_get_smtp_settings(db=None) -> dict:
        return {
            "host": "",
            "port": 0,
            "username": "",
            "password": "",
            "from_email": "test@example.com",
            "use_tls": False,
        }

    from app.services import email_service

    monkeypatch.setattr(email_service, "_get_smtp_settings", _fake_get_smtp_settings)


# ── F-10: a test run must never attempt real delivery ──────────────────────
REAL_DELIVERY_ATTEMPTS: list = []


class RealDeliveryAttempted(AssertionError):
    pass


class _SmtpTripwire:
    """Stands in for smtplib.SMTP / SMTP_SSL for the whole run. Any test that
    reaches a real SMTP constructor without faking it fails here, and the
    attempt is recorded so the session fails too (pytest_sessionfinish)."""

    def __init__(self, host="", port=0, *args, **kwargs):
        REAL_DELIVERY_ATTEMPTS.append(f"smtp {host}:{port}")
        raise RealDeliveryAttempted(f"test attempted real SMTP delivery to {host}:{port} (F-10)")


@pytest.fixture(autouse=True)
def _smtp_tripwire(monkeypatch):
    import smtplib

    monkeypatch.setattr(smtplib, "SMTP", _SmtpTripwire)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _SmtpTripwire)


@pytest.fixture()
def fake_smtp_transport(monkeypatch):
    """Explicit opt-in for tests that replace smtplib with a fake to prove
    delivery mechanics: lets the F-10 outbound guard pass the configured
    (fake) endpoint through. The tripwire above still fails any test that
    opts in but forgets to fake smtplib."""
    from app.core import outbound

    monkeypatch.setattr(outbound, "real_delivery_allowed", lambda channel: True)


def pytest_sessionfinish(session, exitstatus):
    if REAL_DELIVERY_ATTEMPTS:
        session.exitstatus = 1
        print(f"\nF-10: {len(REAL_DELIVERY_ATTEMPTS)} real outbound delivery attempt(s) in this test run: "
              f"{REAL_DELIVERY_ATTEMPTS[:5]}")


@pytest.fixture()
def db():
    """A fresh, isolated SQLite in-memory database for one test.

    StaticPool + a single shared connection is required for SQLite
    in-memory databases: without it, each new Session would get its own
    connection to its own throwaway in-memory database, unable to see
    tables/rows created via another connection.

    `app.database`/the model modules are imported HERE, inside the
    fixture, rather than at module (collection) scope — conftest.py loads
    before any test file's own module-level code runs, so an eager
    top-level `import app.database` here would construct the app's real
    global engine (bound to whatever PAYROLL_DATABASE_URL happens to
    resolve to at that moment — the live Neon Postgres URL from .env)
    before test_assist.py gets a chance to set PAYROLL_DATABASE_URL to its
    own throwaway SQLite file ahead of its own `from app.database import
    engine` — Python caches the module on first import, so that later
    import would silently receive the same already-Postgres-bound engine
    instead of a fresh one. Importing lazily, only once a test actually
    requests this fixture (during the run phase, after every file's own
    module-level setup has already executed during collection), avoids
    that race entirely. (This fixture builds its own separate SQLite
    engine regardless, so it doesn't touch the global engine either way —
    the ordering only matters for not disturbing other test files.)"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.database import Base
    # Import every module that defines a table participating in payroll's
    # FK graph (organizations.id, users.id) so Base.metadata has them all
    # before create_all — payroll models alone would leave those FKs dangling.
    import app.modules.organizations.models  # noqa: F401
    import app.modules.auth.models  # noqa: F401
    import app.modules.payroll.models  # noqa: F401
    import app.modules.billing.models  # noqa: F401
    import app.modules.communications.models  # noqa: F401
    import app.modules.support_access.models  # noqa: F401
    import app.modules.security.models  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def organization(db):
    """A minimal real Organization row — payroll rows FK to it."""
    from app.modules.organizations.models import Organization
    org = Organization(organization_name="Test Org", organization_code="TESTORG")
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


@pytest.fixture()
def published_professional_plan(db):
    """A PUBLISHED PROFESSIONAL plan version, so register_trial can attach a
    TRIALING BillingSubscription to it. Mirrors scripts/seed_professional_plan.py
    using the same service-layer functions."""
    from app.core.security import hash_password
    from app.modules.auth.models import User, UserRole
    from app.modules.billing import plan_catalog

    actor = User(
        email="super-admin@example.com",
        hashed_password=hash_password("a-strong-password-1"),
        role=UserRole.SUPER_ADMIN,
        first_name="Super",
        last_name="Admin",
        phone="",
        is_active=True,
        is_verified=True,
    )
    db.add(actor)
    db.flush()

    plan = plan_catalog.create_plan(db, "PROFESSIONAL", "Professional", actor_user_id=actor.id)
    version = plan_catalog.create_plan_version(
        db,
        plan_id=plan.id,
        feature_set={"features": ["payroll_runs", "multi_entity"]},
        scale_limits={"max_entities": 1},
        actor_user_id=actor.id,
    )
    plan_catalog.add_entitlement_flag(
        db, plan_version_id=version.id, feature_key="max_entities", limit_value=1, actor_user_id=actor.id
    )
    plan_catalog.approve_plan_version(db, version.id, actor_user_id=actor.id)
    plan_catalog.publish_plan_version(db, version.id, published_by_user_id=actor.id)
    db.refresh(version)
    return version


@pytest.fixture()
def raw_log_messages():
    """For the few tests that verify email routing by reading log lines:
    lift the ZP-PRIV D03 redaction filter (which masks addresses once
    app.main has been imported) for this test only. Redaction itself is
    covered by tests/privacy/test_redaction_federation_governance.py."""
    import logging

    # By class NAME, not isinstance: a test module that re-imports app modules
    # (e.g. clears sys.modules) leaves filters of an older RedactingLogFilter
    # class on pytest's session-wide handlers (live-logging / log-file), which
    # sit before caplog's handler and would still mask the record in place.
    removed = []
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access", "celery", "celery.task"):
        for handler in logging.getLogger(name).handlers:
            for f in list(handler.filters):
                if type(f).__name__ == "RedactingLogFilter":
                    handler.removeFilter(f)
                    removed.append((handler, f))
    yield
    for handler, f in removed:
        handler.addFilter(f)
