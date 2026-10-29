"""Mexico final mile migration d3f8b2a6c1e9 (mx_final_mile_m20) — the programme's
one revision: payroll_mx_decisions (X1, platform), payroll_mx_parallel_imports
(X4, TENANT) and payroll_mx_parallel_differences (X4, WORKER).

SQLite (always): guarded, idempotent upgrade / downgrade; no other table touched.

PostgreSQL (MX_PG6_TEST_URL → a THROWAWAY database on 127.0.0.1, else skipped):
  - in flight (DDL applied, not committed): no existing table is locked
    exclusively; organizations / payroll_runs / payroll_employees take SHARE ROW
    EXCLUSIVE (the X4 foreign keys): reads continue, writes wait;
  - lock_timeout is set before any DDL, and a writer makes it fail fast;
  - row-level security on the two X4 tables only, with the predicate
    d7f9b1c3e5a6 derives (and none on the platform decisions table);
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
IMPORTS, DIFFS = "payroll_mx_parallel_imports", "payroll_mx_parallel_differences"
NEW_TABLES = (TABLE, IMPORTS, DIFFS)


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
    assert mod.NEW_TABLES == NEW_TABLES
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
    assert not (set(NEW_TABLES) & others)
    for _ in range(2):
        _run(eng, "upgrade")
    assert _tables(eng) == others | set(NEW_TABLES)
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
def test_pg_in_flight_reads_continue_writes_wait_nothing_exclusive(pg_engine):
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
                    probe.execute(sa.text("SELECT count(*) FROM payslip_items")).scalar(),
                    probe.execute(sa.text("SELECT count(*) FROM payroll_employees")).scalar())
        probe.rollback()
        write_waits = False
        try:
            probe.execute(sa.text("LOCK TABLE payroll_runs IN ROW EXCLUSIVE MODE NOWAIT"))
        except sa.exc.OperationalError:
            write_waits = True
        probe.rollback()
    tx.rollback()
    conn.close()
    held_ms = round((time.perf_counter() - started) * 1000, 2)
    print(f"\nMEASURED in flight: locks = {[tuple(m) for m in modes]}; lock_timeout = {timeout}; ~{held_ms} ms")
    held = {(r, m) for r, m in modes}
    assert timeout == "5s"
    assert {r for r, m in modes if m == "AccessExclusiveLock"} <= set(NEW_TABLES)
    assert {("organizations", "ShareRowExclusiveLock"), ("payroll_runs", "ShareRowExclusiveLock"),
            ("payroll_employees", "ShareRowExclusiveLock")} <= held
    assert not [r for r, m in modes if r in ("payslip_items", "users")]       # never referenced
    assert readable == (0, 0, 0) and write_waits
    assert not (set(NEW_TABLES) & _tables(eng))                               # rolled back: nothing applied


@pg
def test_pg_a_writer_on_payroll_runs_makes_it_fail_fast(pg_engine):
    eng = pg_engine
    holder = eng.connect()
    tx = holder.begin()
    holder.execute(sa.text("LOCK TABLE payroll_runs IN ROW EXCLUSIVE MODE"))      # an in-flight payroll write
    started = time.monotonic()
    with pytest.raises(sa.exc.OperationalError, match="lock timeout"):
        _run(eng, "upgrade")
    elapsed = time.monotonic() - started
    tx.rollback()
    holder.close()
    print(f"\nMEASURED: with a writer on payroll_runs the upgrade gave up after {elapsed:.2f} s")
    assert 4 <= elapsed < 15 and not (set(NEW_TABLES) & _tables(eng))   # one transaction: nothing half-applied


@pg
def test_pg_rls_on_the_x4_tables_only_with_the_derived_predicate(pg_engine):
    eng = pg_engine
    _run(eng, "upgrade")
    with eng.connect() as c:
        for table in (IMPORTS, DIFFS):
            flags = c.execute(sa.text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                                      "WHERE relname = :t"), {"t": table}).one()
            policies = c.execute(sa.text("SELECT policyname FROM pg_policies WHERE tablename = :t"),
                                 {"t": table}).scalars().all()
            assert tuple(flags) == (True, True) and policies == [_rls().POLICY], table
        assert c.execute(sa.text("SELECT count(*) FROM pg_policies WHERE tablename = :t"), {"t": TABLE}).scalar() == 0
        worker, tenant = _rls().classify(c)
    assert IMPORTS in tenant and worker.get(DIFFS) == "org"                  # the predicates d7f9 derives
    _run(eng, "upgrade")                                                      # guarded re-run is a no-op
    _run(eng, "downgrade")
    assert not (set(NEW_TABLES) & _tables(eng))


@pg
def test_pg_real_cli_path_and_schema_drift(pg_engine):
    env = {**os.environ, "PAYROLL_DATABASE_URL": PG_URL, "DATABASE_URL": PG_URL, "PYTHONIOENCODING": "utf-8",
           "PAYROLL_DB_SSL_MODE": "disable"}
    up = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env,
                        capture_output=True, text=True, timeout=120)
    assert up.returncode == 0, up.stderr[-2000:]
    assert set(NEW_TABLES) <= _tables(pg_engine)
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    (head,) = script.get_heads()
    # The database is at the repository head (merge 92c67cab49fc joins South Africa's chain,
    # which also grows from c7d2e9a4f1b6), and this revision is in its history.
    assert REVISION in {rev.revision for rev in script.walk_revisions("base", head)}
    with pg_engine.connect() as c:
        assert c.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() == head
        policies = c.execute(sa.text("SELECT count(*) FROM pg_policies WHERE tablename = :t"), {"t": TABLE}).scalar()
    assert policies == 0                                                      # platform table: no RLS policy
    drift = subprocess.run([sys.executable, "-m", "scripts.check_schema_drift"], cwd=BACKEND, env=env,
                           capture_output=True, text=True, timeout=120)
    assert drift.returncode == 0, drift.stdout[-2000:] + drift.stderr[-2000:]
