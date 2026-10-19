"""Mexico Phase 6 migration c4f7a2d9e6b1 (mx_run_m4) — plan §5.

SQLite (always): guarded, idempotent upgrade/downgrade; existing payslip /
run rows untouched.

PostgreSQL (only when MX_PG6_TEST_URL points at a THROWAWAY database on
127.0.0.1 — skipped otherwise): the migration is driven exactly as
alembic/env.py drives it (one MigrationContext transaction), and must:
  - create the seven tables first, then commit (autocommit_block), then run
    the two shared-table ALTERs LAST, each in its own transaction;
  - hold each ACCESS EXCLUSIVE lock only for its own statement — measured
    and printed;
  - never hold payslip_items while waiting for payroll_runs (a third
    connection reads and row-locks payslip_items during that wait);
  - fail after ~5 s on a held lock, nothing half-applied on that table; a
    re-run then completes (guarded);
  - leave other countries' rows byte-identical; pass the real CLI path
    (env.py) and check_schema_drift."""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import sqlalchemy as sa

REVISION, PARENT = "c4f7a2d9e6b1", "b7a1c9e3d5f2"
BACKEND = Path(__file__).resolve().parents[1]
NEW_TABLES = ("payroll_mx_preflight_exceptions", "payroll_mx_imss_branch_lines", "payroll_mx_isn_liabilities",
              "payroll_mx_sbc_history", "payroll_mx_variable_accumulators", "payroll_mx_benefit_accruals",
              "payroll_mx_approved_hours")


def _module():
    import importlib.util

    path = next((BACKEND / "alembic" / "versions").glob(f"{REVISION}_*.py"))
    spec = importlib.util.spec_from_file_location("mx_run_m4", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(engine, fn):
    """PostgreSQL exactly as env.py: a connection, a MigrationContext and its
    own transaction (autocommit_block needs Alembic to own it). SQLite (no
    autocommit block, non-transactional DDL) inside one engine transaction."""
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


def _cols(engine, table):
    return {c["name"] for c in sa.inspect(engine).get_columns(table)}


def _tables(engine):
    return set(sa.inspect(engine).get_table_names())


def _seed(engine):
    """An NL run + payslip with a snapshot that must survive byte-identical."""
    from sqlalchemy.orm import Session

    from app.modules.organizations.models import Organization
    from app.modules.payroll.models import PayrollEmployee

    with Session(engine) as s:
        org = Organization(organization_name="o", organization_code="M4O", workspace_type="EVALUATION")
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
                          "country_code, status, nl_calculation_snapshot) VALUES (:r, :e, :o, 'x', 'NL', 'Pending', :snap)"),
                  {"r": run_id, "e": ids[1], "o": ids[0], "snap": json.dumps({"keep": [1, "a"]})})


def _rows(engine):
    with engine.connect() as c:
        items = c.execute(sa.text("SELECT id, country_code, CAST(nl_calculation_snapshot AS TEXT) FROM payslip_items "
                                  "ORDER BY id")).fetchall()
        runs = c.execute(sa.text("SELECT id, status, pay_date FROM payroll_runs ORDER BY id")).fetchall()
    return items, runs


def test_revision_links():
    mod = _module()
    assert (mod.revision, mod.down_revision) == (REVISION, PARENT)
    assert mod.NEW_TABLES == NEW_TABLES


# ── SQLite ────────────────────────────────────────────────────────────────

@pytest.fixture()
def sqlite_engine(tmp_path):
    import app.modules.payroll.models  # noqa: F401
    from app.database import Base

    eng = sa.create_engine(f"sqlite:///{tmp_path / 'm4.db'}")
    Base.metadata.create_all(eng)
    _run(eng, "downgrade")                                         # start from the pre-m4 schema
    return eng


