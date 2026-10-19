"""Mexico Phase 7 migration d8b3e5f1a2c7 (mx_cfdi_m5) — new tables only.

SQLite (always): guarded, idempotent upgrade / downgrade; existing payslip and
run rows untouched; no shared-table column added.

PostgreSQL (MX_PG6_TEST_URL → a THROWAWAY database on 127.0.0.1, else skipped):
  - the FK lock is MEASURED: from the first statement that references
    payslip_items to the commit of the migration transaction (alembic/env.py
    holds every lock until then), printed;
  - the lock MODE is proven in flight: with the migration's DDL applied but not
    committed, pg_locks shows SHARE ROW EXCLUSIVE (not ACCESS EXCLUSIVE) on
    payslip_items / payroll_runs, a third connection still READS payslip_items,
    and a writer's ROW EXCLUSIVE lock waits (NOWAIT fails);
  - a writer holding payslip_items makes the upgrade fail fast (~5 s) with
    nothing created; a re-run completes;
  - the real CLI (env.py) and check_schema_drift pass."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import sqlalchemy as sa

REVISION, PARENT = "d8b3e5f1a2c7", "c4f7a2d9e6b1"
BACKEND = Path(__file__).resolve().parents[1]
NEW_TABLES = ("payroll_mx_cfdi_documents", "payroll_mx_cfdi_outbox_items", "payroll_mx_cfdi_events")


def _module():
    import importlib.util

    path = next((BACKEND / "alembic" / "versions").glob(f"{REVISION}_*.py"))
    spec = importlib.util.spec_from_file_location("mx_cfdi_m5", path)
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


def _seed(engine):
    from sqlalchemy.orm import Session

    from app.modules.organizations.models import Organization
    from app.modules.payroll.models import PayrollEmployee

    with Session(engine) as s:
        org = Organization(organization_name="o", organization_code="M5O", workspace_type="EVALUATION")
        s.add(org)
        s.flush()
        emp = PayrollEmployee(organization_id=org.id, employee_code="E1", name="x", country_code="NL")
        s.add(emp)
        s.flush()
        ids = (org.id, emp.id)
        s.commit()
    with engine.begin() as c:
        c.execute(sa.text("INSERT INTO payroll_runs (organization_id, period_label, period_start, period_end, "
                          "pay_date, status) VALUES (:o, 'P', '2026-06-01', '2026-06-30', '2026-06-30', 'Draft')"),
                  {"o": ids[0]})
        run_id = c.execute(sa.text("SELECT max(id) FROM payroll_runs")).scalar()
        c.execute(sa.text("INSERT INTO payslip_items (payroll_run_id, employee_id, organization_id, employee_name, "
                          "country_code, status, nl_calculation_snapshot) VALUES (:r, :e, :o, 'x', 'NL', 'Pending', :s)"),
                  {"r": run_id, "e": ids[1], "o": ids[0], "s": json.dumps({"keep": 1})})


def _rows(engine):
    with engine.connect() as c:
        return (c.execute(sa.text("SELECT id, country_code, CAST(nl_calculation_snapshot AS TEXT) FROM payslip_items "
                                  "ORDER BY id")).fetchall(),
                c.execute(sa.text("SELECT id, status FROM payroll_runs ORDER BY id")).fetchall())


def test_revision_links():
    mod = _module()
    assert (mod.revision, mod.down_revision) == (REVISION, PARENT)
    assert mod.NEW_TABLES == NEW_TABLES


@pytest.fixture()
def sqlite_engine(tmp_path):
    import app.modules.payroll.models  # noqa: F401
    from app.database import Base

    eng = sa.create_engine(f"sqlite:///{tmp_path / 'm5.db'}")
    Base.metadata.create_all(eng)
    _run(eng, "downgrade")
    return eng


def test_sqlite_upgrade_downgrade_idempotent_new_tables_only(sqlite_engine):
    eng = sqlite_engine
    assert not (set(NEW_TABLES) & _tables(eng))
    _seed(eng)
    before, items_cols, runs_cols = _rows(eng), _cols(eng, "payslip_items"), _cols(eng, "payroll_runs")
    for _ in range(2):
        _run(eng, "upgrade")
    assert set(NEW_TABLES) <= _tables(eng)
    assert _cols(eng, "payslip_items") == items_cols and _cols(eng, "payroll_runs") == runs_cols
    assert _rows(eng) == before
    for _ in range(2):
        _run(eng, "downgrade")
    assert not (set(NEW_TABLES) & _tables(eng)) and _rows(eng) == before


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
    _seed(eng)
    with eng.begin() as c:
        c.execute(sa.text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        c.execute(sa.text("DELETE FROM alembic_version"))
        c.execute(sa.text(f"INSERT INTO alembic_version VALUES ('{PARENT}')"))
    yield eng
    eng.dispose()


@pg
def test_pg_measured_fk_lock_hold(pg_engine):
    eng = pg_engine
    before, items_cols = _rows(eng), _cols(eng, "payslip_items")
    marks = {}

    @sa.event.listens_for(eng, "before_cursor_execute")
    def _before(conn, cursor, statement, *a):
        st = " ".join(statement.split())
        if "first_fk" not in marks and st.startswith("CREATE TABLE payroll_mx_cfdi_documents"):
            marks["first_fk"] = time.perf_counter()
        marks.setdefault("statements", []).append(st)

    @sa.event.listens_for(eng, "commit")
    def _commit(conn):
        marks.setdefault("commit", time.perf_counter())

    _run(eng, "upgrade")
    sa.event.remove(eng, "before_cursor_execute", _before)
    sa.event.remove(eng, "commit", _commit)
    held_ms = round((marks["commit"] - marks["first_fk"]) * 1000, 2)
    print(f"\nMEASURED: SHARE ROW EXCLUSIVE on payslip_items / payroll_runs / payroll_employees held {held_ms} ms "
          f"(first FK-creating statement -> migration commit)")
    stmts = marks["statements"]
    assert stmts[0] == "SET LOCAL lock_timeout = '5s'"
    assert not [s for s in stmts if s.startswith(("ALTER TABLE payslip_items", "ALTER TABLE payroll_runs"))]
    assert held_ms < 2000
    assert _rows(eng) == before and _cols(eng, "payslip_items") == items_cols
    _run(eng, "upgrade")                                            # guarded re-run is a no-op
    _run(eng, "downgrade")
    assert not (set(NEW_TABLES) & _tables(eng)) and _rows(eng) == before


@pg
def test_pg_lock_mode_in_flight_reads_continue_writes_wait(pg_engine):
    """The DDL applied in an open transaction (not committed): which locks it
    holds, and what other sessions can still do."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    eng = pg_engine
    conn = eng.connect()
    tx = conn.begin()
    with Operations.context(MigrationContext.configure(conn)):
        _module().upgrade()
    with eng.connect() as probe:
        modes = probe.execute(sa.text(
            "SELECT c.relname, l.mode FROM pg_locks l JOIN pg_class c ON c.oid = l.relation "
            "WHERE c.relname IN ('payslip_items', 'payroll_runs', 'payroll_employees') AND l.granted "
            "AND l.pid <> pg_backend_pid() ORDER BY 1, 2")).fetchall()
        probe.execute(sa.text("SET statement_timeout = '1000ms'"))
        readable = probe.execute(sa.text("SELECT count(*) FROM payslip_items")).scalar()
        probe.rollback()
        write_waits = False
        try:
            probe.execute(sa.text("LOCK TABLE payslip_items IN ROW EXCLUSIVE MODE NOWAIT"))
        except sa.exc.OperationalError:
            write_waits = True
        probe.rollback()
    tx.rollback()
    conn.close()
    print(f"\nMEASURED in flight: locks held by the migration = {[tuple(m) for m in modes]}; "
          f"payslip_items readable (count={readable}); a writer's ROW EXCLUSIVE NOWAIT refused = {write_waits}")
    held = {(r, m) for r, m in modes}
    assert ("payslip_items", "ShareRowExclusiveLock") in held and ("payroll_runs", "ShareRowExclusiveLock") in held
    assert not [m for r, m in modes if m == "AccessExclusiveLock" and r in ("payslip_items", "payroll_runs")]
    assert readable == 1 and write_waits
    assert not (set(NEW_TABLES) & _tables(eng))                     # rolled back: nothing applied


