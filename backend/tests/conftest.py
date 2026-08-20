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

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


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