def test_sqlite_upgrade_downgrade_idempotent_and_other_rows_untouched(sqlite_engine):
    eng = sqlite_engine
    assert not (set(NEW_TABLES) & _tables(eng)) and "mx_calculation_snapshot" not in _cols(eng, "payslip_items")
    _seed(eng)
    before = _rows(eng)
    for _ in range(2):
        _run(eng, "upgrade")
    assert set(NEW_TABLES) <= _tables(eng)
    assert "mx_calculation_snapshot" in _cols(eng, "payslip_items")
    assert {"mx_approval_fingerprint", "mx_run_type"} <= _cols(eng, "payroll_runs")
    assert "salary_days_convention" in _cols(eng, "payroll_mx_labor_policies")
    assert _rows(eng) == before
    for _ in range(2):
        _run(eng, "downgrade")
    assert not (set(NEW_TABLES) & _tables(eng)) and _rows(eng) == before


# ── PostgreSQL (throwaway server only) ────────────────────────────────────

PG_URL = os.getenv("MX_PG6_TEST_URL")
pg = pytest.mark.skipif(not PG_URL, reason="MX_PG6_TEST_URL not set (throwaway PostgreSQL only)")
RESULTS = {}


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
def test_pg_order_and_measured_lock_hold_times(pg_engine):
    eng = pg_engine
    before = _rows(eng)
    events = []

    @sa.event.listens_for(eng, "before_cursor_execute")
    def _before(conn, cursor, statement, params, context, executemany):
        events.append(["start", time.perf_counter(), " ".join(statement.split())])

    @sa.event.listens_for(eng, "after_cursor_execute")
    def _after(conn, cursor, statement, params, context, executemany):
        events.append(["end", time.perf_counter(), " ".join(statement.split())])

    _run(eng, "upgrade")
    sa.event.remove(eng, "before_cursor_execute", _before)
    sa.event.remove(eng, "after_cursor_execute", _after)
    stmts = [e[2] for e in events if e[0] == "start"]

    def first(prefix):
        return next(i for i, s in enumerate(stmts) if s.startswith(prefix))

    creates = [first(f"CREATE TABLE {t}") for t in NEW_TABLES]
    alter_items = [i for i, s in enumerate(stmts) if s.startswith("ALTER TABLE payslip_items")]
    alter_runs = [i for i, s in enumerate(stmts) if s.startswith("ALTER TABLE payroll_runs")]
    assert len(alter_items) == 1 and len(alter_runs) == 1             # one ALTER per shared table
    assert stmts[0] == "SET LOCAL lock_timeout = '5s'"
    assert max(creates) < alter_items[0] < alter_runs[0]             # tables first, shared ALTERs last
    assert first("ALTER TABLE payroll_mx_labor_policies") < alter_items[0]
    assert stmts.index("SET lock_timeout = '5s'") < alter_items[0]   # session timeout inside the autocommit block
    assert stmts[-1 if stmts[-1].startswith("RESET") else stmts.index("RESET lock_timeout")] == "RESET lock_timeout"
    for i in alter_items + alter_runs:
        assert "DEFAULT" not in stmts[i].upper() and "NOT NULL" not in stmts[i].upper()

    # In the autocommit block each ALTER is its own transaction: its ACCESS
    # EXCLUSIVE lock is held exactly while the statement executes.
    def held_ms(prefix):
        start = next(e[1] for e in events if e[0] == "start" and e[2].startswith(prefix))
        end = next(e[1] for e in events if e[0] == "end" and e[2].startswith(prefix))
        return round((end - start) * 1000, 2)

    RESULTS["payslip_items_exclusive_ms"] = held_ms("ALTER TABLE payslip_items")
    RESULTS["payroll_runs_exclusive_ms"] = held_ms("ALTER TABLE payroll_runs")
    print(f"\nMEASURED lock hold: payslip_items ACCESS EXCLUSIVE {RESULTS['payslip_items_exclusive_ms']} ms; "
          f"payroll_runs ACCESS EXCLUSIVE {RESULTS['payroll_runs_exclusive_ms']} ms")
    assert RESULTS["payslip_items_exclusive_ms"] < 1000 and RESULTS["payroll_runs_exclusive_ms"] < 1000
    assert _rows(eng) == before
    with eng.connect() as c:
        assert c.execute(sa.text("SELECT count(*) FROM payslip_items WHERE mx_calculation_snapshot IS NOT NULL")).scalar() == 0
        assert c.execute(sa.text("SELECT count(*) FROM payroll_runs WHERE mx_run_type IS NOT NULL "
                                 "OR mx_approval_fingerprint IS NOT NULL")).scalar() == 0
    _run(eng, "upgrade")                                               # guarded re-run is a no-op
    _run(eng, "downgrade")
    assert not (set(NEW_TABLES) & _tables(eng)) and _rows(eng) == before