@pg
def test_pg_a_writer_on_payslip_items_makes_it_fail_fast(pg_engine):
    eng = pg_engine
    holder = eng.connect()
    tx = holder.begin()
    holder.execute(sa.text("LOCK TABLE payslip_items IN ROW EXCLUSIVE MODE"))     # an in-flight payroll write
    started = time.monotonic()
    with pytest.raises(sa.exc.OperationalError, match="lock timeout"):
        _run(eng, "upgrade")
    elapsed = time.monotonic() - started
    tx.rollback()
    holder.close()
    print(f"\nMEASURED: with a writer on payslip_items the upgrade gave up after {elapsed:.2f} s")
    assert 4 <= elapsed < 15 and not (set(NEW_TABLES) & _tables(eng))   # one transaction: nothing half-applied
    _run(eng, "upgrade")
    assert set(NEW_TABLES) <= _tables(eng)


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
    # The database is at the repository head, and this revision is in its history
    # (a later phase's migration may sit above it).
    assert head in cur.stdout, cur.stdout + cur.stderr[-500:]
    assert REVISION in {rev.revision for rev in script.walk_revisions("base", head)}
    drift = subprocess.run([sys.executable, "-m", "scripts.check_schema_drift"], cwd=BACKEND, env=env,
                           capture_output=True, text=True, timeout=120)
    assert drift.returncode == 0, drift.stdout[-2000:] + drift.stderr[-2000:]
