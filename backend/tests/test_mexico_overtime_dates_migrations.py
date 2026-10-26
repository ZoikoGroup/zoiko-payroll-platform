"""Mexico Phase 11c migration b9f3d5a1c7e2 (mx_overtime_dates_m18) — one nullable
column on payroll_mx_approved_hours.

SQLite (always): guarded, idempotent upgrade / downgrade; existing rows kept.

PostgreSQL (MX_PG6_TEST_URL → a THROWAWAY database on 127.0.0.1, else skipped):
  - in flight (DDL applied, not committed): ACCESS EXCLUSIVE on
    payroll_mx_approved_hours only — no other table locked exclusively, and
    organizations / payroll_employees still readable;
  - a reader holding payroll_mx_approved_hours makes the upgrade fail fast
    (~5 s) with nothing applied; a re-run completes;
  - the table keeps its ZP-PRIV row-level-security policy;
  - the real CLI (env.py) and check_schema_drift pass."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import sqlalchemy as sa

REVISION, PARENT = "b9f3d5a1c7e2", "a8e4c1f7d3b5"
BACKEND = Path(__file__).resolve().parents[1]
TABLE, COLUMN = "payroll_mx_approved_hours", "overtime_dates"


def _module():
    import importlib.util

    path = next((BACKEND / "alembic" / "versions").glob(f"{REVISION}_*.py"))
    spec = importlib.util.spec_from_file_location("mx_overtime_dates_m18", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rls():
    import importlib.util

    path = BACKEND / "alembic" / "versions" / "d7f9b1c3e5a6_postgres_row_level_security.py"
    spec = importlib.util.spec_from_file_location("zp_rls_m18", path)
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


def _cols(engine):
    return {c["name"] for c in sa.inspect(engine).get_columns(TABLE)}


def _seed(engine):
    from sqlalchemy.orm import Session

    from app.modules.organizations.models import Organization
    from app.modules.payroll.models import PayrollEmployee

    with Session(engine) as s:
        org = Organization(organization_name="o", organization_code="M18O", workspace_type="EVALUATION")
        s.add(org)
        s.flush()
        emp = PayrollEmployee(organization_id=org.id, employee_code="E1", name="x", country_code="MX")
        s.add(emp)
        s.flush()
        ids = (org.id, emp.id)
        s.commit()
    with engine.begin() as c:
        c.execute(sa.text(f"INSERT INTO {TABLE} (organization_id, employee_id, week_start, ordinary_hours, "
                          "overtime_hours, sundays_worked, rest_days_worked, status) "
                          "VALUES (:o, :e, '2026-06-01', 40, 2, 0, 0, 'APPROVED')"), {"o": ids[0], "e": ids[1]})


def _rows(engine):
    with engine.connect() as c:
        if engine.dialect.name == "postgresql":
            c.execute(sa.text("SELECT set_config('app.rls_mode', 'system', false)"))
        return c.execute(sa.text(f"SELECT id, week_start, overtime_hours, status FROM {TABLE} ORDER BY id")).fetchall()


def test_revision_links():
    mod = _module()
    assert (mod.revision, mod.down_revision) == (REVISION, PARENT)
    assert mod.NEW_COLUMNS == ((TABLE, COLUMN),)


@pytest.fixture()
def sqlite_engine(tmp_path):
    import app.modules.payroll.models  # noqa: F401
    from app.database import Base

    eng = sa.create_engine(f"sqlite:///{tmp_path / 'm18.db'}")
    Base.metadata.create_all(eng)
    _run(eng, "downgrade")
    return eng


def test_sqlite_upgrade_downgrade_idempotent_rows_kept(sqlite_engine):
    eng = sqlite_engine
    assert COLUMN not in _cols(eng)
    _seed(eng)
    before = _rows(eng)
    for _ in range(2):
        _run(eng, "upgrade")
    assert COLUMN in _cols(eng) and _rows(eng) == before
    for _ in range(2):
        _run(eng, "downgrade")
    assert COLUMN not in _cols(eng) and _rows(eng) == before


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
    _seed(eng)
    with eng.begin() as c:
        c.execute(sa.text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        c.execute(sa.text("DELETE FROM alembic_version"))
        c.execute(sa.text(f"INSERT INTO alembic_version VALUES ('{PARENT}')"))
    yield eng
    eng.dispose()


def _policy(engine):
    with engine.connect() as c:
        return c.execute(sa.text("SELECT policyname, qual FROM pg_policies WHERE tablename = :t"), {"t": TABLE}).all()


@pg
def test_pg_lock_mode_in_flight_only_the_hours_table(pg_engine):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    eng = pg_engine
    policy = _policy(eng)
    conn = eng.connect()
    tx = conn.begin()
    started = time.perf_counter()
    with Operations.context(MigrationContext.configure(conn)):
        _module().upgrade()
    with eng.connect() as probe:
        modes = probe.execute(sa.text(
            "SELECT c.relname, l.mode FROM pg_locks l JOIN pg_class c ON c.oid = l.relation "
            "WHERE c.relkind = 'r' AND l.granted AND l.pid <> pg_backend_pid() ORDER BY 1, 2")).fetchall()
        probe.execute(sa.text("SET statement_timeout = '1000ms'"))
        probe.execute(sa.text("SELECT set_config('app.rls_mode', 'system', true)"))
        readable = (probe.execute(sa.text("SELECT count(*) FROM organizations")).scalar(),
                    probe.execute(sa.text("SELECT count(*) FROM payroll_employees")).scalar())
        probe.rollback()
    tx.rollback()
    conn.close()
    held_ms = round((time.perf_counter() - started) * 1000, 2)
    print(f"\nMEASURED in flight: locks = {[tuple(m) for m in modes]}; readable = {readable}; ~{held_ms} ms")
    exclusive = {r for r, m in modes if m == "AccessExclusiveLock"}
    assert exclusive == {TABLE}
    assert readable == (1, 1)
    assert COLUMN not in _cols(eng)                                 # rolled back: nothing applied
    _run(eng, "upgrade")
    assert COLUMN in _cols(eng) and _policy(eng) == policy           # the RLS policy is unchanged


@pg
def test_pg_a_reader_on_the_hours_table_makes_it_fail_fast(pg_engine):
    eng = pg_engine
    holder = eng.connect()
    tx = holder.begin()
    holder.execute(sa.text("SELECT set_config('app.rls_mode', 'system', true)"))
    holder.execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar()          # an in-flight read
    started = time.monotonic()
    with pytest.raises(sa.exc.OperationalError, match="lock timeout"):
        _run(eng, "upgrade")
    elapsed = time.monotonic() - started
    tx.rollback()
    holder.close()
    print(f"\nMEASURED: with a reader on {TABLE} the upgrade gave up after {elapsed:.2f} s")
    assert 4 <= elapsed < 15 and COLUMN not in _cols(eng)
    _run(eng, "upgrade")
    assert COLUMN in _cols(eng)


@pg
def test_pg_real_cli_path_and_schema_drift(pg_engine):
    env = {**os.environ, "PAYROLL_DATABASE_URL": PG_URL, "DATABASE_URL": PG_URL, "PYTHONIOENCODING": "utf-8",
           "PAYROLL_DB_SSL_MODE": "disable"}
    up = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env,
                        capture_output=True, text=True, timeout=120)
    assert up.returncode == 0, up.stderr[-2000:]
    drift = subprocess.run([sys.executable, "-m", "scripts.check_schema_drift"], cwd=BACKEND, env=env,
                           capture_output=True, text=True, timeout=120)
    assert drift.returncode == 0, drift.stdout[-2000:] + drift.stderr[-2000:]
