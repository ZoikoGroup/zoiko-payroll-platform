"""Mexico CFDI lifecycle migration b5e1c7d9a3f2 (mx_cfdi_lifecycle).

SQLite (always): guarded, idempotent upgrade / downgrade; existing rows and
every shared table untouched; the new columns are nullable.

PostgreSQL (MX_PG6_TEST_URL -> a THROWAWAY database on 127.0.0.1, else skipped):
  - lock MODES proven in flight: ACCESS EXCLUSIVE only on the two Mexican CFDI
    tables the migration alters (dormant and empty in production); the shared
    tables it references by FK (payroll_runs is not referenced; payslip_items,
    payroll_employees, organizations, users) get SHARE ROW EXCLUSIVE at most,
    and a third connection still reads payslip_items;
  - the hold time is MEASURED (first statement -> commit) and printed;
  - a writer holding payroll_mx_cfdi_documents makes the upgrade fail fast
    (~5 s) with nothing applied; a re-run completes;
  - the access-log table is append-only (trigger) and gets the ZP-PRIV worker
    row-level-security policy that d7f9b1c3e5a6's classify() derives;
  - the real CLI (env.py) and check_schema_drift pass."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import sqlalchemy as sa

REVISION, PARENT = "b5e1c7d9a3f2", "a8cde2482ef0"
BACKEND = Path(__file__).resolve().parents[1]
ACCESS = "payroll_mx_document_access_events"
DOCS = "payroll_mx_cfdi_documents"
RELEASES = "payroll_mx_cfdi_schema_releases"
DOC_NEW = {"event_key", "document_subtype", "employer_profile_id", "state_code", "snapshot_hash", "ruleset_version",
           "issuing_cert_token", "document_locale", "published_at", "delivery_status", "cancel_outcome"}


def _module():
    import importlib.util

    path = next((BACKEND / "alembic" / "versions").glob(f"{REVISION}_*.py"))
    spec = importlib.util.spec_from_file_location("mx_cfdi_lifecycle", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rls():
    import importlib.util

    path = BACKEND / "alembic" / "versions" / "d7f9b1c3e5a6_postgres_row_level_security.py"
    spec = importlib.util.spec_from_file_location("zp_rls_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(engine, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    if engine.dialect.name != "postgresql":
        with engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                getattr(_module(), fn)()
        return
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            with ctx.begin_transaction():
                getattr(_module(), fn)()


def _tables(engine):
    return set(sa.inspect(engine).get_table_names())


def _cols(engine, table):
    return {c["name"] for c in sa.inspect(engine).get_columns(table)}


def _shared_columns(engine):
    return {t: _cols(engine, t) for t in ("payslip_items", "payroll_runs", "payroll_employees", "organizations")}


def test_revision_links():
    mod = _module()
    assert (mod.revision, mod.down_revision) == (REVISION, PARENT)


@pytest.fixture()
def sqlite_engine(tmp_path):
    import app.modules.payroll.models  # noqa: F401
    from app.database import Base

    eng = sa.create_engine(f"sqlite:///{tmp_path / 'lc.db'}")
    Base.metadata.create_all(eng)
    _run(eng, "downgrade")
    return eng


def test_sqlite_upgrade_downgrade_idempotent(sqlite_engine):
    eng = sqlite_engine
    assert ACCESS not in _tables(eng) and not (DOC_NEW & _cols(eng, DOCS))
    shared = _shared_columns(eng)
    for _ in range(2):
        _run(eng, "upgrade")
    assert ACCESS in _tables(eng) and DOC_NEW <= _cols(eng, DOCS)
    assert {"effective_from", "effective_to"} <= _cols(eng, RELEASES)
    assert _shared_columns(eng) == shared
    for _ in range(2):
        _run(eng, "downgrade")
    assert ACCESS not in _tables(eng) and not (DOC_NEW & _cols(eng, DOCS))
    assert not ({"effective_from", "effective_to"} & _cols(eng, RELEASES)) and _shared_columns(eng) == shared


PG_URL = os.getenv("MX_PG6_TEST_URL")
pg = pytest.mark.skipif(not PG_URL, reason="MX_PG6_TEST_URL not set (throwaway PostgreSQL only)")


@pytest.fixture()
def pg_engine():
    import app.modules.payroll.models  # noqa: F401
    from app.database import Base

    assert "mx6run" in PG_URL and "127.0.0.1" in PG_URL, "refusing a non-throwaway PostgreSQL URL"
    eng = sa.create_engine(PG_URL)
    with eng.begin() as c:
        c.execute(sa.text("DROP SCHEMA public CASCADE"))
        c.execute(sa.text("CREATE SCHEMA public"))
    Base.metadata.create_all(eng)
    _run(eng, "downgrade")
    with eng.begin() as c:                                      # production state: d7f9b1c3e5a6 applied
        _rls().apply_rls(c, unset_mode="system")
    with eng.begin() as c:
        c.execute(sa.text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        c.execute(sa.text("DELETE FROM alembic_version"))
        c.execute(sa.text(f"INSERT INTO alembic_version VALUES ('{PARENT}')"))
    yield eng
    eng.dispose()


@pg
def test_pg_lock_modes_in_flight_and_measured_hold(pg_engine):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    eng = pg_engine
    conn = eng.connect()
    tx = conn.begin()
    started = time.perf_counter()
    with Operations.context(MigrationContext.configure(conn)):
        _module().upgrade()
    applied_ms = round((time.perf_counter() - started) * 1000, 2)
    with eng.connect() as probe:
        modes = probe.execute(sa.text(
            "SELECT c.relname, l.mode FROM pg_locks l JOIN pg_class c ON c.oid = l.relation "
            "WHERE c.relkind = 'r' AND l.granted AND l.pid <> pg_backend_pid() ORDER BY 1, 2")).fetchall()
        probe.execute(sa.text("SET statement_timeout = '1000ms'"))
        probe.execute(sa.text("SELECT set_config('app.rls_mode', 'system', true)"))
        readable = probe.execute(sa.text("SELECT count(*) FROM payslip_items")).scalar()
        probe.rollback()
    tx.commit()
    conn.close()
    held_ms = round((time.perf_counter() - started) * 1000, 2)
    print(f"\nMEASURED: DDL applied in {applied_ms} ms; locks held until commit ({held_ms} ms): "
          f"{sorted({tuple(m) for m in modes})}; payslip_items readable={readable is not None}")
    exclusive = {r for r, m in modes if m == "AccessExclusiveLock"}
    assert exclusive <= {DOCS, RELEASES, ACCESS}, exclusive          # only the Mexican CFDI tables
    shared = {"payslip_items", "payroll_employees", "organizations", "users", "payroll_runs"}
    assert not ({r for r, m in modes if r in shared} & exclusive)
    assert readable is not None and held_ms < 5000
    with eng.connect() as c:
        flags = c.execute(sa.text(f"SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = '{ACCESS}'")).one()
        worker, _tenant = _rls().classify(c)
    assert tuple(flags) == (True, True) and worker.get(ACCESS) == "org"
    _run(eng, "upgrade")                                            # guarded re-run is a no-op
    _run(eng, "downgrade")
    assert ACCESS not in _tables(eng) and not (DOC_NEW & _cols(eng, DOCS))


@pg
def test_pg_access_log_is_append_only(pg_engine):
    eng = pg_engine
    _run(eng, "upgrade")
    from sqlalchemy.orm import Session

    from app.modules.organizations.models import Organization

    with Session(eng) as s:
        s.execute(sa.text("SELECT set_config('app.rls_mode', 'system', true)"))
        o = Organization(organization_name="o", organization_code="LCPG", workspace_type="EVALUATION")
        s.add(o)
        s.commit()
        org = o.id
    with eng.begin() as c:
        c.execute(sa.text("SELECT set_config('app.rls_mode', 'system', true)"))
        c.execute(sa.text(f"INSERT INTO {ACCESS} (organization_id, event_type, artifact, channel) "
                          "VALUES (:o, 'VIEWED', 'RECIBO_VIEW', 'API')"), {"o": org})
    for stmt in (f"UPDATE {ACCESS} SET channel = 'UI'", f"DELETE FROM {ACCESS}"):
        with pytest.raises(sa.exc.DBAPIError, match="append-only"):
            with eng.begin() as c:
                c.execute(sa.text("SELECT set_config('app.rls_mode', 'system', true)"))
                c.execute(sa.text(stmt))


@pg
def test_pg_a_writer_on_cfdi_documents_makes_it_fail_fast(pg_engine):
    eng = pg_engine
    holder = eng.connect()
    tx = holder.begin()
    holder.execute(sa.text(f"LOCK TABLE {DOCS} IN ROW EXCLUSIVE MODE"))          # an in-flight CFDI write
    started = time.monotonic()
    with pytest.raises(sa.exc.OperationalError, match="lock timeout"):
        _run(eng, "upgrade")
    elapsed = time.monotonic() - started
    tx.rollback()
    holder.close()
    print(f"\nMEASURED: with a writer on {DOCS} the upgrade gave up after {elapsed:.2f} s")
    assert 4 <= elapsed < 15 and ACCESS not in _tables(eng) and not (DOC_NEW & _cols(eng, DOCS))
    _run(eng, "upgrade")
    assert ACCESS in _tables(eng)


@pg
def test_pg_real_cli_path_and_schema_drift(pg_engine):
    env = {**os.environ, "PAYROLL_DATABASE_URL": PG_URL, "DATABASE_URL": PG_URL, "PYTHONIOENCODING": "utf-8",
           "PAYROLL_DB_SSL_MODE": "disable"}
    up = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env,
                        capture_output=True, text=True, timeout=120)
    assert up.returncode == 0, up.stderr[-2000:]
    cur = subprocess.run([sys.executable, "-m", "alembic", "current"], cwd=BACKEND, env=env, capture_output=True,
                         text=True, timeout=120)
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    (head,) = script.get_heads()
    assert head in cur.stdout, cur.stdout + cur.stderr[-500:]
    assert REVISION in {rev.revision for rev in script.walk_revisions("base", head)}
    drift = subprocess.run([sys.executable, "-m", "scripts.check_schema_drift"], cwd=BACKEND, env=env,
                           capture_output=True, text=True, timeout=120)
    assert drift.returncode == 0, drift.stdout[-2000:] + drift.stderr[-2000:]


def test_deploy_drift_filter_explains_every_object():
    """scripts/drift_pending_filter reads exactly this migration's table and columns."""
    from scripts.drift_pending_filter import pending_objects
    from tests._mx_lifecycle_pending import MX_LIFECYCLE_COLUMNS, MX_LIFECYCLE_TABLES

    here = os.getcwd()
    os.chdir(BACKEND)
    try:
        tables, columns = pending_objects(PARENT)
    finally:
        os.chdir(here)
    # After the branch merge, pending_objects(PARENT) also includes the
    # Poland and payslip-template migrations on the other side of the merge.
    # Keep this test focused on ensuring the Mexico lifecycle objects remain
    # covered by the deploy drift filter.
    assert MX_LIFECYCLE_TABLES <= tables
    assert all(expected <= columns.get(table, set()) for table, expected in MX_LIFECYCLE_COLUMNS.items())
