"""Mexico final mile migration d3f8b2a6c1e9 (mx_final_mile_m20) — one new platform
table, payroll_mx_decisions (X1).

SQLite (always): guarded, idempotent upgrade / downgrade; no other table touched.

PostgreSQL (MX_PG6_TEST_URL → a THROWAWAY database on 127.0.0.1, else skipped):
  - in flight (DDL applied, not committed): no existing table is locked
    exclusively (the table has no foreign key to a shared table); organizations
    and payslip_items still readable and writable;
  - lock_timeout is set before any DDL;
  - the real CLI (env.py) upgrades from c7d2e9a4f1b6 and check_schema_drift passes."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import sqlalchemy as sa

REVISION, PARENT = "d3f8b2a6c1e9", "c7d2e9a4f1b6"
BACKEND = Path(__file__).resolve().parents[1]
TABLE = "payroll_mx_decisions"


def _module():
    import importlib.util

    path = next((BACKEND / "alembic" / "versions").glob(f"{REVISION}_*.py"))
    spec = importlib.util.spec_from_file_location("mx_final_mile_m20", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rls():
    import importlib.util

    path = BACKEND / "alembic" / "versions" / "d7f9b1c3e5a6_postgres_row_level_security.py"
    spec = importlib.util.spec_from_file_location("zp_rls_m20", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(engine, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            with ctx.begin_transaction():
                getattr(_module(), fn)()
        if engine.dialect.name != "postgresql":
            conn.commit()


def _tables(engine):
    return set(sa.inspect(engine).get_table_names())


def test_revision_links():
    mod = _module()
    assert (mod.revision, mod.down_revision) == (REVISION, PARENT)
    assert mod.NEW_TABLES == (TABLE,)
    source = (next((BACKEND / "alembic" / "versions").glob(f"{REVISION}_*.py"))).read_text(encoding="utf-8")
    assert "ForeignKey(\"users" not in source and "apply_rls" not in source     # no shared lock, no RLS sweep


@pytest.fixture()
def sqlite_engine(tmp_path):
    import app.modules.payroll.models  # noqa: F401
    from app.database import Base

    eng = sa.create_engine(f"sqlite:///{tmp_path / 'm20.db'}")
    Base.metadata.create_all(eng)
    _run(eng, "downgrade")
    return eng


def test_sqlite_upgrade_downgrade_idempotent(sqlite_engine):
    eng = sqlite_engine
    others = _tables(eng)
    assert TABLE not in others
    for _ in range(2):
        _run(eng, "upgrade")
    assert _tables(eng) == others | {TABLE}
    cols = {c["name"] for c in sa.inspect(eng).get_columns(TABLE)}
    assert {"code", "version", "status", "chosen_option", "content_hash", "supersedes_id"} <= cols
    assert "organization_id" not in cols                                     # platform table, no tenant data
    for _ in range(2):
        _run(eng, "downgrade")
    assert _tables(eng) == others


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
        c.execute(sa.text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        c.execute(sa.text("DELETE FROM alembic_version"))
        c.execute(sa.text(f"INSERT INTO alembic_version VALUES ('{PARENT}')"))
    yield eng
    eng.dispose()


@pg
def test_pg_in_flight_no_existing_table_is_locked_exclusively(pg_engine):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    eng = pg_engine
    conn = eng.connect()
    tx = conn.begin()
    started = time.perf_counter()
    with Operations.context(MigrationContext.configure(conn)):
        _module().upgrade()
    timeout = conn.execute(sa.text("SHOW lock_timeout")).scalar()
    with eng.connect() as probe:
        modes = probe.execute(sa.text(
            "SELECT c.relname, l.mode FROM pg_locks l JOIN pg_class c ON c.oid = l.relation "
            "WHERE c.relkind = 'r' AND l.granted AND l.pid <> pg_backend_pid() ORDER BY 1, 2")).fetchall()
        probe.execute(sa.text("SET statement_timeout = '1000ms'"))
        probe.execute(sa.text("SELECT set_config('app.rls_mode', 'system', true)"))
        readable = (probe.execute(sa.text("SELECT count(*) FROM organizations")).scalar(),
                    probe.execute(sa.text("SELECT count(*) FROM payslip_items")).scalar())
        probe.rollback()
    tx.rollback()
    conn.close()
    held_ms = round((time.perf_counter() - started) * 1000, 2)
    print(f"\nMEASURED in flight: locks = {[tuple(m) for m in modes]}; lock_timeout = {timeout}; ~{held_ms} ms")
    assert timeout == "5s"
    assert {r for r, m in modes if m == "AccessExclusiveLock"} <= {TABLE}
    assert readable == (0, 0)
    assert TABLE not in _tables(eng)                                          # rolled back: nothing applied


@pg
def test_pg_real_cli_path_and_schema_drift(pg_engine):
    env = {**os.environ, "PAYROLL_DATABASE_URL": PG_URL, "DATABASE_URL": PG_URL, "PYTHONIOENCODING": "utf-8",
           "PAYROLL_DB_SSL_MODE": "disable"}
    up = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env,
                        capture_output=True, text=True, timeout=120)
    assert up.returncode == 0, up.stderr[-2000:]
    assert TABLE in _tables(pg_engine)
    with pg_engine.connect() as c:
        assert c.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() == REVISION
        policies = c.execute(sa.text("SELECT count(*) FROM pg_policies WHERE tablename = :t"), {"t": TABLE}).scalar()
    assert policies == 0                                                      # platform table: no RLS policy
    drift = subprocess.run([sys.executable, "-m", "scripts.check_schema_drift"], cwd=BACKEND, env=env,
                           capture_output=True, text=True, timeout=120)
    assert drift.returncode == 0, drift.stdout[-2000:] + drift.stderr[-2000:]