@pg
def test_pg_payslip_items_lock_is_released_while_payroll_runs_is_waited_for(pg_engine):
    eng = pg_engine
    holder = eng.connect()
    tx = holder.begin()
    holder.execute(sa.text("LOCK TABLE payroll_runs IN ACCESS SHARE MODE"))       # a long payroll read
    probe = {}

    def _probe():
        time.sleep(2.0)                                                            # the ALTER on payroll_runs waits now
        with eng.connect() as c:
            c.execute(sa.text("SET statement_timeout = '1000ms'"))
            t0 = time.perf_counter()
            probe["read"] = c.execute(sa.text("SELECT count(*) FROM payslip_items")).scalar()
            c.execute(sa.text("LOCK TABLE payslip_items IN ROW EXCLUSIVE MODE NOWAIT"))       # what writes take
            c.rollback()
            probe["ms"] = round((time.perf_counter() - t0) * 1000, 2)
            probe["locks"] = c.execute(sa.text(
                "SELECT c.relname, l.mode FROM pg_locks l JOIN pg_class c ON c.oid = l.relation "
                "WHERE c.relname IN ('payslip_items', 'payroll_runs') AND l.mode = 'AccessExclusiveLock' "
                "AND l.granted")).fetchall()

    t = threading.Thread(target=_probe)
    t.start()
    started = time.monotonic()
    with pytest.raises(sa.exc.OperationalError, match="lock timeout"):
        _run(eng, "upgrade")
    elapsed = time.monotonic() - started
    t.join()
    tx.rollback()
    holder.close()
    print(f"\nMEASURED: upgrade gave up after {elapsed:.2f} s; during the payroll_runs wait payslip_items was "
          f"readable and row-lockable in {probe.get('ms')} ms; granted ACCESS EXCLUSIVE locks then: "
          f"{probe.get('locks')}")
    assert 4 <= elapsed < 15, elapsed
    assert probe.get("read") is not None and probe.get("locks") == []
    assert "mx_calculation_snapshot" in _cols(eng, "payslip_items")              # its own transaction committed
    assert not ({"mx_approval_fingerprint", "mx_run_type"} & _cols(eng, "payroll_runs"))
    _run(eng, "upgrade")                                                          # re-run completes the rest
    assert {"mx_approval_fingerprint", "mx_run_type"} <= _cols(eng, "payroll_runs")


@pg
def test_pg_a_held_lock_on_payslip_items_fails_fast_with_neither_column_added(pg_engine):
    eng = pg_engine
    holder = eng.connect()
    tx = holder.begin()
    holder.execute(sa.text("LOCK TABLE payslip_items IN ACCESS SHARE MODE"))
    started = time.monotonic()
    with pytest.raises(sa.exc.OperationalError, match="lock timeout"):
        _run(eng, "upgrade")
    elapsed = time.monotonic() - started
    tx.rollback()
    holder.close()
    assert 4 <= elapsed < 15, elapsed
    assert "mx_calculation_snapshot" not in _cols(eng, "payslip_items")
    assert not ({"mx_approval_fingerprint", "mx_run_type"} & _cols(eng, "payroll_runs"))
    assert set(NEW_TABLES) <= _tables(eng)                                       # step 1 committed; re-run is guarded
    _run(eng, "upgrade")
    assert "mx_calculation_snapshot" in _cols(eng, "payslip_items")


@pg
def test_pg_real_cli_path_and_schema_drift(pg_engine):
    env = {**os.environ, "PAYROLL_DATABASE_URL": PG_URL, "DATABASE_URL": PG_URL, "PYTHONIOENCODING": "utf-8",
           "PAYROLL_DB_SSL_MODE": "disable"}                     # the throwaway local server has no TLS
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
